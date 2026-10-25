"""Acesso ao banco SQLite: conexão, transações, criação e migração do esquema."""
import os
import sqlite3
import sys
import unicodedata
from contextlib import contextmanager
from pathlib import Path

SCHEMA_BASE = 1      # esquema de loja/schema.sql
SCHEMA_VERSION = 2   # versão mais recente (ver loja/migrations.py)


def data_dir():
    env = os.environ.get("LOJA_DATA_DIR")
    if env:
        p = Path(env)
    elif getattr(sys, "frozen", False):
        p = Path(sys.executable).parent / "dados"
    else:
        p = Path(__file__).resolve().parent.parent / "dados"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path():
    return data_dir() / os.environ.get("LOJA_DB_NAME", "loja.db")


def unaccent_lower(value):
    if value is None:
        return ""
    s = unicodedata.normalize("NFD", str(value))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def connect(path=None):
    conn = sqlite3.connect(str(path or db_path()), timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")  # durabilidade: dados sobrevivem a queda de energia
    conn.create_function("norm", 1, unaccent_lower, deterministic=True)
    return conn


@contextmanager
def tx(conn):
    """Transação com bloqueio de escrita imediato: operações concorrentes são serializadas."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _schema_sql():
    return (Path(__file__).resolve().parent / "schema.sql").read_text(encoding="utf-8")


# Migrações: {versao_destino: funcao(conn)}. A versão 1 é o esquema inicial (schema.sql); as demais ficam em migrations.py.
# Bancos que já têm dados são migrados na inicialização, depois de uma cópia de segurança automática.
def _migrations():
    from . import migrations
    return migrations.MIGRATIONS


def init_db():
    from . import services  # evita import circular

    conn = connect()
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        fresh = False
        if version == 0:
            has_tables = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
            if not has_tables:
                with tx(conn):
                    for stmt in _split_sql(_schema_sql()):
                        conn.execute(stmt)
                    services.seed_defaults(conn)
                fresh = True
            conn.execute(f"PRAGMA user_version={SCHEMA_BASE}")
            version = SCHEMA_BASE
        migrations = _migrations()
        pending = [t for t in sorted(migrations) if t > version]
        if pending and not fresh:
            try:  # banco com dados: cópia de segurança antes de migrar
                from . import backup
                backup.make_backup("pre-migracao")
            except Exception:  # noqa: BLE001 - não impede a migração; o erro fica no log
                import logging
                logging.getLogger(__name__).exception("Não foi possível criar o backup antes da migração")
        for target in pending:
            with tx(conn):
                migrations[target](conn)
            conn.execute(f"PRAGMA user_version={target}")
            version = target
    finally:
        conn.close()


def _split_sql(script):
    """Divide o script em comandos (sem ponto e vírgula dentro de strings no nosso esquema)."""
    lines = [ln for ln in script.splitlines() if not ln.strip().startswith("--")]
    cleaned = "\n".join(ln.split("--")[0] if "--" in ln else ln for ln in lines)
    return [s.strip() for s in cleaned.split(";") if s.strip()]
