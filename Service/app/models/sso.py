"""
    Single sign-on from the Synaptic portal.

    The portal embeds StateChecker in an iframe on the same origin. Its task form
    POSTs the user's portal bearer token to /api/sso/login; this validates the
    token by introspecting it against the portal (GET /api/aaa/whoami), creates or
    updates the matching StateChecker user, and starts an ordinary StateChecker
    session, so the iframe then loads StateChecker signed in.

    The same contract as the NetBox synaptic-sso plugin. StateChecker never holds
    the portal's signing secret; it trusts only a token the portal itself has just
    confirmed, so expiry and revocation on the portal side apply here too.

    Roles are the portal's: holders of a SSO_ADMIN_ROLES role become StateChecker
    admins, everyone else a user, re-evaluated at every sign-in. A local account
    (one created with a password) is never taken over by a portal user of the same
    name, and a user blacklisted in StateChecker stays blacklisted.
"""

import logging
import re
import secrets

import requests
from flask import abort, current_app, jsonify, request

from .rest import Role
from .user import User

logger = logging.getLogger(__name__)


def _roles(key):
    return {r.strip() for r in current_app.config.get(key, "").split(",") if r.strip()}


def _introspect(bearer):
    """ the portal's claims for this bearer token; aborts if it is not valid """
    try:
        r = requests.get(current_app.config["SSO_INTROSPECTION_URL"],
                         headers={"Authorization": "Bearer %s" % bearer},
                         timeout=current_app.config["SSO_TIMEOUT"],
                         verify=current_app.config["SSO_VERIFY_TLS"])
    except requests.RequestException as e:
        logger.error("sso: portal unreachable: %s", e)
        abort(502, "portal unreachable")
    if r.status_code != 200:
        logger.warning("sso: token rejected by the portal (%s)", r.status_code)
        abort(401, "token rejected by portal")
    try:
        claims = r.json()
    except ValueError:
        abort(502, "portal answered something other than JSON")
    if not isinstance(claims, dict) or not claims.get("username"):
        abort(502, "portal answered without a username")
    return claims


def login():
    """ POST /api/sso/login with Authorization: Bearer <portal token> """
    if not current_app.config.get("SSO_ENABLED"):
        abort(404, "single sign-on is not enabled")
    scheme, _, bearer = request.headers.get("Authorization", "").partition(" ")
    if scheme != "Bearer" or not bearer.strip():
        abort(401, "Bearer Authorization header required")
    claims = _introspect(bearer.strip())

    username = claims["username"]
    roles = set(claims.get("roles") or [])
    if not re.search(User._attributes["username"]["regex"], username):
        abort(403, "portal username %r is not a valid StateChecker username" % username)
    if username.lower() in User.RESERVED:
        abort(403, "username %r is reserved" % username)
    admin = bool(roles & _roles("SSO_ADMIN_ROLES"))
    allowed = _roles("SSO_USER_ROLES")
    if allowed and not admin and not (roles & allowed):
        abort(403, "no portal role that grants StateChecker")
    role = Role.FULL_ADMIN if admin else Role.USER

    u = User.load(username=username)
    if u.exists():
        if not u.sso:
            logger.warning("sso: refused %s: a local account of that name exists", username)
            abort(403, "a local StateChecker account named %s exists; sign in with "
                       "its password" % username)
        if u.role == Role.BLACKLIST:
            abort(403, "%s is blocked in StateChecker" % username)
        u.role = role
    else:
        # a password nobody knows: the account signs in through the portal only
        u = User(username=username, role=role, password=secrets.token_urlsafe(48))
        u.sso = True
    if not u.save():
        abort(500, "failed to save user %s" % username)
    logger.info("sso: %s signed in (role %s)", username, Role.ROLES_STR.get(role))
    return User.start_session(u)


def session():
    """ GET /api/session: who the current session belongs to, for the UI, which
        otherwise only knows about sign-ins made through its own login form """
    from flask import g
    user = getattr(g, "user", None)
    if user is None or getattr(user, "is_authenticated", False) is False:
        abort(401, "Unauthenticated")
    return jsonify({"username": user.username, "role": user.role})
