"""Assistência técnica: ordens de serviço, peças (com baixa de estoque), pagamentos parciais e garantia."""
import json
import re
from datetime import datetime

from .barcode import normalize
from .db import unaccent_lower
from .services import (ApiError, add_days, audit, authorize, build_payments, clean, move_stock, now, open_cash,
                       payment_methods, permissions_of, product_row, to_int, warranty_days, money, get_settings)

STATUS = {
    "recebido": "Recebido", "em_diagnostico": "Em diagnóstico", "aguardando_aprovacao": "Aguardando aprovação",
    "aguardando_peca": "Aguardando peça", "em_reparo": "Em reparo", "em_testes": "Em testes",
    "pronto_retirada": "Pronto para retirada", "entregue": "Entregue", "cancelado": "Cancelado",
}
FINAL = ("entregue", "cancelado")
PART_STATUS = {
    "aguardando_compra": "Aguardando compra", "encomendada": "Encomendada", "recebida": "Recebida",
    "instalada": "Instalada", "cancelada": "Cancelada",
}
BOUGHT = ("encomendada", "recebida", "instalada")      # a loja já gastou com a peça
PART_KIND = {"estoque": "Peça do estoque", "avulsa": "Peça avulsa (sob encomenda)"}
# Peças que valem para o cliente (cobradas) e para o custo. Cancelada some da cobrança; o custo só fica se já tinha sido comprada.
ACTIVE_PART = "removed_at IS NULL AND (part_status IS NULL OR part_status<>'cancelada')"
NEEDS_APPROVAL = ("em_reparo", "em_testes", "pronto_retirada", "entregue")


def order_row(conn, oid):
    row = conn.execute("SELECT * FROM service_orders WHERE id=?", (oid,)).fetchone()
    if not row:
        raise ApiError("Ordem de serviço não encontrada.", 404)
    return row


def totals(conn, o):
    """Valores da OS. Cobrado ao cliente e custo interno ficam separados; custo ausente NÃO vira zero silenciosamente."""
    parts = conn.execute(
        f"SELECT COALESCE(SUM(unit_price_cents*qty),0) price FROM service_order_parts WHERE order_id=? AND {ACTIVE_PART}",
        (o["id"],)).fetchone()
    # Custo: peças válidas + peças canceladas depois de compradas (prejuízo da loja).
    cost_rows = conn.execute(
        "SELECT unit_cost_cents, qty FROM service_order_parts WHERE order_id=? AND removed_at IS NULL"
        " AND (part_status IS NULL OR part_status<>'cancelada' OR cancel_after_purchase=1)", (o["id"],)).fetchall()
    parts_cost = sum(r["unit_cost_cents"] * r["qty"] for r in cost_rows if r["unit_cost_cents"] is not None)
    missing = sum(1 for r in cost_rows if r["unit_cost_cents"] is None)
    paid = conn.execute(
        "SELECT COALESCE(SUM(amount_cents),0) FROM service_payments WHERE order_id=? AND voided_at IS NULL", (o["id"],)).fetchone()[0]
    other = o["other_cost_cents"] or 0
    total = parts["price"] + o["labor_cents"] - o["discount_cents"]
    cost = parts_cost + other
    return {"parts_cents": parts["price"], "parts_cost_cents": parts_cost, "parts_cost_missing": missing,
            "other_cost_cents": other, "cost_cents": cost, "cost_incomplete": missing > 0,
            "total_cents": total, "profit_partial_cents": total - cost,
            "profit_cents": None if missing else total - cost,        # None = lucro incompleto
            "paid_cents": paid, "balance_cents": total - paid}


def warranty_types(conn):
    try:
        types = json.loads(get_settings(conn).get("os_warranty_types") or "[]")
    except ValueError:
        types = []
    return [t for t in types if isinstance(t, dict) and t.get("key") and t.get("label")]


