"""Acesso ao banco SQLite: conexão, transações, criação e migração do esquema."""
import os
import sqlite3
import sys
import unicodedata
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1


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


# Migrações futuras: {versao_destino: "SQL"}. A versão 1 é o esquema inicial.
MIGRATIONS = {}


def init_db():
    from . import services  # evita import circular

    conn = connect()
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            has_tables = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
            ).fetchone()
            if not has_tables:
                with tx(conn):
                    for stmt in _split_sql(_schema_sql()):
                        conn.execute(stmt)
                    services.seed_defaults(conn)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            version = SCHEMA_VERSION
        for target in sorted(MIGRATIONS):
            if target > version:
                with tx(conn):
                    for stmt in _split_sql(MIGRATIONS[target]):
                        conn.execute(stmt)
                conn.execute(f"PRAGMA user_version={target}")
                version = target
    finally:
        conn.close()


def _split_sql(script):
    """Divide o script em comandos (sem ponto e vírgula dentro de strings no nosso esquema)."""
    lines = [ln for ln in script.splitlines() if not ln.strip().startswith("--")]
    cleaned = "\n".join(ln.split("--")[0] if "--" in ln else ln for ln in lines)
    return [s.strip() for s in cleaned.split(";") if s.strip()]
