"""Configuração da suíte: banco descartável, nunca o banco de desenvolvimento.

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
