"""Login com Google — OAuth 2.0 authorization code (server-side).

O segredo do cliente NUNCA vai para o navegador: a troca do `code` pelo `access_token`
acontece aqui no servidor. O front só recebe o nosso token de sessão no fim.

Modos:
  · GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET preenchidos → fala com o Google de verdade
  · GOOGLE_FAKE=1 → provedor de mentira, local, para testar o fluxo inteiro sem credencial
  · nada configurado → login por Google desligado (a rota responde 503 explicando)
"""
from __future__ import annotations

import json
import os
import secrets
import urllib.parse
from typing import Any

import httpx

AUTORIZACAO = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
ESCOPOS = "openid email profile"
TEMPO_LIMITE_S = 10.0


def client_id() -> str:
    return (os.environ.get("GOOGLE_CLIENT_ID") or "").strip()


def client_secret() -> str:
    return (os.environ.get("GOOGLE_CLIENT_SECRET") or "").strip()


def modo_fake() -> bool:
    return (os.environ.get("GOOGLE_FAKE") or "").strip() in ("1", "true", "sim")


def configurado() -> bool:
    return bool(client_id() and client_secret()) or modo_fake()


def redirect_uri(base_url: str) -> str:
    return (os.environ.get("GOOGLE_REDIRECT_URI") or f"{base_url}/api/auth/google/callback").strip()


def url_autorizacao(state: str, uri_retorno: str) -> str:
    if modo_fake():
        # consentimento falso, servido por nós mesmos — exercita o fluxo de verdade
        return f"/api/auth/google/_fake?{urllib.parse.urlencode({'state': state})}"
    parametros = {
        "client_id": client_id(),
        "redirect_uri": uri_retorno,
        "response_type": "code",
        "scope": ESCOPOS,
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{AUTORIZACAO}?{urllib.parse.urlencode(parametros)}"


def trocar_codigo(code: str, uri_retorno: str) -> dict[str, Any]:
    """Troca o `code` pelos tokens. Só o servidor vê o client_secret."""
    if modo_fake():
        return {"access_token": f"fake-{code}", "id_token": f"fake.{code}"}
    resposta = httpx.post(
        TOKEN,
        data={
            "code": code,
            "client_id": client_id(),
            "client_secret": client_secret(),
            "redirect_uri": uri_retorno,
            "grant_type": "authorization_code",
        },
        timeout=TEMPO_LIMITE_S,
    )
    resposta.raise_for_status()
    return resposta.json()


def dados_do_usuario(access_token: str) -> dict[str, Any]:
    """Devolve {sub, email, email_verificado, nome, foto}."""
    if modo_fake():
        # o "código" falso carrega a identidade: fake-<sub>--<email>--<nome>
        corpo = access_token.replace("fake-", "", 1)
        partes = corpo.split("--")
        sub = partes[0] if partes and partes[0] else secrets.token_hex(6)
        email = partes[1] if len(partes) > 1 else f"{sub}@exemplo.test"
        nome = partes[2] if len(partes) > 2 else "Cliente de Teste"
        return {"sub": sub, "email": email, "email_verificado": True, "nome": nome,
                "foto": None}

    resposta = httpx.get(USERINFO, headers={"Authorization": f"Bearer {access_token}"},
                         timeout=TEMPO_LIMITE_S)
    resposta.raise_for_status()
    corpo = resposta.json()
    return {
        "sub": str(corpo.get("sub") or ""),
        "email": (corpo.get("email") or "").lower(),
        "email_verificado": bool(corpo.get("email_verified")),
        "nome": corpo.get("name") or "",
        "foto": corpo.get("picture"),
    }


def paginas_de_teste() -> str:
    """Lista de identidades falsas para o modo GOOGLE_FAKE (só existe em modo fake)."""
    return json.dumps([
        {"sub": "google-teste-1", "email": "joao.teste@exemplo.test", "nome": "João Teste"},
        {"sub": "google-teste-2", "email": "maria.teste@exemplo.test", "nome": "Maria Teste"},
    ])
