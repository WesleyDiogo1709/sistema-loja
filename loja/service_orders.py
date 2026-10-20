"""Assistência técnica: ordens de serviço, peças (com baixa de estoque), pagamentos parciais e garantia."""
import re
from datetime import datetime

from .barcode import normalize
from .db import unaccent_lower
from .services import (ApiError, add_days, audit, authorize, build_payments, clean, move_stock, now, open_cash,
                       payment_methods, permissions_of, product_row, to_int, warranty_days, money)

STATUS = {
    "recebido": "Recebido", "em_diagnostico": "Em diagnóstico", "aguardando_aprovacao": "Aguardando aprovação",
    "aguardando_peca": "Aguardando peça", "em_reparo": "Em reparo", "em_testes": "Em testes",
    "pronto_retirada": "Pronto para retirada", "entregue": "Entregue", "cancelado": "Cancelado",
}
FINAL = ("entregue", "cancelado")
NEEDS_APPROVAL = ("em_reparo", "em_testes", "pronto_retirada", "entregue")


def order_row(conn, oid):
    row = conn.execute("SELECT * FROM service_orders WHERE id=?", (oid,)).fetchone()
    if not row:
        raise ApiError("Ordem de serviço não encontrada.", 404)
    return row


def totals(conn, o):
    parts = conn.execute(
        "SELECT COALESCE(SUM(unit_price_cents*qty),0) price, COALESCE(SUM(unit_cost_cents*qty),0) cost"
        " FROM service_order_parts WHERE order_id=? AND removed_at IS NULL", (o["id"],)).fetchone()
    paid = conn.execute(
        "SELECT COALESCE(SUM(amount_cents),0) FROM service_payments WHERE order_id=? AND voided_at IS NULL", (o["id"],)).fetchone()[0]
    total = parts["price"] + o["labor_cents"] - o["discount_cents"]
    return {"parts_cents": parts["price"], "parts_cost_cents": parts["cost"], "total_cents": total,
            "paid_cents": paid, "balance_cents": total - paid}


def log_event(conn, oid, status, user_id, note=None):
    conn.execute("INSERT INTO service_order_events(order_id, status, note, user_id, created_at) VALUES (?,?,?,?,?)",
                 (oid, status, clean(note), user_id, now()))


def _need(perms):
    if "gerenciar_os" not in perms:
        raise ApiError("Sem permissão para gerenciar ordens de serviço.", 403)


def _valid_date(v, label):
    v = clean(v)
    if not v:
        return None
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise ApiError(f"Data inválida em {label}.")
    return v


def create_order(conn, user, perms, data):
    _need(perms)
    token = clean(data.get("client_token"))
    if token:
        ex = conn.execute("SELECT id FROM service_orders WHERE client_token=?", (token,)).fetchone()
        if ex:
            return ex["id"]
    name, phone = clean(data.get("customer_name")), clean(data.get("customer_phone"))
    cid = data.get("customer_id") or None
    if cid:
        c = conn.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
        if not c:
            raise ApiError("Cliente não encontrado.")
        name, phone = name or c["name"], phone or c["phone"]
    if not name:
        raise ApiError("Informe o nome do cliente.")
    if not phone:
        raise ApiError("Informe um telefone de contato do cliente.")
    brand, model, defect = clean(data.get("brand")), clean(data.get("model")), clean(data.get("defect"))
    if not brand or not model:
        raise ApiError("Informe a marca e o modelo do aparelho.")
    if not defect:
        raise ApiError("Descreva o defeito relatado pelo cliente.")
    tech = data.get("technician_id") or None
    if tech and not conn.execute("SELECT 1 FROM users WHERE id=? AND active=1", (tech,)).fetchone():
        raise ApiError("Técnico não encontrado.")
    labor = to_int(data.get("labor_cents", 0), "Mão de obra")
    cur = conn.execute(
        "INSERT INTO service_orders(customer_id, customer_name, customer_phone, brand, model, imei, serial, defect,"
        " physical_state, accessories, labor_cents, deadline, technician_id, entry_at, warranty_days, notes, created_by, client_token)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (cid, name, phone, brand, model, normalize(data.get("imei")) or None, normalize(data.get("serial")) or None,
         defect, clean(data.get("physical_state")), clean(data.get("accessories")), labor,
         _valid_date(data.get("deadline"), "prazo estimado"), tech, now(),
         warranty_days(data.get("warranty_days")), clean(data.get("notes")), user["id"], token))
    oid = cur.lastrowid
    log_event(conn, oid, "recebido", user["id"], "Aparelho recebido")
    audit(conn, user["id"], "os_criada", "service_order", oid, after={"cliente": name, "aparelho": f"{brand} {model}"})
    return oid


