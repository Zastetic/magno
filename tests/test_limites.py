"""F6 — freio por IP (server/limites.py) e o CAPTCHA do Cloudflare (server/turnstile.py).

O limitador é global no processo, então cada teste força a regra que quer medir
(`monkeypatch.setitem`/`limpar`) e o `conftest` zera os contadores entre testes.
"""
import json

import pytest
from fastapi.testclient import TestClient

from server import db, limites, turnstile
from server.main import app


# --------------------------------------------------------------------- limites
def test_janela_deslizante_libera_ate_o_teto_e_depois_freia(monkeypatch):
    monkeypatch.setattr(limites, "REGRAS", (("POST", "/api/teste", 3, 60),))
    limites.limpar()
    resultados = [limites.permitir("POST", "/api/teste", "1.2.3.4") for _ in range(4)]
    assert [liberado for liberado, _ in resultados[:3]] == [True, True, True]
    liberado, esperar = resultados[3]
    assert liberado is False and esperar >= 1, "a 4a requisição tinha que ser freada"


def test_janela_expira_e_libera_de_novo(monkeypatch):
    monkeypatch.setattr(limites, "REGRAS", (("POST", "/api/teste2", 1, 1),))
    limites.limpar()
    assert limites.permitir("POST", "/api/teste2", "9.9.9.9")[0] is True
    assert limites.permitir("POST", "/api/teste2", "9.9.9.9")[0] is False
    relogio = limites.time.monotonic                          # guarda o original: sem isso a
    with monkeypatch.context() as m:                          # lambda chama a si mesma
        m.setattr(limites.time, "monotonic", lambda: relogio() + 2)
        assert limites.permitir("POST", "/api/teste2", "9.9.9.9")[0] is True


def test_ip_do_cliente_prefere_cabecalho_do_cloudflare(monkeypatch):
    monkeypatch.setenv("MAGNO_ATRAS_DE_PROXY", "1")

    class Falsa:
        headers = {"cf-connecting-ip": "203.0.113.7", "x-forwarded-for": "198.51.100.1, 10.0.0.1"}
        client = type("C", (), {"host": "127.0.0.1"})()

    assert limites.ip_do_cliente(Falsa()) == "203.0.113.7"

    monkeypatch.setenv("MAGNO_ATRAS_DE_PROXY", "0")
    assert limites.ip_do_cliente(Falsa()) == "127.0.0.1"


def test_api_freia_com_429_e_retry_after(monkeypatch):
    """O teto geral (PADRAO) responde 429 com Retry-After e deixa rastro na auditoria.

    Uso /api/saude de propósito: os endpoints de auth têm freio próprio (cooldown de 60 s
    para pedir outro código), e aqui eu quero medir só o middleware.
    """
    monkeypatch.setattr(limites, "REGRAS", ())
    monkeypatch.setattr(limites, "PADRAO", (3, 60))
    limites.limpar()
    with TestClient(app) as cliente:      # o contexto roda o lifespan e cria as tabelas
        codigos = [cliente.get("/api/saude").status_code for _ in range(5)]
        assert codigos[:3] == [200, 200, 200], codigos
        assert codigos[3] == 429 and codigos[4] == 429

        resposta = cliente.get("/api/saude")
        assert resposta.status_code == 429
        assert resposta.json()["codigo"] == "limite"
        assert int(resposta.headers["retry-after"]) >= 1
        assert "Muitas requisições" in resposta.json()["erro"]

    # o bloqueio precisa ficar na auditoria (é o que permite enxergar abuso depois)
    con = db.conectar()
    try:
        tipos = [linha["tipo"] for linha in con.execute(
            "SELECT tipo FROM eventos ORDER BY id DESC LIMIT 20")]
    finally:
        con.close()
    assert "limite_estourado" in tipos


def test_saude_mostra_as_protecoes():
    with TestClient(app) as cliente:
        dados = cliente.get("/api/saude").json()
        assert dados["protecoes"]["limites"]["regras"], "as regras precisam aparecer no health-check"
        assert dados["protecoes"]["captcha"]["modo"] in ("off", "log", "on")


# --------------------------------------------------------------------- turnstile
def test_sem_chave_o_site_funciona_igual(monkeypatch):
    monkeypatch.delenv("MAGNO_TURNSTILE_SITE", raising=False)
    monkeypatch.delenv("MAGNO_TURNSTILE_SECRET", raising=False)
    monkeypatch.delenv("MAGNO_TURNSTILE_MODO", raising=False)
    assert turnstile.modo() == "off"
    assert turnstile.ativo() is False

    class Falsa:
        headers = {}
        client = type("C", (), {"host": "127.0.0.1"})()

    turnstile.exigir(Falsa(), None)          # não levanta: modo off não bloqueia ninguém


