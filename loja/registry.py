"""Clientes, fornecedores, histórico de estoque e inventário com leitor de código de barras."""
from .barcode import variants
from .services import (ApiError, audit, clean, find_by_code, move_stock, now, product_row, to_int)

# ------------------------------------------------------------ clientes e fornecedores

def _party_payload(data, label):
    name = clean(data.get("name"))
    if not name:
        raise ApiError(f"Informe o nome do {label}.")
    doc = "".join(ch for ch in (data.get("doc") or "") if ch.isdigit()) or None
    if doc and len(doc) not in (11, 14):
        raise ApiError("CPF deve ter 11 dígitos e CNPJ 14 dígitos (ou deixe em branco).")
    return {"name": name, "phone": clean(data.get("phone")), "email": clean(data.get("email")), "doc": doc, "notes": clean(data.get("notes"))}


def save_party(conn, user, table, data, pid=None):
    label = "cliente" if table == "customers" else "fornecedor"
    p = _party_payload(data, label)
    if pid:
        old = conn.execute(f"SELECT * FROM {table} WHERE id=?", (pid,)).fetchone()
        if not old:
            raise ApiError("Cadastro não encontrado.", 404)
        conn.execute(f"UPDATE {table} SET name=?, phone=?, email=?, doc=?, notes=? WHERE id=?",
                     (p["name"], p["phone"], p["email"], p["doc"], p["notes"], pid))
        audit(conn, user["id"], f"{label}_alterado", table, pid, before={k: old[k] for k in p if old[k] != p[k]},
              after={k: v for k, v in p.items() if old[k] != v})
        return pid
    cur = conn.execute(f"INSERT INTO {table}(name, phone, email, doc, notes, created_at) VALUES (?,?,?,?,?,?)",
                       (p["name"], p["phone"], p["email"], p["doc"], p["notes"], now()))
    audit(conn, user["id"], f"{label}_criado", table, cur.lastrowid, after=p)
    return cur.lastrowid


def search_parties(conn, table, q="", include_inactive=False):
    sql = f"SELECT * FROM {table} WHERE 1=1"
    args = []
    if not include_inactive:
        sql += " AND active=1"
    q = (q or "").strip()
    if q:
        sql += " AND (norm(name) LIKE norm(?) OR phone LIKE ? OR doc LIKE ?)"
        args += [f"%{q}%", f"%{q}%", f"%{q}%"]
    return [dict(r) for r in conn.execute(sql + " ORDER BY name LIMIT 300", args)]


def set_party_active(conn, user, table, pid, active):
    conn.execute(f"UPDATE {table} SET active=? WHERE id=?", (1 if active else 0, pid))
    audit(conn, user["id"], "cadastro_ativado" if active else "cadastro_inativado", table, pid)


def customer_history(conn, cid):
    c = conn.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
    if not c:
        raise ApiError("Cliente não encontrado.", 404)
    sales = [dict(r) for r in conn.execute(
        "SELECT id, created_at, total_cents, status FROM sales WHERE customer_id=? ORDER BY id DESC LIMIT 200", (cid,))]
    orders = [dict(r) for r in conn.execute(
        "SELECT o.id, o.entry_at, o.brand, o.model, o.status,"
        " (SELECT COALESCE(SUM(unit_price_cents*qty),0) FROM service_order_parts p WHERE p.order_id=o.id AND p.removed_at IS NULL AND (p.part_status IS NULL OR p.part_status<>'cancelada'))"
        "  + o.labor_cents - o.discount_cents AS total_cents,"
        " (SELECT COALESCE(SUM(amount_cents),0) FROM service_payments s WHERE s.order_id=o.id AND s.voided_at IS NULL) AS paid_cents"
        " FROM service_orders o WHERE o.customer_id=? ORDER BY o.id DESC LIMIT 200", (cid,))]
    pend = [dict(r) for r in conn.execute(
        "SELECT * FROM receivables WHERE customer_id=? AND received_at IS NULL ORDER BY due_date", (cid,))]
    os_pending = sum(max(o["total_cents"] - o["paid_cents"], 0) for o in orders if o["status"] == "entregue")
    return {"customer": dict(c), "sales": sales, "orders": orders, "receivables": pend,
            "pending_cents": os_pending + sum(r["amount_cents"] for r in pend),
            "total_bought_cents": sum(s["total_cents"] for s in sales if s["status"] == "concluida")}


