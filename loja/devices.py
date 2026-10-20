"""Aparelhos individuais (iPhones seminovos etc.): um registro por unidade, com IMEI/série."""
import re

from .barcode import normalize
from .services import (ApiError, DEVICE_STATUS, audit, clean, device_event, now, to_int, warranty_days)

MANUAL_STATUS = ("disponivel", "reservado", "em_teste", "em_manutencao", "devolvido")


def luhn_ok(number):
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def clean_imei(value, label):
    v = re.sub(r"[\s\-]", "", value or "")
    if not v:
        return None
    if not (v.isdigit() and len(v) == 15):
        raise ApiError(f"{label} deve ter 15 dígitos numéricos.")
    if not luhn_ok(v):
        raise ApiError(f"{label} inválido: o dígito verificador não confere. Confira a digitação.")
    return v


def _payload(data):
    brand = clean(data.get("brand"))
    model = clean(data.get("model"))
    if not brand or not model:
        raise ApiError("Informe a marca e o modelo do aparelho.")
    bat = data.get("battery_health")
    if bat in (None, ""):
        bat = None
    else:
        bat = to_int(bat, "Saúde da bateria", minimum=0, maximum=100)
    out = {
        "brand": brand, "model": model,
        "storage": clean(data.get("storage")), "color": clean(data.get("color")),
        "imei1": clean_imei(data.get("imei1"), "IMEI 1"), "imei2": clean_imei(data.get("imei2"), "IMEI 2"),
        "serial": normalize(data.get("serial")) or None,
        "battery_health": bat,
        "condition": clean(data.get("condition")), "origin": clean(data.get("origin")),
        "cost_cents": to_int(data.get("cost_cents", 0), "Custo de compra"),
        "price_cents": to_int(data.get("price_cents", 0), "Preço de venda"),
        "supplier": clean(data.get("supplier")),
        "warranty_days": warranty_days(data.get("warranty_days")),
        "notes": clean(data.get("notes")),
    }
    if out["imei1"] and out["imei1"] == out["imei2"]:
        raise ApiError("IMEI 1 e IMEI 2 não podem ser iguais.")
    return out


def _check_unique(conn, p, exclude_id=0):
    for label, field in (("IMEI 1", "imei1"), ("IMEI 2", "imei2"), ("Número de série", "serial")):
        val = p.get(field)
        if not val:
            continue
        cols = ("imei1", "imei2") if field.startswith("imei") else ("serial",)
        for c in cols:
            row = conn.execute(f"SELECT id, code, brand, model FROM devices WHERE {c}=? AND id<>?", (val, exclude_id)).fetchone()
            if row:
                raise ApiError(f"{label} {val} já está cadastrado no aparelho {row['code']} ({row['brand']} {row['model']}).",
                               409, "duplicate_device")


def device_row(conn, did):
    row = conn.execute("SELECT * FROM devices WHERE id=?", (did,)).fetchone()
    if not row:
        raise ApiError("Aparelho não encontrado.", 404)
    return row


def create_device(conn, user, perms, data):
    if "gerenciar_aparelhos" not in perms:
        raise ApiError("Sem permissão para cadastrar aparelhos.", 403)
    p = _payload(data)
    _check_unique(conn, p)
    entry = clean(data.get("entry_date")) or now()[:10]
    cols = list(p)
    cur = conn.execute(
        f"INSERT INTO devices({','.join(cols)}, entry_date, created_at) VALUES ({','.join('?' * len(cols))},?,?)",
        [p[c] for c in cols] + [entry, now()])
    did = cur.lastrowid
    conn.execute("UPDATE devices SET code=? WHERE id=?", (f"APL{did:06d}", did))
    device_event(conn, did, "entrada", "disponivel", user["id"], "Aparelho cadastrado")
    audit(conn, user["id"], "aparelho_criado", "device", did, after=p)
    return device_row(conn, did)


