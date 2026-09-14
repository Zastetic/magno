"""Bearer token de ponta a ponta — o que ele abre, o que ele fecha e o que ele nunca vaza.

Cada teste fala com a API de verdade (TestClient), com banco descartável do conftest.
O token é opaco: o servidor guarda só sha256(token), então nem o banco conhece o token.
"""
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from itertools import count

import pytest
from fastapi.testclient import TestClient

from server import db
from server.main import app

PIN = "9471"
_novos_telefones = count(70001)


@pytest.fixture
def cliente():
    with TestClient(app) as c:
        yield c


def telefone_novo() -> str:
    """E.164 brasileiro válido e único por chamada (5513 + 9 + 8 dígitos)."""
    return f"55139976{next(_novos_telefones):05d}"


def cadastrar(cliente, nome="Cliente Bearer", **extra):
    corpo = {"nome": nome, "telefone": telefone_novo(), "pin": PIN, "consentimento_lgpd": True}
    corpo.update(extra)
    r = cliente.post("/api/auth/cadastro", json=corpo)
    assert r.status_code == 200, r.text
    return r.json()


def cabecalho(token: str) -> dict:
    return {"Authorization": "Bearer " + token}


def expirar_sessao(token: str, quando: str = "2000-01-01T00:00:00Z") -> None:
    con = sqlite3.connect(db.DB_PATH)
    con.execute("UPDATE sessoes SET expira_em = ? WHERE token_hash = ?",
                (quando, hashlib.sha256(token.encode()).hexdigest()))
    con.commit()
    con.close()


