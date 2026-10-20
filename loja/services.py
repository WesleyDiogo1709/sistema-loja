"""Regras de negócio. Todas as funções recebem uma conexão SQLite; as que alteram dados
devem ser chamadas dentro de `db.tx(conn)` (o chamador controla a transação)."""
import json
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from .barcode import classify, normalize, variants


class ApiError(Exception):
    def __init__(self, message, status=400, code=None, **extra):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.extra = extra


# ---------------------------------------------------------------- configuração padrão

PERMISSIONS = {
    "vender": "Realizar vendas no PDV",
    "aplicar_descontos": "Aplicar descontos",
    "cancelar_vendas": "Cancelar vendas",
    "ver_custos": "Ver custos de aquisição",
    "ver_lucros": "Consultar lucros",
    "ver_financeiro": "Consultar informações financeiras e todas as vendas",
    "alterar_precos": "Alterar preços",
    "gerenciar_produtos": "Cadastrar e editar produtos",
    "movimentar_estoque": "Registrar entradas e saídas de estoque",
    "ajustar_estoque": "Ajustar estoque",
    "estoque_negativo": "Autorizar estoque negativo",
    "gerenciar_caixa": "Abrir/fechar caixa, sangria e reforço",
    "ver_clientes": "Acessar dados de clientes",
    "ver_auditoria": "Ver registro de auditoria",
    "gerenciar_usuarios": "Gerenciar usuários e permissões",
    "gerenciar_backup": "Fazer e restaurar backups",
    "gerenciar_config": "Alterar configurações do sistema",
    "gerenciar_aparelhos": "Cadastrar e editar aparelhos (IMEI/série)",
    "gerenciar_os": "Gerenciar ordens de serviço (assistência técnica)",
    "gerenciar_financeiro": "Lançar contas a pagar/receber e despesas",
    "registrar_devolucoes": "Registrar devoluções e trocas",
    "gerenciar_garantias": "Gerenciar reclamações de garantia",
    "ver_relatorios": "Consultar relatórios",
}

ROLES = ("administrador", "gerente", "vendedor", "tecnico")

DEFAULT_ROLE_PERMS = {
    "gerente": [
        "vender", "aplicar_descontos", "cancelar_vendas", "ver_custos", "ver_lucros",
        "ver_financeiro", "alterar_precos", "gerenciar_produtos", "movimentar_estoque",
        "ajustar_estoque", "gerenciar_caixa", "ver_clientes", "ver_auditoria", "gerenciar_backup",
        "gerenciar_aparelhos", "gerenciar_os", "gerenciar_financeiro", "registrar_devolucoes",
        "gerenciar_garantias", "ver_relatorios",
    ],
    "vendedor": ["vender", "gerenciar_caixa", "ver_clientes", "gerenciar_os"],
    "tecnico": ["gerenciar_os", "gerenciar_garantias"],
}

DEFAULT_PAYMENT_METHODS = [
    {"key": "dinheiro", "label": "Dinheiro", "type": "cash"},
    {"key": "pix", "label": "PIX", "type": "other"},
    {"key": "debito", "label": "Cartão de débito", "type": "card"},
    {"key": "credito", "label": "Cartão de crédito", "type": "card", "installments": True},
]

DEFAULT_SETTINGS = {
    "store_name": "Minha Loja de Eletrônicos",
    "store_info": "",
    "receipt_footer": "Obrigado pela preferência! Comprovante sem valor fiscal.",
    "scanner_suffix": "enter",      # enter | tab | nenhum
    "scanner_min_length": "6",      # usado quando o sufixo é "nenhum"
    "max_installments": "12",
    "default_acquirer": "",
    "os_term_days": "30",            # dias parado em "pronto para retirada" até aparecer como não retirado
    "inactive_days": "60",           # dias sem venda para um produto ser considerado parado
    "default_warranty_days": "90",   # garantia legal mínima para bens duráveis (CDC art. 26, II)
    "backup_keep": "30",
    "auto_print_receipt": "0",
    "payment_methods": json.dumps(DEFAULT_PAYMENT_METHODS, ensure_ascii=False),
}

PRODUCT_TEXT_FIELDS = ("category", "brand", "model", "description", "supplier", "location", "notes")
STOCK_OUT_KINDS = {"saida": "Saída manual", "perda": "Perda", "avaria": "Avaria", "troca": "Produto para troca"}


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def seed_defaults(conn):
    for role, perms in DEFAULT_ROLE_PERMS.items():
        for p in perms:
            conn.execute("INSERT OR IGNORE INTO role_permissions(role, permission) VALUES (?,?)", (role, p))
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?,?)", (k, v))
    # Usuário inicial: a senha deve ser trocada no primeiro acesso.
    conn.execute(
        "INSERT INTO users(username, name, password_hash, role, must_change_password) VALUES (?,?,?,?,1)",
        ("admin", "Administrador", generate_password_hash("admin123"), "administrador"),
    )


# ---------------------------------------------------------------- utilidades

def audit(conn, user_id, action, entity, entity_id=None, before=None, after=None, authorized_by=None):
    conn.execute(
        "INSERT INTO audit_log(user_id, authorized_by, action, entity, entity_id, before_json, after_json, created_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (
            user_id, authorized_by, action, entity, entity_id,
            json.dumps(before, ensure_ascii=False, default=str) if before is not None else None,
            json.dumps(after, ensure_ascii=False, default=str) if after is not None else None,
            now(),
        ),
    )


def get_settings(conn):
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}


def payment_methods(conn):
    try:
        return json.loads(get_settings(conn).get("payment_methods") or "[]") or DEFAULT_PAYMENT_METHODS
    except ValueError:
        return DEFAULT_PAYMENT_METHODS


