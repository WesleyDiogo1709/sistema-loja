"""Cliente mínimo (Flask test client) usado só pelos scripts de ferramentas."""
import json


class Client:
    def __init__(self, app):
        self.c = app.test_client()

    def _do(self, method, url, data=None):
        r = self.c.open(url, method=method, data=json.dumps(data) if data is not None else None, content_type="application/json", headers={"X-Requested-With": "loja"})
        body = r.get_json()
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {url} -> {r.status_code}: {body}")
        return body

    def get(self, url):
        return self._do("GET", url)

    def post(self, url, data=None):
        return self._do("POST", url, data or {})

    def put(self, url, data):
        return self._do("PUT", url, data)