def _warranty_for(conn, data, current_type=None):
    """(tipo, dias) da garantia: dias informados > padrão do tipo > padrão da loja."""
    wtype = clean(data.get("warranty_type")) if "warranty_type" in data else current_type
    types = {t["key"]: t for t in warranty_types(conn)}
    if wtype and wtype not in types:
        raise ApiError("Tipo de garantia inválido.")
    explicit = data.get("warranty_days")
    if explicit not in (None, ""):
        return wtype, warranty_days(explicit)
    if wtype:
        return wtype, warranty_days(types[wtype].get("days"))
    return wtype, warranty_days(None, default=int(get_settings(conn).get("default_warranty_days") or 90))


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
    wtype, wdays = _warranty_for(conn, data)
    cur = conn.execute(
        "INSERT INTO service_orders(customer_id, customer_name, customer_phone, brand, model, imei, serial, defect,"
        " physical_state, accessories, labor_cents, deadline, technician_id, entry_at, warranty_days, warranty_type, notes, created_by, client_token)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (cid, name, phone, brand, model, normalize(data.get("imei")) or None, normalize(data.get("serial")) or None,
         defect, clean(data.get("physical_state")), clean(data.get("accessories")), labor,
         _valid_date(data.get("deadline"), "prazo estimado"), tech, now(),
         wdays, wtype, clean(data.get("notes")), user["id"], token))
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
    if "warranty_days" in data or "warranty_type" in data:
        wtype, wdays = _warranty_for(conn, data, o["warranty_type"])
        if "warranty_type" in data and "warranty_days" not in data and wtype == o["warranty_type"]:
            wdays = o["warranty_days"]
        put("warranty_type", wtype)
        put("warranty_days", wdays)
    if "other_cost_cents" in data or "other_cost_note" in data:
        if "ver_custos" not in perms:
            raise ApiError("Sem permissão para lançar ou alterar custos internos da OS.", 403)
        if "other_cost_cents" in data:
            put("other_cost_cents", to_int(data["other_cost_cents"], "Outros custos"))
        if "other_cost_note" in data:
            put("other_cost_note", clean(data["other_cost_note"]))
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
        "INSERT INTO service_order_parts(order_id, product_id, kind, name, qty, unit_cost_cents, unit_price_cents, created_by, created_at)"
        " VALUES (?,?,'estoque',?,?,?,?,?,?)",
        (oid, product_id, prod["name"], qty, prod["cost_cents"], price, user["id"], now()))
    move_stock(conn, product_id, "os_peca", -qty, user["id"], f"Peça usada na OS {oid}", unit_cost=prod["cost_cents"],
               ref_type="service_order", ref_id=oid)
    if o["approved"]:
        conn.execute("UPDATE service_orders SET approved=0, approved_at=NULL WHERE id=?", (oid,))
        log_event(conn, oid, o["status"], user["id"], "Peça adicionada após aprovação: nova autorização do cliente é necessária")
    log_event(conn, oid, o["status"], user["id"], f"Peça adicionada: {qty}x {prod['name']}")
    audit(conn, user["id"], "os_peca_adicionada", "service_order", oid, after={"produto": prod["name"], "qtd": qty})
    return cur.lastrowid


def _open_order(conn, perms, oid):
    _need(perms)
    o = order_row(conn, oid)
    if o["status"] in FINAL:
        raise ApiError("Esta ordem de serviço está encerrada.", 409)
    return o


def _part(conn, oid, part_id, kind=None):
    part = conn.execute("SELECT * FROM service_order_parts WHERE id=? AND order_id=? AND removed_at IS NULL", (part_id, oid)).fetchone()
    if not part:
        raise ApiError("Peça não encontrada.", 404)
    if kind and part["kind"] != kind:
        raise ApiError("Esta operação vale apenas para peças avulsas (sob encomenda)." if kind == "avulsa"
                       else "Esta operação vale apenas para peças do estoque.", 409)
    return part


def _reset_approval(conn, o, user, why):
    """Mudança no valor cobrado depois da autorização do cliente exige nova autorização."""
    if o["approved"]:
        conn.execute("UPDATE service_orders SET approved=0, approved_at=NULL WHERE id=?", (o["id"],))
        log_event(conn, o["id"], o["status"], user["id"], f"{why}: nova autorização do cliente é necessária")


