"""Aplicação web local (Flask): rotas da API, autenticação, permissões e páginas de impressão."""
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, Response, abort, g, jsonify, redirect, render_template, request, send_file, send_from_directory, session

from . import after_sales, backup, db, devices, finance, registry, reports, service_orders as so, services as sv
from .barcode import classify, normalize, variants
from .services import ApiError

APP_VERSION = "1.0.0"
LOGIN_WINDOW, LOGIN_MAX = 300, 5


def create_app(testing=False):
    app = Flask(__name__, static_folder="static", template_folder="templates", static_url_path="/static")
    db.init_db()
    key_file = db.data_dir() / "secret.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32))
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
    app.config.update(
        SECRET_KEY=key_file.read_text().strip(),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict", SESSION_COOKIE_NAME="loja_sessao",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12), MAX_CONTENT_LENGTH=200 * 1024 * 1024,
        JSON_AS_ASCII=False, TESTING=testing, BOOT_ID=secrets.token_hex(8), JSON_SORT_KEYS=False,
    )
    attempts = {}
    attempts_lock = threading.Lock()

    handler = logging.FileHandler(db.data_dir() / "erros.log", encoding="utf-8")
    handler.setLevel(logging.ERROR)
    app.logger.addHandler(handler)

    # ------------------------------------------------------------ infraestrutura
    def conn():
        if "conn" not in g:
            g.conn = db.connect()
        return g.conn

    @app.teardown_request
    def _close(_exc):
        c = g.pop("conn", None)
        if c is not None:
            c.close()

    @app.after_request
    def _headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'"
        if request.path.startswith("/api/") or request.path.startswith("/print/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.errorhandler(ApiError)
    def _api_error(e):
        body = {"error": e.message, "code": e.code, **e.extra}
        return jsonify(body), e.status

    @app.errorhandler(413)
    def _too_big(_e):
        return jsonify({"error": "Arquivo muito grande."}), 413

    @app.errorhandler(Exception)
    def _unexpected(e):
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            if request.path.startswith("/api/"):
                return jsonify({"error": e.description or e.name}), e.code
            return e
        app.logger.exception("Erro inesperado em %s %s", request.method, request.path)
        if isinstance(e, sqlite3.OperationalError) and "locked" in str(e).lower():
            return jsonify({"error": "O banco de dados está ocupado. Tente novamente em instantes."}), 503
        if isinstance(e, sqlite3.IntegrityError):
            return jsonify({"error": "Operação não permitida pelas regras do banco de dados (dado duplicado ou inválido)."}), 409
        return jsonify({"error": "Erro interno. O problema foi registrado em dados/erros.log."}), 500

    def current_user():
        uid = session.get("uid")
        if not uid or session.get("boot") != app.config["BOOT_ID"]:
            return None
        u = conn().execute("SELECT * FROM users WHERE id=? AND active=1", (uid,)).fetchone()
        return u

    def api(rule, methods=("GET",), perm=None, anyperm=None, public=False, tx=None, allow_pwd_change=False):
        """Registra uma rota JSON. Escritas (POST/PUT/DELETE) rodam em transação única."""
        is_write = any(m in ("POST", "PUT", "DELETE", "PATCH") for m in methods)
        use_tx = is_write if tx is None else tx

        def deco(fn):
            @wraps(fn)
            def wrapper(*a, **kw):
                if is_write and request.headers.get("X-Requested-With") != "loja":
                    raise ApiError("Requisição não autorizada.", 403)
                if not public:
                    user = current_user()
                    if not user:
                        raise ApiError("Sessão expirada. Entre novamente.", 401, "unauthenticated")
                    perms = sv.permissions_of(conn(), user)
                    if user["must_change_password"] and not allow_pwd_change:
                        raise ApiError("Troque sua senha para continuar.", 403, "password_change_required")
                    if perm and perm not in perms:
                        raise ApiError("Você não tem permissão para esta operação.", 403)
                    if anyperm and not (set(anyperm) & perms):
                        raise ApiError("Você não tem permissão para esta operação.", 403)
                    g.user, g.perms = user, perms
                if use_tx:
                    with db.tx(conn()):
                        return fn(*a, **kw)
                return fn(*a, **kw)
            app.add_url_rule(rule, fn.__name__ + rule, wrapper, methods=list(methods))
            return wrapper
        return deco

    def body():
        data = request.get_json(silent=True)
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ApiError("Requisição inválida.")
        return data

    def hide_cost(obj, keys=("cost_cents", "unit_cost_cents", "parts_cost_cents", "stock_value_cents")):
        """Remove campos de custo de quem não pode ver custos de aquisição."""
        if "ver_custos" in g.perms:
            return obj
        if isinstance(obj, list):
            return [hide_cost(x, keys) for x in obj]
        if isinstance(obj, dict):
            return {k: hide_cost(v, keys) for k, v in obj.items() if k not in keys}
        return obj

    def hide_profit(obj):
        if "ver_lucros" in g.perms:
            return obj
        return {k: v for k, v in obj.items() if k not in ("profit_cents", "cost_cents", "fees_cents")}

    def dates():
        f = request.args.get("from") or datetime.now().strftime("%Y-%m-%d")
        t = request.args.get("to") or f
        for v in (f, t):
            try:
                datetime.strptime(v, "%Y-%m-%d")
            except ValueError:
                raise ApiError("Data inválida.")
        return f, t

    # ------------------------------------------------------------ páginas
    @app.route("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.route("/api/health")
    def health():
        return jsonify({"ok": True, "version": APP_VERSION})

    # ------------------------------------------------------------ autenticação
    @api("/api/login", ["POST"], public=True, tx=False)
    def login():
        d = body()
        username = (d.get("username") or "").strip()
        key = (request.remote_addr, username.lower())
        with attempts_lock:
            recent = [t for t in attempts.get(key, []) if time.time() - t < LOGIN_WINDOW]
            attempts[key] = recent
            if len(recent) >= LOGIN_MAX:
                raise ApiError("Muitas tentativas de acesso. Aguarde alguns minutos e tente novamente.", 429)
        user = sv.check_credentials(conn(), username, d.get("password"))
        if not user:
            with attempts_lock:
                attempts[key].append(time.time())
            with db.tx(conn()):
                sv.audit(conn(), None, "login_falhou", "user", None, after={"usuario": username[:60]})
            raise ApiError("Usuário ou senha incorretos.", 401)
        with attempts_lock:
            attempts.pop(key, None)
        session.clear()
        session.permanent = True
        session["uid"] = user["id"]
        session["boot"] = app.config["BOOT_ID"]
        with db.tx(conn()):
            sv.audit(conn(), user["id"], "login", "user", user["id"])
        return me_payload(user)

    @api("/api/logout", ["POST"], public=True, tx=False)
    def logout():
        session.clear()
        return jsonify({"ok": True})

    def me_payload(user):
        c = conn()
        perms = sv.permissions_of(c, user)
        st = sv.get_settings(c)
        cash = sv.open_cash(c)
        return jsonify({
            "user": {"id": user["id"], "name": user["name"], "username": user["username"], "role": user["role"],
                     "must_change_password": bool(user["must_change_password"])},
            "permissions": sorted(perms),
            "settings": {k: st.get(k) for k in ("store_name", "scanner_suffix", "scanner_min_length", "max_installments", "auto_print_receipt",
                                                  "default_warranty_days", "receipt_footer")},
            "payment_methods": sv.payment_methods(c),
            "cash_open": bool(cash), "cash_opened_at": cash["opened_at"] if cash else None,
            "version": APP_VERSION,
        })

    @api("/api/me", public=True)
    def me():
        user = current_user()
        if not user:
            raise ApiError("Não autenticado.", 401, "unauthenticated")
        return me_payload(user)

    @api("/api/me/password", ["POST"], allow_pwd_change=True)
    def change_password():
        d = body()
        sv.change_own_password(conn(), g.user, d.get("current"), d.get("new"))
        return jsonify({"ok": True})

    @api("/api/authorize", ["POST"], tx=False)
    def check_authorization():
        """Valida credenciais de um supervisor para uma permissão (usado pelos diálogos de autorização)."""
        d = body()
        perm = d.get("permission")
        if perm not in sv.PERMISSIONS:
            raise ApiError("Permissão inválida.")
        who = sv.authorize(conn(), g.user, g.perms, perm, {"username": d.get("username"), "password": d.get("password")})
        return jsonify({"ok": True, "authorized_by": who})

    # ------------------------------------------------------------ configurações
    @api("/api/settings", perm="gerenciar_config")
    def get_settings():
        return jsonify({"settings": sv.get_settings(conn()), "card_fees": finance.get_card_fees(conn())})

    @api("/api/settings", ["PUT"], perm="gerenciar_config")
    def put_settings():
        d = body()
        c = conn()
        allowed = {"store_name", "store_info", "receipt_footer", "scanner_suffix", "scanner_min_length", "max_installments",
                   "auto_print_receipt", "default_acquirer", "os_term_days", "inactive_days", "default_warranty_days", "backup_keep"}
        before = sv.get_settings(c)
        changes = {}
        for k, v in (d.get("settings") or {}).items():
            if k not in allowed:
                continue
            v = "" if v is None else str(v).strip()
            if k == "scanner_suffix" and v not in ("enter", "tab", "nenhum"):
                raise ApiError("Sufixo do leitor inválido.")
            if k in ("scanner_min_length", "max_installments", "os_term_days", "inactive_days", "backup_keep"):
                v = str(sv.to_int(v, k, minimum=1, maximum=999))
            if k == "default_warranty_days":
                v = str(sv.warranty_days(v))
            if before.get(k) != v:
                c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))
                changes[k] = {"antes": before.get(k), "depois": v}
        if "payment_methods" in d:
            methods = d["payment_methods"]
            if not isinstance(methods, list) or not methods:
                raise ApiError("Cadastre ao menos uma forma de pagamento.")
            seen = set()
            norm = []
            for m in methods:
                key = "".join(ch for ch in (m.get("key") or m.get("label") or "").lower().replace(" ", "_") if ch.isalnum() or ch == "_")
                label = (m.get("label") or "").strip()
                if not key or not label or key in seen:
                    raise ApiError("Cada forma de pagamento precisa de nome único.")
                if m.get("type") not in ("cash", "card", "other"):
                    raise ApiError("Tipo de pagamento inválido.")
                seen.add(key)
                item = {"key": key, "label": label, "type": m["type"]}
                if m.get("installments") and m["type"] == "card":
                    item["installments"] = True
                norm.append(item)
            if not any(m["type"] == "cash" for m in norm):
                raise ApiError("É necessário manter uma forma de pagamento em dinheiro (usada no fechamento do caixa).")
            old_keys = {m["key"] for m in sv.payment_methods(c)}
            used = {r[0] for r in c.execute("SELECT DISTINCT method FROM sale_payments UNION SELECT DISTINCT method FROM service_payments")}
            missing = (old_keys | used) & used - seen
            if missing:
                raise ApiError(f"Não é possível remover formas de pagamento já usadas em vendas: {', '.join(sorted(missing))}. Renomeie-as em vez disso.")
            c.execute("INSERT INTO settings(key,value) VALUES('payment_methods',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (json.dumps(norm, ensure_ascii=False),))
            changes["payment_methods"] = {"depois": norm}
        if "card_fees" in d:
            finance.save_card_fees(c, g.user, d["card_fees"])
        if changes:
            sv.audit(c, g.user["id"], "configuracoes_alteradas", "settings", None, before={k: v["antes"] for k, v in changes.items() if "antes" in v},
                     after={k: v["depois"] for k, v in changes.items()})
        return jsonify({"ok": True})

    # ------------------------------------------------------------ usuários
    @api("/api/users", perm="gerenciar_usuarios")
    def users_list():
        rows = conn().execute("SELECT id, username, name, role, active, must_change_password, created_at FROM users ORDER BY name").fetchall()
        return jsonify([dict(r) for r in rows])

    @api("/api/users/basic", anyperm=("gerenciar_os", "vender", "gerenciar_usuarios", "ver_relatorios", "gerenciar_garantias"))
    def users_basic():
        rows = conn().execute("SELECT id, name, role FROM users WHERE active=1 ORDER BY name").fetchall()
        return jsonify([dict(r) for r in rows])

    @api("/api/users", ["POST"], perm="gerenciar_usuarios")
    def users_create():
        d = body()
        uid = sv.create_user(conn(), g.user, d.get("username"), d.get("name"), d.get("role"), d.get("password"))
        return jsonify({"id": uid}), 201

    @api("/api/users/<int:uid>", ["PUT"], perm="gerenciar_usuarios")
    def users_update(uid):
        sv.update_user(conn(), g.user, uid, body())
        return jsonify({"ok": True})

    @api("/api/permissions", perm="gerenciar_usuarios")
    def perms_get():
        c = conn()
        return jsonify({"permissions": sv.PERMISSIONS, "roles": {r: sorted(sv.permissions_of(c, {"role": r})) for r in sv.ROLES}})

    @api("/api/permissions", ["PUT"], perm="gerenciar_usuarios")
    def perms_put():
        sv.set_role_permissions(conn(), g.user, body().get("roles") or {})
        return jsonify({"ok": True})

    # ------------------------------------------------------------ produtos
    @api("/api/products", anyperm=("vender", "gerenciar_produtos", "movimentar_estoque", "ajustar_estoque", "ver_relatorios", "gerenciar_os"))
    def products_list():
        rows = registry.search_products(conn(), request.args.get("q", ""), request.args.get("category") or None,
                                        request.args.get("low") == "1", request.args.get("inactive") == "1")
        return jsonify(hide_cost(rows))

    @api("/api/products", ["POST"], perm="gerenciar_produtos")
    def products_create():
        d = body()
        if ("cost_cents" in d and d["cost_cents"]) and "ver_custos" not in g.perms:
            raise ApiError("Sem permissão para informar custos.", 403)
        row = sv.create_product(conn(), g.user, g.perms, d)
        return jsonify(hide_cost(dict(row))), 201

    @api("/api/products/<int:pid>", anyperm=("vender", "gerenciar_produtos", "movimentar_estoque", "ajustar_estoque", "gerenciar_os"))
    def products_get(pid):
        return jsonify(hide_cost(dict(sv.product_row(conn(), pid))))

    @api("/api/products/<int:pid>", ["PUT"], perm="gerenciar_produtos")
    def products_update(pid):
        d = body()
        if "ver_custos" not in g.perms:
            d.pop("cost_cents", None)
        return jsonify(hide_cost(dict(sv.update_product(conn(), g.user, g.perms, pid, d))))

    @api("/api/products/<int:pid>/active", ["POST"], perm="gerenciar_produtos")
    def products_active(pid):
        sv.set_product_active(conn(), g.user, g.perms, pid, bool(body().get("active")))
        return jsonify({"ok": True})

    @api("/api/products/<int:pid>/history", anyperm=("gerenciar_produtos", "movimentar_estoque", "ajustar_estoque", "ver_relatorios"))
    def products_history(pid):
        return jsonify(hide_cost(registry.product_history(conn(), pid)))

    @api("/api/products/<int:pid>/entry", ["POST"], perm="movimentar_estoque")
    def stock_entry(pid):
        d = body()
        return jsonify(hide_cost(dict(sv.stock_entry(conn(), g.user, g.perms, pid, d.get("qty"), d.get("unit_cost_cents"), d.get("supplier"), d.get("note")))))

    @api("/api/products/<int:pid>/exit", ["POST"], perm="movimentar_estoque")
    def stock_exit(pid):
        d = body()
        return jsonify(hide_cost(dict(sv.stock_exit(conn(), g.user, g.perms, pid, d.get("qty"), d.get("kind"), d.get("reason")))))

    @api("/api/products/<int:pid>/adjust", ["POST"], perm="ajustar_estoque")
    def stock_adjust(pid):
        d = body()
        return jsonify(hide_cost(dict(sv.stock_adjust(conn(), g.user, g.perms, pid, d.get("new_qty"), d.get("reason")))))

    @api("/api/products/<int:pid>/transfer", ["POST"], perm="movimentar_estoque")
    def stock_transfer(pid):
        d = body()
        registry.transfer_location(conn(), g.user, g.perms, pid, d.get("location"), d.get("note"))
        return jsonify({"ok": True})

    @api("/api/categories", anyperm=("gerenciar_produtos", "ver_relatorios", "vender", "movimentar_estoque"))
    def categories():
        return jsonify(registry.categories(conn()))

    @api("/api/barcode/check")
    def barcode_check():
        """Valida um código digitado/lido: tipo, dígito verificador e se já está cadastrado."""
        raw = request.args.get("code", "")
        try:
            code, kind = classify(raw, request.args.get("internal") == "1")
        except ValueError as e:
            return jsonify({"valid": False, "message": str(e), "code": normalize(raw)})
        used = None
        if code:
            row = sv.find_by_code(conn(), code)
            used = {"id": row["id"], "name": row["name"]} if row else None
        return jsonify({"valid": True, "code": code, "type": kind, "registered": used})

    @api("/api/lookup", anyperm=("vender", "gerenciar_produtos", "movimentar_estoque", "ajustar_estoque", "gerenciar_os"))
    def lookup():
        """Leitura de código no PDV: produto (barras/SKU) ou aparelho (código, IMEI, série)."""
        code = normalize(request.args.get("code", ""))
        if not code:
            raise ApiError("Código vazio.")
        c = conn()
        p = sv.find_by_code(c, code)
        if p:
            return jsonify({"found": "product", "product": hide_cost(dict(p))})
        d = devices.find_by_code(c, code)
        if d:
            return jsonify({"found": "device", "device": hide_cost(dict(d))})
        return jsonify({"found": None, "code": code})

    @api("/api/pdv/search", perm="vender")
    def pdv_search():
        q = request.args.get("q", "")
        prods = [p for p in registry.search_products(conn(), q, limit=30)]
        devs = [d for d in devices.search(conn(), q, "disponivel", 15)] if q.strip() else []
        return jsonify({"products": hide_cost(prods), "devices": hide_cost(devs)})

    # ------------------------------------------------------------ caixa
    def cash_payload():
        c = conn()
        s = sv.open_cash(c)
        if not s:
            return {"open": False}
        out = {"open": True, "id": s["id"], "opened_at": s["opened_at"],
               "opened_by": c.execute("SELECT name FROM users WHERE id=?", (s["opened_by"],)).fetchone()[0], **sv.cash_summary(c, s)}
        out["movements"] = [dict(r) for r in c.execute(
            "SELECT m.*, u.name AS user_name FROM cash_movements m JOIN users u ON u.id=m.user_id WHERE session_id=? ORDER BY m.id DESC", (s["id"],))]
        if "ver_financeiro" not in g.perms and "gerenciar_caixa" not in g.perms:
            return {"open": True}
        return out

    @api("/api/cash", anyperm=("gerenciar_caixa", "vender", "ver_financeiro"))
    def cash_get():
        return jsonify(cash_payload())

    @api("/api/cash/open", ["POST"], perm="gerenciar_caixa")
    def cash_open():
        sv.cash_open(conn(), g.user, g.perms, body().get("opening_cents", 0))
        return jsonify(cash_payload())

    @api("/api/cash/movement", ["POST"], perm="gerenciar_caixa")
    def cash_move():
        d = body()
        sv.cash_movement(conn(), g.user, g.perms, d.get("kind"), d.get("amount_cents"), d.get("reason"))
        return jsonify(cash_payload())

    @api("/api/cash/close", ["POST"], perm="gerenciar_caixa")
    def cash_close():
        d = body()
        res = sv.cash_close(conn(), g.user, g.perms, d.get("counted_cents"), d.get("notes"))
        return jsonify(res)

    @app.after_request
    def _auto_backup_after_close(resp):
        if request.path == "/api/cash/close" and resp.status_code == 200:
            _safe_backup("auto")  # backup ao fechar o caixa
        return resp

    @api("/api/cash/sessions", perm="ver_financeiro")
    def cash_sessions():
        rows = conn().execute("SELECT c.*, u.name AS opener FROM cash_sessions c JOIN users u ON u.id=c.opened_by ORDER BY c.id DESC LIMIT 60").fetchall()
        return jsonify([dict(r) for r in rows])

    # ------------------------------------------------------------ vendas
    @api("/api/sales", ["POST"], perm="vender")
    def sales_create():
        sale_id, duplicate = sv.create_sale(conn(), g.user, g.perms, body())
        d = sv.sale_detail(conn(), sale_id)
        return jsonify({"sale_id": sale_id, "duplicate": duplicate, "sale": hide_profit(hide_cost(d))}), (200 if duplicate else 201)

    @api("/api/sales")
    def sales_list():
        if not ({"vender", "ver_financeiro", "ver_relatorios"} & g.perms):
            raise ApiError("Você não tem permissão para esta operação.", 403)
        f, t = request.args.get("from"), request.args.get("to")
        sql = ("SELECT s.id, s.created_at, s.total_cents, s.discount_cents, s.status, u.name AS seller, c.name AS customer_name,"
               " (SELECT GROUP_CONCAT(method, ', ') FROM sale_payments WHERE sale_id=s.id) AS methods"
               " FROM sales s JOIN users u ON u.id=s.user_id LEFT JOIN customers c ON c.id=s.customer_id WHERE 1=1")
        args = []
        if "ver_financeiro" not in g.perms:
            sql += " AND s.user_id=? AND date(s.created_at)>=date('now','localtime','-7 day')"
            args.append(g.user["id"])
        if f:
            sql += " AND date(s.created_at)>=?"; args.append(f)
        if t:
            sql += " AND date(s.created_at)<=?"; args.append(t)
        q = (request.args.get("q") or "").strip()
        if q:
            if q.lstrip("#").isdigit():
                sql += " AND s.id=?"; args.append(int(q.lstrip("#")))
            else:
                sql += " AND norm(COALESCE(c.name,'')||' '||u.name) LIKE norm(?)"; args.append(f"%{q}%")
        if request.args.get("status") in ("concluida", "cancelada"):
            sql += " AND s.status=?"; args.append(request.args["status"])
        return jsonify([dict(r) for r in conn().execute(sql + " ORDER BY s.id DESC LIMIT 300", args)])

    def _sale_visible(sale_id):
        d = sv.sale_detail(conn(), sale_id)
        if "ver_financeiro" not in g.perms and d["user_id"] != g.user["id"]:
            raise ApiError("Você não tem permissão para ver esta venda.", 403)
        return d

    @api("/api/sales/<int:sid>", anyperm=("vender", "ver_financeiro", "ver_relatorios"))
    def sales_get(sid):
        return jsonify(hide_profit(hide_cost(_sale_visible(sid))))

    @api("/api/sales/<int:sid>/cancel", ["POST"], anyperm=("vender", "cancelar_vendas"))
    def sales_cancel(sid):
        d = body()
        _sale_visible(sid)
        sv.cancel_sale(conn(), g.user, g.perms, sid, d.get("reason"), d.get("authorization"))
        return jsonify({"ok": True})

    # ------------------------------------------------------------ aparelhos
    @api("/api/devices", anyperm=("gerenciar_aparelhos", "vender", "gerenciar_os"))
    def devices_list():
        return jsonify(hide_cost(devices.search(conn(), request.args.get("q", ""), request.args.get("status") or None)))

    @api("/api/devices", ["POST"], perm="gerenciar_aparelhos")
    def devices_create():
        return jsonify(hide_cost(dict(devices.create_device(conn(), g.user, g.perms, body())))), 201

    @api("/api/devices/<int:did>", anyperm=("gerenciar_aparelhos", "vender", "gerenciar_os"))
    def devices_get(did):
        return jsonify(hide_cost(devices.detail(conn(), did)))

    @api("/api/devices/<int:did>", ["PUT"], perm="gerenciar_aparelhos")
    def devices_update(did):
        d = body()
        if "ver_custos" not in g.perms:
            d.pop("cost_cents", None)
        return jsonify(hide_cost(dict(devices.update_device(conn(), g.user, g.perms, did, d))))

    @api("/api/devices/<int:did>/status", ["POST"], perm="gerenciar_aparelhos")
    def devices_status(did):
        d = body()
        return jsonify(hide_cost(dict(devices.set_status(conn(), g.user, g.perms, did, d.get("status"), d.get("note"), d.get("reserved_for")))))

    # ------------------------------------------------------------ assistência técnica
    @api("/api/os", perm="gerenciar_os")
    def os_list():
        a = request.args
        return jsonify(hide_cost(so.search(conn(), a.get("q", ""), a.get("status") or None, a.get("technician_id") or None,
                                           a.get("open") == "1", a.get("unclaimed") == "1")))

    @api("/api/os", ["POST"], perm="gerenciar_os")
    def os_create():
        oid = so.create_order(conn(), g.user, g.perms, body())
        return jsonify({"id": oid}), 201

    @api("/api/os/<int:oid>", perm="gerenciar_os")
    def os_get(oid):
        return jsonify(hide_cost(so.detail(conn(), oid)))

    @api("/api/os/<int:oid>", ["PUT"], perm="gerenciar_os")
    def os_update(oid):
        d = body()
        so.update_order(conn(), g.user, g.perms, oid, d, d.get("authorization"))
        return jsonify(hide_cost(so.detail(conn(), oid)))

    @api("/api/os/<int:oid>/parts", ["POST"], perm="gerenciar_os")
    def os_add_part(oid):
        d = body()
        so.add_part(conn(), g.user, g.perms, oid, d.get("product_id"), d.get("qty", 1), d.get("price_cents"))
        return jsonify(hide_cost(so.detail(conn(), oid)))

    @api("/api/os/<int:oid>/parts/<int:part_id>", ["DELETE"], perm="gerenciar_os")
    def os_del_part(oid, part_id):
        so.remove_part(conn(), g.user, g.perms, oid, part_id)
        return jsonify(hide_cost(so.detail(conn(), oid)))

    @api("/api/os/<int:oid>/approval", ["POST"], perm="gerenciar_os")
    def os_approval(oid):
        d = body()
        so.approve(conn(), g.user, g.perms, oid, bool(d.get("approved", True)), d.get("note"))
        return jsonify(hide_cost(so.detail(conn(), oid)))

    @api("/api/os/<int:oid>/status", ["POST"], perm="gerenciar_os")
    def os_status(oid):
        d = body()
        so.set_status(conn(), g.user, g.perms, oid, d.get("status"), d.get("note"), bool(d.get("allow_pending")), d.get("authorization"))
        return jsonify(hide_cost(so.detail(conn(), oid)))

    @api("/api/os/<int:oid>/payments", ["POST"], perm="gerenciar_os")
    def os_pay(oid):
        so.add_payment(conn(), g.user, g.perms, oid, body().get("payments"))
        return jsonify(hide_cost(so.detail(conn(), oid)))

    # ------------------------------------------------------------ clientes e fornecedores
    @api("/api/customers", perm="ver_clientes")
    def customers_list():
        return jsonify(registry.search_parties(conn(), "customers", request.args.get("q", ""), request.args.get("inactive") == "1"))

    @api("/api/customers", ["POST"], perm="ver_clientes")
    def customers_create():
        return jsonify({"id": registry.save_party(conn(), g.user, "customers", body())}), 201

    @api("/api/customers/<int:cid>", ["PUT"], perm="ver_clientes")
    def customers_update(cid):
        registry.save_party(conn(), g.user, "customers", body(), cid)
        return jsonify({"ok": True})

    @api("/api/customers/<int:cid>/history", perm="ver_clientes")
    def customers_history(cid):
        return jsonify(registry.customer_history(conn(), cid))

    @api("/api/customers/<int:cid>/active", ["POST"], perm="ver_clientes")
    def customers_active(cid):
        registry.set_party_active(conn(), g.user, "customers", cid, bool(body().get("active")))
        return jsonify({"ok": True})

    @api("/api/suppliers", anyperm=("gerenciar_produtos", "movimentar_estoque", "gerenciar_aparelhos", "gerenciar_financeiro"))
    def suppliers_list():
        return jsonify(registry.search_parties(conn(), "suppliers", request.args.get("q", ""), request.args.get("inactive") == "1"))

    @api("/api/suppliers", ["POST"], perm="gerenciar_produtos")
    def suppliers_create():
        return jsonify({"id": registry.save_party(conn(), g.user, "suppliers", body())}), 201

    @api("/api/suppliers/<int:sid>", ["PUT"], perm="gerenciar_produtos")
    def suppliers_update(sid):
        registry.save_party(conn(), g.user, "suppliers", body(), sid)
        return jsonify({"ok": True})

    @api("/api/suppliers/<int:sid>/history", perm="gerenciar_produtos")
    def suppliers_history(sid):
        return jsonify(hide_cost(registry.supplier_history(conn(), sid)))

    @api("/api/suppliers/<int:sid>/active", ["POST"], perm="gerenciar_produtos")
    def suppliers_active(sid):
        registry.set_party_active(conn(), g.user, "suppliers", sid, bool(body().get("active")))
        return jsonify({"ok": True})

    # ------------------------------------------------------------ financeiro
    @api("/api/dashboard")
    def dashboard():
        return jsonify(sv.dashboard(conn(), g.perms))

    @api("/api/finance/summary", perm="ver_financeiro")
    def fin_summary():
        f, t = dates()
        return jsonify(_finance_view(finance.summary(conn(), f, t)))

    def _finance_view(s):
        if "ver_lucros" in g.perms:
            return s
        return {k: v for k, v in s.items() if k not in ("cost_cents", "gross_profit_cents", "result_cents")}

    @api("/api/finance/periods", perm="ver_financeiro")
    def fin_periods():
        return jsonify({k: _finance_view(v) for k, v in finance.periods(conn()).items()})

    @api("/api/finance/cashflow", perm="ver_financeiro")
    def fin_cashflow():
        f, t = dates()
        return jsonify(finance.cashflow(conn(), f, t))

    @api("/api/finance/receivables", perm="ver_financeiro")
    def fin_receivables():
        return jsonify(finance.receivables_overview(conn()))

    @api("/api/payables", perm="ver_financeiro")
    def payables_list():
        a = request.args
        return jsonify(finance.list_payables(conn(), a.get("status", "abertas"), a.get("from"), a.get("to"), a.get("kind")))

    @api("/api/payables", ["POST"], perm="gerenciar_financeiro")
    def payables_create():
        return jsonify({"ids": finance.create_payable(conn(), g.user, g.perms, body())}), 201

    @api("/api/payables/<int:pid>/pay", ["POST"], perm="gerenciar_financeiro")
    def payables_pay(pid):
        d = body()
        finance.pay_payable(conn(), g.user, g.perms, pid, d.get("paid_cents"), d.get("method"), d.get("paid_date"))
        return jsonify({"ok": True})

    @api("/api/payables/<int:pid>", ["DELETE"], perm="gerenciar_financeiro")
    def payables_delete(pid):
        finance.delete_payable(conn(), g.user, g.perms, pid)
        return jsonify({"ok": True})

    @api("/api/receivables", ["POST"], perm="gerenciar_financeiro")
    def receivables_create():
        return jsonify({"id": finance.create_receivable(conn(), g.user, g.perms, body())}), 201

    @api("/api/receivables/<int:rid>/receive", ["POST"], perm="gerenciar_financeiro")
    def receivables_receive(rid):
        d = body()
        finance.receive_receivable(conn(), g.user, g.perms, rid, d.get("method"), d.get("received_cents"))
        return jsonify({"ok": True})

    # ------------------------------------------------------------ devoluções, trocas e garantias
    @api("/api/returns", ["POST"], anyperm=("registrar_devolucoes", "vender"))
    def returns_create():
        rid = after_sales.create_return(conn(), g.user, g.perms, body())
        return jsonify({"id": rid}), 201

    @api("/api/returns", anyperm=("registrar_devolucoes", "ver_relatorios", "ver_financeiro"))
    def returns_list():
        f, t = request.args.get("from"), request.args.get("to")
        return jsonify(after_sales.list_returns(conn(), f, t))

    @api("/api/warranty/lookup", anyperm=("gerenciar_garantias", "vender", "gerenciar_os"))
    def warranty_lookup():
        return jsonify(after_sales.warranty_lookup(conn(), request.args.get("q", "")))

    @api("/api/warranty/claims", perm="gerenciar_garantias")
    def claims_list():
        return jsonify(after_sales.list_claims(conn(), request.args.get("status") or None, (request.args.get("q") or "").strip() or None))

    @api("/api/warranty/claims", ["POST"], perm="gerenciar_garantias")
    def claims_create():
        return jsonify({"id": after_sales.create_claim(conn(), g.user, g.perms, body())}), 201

    @api("/api/warranty/claims/<int:cid>", ["PUT"], perm="gerenciar_garantias")
    def claims_update(cid):
        after_sales.update_claim(conn(), g.user, g.perms, cid, body())
        return jsonify({"ok": True})

    # ------------------------------------------------------------ inventário
    @api("/api/inventory", perm="ajustar_estoque")
    def inv_list():
        rows = conn().execute("SELECT i.*, u.name AS user_name FROM inventory_counts i JOIN users u ON u.id=i.created_by ORDER BY i.id DESC LIMIT 50").fetchall()
        return jsonify([dict(r) for r in rows])

    @api("/api/inventory", ["POST"], perm="ajustar_estoque")
    def inv_start():
        return jsonify({"id": registry.start_count(conn(), g.user, g.perms, body().get("name"))}), 201

    @api("/api/inventory/<int:cid>", perm="ajustar_estoque")
    def inv_get(cid):
        return jsonify(hide_cost(registry.count_detail(conn(), cid)))

    @api("/api/inventory/<int:cid>/scan", ["POST"], perm="ajustar_estoque")
    def inv_scan(cid):
        d = body()
        return jsonify(registry.count_scan(conn(), g.user, g.perms, cid, d.get("code"), d.get("qty", 1)))

    @api("/api/inventory/<int:cid>/item", ["PUT"], perm="ajustar_estoque")
    def inv_item(cid):
        d = body()
        registry.count_set(conn(), g.user, g.perms, cid, d.get("product_id"), d.get("qty"))
        return jsonify({"ok": True})

    @api("/api/inventory/<int:cid>/finish", ["POST"], perm="ajustar_estoque")
    def inv_finish(cid):
        n = registry.finish_count(conn(), g.user, g.perms, cid, bool(body().get("zero_uncounted")))
        return jsonify({"adjusted": n})

    @api("/api/inventory/<int:cid>/cancel", ["POST"], perm="ajustar_estoque")
    def inv_cancel(cid):
        registry.cancel_count(conn(), g.user, g.perms, cid)
        return jsonify({"ok": True})

    # ------------------------------------------------------------ relatórios
    @api("/api/reports", perm="ver_relatorios")
    def reports_list():
        return jsonify(reports.available(g.perms))

    @api("/api/reports/<name>", perm="ver_relatorios")
    def reports_run(name):
        filters = {k: v for k, v in request.args.items() if k not in ("format",) and v != ""}
        rep = reports.run(conn(), name, filters, g.perms)
        fmt = request.args.get("format", "json")
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        if fmt == "csv":
            return Response(reports.to_csv(rep), mimetype="text/csv; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="{name}-{stamp}.csv"'})
        if fmt == "xlsx":
            return Response(reports.to_xlsx(rep), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            headers={"Content-Disposition": f'attachment; filename="{name}-{stamp}.xlsx"'})
        return jsonify(rep)

    # ------------------------------------------------------------ auditoria
    @api("/api/audit", perm="ver_auditoria")
    def audit_list():
        sql = ("SELECT a.*, u.name AS user_name, x.name AS authorized_name FROM audit_log a LEFT JOIN users u ON u.id=a.user_id"
               " LEFT JOIN users x ON x.id=a.authorized_by WHERE 1=1")
        args = []
        if request.args.get("from"):
            sql += " AND date(a.created_at)>=?"; args.append(request.args["from"])
        if request.args.get("to"):
            sql += " AND date(a.created_at)<=?"; args.append(request.args["to"])
        if request.args.get("q"):
            sql += " AND (a.action LIKE ? OR a.entity LIKE ? OR u.name LIKE ?)"; args += [f"%{request.args['q']}%"] * 3
        return jsonify([dict(r) for r in conn().execute(sql + " ORDER BY a.id DESC LIMIT 500", args)])

    # ------------------------------------------------------------ backup
    def _safe_backup(kind):
        try:
            keep = int(sv.get_settings(db.connect()).get("backup_keep") or 30)
            backup.make_backup(kind, keep=keep)
        except Exception:
            app.logger.exception("Falha no backup automático")

    @api("/api/backups", perm="gerenciar_backup")
    def backups_list():
        return jsonify(backup.list_backups())

    @api("/api/backups", ["POST"], perm="gerenciar_backup", tx=False)
    def backups_create():
        p = backup.make_backup("manual", keep=60)
        with db.tx(conn()):
            sv.audit(conn(), g.user["id"], "backup_criado", "backup", None, after={"arquivo": p.name})
        return jsonify({"name": p.name}), 201

    @api("/api/backups/<name>/download", perm="gerenciar_backup")
    def backups_download(name):
        return send_file(backup.backup_path(name), as_attachment=True, download_name=name)

    @api("/api/backups/restore", ["POST"], perm="gerenciar_backup", tx=False)
    def backups_restore():
        if request.form.get("confirm", "").strip().upper() != "RESTAURAR":
            raise ApiError("Digite RESTAURAR para confirmar.")
        if not sv.check_credentials(conn(), g.user["username"], request.form.get("password")):
            raise ApiError("Senha incorreta.", 403)
        tmp = db.data_dir() / f"restore-{secrets.token_hex(4)}.tmp"
        try:
            if request.form.get("name"):
                src = backup.backup_path(request.form["name"])
            else:
                f = request.files.get("file")
                if not f:
                    raise ApiError("Selecione o arquivo de backup.")
                f.save(tmp)
                src = tmp
            result = backup.restore(src)
        finally:
            if tmp.exists():
                tmp.unlink()
        app.config["BOOT_ID"] = secrets.token_hex(8)  # derruba todas as sessões
        session.clear()
        return jsonify({"ok": True, **result})

    # ------------------------------------------------------------ impressão (comprovantes e OS)
    def _printer_guard():
        user = current_user()
        if not user:
            return redirect("/")
        g.user = user
        g.perms = sv.permissions_of(conn(), user)
        return None

    def _tpl_ctx():
        c = conn()
        return {"settings": sv.get_settings(c), "methods": {m["key"]: m["label"] for m in sv.payment_methods(c)},
                "width": request.args.get("w", "80"), "autoprint": request.args.get("print") == "1"}

    @app.template_filter("brl")
    def _brl(cents):
        return sv.money(cents or 0)

    @app.template_filter("dt")
    def _dt(v):
        if not v:
            return ""
        v = str(v)
        try:
            if len(v) > 10:
                return datetime.strptime(v[:19], "%Y-%m-%d %H:%M:%S").strftime("%d/%m/%Y %H:%M")
            return datetime.strptime(v[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            return v

    @app.route("/print/sale/<int:sid>")
    def print_sale(sid):
        deny = _printer_guard()
        if deny:
            return deny
        if not ({"vender", "ver_financeiro"} & g.perms):
            abort(403)
        d = _sale_visible(sid)
        return render_template("receipt.html", sale=d, **_tpl_ctx())

    @app.route("/print/os/<int:oid>")
    def print_os(oid):
        deny = _printer_guard()
        if deny:
            return deny
        if "gerenciar_os" not in g.perms:
            abort(403)
        return render_template("os.html", os=so.detail(conn(), oid), STATUS=so.STATUS, **_tpl_ctx())

    # backup automático diário (na abertura e a cada 6 horas)
    if not testing:
        _safe_backup("auto")

        def loop():
            while True:
                time.sleep(6 * 3600)
                _safe_backup("auto")
        threading.Thread(target=loop, daemon=True).start()
    return app
