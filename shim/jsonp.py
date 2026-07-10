"""JSONP response helper for the webCoRE dashboard's intf/dashboard/* calls.

Every dashboard API call is JSONP (Angular's $http.jsonp with
jsonpCallbackParam: 'callback') — SHIM_API_SPEC.md §2. The response body
must be `<callback>({...json...})` served as application/javascript, or the
dashboard silently fails to render.
"""

import json
import time

from fastapi import Request
from fastapi.responses import Response


def jsonp(request: Request, data: dict) -> Response:
    callback = request.query_params.get("callback", "callback")
    data.setdefault("now", int(time.time() * 1000))
    body = f"{callback}({json.dumps(data)})"
    return Response(content=body, media_type="application/javascript")
