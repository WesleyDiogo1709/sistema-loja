"""Financeiro: contas a pagar/receber, taxas de cartão, resumo do período e fluxo de caixa."""
from datetime import datetime, timedelta

from .services import ApiError, add_days, audit, clean, now, payment_methods, to_int
from . import service_orders as so

KINDS = {"compra": "Compra de mercadoria", "fixa": "Despesa fixa", "variavel": "Despesa variável"}


def _date(v, label):
    v = clean(v)
    if not v:
        raise ApiError(f"Informe a data de {label}.")
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise ApiError(f"Data inválida em {label}.")
    return v


def _need(perms):
    if "gerenciar_financeiro" not in perms:
        raise ApiError("Sem permissão para o financeiro.", 403)


# ------------------------------------------------------------ contas a pagar

def create_payable(conn, user, perms, data):
    _need(perms)
    kind = data.get("kind")
    if kind not in KINDS:
        raise ApiError("Tipo inválido.")
    desc = clean(data.get("description"))
    if not desc:
        raise ApiError("Informe a descrição.")
    amount = to_int(data.get("amount_cents"), "Valor", minimum=1)
    due = _date(data.get("due_date"), "vencimento")
    # Repetição mensal (ex.: aluguel): cria N lançamentos.
    repeat = to_int(data.get("repeat_months", 1), "Repetições", minimum=1, maximum=36)
    ids = []
    for i in range(repeat):
        d = datetime.strptime(due, "%Y-%m-%d")
        month = d.month - 1 + i
        year, month = d.year + month // 12, month % 12 + 1
        day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
        label = desc if repeat == 1 else f"{desc} ({i + 1}/{repeat})"
        cur = conn.execute(
            "INSERT INTO payables(kind, description, supplier, category, amount_cents, due_date, notes, user_id, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (kind, label, clean(data.get("supplier")), clean(data.get("category")), amount,
             f"{year:04d}-{month:02d}-{day:02d}", clean(data.get("notes")), user["id"], now()))
        ids.append(cur.lastrowid)
    audit(conn, user["id"], "conta_pagar_criada", "payable", ids[0], after={"descricao": desc, "valor_cents": amount, "qtd": repeat})
    return ids


def pay_payable(conn, user, perms, pid, paid_cents=None, method=None, paid_date=None):
    _need(perms)
    row = conn.execute("SELECT * FROM payables WHERE id=?", (pid,)).fetchone()
    if not row:
        raise ApiError("Conta não encontrada.", 404)
    if row["paid_at"]:
        raise ApiError("Esta conta já está paga.", 409)
    paid = to_int(paid_cents if paid_cents not in (None, "") else row["amount_cents"], "Valor pago", minimum=1)
    when = _date(paid_date, "pagamento") if paid_date else now()[:10]
    conn.execute("UPDATE payables SET paid_at=?, paid_cents=?, pay_method=? WHERE id=?", (when, paid, clean(method), pid))
    audit(conn, user["id"], "conta_paga", "payable", pid, before={"valor_cents": row["amount_cents"]}, after={"pago_cents": paid, "data": when})


def delete_payable(conn, user, perms, pid):
    _need(perms)
    row = conn.execute("SELECT * FROM payables WHERE id=?", (pid,)).fetchone()
    if not row:
        raise ApiError("Conta não encontrada.", 404)
    if row["paid_at"]:
        raise ApiError("Contas pagas não podem ser excluídas. Elas fazem parte do histórico financeiro.", 409)
    conn.execute("DELETE FROM payables WHERE id=?", (pid,))
    audit(conn, user["id"], "conta_pagar_excluida", "payable", pid, before=dict(row))


def list_payables(conn, status="abertas", date_from=None, date_to=None, kind=None):
    sql, args = "SELECT * FROM payables WHERE 1=1", []
    if status == "abertas":
        sql += " AND paid_at IS NULL"
    elif status == "pagas":
        sql += " AND paid_at IS NOT NULL"
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    if date_from:
        sql += " AND due_date>=?"
        args.append(date_from)
    if date_to:
        sql += " AND due_date<=?"
        args.append(date_to)
    sql += " ORDER BY due_date, id"
    today = now()[:10]
    soon = add_days(today, 7)
    out = []
    for r in conn.execute(sql, args):
        d = dict(r)
        d["kind_label"] = KINDS[d["kind"]]
        d["overdue"] = d["paid_at"] is None and d["due_date"] < today
        d["due_soon"] = d["paid_at"] is None and today <= d["due_date"] <= soon
        out.append(d)
    return out


