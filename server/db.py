"""Acesso ao banco do Barbearia Magno — SQLite com SQL puro, sem ORM.

O banco nasce de `docs/schema.sql` (fonte única da verdade do schema) e é idempotente:
todo CREATE usa IF NOT EXISTS e todo seed usa INSERT OR IGNORE, então subir o servidor
N vezes não recria nem duplica nada.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SCHEMA_SQL = RAIZ / "docs" / "schema.sql"
ENV_LOCAL = RAIZ / ".env.local"


def carregar_env_local() -> None:
    """Lê .env.local (se existir) sem sobrescrever variáveis já definidas no ambiente."""
    if not ENV_LOCAL.exists():
        return
    for linha in ENV_LOCAL.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


carregar_env_local()

DB_PATH = Path(
    os.environ.get("MAGNO_DB")
    or (Path.home() / ".local" / "share" / "magno" / "magno.db")  # ext4 nativo: ver D21
)
PRAZO_LOCK_S = 5.0


def conectar() -> sqlite3.Connection:
    """Conexão nova, com as pragmas que importam: FK ligada, WAL e timeout de lock."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=PRAZO_LOCK_S)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA busy_timeout = 5000")  # ms — não estoura com escrita concorrente
    return con


def inicializar() -> Path:
    """Aplica o schema + seed. Idempotente (seguro rodar a cada boot)."""
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    con = conectar()
    try:
        con.executescript(sql)
        con.commit()
    finally:
        con.close()
    return DB_PATH


def config(chave: str, padrao: str | None = None) -> str | None:
    con = conectar()
    try:
        linha = con.execute("SELECT valor FROM configuracoes WHERE chave = ?", (chave,)).fetchone()
        return linha["valor"] if linha else padrao
    finally:
        con.close()


def configuracoes() -> dict[str, str]:
    con = conectar()
    try:
        return {r["chave"]: r["valor"] for r in con.execute("SELECT chave, valor FROM configuracoes ORDER BY chave")}
    finally:
        con.close()


def resumo() -> dict:
    """Panorama do banco para o health-check: prova que o SQL rodou de verdade."""
    con = conectar()
    try:
        tabelas = [
            r["name"]
            for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        contagens = {t: con.execute(f'SELECT COUNT(*) AS c FROM "{t}"').fetchone()["c"] for t in tabelas}
        indices = [
            r["name"]
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx%' ORDER BY name")
        ]
        return {
            "arquivo": str(DB_PATH),
            "tabelas": len(tabelas),
            "contagens": contagens,
            "indices": len(indices),
            "integridade": con.execute("PRAGMA quick_check").fetchone()[0],
        }
    finally:
        con.close()
