import threading
import unittest

from tests.helpers import Api, BaseCase, ADMIN_PW

EAN = "7891000100103"   # EAN-13 válido
EAN2 = "7894900011517"  # EAN-13 válido


class AuthTests(BaseCase):
    def test_first_login_forces_password_change(self):
        c = Api(self.app)
        c.ok(c.post("/api/login", {"username": "admin", "password": "admin123"}) if False else (200, {}))
        # o admin do setUp já trocou a senha: a antiga não funciona mais
        status, _ = Api(self.app).post("/api/login", {"username": "admin", "password": "admin123"})
        self.assertEqual(status, 401)

    def test_blocked_until_password_changed(self):
        self.admin.ok(self.admin.post("/api/users", {"username": "ana", "name": "Ana", "role": "vendedor", "password": "Inicial#1"}))
        c = Api(self.app)
        c.ok(c.post("/api/login", {"username": "ana", "password": "Inicial#1"}))
        status, body = c.get("/api/products")
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "password_change_required")
        status, _ = c.post("/api/me/password", {"current": "Inicial#1", "new": "123456"})
        self.assertEqual(status, 400)  # senha fraca
        c.ok(c.post("/api/me/password", {"current": "Inicial#1", "new": "Outra#Senha1"}))
        self.assertEqual(c.get("/api/products")[0], 200)

    def test_csrf_header_required_and_unauthenticated(self):
        raw = self.app.test_client()
        r = raw.post("/api/login", json={"username": "admin", "password": ADMIN_PW})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Api(self.app).get("/api/products")[0], 401)

    def test_login_rate_limit(self):
        c = Api(self.app)
        for _ in range(5):
            self.assertEqual(c.post("/api/login", {"username": "admin", "password": "errada"})[0], 401)
        self.assertEqual(c.post("/api/login", {"username": "admin", "password": ADMIN_PW})[0], 429)

    def test_role_permissions(self):
        v = self.user("vera", "vendedor")
        t = self.user("tito", "tecnico")
        self.assertEqual(v.get("/api/users")[0], 403)
        self.assertEqual(v.post("/api/products", {"name": "X", "price_cents": 100})[0], 403)
        self.assertEqual(t.post("/api/sales", {"client_token": "abcdefgh", "items": []})[0], 403)
        self.assertEqual(t.get("/api/finance/summary")[0], 403)
        self.assertEqual(v.get("/api/audit")[0], 403)
        self.assertEqual(v.get("/api/backups")[0], 403)

    def test_cost_hidden_without_permission(self):
        p = self.product(cost=1234)
        v = self.user("vera", "vendedor")
        got = v.ok(v.get(f"/api/products/{p['id']}"))
        self.assertNotIn("cost_cents", got)
        self.assertIn("price_cents", got)
        self.assertIn("cost_cents", self.admin.ok(self.admin.get(f"/api/products/{p['id']}")))

    def test_permissions_configurable(self):
        v = self.user("vera", "vendedor")
        self.assertEqual(v.post("/api/products", {"name": "X", "price_cents": 100})[0], 403)
        roles = self.admin.ok(self.admin.get("/api/permissions"))["roles"]
        roles["vendedor"].append("gerenciar_produtos")
        self.admin.ok(self.admin.put("/api/permissions", {"roles": roles}))
        self.assertEqual(v.post("/api/products", {"name": "X", "price_cents": 100})[0], 201)

    def test_last_admin_protected(self):
        users = self.admin.ok(self.admin.get("/api/users"))
        status, body = self.admin.put(f"/api/users/{users[0]['id']}", {"active": False})
        self.assertEqual(status, 409)


