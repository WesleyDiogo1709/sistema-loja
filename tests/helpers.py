import json
import os
import shutil
import tempfile
import unittest

ADMIN_PW = "Senha@2024"


class Api:
    """Cliente de teste que se comporta como o navegador (cookies + cabeçalho anti-CSRF)."""

    def __init__(self, app):
        self.c = app.test_client()

    def req(self, method, url, data=None, files=None, **kw):
        headers = {"X-Requested-With": "loja"}
        if files is not None:
            r = self.c.open(url, method=method, data=files, headers=headers)
        elif data is not None:
            r = self.c.open(url, method=method, data=json.dumps(data), content_type="application/json", headers=headers)
        else:
            r = self.c.open(url, method=method, headers=headers)
        ctype = r.headers.get("Content-Type", "")
        body = r.get_json() if ctype.startswith("application/json") else r.data
        return r.status_code, body

    def get(self, url):
        return self.req("GET", url)

    def post(self, url, data=None, **kw):
        return self.req("POST", url, data if data is not None else {}, **kw)

    def put(self, url, data):
        return self.req("PUT", url, data)

    def delete(self, url):
        return self.req("DELETE", url)

    def ok(self, status_body, expect=(200, 201)):
        status, body = status_body
        assert status in expect, f"HTTP {status}: {body}"
        return body


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="loja-test-")
        os.environ["LOJA_DATA_DIR"] = self.tmp
        from loja.app import create_app
        self.app = create_app(testing=True)
        self.admin = Api(self.app)
        self.admin.ok(self.admin.post("/api/login", {"username": "admin", "password": "admin123"}))
        self.admin.ok(self.admin.post("/api/me/password", {"current": "admin123", "new": ADMIN_PW}))
        self.counter = 0

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- atalhos
    def user(self, username, role, name=None):
        a = self.admin
        a.ok(a.post("/api/users", {"username": username, "name": name or username.title(), "role": role, "password": "Inicial#1"}))
        c = Api(self.app)
        c.ok(c.post("/api/login", {"username": username, "password": "Inicial#1"}))
        c.ok(c.post("/api/me/password", {"current": "Inicial#1", "new": "Trocada#99"}))
        return c

    def product(self, name="Cabo USB-C", barcode=None, cost=1000, price=2500, qty=10, **kw):
        d = {"name": name, "barcode": barcode, "cost_cents": cost, "price_cents": price, "qty": qty, "min_qty": 2, **kw}
        return self.admin.ok(self.admin.post("/api/products", d))

    def open_cash(self, who=None, opening=10000):
        who = who or self.admin
        return who.ok(who.post("/api/cash/open", {"opening_cents": opening}))

    def sale(self, items, payments, who=None, **extra):
        who = who or self.admin
        self.counter += 1
        return who.post("/api/sales", {"client_token": f"tok-{self.tmp[-6:]}-{self.counter:04d}", "items": items, "payments": payments, **extra})

    def cash(self, cents):
        return [{"method": "dinheiro", "amount_cents": cents, "received_cents": cents}]

    def valid_imei(self, base="35692011234567"):
        total = 0
        for i, ch in enumerate(reversed(base)):
            d = int(ch)
            if i % 2 == 0:
                d *= 2
                if d > 9:
                    d -= 9
            total += d
        return base + str((10 - total % 10) % 10)
