"""
    The snapshot comparison, end to end and without an APIC.

    Two snapshot bundles are written in exactly the format execute_snapshot
    produces (an outer .tgz holding bundle.tgz and md5checksum.json), recorded
    as uploaded snapshots, and compared through the REST API. That runs the
    real background worker (app.models.aci.worker in its own process) and, when
    not serialized, the multiprocessing pool - the parts of the Python 3 port
    that upstream's tests never reached.
"""

import hashlib, io, json, logging, os, tarfile, time
import pytest

from app.models.aci.compare import Compare, CompareResults
from app.models.aci.definitions import Definitions
from app.models.aci.fabric import Fabric
from app.models.aci.managed_objects import ManagedObjects
from app.models.aci.snapshots import Snapshots

logger = logging.getLogger(__name__)

FABRIC = "fab1"
DEFINITION = "compare-test"

def bd(name, **attrs):
    a = {"dn": "topology/pod-1/node-%s/sys/bd-[%s]" % (attrs.pop("node", 101), name),
         "arpFlood": "no", "descr": ""}
    a.update(attrs)
    return {"testBridge": {"attributes": a}}

def vlan_obj(vlan, value):
    # no dn: it would differ with the vlan and be reported as a modification
    return {"testVlanObj": {"attributes": {"id": "vlan%s" % vlan, "value": value}}}

def vlan_ckt(vlan, vnid):
    return {"vlanCktEp": {"attributes": {"id": "%s" % vlan, "fabEncap": vnid,
            "dn": "topology/pod-1/node-101/sys/ctx-[vxlan-1]/bd-[vxlan-2]/vlan-[vlan-%s]" % vlan}}}

# snapshot 1 -> snapshot 2:
#   bd1 modified (arpFlood), bd2 equal, bd3 deleted, bd4 created,
#   every bridge gains an attribute snapshot 1 never had (ignored by default;
#   the attributes compared are taken from the first object in snapshot 2),
#   node 102 appears only in snapshot 2 (one created),
#   the vlan object moves from vlan5 to vlan7 but maps to the same VNID
S1 = {
    "101": {
        "testBridge": [bd("bd1"), bd("bd2", descr="same"), bd("bd3")],
        "testVlanObj": [vlan_obj(5, "x")],
        "vlanCktEp": [vlan_ckt(5, "vxlan-100")],
    },
}
S2 = {
    "101": {
        "testBridge": [bd("bd1", arpFlood="yes", newAttr="1"),
                       bd("bd2", descr="same", newAttr="1"), bd("bd4", newAttr="1")],
        "testVlanObj": [vlan_obj(7, "x")],
        "vlanCktEp": [vlan_ckt(7, "vxlan-100")],
    },
    "102": {
        "testBridge": [bd("bd9", node=102, newAttr="1")],
    },
}

def _add(tar, name, data):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))

def write_snapshot(directory, name, nodes, managed_objects):
    """ write a snapshot bundle as execute_snapshot does; return its path """
    inner = io.BytesIO()
    with tarfile.open(fileobj=inner, mode="w:gz") as t:
        _add(t, "./snapshot.json", json.dumps({"fabric": FABRIC}).encode())
        _add(t, "./definition.json", json.dumps({
            "definition": DEFINITION, "managed_objects": managed_objects}).encode())
        for node, classes in nodes.items():
            for classname, objects in classes.items():
                _add(t, "./node-%s/%s.json" % (node, classname), json.dumps(objects).encode())
    bundle = inner.getvalue()
    path = os.path.join(directory, name)
    with tarfile.open(path, mode="w:gz") as t:
        _add(t, "./bundle.tgz", bundle)
        _add(t, "./md5checksum.json", json.dumps(
            {"md5checksum": hashlib.md5(bundle).hexdigest()}).encode())
    return path