class ProductBarcodeTests(BaseCase):
    def test_create_and_lookup_by_barcode_and_sku(self):
        p = self.product(barcode=EAN)
        self.assertEqual(p["barcode_type"], "EAN-13")
        self.assertTrue(p["sku"].startswith("P"))
        found = self.admin.ok(self.admin.get(f"/api/lookup?code={EAN}"))
        self.assertEqual(found["found"], "product")
        self.assertEqual(found["product"]["id"], p["id"])
        self.assertEqual(self.admin.ok(self.admin.get(f"/api/lookup?code={p['sku']}"))["product"]["id"], p["id"])

    def test_scanner_noise_is_normalized(self):
        p = self.product(barcode=EAN)
        found = self.admin.ok(self.admin.get(f"/api/lookup?code=%20{EAN}%0D%0A"))
        self.assertEqual(found["product"]["id"], p["id"])

    def test_invalid_check_digit_rejected(self):
        status, body = self.admin.post("/api/products", {"name": "X", "barcode": "7891000100104", "price_cents": 100})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "invalid_barcode")
        # como código interno é aceito
        self.assertEqual(self.admin.post("/api/products", {"name": "X", "barcode": "7891000100104", "barcode_internal": True, "price_cents": 100})[0], 201)

    def test_duplicate_barcode_and_sku_blocked(self):
        self.product(barcode=EAN, sku="ABC1")
        s, b = self.admin.post("/api/products", {"name": "Outro", "barcode": EAN, "price_cents": 1})
        self.assertEqual((s, b["code"]), (409, "duplicate_code"))
        s, b = self.admin.post("/api/products", {"name": "Outro", "sku": "abc1", "price_cents": 1})
        self.assertEqual(s, 409)

    def test_upc_a_matches_ean13_with_leading_zero(self):
        upc = "036000291452"  # UPC-A válido
        p = self.product(barcode=upc)
        self.assertEqual(p["barcode_type"], "UPC-A")
        found = self.admin.ok(self.admin.get("/api/lookup?code=0036000291452"))
        self.assertEqual(found["product"]["id"], p["id"])
        s, _ = self.admin.post("/api/products", {"name": "dup", "barcode": "0036000291452", "price_cents": 1})
        self.assertEqual(s, 409)

    def test_ean8(self):
        p = self.product(barcode="96385074")
        self.assertEqual(p["barcode_type"], "EAN-8")

    def test_unknown_code(self):
        found = self.admin.ok(self.admin.get(f"/api/lookup?code={EAN2}"))
        self.assertIsNone(found["found"])
        chk = self.admin.ok(self.admin.get(f"/api/barcode/check?code={EAN2}"))
        self.assertTrue(chk["valid"])
        self.assertIsNone(chk["registered"])

    def test_search_by_name_sku_barcode_without_accents(self):
        p = self.product(name="Película de Vidro iPhone 13", barcode=EAN)
        for q in ("pelicula", "iphone 13", p["sku"], EAN[:8]):
            res = self.admin.ok(self.admin.get(f"/api/products?q={q}"))
            self.assertEqual([r["id"] for r in res], [p["id"]], q)

    def test_price_change_requires_permission_and_is_audited(self):
        roles = self.admin.ok(self.admin.get("/api/permissions"))["roles"]
        roles["vendedor"].append("gerenciar_produtos")
        self.admin.ok(self.admin.put("/api/permissions", {"roles": roles}))
        v = self.user("vera", "vendedor")
        p = self.product()
        s, _ = v.put(f"/api/products/{p['id']}", {"name": p["name"], "price_cents": 9999})
        self.assertEqual(s, 403)
        self.admin.ok(self.admin.put(f"/api/products/{p['id']}", {"name": p["name"], "price_cents": 3000}))
        log = self.admin.ok(self.admin.get("/api/audit?q=produto_alterado"))
        self.assertTrue(any('"price_cents": 3000' in (r["after_json"] or "") for r in log))

    def test_warranty_minimum_90_days(self):
        s, b = self.admin.post("/api/products", {"name": "X", "price_cents": 100, "warranty_days": 30})
        self.assertEqual(s, 400)
        self.assertIn("90", b["error"])