# ------------------------------------------------------------ contas a receber

def create_receivable(conn, user, perms, data):
    _need(perms)
    desc = clean(data.get("description"))
    if not desc:
        raise ApiError("Informe a descrição.")
    cid = data.get("customer_id") or None
    if cid and not conn.execute("SELECT 1 FROM customers WHERE id=?", (cid,)).fetchone():
        raise ApiError("Cliente não encontrado.")
    cur = conn.execute(
        "INSERT INTO receivables(customer_id, description, amount_cents, due_date, notes, user_id, created_at) VALUES (?,?,?,?,?,?,?)",
        (cid, desc, to_int(data.get("amount_cents"), "Valor", minimum=1), _date(data.get("due_date"), "vencimento"),
         clean(data.get("notes")), user["id"], now()))
    audit(conn, user["id"], "conta_receber_criada", "receivable", cur.lastrowid, after={"descricao": desc})
    return cur.lastrowid


def receive_receivable(conn, user, perms, rid, method=None, received_cents=None):
    _need(perms)
    row = conn.execute("SELECT * FROM receivables WHERE id=?", (rid,)).fetchone()
    if not row:
        raise ApiError("Conta não encontrada.", 404)
    if row["received_at"]:
        raise ApiError("Esta conta já foi recebida.", 409)
    val = to_int(received_cents if received_cents not in (None, "") else row["amount_cents"], "Valor recebido", minimum=1)
    conn.execute("UPDATE receivables SET received_at=?, received_cents=?, receive_method=? WHERE id=?", (now()[:10], val, clean(method), rid))
    audit(conn, user["id"], "conta_recebida", "receivable", rid, after={"valor_cents": val})


def card_receivables(conn, today=None):
    """Previsão de recebimento de cartão (líquido de taxas): parcela k vence em venda + prazo + 30*(k-1) dias."""
    today = today or now()[:10]
    card_keys = {m["key"] for m in payment_methods(conn) if m.get("type") == "card"}
    rows = []
    q = ("SELECT p.*, s.created_at AS sale_date, s.id AS sid, 'venda' AS origin FROM sale_payments p JOIN sales s ON s.id=p.sale_id"
         " WHERE s.status='concluida' UNION ALL "
         "SELECT p.id, p.order_id, p.method, p.amount_cents, p.received_cents, p.change_cents, p.installments, p.fee_cents,"
         " p.net_cents, p.rec_days, p.acquirer, p.created_at, p.order_id, 'os' FROM service_payments p WHERE p.voided_at IS NULL")
    for p in conn.execute(q):
        if p["method"] not in card_keys:
            continue
        n = max(p["installments"], 1)
        base = p["net_cents"] // n
        for k in range(1, n + 1):
            amt = base + (p["net_cents"] - base * n if k == 1 else 0)
            due = add_days(p["sale_date"], p["rec_days"] + 30 * (k - 1))
            if due >= today:
                rows.append({"due_date": due, "amount_cents": amt, "origin": p["origin"], "ref": p["sid"],
                             "method": p["method"], "installment": f"{k}/{n}", "acquirer": p["acquirer"]})
    rows.sort(key=lambda r: r["due_date"])
    return rows


def receivables_overview(conn):
    today = now()[:10]
    manual = []
    for r in conn.execute("SELECT r.*, c.name AS customer_name FROM receivables r LEFT JOIN customers c ON c.id=r.customer_id"
                          " WHERE received_at IS NULL ORDER BY due_date"):
        d = dict(r)
        d["overdue"] = d["due_date"] < today
        manual.append(d)
    pend_os = [o for o in so.search(conn, limit=2000) if o["status"] == "entregue" and o["balance_cents"] > 0]
    cards = card_receivables(conn, today)
    return {
        "manual": manual,
        "service_pending": pend_os,
        "cards": cards,
        "totals": {
            "manual_cents": sum(r["amount_cents"] for r in manual),
            "service_pending_cents": sum(o["balance_cents"] for o in pend_os),
            "cards_cents": sum(c["amount_cents"] for c in cards),
        },
    }


# ------------------------------------------------------------ taxas de cartão