@pytest.fixture(scope="module")
def snapshots(app, tmp_path_factory):
    with app.app_context():
        directory = str(tmp_path_factory.mktemp("snapshots"))
        for cn, extra in (("testBridge", {}),
                          ("testVlanObj", {"key": "id", "remap": ["vlan"]}),
                          ("vlanCktEp", {"analyzer": "exclude"})):
            mo = ManagedObjects(classname=cn, description="test class %s" % cn, **extra)
            assert mo.save()
        d = Definitions(definition=DEFINITION, description="compare test",
                        managed_objects=["testBridge", "testVlanObj", "vlanCktEp"])
        assert d.save()
        managed_objects = d.get_managed_objects()
        f = Fabric(fabric=FABRIC)
        assert f.save()
        ids = []
        for i, nodes in enumerate((S1, S2)):
            s = Snapshots(fabric=FABRIC, definition=DEFINITION, description="s%s" % i)
            s.source = "upload"
            s.status = "complete"
            s.progress = 1.0
            s.nodes = sorted(nodes)
            s.filename = write_snapshot(directory, "s%s.tgz" % i, nodes, managed_objects)
            assert s.save()
            ids.append(s._id)
        return ids

def run_compare(app, snapshots, **options):
    """ create a comparison through the API and wait for the worker to finish """
    body = {"snapshot1": snapshots[0], "snapshot2": snapshots[1], "definition": DEFINITION}
    body.update(options)
    r = app.client.post("/api/aci/compare", data=json.dumps(body),
                        content_type="application/json")
    assert r.status_code == 200, r.data
    _id = json.loads(r.data)["_id"]
    deadline = time.time() + 60
    while time.time() < deadline:
        c = Compare.load(_id=_id)
        if c.status in ("complete", "error"): break
        time.sleep(0.25)
    assert c.status == "complete", "compare %s ended as %s: %s" % (_id, c.status, c.error)
    results = {}
    for o in CompareResults.read(compare_id=_id)["objects"]:
        results[(o["node_id"], o["classname"])] = o
    return c, results

@pytest.mark.parametrize("serialize", [True, False], ids=["serialized", "multiprocess"])
def test_compare_classifies_every_change(app, snapshots, serialize):
    c, results = run_compare(app, snapshots, serialize=serialize)
    bridge = results[(101, "testBridge")]["total"]
    assert (bridge["created"], bridge["modified"], bridge["deleted"], bridge["equal"]) == (1, 1, 1, 1)
    modified = results[(101, "testBridge")]["modified"][0]
    assert modified["key1"].endswith("bd-[bd1]")
    assert [m["attribute"] for m in modified["modified"]] == ["arpFlood"]
    assert (modified["modified"][0]["value1"], modified["modified"][0]["value2"]) == ("no", "yes")
    assert results[(102, "testBridge")]["total"]["created"] == 1
    # remapped: vlan5 and vlan7 carry the same VNID, so it is one unchanged object
    vlan = results[(101, "testVlanObj")]["total"]
    assert (vlan["created"], vlan["deleted"], vlan["equal"]) == (0, 0, 1)
    assert c.total == {"created": 2, "modified": 1, "deleted": 1, "equal": 2}
    assert [n["node_id"] for n in c.total_per_node] == [101, 102]

def test_compare_without_remap_sees_the_vlan_move(app, snapshots):
    _, results = run_compare(app, snapshots, serialize=True, remap=False)
    vlan = results[(101, "testVlanObj")]["total"]
    assert (vlan["created"], vlan["deleted"], vlan["equal"]) == (1, 1, 0)

def test_compare_can_report_new_attributes(app, snapshots):
    _, results = run_compare(app, snapshots, serialize=True, ignore_new_attributes=False)
    bridge = results[(101, "testBridge")]["total"]
    # the new attribute now counts: bd2 is modified too, and bd1 twice over
    assert (bridge["modified"], bridge["equal"]) == (2, 0)
    bd1 = [m for m in results[(101, "testBridge")]["modified"] if m["key1"].endswith("bd-[bd1]")][0]
    assert sorted(m["attribute"] for m in bd1["modified"]) == ["arpFlood", "newAttr"]