def permissions_of(conn, user):
    if user["role"] == "administrador":
        return set(PERMISSIONS)
    rows = conn.execute("SELECT permission FROM role_permissions WHERE role=?", (user["role"],))
    return {r["permission"] for r in rows} & set(PERMISSIONS)


def check_credentials(conn, username, password):
    row = conn.execute("SELECT * FROM users WHERE username=? AND active=1", ((username or "").strip(),)).fetchone()
    if row and check_password_hash(row["password_hash"], password or ""):
        return row
    return None


def authorize(conn, user, perms, permission, auth=None):
    """Retorna o ID de quem autoriza. Se o usuário atual não tem a permissão, aceita as credenciais
    de um supervisor (`auth = {username, password}`) que a possua."""
    if permission in perms:
        return user["id"]
    if auth and auth.get("username"):
        sup = check_credentials(conn, auth.get("username"), auth.get("password"))
        if not sup:
            raise ApiError("Usuário ou senha do supervisor inválidos.", 403, "authorization_invalid")
        if permission in permissions_of(conn, sup):
            return sup["id"]
        raise ApiError("O supervisor informado não tem permissão para autorizar esta operação.", 403, "authorization_invalid")
    raise ApiError(
        f"Esta operação requer autorização ({PERMISSIONS.get(permission, permission)}).",
        403, "authorization_required", permission=permission,
    )


def to_int(value, label, minimum=0, maximum=None):
    if isinstance(value, bool):
        raise ApiError(f"Valor inválido em {label}.")
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ApiError(f"Valor inválido em {label}.")
    if n < minimum:
        raise ApiError(f"{label} não pode ser menor que {minimum}.")
    if maximum is not None and n > maximum:
        raise ApiError(f"{label} não pode ser maior que {maximum}.")
    return n


def warranty_days(value, default=90):
    """Garantia em dias. O mínimo é 90 (garantia legal para bens duráveis, CDC art. 26, II): não é possível reduzir."""
    if value in (None, ""):
        return default
    n = to_int(value, "Garantia (dias)", minimum=0, maximum=3650)
    if n < 90:
        raise ApiError("A garantia não pode ser menor que 90 dias (garantia legal do Código de Defesa do Consumidor para bens duráveis).")
    return n


def clean(value):
    value = (value or "").strip() if isinstance(value, str) else value
    return value or None


# ---------------------------------------------------------------- produtos

def product_row(conn, product_id):
    row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    if not row:
        raise ApiError("Produto não encontrado.", 404)
    return row


def find_by_code(conn, code):
    """Busca por código de barras (inclui equivalência UPC-A/EAN-13) ou SKU/código interno."""
    for v in variants(code):
        row = conn.execute("SELECT * FROM products WHERE barcode=? OR sku=?", (v, v)).fetchone()
        if row:
            return row
    return None


def _check_unique(conn, codes, exclude_id=None):
    for code in codes:
        if not code:
            continue
        for v in variants(code):
            row = conn.execute(
                "SELECT id, name FROM products WHERE (barcode=? OR sku=?) AND id<>?", (v, v, exclude_id or 0)
            ).fetchone()
            if row:
                raise ApiError(
                    f"O código {v} já está cadastrado no produto \"{row['name']}\".", 409, "duplicate_code"
                )


def _product_payload(data):
    name = clean(data.get("name"))
    if not name:
        raise ApiError("Informe o nome do produto.")
    try:
        barcode, btype = classify(data.get("barcode"), bool(data.get("barcode_internal")))
    except ValueError as e:
        raise ApiError(str(e), 400, "invalid_barcode")
    sku = normalize(data.get("sku")) or None
    out = {
        "name": name,
        "barcode": barcode,
        "barcode_type": btype,
        "sku": sku,
        "cost_cents": to_int(data.get("cost_cents", 0), "Custo"),
        "price_cents": to_int(data.get("price_cents", 0), "Preço de venda"),
        "min_qty": to_int(data.get("min_qty", 0), "Estoque mínimo"),
        "warranty_days": warranty_days(data.get("warranty_days")),
    }
    for f in PRODUCT_TEXT_FIELDS:
        out[f] = clean(data.get(f))
    return out


def create_product(conn, user, perms, data):
    if "gerenciar_produtos" not in perms:
        raise ApiError("Sem permissão para cadastrar produtos.", 403)
    p = _product_payload(data)
    initial = to_int(data.get("qty", 0), "Quantidade inicial")
    _check_unique(conn, [p["barcode"], p["sku"]])
    cols = list(p)
    cur = conn.execute(
        f"INSERT INTO products({','.join(cols)}, qty, created_at) VALUES ({','.join('?' * len(cols))}, 0, ?)",
        [p[c] for c in cols] + [now()],
    )
    pid = cur.lastrowid
    if not p["sku"]:
        conn.execute("UPDATE products SET sku=? WHERE id=?", (f"P{pid:06d}", pid))
    if initial:
        move_stock(conn, pid, "entrada_inicial", initial, user["id"], "Estoque inicial", unit_cost=p["cost_cents"])
    audit(conn, user["id"], "produto_criado", "product", pid, after={**p, "qty": initial})
    return product_row(conn, pid)