def _check_not_below_paid(conn, oid, delta_cents):
    o = order_row(conn, oid)
    t = totals(conn, o)
    if t["total_cents"] + delta_cents < t["paid_cents"]:
        raise ApiError("A alteração deixaria o total menor que o valor já pago pelo cliente.", 409)


def _money_or_none(value, label):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return to_int(value, label)


def add_loose_part(conn, user, perms, oid, data):
    """Peça avulsa / sob encomenda: vale só para esta OS, não exige cadastro e NÃO mexe no estoque."""
    o = _open_order(conn, perms, oid)
    name = clean(data.get("name"))
    if not name or len(name) < 2:
        raise ApiError("Informe o nome ou a descrição da peça.")
    qty = to_int(data.get("qty", 1), "Quantidade", minimum=1, maximum=1000)
    price = to_int(data.get("unit_price_cents") or 0, "Valor cobrado do cliente")
    cost = _money_or_none(data.get("unit_cost_cents"), "Custo da peça")
    supplier = clean(data.get("supplier"))
    if (cost is not None or supplier) and "ver_custos" not in perms:
        raise ApiError("Sem permissão para informar custo ou fornecedor da peça. Deixe em branco: a gerência completa depois.", 403)
    status = clean(data.get("part_status")) or "aguardando_compra"
    if status not in PART_STATUS or status == "cancelada":
        raise ApiError("Situação da peça inválida.")
    if status in BOUGHT and not o["approved"] and (o["labor_cents"] + price * qty) > 0:
        raise ApiError("O cliente ainda não autorizou o orçamento. Registre a autorização antes de encomendar a peça.", 409, "approval_required")
    cur = conn.execute(
        "INSERT INTO service_order_parts(order_id, product_id, kind, name, compat, qty, unit_cost_cents, unit_price_cents, part_status,"
        " supplier, notes, cost_updated_by, cost_updated_at, created_by, created_at) VALUES (?,NULL,'avulsa',?,?,?,?,?,?,?,?,?,?,?,?)",
        (oid, name, clean(data.get("compat")), qty, cost, price, status, supplier, clean(data.get("notes")),
         user["id"] if cost is not None else None, now() if cost is not None else None, user["id"], now()))
    if price * qty > 0:
        _reset_approval(conn, o, user, "Peça avulsa adicionada após aprovação")
    log_event(conn, oid, o["status"], user["id"], f"Peça avulsa adicionada: {qty}x {name} ({PART_STATUS[status]})")
    audit(conn, user["id"], "os_peca_avulsa_adicionada", "service_order", oid,
          after={"peca": name, "qtd": qty, "cobrado_cents": price * qty, "custo_informado": cost is not None})
    return cur.lastrowid


