"""F1 — login por telefone + PIN, sessão opaca, lockout e papéis."""
import pytest
from fastapi.testclient import TestClient

from server import auth
from server.main import app


@pytest.fixture
def cliente():
    with TestClient(app) as c:
        yield c


def criar(cliente, telefone="13997630784", pin="9471", nome="João da Silva", consentimento=True):
    return cliente.post("/api/auth/cadastro", json={
        "nome": nome, "telefone": telefone, "pin": pin,
        "consentimento_lgpd": consentimento,
    })


# ------------------------------------------------------------------ telefone
@pytest.mark.parametrize("entrada,esperado", [
    ("13997630784", "5513997630784"),
    ("(13) 99763-0784", "5513997630784"),
    ("+55 13 99763-0784", "5513997630784"),
    ("5513997630784", "5513997630784"),
    ("1333224455", "551333224455"),        # fixo
])
def test_normaliza_telefone(entrada, esperado):
    assert auth.normalizar_telefone(entrada) == esperado


@pytest.mark.parametrize("entrada", ["", "abc", "123", "1399763078", "00999999999", "5513999999999", "5513997630"])
def test_rejeita_telefone_invalido(entrada):
    assert auth.normalizar_telefone(entrada) is None


def test_formata_telefone():
    assert auth.telefone_formatado("5513997630784") == "(13) 99763-0784"
    assert auth.telefone_formatado("551333224455") == "(13) 3322-4455"


# ------------------------------------------------------------------ PIN
@pytest.mark.parametrize("pin,ok", [("9471", True), ("482913", True),
                                    ("1234", False), ("0000", False), ("4321", False),
                                    ("12345", False), ("12", False), ("abcd", False)])
def test_valida_pin(pin, ok):
    assert auth.validar_pin(pin)[0] is ok


def test_pin_nao_pode_ser_pedaco_do_telefone():
    assert auth.validar_pin("3078", "5513997630784")[0] is False


def test_hash_de_pin_nao_guarda_o_pin():
    guardado = auth.hash_pin("9471")
    assert "9471" not in guardado
    assert guardado.startswith("pbkdf2_sha256$")
    assert auth.conferir_pin("9471", guardado) is True
    assert auth.conferir_pin("9472", guardado) is False
    assert auth.conferir_pin("9471", None) is False
    assert auth.conferir_pin("9471", "lixo") is False


def test_dois_hashes_do_mesmo_pin_sao_diferentes():
    assert auth.hash_pin("9471") != auth.hash_pin("9471")   # sal aleatório


# ------------------------------------------------------------------ cadastro
def test_cadastro_cria_conta_e_sessao(cliente):
    r = criar(cliente)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["usuario"]["nome"] == "João da Silva"
    assert corpo["usuario"]["telefone_formatado"] == "(13) 99763-0784"
    assert corpo["usuario"]["papel"] == "cliente"
    assert corpo["usuario"]["tem_senha"] is True
    assert corpo["usuario"]["tem_google"] is False
    assert "senha_hash" not in corpo["usuario"]
    assert len(corpo["token"]) > 30

    me = cliente.get("/api/auth/me", headers={"Authorization": "Bearer " + corpo["token"]})
    assert me.status_code == 200
    assert me.json()["usuario"]["telefone"] == "5513997630784"


def test_cadastro_exige_consentimento(cliente):
    r = criar(cliente, consentimento=False)
    assert r.status_code == 400
    assert r.json()["codigo"] == "sem_consentimento"


def test_cadastro_recusa_telefone_invalido(cliente):
    r = criar(cliente, telefone="123")
    assert r.status_code == 400
    assert r.json()["codigo"] == "telefone_invalido"


def test_cadastro_recusa_pin_fraco(cliente):
    r = criar(cliente, telefone="13997630001", pin="1234")
    assert r.status_code == 400
    assert r.json()["codigo"] == "pin_fraco"
    assert "sequência" in r.json()["erro"]


def test_cadastro_recusa_telefone_repetido(cliente):
    criar(cliente, telefone="13997630002")
    r = criar(cliente, telefone="(13) 99763-0002")
    assert r.status_code == 409
    assert r.json()["codigo"] == "ja_existe"


# ------------------------------------------------------------------ login
def test_login_com_pin_certo(cliente):
    criar(cliente, telefone="13997630003", pin="9471")
    r = cliente.post("/api/auth/login", json={"telefone": "(13) 99763-0003", "pin": "9471"})
    assert r.status_code == 200
    assert r.json()["usuario"]["telefone"] == "5513997630003"