def update_product(conn, user, perms, product_id, data):
    if "gerenciar_produtos" not in perms:
        raise ApiError("Sem permissão para editar produtos.", 403)
    old = product_row(conn, product_id)
    p = _product_payload({**dict(old), "barcode_internal": old["barcode_type"] == "INTERNO", **data})
    if p["price_cents"] != old["price_cents"] and "alterar_precos" not in perms:
        raise ApiError("Sem permissão para alterar preços.", 403)
    if p["cost_cents"] != old["cost_cents"] and "ver_custos" not in perms:
        raise ApiError("Sem permissão para alterar custos.", 403)
    if not p["sku"]:
        p["sku"] = old["sku"]
    _check_unique(conn, [p["barcode"], p["sku"]], exclude_id=product_id)
    sets = ", ".join(f"{c}=?" for c in p)
    conn.execute(f"UPDATE products SET {sets} WHERE id=?", list(p.values()) + [product_id])
    before = {k: old[k] for k in p}
    audit(conn, user["id"], "produto_alterado", "product", product_id,
          before={k: v for k, v in before.items() if v != p[k]}, after={k: v for k, v in p.items() if v != before[k]})
    return product_row(conn, product_id)


def set_product_active(conn, user, perms, product_id, active):
    if "gerenciar_produtos" not in perms:
        raise ApiError("Sem permissão para alterar produtos.", 403)
    product_row(conn, product_id)
    conn.execute("UPDATE products SET active=? WHERE id=?", (1 if active else 0, product_id))
    audit(conn, user["id"], "produto_ativado" if active else "produto_inativado", "product", product_id)


# ---------------------------------------------------------------- estoque

def move_stock(conn, product_id, kind, delta, user_id, reason=None, unit_cost=None,
               ref_type=None, ref_id=None, allow_negative=False, authorized_by=None):
    """Única porta de entrada para alterar estoque. Registra quantidade antes/depois."""
    if delta == 0:
        raise ApiError("A quantidade da movimentação não pode ser zero.")
    row = product_row(conn, product_id)
    before = row["qty"]
    after = before + delta
    if after < 0 and not allow_negative:
        raise ApiError(
            f"Estoque insuficiente para \"{row['name']}\" (disponível: {before}).", 409, "insufficient_stock",
            product_id=product_id, available=before,
        )
    # UPDATE condicional protege contra corrida entre operações simultâneas.
    if allow_negative:
        cur = conn.execute("UPDATE products SET qty=qty+? WHERE id=?", (delta, product_id))
    else:
        cur = conn.execute("UPDATE products SET qty=qty+? WHERE id=? AND qty+?>=0", (delta, product_id, delta))
    if cur.rowcount != 1:
        raise ApiError(f"Estoque insuficiente para \"{row['name']}\".", 409, "insufficient_stock", product_id=product_id)
    conn.execute(
        "INSERT INTO stock_movements(product_id, kind, qty_delta, qty_before, qty_after, unit_cost_cents,"
        " reason, user_id, authorized_by, ref_type, ref_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (product_id, kind, delta, before, after, unit_cost, reason, user_id, authorized_by, ref_type, ref_id, now()),
    )
    return after


def stock_entry(conn, user, perms, product_id, qty, unit_cost_cents=None, supplier=None, note=None):
    if "movimentar_estoque" not in perms:
        raise ApiError("Sem permissão para registrar entradas de estoque.", 403)
    qty = to_int(qty, "Quantidade", minimum=1)
    row = product_row(conn, product_id)
    new_cost = row["cost_cents"]
    if unit_cost_cents is not None and unit_cost_cents != "":
        if "ver_custos" not in perms:
            raise ApiError("Sem permissão para informar custos.", 403)
        cost = to_int(unit_cost_cents, "Custo unitário")
        base_qty = max(row["qty"], 0)
        # Custo médio ponderado entre o estoque atual e a nova compra.
        new_cost = round((base_qty * row["cost_cents"] + qty * cost) / (base_qty + qty))
        conn.execute("UPDATE products SET cost_cents=? WHERE id=?", (new_cost, product_id))
    else:
        cost = None
    if supplier:
        conn.execute("UPDATE products SET supplier=? WHERE id=?", (supplier.strip(), product_id))
    reason = " · ".join(x for x in [f"Fornecedor: {supplier.strip()}" if supplier else None, (note or "").strip() or None] if x) or "Entrada de mercadoria"
    after = move_stock(conn, product_id, "entrada", qty, user["id"], reason, unit_cost=cost)
    audit(conn, user["id"], "entrada_estoque", "product", product_id,
          before={"qty": row["qty"], "cost_cents": row["cost_cents"]}, after={"qty": after, "cost_cents": new_cost})
    return product_row(conn, product_id)


def stock_exit(conn, user, perms, product_id, qty, kind, reason):
    if "movimentar_estoque" not in perms:
        raise ApiError("Sem permissão para registrar saídas de estoque.", 403)
    if kind not in STOCK_OUT_KINDS:
        raise ApiError("Tipo de saída inválido.")
    qty = to_int(qty, "Quantidade", minimum=1)
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise ApiError("Informe a justificativa da saída.")
    row = product_row(conn, product_id)
    after = move_stock(conn, product_id, kind, -qty, user["id"], reason, unit_cost=row["cost_cents"])
    audit(conn, user["id"], f"estoque_{kind}", "product", product_id,
          before={"qty": row["qty"]}, after={"qty": after, "motivo": reason})
    return product_row(conn, product_id)


def stock_adjust(conn, user, perms, product_id, new_qty, reason):
    if "ajustar_estoque" not in perms:
        raise ApiError("Sem permissão para ajustar estoque.", 403)
    new_qty = to_int(new_qty, "Quantidade contada")
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise ApiError("Informe o motivo do ajuste.")
    row = product_row(conn, product_id)
    delta = new_qty - row["qty"]
    if delta == 0:
        raise ApiError("A quantidade informada é igual ao estoque atual.")
    move_stock(conn, product_id, "ajuste", delta, user["id"], reason, unit_cost=row["cost_cents"])
    audit(conn, user["id"], "ajuste_estoque", "product", product_id,
          before={"qty": row["qty"]}, after={"qty": new_qty, "motivo": reason})
    return product_row(conn, product_id)