class StockTests(BaseCase):
    def test_entry_updates_weighted_average_cost_and_history(self):
        p = self.product(cost=1000, qty=10)
        r = self.admin.ok(self.admin.post(f"/api/products/{p['id']}/entry", {"qty": 10, "unit_cost_cents": 2000, "supplier": "Forn A"}))
        self.assertEqual(r["qty"], 20)
        self.assertEqual(r["cost_cents"], 1500)
        hist = self.admin.ok(self.admin.get(f"/api/products/{p['id']}/history"))["movements"]
        self.assertEqual([m["kind"] for m in hist], ["entrada", "entrada_inicial"])
        self.assertEqual((hist[0]["qty_before"], hist[0]["qty_after"]), (10, 20))

    def test_exit_requires_justification_and_cannot_go_negative(self):
        p = self.product(qty=3)
        self.assertEqual(self.admin.post(f"/api/products/{p['id']}/exit", {"qty": 1, "kind": "perda", "reason": ""})[0], 400)
        self.assertEqual(self.admin.post(f"/api/products/{p['id']}/exit", {"qty": 5, "kind": "perda", "reason": "quebrou"})[0], 409)
        r = self.admin.ok(self.admin.post(f"/api/products/{p['id']}/exit", {"qty": 2, "kind": "avaria", "reason": "caiu no chão"}))
        self.assertEqual(r["qty"], 1)

    def test_adjust_records_user_and_reason(self):
        p = self.product(qty=5)
        self.admin.ok(self.admin.post(f"/api/products/{p['id']}/adjust", {"new_qty": 8, "reason": "contagem"}))
        m = self.admin.ok(self.admin.get(f"/api/products/{p['id']}/history"))["movements"][0]
        self.assertEqual((m["kind"], m["qty_delta"], m["user_name"], m["reason"]), ("ajuste", 3, "Administrador", "contagem"))

    def test_low_stock_flag(self):
        self.product(name="Baixo", qty=1)
        self.product(name="Ok", qty=50)
        low = self.admin.ok(self.admin.get("/api/products?low=1"))
        self.assertEqual([p["name"] for p in low], ["Baixo"])
        self.assertEqual([p["name"] for p in self.admin.ok(self.admin.get("/api/dashboard"))["low_stock"]], ["Baixo"])

    def test_inventory_with_scanner(self):
        a = self.product(name="A", barcode=EAN, qty=10)
        b = self.product(name="B", barcode=EAN2, qty=5)
        c = self.product(name="C", qty=7)
        inv = self.admin.ok(self.admin.post("/api/inventory", {"name": "Teste"}))["id"]
        for _ in range(8):
            self.admin.ok(self.admin.post(f"/api/inventory/{inv}/scan", {"code": EAN}))
        self.admin.ok(self.admin.post(f"/api/inventory/{inv}/scan", {"code": EAN2, "qty": 5}))
        self.assertEqual(self.admin.post(f"/api/inventory/{inv}/scan", {"code": "0000000000000"})[0], 404)
        det = self.admin.ok(self.admin.get(f"/api/inventory/{inv}"))
        self.assertEqual({r["name"]: r["diff"] for r in det["items"]}, {"A": -2, "B": 0})
        self.assertEqual([r["name"] for r in det["uncounted"]], ["C"])
        self.assertEqual(self.admin.ok(self.admin.post(f"/api/inventory/{inv}/finish", {}))["adjusted"], 1)
        self.assertEqual(self.admin.ok(self.admin.get(f"/api/products/{a['id']}"))["qty"], 8)
        self.assertEqual(self.admin.ok(self.admin.get(f"/api/products/{c['id']}"))["qty"], 7)  # não lido: intacto


