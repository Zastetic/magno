"""Migração do banco v1 (só telefone+PIN) para o v2 (telefone+PIN ou Google).

O ponto crítico: SQLite não remove NOT NULL por ALTER TABLE, então a tabela `usuarios`
é reconstruída. Estes testes provam que isso não perde dados e que não dá para rodar
a migração duas vezes por engano.
"""
import sqlite3

import pytest

from server import db

DDL_V1 = """
CREATE TABLE usuarios (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nome TEXT NOT NULL,
  telefone TEXT NOT NULL UNIQUE,
  email TEXT,
  senha_hash TEXT NOT NULL,
  papel TEXT NOT NULL DEFAULT 'cliente' CHECK (papel IN ('cliente','barbeiro','admin')),
  ativo INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1)),
  consentimento_lgpd_em TEXT,
  anonimizado_em TEXT,
  criado_em TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  atualizado_em TEXT
);
CREATE INDEX idx_usuarios_papel ON usuarios(papel, ativo);
"""


@pytest.fixture
def banco_antigo(tmp_path, monkeypatch):
    caminho = tmp_path / "v1.db"
    con = sqlite3.connect(caminho)
    con.executescript(DDL_V1)
    con.execute("""INSERT INTO usuarios (nome, telefone, senha_hash, email, papel)
                   VALUES ('Cliente Antigo', '5513997630784', 'pbkdf2_sha256$1$ab$cd',
                           'antigo@exemplo.test', 'cliente')""")
    con.commit()
    con.close()
    monkeypatch.setattr(db, "DB_PATH", caminho)
    return caminho


def abrir(caminho):
    con = sqlite3.connect(caminho)
    con.row_factory = sqlite3.Row
    return con


def test_migra_sem_perder_dados(banco_antigo):
    db.inicializar()
    con = abrir(banco_antigo)
    linha = con.execute("SELECT * FROM usuarios WHERE telefone = '5513997630784'").fetchone()
    assert linha is not None, "a conta antiga sumiu na migração"
    assert linha["nome"] == "Cliente Antigo"
    assert linha["senha_hash"] == "pbkdf2_sha256$1$ab$cd"
    assert linha["email"] == "antigo@exemplo.test"
    assert linha["google_sub"] is None
    assert linha["id"] == 1
    con.close()


def test_colunas_obrigatorias_viraram_opcionais(banco_antigo):
    db.inicializar()
    con = abrir(banco_antigo)
    colunas = {r["name"]: r["notnull"] for r in con.execute("PRAGMA table_info(usuarios)")}
    assert colunas["telefone"] == 0, "telefone ainda é obrigatório: conta só-Google não entra"
    assert colunas["senha_hash"] == 0, "senha_hash ainda é obrigatório"
    assert "google_sub" in colunas and "foto_url" in colunas and "ultimo_login_em" in colunas
    con.close()


def test_conta_sem_pin_e_sem_google_e_recusada(banco_antigo):
    db.inicializar()
    con = abrir(banco_antigo)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO usuarios (nome) VALUES ('Sem como entrar')")
    con.close()


def test_conta_so_google_entra(banco_antigo):
    db.inicializar()
    con = abrir(banco_antigo)
    con.execute("INSERT INTO usuarios (nome, email, google_sub, papel) VALUES ('Só Google', 'g@x.test', 'sub-1', 'barbeiro')")
    con.commit()
    assert con.execute("SELECT COUNT(*) FROM usuarios WHERE google_sub = 'sub-1'").fetchone()[0] == 1
    con.close()


def test_email_unico_ignorando_maiusculas(banco_antigo):
    db.inicializar()
    con = abrir(banco_antigo)
    con.execute("INSERT INTO usuarios (nome, email, google_sub) VALUES ('Um', 'pessoa@x.test', 'sub-a')")
    con.commit()
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO usuarios (nome, email, google_sub) VALUES ('Dois', 'PESSOA@X.TEST', 'sub-b')")
    con.close()


def test_google_sub_unico(banco_antigo):
    db.inicializar()
    con = abrir(banco_antigo)
    con.execute("INSERT INTO usuarios (nome, google_sub) VALUES ('Um', 'sub-repetido')")
    con.commit()
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO usuarios (nome, google_sub) VALUES ('Dois', 'sub-repetido')")
    con.close()


def test_migrar_e_idempotente(banco_antigo):
    db.inicializar()
    con = db.conectar()
    try:
        assert db.migrar(con) is False, "migrou de novo sem precisar"
    finally:
        con.close()
    # e o dado continua no lugar depois de mais um boot
    db.inicializar()
    con = abrir(banco_antigo)
    assert con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] >= 1
    con.close()


def test_banco_novo_nao_migra(tmp_path, monkeypatch):
    caminho = tmp_path / "novo.db"
    monkeypatch.setattr(db, "DB_PATH", caminho)
    con = db.conectar()
    try:
        assert db.migrar(con) is False       # nada para migrar: o schema já nasce v2
    finally:
        con.close()
    db.inicializar()
    con = abrir(caminho)
    tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"usuarios", "sessoes", "logins_pendentes", "agendamentos"} <= tabelas
    con.close()
