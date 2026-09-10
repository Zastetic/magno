"""F1 — login com Google (fluxo OAuth 2.0 authorization code).

Roda contra o provedor FALSO (`GOOGLE_FAKE=1`, ligado no conftest): o fluxo é o de
verdade — state de uso único, callback, criação/vinculação de conta, sessão — só a
conversa com o Google é substituída.
"""
import pytest
from fastapi.testclient import TestClient

from server import auth, google_auth
from server.main import app

IDENTIDADE = "google-teste-1--joao.teste@exemplo.test--João Teste"


@pytest.fixture
def cliente():
    with TestClient(app) as c:
        yield c


def comecar(cliente, destino=None):
    """Percorre /iniciar → /_fake e devolve o state do consentimento falso."""
    url = "/api/auth/google/iniciar" + (f"?destino={destino}" if destino else "")
    r = cliente.get(url, follow_redirects=False)
    assert r.status_code in (302, 307), r.text
    local = r.headers["location"]
    assert "_fake" in local and "state=" in local, local
    return local.split("state=")[1]


def autenticar(cliente, identidade=IDENTIDADE, destino=None):
    state = comecar(cliente, destino)
    r = cliente.get(f"/api/auth/google/callback?code={identidade}&state={state}",
                    follow_redirects=False)
    return r


# ------------------------------------------------------------------ fluxo feliz
def test_iniciar_manda_para_o_consentimento(cliente):
    state = comecar(cliente)
    assert len(state) > 20


def test_tela_falsa_lista_identidades(cliente):
    state = comecar(cliente)
    pagina = cliente.get(f"/api/auth/google/_fake?state={state}")
    assert pagina.status_code == 200
    assert "João Teste" in pagina.text and "maria.teste@exemplo.test" in pagina.text


def test_callback_cria_conta_e_devolve_sessao(cliente):
    r = autenticar(cliente)
    assert r.status_code in (302, 307), r.text
    local = r.headers["location"]
    assert local.startswith("/conta.html#entrar="), local
    token = local.split("#entrar=")[1]

    me = cliente.get("/api/auth/me", headers={"Authorization": "Bearer " + token})
    assert me.status_code == 200
    usuario = me.json()["usuario"]
    assert usuario["nome"] == "João Teste"
    assert usuario["email"] == "joao.teste@exemplo.test"
    assert usuario["tem_google"] is True
    assert usuario["tem_pin"] is False
    assert usuario["telefone"] is None
    assert usuario["precisa_telefone"] is True      # barbearia precisa do número


def test_login_repetido_nao_duplica_conta(cliente):
    r1 = autenticar(cliente)
    r2 = autenticar(cliente)
    t1 = r1.headers["location"].split("#entrar=")[1]
    t2 = r2.headers["location"].split("#entrar=")[1]
    u1 = cliente.get("/api/auth/me", headers={"Authorization": "Bearer " + t1}).json()["usuario"]
    u2 = cliente.get("/api/auth/me", headers={"Authorization": "Bearer " + t2}).json()["usuario"]
    assert u1["id"] == u2["id"]


def test_conta_google_completa_telefone(cliente):
    token = autenticar(cliente).headers["location"].split("#entrar=")[1]
    cabecalho = {"Authorization": "Bearer " + token}
    r = cliente.patch("/api/auth/telefone", json={"telefone": "13997630500"}, headers=cabecalho)
    assert r.status_code == 200
    assert r.json()["usuario"]["precisa_telefone"] is False
    assert r.json()["usuario"]["tem_google"] is True


def test_destino_do_login_e_respeitado(cliente):
    r = autenticar(cliente, destino="/painel.html")
    assert r.headers["location"].startswith("/painel.html#entrar=")


# ------------------------------------------------------------------ segurança
def test_state_de_uso_unico(cliente):
    state = comecar(cliente)
    primeira = cliente.get(f"/api/auth/google/callback?code={IDENTIDADE}&state={state}",
                           follow_redirects=False)
    assert "entrar=" in primeira.headers["location"]
    repetida = cliente.get(f"/api/auth/google/callback?code={IDENTIDADE}&state={state}",
                           follow_redirects=False)
    assert repetida.headers["location"] == "/entrar.html?erro=state_invalido"