def update_order(conn, user, perms, oid, data, auth=None):
    _need(perms)
    o = order_row(conn, oid)
    if o["status"] in FINAL:
        raise ApiError("Esta ordem de serviço está encerrada e não pode ser alterada.", 409)
    sets, vals, before, after = [], [], {}, {}

    def put(col, val):
        if val != o[col]:
            sets.append(f"{col}=?")
            vals.append(val)
            before[col], after[col] = o[col], val

    for col in ("customer_name", "customer_phone", "brand", "model", "defect", "physical_state", "accessories",
                "diagnosis", "services_done", "notes"):
        if col in data:
            v = clean(data[col])
            if col in ("customer_name", "brand", "model", "defect") and not v:
                raise ApiError("Campo obrigatório não pode ficar vazio.")
            put(col, v)
    for col in ("imei", "serial"):
        if col in data:
            put(col, normalize(data[col]) or None)
    if "labor_cents" in data:
        put("labor_cents", to_int(data["labor_cents"], "Mão de obra"))
    if "deadline" in data:
        put("deadline", _valid_date(data["deadline"], "prazo estimado"))
    if "technician_id" in data:
        put("technician_id", data["technician_id"] or None)
    if "warranty_days" in data:
        put("warranty_days", warranty_days(data["warranty_days"]))
    authorized = None
    if "discount_cents" in data:
        d = to_int(data["discount_cents"], "Desconto")
        if d != o["discount_cents"]:
            authorized = authorize(conn, user, perms, "aplicar_descontos", auth)
            put("discount_cents", d)
    if sets:
        conn.execute(f"UPDATE service_orders SET {', '.join(sets)} WHERE id=?", vals + [oid])
        # Mudança de valor depois da aprovação invalida a autorização do cliente.
        if o["approved"] and any(k in after for k in ("labor_cents", "discount_cents")):
            conn.execute("UPDATE service_orders SET approved=0, approved_at=NULL WHERE id=?", (oid,))
            log_event(conn, oid, o["status"], user["id"], "Valores alterados: nova autorização do cliente é necessária")
        t = totals(conn, order_row(conn, oid))
        if t["total_cents"] < t["paid_cents"]:
            raise ApiError("O novo total ficaria menor que o valor já pago pelo cliente.", 409)
        audit(conn, user["id"], "os_alterada", "service_order", oid, before=before, after=after,
              authorized_by=authorized if authorized and authorized != user["id"] else None)
    return order_row(conn, oid)


def add_part(conn, user, perms, oid, product_id, qty, price_cents=None):
    _need(perms)
    o = order_row(conn, oid)
    if o["status"] in FINAL:
        raise ApiError("Esta ordem de serviço está encerrada.", 409)
    qty = to_int(qty, "Quantidade", minimum=1, maximum=1000)
    prod = product_row(conn, product_id)
    if not prod["active"]:
        raise ApiError("Este produto está inativo.", 409)
    price = prod["price_cents"]
    if price_cents not in (None, "") and int(price_cents) != price:
        if "alterar_precos" not in perms:
            raise ApiError("Sem permissão para alterar o preço da peça.", 403)
        price = to_int(price_cents, "Preço da peça")
    cur = conn.execute(
        "INSERT INTO service_order_parts(order_id, product_id, name, qty, unit_cost_cents, unit_price_cents) VALUES (?,?,?,?,?,?)",
        (oid, product_id, prod["name"], qty, prod["cost_cents"], price))
    move_stock(conn, product_id, "os_peca", -qty, user["id"], f"Peça usada na OS {oid}", unit_cost=prod["cost_cents"],
               ref_type="service_order", ref_id=oid)
    if o["approved"]:
        conn.execute("UPDATE service_orders SET approved=0, approved_at=NULL WHERE id=?", (oid,))
        log_event(conn, oid, o["status"], user["id"], "Peça adicionada após aprovação: nova autorização do cliente é necessária")
    log_event(conn, oid, o["status"], user["id"], f"Peça adicionada: {qty}x {prod['name']}")
    audit(conn, user["id"], "os_peca_adicionada", "service_order", oid, after={"produto": prod["name"], "qtd": qty})
    return cur.lastrowid