def get_card_fees(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM card_fees ORDER BY acquirer, method, installments")]


def save_card_fees(conn, user, fees):
    keys = {m["key"] for m in payment_methods(conn) if m.get("type") == "card"}
    clean_rows = []
    seen = set()
    for f in fees or []:
        acq = clean(f.get("acquirer"))
        if not acq or f.get("method") not in keys:
            raise ApiError("Cada taxa precisa de adquirente e de uma modalidade de cartão válida.")
        inst = to_int(f.get("installments"), "Parcelas", minimum=1, maximum=24)
        bp = round(float(str(f.get("fee_percent", 0)).replace(",", ".")) * 100) if "fee_percent" in f else to_int(f.get("fee_bp"), "Taxa")
        if not 0 <= bp <= 10000:
            raise ApiError("A taxa deve estar entre 0% e 100%.")
        key = (acq, f["method"], inst)
        if key in seen:
            raise ApiError(f"Taxa duplicada para {acq} / {f['method']} / {inst}x.")
        seen.add(key)
        clean_rows.append((acq, f["method"], inst, bp, to_int(f.get("days", 30), "Prazo (dias)")))
    before = get_card_fees(conn)
    conn.execute("DELETE FROM card_fees")
    conn.executemany("INSERT INTO card_fees(acquirer, method, installments, fee_bp, days) VALUES (?,?,?,?,?)", clean_rows)
    audit(conn, user["id"], "taxas_cartao_alteradas", "card_fees", None, before=before, after=get_card_fees(conn))


# ------------------------------------------------------------ resumo do período

def _rng(col, a, b):
    return f"date({col}) BETWEEN '{a}' AND '{b}'"


def summary(conn, date_from, date_to):
    """Resumo financeiro. Valores em centavos.
    faturamento      = vendas concluídas - devoluções + serviços entregues
    recebimentos     = dinheiro/PIX/cartão efetivamente recebidos no período (vendas + serviços)
    custo_mercadoria = custo real das unidades vendidas (menos o custo das devolvidas que voltaram ao estoque) + peças usadas
    lucro_bruto      = faturamento - custo
    resultado        = lucro_bruto - taxas de cartão - despesas - custo de garantia
    """
    a, b = date_from, date_to
    one = lambda sql: conn.execute(sql).fetchone()
    sales = one(f"SELECT COUNT(*) n, COALESCE(SUM(total_cents),0) total, COALESCE(SUM(discount_cents),0) disc FROM sales"
                f" WHERE status='concluida' AND {_rng('created_at', a, b)}")
    cogs = one(f"SELECT COALESCE(SUM(i.unit_cost_cents*i.qty),0) c FROM sale_items i JOIN sales s ON s.id=i.sale_id"
               f" WHERE s.status='concluida' AND {_rng('s.created_at', a, b)}")["c"]
    ret = one(f"SELECT COALESCE(SUM(ri.amount_cents),0) amount, COALESCE(SUM(CASE WHEN ri.restock=1 THEN ri.cost_cents ELSE 0 END),0) restock_cost"
              f" FROM return_items ri JOIN returns r ON r.id=ri.return_id WHERE {_rng('r.created_at', a, b)}")
    svc_total = svc_cost = svc_count = svc_incomplete = 0
    for r in conn.execute(f"SELECT id FROM service_orders WHERE status='entregue' AND {_rng('delivered_at', a, b)}"):
        t = so.totals(conn, so.order_row(conn, r["id"]))
        svc_total += t["total_cents"]
        svc_cost += t["cost_cents"]
        svc_incomplete += 1 if t["cost_incomplete"] else 0
        svc_count += 1
    fees = one(f"SELECT COALESCE(SUM(p.fee_cents),0) f FROM sale_payments p JOIN sales s ON s.id=p.sale_id"
               f" WHERE s.status='concluida' AND {_rng('s.created_at', a, b)}")["f"]
    fees += one(f"SELECT COALESCE(SUM(fee_cents),0) f FROM service_payments WHERE voided_at IS NULL AND {_rng('created_at', a, b)}")["f"]
    exp = {r["kind"]: r["t"] for r in conn.execute(
        f"SELECT kind, SUM(amount_cents) t FROM payables WHERE {_rng('due_date', a, b)} GROUP BY kind")}
    warranty = one(f"SELECT COALESCE(SUM(cost_cents),0) c FROM warranty_claims WHERE cost_cents>0 AND {_rng('COALESCE(closed_at, opened_at)', a, b)}")["c"]
    by_method = {}
    for r in conn.execute(f"SELECT p.method, SUM(p.amount_cents) t FROM sale_payments p JOIN sales s ON s.id=p.sale_id"
                          f" WHERE s.status='concluida' AND {_rng('s.created_at', a, b)} GROUP BY p.method"):
        by_method[r["method"]] = r["t"]
    for r in conn.execute(f"SELECT method, SUM(amount_cents) t FROM service_payments WHERE voided_at IS NULL AND {_rng('created_at', a, b)} GROUP BY method"):
        by_method[r["method"]] = by_method.get(r["method"], 0) + r["t"]
    received = sum(by_method.values())
    faturamento = sales["total"] - ret["amount"] + svc_total
    custo = cogs - ret["restock_cost"] + svc_cost
    lucro_bruto = faturamento - custo
    despesas = exp.get("fixa", 0) + exp.get("variavel", 0)
    return {
        "from": a, "to": b,
        "sales_count": sales["n"], "sales_total_cents": sales["total"], "discounts_cents": sales["disc"],
        "returns_cents": ret["amount"],
        "services_count": svc_count, "services_total_cents": svc_total, "services_cost_incomplete": svc_incomplete,
        "revenue_cents": faturamento,
        "received_cents": received, "received_by_method": by_method,
        "cost_cents": custo, "gross_profit_cents": lucro_bruto,
        "card_fees_cents": fees,
        "expenses_fixed_cents": exp.get("fixa", 0), "expenses_variable_cents": exp.get("variavel", 0),
        "expenses_cents": despesas,
        "purchases_cents": exp.get("compra", 0),
        "warranty_cost_cents": warranty,
        "result_cents": lucro_bruto - fees - despesas - warranty,
    }


def cashflow(conn, date_from, date_to):
    days = {}

    def day(d):
        return days.setdefault(d, {"date": d, "in_cents": 0, "out_cents": 0, "in_detail": {}, "out_detail": {}})

    for r in conn.execute("SELECT date(s.created_at) d, p.method m, SUM(p.amount_cents) t FROM sale_payments p JOIN sales s ON s.id=p.sale_id"
                          " WHERE s.status='concluida' AND date(s.created_at) BETWEEN ? AND ? GROUP BY d, m", (date_from, date_to)):
        x = day(r["d"]); x["in_cents"] += r["t"]; x["in_detail"]["vendas"] = x["in_detail"].get("vendas", 0) + r["t"]
    for r in conn.execute("SELECT date(created_at) d, SUM(amount_cents) t FROM service_payments WHERE voided_at IS NULL"
                          " AND date(created_at) BETWEEN ? AND ? GROUP BY d", (date_from, date_to)):
        x = day(r["d"]); x["in_cents"] += r["t"]; x["in_detail"]["serviços"] = r["t"]
    for r in conn.execute("SELECT received_at d, SUM(received_cents) t FROM receivables WHERE received_at BETWEEN ? AND ? GROUP BY d", (date_from, date_to)):
        x = day(r["d"]); x["in_cents"] += r["t"]; x["in_detail"]["contas a receber"] = r["t"]
    for r in conn.execute("SELECT paid_at d, kind, SUM(paid_cents) t FROM payables WHERE paid_at BETWEEN ? AND ? GROUP BY d, kind", (date_from, date_to)):
        x = day(r["d"]); x["out_cents"] += r["t"]; x["out_detail"][KINDS[r["kind"]]] = r["t"]
    for r in conn.execute("SELECT date(created_at) d, SUM(refund_cents) t FROM returns WHERE refund_cents>0 AND date(created_at) BETWEEN ? AND ? GROUP BY d", (date_from, date_to)):
        x = day(r["d"]); x["out_cents"] += r["t"]; x["out_detail"]["devoluções"] = r["t"]
    rows = [days[k] for k in sorted(days)]
    bal = 0
    for r in rows:
        bal += r["in_cents"] - r["out_cents"]
        r["balance_cents"] = bal
    return {"days": rows, "in_cents": sum(r["in_cents"] for r in rows), "out_cents": sum(r["out_cents"] for r in rows)}


def periods(conn, today=None):
    today = today or now()[:10]
    d = datetime.strptime(today, "%Y-%m-%d")
    monday = (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")
    first = d.replace(day=1).strftime("%Y-%m-%d")
    return {"day": summary(conn, today, today), "week": summary(conn, monday, today), "month": summary(conn, first, today)}
