"""Pós-venda: devoluções, trocas e garantias."""
from datetime import datetime

from .services import (ApiError, add_days, audit, authorize, clean, device_event, move_stock, now, open_cash,
                       payment_methods, sale_detail, to_int)
from . import service_orders as so


# ------------------------------------------------------------ devoluções e trocas

def create_return(conn, user, perms, data):
    who = authorize(conn, user, perms, "registrar_devolucoes", data.get("authorization"))
    sale = conn.execute("SELECT * FROM sales WHERE id=?", (data.get("sale_id"),)).fetchone()
    if not sale:
        raise ApiError("Venda não encontrada.", 404)
    if sale["status"] != "concluida":
        raise ApiError("A venda está cancelada: não há o que devolver.", 409)
    kind = data.get("kind")
    if kind not in ("devolucao", "troca"):
        raise ApiError("Tipo inválido (devolução ou troca).")
    reason = clean(data.get("reason"))
    if not reason or len(reason) < 3:
        raise ApiError("Informe o motivo.")
    raw = data.get("items") or []
    if not raw:
        raise ApiError("Selecione ao menos um item.")
    prepared, total_amount = [], 0
    seen = set()
    for r in raw:
        iid = to_int(r.get("sale_item_id"), "Item", minimum=1)
        if iid in seen:
            raise ApiError("Item repetido na devolução.")
        seen.add(iid)
        it = conn.execute("SELECT * FROM sale_items WHERE id=? AND sale_id=?", (iid, sale["id"])).fetchone()
        if not it:
            raise ApiError("Item não pertence a esta venda.")
        done = conn.execute("SELECT COALESCE(SUM(qty),0) FROM return_items WHERE sale_item_id=?", (iid,)).fetchone()[0]
        qty = to_int(r.get("qty"), "Quantidade", minimum=1)
        if qty > it["qty"] - done:
            raise ApiError(f"\"{it['product_name']}\": só é possível devolver {it['qty'] - done} unidade(s).", 409)
        amount = round(it["total_cents"] * (done + qty) / it["qty"]) - round(it["total_cents"] * done / it["qty"])
        prepared.append({"item": it, "qty": qty, "amount": amount, "cost": it["unit_cost_cents"] * qty,
                         "restock": bool(r.get("restock", True)), "note": clean(r.get("condition_note"))})
        total_amount += amount
    refund = data.get("refund_cents")
    refund = total_amount if kind == "devolucao" and refund in (None, "") else to_int(refund or 0, "Valor a devolver")
    if refund > total_amount:
        raise ApiError("O valor a devolver não pode ser maior que o valor dos itens.")
    method = clean(data.get("refund_method"))
    sess = open_cash(conn)
    if refund > 0:
        m = {x["key"]: x for x in payment_methods(conn)}.get(method)
        if not m:
            raise ApiError("Informe a forma de devolução do dinheiro.")
        if m.get("type") == "cash":
            if not sess:
                raise ApiError("Abra o caixa para devolver dinheiro ao cliente.", 409, "cash_closed")
            from .services import cash_summary
            if refund > cash_summary(conn, sess)["expected_cash_cents"]:
                raise ApiError("Não há dinheiro suficiente no caixa para esta devolução.", 409)
    cur = conn.execute(
        "INSERT INTO returns(sale_id, kind, reason, refund_method, refund_cents, user_id, authorized_by, notes, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (sale["id"], kind, reason, method if refund > 0 else None, refund, user["id"], who if who != user["id"] else None,
         clean(data.get("notes")), now()))
    rid = cur.lastrowid
    for p in prepared:
        it = p["item"]
        conn.execute(
            "INSERT INTO return_items(return_id, sale_item_id, qty, amount_cents, cost_cents, restock, condition_note) VALUES (?,?,?,?,?,?,?)",
            (rid, it["id"], p["qty"], p["amount"], p["cost"], 1 if p["restock"] else 0, p["note"]))
        label = "Devolução" if kind == "devolucao" else "Troca"
        if it["product_id"]:
            move_stock(conn, it["product_id"], "devolucao", p["qty"], user["id"], f"{label} da venda #{sale['id']}: {reason}",
                       unit_cost=it["unit_cost_cents"], ref_type="return", ref_id=rid)
            if not p["restock"]:  # produto com defeito/avaria: entra e sai, ficando registrado como perda
                move_stock(conn, it["product_id"], "avaria", -p["qty"], user["id"],
                           f"Produto devolvido sem condição de revenda (venda #{sale['id']}): {p['note'] or reason}",
                           unit_cost=it["unit_cost_cents"], ref_type="return", ref_id=rid)
        else:
            conn.execute("UPDATE devices SET status='devolvido' WHERE id=?", (it["device_id"],))
            device_event(conn, it["device_id"], "devolucao", "devolvido", user["id"],
                         f"{label} da venda #{sale['id']}: {reason}" + ("" if p["restock"] else " (sem condição de revenda)"),
                         "return", rid)
    if refund > 0 and sess and {x["key"]: x for x in payment_methods(conn)}[method].get("type") == "cash":
        conn.execute("INSERT INTO cash_movements(session_id, kind, amount_cents, reason, user_id, created_at) VALUES (?,?,?,?,?,?)",
                     (sess["id"], "devolucao", refund, f"{label} da venda #{sale['id']}", user["id"], now()))
    audit(conn, user["id"], "devolucao" if kind == "devolucao" else "troca", "sale", sale["id"],
          after={"retorno": rid, "itens": len(prepared), "reembolso_cents": refund, "motivo": reason},
          authorized_by=who if who != user["id"] else None)
    return rid