def test_state_inventado_e_recusado(cliente):
    r = cliente.get(f"/api/auth/google/callback?code={IDENTIDADE}&state=inventado",
                    follow_redirects=False)
    assert r.headers["location"] == "/entrar.html?erro=state_invalido"


def test_cancelamento_no_google_volta_para_o_login(cliente):
    r = cliente.get("/api/auth/google/callback?error=access_denied&state=x", follow_redirects=False)
    assert r.headers["location"] == "/entrar.html?erro=google_cancelado"


def test_state_expirado_e_recusado(cliente):
    import sqlite3
    from server import db
    state = comecar(cliente)
    con = sqlite3.connect(db.DB_PATH)
    con.execute("UPDATE logins_pendentes SET expira_em = '2000-01-01T00:00:00Z' WHERE state = ?", (state,))
    con.commit()
    con.close()
    r = cliente.get(f"/api/auth/google/callback?code={IDENTIDADE}&state={state}",
                    follow_redirects=False)
    assert r.headers["location"] == "/entrar.html?erro=state_invalido"


# ------------------------------------------------------------------ vínculo
def test_google_vincula_conta_existente_pelo_email(cliente):
    """Quem já tem conta com e-mail igual não vira duas contas."""
    r = cliente.post("/api/auth/cadastro", json={
        "nome": "Maria Teste", "telefone": "13997630501", "pin": "9471",
        "email": "maria.teste@exemplo.test", "consentimento_lgpd": True,
    })
    assert r.status_code == 200
    id_telefone = r.json()["usuario"]["id"]

    token = autenticar(cliente, "google-teste-2--maria.teste@exemplo.test--Maria Teste"
                       ).headers["location"].split("#entrar=")[1]
    usuario = cliente.get("/api/auth/me", headers={"Authorization": "Bearer " + token}).json()["usuario"]

    assert usuario["id"] == id_telefone
    assert usuario["tem_google"] is True
    assert usuario["tem_pin"] is True          # continua entrando com PIN também
    assert usuario["telefone_formatado"] == "(13) 99763-0501"


def test_email_nao_pode_estar_em_duas_contas(cliente):
    cliente.post("/api/auth/cadastro", json={
        "nome": "Um", "telefone": "13997630502", "pin": "9471",
        "email": "repetido@exemplo.test", "consentimento_lgpd": True})
    cliente.post("/api/auth/cadastro", json={
        "nome": "Dois", "telefone": "13997630503", "pin": "9471",
        "email": "REPETIDO@exemplo.test", "consentimento_lgpd": True})
    import sqlite3
    from server import db
    con = sqlite3.connect(db.DB_PATH)
    n = con.execute("SELECT COUNT(*) FROM usuarios WHERE lower(email) = 'repetido@exemplo.test'").fetchone()[0]
    con.close()
    assert n == 1, "o e-mail não pode se repetir ignorando maiúsculas"


# ------------------------------------------------------------------ desligado
def test_sem_credencial_o_google_fica_desligado(cliente, monkeypatch):
    monkeypatch.setenv("GOOGLE_FAKE", "")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "")
    assert google_auth.configurado() is False

    r = cliente.get("/api/auth/google/iniciar", follow_redirects=False)
    assert r.status_code == 503
    assert r.json()["codigo"] == "google_desligado"

    fake = cliente.get("/api/auth/google/_fake?state=x")
    assert fake.status_code == 404


def test_url_do_google_real(cliente, monkeypatch):
    """Com credenciais, a URL aponta para o Google de verdade e leva o state."""
    monkeypatch.setenv("GOOGLE_FAKE", "")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cliente-de-teste")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "segredo-de-teste")
    url = google_auth.url_autorizacao("state-abc", "https://magnum.autoava.us/api/auth/google/callback")
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=cliente-de-teste" in url
    assert "state=state-abc" in url
    assert "scope=openid" in url.replace("%20", "+")
    assert "segredo-de-teste" not in url          # o segredo nunca sai do servidor
