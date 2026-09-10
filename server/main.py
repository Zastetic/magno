"""Barbearia Magno — API + SPA na mesma origem (F0: esqueleto e health-check)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from server import db

RAIZ = Path(__file__).resolve().parent.parent
WEB = RAIZ / "web"
VERSAO = "0.1.0-f0"
LIMITE_CORPO_BYTES = 1_000_000

CSP = (
    "default-src 'self'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "img-src 'self' data:; font-src 'self' https://fonts.gstatic.com; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)

@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    caminho = db.inicializar()
    print(f"[magno] banco pronto em {caminho}")
    yield


app = FastAPI(
    title="Barbearia Magno",
    version=VERSAO,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=ciclo_de_vida,
)


@app.middleware("http")
async def cabecalhos_de_seguranca(request: Request, call_next):
    tamanho = request.headers.get("content-length")
    if tamanho and tamanho.isdigit() and int(tamanho) > LIMITE_CORPO_BYTES:
        return JSONResponse({"erro": "Requisição grande demais.", "codigo": "corpo_grande"}, status_code=413)

    resposta = await call_next(request)
    cabecalhos = resposta.headers
    cabecalhos["X-Content-Type-Options"] = "nosniff"
    cabecalhos["X-Frame-Options"] = "DENY"
    cabecalhos["Referrer-Policy"] = "no-referrer"
    cabecalhos["Content-Security-Policy"] = CSP
    if request.url.path.startswith("/api"):
        cabecalhos["Cache-Control"] = "no-store"
    return resposta


@app.get("/api/saude")
def saude() -> dict:
    """Health-check que também prova que o schema SQL aplicou: tabelas, contagens e integridade."""
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    banco = db.resumo()
    return {
        "ok": banco["integridade"] == "ok",
        "servico": "magno",
        "versao": VERSAO,
        "hora": agora,
        "banco": banco,
        "regras": {
            "slot_min": db.config("slot_min"),
            "buffer_min": db.config("buffer_min"),
            "antecedencia_min_h": db.config("antecedencia_min_h"),
            "janela_dias": db.config("janela_dias"),
            "cancelamento_limite_h": db.config("cancelamento_limite_h"),
            "fuso": db.config("fuso"),
        },
    }


if WEB.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