def update_loose_part(conn, user, perms, oid, part_id, data):
    """Edita a peça avulsa: dados, valor cobrado e (com permissão) custo real."""
    o = _open_order(conn, perms, oid)
    part = _part(conn, oid, part_id, "avulsa")
    cancelled_loss = part["part_status"] == "cancelada" and part["cancel_after_purchase"]
    if part["part_status"] == "cancelada" and not cancelled_loss:
        raise ApiError("Peça cancelada não pode ser editada.", 409)
    sets, vals, before, after = [], [], {}, {}

    def put(col, val, label=None):
        if val != part[col]:
            sets.append(f"{col}=?")
            vals.append(val)
            before[label or col], after[label or col] = part[col], val

    money_changed = False
    if not cancelled_loss:
        if "name" in data:
            name = clean(data["name"])
            if not name or len(name) < 2:
                raise ApiError("Informe o nome ou a descrição da peça.")
            put("name", name)
        for col in ("compat", "notes"):
            if col in data:
                put(col, clean(data[col]))
        qty, price = part["qty"], part["unit_price_cents"]
        if "qty" in data:
            qty = to_int(data["qty"], "Quantidade", minimum=1, maximum=1000)
            put("qty", qty)
        if "unit_price_cents" in data:
            price = to_int(data["unit_price_cents"] or 0, "Valor cobrado do cliente")
            put("unit_price_cents", price)
        money_changed = qty * price != part["qty"] * part["unit_price_cents"]
        if money_changed:
            _check_not_below_paid(conn, oid, qty * price - part["qty"] * part["unit_price_cents"])
    if "unit_cost_cents" in data or "supplier" in data:
        if "ver_custos" not in perms:
            raise ApiError("Sem permissão para lançar ou alterar o custo da peça.", 403)
        if "unit_cost_cents" in data:
            cost = _money_or_none(data["unit_cost_cents"], "Custo da peça")
            if cost != part["unit_cost_cents"]:
                put("unit_cost_cents", cost)
                sets += ["cost_updated_by=?", "cost_updated_at=?"]
                vals += [user["id"], now()]
        if "supplier" in data:
            put("supplier", clean(data["supplier"]))
    if sets:
        conn.execute(f"UPDATE service_order_parts SET {', '.join(sets)} WHERE id=?", vals + [part_id])
        if money_changed:
            _reset_approval(conn, o, user, "Valor da peça alterado após aprovação")
        log_event(conn, oid, o["status"], user["id"], f"Peça avulsa alterada: {part['name']}")
        audit(conn, user["id"], "os_peca_avulsa_alterada", "service_order", oid, before=before, after=after)


def set_part_status(conn, user, perms, oid, part_id, status, note=None):
    """aguardando compra → encomendada → recebida → instalada (cancelar é outra operação)."""
    o = _open_order(conn, perms, oid)
    part = _part(conn, oid, part_id, "avulsa")
    if status not in PART_STATUS or status == "cancelada":
        raise ApiError("Situação da peça inválida. Para desistir da peça use \"Cancelar peça\".")
    if part["part_status"] == "cancelada":
        raise ApiError("Peça cancelada não pode mudar de situação.", 409)
    if status == part["part_status"]:
        raise ApiError("A peça já está nesta situação.")
    if status in BOUGHT and not o["approved"] and totals(conn, o)["total_cents"] > 0:
        raise ApiError("O cliente ainda não autorizou o orçamento. Registre a autorização antes de encomendar a peça.", 409, "approval_required")
    conn.execute("UPDATE service_order_parts SET part_status=? WHERE id=?", (status, part_id))
    log_event(conn, oid, o["status"], user["id"], f"Peça '{part['name']}': {PART_STATUS[status]}" + (f" ({clean(note)})" if clean(note) else ""))
    audit(conn, user["id"], "os_peca_avulsa_situacao", "service_order", oid,
          before={"peca": part["name"], "situacao": part["part_status"]}, after={"situacao": status})


def cancel_part(conn, user, perms, oid, part_id, reason, auth=None):
    """O cliente desistiu da peça avulsa. Se ela já foi comprada, o custo continua no resultado (prejuízo) e exige supervisor."""
    o = _open_order(conn, perms, oid)
    part = _part(conn, oid, part_id, "avulsa")
    if part["part_status"] == "cancelada":
        raise ApiError("A peça já está cancelada.", 409)
    reason = clean(reason)
    if not reason:
        raise ApiError("Informe o motivo do cancelamento da peça.")
    bought = part["part_status"] in BOUGHT
    authorized = authorize(conn, user, perms, "cancelar_vendas", auth) if bought else None
    _check_not_below_paid(conn, oid, -part["qty"] * part["unit_price_cents"])
    conn.execute("UPDATE service_order_parts SET part_status='cancelada', cancel_after_purchase=? WHERE id=?", (1 if bought else 0, part_id))
    log_event(conn, oid, o["status"], user["id"], f"Peça cancelada: {part['qty']}x {part['name']} — {reason}")
    audit(conn, user["id"], "os_peca_avulsa_cancelada", "service_order", oid,
          before={"peca": part["name"], "situacao": part["part_status"]}, after={"motivo": reason, "custo_mantido": bought},
          authorized_by=authorized if authorized and authorized != user["id"] else None)


