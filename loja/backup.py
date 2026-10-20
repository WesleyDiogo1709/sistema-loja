"""Backup e restauração do banco SQLite (usa a API de backup do SQLite: cópia consistente com o sistema em uso)."""
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from . import db
from .services import ApiError

REQUIRED_TABLES = {"users", "products", "sales", "sale_items", "sale_payments", "stock_movements", "settings", "audit_log"}


def backup_dir():
    p = db.data_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def make_backup(kind="manual", keep=None):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = backup_dir() / f"loja-{kind}-{stamp}.db"
    n = 1
    while dest.exists():
        dest = backup_dir() / f"loja-{kind}-{stamp}-{n}.db"
        n += 1
    src = db.connect()
    try:
        out = sqlite3.connect(str(dest))
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    if keep:
        prune(kind, keep)
    return dest


def prune(kind, keep):
    files = sorted(backup_dir().glob(f"loja-{kind}-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[int(keep):]:
        try:
            old.unlink()
        except OSError:
            pass


def list_backups():
    out = []
    for p in sorted(backup_dir().glob("loja-*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
        st = p.stat()
        out.append({"name": p.name, "size": st.st_size, "created_at": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "kind": p.name.split("-")[1]})
    return out


def backup_path(name):
    if not re.fullmatch(r"loja-[a-z\-]+-[0-9\-]+\.db", name or ""):
        raise ApiError("Nome de backup inválido.")
    p = backup_dir() / name
    if not p.is_file():
        raise ApiError("Backup não encontrado.", 404)
    return p


def validate(path):
    """Confere se o arquivo é um banco desta aplicação e se está íntegro. Retorna informações básicas."""
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        raise ApiError("O arquivo enviado não é um banco de dados válido.")
    try:
        try:
            ok = c.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        except sqlite3.DatabaseError:
            raise ApiError("O arquivo enviado não é um banco de dados válido.")
        if ok != "ok":
            raise ApiError("O backup está corrompido (falha na verificação de integridade).")
        if not REQUIRED_TABLES <= tables:
            raise ApiError("Este arquivo não é um backup do Sistema da Loja.")
        version = c.execute("PRAGMA user_version").fetchone()[0]
        if version > db.SCHEMA_VERSION + len(db.MIGRATIONS):
            raise ApiError("Este backup foi criado por uma versão mais nova do sistema. Atualize o sistema antes de restaurar.")
        info = {
            "users": c.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "products": c.execute("SELECT COUNT(*) FROM products").fetchone()[0],
            "sales": c.execute("SELECT COUNT(*) FROM sales").fetchone()[0],
        }
        if info["users"] == 0:
            raise ApiError("O backup não possui usuários e não permitiria entrar no sistema.")
        return info
    finally:
        c.close()


def restore(path):
    """Restaura um backup sobre o banco atual. Antes, guarda uma cópia de segurança do estado atual."""
    info = validate(path)
    safety = make_backup("antes-restauracao", keep=10)
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    dest = db.connect()
    try:
        src.backup(dest)
    finally:
        src.close()
        dest.close()
    db.init_db()  # aplica migrações caso o backup seja de versão anterior
    return {"safety_backup": safety.name, **info}