def test_login_nao_diz_se_o_telefone_existe(cliente):
    criar(cliente, telefone="13997630004", pin="9471")
    errado = cliente.post("/api/auth/login", json={"telefone": "13997630004", "pin": "9472"})
    inexistente = cliente.post("/api/auth/login", json={"telefone": "13990000009", "pin": "9472"})
    assert errado.status_code == inexistente.status_code == 401
    assert errado.json()["erro"] == inexistente.json()["erro"]
    assert errado.json()["codigo"] == "credencial_invalida"


def test_lockout_apos_cinco_falhas(cliente):
    criar(cliente, telefone="13997630005", pin="9471")
    for _ in range(5):
        cliente.post("/api/auth/login", json={"telefone": "13997630005", "pin": "0001"})
    bloqueado = cliente.post("/api/auth/login", json={"telefone": "13997630005", "pin": "9471"})
    assert bloqueado.status_code == 429
    assert bloqueado.json()["codigo"] == "lockout"
    assert bloqueado.json()["esperar_seg"] > 0


def test_lockout_libera_com_sucesso(cliente):
    criar(cliente, telefone="13997630006", pin="9471")
    cliente.post("/api/auth/login", json={"telefone": "13997630006", "pin": "0001"})
    assert cliente.post("/api/auth/login", json={"telefone": "13997630006", "pin": "9471"}).status_code == 200


# ------------------------------------------------------------------ sessão
def test_me_sem_token(cliente):
    r = cliente.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["codigo"] == "sessao_invalida"


def test_me_com_token_inventado(cliente):
    r = cliente.get("/api/auth/me", headers={"Authorization": "Bearer nada-a-ver"})
    assert r.status_code == 401


def test_logout_revoga_de_verdade(cliente):
    token = criar(cliente, telefone="13997630007").json()["token"]
    cabecalho = {"Authorization": "Bearer " + token}
    assert cliente.get("/api/auth/me", headers=cabecalho).status_code == 200
    assert cliente.post("/api/auth/logout", headers=cabecalho).status_code == 200
    assert cliente.get("/api/auth/me", headers=cabecalho).status_code == 401


def test_token_expirado(cliente, monkeypatch):
    token = criar(cliente, telefone="13997630008").json()["token"]
    monkeypatch.setattr(auth, "TTL_MIN", 0)
    novo = auth.criar_sessao(1)
    r = cliente.get("/api/auth/me", headers={"Authorization": "Bearer " + novo})
    assert r.status_code == 401
    assert cliente.get("/api/auth/me", headers={"Authorization": "Bearer " + token}).status_code == 200


def test_senha_do_banco_nao_e_o_pin(cliente):
    """Nada de PIN em claro no banco."""
    import sqlite3
    from server import db
    criar(cliente, telefone="13997630009", pin="9471")
    con = sqlite3.connect(db.DB_PATH)
    guardado = con.execute("SELECT senha_hash FROM usuarios WHERE telefone = '5513997630009'").fetchone()[0]
    con.close()
    assert guardado and guardado != "9471"
    assert guardado.startswith("pbkdf2_sha256$")


# ------------------------------------------------------- telefone em falta (Google)
def test_completar_telefone(cliente):
    token = criar(cliente, telefone="13997630010").json()["token"]
    cabecalho = {"Authorization": "Bearer " + token}
    r = cliente.patch("/api/auth/telefone", json={"telefone": "13997630011"}, headers=cabecalho)
    assert r.status_code == 200
    assert r.json()["usuario"]["telefone"] == "5513997630011"

    invalido = cliente.patch("/api/auth/telefone", json={"telefone": "123"}, headers=cabecalho)
    assert invalido.status_code == 400


def test_completar_telefone_nao_rouba_numero_de_outro(cliente):
    criar(cliente, telefone="13997630012")
    token = criar(cliente, telefone="13997630013").json()["token"]
    r = cliente.patch("/api/auth/telefone", json={"telefone": "13997630012"},
                      headers={"Authorization": "Bearer " + token})
    assert r.status_code == 409
    assert r.json()["codigo"] == "telefone_em_uso"


# ------------------------------------------------------------------ papéis
def test_rota_de_admin_exige_papel(cliente):
    """O guarda de papel recusa cliente antes de qualquer regra de negócio."""
    from fastapi import HTTPException

    token = criar(cliente, telefone="13997630014").json()["token"]
    usuario = auth.usuario_por_token(token)
    assert usuario is not None
    assert usuario["papel"] == "cliente"

    guarda = auth.exigir_papel("admin")
    with pytest.raises(HTTPException) as erro:
        guarda(usuario)
    assert erro.value.status_code == 403
    assert erro.value.detail["codigo"] == "sem_permissao"

    # e o mesmo guarda deixa passar quem tem o papel
    usuario["papel"] = "admin"
    assert guarda(usuario)["id"] == usuario["id"]