def remove_part(conn, user, perms, oid, part_id):
    o = _open_order(conn, perms, oid)
    part = _part(conn, oid, part_id)
    price = part["unit_price_cents"] * part["qty"] if part["part_status"] != "cancelada" else 0
    t = totals(conn, o)
    if t["total_cents"] - price < t["paid_cents"]:
        raise ApiError("Remover esta peça deixaria o total menor que o valor já pago.", 409)
    if part["kind"] == "avulsa":
        if part["part_status"] in BOUGHT:
            raise ApiError("Esta peça já foi comprada. Use \"Cancelar peça\" para registrar a desistência e manter o custo.", 409)
        conn.execute("UPDATE service_order_parts SET removed_at=? WHERE id=?", (now(), part_id))  # sem estoque para devolver
    else:
        conn.execute("UPDATE service_order_parts SET removed_at=? WHERE id=?", (now(), part_id))
        move_stock(conn, part["product_id"], "os_estorno", part["qty"], user["id"], f"Peça removida da OS {oid}",
                   unit_cost=part["unit_cost_cents"], ref_type="service_order", ref_id=oid)
    log_event(conn, oid, o["status"], user["id"], f"Peça removida: {part['qty']}x {part['name']}")
    audit(conn, user["id"], "os_peca_removida", "service_order", oid, before={"produto": part["name"], "qtd": part["qty"], "tipo": part["kind"]})


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
    if status == "pronto_retirada":
        waiting = [r["name"] for r in conn.execute(
            f"SELECT name FROM service_order_parts WHERE order_id=? AND kind='avulsa' AND {ACTIVE_PART}"
            " AND part_status IN ('aguardando_compra','encomendada')", (oid,))]
        if waiting:
            raise ApiError("Ainda há peça avulsa que não chegou: " + ", ".join(waiting)
                           + ". Marque como recebida/instalada (ou cancele a peça) antes de finalizar a OS.", 409, "parts_pending")
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
            if part["kind"] == "avulsa":
                # Peça avulsa não volta ao estoque: fica registrada como cancelada (e o custo fica se já foi comprada).
                if part["part_status"] != "cancelada":
                    conn.execute("UPDATE service_order_parts SET part_status='cancelada', cancel_after_purchase=? WHERE id=?",
                                 (1 if part["part_status"] in BOUGHT else 0, part["id"]))
                continue
            conn.execute("UPDATE service_order_parts SET removed_at=? WHERE id=?", (now(), part["id"]))
            move_stock(conn, part["product_id"], "os_estorno", part["qty"], user["id"], f"OS {oid} cancelada",
                       unit_cost=part["unit_cost_cents"], ref_type="service_order", ref_id=oid)
    sets, vals = ["status=?"], [status]
    terms = get_settings(conn).get("os_warranty_terms") or ""
    if status in ("pronto_retirada", "entregue") and not o["warranty_terms"] and terms:
        sets.append("warranty_terms=?")   # guarda o texto vigente: editar o termo depois não altera OS já finalizadas
        vals.append(terms)
    if status == "pronto_retirada":
        sets += ["completed_at=?", "warranty_start=?", "warranty_end=?"]   # a garantia começa quando o serviço está confirmado e o aparelho pronto
        vals += [now(), now()[:10], add_days(now(), o["warranty_days"])]
    elif status == "entregue":
        sets.append("delivered_at=?")
        vals.append(now())
        if not o["warranty_start"]:   # entrega direta, sem passar por "pronto": começa agora
            sets += ["warranty_start=?", "warranty_end=?", "completed_at=COALESCE(completed_at, ?)"]
            vals += [now()[:10], add_days(now(), o["warranty_days"]), now()]
    elif o["warranty_start"] and not o["delivered_at"]:
        sets += ["warranty_start=NULL", "warranty_end=NULL", "completed_at=NULL"]   # voltou para reparo: a garantia só vale quando ficar pronto de novo
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
    o["parts"] = []
    for r in conn.execute("SELECT * FROM service_order_parts WHERE order_id=? AND removed_at IS NULL ORDER BY id", (oid,)):
        p = dict(r)
        p["kind_label"] = PART_KIND[p["kind"]]
        p["part_status_label"] = PART_STATUS.get(p["part_status"]) if p["part_status"] else None
        p["cancelled"] = p["part_status"] == "cancelada"
        p["line_price_cents"] = 0 if p["cancelled"] else p["unit_price_cents"] * p["qty"]
        p["line_cost_cents"] = None if p["unit_cost_cents"] is None else p["unit_cost_cents"] * p["qty"]
        o["parts"].append(p)
    o["payments"] = [dict(r) for r in conn.execute("SELECT * FROM service_payments WHERE order_id=? ORDER BY id", (oid,))]
    o["events"] = [dict(r) for r in conn.execute(
        "SELECT e.*, u.name AS user_name FROM service_order_events e LEFT JOIN users u ON u.id=e.user_id WHERE order_id=? ORDER BY e.id DESC", (oid,))]
    t = conn.execute("SELECT name FROM users WHERE id=?", (o["technician_id"],)).fetchone() if o["technician_id"] else None
    o["technician_name"] = t["name"] if t else None
    base = o["warranty_start"] or o["completed_at"] or o["delivered_at"]
    if base and not o["warranty_start"]:
        o["warranty_start"] = base[:10]
    o["warranty_ends"] = o["warranty_end"] or (add_days(base, o["warranty_days"]) if base else None)
    o["warranty_type_label"] = next((t["label"] for t in warranty_types(conn) if t["key"] == o["warranty_type"]), None)
    keys = [k for k in (o["imei"], o["serial"]) if k]
    o["history"] = []
    if keys:
        ph = ",".join("?" * len(keys))
        o["history"] = [dict(r) for r in conn.execute(
            f"SELECT id, entry_at, defect, status FROM service_orders WHERE id<>? AND (imei IN ({ph}) OR serial IN ({ph})) ORDER BY id DESC",
            [oid] + keys + keys)]
    o["overdue"] = bool(o["deadline"] and o["status"] not in FINAL and o["deadline"] < now()[:10])
    return o