def list_returns(conn, date_from=None, date_to=None):
    sql = ("SELECT r.*, u.name AS user_name FROM returns r JOIN users u ON u.id=r.user_id WHERE 1=1")
    args = []
    if date_from:
        sql += " AND date(r.created_at)>=?"; args.append(date_from)
    if date_to:
        sql += " AND date(r.created_at)<=?"; args.append(date_to)
    out = []
    for r in conn.execute(sql + " ORDER BY r.id DESC LIMIT 500", args):
        d = dict(r)
        d["items"] = [dict(i) for i in conn.execute(
            "SELECT ri.*, si.product_name FROM return_items ri JOIN sale_items si ON si.id=ri.sale_item_id WHERE return_id=?", (r["id"],))]
        out.append(d)
    return out


# ------------------------------------------------------------ garantias

def warranty_lookup(conn, q):
    """Procura itens vendidos e serviços com garantia por nº da venda, IMEI/série, OS ou telefone/nome do cliente."""
    q = (q or "").strip()
    if len(q) < 2:
        raise ApiError("Digite ao menos 2 caracteres para buscar.")
    today = now()[:10]
    out = []
    digits = q.lstrip("#")
    like = f"%{q}%"
    rows = conn.execute(
        "SELECT i.*, s.created_at AS sale_date, s.status AS sale_status, c.name AS customer_name, c.phone AS customer_phone,"
        " d.imei1, d.serial FROM sale_items i JOIN sales s ON s.id=i.sale_id LEFT JOIN customers c ON c.id=s.customer_id"
        " LEFT JOIN devices d ON d.id=i.device_id"
        " WHERE s.status='concluida' AND (s.id=? OR d.imei1=? OR d.imei2=? OR d.serial=? OR d.code=? OR c.phone LIKE ? OR norm(c.name) LIKE norm(?))"
        " ORDER BY s.id DESC LIMIT 100",
        (int(digits) if digits.isdigit() else -1, q, q, q, q.upper(), like, like)).fetchall()
    for r in rows:
        out.append({"type": "venda", "sale_id": r["sale_id"], "sale_item_id": r["id"], "device_id": r["device_id"],
                    "description": r["product_name"], "customer_name": r["customer_name"], "customer_phone": r["customer_phone"],
                    "start": r["sale_date"][:10], "ends": r["warranty_ends"], "in_warranty": bool(r["warranty_ends"] and r["warranty_ends"] >= today),
                    "ref": f"Venda #{r['sale_id']}"})
    for o in conn.execute(
            "SELECT * FROM service_orders WHERE status='entregue' AND (id=? OR imei=? OR serial=? OR customer_phone LIKE ? OR norm(customer_name) LIKE norm(?))"
            " ORDER BY id DESC LIMIT 100", (int(digits) if digits.isdigit() else -1, q, q, like, like)):
        ends = (o["warranty_end"] or "")[:10] or add_days(o["delivered_at"], o["warranty_days"])
        out.append({"type": "servico", "order_id": o["id"], "description": f"Serviço em {o['brand']} {o['model']}: {o['defect']}",
                    "customer_name": o["customer_name"], "customer_phone": o["customer_phone"], "start": o["delivered_at"][:10],
                    "ends": ends, "in_warranty": ends >= today, "ref": f"OS {o['id']}"})
    return out


