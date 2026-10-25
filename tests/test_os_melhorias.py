"""Melhorias da OS: peças avulsas, custos, lucro incompleto, impressão do cliente sem dados internos, garantia e migração."""
import os
import re
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

from tests.helpers import ADMIN_PW, BaseCase

COST = 7311  # valor "marcador": se aparecer em qualquer página do cliente, houve vazamento
COST_TXT = "73,11"


class OsBase(BaseCase):
    def order(self, who=None, **kw):
        who = who or self.admin
        d = {"customer_name": "Carlos", "customer_phone": "(21) 98888-7777", "brand": "Samsung", "model": "A54",
             "imei": self.valid_imei(), "defect": "Tela quebrada", "labor_cents": 8000,
             "deadline": (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d"), **kw}
        return who.ok(who.post("/api/os", d))["id"]

    def loose(self, oid, who=None, **kw):
        who = who or self.admin
        d = {"name": "Tela OLED A54", "compat": "SM-A546", "qty": 1, "unit_price_cents": 25000, "unit_cost_cents": COST, "supplier": "Fornecedor X", **kw}
        o = who.ok(who.post(f"/api/os/{oid}/loose-parts", d))
        return o, [p for p in o["parts"] if p["kind"] == "avulsa"][-1]["id"]

    def approve(self, oid):
        self.admin.ok(self.admin.post(f"/api/os/{oid}/approval", {"approved": True, "note": "Autorizou por WhatsApp"}))


class LoosePartTests(OsBase):
    def test_loose_part_does_not_touch_stock_or_catalog(self):
        p = self.product(qty=5)
        before = len(self.admin.ok(self.admin.get("/api/products")))
        oid = self.order()
        o, pid = self.loose(oid)
        self.assertEqual(len(self.admin.ok(self.admin.get("/api/products"))), before)
        self.assertEqual(self.admin.ok(self.admin.get(f"/api/products/{p['id']}"))["qty"], 5)
        part = o["parts"][0]
        self.assertEqual((part["kind"], part["part_status"]), ("avulsa", "aguardando_compra"))
        self.assertIsNone(part["product_id"])
        db = sqlite3.connect(os.path.join(self.tmp, "loja.db"))
        self.assertEqual(db.execute("SELECT COUNT(*) FROM stock_movements WHERE ref_type='service_order'").fetchone()[0], 0)
        db.close()

    def test_status_flow_and_buying_requires_approval(self):
        oid = self.order()
        _, pid = self.loose(oid)
        s, b = self.admin.post(f"/api/os/{oid}/parts/{pid}/status", {"status": "encomendada"})
        self.assertEqual((s, b["code"]), (409, "approval_required"))
        self.approve(oid)
        for st in ("encomendada", "recebida", "instalada"):
            o = self.admin.ok(self.admin.post(f"/api/os/{oid}/parts/{pid}/status", {"status": st}))
            self.assertEqual(o["parts"][0]["part_status"], st)
        self.assertEqual(self.admin.post(f"/api/os/{oid}/parts/{pid}/status", {"status": "inventado"})[0], 400)

    def test_cannot_mark_ready_with_pending_loose_part(self):
        oid = self.order()
        _, pid = self.loose(oid)
        self.approve(oid)
        for st in ("em_reparo", "em_testes"):
            self.admin.ok(self.admin.post(f"/api/os/{oid}/status", {"status": st}))
        s, b = self.admin.post(f"/api/os/{oid}/status", {"status": "pronto_retirada"})
        self.assertEqual((s, b.get("code")), (409, "parts_pending"))
        self.admin.ok(self.admin.post(f"/api/os/{oid}/parts/{pid}/status", {"status": "instalada"}))
        self.admin.ok(self.admin.post(f"/api/os/{oid}/status", {"status": "pronto_retirada"}))

    def test_remove_before_purchase_and_cancel_after(self):
        oid = self.order()
        _, pid = self.loose(oid)
        o = self.admin.ok(self.admin.delete(f"/api/os/{oid}/parts/{pid}"))
        self.assertEqual(o["parts"], [])  # sumiu da OS, mas a linha fica (removed_at) para o histórico
        db = sqlite3.connect(os.path.join(self.tmp, "loja.db"))
        self.assertEqual(db.execute("SELECT COUNT(*) FROM service_order_parts WHERE order_id=? AND removed_at IS NOT NULL", (oid,)).fetchone()[0], 1)
        db.close()
        oid2 = self.order()
        self.approve(oid2)
        _, pid2 = self.loose(oid2, part_status="encomendada")
        self.assertEqual(self.admin.delete(f"/api/os/{oid2}/parts/{pid2}")[0], 409)  # já comprada: só cancelando
        self.assertEqual(self.admin.post(f"/api/os/{oid2}/parts/{pid2}/cancel", {"reason": ""})[0], 400)
        o = self.admin.ok(self.admin.post(f"/api/os/{oid2}/parts/{pid2}/cancel", {"reason": "Cliente desistiu"}))
        self.assertEqual(o["parts"][0]["part_status"], "cancelada")
        self.assertEqual(o["parts_cents"], 0)  # não cobra o cliente
        self.assertEqual(o["parts_cost_cents"], COST)  # custo da peça já comprada continua no resultado
        self.assertEqual(o["profit_cents"], 8000 - COST)

    def test_cancel_bought_part_needs_supervisor_for_technician(self):
        oid = self.order()
        self.approve(oid)
        _, pid = self.loose(oid, part_status="encomendada")
        tech = self.user("tec1", "tecnico")
        s, b = tech.post(f"/api/os/{oid}/parts/{pid}/cancel", {"reason": "Desistiu"})
        self.assertEqual((s, b["code"]), (403, "authorization_required"))
        tech.ok(tech.post(f"/api/os/{oid}/parts/{pid}/cancel", {"reason": "Desistiu", "authorization": {"username": "admin", "password": ADMIN_PW}}))

    def test_validation(self):
        oid = self.order()
        for bad in ({"name": ""}, {"qty": 0}, {"unit_price_cents": -1}, {"unit_cost_cents": -5}):
            s, _ = self.admin.post(f"/api/os/{oid}/loose-parts", {"name": "Peça", "qty": 1, "unit_price_cents": 100, **bad})
            self.assertEqual(s, 400, bad)

    def test_stock_part_still_works(self):
        p = self.product(qty=5, cost=1000, price=4000)
        oid = self.order(labor_cents=0)
        o = self.admin.ok(self.admin.post(f"/api/os/{oid}/parts", {"product_id": p["id"], "qty": 2}))
        self.assertEqual(o["parts"][0]["kind"], "estoque")
        self.assertEqual(self.admin.ok(self.admin.get(f"/api/products/{p['id']}"))["qty"], 3)
        self.assertEqual((o["parts_cents"], o["parts_cost_cents"], o["profit_cents"]), (8000, 2000, 6000))
        o = self.admin.ok(self.admin.delete(f"/api/os/{oid}/parts/{o['parts'][0]['id']}"))
        self.assertEqual(self.admin.ok(self.admin.get(f"/api/products/{p['id']}"))["qty"], 5)


class CostTests(OsBase):
    def test_totals_formulas_no_double_counting(self):
        p = self.product(qty=5, cost=1000, price=4000)
        oid = self.order(labor_cents=8000)
        self.admin.ok(self.admin.post(f"/api/os/{oid}/parts", {"product_id": p["id"], "qty": 1}))
        self.loose(oid, qty=2, unit_price_cents=10000, unit_cost_cents=3000)
        o = self.admin.ok(self.admin.put(f"/api/os/{oid}", {"discount_cents": 1000, "other_cost_cents": 500, "other_cost_note": "Frete"}))
        self.assertEqual(o["parts_cents"], 4000 + 20000)
        self.assertEqual(o["parts_cost_cents"], 1000 + 6000)
        self.assertEqual(o["cost_cents"], 7000 + 500)
        self.assertEqual(o["total_cents"], 24000 + 8000 - 1000)
        self.assertEqual(o["profit_cents"], 31000 - 7500)
        self.assertFalse(o["cost_incomplete"])

    def test_missing_cost_flags_profit_incomplete(self):
        oid = self.order()
        o = self.admin.ok(self.admin.post(f"/api/os/{oid}/loose-parts", {"name": "Bateria", "qty": 1, "unit_price_cents": 12000}))
        self.assertTrue(o["cost_incomplete"])
        self.assertEqual(o["parts_cost_missing"], 1)
        self.assertIsNone(o["profit_cents"])  # nunca assume custo zero
        self.assertIsNone(o["parts"][0]["unit_cost_cents"])
        pid = o["parts"][0]["id"]
        o = self.admin.ok(self.admin.put(f"/api/os/{oid}/parts/{pid}", {"unit_cost_cents": 4500}))
        self.assertFalse(o["cost_incomplete"])
        self.assertEqual(o["profit_cents"], 8000 + 12000 - 4500)
        # custo zero informado de propósito (peça de cortesia) é um dado válido
        o = self.admin.ok(self.admin.put(f"/api/os/{oid}/parts/{pid}", {"unit_cost_cents": 0}))
        self.assertEqual(o["profit_cents"], 20000)

    def test_cost_not_copied_from_price(self):
        oid = self.order()
        o = self.admin.ok(self.admin.post(f"/api/os/{oid}/loose-parts", {"name": "Conector", "qty": 1, "unit_price_cents": 9000}))
        self.assertIsNone(o["parts"][0]["unit_cost_cents"])

    def test_cost_permissions(self):
        oid = self.order()
        tech = self.user("tec2", "tecnico")
        # técnico não informa custo
        s, _ = tech.post(f"/api/os/{oid}/loose-parts", {"name": "Peça", "qty": 1, "unit_price_cents": 100, "unit_cost_cents": 50})
        self.assertEqual(s, 403)
        s, _ = tech.put(f"/api/os/{oid}", {"other_cost_cents": 100})
        self.assertEqual(s, 403)
        # mas pode adicionar a peça sem custo e vê a OS sem nenhum campo de custo/lucro
        o = tech.ok(tech.post(f"/api/os/{oid}/loose-parts", {"name": "Peça", "qty": 1, "unit_price_cents": 100}))
        self.assertNotIn("unit_cost_cents", o["parts"][0])
        self.assertNotIn("cost_cents", o)
        self.assertNotIn("profit_cents", o)
        pid = o["parts"][0]["id"]
        self.assertEqual(tech.put(f"/api/os/{oid}/parts/{pid}", {"unit_cost_cents": 10})[0], 403)
        # gerente (ver_custos + ver_lucros) lança o custo
        ger = self.user("ger1", "gerente")
        o = ger.ok(ger.put(f"/api/os/{oid}/parts/{pid}", {"unit_cost_cents": 10}))
        self.assertEqual(o["parts"][0]["unit_cost_cents"], 10)
        # vendedor: lista e detalhe sem custo
        ven = self.user("ven1", "vendedor")
        for url in ("/api/os", f"/api/os/{oid}"):
            txt = str(ven.ok(ven.get(url)))
            for k in ("unit_cost_cents", "parts_cost_cents", "profit_cents", "cost_cents", "supplier"):
                self.assertNotIn(k, txt, (url, k))

    def test_finance_flags_incomplete_cost(self):
        self.open_cash(opening=0)
        oid = self.order(labor_cents=0)
        self.admin.ok(self.admin.post(f"/api/os/{oid}/loose-parts", {"name": "Tela", "qty": 1, "unit_price_cents": 10000}))
        self.approve(oid)
        self.admin.ok(self.admin.post(f"/api/os/{oid}/payments", {"payments": [{"method": "pix", "amount_cents": 10000}]}))
        self.admin.ok(self.admin.post(f"/api/os/{oid}/parts/{self.admin.ok(self.admin.get(f'/api/os/{oid}'))['parts'][0]['id']}/status", {"status": "instalada"}))
        for st in ("em_reparo", "em_testes", "pronto_retirada", "entregue"):
            self.admin.ok(self.admin.post(f"/api/os/{oid}/status", {"status": st}))
        hoje = datetime.now().strftime("%Y-%m-%d")
        sm = self.admin.ok(self.admin.get(f"/api/finance/summary?from={hoje}&to={hoje}"))
        self.assertEqual(sm.get("services_cost_incomplete"), 1)


class CustomerPrintTests(OsBase):
    def full_order(self):
        self.approve_later = None
        oid = self.order(customer_name="Maria das Graças Albuquerque de Souza e Silva Nogueira", model="Galaxy S23 Ultra 5G Enterprise Edition 512GB",
                         defect="Não liga\nTela quebrada\nNão carrega mais", physical_state="Riscos", accessories="Capa e carregador", notes="NOTA-INTERNA-SECRETA", diagnosis="Troca de tela")
        self.approve(oid)
        self.loose(oid, notes="OBS-INTERNA-PECA")
        return oid

    def test_no_internal_data_in_any_customer_document(self):
        oid = self.full_order()
        self.admin.ok(self.admin.put(f"/api/os/{oid}", {"other_cost_cents": 1234, "other_cost_note": "FRETE-INTERNO"}))
        for q in ("?formato=termico", "?formato=a4", "?formato=termico&largura=48", ""):
            r = self.admin.c.get(f"/print/os/{oid}{q}")
            self.assertEqual(r.status_code, 200)
            html = r.get_data(as_text=True)
            for bad in (COST_TXT, str(COST), "Fornecedor X", "NOTA-INTERNA-SECRETA", "OBS-INTERNA-PECA", "FRETE-INTERNO", "12,34", "lucro", "Lucro", "margem", "Margem", "Custo", "custo", "aguardando_compra", "Aguardando compra"):
                self.assertNotIn(bad, html, (q, bad))
            self.assertIn("TERMO DE GARANTIA DO SERVIÇO", html)
            self.assertIn("Maria das Graças", html)
            self.assertIn("Tela OLED A54", html)

    def test_customer_document_has_no_cost_keys(self):
        from loja import db, service_orders as so
        oid = self.full_order()
        c = db.connect()
        try:
            doc = so.customer_document(c, oid)
        finally:
            c.close()
        flat = str(doc)
        for bad in ("cost", "profit", "supplier", "NOTA-INTERNA", "Fornecedor X", str(COST)):
            self.assertNotIn(bad, flat)

    def test_cancelled_part_not_printed(self):
        oid = self.order()
        _, pid = self.loose(oid, name="PECA-CANCELADA-XYZ")
        self.admin.ok(self.admin.post(f"/api/os/{oid}/parts/{pid}/cancel", {"reason": "Desistiu"}))
        self.assertNotIn("PECA-CANCELADA-XYZ", self.admin.c.get(f"/print/os/{oid}").get_data(as_text=True))

    def test_print_requires_login_and_permission(self):
        oid = self.order()
        anon = self.app.test_client()
        self.assertIn(anon.get(f"/print/os/{oid}").status_code, (401, 403, 302))

    def test_empty_optional_fields(self):
        oid = self.admin.ok(self.admin.post("/api/os", {"customer_name": "Ana", "customer_phone": "1199999", "brand": "X", "model": "Y", "defect": "Z"}))["id"]
        for q in ("?formato=termico", "?formato=a4"):
            html = self.admin.c.get(f"/print/os/{oid}{q}").get_data(as_text=True)
            self.assertNotIn("None", html)
            self.assertNotIn("undefined", html)

    def test_thermal_template_has_print_css(self):
        oid = self.order()
        html = self.admin.c.get(f"/print/os/{oid}?formato=termico").get_data(as_text=True)
        self.assertIn("@page", html)
        self.assertIn("@media print", html)
        self.assertIn("80mm", html)
        self.assertEqual(self.admin.c.get("/print/teste-termica").status_code, 200)

    def test_a4_still_works(self):
        oid = self.order()
        r = self.admin.c.get(f"/print/os/{oid}?formato=a4")
        self.assertEqual(r.status_code, 200)
        self.assertIn(f"{oid}", r.get_data(as_text=True))


class WarrantyTests(OsBase):
    def test_default_term_exact_text_and_snapshot(self):
        oid = self.order()
        html = self.admin.c.get(f"/print/os/{oid}").get_data(as_text=True)
        for frag in ("TERMO DE GARANTIA DO SERVIÇO", "A garantia cobre defeitos relacionados ao serviço executado",
                     "A garantia não exclui os direitos assegurados ao consumidor por lei",
                     "o cliente declara ter conferido as informações registradas nesta ordem de serviço"):
            self.assertIn(frag, html)
        self.admin.ok(self.admin.put("/api/settings", {"settings": {"os_warranty_terms": "TERMO NOVO DA LOJA\n\nTexto novo do termo, editado pelo administrador."}}))
        self.assertIn("TERMO NOVO DA LOJA", self.admin.c.get(f"/print/os/{oid}").get_data(as_text=True))
        # OS já pronta guarda o texto vigente: mudar o termo depois não a altera
        self.approve(oid)
        for st in ("em_reparo", "em_testes", "pronto_retirada"):
            self.admin.ok(self.admin.post(f"/api/os/{oid}/status", {"status": st}))
        self.admin.ok(self.admin.put("/api/settings", {"settings": {"os_warranty_terms": "TERMO MUDOU DEPOIS\n\nOutro texto qualquer para o termo."}}))
        html = self.admin.c.get(f"/print/os/{oid}").get_data(as_text=True)
        self.assertIn("TERMO NOVO DA LOJA", html)
        self.assertNotIn("TERMO MUDOU DEPOIS", html)

    def test_term_editing_permissions_and_validation(self):
        ger = self.user("ger2", "gerente")
        self.assertEqual(ger.put("/api/settings", {"settings": {"os_warranty_terms": "x" * 30}})[0], 403)  # só quem gerencia configurações
        self.assertEqual(self.admin.put("/api/settings", {"settings": {"os_warranty_terms": ""}})[0], 400)
        self.assertEqual(self.admin.put("/api/settings", {"settings": {"os_warranty_terms": "x" * 5000}})[0], 400)
        self.assertEqual(self.admin.put("/api/settings", {"settings": {"os_print_default": "xyz"}})[0], 400)
        self.assertEqual(self.admin.put("/api/settings", {"settings": {"os_thermal_width_mm": "10"}})[0], 400)
        self.admin.ok(self.admin.put("/api/settings", {"settings": {"os_warranty_terms": "__padrao__"}}))
        st = self.admin.ok(self.admin.get("/api/settings"))["settings"]
        self.assertTrue(st["os_warranty_terms"].startswith("TERMO DE GARANTIA DO SERVIÇO"))

    def test_warranty_types_and_dates(self):
        types = self.admin.ok(self.admin.get("/api/settings"))["settings"]["os_warranty_types"]
        self.assertIn("tela", types)
        self.assertEqual(self.admin.put("/api/settings", {"settings": {"os_warranty_types": '[{"label":"Curta","days":30}]'}})[0], 400)
        self.admin.ok(self.admin.put("/api/settings", {"settings": {"os_warranty_types": '[{"key":"tela","label":"Tela","days":120},{"key":"outros","label":"Outros","days":90}]'}}))
        oid = self.order(warranty_type="tela")
        o = self.admin.ok(self.admin.get(f"/api/os/{oid}"))
        self.assertEqual((o["warranty_type"], o["warranty_days"]), ("tela", 120))
        self.approve(oid)
        for st in ("em_reparo", "em_testes", "pronto_retirada", "entregue"):
            o = self.admin.ok(self.admin.post(f"/api/os/{oid}/status", {"status": st, "allow_pending": True}))
        hoje = datetime.now().date()
        self.assertEqual(o["warranty_start"][:10], hoje.isoformat())
        self.assertEqual(o["warranty_end"][:10], (hoje + timedelta(days=120)).isoformat())
        html = self.admin.c.get(f"/print/os/{oid}").get_data(as_text=True)
        self.assertIn("120", html)
        self.assertIn((hoje + timedelta(days=120)).strftime("%d/%m/%Y"), html)

    def test_warranty_below_legal_minimum_rejected(self):
        self.assertEqual(self.admin.post("/api/os", {"customer_name": "A", "customer_phone": "1", "brand": "B", "model": "C", "defect": "D", "warranty_days": 30})[0], 400)


class MigrationTests(unittest.TestCase):
    def test_v1_database_migrates_preserving_data(self):
        from loja import db
        tmp = tempfile.mkdtemp(prefix="loja-mig-")
        old = os.environ.get("LOJA_DATA_DIR")
        os.environ["LOJA_DATA_DIR"] = tmp
        try:
            with mock.patch.object(db, "_migrations", lambda: {}):
                db.init_db()  # cria o banco no formato antigo (v1)
            path = os.path.join(tmp, "loja.db")
            raw = sqlite3.connect(path)
            self.assertEqual(raw.execute("PRAGMA user_version").fetchone()[0], 1)
            raw.execute("INSERT INTO products(name, cost_cents, price_cents, qty) VALUES ('Tela A', 1000, 3000, 7)")
            raw.execute("INSERT INTO customers(name, phone) VALUES ('Cliente Antigo','1199')")
            raw.execute("INSERT INTO service_orders(customer_name, brand, model, defect, labor_cents, entry_at, status, approved, delivered_at, warranty_days) "
                        "VALUES ('Cliente Antigo','Apple','iPhone 11','Tela',5000,'2026-01-10 10:00:00','entregue',1,'2026-01-12 15:00:00',90)")
            raw.execute("INSERT INTO service_order_parts(order_id, product_id, name, qty, unit_cost_cents, unit_price_cents) VALUES (1,1,'Tela A',2,1000,3000)")
            raw.commit()
            raw.close()
            db.init_db()  # aplica a migração v2
            raw = sqlite3.connect(path)
            raw.row_factory = sqlite3.Row
            self.assertEqual(raw.execute("PRAGMA user_version").fetchone()[0], db.SCHEMA_VERSION)
            part = raw.execute("SELECT * FROM service_order_parts WHERE order_id=1").fetchone()
            self.assertEqual((part["kind"], part["product_id"], part["qty"], part["unit_cost_cents"], part["unit_price_cents"], part["name"]), ("estoque", 1, 2, 1000, 3000, "Tela A"))
            self.assertEqual(raw.execute("SELECT qty FROM products WHERE id=1").fetchone()[0], 7)
            osr = raw.execute("SELECT * FROM service_orders WHERE id=1").fetchone()
            self.assertEqual((osr["labor_cents"], osr["status"], osr["other_cost_cents"]), (5000, "entregue", 0))
            self.assertEqual(osr["warranty_start"][:10], "2026-01-12")
            self.assertEqual(osr["warranty_end"][:10], "2026-04-12")
            self.assertIsNotNone(raw.execute("SELECT value FROM settings WHERE key='os_warranty_terms'").fetchone())
            self.assertEqual(raw.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(raw.execute("PRAGMA foreign_key_check").fetchall(), [])
            raw.close()
            # backup automático antes de migrar
            self.assertTrue(any("pre-migracao" in f for r, _, fs in os.walk(tmp) for f in fs))
            # idempotente: abrir de novo não muda nada
            db.init_db()
        finally:
            if old is None:
                os.environ.pop("LOJA_DATA_DIR", None)
            else:
                os.environ["LOJA_DATA_DIR"] = old
            shutil.rmtree(tmp, ignore_errors=True)

    def test_old_order_still_works_in_app(self):
        from loja import db
        tmp = tempfile.mkdtemp(prefix="loja-mig2-")
        old = os.environ.get("LOJA_DATA_DIR")
        os.environ["LOJA_DATA_DIR"] = tmp
        try:
            with mock.patch.object(db, "_migrations", lambda: {}):
                db.init_db()
            raw = sqlite3.connect(os.path.join(tmp, "loja.db"))
            raw.execute("INSERT INTO products(name, cost_cents, price_cents, qty) VALUES ('Tela A', 1000, 3000, 7)")
            raw.execute("INSERT INTO service_orders(customer_name, customer_phone, brand, model, defect, labor_cents, entry_at, status) VALUES ('Antigo','11','A','B','C',5000,'2026-01-10 10:00:00','recebido')")
            raw.execute("INSERT INTO service_order_parts(order_id, product_id, name, qty, unit_cost_cents, unit_price_cents) VALUES (1,1,'Tela A',1,1000,3000)")
            raw.commit()
            raw.close()
            from tests.helpers import Api
            from loja.app import create_app
            app = create_app(testing=True)
            a = Api(app)
            a.ok(a.post("/api/login", {"username": "admin", "password": "admin123"}))
            a.ok(a.post("/api/me/password", {"current": "admin123", "new": ADMIN_PW}))
            o = a.ok(a.get("/api/os/1"))
            self.assertEqual((o["parts_cents"], o["parts_cost_cents"], o["total_cents"], o["profit_cents"]), (3000, 1000, 8000, 7000))
            self.assertEqual(a.c.get("/print/os/1").status_code, 200)
        finally:
            if old is None:
                os.environ.pop("LOJA_DATA_DIR", None)
            else:
                os.environ["LOJA_DATA_DIR"] = old
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
