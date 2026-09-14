"""F0 — critérios de aceite do esqueleto, como teste repetível.

Rodar: ./venv/bin/pytest tests/ -v
"""
from fastapi.testclient import TestClient

from server import db
from server.main import app


def test_schema_aplica_e_e_idempotente():
    """Subir o servidor N vezes não pode recriar tabela nem duplicar seed."""
    db.inicializar()
    primeira = db.resumo()["contagens"]
    db.inicializar()
    db.inicializar()
    segunda = db.resumo()["contagens"]

    assert primeira == segunda
    assert segunda["configuracoes"] == 12, "seed de configurações duplicou"
    assert segunda["horarios"] == 7, "seed de horários duplicou"
    assert segunda["servicos"] == 4, "seed de serviços duplicou"


def test_banco_tem_as_tabelas_e_os_indices():
    resumo = db.resumo()
    assert resumo["tabelas"] == 13          # 12 de domínio + logins_pendentes (state do OAuth)
    assert resumo["indices"] == 11
    assert resumo["integridade"] == "ok"


def test_banco_fica_no_ext4_e_nao_em_mnt_d():
    """Decisão D21: SQLite em DrvFs/9p é ~238x mais lento — o .db nunca mora no D:."""
    assert not str(db.DB_PATH).startswith("/mnt/"), f"banco em partição lenta: {db.DB_PATH}"


def test_saude_responde_e_mostra_as_regras():
    with TestClient(app) as cliente:
        r = cliente.get("/api/saude")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["ok"] is True
    assert corpo["banco"]["integridade"] == "ok"
    assert corpo["regras"] == {
        "slot_min": "30",
        "buffer_min": "5",
        "antecedencia_min_h": "1",
        "janela_dias": "60",
        "cancelamento_limite_h": "2",
        "fuso": "America/Sao_Paulo",
    }


def test_cabecalhos_de_seguranca_presentes():
    with TestClient(app) as cliente:
        r = cliente.get("/api/saude")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp, "CSP sem script-src 'self' abre a porta para XSS"
    assert "unsafe-inline" not in csp.split("style-src")[0].split("script-src")[1], \
        "script-src não pode conter unsafe-inline"


def test_corpo_grande_e_recusado_com_413():
    with TestClient(app) as cliente:
        r = cliente.post("/api/saude", content=b"x" * 1_000_001)
    assert r.status_code == 413
    assert r.json()["codigo"] == "corpo_grande"


def test_spa_servida_na_mesma_origem():
    with TestClient(app) as cliente:
        for caminho, tipo in (
            ("/", "text/html"),
            ("/index-b.html", "text/html"),
            ("/status.html", "text/html"),
            ("/app.js", "javascript"),
            ("/status.js", "javascript"),
            ("/styles.css", "text/css"),
        ):
            r = cliente.get(caminho)
            assert r.status_code == 200, caminho
            assert tipo in r.headers["content-type"], (caminho, r.headers["content-type"])


def test_home_tem_o_conteudo_da_loja():
    """A home é institucional: marca, serviços/preços e chamada para login."""
    with TestClient(app) as cliente:
        html = cliente.get("/").text
    for esperado in ("Barbearia Magnum", "Magnum", "Corte masculino", "R$ 45",
                     "Barba na navalha", "Degradê navalhado", "Seu horário começa aqui.", 'href="/login"'):
        assert esperado in html, f"faltando na home: {esperado}"
    assert "iframe" not in html.lower()
    # script inline é bloqueado pela CSP (script-src 'self') — a home não pode ter nenhum
    assert "<script>" not in html, "home com <script> inline seria bloqueada pela CSP"


def test_area_da_conta_nao_tem_usuario_fixo_e_permite_troca():
    """A agenda é do usuário do Bearer: nome, idade e telefone nunca vêm do HTML."""
    with TestClient(app) as cliente:
        html = cliente.get("/account").text
        auth_js = cliente.get("/auth.js").text
        account_js = cliente.get("/conta.js").text
    assert "Matheus Oliveira" not in html
    assert 'id="switchAccount"' in html
    assert 'id="bookingName">—<' in html, "o nome na agenda tem que vir do perfil, não do HTML"
    assert "profileForm" not in html, "as perguntas de perfil saíram daqui: agora são a página /perfil"
    assert "A tela de login continua disponível mesmo com uma sessão aberta." in auth_js
    assert "!auth || !auth.lerSessao()" in account_js, "sem Bearer a agenda não pode mostrar nada"
    assert "!result.usuario.perfil_completo" in account_js, "perfil incompleto precisa cair em /perfil"


def test_pagina_de_perfil_pergunta_nome_e_depois_idade():
    """/perfil é o primeiro acesso: passo 1 nome, passo 2 idade, e segue para os agendamentos."""
    with TestClient(app) as cliente:
        r = cliente.get("/perfil")
        pagina = r.text
        js = cliente.get("/perfil.js").text
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    assert "Como você quer ser chamado?" in pagina
    assert 'id="formNome"' in pagina and 'id="formIdade" hidden' in pagina, "a idade só aparece depois do nome"
    assert 'for="nome"' in pagina and 'for="idade"' in pagina
    assert "/api/account/profile" in js          # salva os dois de uma vez
    assert "location.replace('/account')" in js  # e prossegue para os agendamentos
    assert "lerSessao()" in js                   # nada de HTML com dado pessoal