def remove_part(conn, user, perms, oid, part_id):
    _need(perms)
    o = order_row(conn, oid)
    if o["status"] in FINAL:
        raise ApiError("Esta ordem de serviço está encerrada.", 409)
    part = conn.execute("SELECT * FROM service_order_parts WHERE id=? AND order_id=? AND removed_at IS NULL", (part_id, oid)).fetchone()
    if not part:
        raise ApiError("Peça não encontrada.", 404)
    t = totals(conn, o)
    if t["total_cents"] - part["unit_price_cents"] * part["qty"] < t["paid_cents"]:
        raise ApiError("Remover esta peça deixaria o total menor que o valor já pago.", 409)
    conn.execute("UPDATE service_order_parts SET removed_at=? WHERE id=?", (now(), part_id))
    move_stock(conn, part["product_id"], "os_estorno", part["qty"], user["id"], f"Peça removida da OS {oid}",
               unit_cost=part["unit_cost_cents"], ref_type="service_order", ref_id=oid)
    log_event(conn, oid, o["status"], user["id"], f"Peça removida: {part['qty']}x {part['name']}")
    audit(conn, user["id"], "os_peca_removida", "service_order", oid, before={"produto": part["name"], "qtd": part["qty"]})


def approve(conn, user, perms, oid, approved, note):
    """Registra a autorização (ou recusa) do orçamento pelo cliente."""
    _need(perms)
    o = order_row(conn, oid)
    if o["status"] in FINAL:
        raise ApiError("Esta ordem de serviço está encerrada.", 409)
    note = clean(note)
    if approved:
        if not note:
            raise ApiError("Registre como o cliente autorizou (ex.: assinatura, WhatsApp, ligação) e quem autorizou.")
        conn.execute("UPDATE service_orders SET approved=1, approved_at=?, approved_note=? WHERE id=?", (now(), note, oid))
        log_event(conn, oid, o["status"], user["id"], f"Orçamento autorizado pelo cliente: {note}")
        audit(conn, user["id"], "os_orcamento_aprovado", "service_order", oid, after={"obs": note})
    else:
        conn.execute("UPDATE service_orders SET approved=0, approved_at=NULL, approved_note=? WHERE id=?", (note, oid))
        log_event(conn, oid, o["status"], user["id"], f"Orçamento recusado pelo cliente: {note or '-'}")
        audit(conn, user["id"], "os_orcamento_recusado", "service_order", oid, after={"obs": note})