def update_device(conn, user, perms, did, data):
    if "gerenciar_aparelhos" not in perms:
        raise ApiError("Sem permissão para editar aparelhos.", 403)
    old = device_row(conn, did)
    p = _payload({**dict(old), **data})
    if p["price_cents"] != old["price_cents"] and "alterar_precos" not in perms:
        raise ApiError("Sem permissão para alterar preços.", 403)
    if p["cost_cents"] != old["cost_cents"] and "ver_custos" not in perms:
        raise ApiError("Sem permissão para alterar custos.", 403)
    if old["status"] == "vendido" and (p["price_cents"] != old["price_cents"] or p["cost_cents"] != old["cost_cents"]):
        raise ApiError("Aparelho já vendido: preço e custo não podem mais ser alterados.", 409)
    _check_unique(conn, p, did)
    conn.execute(f"UPDATE devices SET {', '.join(c + '=?' for c in p)}, entry_date=? WHERE id=?",
                 list(p.values()) + [clean(data.get("entry_date")) or old["entry_date"], did])
    audit(conn, user["id"], "aparelho_alterado", "device", did,
          before={k: old[k] for k in p if old[k] != p[k]}, after={k: v for k, v in p.items() if old[k] != v})
    return device_row(conn, did)


def set_status(conn, user, perms, did, status, note=None, reserved_for=None):
    if "gerenciar_aparelhos" not in perms:
        raise ApiError("Sem permissão para alterar aparelhos.", 403)
    d = device_row(conn, did)
    if status not in MANUAL_STATUS:
        raise ApiError("Situação inválida. A situação \"Vendido\" só é definida por uma venda.")
    if d["status"] == "vendido":
        raise ApiError("Aparelho vendido: use cancelamento ou devolução da venda para liberá-lo.", 409)
    conn.execute("UPDATE devices SET status=?, reserved_for=? WHERE id=?",
                 (status, clean(reserved_for) if status == "reservado" else None, did))
    device_event(conn, did, "mudanca_situacao", status, user["id"], clean(note))
    audit(conn, user["id"], "aparelho_situacao", "device", did, before={"status": d["status"]}, after={"status": status})
    return device_row(conn, did)


def search(conn, q="", status=None, limit=200):
    q = (q or "").strip()
    sql = "SELECT * FROM devices WHERE 1=1"
    args = []
    if status:
        sql += " AND status=?"
        args.append(status)
    if q:
        like = f"%{q}%"
        sql += (" AND (code LIKE ? OR imei1 LIKE ? OR imei2 LIKE ? OR serial LIKE ? OR norm(brand||' '||model||' '||COALESCE(storage,'')"
                "||' '||COALESCE(color,'')) LIKE ?)")
        from .db import unaccent_lower
        args += [like, like, like, like, f"%{unaccent_lower(q)}%"]
    sql += " ORDER BY CASE status WHEN 'disponivel' THEN 0 ELSE 1 END, id DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in conn.execute(sql, args)]


def find_by_code(conn, code):
    code = normalize(code)
    if not code:
        return None
    return conn.execute(
        "SELECT * FROM devices WHERE code=? OR imei1=? OR imei2=? OR serial=?", (code, code, code, code)).fetchone()


def detail(conn, did):
    d = dict(device_row(conn, did))
    d["status_label"] = DEVICE_STATUS.get(d["status"], d["status"])
    d["events"] = [dict(r) for r in conn.execute(
        "SELECT e.*, u.name AS user_name FROM device_events e LEFT JOIN users u ON u.id=e.user_id WHERE device_id=? ORDER BY e.id DESC", (did,))]
    keys = [k for k in (d["imei1"], d["imei2"], d["serial"]) if k]
    d["repairs"] = []
    if keys:
        ph = ",".join("?" * len(keys))
        d["repairs"] = [dict(r) for r in conn.execute(
            f"SELECT id, entry_at, defect, status FROM service_orders WHERE imei IN ({ph}) OR serial IN ({ph}) ORDER BY id DESC",
            keys + keys)]
    sale = conn.execute(
        "SELECT s.id, s.created_at, s.status, i.warranty_ends FROM sale_items i JOIN sales s ON s.id=i.sale_id"
        " WHERE i.device_id=? ORDER BY s.id DESC LIMIT 1", (did,)).fetchone()
    d["last_sale"] = dict(sale) if sale else None
    return d