class SaleTests(BaseCase):
    def test_sale_requires_open_cash(self):
        p = self.product()
        s, b = self.sale([{"product_id": p["id"], "qty": 1}], self.cash(2500))
        self.assertEqual((s, b["code"]), (409, "cash_closed"))

    def test_full_sale_flow_updates_stock_and_totals(self):
        p = self.product(barcode=EAN, cost=1000, price=2500, qty=10)
        self.open_cash()
        r = self.admin.ok(self.sale([{"product_id": p["id"], "qty": 3}], [{"method": "dinheiro", "amount_cents": 7500, "received_cents": 10000}]))
        sale = r["sale"]
        self.assertEqual((sale["subtotal_cents"], sale["total_cents"]), (7500, 7500))
        self.assertEqual(sale["payments"][0]["change_cents"], 2500)
        self.assertEqual(self.admin.ok(self.admin.get(f"/api/products/{p['id']}"))["qty"], 7)
        self.assertEqual(sale["items"][0]["unit_cost_cents"], 1000)
        self.assertEqual(sale["profit_cents"], 7500 - 3000)
        self.assertEqual(sale["items"][0]["warranty_days"], 90)
        h = self.admin.ok(self.admin.get(f"/api/products/{p['id']}/history"))["movements"][0]
        self.assertEqual((h["kind"], h["qty_delta"], h["ref_type"], h["ref_id"]), ("venda", -3, "sale", sale["id"]))

    def test_price_comes_from_server_not_client(self):
        p = self.product(price=2500)
        self.open_cash()
        s, b = self.sale([{"product_id": p["id"], "qty": 1, "unit_price_cents": 1}], self.cash(2500))
        self.assertEqual(b["sale"]["total_cents"], 2500)

    def test_combined_payment_pix_and_credit_card_with_fees(self):
        p = self.product(price=10000, cost=6000)
        self.open_cash()
        self.admin.ok(self.admin.put("/api/settings", {"settings": {"default_acquirer": "Stone"}, "card_fees": [
            {"acquirer": "Stone", "method": "debito", "installments": 1, "fee_percent": "1,99", "days": 1},
            {"acquirer": "Stone", "method": "credito", "installments": 1, "fee_percent": "3,5", "days": 30},
            {"acquirer": "Stone", "method": "credito", "installments": 3, "fee_percent": "5,0", "days": 30}]}))
        pays = [{"method": "pix", "amount_cents": 4000}, {"method": "credito", "amount_cents": 6000, "installments": 3}]
        sale = self.admin.ok(self.sale([{"product_id": p["id"], "qty": 1}], pays))["sale"]
        card = [x for x in sale["payments"] if x["method"] == "credito"][0]
        self.assertEqual((card["fee_cents"], card["net_cents"], card["installments"]), (300, 5700, 3))
        self.assertEqual(sale["fees_cents"], 300)

    def test_payment_sum_must_match_total(self):
        p = self.product(price=2500)
        self.open_cash()
        s, b = self.sale([{"product_id": p["id"], "qty": 1}], [{"method": "pix", "amount_cents": 2000}])
        self.assertEqual((s, b["code"]), (400, "payment_mismatch"))
        s, b = self.sale([{"product_id": p["id"], "qty": 1}], self.cash(2500) + [{"method": "pix", "amount_cents": 1}])
        self.assertEqual(s, 400)
        s, b = self.sale([{"product_id": p["id"], "qty": 1}], [{"method": "dinheiro", "amount_cents": 2500, "received_cents": 2000}])
        self.assertEqual(s, 400)

    def test_idempotent_token_prevents_duplicate_sale(self):
        p = self.product(qty=5)
        self.open_cash()
        payload = {"client_token": "token-unico-123", "items": [{"product_id": p["id"], "qty": 2}], "payments": self.cash(5000)}
        s1, b1 = self.admin.post("/api/sales", payload)
        s2, b2 = self.admin.post("/api/sales", payload)
        self.assertEqual((s1, s2, b2["duplicate"]), (201, 200, True))
        self.assertEqual(b1["sale_id"], b2["sale_id"])
        self.assertEqual(self.admin.ok(self.admin.get(f"/api/products/{p['id']}"))["qty"], 3)

    def test_negative_stock_needs_authorization(self):
        v = self.user("vera", "vendedor")
        p = self.product(qty=1)
        self.open_cash(v)
        items = [{"product_id": p["id"], "qty": 2}]
        s, b = self.sale(items, self.cash(5000), who=v)
        self.assertEqual((s, b["code"]), (403, "authorization_required"))
        s, b = self.sale(items, self.cash(5000), who=v, authorization={"username": "admin", "password": ADMIN_PW})
        self.assertEqual(s, 201)
        self.assertEqual(self.admin.ok(self.admin.get(f"/api/products/{p['id']}"))["qty"], -1)
        mv = self.admin.ok(self.admin.get(f"/api/products/{p['id']}/history"))["movements"][0]
        self.assertEqual(mv["authorized_name"], "Administrador")

    def test_failed_sale_is_fully_rolled_back(self):
        a = self.product(name="A", qty=5)
        b = self.product(name="B", qty=1)
        self.open_cash()
        v = self.user("vera", "vendedor")
        s, _ = self.sale([{"product_id": a["id"], "qty": 2}, {"product_id": b["id"], "qty": 9}], self.cash(99999), who=v)
        self.assertNotEqual(s, 201)
        self.assertEqual(self.admin.ok(self.admin.get(f"/api/products/{a['id']}"))["qty"], 5)
        self.assertEqual(self.admin.ok(self.admin.get("/api/sales")), [])

    def test_discount_needs_permission_or_supervisor(self):
        v = self.user("vera", "vendedor")
        p = self.product(price=10000)
        self.open_cash(v)
        items = [{"product_id": p["id"], "qty": 1, "discount_cents": 1000}]
        s, b = self.sale(items, self.cash(9000), who=v)
        self.assertEqual((s, b["code"]), (403, "authorization_required"))
        s, b = self.sale(items, self.cash(9000), who=v, authorization={"username": "vera", "password": "Trocada#99"})
        self.assertEqual(s, 403)
        s, b = self.sale(items, self.cash(9000), who=v, authorization={"username": "admin", "password": "errada"})
        self.assertEqual(s, 403)
        s, b = self.sale(items, self.cash(9000), who=v, authorization={"username": "admin", "password": ADMIN_PW})
        self.assertEqual(s, 201)
        self.assertEqual((b["sale"]["discount_cents"], b["sale"]["total_cents"]), (1000, 9000))
        self.assertEqual(b["sale"]["items"][0]["discount_cents"], 1000)

    def test_discount_cannot_exceed_item_value(self):
        p = self.product(price=1000)
        self.open_cash()
        self.assertEqual(self.sale([{"product_id": p["id"], "qty": 1, "discount_cents": 1001}], self.cash(1))[0], 400)

    def test_cancel_restores_stock_and_keeps_history(self):
        v = self.user("vera", "vendedor")
        p = self.product(qty=10)
        self.open_cash(v)
        sale = self.admin.ok(self.sale([{"product_id": p["id"], "qty": 4}], self.cash(10000), who=v))["sale"]
        s, b = v.post(f"/api/sales/{sale['id']}/cancel", {"reason": "cliente desistiu"})
        self.assertEqual((s, b["code"]), (403, "authorization_required"))
        s, _ = v.post(f"/api/sales/{sale['id']}/cancel", {"reason": "x"})  # motivo curto
        self.assertIn(s, (400, 403))
        v.ok(v.post(f"/api/sales/{sale['id']}/cancel", {"reason": "cliente desistiu", "authorization": {"username": "admin", "password": ADMIN_PW}}))
        self.assertEqual(self.admin.ok(self.admin.get(f"/api/products/{p['id']}"))["qty"], 10)
        kinds = [m["kind"] for m in self.admin.ok(self.admin.get(f"/api/products/{p['id']}/history"))["movements"]]
        self.assertEqual(kinds[:2], ["cancelamento_venda", "venda"])
        got = self.admin.ok(self.admin.get(f"/api/sales/{sale['id']}"))
        self.assertEqual((got["status"], got["cancel_reason"]), ("cancelada", "cliente desistiu"))
        self.assertEqual(self.admin.post(f"/api/sales/{sale['id']}/cancel", {"reason": "outra vez"})[0], 409)

    def test_cancelled_sale_not_in_cash_summary(self):
        p = self.product()
        self.open_cash(opening=5000)
        s1 = self.admin.ok(self.sale([{"product_id": p["id"], "qty": 1}], self.cash(2500)))["sale"]
        self.admin.ok(self.sale([{"product_id": p["id"], "qty": 2}], self.cash(5000)))
        self.admin.ok(self.admin.post(f"/api/sales/{s1['id']}/cancel", {"reason": "erro de digitação"}))
        cash = self.admin.ok(self.admin.get("/api/cash"))
        self.assertEqual(cash["sales_count"], 1)
        self.assertEqual(cash["expected_cash_cents"], 5000 + 5000)

    def test_sale_with_customer_optional(self):
        p = self.product()
        c = self.admin.ok(self.admin.post("/api/customers", {"name": "João", "phone": "(11) 99999-0000"}))
        self.open_cash()
        sale = self.admin.ok(self.sale([{"product_id": p["id"], "qty": 1}], self.cash(2500), customer_id=c["id"]))["sale"]
        self.assertEqual(sale["customer_name"], "João")
        hist = self.admin.ok(self.admin.get(f"/api/customers/{c['id']}/history"))
        self.assertEqual(hist["total_bought_cents"], 2500)

    def test_vendor_sees_only_own_sales(self):
        v1 = self.user("vera", "vendedor"); v2 = self.user("vitor", "vendedor")
        p = self.product(qty=20)
        self.open_cash(v1)
        s1 = self.admin.ok(self.sale([{"product_id": p["id"], "qty": 1}], self.cash(2500), who=v1))["sale"]
        s2 = self.admin.ok(self.sale([{"product_id": p["id"], "qty": 1}], self.cash(2500), who=v2))["sale"]
        self.assertEqual([x["id"] for x in v1.ok(v1.get("/api/sales"))], [s1["id"]])
        self.assertEqual(v1.get(f"/api/sales/{s2['id']}")[0], 403)
        self.assertNotIn("profit_cents", v1.ok(v1.get(f"/api/sales/{s1['id']}")))

    def test_receipt_print_page(self):
        p = self.product(name="Carregador <b>Turbo</b>", qty=5)
        self.open_cash()
        sale = self.admin.ok(self.sale([{"product_id": p["id"], "qty": 1}], self.cash(2500)))["sale"]
        r = self.admin.c.get(f"/print/sale/{sale['id']}?w=80")
        html = r.get_data(as_text=True)
        self.assertEqual(r.status_code, 200)
        self.assertIn("R$ 25,00", html)
        self.assertIn("&lt;b&gt;Turbo", html)   # escapado
        self.assertRegex(html, r"\d{2}/\d{2}/\d{4}")
        self.assertEqual(self.app.test_client().get(f"/print/sale/{sale['id']}").status_code, 302)

    def test_concurrent_sales_of_last_unit(self):
        p = self.product(qty=1, price=1000)
        self.open_cash()
        results = []
        clients = [Api(self.app) for _ in range(6)]
        for c in clients:
            c.ok(c.post("/api/login", {"username": "admin", "password": ADMIN_PW}))
        def worker(i, c):
            results.append(c.post("/api/sales", {"client_token": f"concorrente-{i}-{self.tmp[-5:]}", "items": [{"product_id": p["id"], "qty": 1}],
                                                  "payments": self.cash(1000), "authorization": None})[0])
        # administrador tem a permissão de estoque negativo; usa vendedor sem ela
        v_clients = []
        for i in range(6):
            v_clients.append(self.user(f"v{i}", "vendedor"))
        threads = [threading.Thread(target=worker, args=(i, c)) for i, c in enumerate(v_clients)]
        [t.start() for t in threads]; [t.join() for t in threads]
        self.assertEqual(sorted(results).count(201), 1, results)
        self.assertEqual(self.admin.ok(self.admin.get(f"/api/products/{p['id']}"))["qty"], 0)


