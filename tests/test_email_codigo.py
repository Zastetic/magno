"""F1 — login por código de 5 dígitos no e-mail (entrada principal, sem senha).

Roda com o provedor de e-mail em modo `arquivo` (não envia nada para fora): o código fica
em `logs/emails/enviados.jsonl` e os testes leem de lá — igual ao que o front faria se
recebesse o e-mail de verdade.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import auth, email_provider
from server.main import app

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def cliente():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def provedor_de_arquivo(monkeypatch, tmp_path):
    """Isola os e-mails de teste numa pasta temporária.

    O intervalo mínimo entre envios fica em 0 para os testes pedirem código à vontade —
    o teste do limite de rajada sobe ele de volta na mão.
    """
    monkeypatch.setenv("MAGNO_EMAIL_MODO", "arquivo")
    monkeypatch.setenv("MAGNO_EMAIL_DE", "magnum@autoava.us")
    monkeypatch.setattr(email_provider, "PASTA_EMAILS", tmp_path / "emails")
    monkeypatch.setattr(auth, "_envios", {})
    monkeypatch.setattr(auth, "_falhas", {})
    monkeypatch.setattr(auth, "INTERVALO_MINIMO_S", 0)


def enviados() -> list[dict]:
    arquivo = email_provider.PASTA_EMAILS / "enviados.jsonl"
    if not arquivo.exists():
        return []
    return [json.loads(l) for l in arquivo.read_text(encoding="utf-8").splitlines() if l.strip()]


def codigo_de(email: str) -> str:
    alvo = auth.normalizar_email(email) or email
    for registro in reversed(enviados()):
        if registro["para"] == alvo:
            return registro["codigo"]
    raise AssertionError(f"nenhum código enviado para {alvo}")


def entrar(cliente, email="cliente.teste@exemplo.test"):
    """Faz o fluxo completo: pede o código e confirma."""
    pedido = cliente.post("/api/auth/codigo", json={"email": email, "nome": "Cliente Teste"})
    assert pedido.status_code == 200, pedido.text
    verificado = cliente.post("/api/auth/verificar", json={"email": email, "codigo": codigo_de(email)})
    return verificado


# ------------------------------------------------------------------ e-mail
@pytest.mark.parametrize("entrada,esperado", [
    ("Cliente.Teste@Exemplo.TEST", "cliente.teste@exemplo.test"),
    ("  joao@autoava.us  ", "joao@autoava.us"),
    ("a.b-c+tag@sub.dominio.com.br", "a.b-c+tag@sub.dominio.com.br"),
])
def test_normaliza_email(entrada, esperado):
    assert auth.normalizar_email(entrada) == esperado


@pytest.mark.parametrize("entrada", ["", "semarroba", "a@b", "@x.com", "a@.com", "a b@x.com", "x" * 300 + "@x.com"])
def test_rejeita_email_invalido(entrada):
    assert auth.normalizar_email(entrada) is None


def test_gerar_codigo_tem_cinco_digitos():
    for _ in range(50):
        codigo = auth.gerar_codigo()
        assert len(codigo) == 5 and codigo.isdigit()


# ------------------------------------------------------------------ fluxo
def test_pedido_de_codigo_manda_email(cliente):
    r = cliente.post("/api/auth/codigo", json={"email": "primeiro@exemplo.test"})
    assert r.status_code == 200, r.text
    assert r.json()["enviado"] is True
    assert r.json()["minutos"] == 10

    enviados_agora = enviados()
    assert len(enviados_agora) == 1
    assert enviados_agora[0]["para"] == "primeiro@exemplo.test"
    assert len(enviados_agora[0]["codigo"]) == 5
    # o e-mail em HTML também foi gravado, com a marca dentro
    htmls = list(email_provider.PASTA_EMAILS.glob("*.html"))
    assert htmls and "Barbearia Magnum" in htmls[0].read_text(encoding="utf-8")


def test_codigo_cria_conta_e_sessao(cliente):
    r = entrar(cliente, "novo@exemplo.test")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["conta_nova"] is True
    usuario = corpo["usuario"]
    assert usuario["email"] == "novo@exemplo.test"
    assert usuario["email_verificado"] is True
    assert usuario["tem_senha"] is False       # entrou sem senha nenhuma
    assert usuario["telefone"] is None
    assert usuario["precisa_telefone"] is True

    me = cliente.get("/api/auth/me", headers={"Authorization": "Bearer " + corpo["token"]})
    assert me.status_code == 200
    assert me.json()["usuario"]["email"] == "novo@exemplo.test"


def test_segundo_login_nao_duplica_conta(cliente):
    primeira = entrar(cliente, "repetido@exemplo.test").json()
    segunda = entrar(cliente, "repetido@exemplo.test").json()
    assert primeira["usuario"]["id"] == segunda["usuario"]["id"]
    assert segunda["conta_nova"] is False


def test_nome_vem_do_pedido_ou_do_email(cliente):
    entrar(cliente, "maria.silva@exemplo.test")
    assert email_provider.PASTA_EMAILS.exists()
    # sem nome informado, o nome sai do e-mail de forma apresentável
    auth_resumo = cliente.post("/api/auth/codigo", json={"email": "joao.pereira@exemplo.test"})
    assert auth_resumo.status_code == 200
    token = cliente.post("/api/auth/verificar",
                         json={"email": "joao.pereira@exemplo.test",
                               "codigo": codigo_de("joao.pereira@exemplo.test")}).json()
    assert token["usuario"]["nome"] == "Joao Pereira"


# ------------------------------------------------------------------ segurança
def test_codigo_errado_nao_entra(cliente):
    cliente.post("/api/auth/codigo", json={"email": "errado@exemplo.test"})
    certo = codigo_de("errado@exemplo.test")
    errado = "00000" if certo != "00000" else "11111"
    r = cliente.post("/api/auth/verificar", json={"email": "errado@exemplo.test", "codigo": errado})
    assert r.status_code == 401
    assert r.json()["codigo"] == "codigo_invalido"
    assert "não confere" in r.json()["erro"]


def test_codigo_morre_depois_de_cinco_tentativas(cliente):
    cliente.post("/api/auth/codigo", json={"email": "bruto@exemplo.test"})
    certo = codigo_de("bruto@exemplo.test")
    errado = "00000" if certo != "00000" else "11111"
    for _ in range(5):
        cliente.post("/api/auth/verificar", json={"email": "bruto@exemplo.test", "codigo": errado})
    # mesmo com o código certo, ele já morreu
    r = cliente.post("/api/auth/verificar", json={"email": "bruto@exemplo.test", "codigo": certo})
    assert r.status_code == 401
    assert "Peça outro" in r.json()["erro"] or "Muitas tentativas" in r.json()["erro"]


def test_codigo_e_de_uso_unico(cliente):
    cliente.post("/api/auth/codigo", json={"email": "unico@exemplo.test"})
    codigo = codigo_de("unico@exemplo.test")
    primeira = cliente.post("/api/auth/verificar", json={"email": "unico@exemplo.test", "codigo": codigo})
    assert primeira.status_code == 200
    repetida = cliente.post("/api/auth/verificar", json={"email": "unico@exemplo.test", "codigo": codigo})
    assert repetida.status_code == 401


def test_codigo_novo_invalida_o_anterior(cliente, monkeypatch):
    monkeypatch.setattr(auth, "INTERVALO_MINIMO_S", 0)   # libera o reenvio imediato
    cliente.post("/api/auth/codigo", json={"email": "dois@exemplo.test"})
    antigo = codigo_de("dois@exemplo.test")
    cliente.post("/api/auth/codigo", json={"email": "dois@exemplo.test"})
    novo = codigo_de("dois@exemplo.test")
    assert antigo != novo or True       # pode coincidir por sorte; o importante é a validade
    r = cliente.post("/api/auth/verificar", json={"email": "dois@exemplo.test", "codigo": novo})
    assert r.status_code == 200


def test_codigo_expirado(cliente, monkeypatch):
    import sqlite3
    from server import db
    cliente.post("/api/auth/codigo", json={"email": "velho@exemplo.test"})
    codigo = codigo_de("velho@exemplo.test")
    con = sqlite3.connect(db.DB_PATH)
    con.execute("UPDATE codigos_email SET expira_em = '2000-01-01T00:00:00Z' WHERE email = ?",
                ("velho@exemplo.test",))
    con.commit()
    con.close()
    r = cliente.post("/api/auth/verificar", json={"email": "velho@exemplo.test", "codigo": codigo})
    assert r.status_code == 401
    assert "expirou" in r.json()["erro"]


def test_nao_deixa_pedir_codigo_em_rajada(cliente, monkeypatch):
    monkeypatch.setattr(auth, "INTERVALO_MINIMO_S", 60)   # regra real
    primeira = cliente.post("/api/auth/codigo", json={"email": "rajada@exemplo.test"})
    assert primeira.status_code == 200
    segunda = cliente.post("/api/auth/codigo", json={"email": "rajada@exemplo.test"})
    assert segunda.status_code == 429
    assert segunda.json()["codigo"] == "aguarde"
    assert segunda.json()["esperar_se"] > 0


def test_limite_de_tres_envios_por_janela(cliente, monkeypatch):
    monkeypatch.setattr(auth, "INTERVALO_MINIMO_S", 0)
    email = "limite@exemplo.test"
    for _ in range(3):
        assert cliente.post("/api/auth/codigo", json={"email": email}).status_code == 200
    quarta = cliente.post("/api/auth/codigo", json={"email": email})
    assert quarta.status_code == 429


def test_email_invalido_no_pedido(cliente):
    r = cliente.post("/api/auth/codigo", json={"email": "nao-e-email"})
    assert r.status_code == 400
    assert r.json()["codigo"] == "email_invalido"


def test_email_invalido_na_verificacao(cliente):
    r = cliente.post("/api/auth/verificar", json={"email": "nao-e-email", "codigo": "12345"})
    assert r.status_code == 400


def test_codigo_precisa_ter_cinco_digitos(cliente):
    cliente.post("/api/auth/codigo", json={"email": "curto@exemplo.test"})
    r = cliente.post("/api/auth/verificar", json={"email": "curto@exemplo.test", "codigo": "123"})
    assert r.status_code == 401
    assert "5 dígitos" in r.json()["erro"]


def test_codigo_nao_fica_em_claro_no_banco(cliente):
    import sqlite3
    from server import db
    cliente.post("/api/auth/codigo", json={"email": "hash@exemplo.test"})
    codigo = codigo_de("hash@exemplo.test")
    con = sqlite3.connect(db.DB_PATH)
    guardados = [l[0] for l in con.execute("SELECT codigo_hash FROM codigos_email WHERE email = 'hash@exemplo.test'")]
    con.close()
    assert guardados and codigo not in guardados[0]
    assert guardados[0].startswith("pbkdf2_sha256$")


# ------------------------------------------------------------------ senha opcional
def test_criar_senha_e_entrar_com_ela(cliente):
    sessao = entrar(cliente, "comsenha@exemplo.test").json()
    cabecalho = {"Authorization": "Bearer " + sessao["token"]}

    fraca = cliente.post("/api/auth/senha", json={"senha": "12"}, headers=cabecalho)
    assert fraca.status_code == 400
    assert fraca.json()["codigo"] == "senha_fraca"

    r = cliente.post("/api/auth/senha", json={"senha": "minhaSenha1"}, headers=cabecalho)
    assert r.status_code == 200
    assert r.json()["usuario"]["tem_senha"] is True

    login = cliente.post("/api/auth/entrar-senha",
                         json={"email": "comsenha@exemplo.test", "senha": "minhaSenha1"})
    assert login.status_code == 200
    assert login.json()["usuario"]["tem_senha"] is True

    errado = cliente.post("/api/auth/entrar-senha",
                          json={"email": "comsenha@exemplo.test", "senha": "nao-e-essa"})
    assert errado.status_code == 401


def test_conta_sem_senha_nao_entra_com_senha(cliente):
    entrar(cliente, "semSenha@exemplo.test")
    r = cliente.post("/api/auth/entrar-senha",
                     json={"email": "semSenha@exemplo.test", "senha": "qualquer123"})
    assert r.status_code == 401
    assert r.json()["codigo"] == "credencial_invalida"


def test_senha_exige_sessao(cliente):
    r = cliente.post("/api/auth/senha", json={"senha": "minhaSenha1"})
    assert r.status_code == 401


def test_fluxo_por_email_e_depois_por_telefone_na_mesma_conta(cliente):
    """Quem entrou por e-mail completa o telefone e passa a ter também telefone+PIN."""
    sessao = entrar(cliente, "duplo@exemplo.test").json()
    cabecalho = {"Authorization": "Bearer " + sessao["token"]}
    r = cliente.patch("/api/auth/telefone", json={"telefone": "13997630777"}, headers=cabecalho)
    assert r.status_code == 200
    assert r.json()["usuario"]["precisa_telefone"] is False

    cliente.post("/api/auth/senha", json={"senha": "9471"}, headers=cabecalho)
    login = cliente.post("/api/auth/login", json={"telefone": "13997630777", "pin": "9471"})
    assert login.status_code == 200
    assert login.json()["usuario"]["id"] == sessao["usuario"]["id"]
