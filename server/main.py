"""Barbearia Magno — API + site na mesma origem.

F0: esqueleto, banco e health-check · F1: login por telefone+PIN e login com Google.
"""
from __future__ import annotations

import html
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from server import auth, db, email_provider, google_auth

RAIZ = Path(__file__).resolve().parent.parent
WEB = RAIZ / "web"
VERSAO = "0.2.0-f1"
LIMITE_CORPO_BYTES = 1_000_000
MINUTOS_STATE = 10

CSP = (
    "default-src 'self'; script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "img-src 'self' data: https://lh3.googleusercontent.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


def url_publica(request: Request) -> str:
    """URL base pública (atrás do túnel, o request já chega com o host real)."""
    return (os.environ.get("MAGNO_URL_BASE") or str(request.base_url)).rstrip("/")


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    caminho = db.inicializar()
    print(f"[magno] banco pronto em {caminho}")
    if not google_auth.configurado():
        print("[magno] login com Google desligado (faltam GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET)")
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


@app.exception_handler(StarletteHTTPException)
async def erro_padronizado(request: Request, exc: StarletteHTTPException):
    """Todo erro sai como {"erro": mensagem em pt-BR, "codigo": slug}."""
    detalhe = exc.detail
    if isinstance(detalhe, dict) and "erro" in detalhe:
        corpo = detalhe
    else:
        corpo = {"erro": str(detalhe), "codigo": "erro"}
    return JSONResponse(corpo, status_code=exc.status_code,
                        headers=getattr(exc, "headers", None))


@app.exception_handler(RequestValidationError)
async def validacao(request: Request, exc: RequestValidationError):
    campos = ", ".join(".".join(str(p) for p in e.get("loc", [])[1:]) for e in exc.errors())
    return JSONResponse({"erro": f"Confira os campos: {campos}.", "codigo": "validacao"}, status_code=400)


# ============================================================== health-check
@app.get("/api/saude")
def saude() -> dict:
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    banco = db.resumo()
    return {
        "ok": banco["integridade"] == "ok",
        "servico": "magno",
        "versao": VERSAO,
        "hora": agora,
        "banco": banco,
        "login": {
            "telefone_pin": True,
            "email_codigo": True,
            "google": google_auth.configurado(),
            "google_modo_teste": google_auth.modo_fake(),
            "email_modo": email_provider.modo(),
            "email_pronto": email_provider.configurado(),
            "email_remetente": email_provider.remetente(),
        },
        "regras": {
            "slot_min": db.config("slot_min"),
            "buffer_min": db.config("buffer_min"),
            "antecedencia_min_h": db.config("antecedencia_min_h"),
            "janela_dias": db.config("janela_dias"),
            "cancelamento_limite_h": db.config("cancelamento_limite_h"),
            "fuso": db.config("fuso"),
        },
    }


# ================================================================== cadastro
class CorpoCadastro(BaseModel):
    nome: str = Field(min_length=2, max_length=80)
    telefone: str
    pin: str
    email: str | None = None
    consentimento_lgpd: bool = False


class CorpoLogin(BaseModel):
    telefone: str
    pin: str


class CorpoTelefone(BaseModel):
    telefone: str


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@app.post("/api/auth/cadastro")
def cadastrar(corpo: CorpoCadastro, request: Request):
    if not corpo.consentimento_lgpd:
        raise HTTPException(400, {"erro": "É preciso aceitar os termos e a política de privacidade.",
                                  "codigo": "sem_consentimento"})
    telefone = auth.normalizar_telefone(corpo.telefone)
    if not telefone:
        raise HTTPException(400, {"erro": "Telefone inválido. Use DDD + número, ex: (13) 99763-0784.",
                                  "codigo": "telefone_invalido"})
    ok, mensagem = auth.validar_pin(corpo.pin, telefone)
    if not ok:
        raise HTTPException(400, {"erro": mensagem, "codigo": "pin_fraco"})
    if auth.buscar_por_telefone(telefone):
        raise HTTPException(409, {"erro": "Esse telefone já tem conta. Tente entrar.", "codigo": "ja_existe"})

    email = (corpo.email or "").strip().lower() or None
    if email and auth.buscar_por_email(email):
        raise HTTPException(409, {"erro": "Esse e-mail já está em outra conta.",
                                  "codigo": "email_em_uso"})

    con = db.conectar()
    try:
        cursor = con.execute(
            """INSERT INTO usuarios (nome, telefone, email, senha_hash, papel, consentimento_lgpd_em)
               VALUES (?, ?, ?, ?, 'cliente', ?)""",
            (corpo.nome.strip(), telefone, email, auth.hash_pin(corpo.pin),
             datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
        )
        con.commit()
        usuario_id = int(cursor.lastrowid or 0)
    except sqlite3.IntegrityError:
        # corrida entre a checagem acima e o INSERT: o índice único decide
        con.rollback()
        raise HTTPException(409, {"erro": "Esse telefone ou e-mail já tem conta.",
                                  "codigo": "ja_existe"})
    finally:
        con.close()
    if not usuario_id:
        raise HTTPException(500, {"erro": "Não consegui criar a conta.", "codigo": "erro_interno"})

    token = auth.criar_sessao(usuario_id, _ip(request), request.headers.get("user-agent"))
    db.registrar_evento("usuario.criado", usuario_id, payload='{"via":"telefone_pin"}')
    criado = auth.buscar_por_id(usuario_id)
    if not criado:
        raise HTTPException(500, {"erro": "Não consegui criar a conta.", "codigo": "erro_interno"})
    return {"token": token, "usuario": auth.publico(criado)}


@app.post("/api/auth/login")
def entrar(corpo: CorpoLogin, request: Request):
    telefone = auth.normalizar_telefone(corpo.telefone) or ""
    ip = _ip(request)

    restante = auth.bloqueio_restante(telefone, ip)
    if restante:
        raise HTTPException(429, {"erro": f"Muitas tentativas. Tente de novo em {restante // 60 + 1} min.",
                                  "codigo": "lockout", "esperar_seg": restante})

    usuario = auth.buscar_por_telefone(telefone) if telefone else None
    if not usuario or not auth.conferir_pin(corpo.pin or "", usuario.get("senha_hash")):
        auth.registrar_falha(telefone, ip)
        # mensagem idêntica nos dois casos: não revela se o telefone existe
        raise HTTPException(401, {"erro": "Telefone ou PIN não conferem.", "codigo": "credencial_invalida"})
    if not usuario["ativo"]:
        raise HTTPException(403, {"erro": "Conta desativada. Fale com a barbearia.", "codigo": "conta_inativa"})

    auth.limpar_falhas(telefone, ip)
    token = auth.criar_sessao(usuario["id"], ip, request.headers.get("user-agent"))
    db.registrar_evento("login.telefone", usuario["id"])
    return {"token": token, "usuario": auth.publico(usuario)}


@app.post("/api/auth/logout")
def sair(request: Request, usuario: dict = Depends(auth.usuario_atual)):
    cabecalho = request.headers.get("authorization", "")
    auth.revogar_sessao(cabecalho[7:].strip() if cabecalho.lower().startswith("bearer ") else "")
    db.registrar_evento("logout", usuario["id"])
    return {"ok": True}


@app.get("/api/auth/me")
def eu(usuario: dict = Depends(auth.usuario_atual)):
    return {"usuario": auth.publico(usuario)}


@app.patch("/api/auth/telefone")
def completar_telefone(corpo: CorpoTelefone, usuario: dict = Depends(auth.usuario_atual)):
    """Conta criada pelo Google ainda não tem telefone — e a barbearia precisa dele."""
    telefone = auth.normalizar_telefone(corpo.telefone)
    if not telefone:
        raise HTTPException(400, {"erro": "Telefone inválido. Use DDD + número.",
                                  "codigo": "telefone_invalido"})
    outro = auth.buscar_por_telefone(telefone)
    if outro and outro["id"] != usuario["id"]:
        raise HTTPException(409, {"erro": "Esse telefone já está em outra conta.", "codigo": "telefone_em_uso"})
    con = db.conectar()
    try:
        con.execute("UPDATE usuarios SET telefone = ?, atualizado_em = ? WHERE id = ?",
                    (telefone, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), usuario["id"]))
        con.commit()
    finally:
        con.close()
    atualizado = dict(usuario)
    atualizado["telefone"] = telefone
    return {"usuario": auth.publico(atualizado)}


# ==================================================== login por código no e-mail
class CorpoEmail(BaseModel):
    email: str
    nome: str | None = None


class CorpoCodigo(BaseModel):
    email: str
    codigo: str
    nome: str | None = None


class CorpoSenha(BaseModel):
    senha: str


class CorpoEntrarSenha(BaseModel):
    email: str
    senha: str


@app.post("/api/auth/codigo")
def pedir_codigo(corpo: CorpoEmail, request: Request):
    """Manda um código de 5 dígitos para o e-mail. É a entrada principal — sem senha."""
    email = auth.normalizar_email(corpo.email)
    if not email:
        raise HTTPException(400, {"erro": "Confira o e-mail digitado.", "codigo": "email_invalido"})

    ip = _ip(request)
    espera = auth.espera_para_enviar(email, ip)
    if espera:
        raise HTTPException(429, {
            "erro": f"Calma — dá para pedir outro código em {espera} segundos.",
            "codigo": "aguarde", "esperar_se": espera})

    usuario = auth.buscar_por_email(email)
    codigo, expira = auth.criar_codigo(email, ip)
    nome = (usuario or {}).get("nome") or corpo.nome
    envio = email_provider.enviar_codigo(email, codigo, nome)
    if not envio["ok"]:
        print(f"[magno] falha ao enviar e-mail ({envio['modo']}): {envio['detalhe']}")
        raise HTTPException(502, {
            "erro": "Não consegui enviar o e-mail agora. Tente de novo ou entre com telefone e PIN.",
            "codigo": "email_falhou"})

    auth.registrar_envio(email, ip)
    db.registrar_evento("codigo_email.enviado", (usuario or {}).get("id"))
    return {"enviado": True, "expira_em": expira, "minutos": auth.TEMPO_CODIGO_MIN}


@app.post("/api/auth/verificar")
def verificar_codigo(corpo: CorpoCodigo, request: Request):
    """Confere o código; cria a conta se for a primeira vez. Devolve a sessão."""
    email = auth.normalizar_email(corpo.email)
    if not email:
        raise HTTPException(400, {"erro": "Confira o e-mail digitado.", "codigo": "email_invalido"})

    ok, motivo = auth.conferir_codigo(email, corpo.codigo)
    if not ok:
        raise HTTPException(401, {"erro": motivo, "codigo": "codigo_invalido"})

    usuario = auth.buscar_por_email(email)
    criado = False
    if usuario and not usuario["ativo"]:
        raise HTTPException(403, {"erro": "Conta desativada. Fale com a barbearia.",
                                  "codigo": "conta_inativa"})
    if not usuario:
        nome = (corpo.nome or "").strip() or email.split("@")[0].replace(".", " ").title()
        con = db.conectar()
        try:
            cursor = con.execute(
                """INSERT INTO usuarios (nome, email, email_verificado_em, papel, consentimento_lgpd_em)
                   VALUES (?, ?, ?, 'cliente', ?)""",
                (nome[:80], email, auth._agora_iso(), auth._agora_iso()))
            con.commit()
            usuario_id = int(cursor.lastrowid or 0)
        finally:
            con.close()
        if not usuario_id:
            raise HTTPException(500, {"erro": "Não consegui criar a conta.", "codigo": "erro_interno"})
        criado = True
    else:
        usuario_id = int(usuario["id"])
        auth.marcar_email_verificado(usuario_id)

    token = auth.criar_sessao(usuario_id, _ip(request), request.headers.get("user-agent"))
    db.registrar_evento("login.email", usuario_id,
                        payload='{"criado": %s}' % ("true" if criado else "false"))
    conta = auth.buscar_por_id(usuario_id)
    if not conta:
        raise HTTPException(500, {"erro": "Conta não encontrada.", "codigo": "erro_interno"})
    return {"token": token, "usuario": auth.publico(conta), "conta_nova": criado}


@app.post("/api/auth/senha")
def criar_senha(corpo: CorpoSenha, usuario: dict = Depends(auth.usuario_atual)):
    """Senha é opcional: quem quiser um atalho cria aqui (pode trocar depois)."""
    ok, mensagem = auth.validar_senha(corpo.senha)
    if not ok:
        raise HTTPException(400, {"erro": mensagem, "codigo": "senha_fraca"})
    auth.definir_senha(usuario["id"], corpo.senha)
    db.registrar_evento("senha.definida", usuario["id"])
    conta = auth.buscar_por_id(usuario["id"])
    return {"usuario": auth.publico(conta) if conta else auth.publico(usuario)}


@app.post("/api/auth/entrar-senha")
def entrar_com_senha(corpo: CorpoEntrarSenha, request: Request):
    email = auth.normalizar_email(corpo.email) or ""
    ip = _ip(request)
    restante = auth.bloqueio_restante(email, ip)
    if restante:
        raise HTTPException(429, {"erro": f"Muitas tentativas. Tente de novo em {restante // 60 + 1} min.",
                                  "codigo": "lockout", "esperar_seg": restante})

    usuario = auth.buscar_por_email(email) if email else None
    if not usuario or not auth.conferir_pin(corpo.senha or "", usuario.get("senha_hash")):
        auth.registrar_falha(email, ip)
        raise HTTPException(401, {"erro": "E-mail ou senha não conferem.", "codigo": "credencial_invalida"})
    if not usuario["ativo"]:
        raise HTTPException(403, {"erro": "Conta desativada. Fale com a barbearia.", "codigo": "conta_inativa"})

    auth.limpar_falhas(email, ip)
    token = auth.criar_sessao(usuario["id"], ip, request.headers.get("user-agent"))
    db.registrar_evento("login.senha", usuario["id"])
    return {"token": token, "usuario": auth.publico(usuario)}


# ============================================================ login com Google
@app.get("/api/auth/google/iniciar")
def google_iniciar(request: Request):
    if not google_auth.configurado():
        raise HTTPException(503, {"erro": "O login com Google ainda não está configurado nesta loja.",
                                  "codigo": "google_desligado"})
    state = secrets.token_urlsafe(24)
    agora = datetime.now(timezone.utc)
    con = db.conectar()
    try:
        con.execute("DELETE FROM logins_pendentes WHERE expira_em < ?",
                    (agora.strftime("%Y-%m-%dT%H:%M:%SZ"),))
        con.execute("INSERT INTO logins_pendentes (state, expira_em, destino, ip) VALUES (?, ?, ?, ?)",
                    (state,
                     (agora + timedelta(minutes=MINUTOS_STATE)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     (request.query_params.get("destino") or "")[:300],
                     _ip(request)))
        con.commit()
    finally:
        con.close()
    return RedirectResponse(google_auth.url_autorizacao(state, google_auth.redirect_uri(url_publica(request))))


@app.get("/api/auth/google/callback")
def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error or not code or not state:
        return RedirectResponse("/entrar.html?erro=google_cancelado")

    agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    con = db.conectar()
    try:
        linha = con.execute("SELECT * FROM logins_pendentes WHERE state = ? AND expira_em > ?",
                            (state, agora)).fetchone()
        if not linha:
            return RedirectResponse("/entrar.html?erro=state_invalido")
        con.execute("DELETE FROM logins_pendentes WHERE state = ?", (state,))  # uso único
        con.commit()
        destino = linha["destino"] or "/conta.html"
    finally:
        con.close()

    try:
        tokens = google_auth.trocar_codigo(code, google_auth.redirect_uri(url_publica(request)))
        dados = google_auth.dados_do_usuario(tokens.get("access_token", ""))
    except Exception:
        return RedirectResponse("/entrar.html?erro=google_falhou")

    if not dados.get("sub") or not dados.get("email"):
        return RedirectResponse("/entrar.html?erro=google_sem_email")

    usuario = auth.buscar_por_google(dados["sub"]) or auth.buscar_por_email(dados["email"])
    criado = False
    usuario_id = 0
    con = db.conectar()
    try:
        if usuario:
            con.execute(
                """UPDATE usuarios SET google_sub = COALESCE(google_sub, ?),
                          foto_url = COALESCE(?, foto_url), email = COALESCE(email, ?),
                          atualizado_em = ?
                    WHERE id = ?""",
                (dados["sub"], dados.get("foto"), dados["email"], agora, usuario["id"]))
            usuario_id = usuario["id"]
        else:
            cursor = con.execute(
                """INSERT INTO usuarios (nome, email, senha_hash, google_sub, foto_url, papel,
                                         consentimento_lgpd_em)
                   VALUES (?, ?, NULL, ?, ?, 'cliente', ?)""",
                (dados["nome"] or dados["email"].split("@")[0], dados["email"], dados["sub"],
                 dados.get("foto"), agora))
            usuario_id = cursor.lastrowid
            criado = True
        con.commit()
        usuario_id = int(usuario_id or 0)
    finally:
        con.close()
    if not usuario_id:
        return RedirectResponse("/entrar.html?erro=google_falhou")

    token = auth.criar_sessao(usuario_id, _ip(request), request.headers.get("user-agent"))
    db.registrar_evento("login.google", usuario_id, payload='{"criado": %s}' % ("true" if criado else "false"))
    separador = "" if destino.startswith("/") else "/"
    return RedirectResponse(f"{destino}{separador}#entrar={token}")


@app.get("/api/auth/google/_fake", response_class=HTMLResponse)
def google_fake(request: Request, state: str = ""):
    """Consentimento falso, local — substitui o Google quando GOOGLE_FAKE=1.

    Existe só para testar o fluxo inteiro sem credencial real. Fora do modo fake,
    a rota não faz nada além de dizer que não existe.
    """
    if not google_auth.modo_fake():
        raise HTTPException(404, {"erro": "Rota não encontrada.", "codigo": "nao_encontrado"})
    identidades = [
        ("google-teste-1", "joao.teste@exemplo.test", "João Teste"),
        ("google-teste-2", "maria.teste@exemplo.test", "Maria Teste"),
    ]
    links = "".join(
        f'<li><a class="btn btn-vazado" href="/api/auth/google/callback'
        f'?code={html.escape(sub)}--{html.escape(email)}--{html.escape(nome)}'
        f'&state={html.escape(state)}">Entrar como {html.escape(nome)}</a>'
        f'<span class="email">{html.escape(email)}</span></li>'
        for sub, email, nome in identidades
    )
    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Google (teste) — Barbearia Magnum</title>
<link rel="stylesheet" href="/styles.css"></head>
<body class="composicao-editorial">
<main class="aviso-fake">
  <p class="kicker">Ambiente de teste</p>
  <h1>Escolha uma conta</h1>
  <p class="linha-fina">Esta tela substitui o Google enquanto as credenciais reais não
  estão configuradas. O fluxo (state, callback, criação de conta, sessão) é o mesmo.</p>
  <ul class="lista-fake">{links}</ul>
  <a class="btn btn-texto" href="/entrar.html">Voltar</a>
</main></body></html>"""


if WEB.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")