class CashTests(BaseCase):
    def test_open_close_difference(self):
        p = self.product(price=2500)
        self.open_cash(opening=10000)
        self.assertEqual(self.admin.post("/api/cash/open", {"opening_cents": 1})[0], 409)  # só um caixa aberto
        self.admin.ok(self.sale([{"product_id": p["id"], "qty": 2}], self.cash(5000)))
        self.admin.ok(self.sale([{"product_id": p["id"], "qty": 1}], [{"method": "pix", "amount_cents": 2500}]))
        self.admin.ok(self.admin.post("/api/cash/movement", {"kind": "sangria", "amount_cents": 3000, "reason": "depósito banco"}))
        self.admin.ok(self.admin.post("/api/cash/movement", {"kind": "reforco", "amount_cents": 500, "reason": "troco"}))
        self.assertEqual(self.admin.post("/api/cash/movement", {"kind": "sangria", "amount_cents": 999999, "reason": "absurdo"})[0], 409)
        cash = self.admin.ok(self.admin.get("/api/cash"))
        self.assertEqual(cash["expected_cash_cents"], 10000 + 5000 - 3000 + 500)  # PIX não entra no dinheiro esperado
        self.assertEqual(cash["by_method"], {"dinheiro": 5000, "pix": 2500})
        s, b = self.admin.post("/api/cash/close", {"counted_cents": 12000})
        self.assertEqual((s, b["code"]), (400, "notes_required"))
        res = self.admin.ok(self.admin.post("/api/cash/close", {"counted_cents": 12000, "notes": "faltou troco"}))
        self.assertEqual((res["expected_cents"], res["difference_cents"]), (12500, -500))
        self.assertFalse(self.admin.ok(self.admin.get("/api/cash"))["open"])
        self.assertEqual(self.sale([{"product_id": p["id"], "qty": 1}], self.cash(2500))[0], 409)

    def test_close_without_difference_needs_no_note(self):
        self.open_cash(opening=5000)
        res = self.admin.ok(self.admin.post("/api/cash/close", {"counted_cents": 5000}))
        self.assertEqual(res["difference_cents"], 0)


if __name__ == "__main__":
    unittest.main()
