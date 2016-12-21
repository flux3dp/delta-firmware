
from httplib import (
    HTTPConnection as _HTTPConnection,
    HTTPSConnection as _HTTPSConnection)
from urllib import urlencode
import json


class RestAPIMixIn(object):
    def post_request(self, path, postdata):
        params = urlencode({k: v if isinstance(v, str) else json.dumps(v)
                            for k, v in postdata.items()})
        headers = {
            "Content-type": "application/x-www-form-urlencoded",
            "Accept": "text/plain"
        }
        self.request("POST", path, params, headers)

    def get_json_response(self):
        resp = self.getresponse()

        if resp.status == 200:
            try:
                doc = json.loads(resp.read())
                if doc.get("status") != "ok":
                    raise RuntimeWarning(
                        doc.get("error")[0] or "SERVER_ERROR", doc)
            except ValueError as e:
                raise RuntimeWarning("SERVER_ERROR", e)
        else:
            raise RuntimeWarning(
                "SERVER_ERROR",
                "Server return %i %s" % (resp.status, resp.reason))
        return doc


class HTTPConnection(_HTTPConnection, RestAPIMixIn):
    pass


class HTTPSConnection(_HTTPSConnection, RestAPIMixIn):
    pass


def get_connection(url):
    if url.scheme == 'http':
        return HTTPConnection(url.hostname, url.port or 80)
    elif url.scheme == 'https':
        return HTTPSConnection(url.hostname, url.port or 443)
    else:
        raise RuntimeWarning("BAD_PARAMS",
                             "Can not handle url scheme: '%s'", url.scheme)