def create_claim(conn, user, perms, data):
    if "gerenciar_garantias" not in perms:
        raise ApiError("Sem permissão para registrar reclamações de garantia.", 403)
    defect = clean(data.get("defect"))
    if not defect:
        raise ApiError("Descreva o defeito relatado.")
    sale_id = data.get("sale_id") or None
    item_id = data.get("sale_item_id") or None
    order_id = data.get("order_id") or None
    desc = clean(data.get("item_desc"))
    cname, cphone = clean(data.get("customer_name")), clean(data.get("customer_phone"))
    device_id = None
    in_warranty = 1
    today = now()[:10]
    if item_id:
        it = conn.execute("SELECT i.*, s.id sid FROM sale_items i JOIN sales s ON s.id=i.sale_id WHERE i.id=?", (item_id,)).fetchone()
        if not it:
            raise ApiError("Item da venda não encontrado.")
        sale_id, device_id, desc = it["sid"], it["device_id"], desc or it["product_name"]
        in_warranty = 1 if it["warranty_ends"] and it["warranty_ends"] >= today else 0
        c = conn.execute("SELECT c.name, c.phone FROM sales s JOIN customers c ON c.id=s.customer_id WHERE s.id=?", (sale_id,)).fetchone()
        if c:
            cname, cphone = cname or c["name"], cphone or c["phone"]
    elif order_id:
        o = so.order_row(conn, order_id)
        desc = desc or f"Serviço OS {order_id}: {o['brand']} {o['model']}"
        cname, cphone = cname or o["customer_name"], cphone or o["customer_phone"]
        in_warranty = 1 if o["delivered_at"] and ((o["warranty_end"] or "")[:10] or add_days(o["delivered_at"], o["warranty_days"])) >= today else 0
    if not desc:
        raise ApiError("Informe o item ou serviço da reclamação.")
    cur = conn.execute(
        "INSERT INTO warranty_claims(sale_id, sale_item_id, order_id, device_id, customer_name, customer_phone, item_desc, defect,"
        " in_warranty, responsible_id, opened_by, opened_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (sale_id, item_id, order_id, device_id, cname, cphone, desc, defect, in_warranty, user["id"], user["id"], now()))
    audit(conn, user["id"], "garantia_aberta", "warranty_claim", cur.lastrowid, after={"item": desc, "na_garantia": bool(in_warranty)})
    return cur.lastrowid


def update_claim(conn, user, perms, cid, data):
    if "gerenciar_garantias" not in perms:
        raise ApiError("Sem permissão para gerenciar garantias.", 403)
    row = conn.execute("SELECT * FROM warranty_claims WHERE id=?", (cid,)).fetchone()
    if not row:
        raise ApiError("Reclamação não encontrada.", 404)
    if row["status"] in ("resolvida", "negada"):
        raise ApiError("Reclamação encerrada.", 409)
    status = data.get("status", row["status"])
    if status not in ("aberta", "em_analise", "resolvida", "negada"):
        raise ApiError("Situação inválida.")
    resolution = clean(data.get("resolution"))
    diagnosis, solution = clean(data.get("diagnosis")) or row["diagnosis"], clean(data.get("solution")) or row["solution"]
    cost = to_int(data.get("cost_cents", row["cost_cents"]), "Custo")
    if status in ("resolvida", "negada"):
        if not diagnosis or not solution:
            raise ApiError("Para encerrar, registre o diagnóstico e a solução/justificativa.")
        if status == "negada":
            resolution = "negada"
        elif resolution not in ("reparo", "troca", "reembolso"):
            raise ApiError("Informe como foi resolvido (reparo, troca ou reembolso).")
    resp = data.get("responsible_id") or row["responsible_id"]
    conn.execute(
        "UPDATE warranty_claims SET status=?, diagnosis=?, solution=?, resolution=?, cost_cents=?, responsible_id=?, closed_at=? WHERE id=?",
        (status, diagnosis, solution, resolution, cost, resp, now() if status in ("resolvida", "negada") else None, cid))
    audit(conn, user["id"], "garantia_atualizada", "warranty_claim", cid, before={"status": row["status"]},
          after={"status": status, "custo_cents": cost})


def list_claims(conn, status=None, q=None):
    sql = "SELECT w.*, u.name AS responsible_name FROM warranty_claims w LEFT JOIN users u ON u.id=w.responsible_id WHERE 1=1"
    args = []
    if status:
        sql += " AND w.status=?"; args.append(status)
    if q:
        sql += " AND (norm(w.customer_name||' '||w.item_desc) LIKE norm(?) OR w.customer_phone LIKE ? OR w.sale_id=?)"
        args += [f"%{q}%", f"%{q}%", int(q) if q.isdigit() else -1]
    return [dict(r) for r in conn.execute(sql + " ORDER BY w.id DESC LIMIT 300", args)]
