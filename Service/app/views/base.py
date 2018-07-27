
from flask import current_app, Blueprint
base = Blueprint("base", __name__)

from flask import jsonify, redirect, abort, g, make_response, request
from werkzeug.exceptions import BadRequest
from ..models.rest import (Role, Rest)
import json, re, requests

# redirect for base folder to UIAssets folder
@base.route("/")
def base_redirect():
    # check status and only if 200 (ready) redirect to UIAssets
    from ..models.aci.app_status import check_status
    (ready, status) = check_status(api=False)
    if not ready: return abort(400, status)
    return redirect("/UIAssets/", code=302)

##############################################################################
# proxy API, imported by api module
##############################################################################

@base.route("/proxy", methods=["GET","POST"])
@base.route("/proxy.json", methods=["GET", "POST"])
def aci_app_proxy():
    """ this function is a workaround to current ACI app api restriction that
        only allows for post/get requests and static one-level urls.  Instead
        of doing get/post/delete to dynamic url as provided by this app, 
        the request will be posted to a static 'proxy' url with the following 
        information provided via post data or url params
        Args:
            url(str): original url to perform proxy
            method(str): get, post, or delete (default get)
            data(json): post data to forward to url
            params(json): parameters to forward to url
        Returns:
            json for proxies to api else text response from proxy
    """
    Rest.authenticated()
    if g.user.role != Role.FULL_ADMIN: abort(403)
   
    # args can be provided via params or post data.  If both are provided
    # then post data will be preferred
    is_json = False
    method = request.args.get("method", "get").lower()
    url = request.args.get("url", None)
    data = request.args.get("data", {})
    params = request.args.get("params", {})
    try:
        user_json = request.json
        if user_json is not None:
            if "method" in user_json: method = user_json["method"]
            if "url" in user_json: url = user_json["url"]
            if "data" in user_json: data = user_json["data"]
            if "params" in user_json: params = user_json["params"]
    except BadRequest as e: pass
   
    # force data from json and back to ensure it's properly formatted 
    if data is not None and type(data) is not dict:
        try: data = json.loads(data)
        except Exception as e: abort(400, "invalid value for 'data'")
    data = json.dumps(data)
    # leave params as dict as required by requests methods
    if params is not None and type(params) is not dict:
        try: params = json.loads(params)
        except Exception as e: abort(400, "invalid value for 'params'")

    # validate url and methods
    if type(method) is not str and type(method) is not unicode:
        abort(400, "invalid value for 'method'")
    if url is None:
        abort(400, "missing required attribute 'url'")
    if type(url) is not str and type(url) is not unicode:
        abort(400, "invalid value for 'url'")
    if not re.search("^/", url):
        abort(400, "invalid value for 'url', must start with / character") 

    method = method.lower()
    url = "%s%s"%(current_app.config.get("PROXY_URL", "http://localhost"),url)
    header = {}
    if "/api/" in url: 
        header = {"content-type":"application/json"}
        is_json = True
    if method == "get":
        r = requests.get(url, verify=False, data=data, params=params,
            cookies=request.cookies,headers=header)
    elif method == "post":
        r = requests.post(url, verify=False, data=data, params=params,
            cookies=request.cookies,headers=header)
    elif method == "patch":
        r = requests.patch(url, verify=False, data=data, params=params,
            cookies=request.cookies,headers=header)
    elif method == "delete":
        r = requests.delete(url, verify=False, data=data, params=params,
            cookies=request.cookies,headers=header)
    else:
        abort(400, "invalid value for 'method'")
  
    if r.status_code != 200:
        # if json was provided in the status code with attribute error, 
        # extract it and provide just the error text back to user
        text = r.text
        try: 
            js = r.json()
            if "error" in js: text = js["error"] 
        except Exception as e: pass
        abort(r.status_code, text)
    if is_json:
        try: return jsonify(r.json())
        except Exception as e:
            r1 = re.search("https?://[^/]+(?P<clean>.*)", r.url)
            if r1 is not None: clean = r1.group("clean")
            else:clean = r.url
            abort(500, "proxy to (%s)%s failed, received non-json reply" % (
                method, clean))
    else:
       return make_response(r.text)