def test_modo_on_bloqueia_sem_token_valido(monkeypatch):
    monkeypatch.setenv("MAGNO_TURNSTILE_SITE", "0xSITE")
    monkeypatch.setenv("MAGNO_TURNSTILE_SECRET", "0xSEGREDO")
    monkeypatch.setenv("MAGNO_TURNSTILE_MODO", "on")
    monkeypatch.setattr(turnstile, "verificar", lambda token, ip: (False, "invalid-input-response"))

    class Falsa:
        headers = {"cf-connecting-ip": "203.0.113.9"}
        client = type("C", (), {"host": "127.0.0.1"})()

    with pytest.raises(Exception) as erro:
        turnstile.exigir(Falsa(), "token-ruim")
    assert "robô" in str(erro.value)


def test_modo_log_nunca_bloqueia(monkeypatch):
    monkeypatch.setenv("MAGNO_TURNSTILE_SECRET", "0xSEGREDO")
    monkeypatch.setenv("MAGNO_TURNSTILE_MODO", "log")
    monkeypatch.setattr(turnstile, "verificar", lambda token, ip: (False, "invalid-input-response"))
    assert turnstile.modo() == "log"

    class Falsa:
        headers = {}
        client = type("C", (), {"host": "127.0.0.1"})()

    turnstile.exigir(Falsa(), None)          # passa: em log só registra


def test_verificacao_le_a_resposta_do_cloudflare(monkeypatch):
    monkeypatch.setenv("MAGNO_TURNSTILE_SECRET", "0xSEGREDO")

    class Resposta:
        def __init__(self, corpo):
            self._corpo = json.dumps(corpo).encode()

        def read(self):
            return self._corpo

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(turnstile.urllib.request, "urlopen",
                        lambda req, timeout=6: Resposta({"success": True}))
    assert turnstile.verificar("token", "1.1.1.1") == (True, "ok")

    monkeypatch.setattr(turnstile.urllib.request, "urlopen",
                        lambda req, timeout=6: Resposta({"success": False,
                                                         "error-codes": ["timeout-or-duplicate"]}))
    ok, detalhe = turnstile.verificar("token", "1.1.1.1")
    assert ok is False and "timeout-or-duplicate" in detalhe

    def explode(*a, **k):
        raise OSError("sem rede")

    monkeypatch.setattr(turnstile.urllib.request, "urlopen", explode)
    ok, detalhe = turnstile.verificar("token", "1.1.1.1")
    assert ok is True and detalhe.startswith("indisponivel"), "queda do Cloudflare não pode derrubar o login"


def test_cadastro_aceita_o_campo_turnstile(monkeypatch):
    """O campo existe no contrato (o front manda quando o CAPTCHA está ligado)."""
    from server.main import CorpoCadastro
    corpo = CorpoCadastro(nome="Teste Captcha", telefone="13997630784", pin="9471",
                          consentimento_lgpd=True, turnstile="token-do-widget")
    assert corpo.turnstile == "token-do-widget"


# --------------------------------------------------------------- 404 e páginas novas
def test_404_do_site_x_json_da_api():
    """Navegador pedindo página inexistente recebe a 404 do site; /api continua JSON.

    Isto já quebrou uma vez: com o arquivo chamado web/404.html, o StaticFiles(html=True) do
    mount "/" servia HTML até para /api/*.
    """
    with TestClient(app) as cliente:
        pagina = cliente.get("/nao-existe-mesmo", headers={"Accept": "text/html"})
        assert pagina.status_code == 404 and "text/html" in pagina.headers["content-type"]
        assert "Esse horário não existe" in pagina.text

        api = cliente.get("/api/nao-existe-mesmo", headers={"Accept": "application/json"})
        assert api.status_code == 404
        assert "application/json" in api.headers["content-type"], api.headers["content-type"]
        assert api.json()["codigo"] in ("erro", "nao_encontrado")


def test_paginas_legais_e_arquivos_publicos():
    with TestClient(app) as cliente:
        for caminho in ("/privacidade", "/termos", "/robots.txt", "/sitemap.xml"):
            r = cliente.get(caminho)
            assert r.status_code == 200, f"{caminho} -> {r.status_code}"
        assert "Política de privacidade" in cliente.get("/privacidade").text
        assert "Termos de uso" in cliente.get("/termos").text
        assert "Sitemap:" in cliente.get("/robots.txt").text


def test_config_publica_nao_vaza_segredo():
    with TestClient(app) as cliente:
        dados = cliente.get("/api/publica/config").json()
        assert set(dados["captcha"]) == {"chave_site", "modo"}
        assert "secret" not in json.dumps(dados).lower()
