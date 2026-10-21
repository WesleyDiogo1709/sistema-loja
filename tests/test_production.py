"""Acesso remoto: configuração de produção, HTTPS, cookies, origem, diagnóstico e uso por vários dispositivos."""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from tests.helpers import ADMIN_PW, Api, BaseCase


class ProdBase(unittest.TestCase):
    """App em modo produção: servidor atrás de um proxy HTTPS (como Render/Railway/Fly)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="loja-prod-")
        self.env = mock.patch.dict(os.environ, {"LOJA_ENV": "production", "LOJA_DATA_DIR": self.tmp, "LOJA_ADMIN_PASSWORD": "SenhaInicial#2026"})
        self.env.start()
        from loja.app import create_app
        self.app = create_app(testing=True)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def client(self, ip="203.0.113.7"):
        c = self.app.test_client()
        c.environ_base.update({"HTTP_X_FORWARDED_PROTO": "https", "HTTP_X_FORWARDED_FOR": ip, "HTTP_X_FORWARDED_HOST": "loja.exemplo.com"})
        return c

    @staticmethod
    def post(c, url, data, **kw):
        h = {"X-Requested-With": "loja", **kw.pop("headers", {})}
        return c.post(url, json=data, headers=h, **kw)


class TestProductionConfig(ProdBase):
    def test_exige_disco_persistente(self):
        from loja.app import create_app
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LOJA_DATA_DIR")
            with self.assertRaises(SystemExit) as cm:
                create_app(testing=True)
        self.assertIn("LOJA_DATA_DIR", str(cm.exception))

    def test_exige_senha_inicial_do_admin(self):
        tmp2 = tempfile.mkdtemp(prefix="loja-prod2-")
        try:
            with mock.patch.dict(os.environ, {"LOJA_DATA_DIR": tmp2}):
                os.environ.pop("LOJA_ADMIN_PASSWORD")
                from loja.app import create_app
                with self.assertRaises(SystemExit) as cm:
                    create_app(testing=True)
            self.assertIn("LOJA_ADMIN_PASSWORD", str(cm.exception))
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)

    def test_senha_inicial_vem_da_variavel_e_admin123_nao_funciona(self):
        c = self.client()
        r = self.post(c, "/api/login", {"username": "admin", "password": "admin123"})
        self.assertEqual(r.status_code, 401)
        r = self.post(c, "/api/login", {"username": "admin", "password": "SenhaInicial#2026"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["user"]["must_change_password"])

    def test_chave_secreta_curta_e_recusada(self):
        from loja.app import create_app
        with mock.patch.dict(os.environ, {"LOJA_SECRET_KEY": "curta"}):
            with self.assertRaises(SystemExit):
                create_app(testing=True)


class TestHttpsAndCookies(ProdBase):
    def test_http_redireciona_para_https(self):
        c = self.app.test_client()  # sem cabeçalho de proxy = HTTP puro
        r = c.get("/", base_url="http://loja.exemplo.com")
        self.assertEqual(r.status_code, 301)
        self.assertTrue(r.headers["Location"].startswith("https://"))
        r = c.post("/api/login", json={}, base_url="http://loja.exemplo.com", headers={"X-Requested-With": "loja"})
        self.assertEqual(r.status_code, 301)

    def test_health_responde_sem_redirecionar_e_sem_detalhes(self):
        r = self.app.test_client().get("/api/health", base_url="http://loja.exemplo.com")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.get_json()), {"ok", "version"})

    def test_cookie_secure_httponly_samesite_e_hsts(self):
        c = self.client()
        r = self.post(c, "/api/login", {"username": "admin", "password": "SenhaInicial#2026"})
        cookie = r.headers.get("Set-Cookie", "")
        for flag in ("Secure", "HttpOnly", "SameSite=Strict"):
            self.assertIn(flag, cookie)
        self.assertIn("max-age=31536000", r.headers["Strict-Transport-Security"])

    def test_origem_diferente_e_bloqueada(self):
        c = self.client()
        r = self.post(c, "/api/login", {"username": "admin", "password": "x"}, headers={"Origin": "https://site-malicioso.example"})
        self.assertEqual(r.status_code, 403)
        r = self.post(c, "/api/login", {"username": "admin", "password": "x"}, headers={"Origin": "https://loja.exemplo.com"})
        self.assertEqual(r.status_code, 401)  # passou pela origem; senha errada

    def test_limite_de_login_usa_ip_real_do_cliente(self):
        a, b = self.client("198.51.100.1"), self.client("198.51.100.2")
        for _ in range(5):
            self.post(a, "/api/login", {"username": "admin", "password": "errada"})
        self.assertEqual(self.post(a, "/api/login", {"username": "admin", "password": "errada"}).status_code, 429)
        # outro IP não é bloqueado junto (sem ProxyFix todos pareceriam o IP do proxy)
        self.assertEqual(self.post(b, "/api/login", {"username": "admin", "password": "errada"}).status_code, 401)

    def test_api_sem_login_e_rotas_internas(self):
        c = self.client()
        for url in ("/api/products", "/api/sales", "/api/diagnostico", "/api/dashboard", "/api/users"):
            self.assertEqual(c.get(url).status_code, 401, url)
        self.assertEqual(c.get("/print/sale/1").status_code in (401, 403, 302), True)
        # rotas do front usam #/rota: abrir qualquer caminho direto não vaza dados
        self.assertEqual(c.get("/").status_code, 200)


class TestPwa(ProdBase):
    def test_manifest_e_service_worker(self):
        c = self.client()
        m = c.get("/manifest.webmanifest")
        self.assertEqual(m.status_code, 200)
        j = m.get_json()
        self.assertEqual(j["display"], "standalone")
        self.assertTrue(any(i["sizes"] == "512x512" for i in j["icons"]))
        for i in j["icons"]:
            self.assertEqual(c.get(i["src"]).status_code, 200)
        sw = c.get("/sw.js")
        self.assertEqual(sw.status_code, 200)
        self.assertEqual(sw.headers["Service-Worker-Allowed"], "/")
        self.assertIn("no-cache", sw.headers["Cache-Control"])
        txt = sw.get_data(as_text=True)
        self.assertNotIn("cache.put", txt)       # nunca guarda respostas
        self.assertNotIn("caches.open", txt)

    def test_api_nao_e_cacheavel(self):
        c = self.client()
        self.post(c, "/api/login", {"username": "admin", "password": "SenhaInicial#2026"})
        self.assertEqual(c.get("/api/me").headers["Cache-Control"], "no-store")


class TestDiagnostico(BaseCase):
    def test_apenas_quem_tem_permissao(self):
        d = self.admin.ok(self.admin.get("/api/diagnostico"))
        self.assertTrue(d["online"] and d["database_ok"])
        self.assertEqual(d["user"], "admin")
        vend = self.user("vend1", "vendedor")
        self.assertEqual(vend.get("/api/diagnostico")[0], 403)
        self.assertEqual(Api(self.app).get("/api/diagnostico")[0], 401)

    def test_nao_expõe_segredos(self):
        txt = str(self.admin.ok(self.admin.get("/api/diagnostico")))
        for palavra in ("secret", "password", "hash", self.tmp):
            self.assertNotIn(palavra, txt.lower() if palavra != self.tmp else txt)


class TestVariosDispositivos(BaseCase):
    """Dois aparelhos diferentes enxergam o mesmo banco; operação repetida não duplica."""

    def test_venda_em_um_aparelho_aparece_no_outro(self):
        p = self.product(qty=10, price=2500)
        self.open_cash()
        celular = self.user("vend_cel", "vendedor")
        r = self.sale([{"product_id": p["id"], "qty": 3}], self.cash(7500), who=celular)
        self.assertEqual(r[0], 201, r)
        prods = self.admin.ok(self.admin.get("/api/products"))
        item = next(x for x in (prods if isinstance(prods, list) else prods["items"]) if x["id"] == p["id"])
        self.assertEqual(item["qty"], 7)
        hist = self.admin.ok(self.admin.get("/api/sales"))
        self.assertTrue(len(hist if isinstance(hist, list) else hist["items"]) >= 1)

    def test_reenvio_depois_de_perder_conexao_nao_duplica(self):
        p = self.product(qty=10, price=1000)
        self.open_cash()
        payload = {"client_token": "tok-reconexao-0001", "items": [{"product_id": p["id"], "qty": 2}], "payments": self.cash(2000)}
        a = self.admin.post("/api/sales", payload)
        b = self.admin.post("/api/sales", payload)  # o celular não viu a resposta e tentou de novo
        self.assertEqual(a[0], 201)
        self.assertEqual(b[0], 200)
        self.assertTrue(b[1]["duplicate"])
        self.assertEqual(a[1]["sale_id"], b[1]["sale_id"])
        prods = self.admin.ok(self.admin.get("/api/products"))
        item = next(x for x in (prods if isinstance(prods, list) else prods["items"]) if x["id"] == p["id"])
        self.assertEqual(item["qty"], 8)  # baixou uma vez só

    def test_usuario_bloqueado_perde_acesso_imediatamente(self):
        vend = self.user("vend_bloq", "vendedor")
        self.assertEqual(vend.get("/api/products")[0], 200)
        uid = next(u["id"] for u in self.admin.ok(self.admin.get("/api/users")) if u["username"] == "vend_bloq")
        self.admin.ok(self.admin.put(f"/api/users/{uid}", {"active": 0}))
        self.assertEqual(vend.get("/api/products")[0], 401)
        self.assertEqual(vend.post("/api/login", {"username": "vend_bloq", "password": "Trocada#99"})[0], 401)

    def test_logout_encerra_a_sessao(self):
        vend = self.user("vend_out", "vendedor")
        vend.ok(vend.post("/api/logout"))
        self.assertEqual(vend.get("/api/products")[0], 401)


if __name__ == "__main__":
    unittest.main()