def customer_document(conn, oid):
    """Dados da OS que podem ser entregues ao cliente. Lista BRANCA: só entra aqui o que for explicitamente copiado.
    Custos, lucro, fornecedores, observações internas e situação de compra das peças nunca passam por esta função."""
    d = detail(conn, oid)
    cfg = get_settings(conn)
    start, end = d["warranty_start"], d["warranty_ends"]
    return {
        "id": d["id"], "status_label": d["status_label"],
        "store_name": cfg.get("store_name") or "", "store_info": cfg.get("store_info") or "",
        "entry_at": d["entry_at"], "deadline": d["deadline"], "completed_at": d["completed_at"], "delivered_at": d["delivered_at"],
        "customer_name": d["customer_name"], "customer_phone": d["customer_phone"],
        "brand": d["brand"], "model": d["model"], "imei": d["imei"], "serial": d["serial"],
        "defect": d["defect"], "physical_state": d["physical_state"], "accessories": d["accessories"],
        "diagnosis": d["diagnosis"], "services_done": d["services_done"], "technician_name": d["technician_name"],
        "total_cents": d["total_cents"],  # valor único cobrado do cliente: sem discriminar peças, mão de obra ou desconto
        "approved_at": d["approved_at"] if d["approved"] else None,
        "warranty": {"days": d["warranty_days"], "type_label": d["warranty_type_label"], "start": start, "end": end},
        "warranty_terms": d["warranty_terms"] or cfg.get("os_warranty_terms") or "",
        "service_conditions": cfg.get("os_service_conditions") or "",
    }


def search(conn, q="", status=None, technician_id=None, open_only=False, unclaimed=False, limit=300):
    sql = ("SELECT o.*, u.name AS technician_name,"
           " (SELECT COALESCE(SUM(unit_price_cents*qty),0) FROM service_order_parts p WHERE p.order_id=o.id AND p.removed_at IS NULL AND (p.part_status IS NULL OR p.part_status<>'cancelada')) AS parts_cents,"
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