# ---------------------------------------------------------------- caixa

def open_cash(conn):
    return conn.execute("SELECT * FROM cash_sessions WHERE closed_at IS NULL").fetchone()


def cash_summary(conn, session):
    sid = session["id"]
    by_method = {}
    for r in conn.execute(
            "SELECT p.method, SUM(p.amount_cents) AS total FROM sale_payments p JOIN sales s ON s.id=p.sale_id"
            " WHERE s.cash_session_id=? AND s.status='concluida' GROUP BY p.method", (sid,)):
        by_method[r["method"]] = by_method.get(r["method"], 0) + r["total"]
    service_in = 0
    for r in conn.execute(
            "SELECT method, SUM(amount_cents) AS total FROM service_payments WHERE cash_session_id=? AND voided_at IS NULL"
            " GROUP BY method", (sid,)):
        by_method[r["method"]] = by_method.get(r["method"], 0) + r["total"]
        service_in += r["total"]
    sales = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(total_cents),0) AS total FROM sales WHERE cash_session_id=? AND status='concluida'",
        (sid,)).fetchone()
    mv = {r["kind"]: r["total"] for r in conn.execute(
        "SELECT kind, SUM(amount_cents) AS total FROM cash_movements WHERE session_id=? GROUP BY kind", (sid,))}
    cash_methods = {m["key"] for m in payment_methods(conn) if m.get("type") == "cash"}
    cash_sales = sum(v for k, v in by_method.items() if k in cash_methods)
    expected = session["opening_cents"] + cash_sales + mv.get("reforco", 0) - mv.get("sangria", 0) - mv.get("devolucao", 0)
    return {
        "opening_cents": session["opening_cents"],
        "sales_count": sales["n"],
        "sales_total_cents": sales["total"],
        "service_received_cents": service_in,
        "by_method": by_method,
        "cash_sales_cents": cash_sales,
        "reforco_cents": mv.get("reforco", 0),
        "sangria_cents": mv.get("sangria", 0),
        "refunds_cents": mv.get("devolucao", 0),
        "expected_cash_cents": expected,
    }


def cash_open(conn, user, perms, opening_cents):
    if "gerenciar_caixa" not in perms:
        raise ApiError("Sem permissão para abrir o caixa.", 403)
    if open_cash(conn):
        raise ApiError("Já existe um caixa aberto.", 409)
    opening = to_int(opening_cents, "Valor inicial")
    cur = conn.execute("INSERT INTO cash_sessions(opened_by, opened_at, opening_cents) VALUES (?,?,?)", (user["id"], now(), opening))
    audit(conn, user["id"], "caixa_aberto", "cash_session", cur.lastrowid, after={"opening_cents": opening})
    return cur.lastrowid


def cash_movement(conn, user, perms, kind, amount_cents, reason):
    if "gerenciar_caixa" not in perms:
        raise ApiError("Sem permissão para movimentar o caixa.", 403)
    if kind not in ("sangria", "reforco"):
        raise ApiError("Tipo de movimentação inválido.")
    session = open_cash(conn)
    if not session:
        raise ApiError("Não há caixa aberto.", 409)
    amount = to_int(amount_cents, "Valor", minimum=1)
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise ApiError("Informe o motivo.")
    if kind == "sangria" and amount > cash_summary(conn, session)["expected_cash_cents"]:
        raise ApiError("A sangria é maior que o dinheiro disponível no caixa.", 409)
    cur = conn.execute(
        "INSERT INTO cash_movements(session_id, kind, amount_cents, reason, user_id, created_at) VALUES (?,?,?,?,?,?)",
        (session["id"], kind, amount, reason, user["id"], now()))
    audit(conn, user["id"], f"caixa_{kind}", "cash_session", session["id"], after={"valor": amount, "motivo": reason})
    return cur.lastrowid


def cash_close(conn, user, perms, counted_cents, notes=None):
    if "gerenciar_caixa" not in perms:
        raise ApiError("Sem permissão para fechar o caixa.", 403)
    session = open_cash(conn)
    if not session:
        raise ApiError("Não há caixa aberto.", 409)
    counted = to_int(counted_cents, "Valor contado")
    summary = cash_summary(conn, session)
    diff = counted - summary["expected_cash_cents"]
    notes = (notes or "").strip() or None
    if diff != 0 and not notes:
        raise ApiError("Há diferença no caixa: informe uma observação para fechar.", 400, "notes_required",
                       difference_cents=diff)
    conn.execute(
        "UPDATE cash_sessions SET closed_at=?, closed_by=?, expected_cents=?, counted_cents=?, notes=? WHERE id=?",
        (now(), user["id"], summary["expected_cash_cents"], counted, notes, session["id"]))
    audit(conn, user["id"], "caixa_fechado", "cash_session", session["id"],
          before={"esperado": summary["expected_cash_cents"]}, after={"contado": counted, "diferenca": diff})
    return {"session_id": session["id"], "expected_cents": summary["expected_cash_cents"], "counted_cents": counted, "difference_cents": diff}


# ---------------------------------------------------------------- vendas

def card_fee(conn, method_key, installments):
    """Taxa (em centésimos de %), prazo e adquirente cadastrados para a modalidade/parcelas."""
    acq = get_settings(conn).get("default_acquirer", "")
    row = conn.execute(
        "SELECT * FROM card_fees WHERE method=? AND installments<=? ORDER BY (acquirer=?) DESC, installments DESC LIMIT 1",
        (method_key, installments, acq)).fetchone()
    if row:
        return row["fee_bp"], row["days"], row["acquirer"]
    return 0, (30 if installments > 1 or method_key == "credito" else 1), None