def set_status(conn, user, perms, oid, status, note=None, allow_pending=False, auth=None):
    _need(perms)
    if status not in STATUS:
        raise ApiError("Situação inválida.")
    o = order_row(conn, oid)
    if o["status"] in FINAL:
        raise ApiError("Esta ordem de serviço está encerrada.", 409)
    if status == o["status"]:
        raise ApiError("A ordem de serviço já está nesta situação.")
    t = totals(conn, o)
    if status in NEEDS_APPROVAL and t["total_cents"] > 0 and not o["approved"]:
        raise ApiError("O cliente ainda não autorizou o orçamento. Registre a autorização antes de continuar.", 409, "approval_required")
    if status == "entregue":
        if o["status"] != "pronto_retirada":
            raise ApiError("Só é possível entregar uma ordem que esteja \"Pronto para retirada\".", 409)
        if t["balance_cents"] > 0 and not allow_pending:
            raise ApiError(f"Há saldo pendente de {money(t['balance_cents'])}. Receba o pagamento ou confirme a entrega com pendência.",
                           409, "pending_balance", balance_cents=t["balance_cents"])
    authorized = None
    if status == "cancelado":
        authorized = authorize(conn, user, perms, "cancelar_vendas", auth)
        if not clean(note):
            raise ApiError("Informe o motivo do cancelamento.")
        paid = conn.execute("SELECT * FROM service_payments WHERE order_id=? AND voided_at IS NULL", (oid,)).fetchall()
        cash_keys = {m["key"] for m in payment_methods(conn) if m.get("type") == "cash"}
        # Dinheiro recebido no caixa que ainda está aberto simplesmente deixa de contar (pagamento anulado);
        # só gera saída de caixa o que foi recebido em um caixa já fechado.
        cur_sess = open_cash(conn)
        cash_back = sum(p["amount_cents"] for p in paid if p["method"] in cash_keys
                        and p["cash_session_id"] != (cur_sess["id"] if cur_sess else None))
        if cash_back:
            sess = open_cash(conn)
            if not sess:
                raise ApiError("Abra o caixa para devolver ao cliente o valor pago em dinheiro.", 409, "cash_closed")
            conn.execute("INSERT INTO cash_movements(session_id, kind, amount_cents, reason, user_id, created_at) VALUES (?,?,?,?,?,?)",
                         (sess["id"], "devolucao", cash_back, f"Estorno da OS {oid} cancelada", user["id"], now()))
        conn.execute("UPDATE service_payments SET voided_at=? WHERE order_id=? AND voided_at IS NULL", (now(), oid))
        for part in conn.execute("SELECT * FROM service_order_parts WHERE order_id=? AND removed_at IS NULL", (oid,)).fetchall():
            conn.execute("UPDATE service_order_parts SET removed_at=? WHERE id=?", (now(), part["id"]))
            move_stock(conn, part["product_id"], "os_estorno", part["qty"], user["id"], f"OS {oid} cancelada",
                       unit_cost=part["unit_cost_cents"], ref_type="service_order", ref_id=oid)
    sets, vals = ["status=?"], [status]
    if status == "pronto_retirada":
        sets.append("completed_at=?")
        vals.append(now())
    if status == "entregue":
        sets.append("delivered_at=?")
        vals.append(now())
    conn.execute(f"UPDATE service_orders SET {', '.join(sets)} WHERE id=?", vals + [oid])
    log_event(conn, oid, status, user["id"], note)
    audit(conn, user["id"], "os_situacao", "service_order", oid, before={"status": o["status"]},
          after={"status": status, "obs": clean(note)}, authorized_by=authorized if authorized and authorized != user["id"] else None)


def add_payment(conn, user, perms, oid, payments):
    _need(perms)
    o = order_row(conn, oid)
    if o["status"] == "cancelado":
        raise ApiError("Ordem cancelada: não aceita pagamentos.", 409)
    t = totals(conn, o)
    pays, total_paid = build_payments(conn, payments, None)
    if not pays:
        raise ApiError("Informe ao menos um pagamento.")
    if total_paid > t["balance_cents"]:
        raise ApiError(f"O valor informado ({money(total_paid)}) é maior que o saldo da ordem ({money(t['balance_cents'])}).")
    cash_keys = {m["key"] for m in payment_methods(conn) if m.get("type") == "cash"}
    sess = open_cash(conn)
    if any(p["method"] in cash_keys for p in pays) and not sess:
        raise ApiError("Abra o caixa antes de receber pagamentos em dinheiro.", 409, "cash_closed")
    for p in pays:
        in_cash_session = sess["id"] if sess else None
        conn.execute(
            "INSERT INTO service_payments(order_id, method, amount_cents, received_cents, change_cents, installments,"
            " fee_cents, net_cents, rec_days, acquirer, cash_session_id, user_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (oid, p["method"], p["amount"], p["received"], p["change"], p["inst"], p["fee"], p["net"], p["days"], p["acq"],
             in_cash_session, user["id"], now()))
    log_event(conn, oid, o["status"], user["id"], f"Pagamento recebido: {money(total_paid)}")
    audit(conn, user["id"], "os_pagamento", "service_order", oid, after={"valor_cents": total_paid})


