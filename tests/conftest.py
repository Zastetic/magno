"""Configuração da suíte: banco descartável e provedor Google falso.

Precisa rodar ANTES de importar `server.*`, porque `server/db.py` resolve o caminho do
banco no momento do import.
"""
import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

_banco_de_teste = Path(tempfile.gettempdir()) / "magno-teste.db"
for sufixo in ("", "-wal", "-shm"):
    try:
        os.remove(str(_banco_de_teste) + sufixo)
    except OSError:
        pass
os.environ["MAGNO_DB"] = str(_banco_de_teste)
os.environ.setdefault("MAGNO_AMBIENTE", "teste")
os.environ["MAGNO_URL_BASE"] = "http://testserver"
# provedor Google falso: o fluxo inteiro (state, callback, criação de conta, sessão) roda
# sem credencial real. Os testes que precisam do Google "desligado" desligam na mão.
os.environ["GOOGLE_FAKE"] = "1"
os.environ.pop("GOOGLE_CLIENT_ID", None)
os.environ.pop("GOOGLE_CLIENT_SECRET", None)


# --------------------------------------------------------------- fixtures (pytest)
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def limites_zerados():
    """Zera o freio por IP antes de cada teste.

    O limitador é global de propósito (um dicionário no processo). Sem isso, os testes —
    que fazem dezenas de requisições do mesmo "IP" (testclient) — esbarram no 429 e a
    suíte inteira falha por um motivo que não é o que ela quer medir. Os testes de limite
    (tests/test_limites.py) forçam a regra que querem testar dentro do próprio teste.
    """
    from server import limites
    limites.limpar()
    yield
    limites.limpar()
