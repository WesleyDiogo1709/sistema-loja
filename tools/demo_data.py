"""Cria um banco de DEMONSTRAÇÃO separado (pasta dados_demo). Nunca toca nos dados reais (pasta dados).
Uso:  python tools/demo_data.py        -> gera dados_demo/loja.db
Acesso na demonstração: usuário "admin", senha "Demo@1234" (também: vendedor / Demo@1234, tecnico / Demo@1234)."""
import os
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
DEMO = ROOT / "dados_demo"


def luhn(base):
    total = 0
    for i, ch in enumerate(reversed(base)):
        d = int(ch)
        if i % 2 == 0:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return base + str((10 - total % 10) % 10)


def ean13(body12):
    s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(body12))
    return body12 + str((10 - s % 10) % 10)


def main():
    if DEMO.exists():
        for f in DEMO.rglob("*"):
            if f.is_file():
                f.unlink()
    DEMO.mkdir(exist_ok=True)
    os.environ["LOJA_DATA_DIR"] = str(DEMO)
    from loja.app import create_app
    sys.path.insert(0, str(ROOT / "tools"))
    from tests_shim import Client
    app = create_app(testing=True)
    api = Client(app)
    api.post("/api/login", {"username": "admin", "password": "admin123"})
    api.post("/api/me/password", {"current": "admin123", "new": "Demo@1234"})
    rnd = random.Random(7)

    api.put("/api/settings", {"settings": {"store_name": "Loja Demonstração", "store_info": "Rua Exemplo, 123 - Centro\nTel. (00) 0000-0000", "default_acquirer": "Maquininha"},
                              "card_fees": [{"acquirer": "Maquininha", "method": "debito", "installments": 1, "fee_percent": "1,39", "days": 1},
                                            {"acquirer": "Maquininha", "method": "credito", "installments": 1, "fee_percent": "3,15", "days": 30},
                                            {"acquirer": "Maquininha", "method": "credito", "installments": 2, "fee_percent": "4,59", "days": 30},
                                            {"acquirer": "Maquininha", "method": "credito", "installments": 6, "fee_percent": "8,99", "days": 30},
                                            {"acquirer": "Maquininha", "method": "credito", "installments": 12, "fee_percent": "13,99", "days": 30}]})
    for u, n, r in (("vendedor", "Vera Vendedora", "vendedor"), ("tecnico", "Tiago Técnico", "tecnico"), ("gerente", "Gabriela Gerente", "gerente")):
        api.post("/api/users", {"username": u, "name": n, "role": r, "password": "Provisoria#1"})
    con = sqlite3.connect(DEMO / "loja.db")
    from werkzeug.security import generate_password_hash
    con.execute("UPDATE users SET password_hash=?, must_change_password=0 WHERE username<>'admin'", (generate_password_hash("Demo@1234"),))
    con.commit()

    for n, ph in (("Distribuidora TechSul", "(11) 4000-1000"), ("Importadora Mobile Pro", "(11) 4000-2000"), ("Assistec Peças", "(11) 4000-3000")):
        api.post("/api/suppliers", {"name": n, "phone": ph})
    custs = []
    for n, ph in (("Maria Souza", "(11) 98888-1111"), ("João Pereira", "(11) 97777-2222"), ("Ana Lima", "(11) 96666-3333"), ("Carlos Santos", "(11) 95555-4444")):
        custs.append(api.post("/api/customers", {"name": n, "phone": ph})["id"])

    catalog = [
        ("Cabo USB-C 1m", "Cabos", "Genérico", 450, 1990, 60, "Distribuidora TechSul", 90),
        ("Cabo Lightning 1m", "Cabos", "Genérico", 700, 2990, 40, "Distribuidora TechSul", 90),
        ("Carregador Turbo 20W USB-C", "Carregadores", "Genérico", 1800, 6990, 30, "Distribuidora TechSul", 90),
        ("Carregador Veicular Duplo", "Carregadores", "Genérico", 1200, 3990, 12, "Distribuidora TechSul", 90),
        ("Fone Bluetooth TWS", "Áudio", "SoundX", 3500, 9990, 18, "Importadora Mobile Pro", 180),
        ("Fone de Ouvido com Fio P2", "Áudio", "Genérico", 400, 1990, 25, "Distribuidora TechSul", 90),
        ("Caixa de Som Bluetooth Mini", "Áudio", "SoundX", 4500, 12990, 9, "Importadora Mobile Pro", 180),
        ("Película de Vidro iPhone 13", "Películas", "Genérico", 300, 2990, 50, "Distribuidora TechSul", 90),
        ("Película de Vidro iPhone 14", "Películas", "Genérico", 300, 2990, 45, "Distribuidora TechSul", 90),
        ("Película de Vidro Galaxy A54", "Películas", "Genérico", 280, 2490, 30, "Distribuidora TechSul", 90),
        ("Capa Silicone iPhone 13", "Capas", "Genérico", 800, 4990, 20, "Importadora Mobile Pro", 90),
        ("Capa Anti-impacto Galaxy A54", "Capas", "Genérico", 900, 4490, 15, "Importadora Mobile Pro", 90),
        ("Power Bank 10.000 mAh", "Energia", "PowerGo", 4200, 12990, 3, "Importadora Mobile Pro", 180),
        ("Suporte Veicular Magnético", "Acessórios", "Genérico", 700, 2990, 22, "Distribuidora TechSul", 90),
        ("Cartão de Memória 64GB", "Armazenamento", "MemX", 1900, 5990, 14, "Distribuidora TechSul", 90),
        ("Pen Drive 32GB", "Armazenamento", "MemX", 1300, 3990, 0, "Distribuidora TechSul", 90),
        ("Smartwatch Fit", "Wearables", "FitPlus", 9000, 24990, 6, "Importadora Mobile Pro", 180),
        ("Tela iPhone 11 (peça)", "Peças", "Original-like", 14000, 28000, 5, "Assistec Peças", 90),
        ("Bateria iPhone 11 (peça)", "Peças", "Original-like", 6000, 15000, 8, "Assistec Peças", 90),
        ("Tela Galaxy A54 (peça)", "Peças", "Original-like", 16000, 32000, 3, "Assistec Peças", 90),
        ("Conector de Carga USB-C (peça)", "Peças", "Genérico", 1500, 6000, 12, "Assistec Peças", 90),
    ]
    prods = []
    for i, (name, cat, brand, cost, price, qty, sup, war) in enumerate(catalog):
        body = {"name": name, "category": cat, "brand": brand, "cost_cents": cost, "price_cents": price, "qty": qty, "min_qty": 5 if qty else 3,
                "supplier": sup, "location": f"Prateleira {chr(65 + i // 7)}{i % 7 + 1}", "warranty_days": war}
        if cat != "Peças":
            body["barcode"] = ean13(f"78910001{i:04d}")
        prods.append(api.post("/api/products", body))
    iph = []
    for model, st, cor, imei, bat, cost, price in (("iPhone 11", "64 GB", "Preto", "35692011111111", 86, 130000, 179000), ("iPhone 12", "128 GB", "Azul", "35692011111222", 91, 190000, 249000), ("iPhone 13", "128 GB", "Estelar", "35692011111333", 88, 250000, 319000),
                                                   ("iPhone 13", "256 GB", "Meia-noite", "35692011111444", 94, 290000, 359000), ("iPhone 14 Pro", "256 GB", "Roxo Profundo", "35692011111555", 90, 420000, 519000)):
        iph.append(api.post("/api/devices", {"brand": "Apple", "model": model, "storage": st, "color": cor, "imei1": luhn(imei), "serial": "DEMO" + imei[-6:], "battery_health": bat, "condition": "Muito bom",
                                             "origin": "Compra de cliente", "supplier": "Importadora Mobile Pro", "cost_cents": cost, "price_cents": price, "warranty_days": 180}))
    api.post("/api/cash/open", {"opening_cents": 20000})

    def sell(items, pays, customer=None, days_ago=0):
        r = api.post("/api/sales", {"client_token": f"demo-{rnd.random()}-{rnd.random()}", "items": items, "payments": pays, "customer_id": customer})
        if days_ago:
            con.execute("UPDATE sales SET created_at=datetime(created_at, ?) WHERE id=?", (f"-{days_ago} day", r["sale_id"]))
            con.execute("UPDATE sale_items SET warranty_ends=date(warranty_ends, ?) WHERE sale_id=?", (f"-{days_ago} day", r["sale_id"]))
            con.commit()
        return r

    for d in range(14, -1, -1):
        for _ in range(rnd.randint(1, 4)):
            p = rnd.choice(prods[:17])
            if p["qty"] < 3:
                continue
            qty = rnd.randint(1, 2)
            tot = p["price_cents"] * qty
            kind = rnd.choice(["dinheiro", "pix", "debito", "credito"])
            pay = {"method": kind, "amount_cents": tot}
            if kind == "credito":
                pay["installments"] = rnd.choice([1, 2, 3, 6])
            sell([{"product_id": p["id"], "qty": qty}], [pay], rnd.choice([None, None, custs[0], custs[1]]), d)
    sell([{"device_id": iph[0]["id"]}], [{"method": "pix", "amount_cents": 179000}], custs[2], 5)
    sell([{"device_id": iph[3]["id"]}, {"product_id": prods[7]["id"], "qty": 1}],
         [{"method": "pix", "amount_cents": 150000}, {"method": "credito", "amount_cents": 361990 - 150000, "installments": 6}], custs[3], 2)
    api.post("/api/devices/%d/status" % iph[2]["id"], {"status": "reservado", "reserved_for": "Maria Souza"})

    def os_(cust, brand, model, defect, labor, status_path, parts=(), pay=0, deadline_days=3, approve=True):
        oid = api.post("/api/os", {"customer_name": cust[0], "customer_phone": cust[1], "brand": brand, "model": model, "defect": defect, "physical_state": "Riscos leves", "accessories": "Capa",
                                   "labor_cents": labor, "deadline": (datetime.now() + timedelta(days=deadline_days)).strftime("%Y-%m-%d"), "imei": luhn("35692099" + str(rnd.randint(100000, 999999)))})["id"]
        for pid, q in parts:
            api.post(f"/api/os/{oid}/parts", {"product_id": pid, "qty": q})
        if approve:
            api.post(f"/api/os/{oid}/approval", {"approved": True, "note": "Autorizado no balcão"})
        for s in status_path:
            api.post(f"/api/os/{oid}/status", {"status": s, "allow_pending": True})
        if pay:
            api.post(f"/api/os/{oid}/payments", {"payments": [{"method": "pix", "amount_cents": pay}]})
        return oid
    os_(("Fernanda Alves", "(11) 94444-5555"), "Apple", "iPhone 11", "Tela quebrada", 8000, ["em_reparo", "em_testes", "pronto_retirada"], [(prods[17]["id"], 1)], 20000, 1)
    os_(("Roberto Dias", "(11) 93333-6666"), "Samsung", "Galaxy A54", "Não carrega", 6000, ["em_reparo"], [(prods[20]["id"], 1)], 0, 2)
    os_(("Lucia Prado", "(11) 92222-7777"), "Motorola", "Moto G", "Bateria viciada", 4000, ["aguardando_aprovacao"], (), 0, 4, approve=False)
    os_(("Paulo Neri", "(11) 91111-8888"), "Apple", "iPhone 12", "Face ID não funciona", 12000, ["em_reparo", "em_testes", "pronto_retirada", "entregue"], (), 12000, 0)
    for kind, desc, val, days in (("fixa", "Aluguel da loja", 250000, 5), ("fixa", "Internet", 12000, 3), ("variavel", "Embalagens", 8000, -2), ("compra", "Reposição de películas - TechSul", 90000, 2), ("fixa", "Energia elétrica", 35000, -3)):
        api.post("/api/payables", {"kind": kind, "description": desc, "amount_cents": val, "due_date": (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")})
    con.close()
    print(f"Banco de demonstração criado em: {DEMO / 'loja.db'}")
    print('Entre com usuário "admin" e senha "Demo@1234".')


if __name__ == "__main__":
    main()