def build_payments(conn, raw_payments, expected_total, label="venda"):
    """Valida e normaliza pagamentos (troco, parcelas, taxa estimada). Soma deve fechar o total."""
    methods = {m["key"]: m for m in payment_methods(conn)}
    max_inst = to_int(get_settings(conn).get("max_installments", 12), "Parcelas", minimum=1)
    pays, paid = [], 0
    for p in raw_payments or []:
        m = methods.get(p.get("method"))
        if not m:
            raise ApiError("Forma de pagamento inválida.")
        amount = to_int(p.get("amount_cents"), "Valor do pagamento", minimum=1)
        received = to_int(p.get("received_cents", amount), "Valor recebido")
        if m.get("type") == "cash":
            if received < amount:
                raise ApiError("O valor recebido em dinheiro é menor que o valor a pagar.")
        else:
            received = amount
        inst = to_int(p.get("installments", 1), "Parcelas", minimum=1, maximum=max_inst) if m.get("installments") else 1
        fee = 0
        days = 0
        acq = None
        if m.get("type") == "card":
            bp, days, acq = card_fee(conn, m["key"], inst)
            fee = (amount * bp + 5000) // 10000
        pays.append({"method": m["key"], "amount": amount, "received": received, "change": received - amount,
                     "inst": inst, "fee": fee, "net": amount - fee, "days": days, "acq": acq})
        paid += amount
    if expected_total is not None and paid != expected_total:
        raise ApiError(
            f"A soma dos pagamentos ({money(paid)}) é diferente do total da {label} ({money(expected_total)}).",
            400, "payment_mismatch")
    return pays, paid


def money(cents):
    s = f"{abs(cents) / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if cents < 0 else "") + "R$ " + s


