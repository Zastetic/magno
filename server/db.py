"""Acesso ao banco do Barbearia Magno — SQLite com SQL puro, sem ORM.

O banco nasce de `docs/schema.sql` (fonte única da verdade do schema) e é idempotente:
todo CREATE usa IF NOT EXISTS e todo seed usa INSERT OR IGNORE, então subir o servidor
N vezes não recria nem duplica nada. Bancos antigos passam por `migrar()` antes.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import datetime, timezone
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

# Colunas da tabela usuarios na forma atual (v4). Qualquer banco que não tenha todas, ou que
# ainda exija telefone/senha, é reconstruído. Espelha docs/schema.sql — manter as duas juntas.
COLUNAS_USUARIOS = (
    "id", "nome", "idade", "telefone", "email", "email_verificado_em", "senha_hash", "google_sub",
    "foto_url", "papel", "ativo", "consentimento_lgpd_em", "anonimizado_em",
    "ultimo_login_em", "criado_em", "atualizado_em",
)

DDL_USUARIOS_ATUAL = """
CREATE TABLE usuarios_novo (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  nome                 TEXT    NOT NULL,
  idade                INTEGER CHECK (idade BETWEEN 13 AND 120),
  telefone             TEXT    UNIQUE,
  email                TEXT,
  email_verificado_em  TEXT,
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
  CHECK (senha_hash IS NOT NULL OR google_sub IS NOT NULL OR email IS NOT NULL)
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


def ja_na_forma_atual(colunas: dict[str, dict]) -> bool:
    if not set(COLUNAS_USUARIOS) <= set(colunas):
        return False
    # telefone e senha precisam ser opcionais (conta só-Google e conta sem senha)
    return not colunas["telefone"]["notnull"] and not colunas["senha_hash"]["notnull"]


def migrar(con: sqlite3.Connection) -> bool:
    """Leva qualquer versão antiga de `usuarios` para a forma atual, preservando os dados.

    SQLite não remove NOT NULL nem troca CHECK por ALTER TABLE, então a tabela é
    reconstruída. As colunas que não existiam no banco antigo entram como NULL.
    ATENÇÃO à ordem: esta migração roda ANTES do schema.sql, senão os índices novos
    (que citam colunas novas) falhariam.
    """
    colunas = {row["name"]: dict(row) for row in con.execute("PRAGMA table_info(usuarios)")}
    if not colunas:
        return False  # banco novo — o schema.sql já cria na forma atual
    if ja_na_forma_atual(colunas):
        return False

    presentes = [c for c in COLUNAS_USUARIOS if c in colunas]
    lista = ", ".join(presentes)

    con.commit()  # PRAGMA foreign_keys é ignorado dentro de transação
    con.execute("PRAGMA foreign_keys = OFF")
    con.execute("BEGIN")
    try:
        con.execute(DDL_USUARIOS_ATUAL)
        con.execute(f"INSERT INTO usuarios_novo ({lista}) SELECT {lista} FROM usuarios")
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
    configurar_seed_dev()
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



def obter_usuario_por_email(email: str) -> dict | None:
    """Busca um usuário pelo e-mail (case-insensitive)."""
    con = conectar()
    try:
        return con.execute("SELECT * FROM usuarios WHERE lower(email) = ?", (email.lower(),)).fetchone()
    finally:
        con.close()


def obter_usuario_por_telefone(telefone: str) -> dict | None:
    """Busca um usuário pelo telefone (E.164)."""
    con = conectar()
    try:
        return con.execute("SELECT * FROM usuarios WHERE telefone = ?", (telefone,)).fetchone()
    finally:
        con.close()


def obter_servico_por_nome(nome: str) -> dict | None:
    con = conectar()
    try:
        return con.execute("SELECT * FROM servicos WHERE nome = ?", (nome,)).fetchone()
    finally:
        con.close()


def obter_profissional_por_apelido(apelido: str) -> dict | None:
    con = conectar()
    try:
        return con.execute("SELECT p.*, u.nome FROM profissionais p JOIN usuarios u ON p.usuario_id = u.id WHERE p.apelido = ?", (apelido,)).fetchone()
    finally:
        con.close()


def criar_agendamento(cliente_id: int, profissional_id: int, servico_id: int,
                      inicio_utc: datetime, fim_utc: datetime, duracao_min: int, preco_centavos: int,
                      observacao: str | None = None) -> dict:
    """Grava a reserva com timestamps UTC ISO; o endpoint já valida disponibilidade."""
    inicio = inicio_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fim = fim_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    con = conectar()
    try:
        codigo = secrets.token_urlsafe(8)
        cur = con.execute(
            "INSERT INTO agendamentos (codigo, cliente_id, profissional_id, servico_id, inicio, fim, duracao_min, preco_centavos, observacao) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (codigo, cliente_id, profissional_id, servico_id, inicio, fim, duracao_min, preco_centavos, observacao),
        )
        con.commit()
        return dict(con.execute("SELECT * FROM agendamentos WHERE id = ?", (cur.lastrowid,)).fetchone())
    finally:
        con.close()


def listar_agendamentos_do_cliente(cliente_id: int) -> list[dict]:
    con = conectar()
    try:
        return con.execute("SELECT * FROM agendamentos WHERE cliente_id = ? ORDER BY inicio DESC", (cliente_id,)).fetchall()
    finally:
        con.close()

def configurar_seed_dev() -> None:
    """Cria profissionais de demonstração apenas quando o modo demo é ativado."""
    if os.environ.get("MAGNO_SEED_DEV") != "1":
        return
    con = conectar()
    try:
        for nome, email, bio in (
            ("Rafael", "rafael@barbeariamagnum.com", "Especialista em degradê e navalha"),
            ("Bruno", "bruno@barbeariamagnum.com", "Clássico na tesoura"),
        ):
            con.execute(
                "INSERT OR IGNORE INTO usuarios (nome, email, papel) VALUES (?, ?, 'barbeiro')",
                (nome, email),
            )
            usuario = con.execute("SELECT id FROM usuarios WHERE email = ?", (email,)).fetchone()
            con.execute(
                "INSERT OR IGNORE INTO profissionais (usuario_id, apelido, bio) VALUES (?, ?, ?)",
                (usuario["id"], nome, bio),
            )
        for profissional in con.execute("SELECT id FROM profissionais"):
            for servico in con.execute("SELECT id FROM servicos"):
                con.execute(
                    "INSERT OR IGNORE INTO servico_profissional (servico_id, profissional_id) VALUES (?, ?)",
                    (servico["id"], profissional["id"]),
                )
        con.commit()
    finally:
        con.close()


def resumo() -> dict:
    """Panorama do banco para o health-check: prova que o SQL rodou de verdade."""
    con = conectar()
    try:
        tabelas = [r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        contagens = {t: con.execute(f'SELECT COUNT(*) AS c FROM \"{t}\"').fetchone()["c"] for t in tabelas}
        indices = [r["name"] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx%' ORDER BY name"
        )]
        return {"arquivo": str(DB_PATH), "tabelas": len(tabelas), "contagens": contagens,
                "indices": len(indices), "integridade": con.execute("PRAGMA quick_check").fetchone()[0]}
    finally:
        con.close()