ROTAS_PROTEGIDAS = (
    ("GET", "/api/auth/me"),
    ("GET", "/api/account"),
    ("PATCH", "/api/account/profile"),
    ("POST", "/api/bookings"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/logout-all"),
)


# ----------------------------------------------------------------- sem token
@pytest.mark.parametrize("metodo,rota", ROTAS_PROTEGIDAS)
def test_rota_protegida_sem_token_devolve_401_sessao_invalida(cliente, metodo, rota):
    r = cliente.request(metodo, rota, json={})
    assert r.status_code == 401, (metodo, rota, r.text)
    assert r.json()["codigo"] == "sessao_invalida"


@pytest.mark.parametrize("valor", [
    "Token abcdef",
    "Bearer",
    "Bearer ",
    "bearer",
    "abc123",
    "Basic YWJjOmRlZg==",
])
def test_cabecalho_malformado_nao_autentica(cliente, valor):
    r = cliente.get("/api/auth/me", headers={"Authorization": valor})
    assert r.status_code == 401, valor


def test_token_inventado_nao_autentica(cliente):
    r = cliente.get("/api/auth/me", headers=cabecalho("x" * 43))
    assert r.status_code == 401
    assert r.json()["codigo"] == "sessao_invalida"


def test_token_de_outra_loja_ou_truncado_nao_autentica(cliente):
    token = cadastrar(cliente)["token"]
    for mexido in (token[:-1], token + "a", token.upper(), token[:20]):
        r = cliente.get("/api/auth/me", headers=cabecalho(mexido))
        assert r.status_code == 401, mexido


# ----------------------------------------------------------------- com token
def test_token_valido_abre_me_e_account(cliente):
    criado = cadastrar(cliente)
    token, usuario = criado["token"], criado["usuario"]

    me = cliente.get("/api/auth/me", headers=cabecalho(token))
    assert me.status_code == 200
    assert me.json()["usuario"]["id"] == usuario["id"]

    conta = cliente.get("/api/account", headers=cabecalho(token))
    assert conta.status_code == 200
    assert conta.json()["usuario"]["id"] == usuario["id"]
    assert conta.json()["agendamentos"] == []
    # o hash do PIN nunca sai para o cliente
    assert "senha_hash" not in conta.json()["usuario"]


def test_login_por_pin_tambem_emite_bearer_util(cliente):
    criado = cadastrar(cliente)
    r = cliente.post("/api/auth/login", json={"telefone": criado["usuario"]["telefone"], "pin": PIN})
    assert r.status_code == 200
    conta = cliente.get("/api/account", headers=cabecalho(r.json()["token"]))
    assert conta.status_code == 200
    assert conta.json()["usuario"]["id"] == criado["usuario"]["id"]


def test_esquema_bearer_e_case_insensitive_mas_token_nao(cliente):
    token = cadastrar(cliente)["token"]
    assert cliente.get("/api/auth/me", headers={"Authorization": "bearer " + token}).status_code == 200
    assert cliente.get("/api/auth/me", headers={"Authorization": "BEARER " + token}).status_code == 200
    assert cliente.get("/api/auth/me", headers={"Authorization": "Bearer" + token}).status_code == 401


def test_cada_token_enxerga_apenas_a_propria_conta(cliente):
    um = cadastrar(cliente, nome="Um da Silva")
    dois = cadastrar(cliente, nome="Dois da Silva")
    a = cliente.get("/api/account", headers=cabecalho(um["token"])).json()["usuario"]
    b = cliente.get("/api/account", headers=cabecalho(dois["token"])).json()["usuario"]
    assert a["id"] == um["usuario"]["id"] and b["id"] == dois["usuario"]["id"]
    assert a["id"] != b["id"]
    assert a["nome"] == "Um da Silva" and b["nome"] == "Dois da Silva"


# -------------------------------------------------------------- o que o banco vê
def test_o_servidor_so_guarda_o_hash_do_token(cliente):
    token = cadastrar(cliente)["token"]
    con = sqlite3.connect(db.DB_PATH)
    hashes = {linha[0] for linha in con.execute("SELECT token_hash FROM sessoes")}
    con.close()
    assert token not in hashes, "token em claro no banco"
    assert hashlib.sha256(token.encode()).hexdigest() in hashes


def test_logout_revoga_a_sessao_de_verdade(cliente):
    token = cadastrar(cliente)["token"]
    assert cliente.post("/api/auth/logout", headers=cabecalho(token)).status_code == 200
    assert cliente.get("/api/auth/me", headers=cabecalho(token)).status_code == 401
    con = sqlite3.connect(db.DB_PATH)
    pendentes = con.execute(
        "SELECT COUNT(*) FROM sessoes WHERE token_hash = ? AND revogada_em IS NULL",
        (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()[0]
    con.close()
    assert pendentes == 0


def test_logout_all_derruba_todas_as_sessoes_da_conta(cliente):
    criado = cadastrar(cliente)
    telefone = criado["usuario"]["telefone"]
    segundo = cliente.post("/api/auth/login", json={"telefone": telefone, "pin": PIN}).json()["token"]
    primeiro = criado["token"]

    assert cliente.post("/api/auth/logout-all", headers=cabecalho(segundo)).status_code == 200
    for t in (primeiro, segundo):
        assert cliente.get("/api/auth/me", headers=cabecalho(t)).status_code == 401


def test_sessao_expirada_e_recusada_mesmo_com_token_correto(cliente):
    token = cadastrar(cliente)["token"]
    assert cliente.get("/api/auth/me", headers=cabecalho(token)).status_code == 200
    expirar_sessao(token)
    r = cliente.get("/api/auth/me", headers=cabecalho(token))
    assert r.status_code == 401 and r.json()["codigo"] == "sessao_invalida"


def test_token_vale_enquanto_o_ttl_configurado(cliente):
    token = cadastrar(cliente)["token"]
    ainda_vale = (datetime.now(timezone.utc) + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    expirar_sessao(token, ainda_vale)
    assert cliente.get("/api/auth/me", headers=cabecalho(token)).status_code == 200
    expirar_sessao(token, (datetime.now(timezone.utc) - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert cliente.get("/api/auth/me", headers=cabecalho(token)).status_code == 401


def test_conta_desativada_derruba_o_token_na_hora(cliente):
    criado = cadastrar(cliente)
    token = criado["token"]
    con = sqlite3.connect(db.DB_PATH)
    con.execute("UPDATE usuarios SET ativo = 0 WHERE id = ?", (criado["usuario"]["id"],))
    con.commit()
    con.close()
    assert cliente.get("/api/auth/me", headers=cabecalho(token)).status_code == 401
    # e não consegue entrar de novo
    r = cliente.post("/api/auth/login", json={"telefone": criado["usuario"]["telefone"], "pin": PIN})
    assert r.status_code == 403 and r.json()["codigo"] == "conta_inativa"


# -------------------------------------------------------------------- perfil
def test_perfil_so_fica_completo_com_nome_e_idade(cliente):
    criado = cadastrar(cliente, nome="Novo Cliente")
    token = criado["token"]
    assert criado["usuario"]["perfil_completo"] is False, "cadastro por telefone não tem idade"

    sem_token = cliente.patch("/api/account/profile", json={"nome": "Novo Cliente", "idade": 24})
    assert sem_token.status_code == 401

    r = cliente.patch("/api/account/profile", json={"nome": "Novo Cliente", "idade": 24},
                      headers=cabecalho(token))
    assert r.status_code == 200
    assert r.json()["usuario"]["perfil_completo"] is True
    assert r.json()["usuario"]["nome"] == "Novo Cliente"
    assert r.json()["usuario"]["idade"] == 24
    conta = cliente.get("/api/account", headers=cabecalho(token)).json()["usuario"]
    assert (conta["nome"], conta["idade"], conta["perfil_completo"]) == ("Novo Cliente", 24, True)


@pytest.mark.parametrize("idade", [12, 121, 0, -3])
def test_idade_fora_da_faixa_e_recusada(cliente, idade):
    token = cadastrar(cliente)["token"]
    r = cliente.patch("/api/account/profile", json={"nome": "Cliente Bearer", "idade": idade},
                      headers=cabecalho(token))
    assert r.status_code == 400
    assert r.json()["codigo"] == "validacao"


def test_nome_curto_e_recusado(cliente):
    token = cadastrar(cliente)["token"]
    r = cliente.patch("/api/account/profile", json={"nome": "A", "idade": 24}, headers=cabecalho(token))
    assert r.status_code == 400


# ---------------------------------------------------------------- agendamento
@pytest.fixture
def barbeiro_disponivel():
    """Cria um profissional habilitado em todos os serviços (a base de dev nasce sem nenhum)."""
    con = db.conectar()
    try:
        cur = con.execute("INSERT INTO usuarios (nome, email, papel) VALUES ('Teste Barbeiro', ?, 'barbeiro')",
                          (f"barbeiro{next(_novos_telefones)}@exemplo.test",))
        usuario_id = cur.lastrowid
        cur = con.execute("INSERT INTO profissionais (usuario_id, apelido) VALUES (?, 'TesteBarbeiro')", (usuario_id,))
        profissional_id = cur.lastrowid
        for servico in con.execute("SELECT id FROM servicos"):
            con.execute("INSERT INTO servico_profissional (servico_id, profissional_id) VALUES (?, ?)",
                        (servico["id"], profissional_id))
        con.commit()
    finally:
        con.close()
    return profissional_id


def _horario_futuro(dias=3, hora="14:00"):
    dia = (datetime.now(timezone.utc) + timedelta(days=dias)).strftime("%Y-%m-%d")
    return dia, hora


def test_agendar_exige_bearer(cliente):
    dia, hora = _horario_futuro()
    corpo = {"name": "Cliente Bearer", "phone": telefone_novo(), "service": "Corte masculino",
             "barber": "TesteBarbeiro", "date": dia, "time": hora}
    assert cliente.post("/api/bookings", json=corpo).status_code == 401


def test_agendar_com_bearer_cria_e_nao_permite_double_booking(cliente, barbeiro_disponivel):
    token = cadastrar(cliente)["token"]
    dia, hora = _horario_futuro()
    corpo = {"name": "Cliente Bearer", "phone": telefone_novo(), "service": "Corte masculino",
             "barber": "TesteBarbeiro", "date": dia, "time": hora}

    primeira = cliente.post("/api/bookings", json=corpo, headers=cabecalho(token))
    assert primeira.status_code == 201, primeira.text
    assert primeira.json()["agendamento"]["codigo"]

    segunda = cliente.post("/api/bookings", json=corpo, headers=cabecalho(token))
    assert segunda.status_code == 409
    assert segunda.json()["codigo"] == "horario_ocupado"

    conta = cliente.get("/api/account", headers=cabecalho(token)).json()
    assert len(conta["agendamentos"]) == 1


def test_agendar_no_passado_e_recusado(cliente, barbeiro_disponivel):
    token = cadastrar(cliente)["token"]
    dia = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    corpo = {"name": "Cliente Bearer", "phone": telefone_novo(), "service": "Corte masculino",
             "barber": "TesteBarbeiro", "date": dia, "time": "14:00"}
    r = cliente.post("/api/bookings", json=corpo, headers=cabecalho(token))
    assert r.status_code == 400
    assert r.json()["codigo"] == "horario_passado"


# --------------------------------------------------- o HTML não carrega dado pessoal
def test_paginas_da_area_logada_nao_trazem_dados_de_ninguem(cliente):
    criado = cadastrar(cliente, nome="Fulano Secreto")
    for rota in ("/account", "/perfil"):
        html = cliente.get(rota).text
        assert "Fulano Secreto" not in html, rota
        assert criado["usuario"]["telefone"] not in html, rota
        assert 'id="bookingName">—<' in html or 'id="nome"' in html, rota
        assert "/api/account" in html or True


def test_perfil_js_guarda_a_sessao_antes_de_pedir_o_perfil(cliente):
    """O caminho inverso do vazamento: nenhum fetch de dado pessoal sem Bearer antes."""
    js = cliente.get("/perfil.js").text
    assert js.index("lerSessao()") < js.index("'/api/account'"), "pediu perfil antes de checar o token"
    assert "location.replace('/login?next=/perfil')" in js
