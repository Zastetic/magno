"""Acesso ao banco do Barbearia Magno — SQLite com SQL puro, sem ORM.

O banco nasce de `docs/schema.sql` (fonte única da verdade do schema) e é idempotente:
todo CREATE usa IF NOT EXISTS e todo seed usa INSERT OR IGNORE, então subir o servidor
N vezes não recria nem duplica nada. Bancos antigos passam por `migrar()` antes.
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

# v2: telefone e senha_hash deixaram de ser obrigatórios (entra quem tem telefone+PIN OU Google).
# Espelha a definição de `usuarios` em docs/schema.sql — manter as duas juntas.
DDL_USUARIOS_V2 = """
CREATE TABLE usuarios_novo (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  nome                 TEXT    NOT NULL,
  telefone             TEXT    UNIQUE,
  email                TEXT,
  senha_hash           TEXT,
  google_sub           TEXT,
  foto_url             TEXT,
  papel                TEXT    NOT NULL DEFAULT 'cliente'
                               CHECK (papel IN ('cliente','barbeiro','admin')),
  ativo                INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1)),
  consentimento_lgpd_em TEXT,
  anonimizado_em       TEXT,
  ultimo_login_em      TEXT,
  criado_em            TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  atualizado_em        TEXT,
  CHECK (senha_hash IS NOT NULL OR google_sub IS NOT NULL)
)
"""


def conectar() -> sqlite3.Connection:
    """Conexão nova, com as pragmas que importam: FK ligada, WAL e timeout de lock."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=PRAZO_LOCK_S)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA busy_timeout = 5000")  # ms — não estoura com escrita concorrente
    return con


def migrar(con: sqlite3.Connection) -> bool:
    """Leva o banco v1 (só telefone+PIN) para o v2 (telefone+PIN ou Google).

    SQLite não remove NOT NULL por ALTER TABLE, então a tabela é reconstruída
    preservando ids e dados. ATENÇÃO à ordem: esta migração roda ANTES do
    schema.sql, senão os índices novos (que citam google_sub) falhariam.
    """
    colunas = {row["name"]: row["notnull"] for row in con.execute("PRAGMA table_info(usuarios)")}
    if not colunas:
        return False  # banco novo — o schema.sql já cria na forma atual

    falta_google = "google_sub" not in colunas
    telefone_obrigatorio = bool(colunas.get("telefone", 0))
    senha_obrigatoria = bool(colunas.get("senha_hash", 0))
    if not (falta_google or telefone_obrigatorio or senha_obrigatoria):
        return False

    con.commit()  # PRAGMA foreign_keys é ignorado dentro de transação
    con.execute("PRAGMA foreign_keys = OFF")
    con.execute("BEGIN")
    try:
        con.execute(DDL_USUARIOS_V2)
        con.execute("""
            INSERT INTO usuarios_novo
              (id, nome, telefone, email, senha_hash, google_sub, foto_url, papel, ativo,
               consentimento_lgpd_em, anonimizado_em, ultimo_login_em, criado_em, atualizado_em)
            SELECT id, nome, telefone, email, senha_hash, NULL, NULL, papel, ativo,
                   consentimento_lgpd_em, anonimizado_em, NULL, criado_em, atualizado_em
              FROM usuarios
        """)
        con.execute("DROP TABLE usuarios")
        con.execute("ALTER TABLE usuarios_novo RENAME TO usuarios")
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.execute("PRAGMA foreign_keys = ON")
    return True


def inicializar() -> Path:
    """Aplica migração + schema + seed. Idempotente (seguro rodar a cada boot)."""
    sql = SCHEMA_SQL.read_text(encoding="utf-8")
    con = conectar()
    try:
        migrou = migrar(con)
        con.executescript(sql)
        con.commit()
    finally:
        con.close()
    if migrou:
        print("[magno] banco migrado para o schema v2 (login por telefone+PIN ou Google)")
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


def registrar_evento(tipo: str, ator_id: int | None = None, agendamento_id: int | None = None,
                     payload: str | None = None) -> None:
    """Auditoria: quem fez o quê. Nunca derruba a requisição se falhar."""
    try:
        con = conectar()
        try:
            con.execute(
                "INSERT INTO eventos (tipo, ator_id, agendamento_id, payload) VALUES (?, ?, ?, ?)",
                (tipo, ator_id, agendamento_id, payload),
            )
            con.commit()
        finally:
            con.close()
    except sqlite3.Error:
        pass


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
