
from flask import Blueprint
api = Blueprint("api", __name__)

from . import base

#### base

@api.route("/proxy", methods=["GET","POST"])
@api.route("/proxy.json", methods=["GET","POST"])
def base_aci_app_proxy(): return base.aci_app_proxy()
base_aci_app_proxy.__doc__ = base.aci_app_proxy.__doc__



#### single sign-on from the Synaptic portal (see models/sso.py)

@api.route("/sso/login", methods=["POST"])
def sso_login():
    from ..models import sso
    return sso.login()

@api.route("/session", methods=["GET"])
def current_session():
    from ..models import sso
    return sso.session()