def add_days(date_str, days):
    from datetime import timedelta
    return (datetime.strptime(date_str[:10], "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def create_sale(conn, user, perms, data):
    """Cria uma venda de forma atômica e idempotente (pelo `client_token`)."""
    if "vender" not in perms:
        raise ApiError("Sem permissão para realizar vendas.", 403)
    token = (data.get("client_token") or "").strip()
    if len(token) < 8:
        raise ApiError("Requisição de venda inválida (identificador ausente).")
    existing = conn.execute("SELECT id FROM sales WHERE client_token=?", (token,)).fetchone()
    if existing:
        return existing["id"], True

    session = open_cash(conn)
    if not session:
        raise ApiError("Abra o caixa antes de realizar vendas.", 409, "cash_closed")

    raw_items = data.get("items") or []
    if not raw_items:
        raise ApiError("O carrinho está vazio.")
    auth = data.get("authorization")

    # Consolida linhas do mesmo produto; aparelhos são sempre unidades individuais.
    lines = {}
    for it in raw_items:
        disc = to_int(it.get("discount_cents", 0), "Desconto")
        if it.get("device_id"):
            did = to_int(it.get("device_id"), "Aparelho", minimum=1)
            if ("d", did) in lines:
                raise ApiError("O mesmo aparelho foi adicionado mais de uma vez ao carrinho.")
            lines[("d", did)] = {"qty": 1, "discount": disc}
        else:
            pid = to_int(it.get("product_id"), "Produto", minimum=1)
            qty = to_int(it.get("qty"), "Quantidade", minimum=1, maximum=10000)
            cur = lines.setdefault(("p", pid), {"qty": 0, "discount": 0})
            cur["qty"] += qty
            cur["discount"] += disc

    today = now()[:10]
    items, subtotal, discount_total = [], 0, 0
    for (kind, ident), ln in lines.items():
        if kind == "p":
            prod = product_row(conn, ident)
            if not prod["active"]:
                raise ApiError(f"O produto \"{prod['name']}\" está inativo.", 409)
            name, price, cost, wdays = prod["name"], prod["price_cents"], prod["cost_cents"], prod["warranty_days"]
            dev = None
        else:
            dev = conn.execute("SELECT * FROM devices WHERE id=?", (ident,)).fetchone()
            if not dev:
                raise ApiError("Aparelho não encontrado.", 404)
            if dev["status"] != "disponivel":
                raise ApiError(
                    f"O aparelho {dev['code']} ({dev['brand']} {dev['model']}) não está disponível para venda "
                    f"(situação: {DEVICE_STATUS.get(dev['status'], dev['status'])}).", 409, "device_unavailable")
            prod = None
            name = device_label(dev)
            price, cost, wdays = dev["price_cents"], dev["cost_cents"], dev["warranty_days"]
        gross = price * ln["qty"]  # preço sempre vem do banco, nunca do cliente
        if ln["discount"] > gross:
            raise ApiError(f"O desconto de \"{name}\" é maior que o valor do item.")
        items.append({"prod": prod, "dev": dev, "name": name, "price": price, "cost": cost, "wdays": wdays,
                      "qty": ln["qty"], "discount": ln["discount"], "gross": gross})
        subtotal += gross
        discount_total += ln["discount"]
    total = subtotal - discount_total
    if total <= 0:
        raise ApiError("O total da venda deve ser maior que zero.")

    authorized_by = None
    if discount_total > 0:
        authorized_by = authorize(conn, user, perms, "aplicar_descontos", auth)

    pays, _ = build_payments(conn, data.get("payments"), total)

    customer_id = data.get("customer_id")
    if customer_id:
        if not conn.execute("SELECT 1 FROM customers WHERE id=?", (customer_id,)).fetchone():
            raise ApiError("Cliente não encontrado.")

    # Estoque: verifica e baixa. Falta de estoque exige autorização de quem pode ter estoque negativo.
    neg_auth = None
    for it in items:
        if it["prod"] is not None and it["prod"]["qty"] < it["qty"]:
            neg_auth = neg_auth or authorize(conn, user, perms, "estoque_negativo", auth)
    cur = conn.execute(
        "INSERT INTO sales(client_token, cash_session_id, user_id, customer_id, subtotal_cents, discount_cents,"
        " total_cents, authorized_by, notes, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (token, session["id"], user["id"], customer_id or None, subtotal, discount_total, total,
         authorized_by, clean(data.get("notes")), now()))
    sale_id = cur.lastrowid
    for it in items:
        prod, dev = it["prod"], it["dev"]
        conn.execute(
            "INSERT INTO sale_items(sale_id, product_id, device_id, product_name, qty, unit_price_cents, unit_cost_cents,"
            " discount_cents, total_cents, warranty_days, warranty_ends) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (sale_id, prod["id"] if prod else None, dev["id"] if dev else None, it["name"], it["qty"], it["price"],
             it["cost"], it["discount"], it["gross"] - it["discount"], it["wdays"], add_days(today, it["wdays"])))
        if prod is not None:
            short = prod["qty"] < it["qty"]
            move_stock(conn, prod["id"], "venda", -it["qty"], user["id"], f"Venda #{sale_id}",
                       unit_cost=prod["cost_cents"], ref_type="sale", ref_id=sale_id,
                       allow_negative=short, authorized_by=neg_auth if short else None)
        else:
            cur = conn.execute("UPDATE devices SET status='vendido' WHERE id=? AND status='disponivel'", (dev["id"],))
            if cur.rowcount != 1:  # outro atendimento vendeu o aparelho no mesmo instante
                raise ApiError(f"O aparelho {dev['code']} acabou de ficar indisponível.", 409, "device_unavailable")
            device_event(conn, dev["id"], "venda", "vendido", user["id"], f"Venda #{sale_id}", "sale", sale_id)
    for p in pays:
        conn.execute(
            "INSERT INTO sale_payments(sale_id, method, amount_cents, received_cents, change_cents, installments,"
            " fee_cents, net_cents, rec_days, acquirer) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (sale_id, p["method"], p["amount"], p["received"], p["change"], p["inst"], p["fee"], p["net"], p["days"], p["acq"]))
    audit(conn, user["id"], "venda_criada", "sale", sale_id,
          after={"total_cents": total, "desconto_cents": discount_total, "itens": len(items)},
          authorized_by=authorized_by if authorized_by != user["id"] else None)
    return sale_id, False


DEVICE_STATUS = {
    "disponivel": "Disponível", "reservado": "Reservado", "vendido": "Vendido", "em_teste": "Em teste",
    "em_manutencao": "Em manutenção", "devolvido": "Devolvido",
}


def device_label(d):
    parts = [d["brand"], d["model"], d["storage"], d["color"]]
    return " ".join(x for x in parts if x) + f" [{d['code']}]"


def device_event(conn, device_id, event, status=None, user_id=None, note=None, ref_type=None, ref_id=None):
    conn.execute(
        "INSERT INTO device_events(device_id, event, status, user_id, note, ref_type, ref_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (device_id, event, status, user_id, note, ref_type, ref_id, now()))


def cancel_sale(conn, user, perms, sale_id, reason, auth=None):
    sale = conn.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
    if not sale:
        raise ApiError("Venda não encontrada.", 404)
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise ApiError("Informe o motivo do cancelamento.")
    authorized_by = authorize(conn, user, perms, "cancelar_vendas", auth)
    if sale["status"] != "concluida":
        raise ApiError("Esta venda já foi cancelada.", 409)
    if conn.execute("SELECT 1 FROM returns WHERE sale_id=?", (sale_id,)).fetchone():
        raise ApiError("Esta venda possui devolução registrada e não pode ser cancelada.", 409)
    # Dinheiro de um caixa já fechado: o estorno sai do caixa aberto agora.
    cur_session = open_cash(conn)
    if sale["cash_session_id"] != (cur_session["id"] if cur_session else None):
        cash_methods = {m["key"] for m in payment_methods(conn) if m.get("type") == "cash"}
        cash_paid = sum(r["amount_cents"] for r in conn.execute("SELECT * FROM sale_payments WHERE sale_id=?", (sale_id,))
                        if r["method"] in cash_methods)
        if cash_paid:
            if not cur_session:
                raise ApiError("Abra o caixa para cancelar uma venda paga em dinheiro em um caixa anterior (o estorno sai do caixa aberto).", 409, "cash_closed")
            conn.execute("INSERT INTO cash_movements(session_id, kind, amount_cents, reason, user_id, created_at) VALUES (?,?,?,?,?,?)",
                         (cur_session["id"], "devolucao", cash_paid, f"Estorno do cancelamento da venda #{sale_id}", user["id"], now()))
    who = authorized_by if authorized_by != user["id"] else None
    for it in conn.execute("SELECT * FROM sale_items WHERE sale_id=?", (sale_id,)).fetchall():
        if it["product_id"]:
            move_stock(conn, it["product_id"], "cancelamento_venda", it["qty"], user["id"],
                       f"Cancelamento da venda #{sale_id}: {reason}", unit_cost=it["unit_cost_cents"],
                       ref_type="sale", ref_id=sale_id, authorized_by=who)
        else:
            conn.execute("UPDATE devices SET status='disponivel' WHERE id=?", (it["device_id"],))
            device_event(conn, it["device_id"], "cancelamento_venda", "disponivel", user["id"],
                         f"Cancelamento da venda #{sale_id}: {reason}", "sale", sale_id)
    conn.execute(
        "UPDATE sales SET status='cancelada', cancelled_at=?, cancelled_by=?, cancel_auth_by=?, cancel_reason=? WHERE id=?",
        (now(), user["id"], authorized_by, reason, sale_id))
    audit(conn, user["id"], "venda_cancelada", "sale", sale_id, before={"status": "concluida"},
          after={"status": "cancelada", "motivo": reason}, authorized_by=who)


def sale_detail(conn, sale_id):
    sale = conn.execute(
        "SELECT s.*, u.name AS seller, c.name AS customer_name, c.phone AS customer_phone, cu.name AS cancelled_by_name"
        " FROM sales s JOIN users u ON u.id=s.user_id LEFT JOIN customers c ON c.id=s.customer_id"
        " LEFT JOIN users cu ON cu.id=s.cancelled_by WHERE s.id=?", (sale_id,)).fetchone()
    if not sale:
        raise ApiError("Venda não encontrada.", 404)
    d = dict(sale)
    d["items"] = [dict(r) for r in conn.execute("SELECT * FROM sale_items WHERE sale_id=? ORDER BY id", (sale_id,))]
    for it in d["items"]:
        it["returned_qty"] = conn.execute(
            "SELECT COALESCE(SUM(qty),0) FROM return_items WHERE sale_item_id=?", (it["id"],)).fetchone()[0]
    d["payments"] = [dict(r) for r in conn.execute("SELECT * FROM sale_payments WHERE sale_id=? ORDER BY id", (sale_id,))]
    d["cost_cents"] = sum(i["unit_cost_cents"] * i["qty"] for i in d["items"])
    d["profit_cents"] = d["total_cents"] - d["cost_cents"]
    d["fees_cents"] = sum(p["fee_cents"] for p in d["payments"])
    d["refunded_cents"] = conn.execute(
        "SELECT COALESCE(SUM(ri.amount_cents),0) FROM return_items ri JOIN returns r ON r.id=ri.return_id WHERE r.sale_id=?",
        (sale_id,)).fetchone()[0]
    return d


# ---------------------------------------------------------------- usuários

def validate_password(password, username=""):
    if not password or len(password) < 6:
        raise ApiError("A senha deve ter pelo menos 6 caracteres.")
    if password.lower() == (username or "").lower() or password.lower() in ("123456", "admin123", "senha123", "password"):
        raise ApiError("Escolha uma senha menos óbvia.")


def create_user(conn, actor, username, name, role, password):
    username = (username or "").strip()
    if not username or not (name or "").strip():
        raise ApiError("Informe o nome e o usuário.")
    if role not in ROLES:
        raise ApiError("Perfil inválido.")
    validate_password(password, username)
    if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        raise ApiError("Já existe um usuário com este login.", 409)
    cur = conn.execute(
        "INSERT INTO users(username, name, password_hash, role, must_change_password, created_at) VALUES (?,?,?,?,1,?)",
        (username, name.strip(), generate_password_hash(password), role, now()))
    audit(conn, actor["id"], "usuario_criado", "user", cur.lastrowid, after={"username": username, "role": role})
    return cur.lastrowid


def update_user(conn, actor, user_id, data):
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        raise ApiError("Usuário não encontrado.", 404)
    sets, vals, before, after = [], [], {}, {}
    if "name" in data and (data["name"] or "").strip():
        sets.append("name=?"); vals.append(data["name"].strip())
    if "role" in data and data["role"] != row["role"]:
        if data["role"] not in ROLES:
            raise ApiError("Perfil inválido.")
        sets.append("role=?"); vals.append(data["role"]); before["role"] = row["role"]; after["role"] = data["role"]
    if "active" in data and bool(data["active"]) != bool(row["active"]):
        sets.append("active=?"); vals.append(1 if data["active"] else 0)
        before["active"] = row["active"]; after["active"] = 1 if data["active"] else 0
    if data.get("password"):
        validate_password(data["password"], row["username"])
        sets += ["password_hash=?", "must_change_password=1"]; vals.append(generate_password_hash(data["password"]))
        after["senha"] = "redefinida"
    # Nunca deixar o sistema sem administrador ativo.
    new_role = data.get("role", row["role"]); new_active = bool(data.get("active", row["active"]))
    if row["role"] == "administrador" and (new_role != "administrador" or not new_active):
        others = conn.execute("SELECT COUNT(*) FROM users WHERE role='administrador' AND active=1 AND id<>?", (user_id,)).fetchone()[0]
        if others == 0:
            raise ApiError("É necessário manter ao menos um administrador ativo.", 409)
    if sets:
        conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", vals + [user_id])
        audit(conn, actor["id"], "usuario_alterado", "user", user_id, before=before, after=after)


def change_own_password(conn, user, current, new):
    if not check_password_hash(user["password_hash"], current or ""):
        raise ApiError("A senha atual está incorreta.", 400)
    validate_password(new, user["username"])
    if check_password_hash(user["password_hash"], new):
        raise ApiError("A nova senha deve ser diferente da atual.")
    conn.execute("UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?", (generate_password_hash(new), user["id"]))
    audit(conn, user["id"], "senha_alterada", "user", user["id"])


def set_role_permissions(conn, actor, matrix):
    before = {r: sorted(permissions_of(conn, {"role": r})) for r in ROLES if r != "administrador"}
    for role, perms in matrix.items():
        if role not in ROLES or role == "administrador":
            continue
        conn.execute("DELETE FROM role_permissions WHERE role=?", (role,))
        for p in perms:
            if p in PERMISSIONS:
                conn.execute("INSERT INTO role_permissions(role, permission) VALUES (?,?)", (role, p))
    after = {r: sorted(permissions_of(conn, {"role": r})) for r in ROLES if r != "administrador"}
    audit(conn, actor["id"], "permissoes_alteradas", "role_permissions", None, before=before, after=after)


# ---------------------------------------------------------------- painel

def dashboard(conn, perms):
    today = datetime.now().strftime("%Y-%m-%d")
    month = datetime.now().strftime("%Y-%m")
    q = lambda sql, *a: conn.execute(sql, a).fetchone()
    t = q("SELECT COUNT(*) n, COALESCE(SUM(total_cents),0) total FROM sales WHERE status='concluida' AND date(created_at)=?", today)
    m = q("SELECT COUNT(*) n, COALESCE(SUM(total_cents),0) total FROM sales WHERE status='concluida' AND strftime('%Y-%m',created_at)=?", month)
    st = q("SELECT COALESCE(SUM(CASE WHEN qty>0 THEN qty ELSE 0 END),0) units, COUNT(*) products FROM products WHERE active=1")
    low = [dict(r) for r in conn.execute(
        "SELECT id, name, sku, qty, min_qty FROM products WHERE active=1 AND qty<=min_qty AND (min_qty>0 OR qty<=0)"
        " ORDER BY qty-min_qty LIMIT 20")]
    top = [dict(r) for r in conn.execute(
        "SELECT COALESCE(i.product_id, -i.device_id) AS pid, MAX(i.product_name) AS name, SUM(i.qty) AS qty, SUM(i.total_cents) AS total_cents,"
        " SUM(i.total_cents - i.unit_cost_cents*i.qty) AS profit_cents"
        " FROM sale_items i JOIN sales s ON s.id=i.sale_id WHERE s.status='concluida' AND date(s.created_at)>=date('now','localtime','-30 day')"
        " GROUP BY pid ORDER BY qty DESC LIMIT 5")]
    days = int(get_settings(conn).get("inactive_days") or 60)
    stalled = [dict(r) for r in conn.execute(
        "SELECT id, name, qty FROM products p WHERE active=1 AND qty>0 AND created_at < datetime('now','localtime',?)"
        " AND NOT EXISTS (SELECT 1 FROM sale_items i JOIN sales s ON s.id=i.sale_id WHERE i.product_id=p.id AND s.status='concluida'"
        " AND s.created_at >= datetime('now','localtime',?)) ORDER BY qty DESC LIMIT 10", (f"-{days} day", f"-{days} day"))]
    os_open = q("SELECT COUNT(*) n FROM service_orders WHERE status NOT IN ('entregue','cancelado')")["n"]
    os_ready = [dict(r) for r in conn.execute(
        "SELECT id, customer_name, brand, model, completed_at FROM service_orders WHERE status='pronto_retirada' ORDER BY completed_at LIMIT 10")]
    os_late = q("SELECT COUNT(*) n FROM service_orders WHERE status NOT IN ('entregue','cancelado') AND deadline IS NOT NULL AND deadline < ?", today)["n"]
    devs = q("SELECT COUNT(*) n, COALESCE(SUM(cost_cents),0) cost FROM devices WHERE status IN ('disponivel','reservado','em_teste','em_manutencao')")
    out = {
        "sales_today": {"count": t["n"], "total_cents": t["total"]},
        "revenue_month": {"count": m["n"], "total_cents": m["total"]},
        "stock_units": st["units"], "products_active": st["products"],
        "low_stock": low, "top_sold": top, "stalled": stalled,
        "os_open": os_open, "os_late": os_late, "os_ready": os_ready, "devices_in_stock": devs["n"],
    }
    session = open_cash(conn)
    out["cash"] = ({"open": True, "opened_at": session["opened_at"], **cash_summary(conn, session)} if session else {"open": False})
    if "ver_lucros" in perms:
        p = q("SELECT COALESCE(SUM(i.total_cents - i.unit_cost_cents*i.qty),0) profit FROM sale_items i JOIN sales s ON s.id=i.sale_id"
              " WHERE s.status='concluida' AND strftime('%Y-%m',s.created_at)=?", month)
        ret = q("SELECT COALESCE(SUM(ri.amount_cents),0) a, COALESCE(SUM(CASE WHEN ri.restock=1 THEN ri.cost_cents ELSE 0 END),0) c"
                " FROM return_items ri JOIN returns r ON r.id=ri.return_id WHERE strftime('%Y-%m',r.created_at)=?", month)
        out["gross_profit_month_cents"] = p["profit"] - ret["a"] + ret["c"]
        out["top_margin"] = [dict(r) for r in conn.execute(
            "SELECT id, name, price_cents, cost_cents, ROUND((price_cents-cost_cents)*100.0/price_cents,1) AS margin FROM products"
            " WHERE active=1 AND qty>0 AND price_cents>0 ORDER BY margin DESC LIMIT 5")]
    else:
        out["top_sold"] = [{k: v for k, v in r.items() if k != "profit_cents"} for r in out["top_sold"]]
    if "ver_financeiro" in perms:
        out["payables_soon"] = [dict(r) for r in conn.execute(
            "SELECT id, description, amount_cents, due_date FROM payables WHERE paid_at IS NULL AND due_date <= date('now','localtime','+7 day')"
            " ORDER BY due_date LIMIT 10")]
    else:
        out["revenue_month"] = None
        out["cash"] = {"open": out["cash"]["open"]}
    return out