def supplier_history(conn, sid):
    s = conn.execute("SELECT * FROM suppliers WHERE id=?", (sid,)).fetchone()
    if not s:
        raise ApiError("Fornecedor não encontrado.", 404)
    products = [dict(r) for r in conn.execute(
        "SELECT id, name, sku, cost_cents, qty FROM products WHERE supplier=? ORDER BY name", (s["name"],))]
    entries = [dict(r) for r in conn.execute(
        "SELECT m.created_at, p.name, m.qty_delta AS qty, m.unit_cost_cents FROM stock_movements m JOIN products p ON p.id=m.product_id"
        " WHERE m.kind='entrada' AND m.reason LIKE ? ORDER BY m.id DESC LIMIT 200", (f"%Fornecedor: {s['name']}%",))]
    devices = [dict(r) for r in conn.execute(
        "SELECT id, code, brand, model, cost_cents, entry_date, status FROM devices WHERE supplier=? ORDER BY id DESC", (s["name"],))]
    payables = [dict(r) for r in conn.execute(
        "SELECT * FROM payables WHERE supplier=? ORDER BY due_date DESC LIMIT 200", (s["name"],))]
    return {"supplier": dict(s), "products": products, "entries": entries, "devices": devices, "payables": payables}


# ------------------------------------------------------------ produtos: consulta e histórico

def search_products(conn, q="", category=None, low_only=False, include_inactive=False, limit=200):
    sql, args = "SELECT * FROM products WHERE 1=1", []
    if not include_inactive:
        sql += " AND active=1"
    q = (q or "").strip()
    if q:
        sql += (" AND (norm(name||' '||COALESCE(brand,'')||' '||COALESCE(model,'')||' '||COALESCE(category,'')) LIKE norm(?)"
                " OR barcode LIKE ? OR sku LIKE ?)")
        args += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if category:
        sql += " AND category=?"
        args.append(category)
    if low_only:
        sql += " AND qty<=min_qty"
    sql += " ORDER BY name LIMIT ?"
    args.append(limit)
    return [dict(r) for r in conn.execute(sql, args)]


def product_history(conn, pid):
    product_row(conn, pid)
    moves = [dict(r) for r in conn.execute(
        "SELECT m.*, u.name AS user_name, a.name AS authorized_name FROM stock_movements m LEFT JOIN users u ON u.id=m.user_id"
        " LEFT JOIN users a ON a.id=m.authorized_by WHERE product_id=? ORDER BY m.id DESC LIMIT 500", (pid,))]
    sales = [dict(r) for r in conn.execute(
        "SELECT s.id, s.created_at, i.qty, i.unit_price_cents, i.total_cents, s.status FROM sale_items i JOIN sales s ON s.id=i.sale_id"
        " WHERE i.product_id=? ORDER BY s.id DESC LIMIT 100", (pid,))]
    return {"movements": moves, "sales": sales}


def transfer_location(conn, user, perms, pid, new_location, note=None):
    """Transferência de local físico do produto (o saldo não muda; fica registrado na auditoria)."""
    if "movimentar_estoque" not in perms:
        raise ApiError("Sem permissão para movimentar estoque.", 403)
    row = product_row(conn, pid)
    new_location = clean(new_location)
    if not new_location:
        raise ApiError("Informe o novo local.")
    if new_location == row["location"]:
        raise ApiError("O produto já está neste local.")
    conn.execute("UPDATE products SET location=? WHERE id=?", (new_location, pid))
    audit(conn, user["id"], "transferencia_local", "product", pid, before={"local": row["location"]},
          after={"local": new_location, "obs": clean(note)})


