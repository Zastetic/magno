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


def test_banco_tem_as_11_tabelas_e_os_indices():
    resumo = db.resumo()
    assert resumo["tabelas"] == 11
    assert resumo["indices"] == 8
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
        for caminho, tipo in (("/", "text/html"), ("/app.js", "javascript"), ("/styles.css", "text/css")):
            r = cliente.get(caminho)
            assert r.status_code == 200, caminho
            assert tipo in r.headers["content-type"], (caminho, r.headers["content-type"])