def detail(conn, oid):
    o = dict(order_row(conn, oid))
    o.update(totals(conn, o))
    o["status_label"] = STATUS[o["status"]]
    o["parts"] = [dict(r) for r in conn.execute("SELECT * FROM service_order_parts WHERE order_id=? AND removed_at IS NULL ORDER BY id", (oid,))]
    o["payments"] = [dict(r) for r in conn.execute("SELECT * FROM service_payments WHERE order_id=? ORDER BY id", (oid,))]
    o["events"] = [dict(r) for r in conn.execute(
        "SELECT e.*, u.name AS user_name FROM service_order_events e LEFT JOIN users u ON u.id=e.user_id WHERE order_id=? ORDER BY e.id DESC", (oid,))]
    t = conn.execute("SELECT name FROM users WHERE id=?", (o["technician_id"],)).fetchone() if o["technician_id"] else None
    o["technician_name"] = t["name"] if t else None
    o["warranty_ends"] = add_days(o["delivered_at"], o["warranty_days"]) if o["delivered_at"] else None
    keys = [k for k in (o["imei"], o["serial"]) if k]
    o["history"] = []
    if keys:
        ph = ",".join("?" * len(keys))
        o["history"] = [dict(r) for r in conn.execute(
            f"SELECT id, entry_at, defect, status FROM service_orders WHERE id<>? AND (imei IN ({ph}) OR serial IN ({ph})) ORDER BY id DESC",
            [oid] + keys + keys)]
    o["overdue"] = bool(o["deadline"] and o["status"] not in FINAL and o["deadline"] < now()[:10])
    return o


def search(conn, q="", status=None, technician_id=None, open_only=False, unclaimed=False, limit=300):
    sql = ("SELECT o.*, u.name AS technician_name,"
           " (SELECT COALESCE(SUM(unit_price_cents*qty),0) FROM service_order_parts p WHERE p.order_id=o.id AND p.removed_at IS NULL) AS parts_cents,"
           " (SELECT COALESCE(SUM(amount_cents),0) FROM service_payments s WHERE s.order_id=o.id AND s.voided_at IS NULL) AS paid_cents"
           " FROM service_orders o LEFT JOIN users u ON u.id=o.technician_id WHERE 1=1")
    args = []
    q = (q or "").strip()
    if q:
        m = re.fullmatch(r"(?i)(?:os)?[-\s]*0*(\d+)", q)
        exact = m and len(m.group(1)) <= 5 and conn.execute("SELECT 1 FROM service_orders WHERE id=?", (int(m.group(1)),)).fetchone()
        if exact:  # número de OS existente: resultado exato
            sql += " AND o.id=?"
            args.append(int(m.group(1)))
        else:
            like = f"%{unaccent_lower(q)}%"
            sql += (" AND (norm(o.customer_name) LIKE ? OR o.customer_phone LIKE ? OR o.imei LIKE ? OR o.serial LIKE ?"
                    " OR norm(o.brand||' '||o.model) LIKE ?)")
            args += [like, f"%{q}%", f"%{q}%", f"%{q}%", like]
    if status:
        sql += " AND o.status=?"
        args.append(status)
    if technician_id:
        sql += " AND o.technician_id=?"
        args.append(technician_id)
    if open_only:
        sql += " AND o.status NOT IN ('entregue','cancelado')"
    if unclaimed:
        days = int(conn.execute("SELECT value FROM settings WHERE key='os_term_days'").fetchone()[0] or 30)
        sql += " AND o.status='pronto_retirada' AND date(o.completed_at) <= date('now','localtime',?)"
        args.append(f"-{days} day")
    sql += " ORDER BY o.id DESC LIMIT ?"
    args.append(limit)
    out = []
    for r in conn.execute(sql, args):
        d = dict(r)
        d["total_cents"] = d["parts_cents"] + d["labor_cents"] - d["discount_cents"]
        d["balance_cents"] = d["total_cents"] - d["paid_cents"]
        d["status_label"] = STATUS[d["status"]]
        d["overdue"] = bool(d["deadline"] and d["status"] not in FINAL and d["deadline"] < now()[:10])
        out.append(d)
    return out