def categories(conn):
    return [r[0] for r in conn.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL ORDER BY category")]


# ------------------------------------------------------------ inventário por leitor

def start_count(conn, user, perms, name):
    if "ajustar_estoque" not in perms:
        raise ApiError("Sem permissão para fazer inventário.", 403)
    if conn.execute("SELECT 1 FROM inventory_counts WHERE status='aberto'").fetchone():
        raise ApiError("Já existe um inventário aberto. Finalize ou cancele antes de iniciar outro.", 409)
    name = clean(name) or f"Inventário {now()[:10]}"
    cur = conn.execute("INSERT INTO inventory_counts(name, created_by, created_at) VALUES (?,?,?)", (name, user["id"], now()))
    audit(conn, user["id"], "inventario_iniciado", "inventory_count", cur.lastrowid, after={"nome": name})
    return cur.lastrowid


def count_scan(conn, user, perms, count_id, code, qty=1):
    if "ajustar_estoque" not in perms:
        raise ApiError("Sem permissão.", 403)
    c = conn.execute("SELECT * FROM inventory_counts WHERE id=?", (count_id,)).fetchone()
    if not c or c["status"] != "aberto":
        raise ApiError("Inventário não está aberto.", 409)
    prod = find_by_code(conn, code)
    if not prod:
        raise ApiError(f"Código {code} não cadastrado.", 404, "unknown_code")
    qty = to_int(qty, "Quantidade", minimum=1, maximum=100000)
    conn.execute(
        "INSERT INTO inventory_count_items(count_id, product_id, counted_qty) VALUES (?,?,?)"
        " ON CONFLICT(count_id, product_id) DO UPDATE SET counted_qty=counted_qty+excluded.counted_qty", (count_id, prod["id"], qty))
    counted = conn.execute("SELECT counted_qty FROM inventory_count_items WHERE count_id=? AND product_id=?", (count_id, prod["id"])).fetchone()[0]
    return {"product": {"id": prod["id"], "name": prod["name"], "sku": prod["sku"]}, "counted_qty": counted, "system_qty": prod["qty"]}


def count_set(conn, user, perms, count_id, product_id, qty):
    c = conn.execute("SELECT * FROM inventory_counts WHERE id=?", (count_id,)).fetchone()
    if not c or c["status"] != "aberto":
        raise ApiError("Inventário não está aberto.", 409)
    if "ajustar_estoque" not in perms:
        raise ApiError("Sem permissão.", 403)
    product_row(conn, product_id)
    qty = to_int(qty, "Quantidade contada")
    conn.execute(
        "INSERT INTO inventory_count_items(count_id, product_id, counted_qty) VALUES (?,?,?)"
        " ON CONFLICT(count_id, product_id) DO UPDATE SET counted_qty=excluded.counted_qty", (count_id, product_id, qty))


def count_detail(conn, count_id, show_all=False):
    c = conn.execute("SELECT i.*, u.name AS user_name FROM inventory_counts i JOIN users u ON u.id=i.created_by WHERE i.id=?", (count_id,)).fetchone()
    if not c:
        raise ApiError("Inventário não encontrado.", 404)
    rows = [dict(r) for r in conn.execute(
        "SELECT ci.product_id, p.name, p.sku, p.barcode, p.qty AS system_qty, ci.counted_qty,"
        " ci.counted_qty - p.qty AS diff FROM inventory_count_items ci JOIN products p ON p.id=ci.product_id"
        " WHERE ci.count_id=? ORDER BY ci.id DESC", (count_id,))]
    uncounted = [dict(r) for r in conn.execute(
        "SELECT id AS product_id, name, sku, barcode, qty AS system_qty FROM products WHERE active=1 AND qty<>0"
        " AND id NOT IN (SELECT product_id FROM inventory_count_items WHERE count_id=?) ORDER BY name", (count_id,))]
    return {"count": dict(c), "items": rows, "uncounted": uncounted}


def finish_count(conn, user, perms, count_id, zero_uncounted=False):
    if "ajustar_estoque" not in perms:
        raise ApiError("Sem permissão para ajustar estoque.", 403)
    d = count_detail(conn, count_id)
    if d["count"]["status"] != "aberto":
        raise ApiError("Inventário já encerrado.", 409)
    adjusted = 0
    targets = [(r["product_id"], r["counted_qty"]) for r in d["items"]]
    if zero_uncounted:
        targets += [(r["product_id"], 0) for r in d["uncounted"]]
    for pid, counted in targets:
        row = product_row(conn, pid)
        delta = counted - row["qty"]
        if delta:
            move_stock(conn, pid, "ajuste", delta, user["id"], f"Inventário #{count_id}: contagem {counted}, sistema {row['qty']}",
                       unit_cost=row["cost_cents"], ref_type="inventory", ref_id=count_id, allow_negative=False)
            adjusted += 1
    conn.execute("UPDATE inventory_counts SET status='finalizado', finished_at=?, finished_by=? WHERE id=?", (now(), user["id"], count_id))
    audit(conn, user["id"], "inventario_finalizado", "inventory_count", count_id,
          after={"produtos_ajustados": adjusted, "nao_lidos_zerados": bool(zero_uncounted)})
    return adjusted


def cancel_count(conn, user, perms, count_id):
    if "ajustar_estoque" not in perms:
        raise ApiError("Sem permissão.", 403)
    cur = conn.execute("UPDATE inventory_counts SET status='cancelado', finished_at=?, finished_by=? WHERE id=? AND status='aberto'",
                       (now(), user["id"], count_id))
    if cur.rowcount != 1:
        raise ApiError("Inventário não está aberto.", 409)
    audit(conn, user["id"], "inventario_cancelado", "inventory_count", count_id)
