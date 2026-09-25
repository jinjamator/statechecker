"""
    Single sign-on from the Synaptic portal (app/models/sso.py).

    A stand-in portal answers GET /api/aaa/whoami per bearer token, the way the
    Synaptic engine does, so every rule is checked through the real endpoint:
    who gets in, with which role, what is never taken over, and that the session
    it starts is an ordinary StateChecker session.
"""

import json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.models.rest import Role
from app.models.user import User

PORTAL = {
    "Bearer tok-alice": {"username": "alice@example.com", "roles": ["administrator", "task_x"]},
    "Bearer tok-bob": {"username": "bob-ops", "roles": ["operators"]},
    "Bearer tok-carol": {"username": "carol", "roles": []},
    # "admin" is a local StateChecker account (conftest creates it with a password)
    "Bearer tok-admin": {"username": "admin", "roles": ["administrator"]},
    "Bearer tok-local": {"username": "local", "roles": ["administrator"]},
    "Bearer tok-bad-name": {"username": "has space", "roles": []},
}

class Portal(BaseHTTPRequestHandler):
    seen = []
    def do_GET(self):
        auth = self.headers.get("Authorization", "")
        Portal.seen.append((self.path, auth))
        claims = PORTAL.get(auth)
        body = json.dumps(claims if claims else {"message": "Token invalid"}).encode()
        self.send_response(200 if claims else 400)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args): pass

@pytest.fixture(scope="module")
def portal(app):
    server = HTTPServer(("127.0.0.1", 0), Portal)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    saved = {k: app.config.get(k) for k in ("SSO_ENABLED", "SSO_INTROSPECTION_URL", "LOGIN_ENABLED", "SSO_USER_ROLES")}
    app.config.update(SSO_ENABLED=True, LOGIN_ENABLED=True, SSO_USER_ROLES="",
                      SSO_INTROSPECTION_URL="http://127.0.0.1:%s/api/aaa/whoami" % server.server_port)
    yield server
    server.shutdown()
    app.config.update(saved)

def sso(app, token):
    c = app.test_client()
    headers = {"Authorization": token} if token else {}
    return c, c.post("/api/sso/login", headers=headers)

def test_the_portal_decides_who_gets_in(app, portal):
    assert sso(app, None)[1].status_code == 401
    assert sso(app, "Basic abc")[1].status_code == 401
    assert sso(app, "Bearer nope")[1].status_code == 401
    # the token is forwarded as it came, to the portal's whoami
    assert Portal.seen[-1] == ("/api/aaa/whoami", "Bearer nope")

def test_an_administrator_becomes_a_statechecker_admin(app, portal):
    c, r = sso(app, "Bearer tok-alice")
    assert r.status_code == 200, r.data
    u = User.load(username="alice@example.com")
    assert u.exists() and u.sso is True and u.role == Role.FULL_ADMIN
    # an ordinary session: the same client is now signed in
    s = c.get("/api/session")
    assert s.status_code == 200 and json.loads(s.data) == {"username": "alice@example.com", "role": 0}
    assert c.get("/api/users").status_code == 200
    # a client without the cookie is not
    assert app.test_client().get("/api/session").status_code == 401

def test_everyone_else_is_a_user_and_roles_follow_the_portal(app, portal):
    sso(app, "Bearer tok-bob")
    assert User.load(username="bob-ops").role == Role.USER
    PORTAL["Bearer tok-bob"]["roles"].append("administrator")
    try:
        sso(app, "Bearer tok-bob")
        assert User.load(username="bob-ops").role == Role.FULL_ADMIN
    finally:
        PORTAL["Bearer tok-bob"]["roles"].remove("administrator")
    sso(app, "Bearer tok-bob")
    assert User.load(username="bob-ops").role == Role.USER, "a role taken away in the portal is taken away here"

def test_a_local_account_is_never_taken_over(app, portal):
    before = User.load(username="admin")
    c, r = sso(app, "Bearer tok-admin")
    assert r.status_code == 403
    after = User.load(username="admin")
    assert after.sso is False and after.password == before.password
    assert sso(app, "Bearer tok-local")[1].status_code == 403, "reserved"
    assert sso(app, "Bearer tok-bad-name")[1].status_code == 403

def test_a_blacklisted_user_stays_out(app, portal):
    sso(app, "Bearer tok-carol")
    u = User.load(username="carol")
    u.role = Role.BLACKLIST
    assert u.save()
    assert sso(app, "Bearer tok-carol")[1].status_code == 403
    assert User.load(username="carol").role == Role.BLACKLIST

def test_an_sso_account_has_no_password_login(app, portal):
    sso(app, "Bearer tok-alice")
    u = User.load(username="alice@example.com")
    u.password = "now-known"          # even if an admin sets one
    assert u.save()
    r = app.test_client().post("/api/users/login", data=json.dumps(
        {"username": "alice@example.com", "password": "now-known"}), content_type="application/json")
    assert r.status_code == 401

def test_user_roles_can_be_required(app, portal):
    app.config["SSO_USER_ROLES"] = "statechecker"
    try:
        assert sso(app, "Bearer tok-bob")[1].status_code == 403
        assert sso(app, "Bearer tok-alice")[1].status_code == 200, "administrators always"
        PORTAL["Bearer tok-bob"]["roles"].append("statechecker")
        assert sso(app, "Bearer tok-bob")[1].status_code == 200
    finally:
        PORTAL["Bearer tok-bob"]["roles"].remove("statechecker")
        app.config["SSO_USER_ROLES"] = ""

def test_an_unreachable_portal_is_a_502_not_a_login(app, portal):
    url = app.config["SSO_INTROSPECTION_URL"]
    app.config["SSO_INTROSPECTION_URL"] = "http://127.0.0.1:9/api/aaa/whoami"
    try:
        assert sso(app, "Bearer tok-alice")[1].status_code == 502
    finally:
        app.config["SSO_INTROSPECTION_URL"] = url

def test_off_unless_enabled(app, portal):
    app.config["SSO_ENABLED"] = False
    try:
        assert sso(app, "Bearer tok-alice")[1].status_code == 404
    finally:
        app.config["SSO_ENABLED"] = True
