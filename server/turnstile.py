"""Cloudflare Turnstile nas ações sensíveis (cadastro, código por e-mail, login).

Ligado por ambiente — sem chave, o site funciona exatamente como hoje:

    MAGNO_TURNSTILE_SITE=0x4AAA...      # chave pública (vai para o HTML)
    MAGNO_TURNSTILE_SECRET=0x4AAA...    # chave secreta (só no servidor)
    MAGNO_TURNSTILE_MODO=log            # off | log | on   (padrão: on se houver chaves)

`log` é o modo recomendado para ligar em produção: verifica de verdade e grava o resultado
em `eventos`, mas **nunca bloqueia** — assim dá para medir quantos visitantes reais passam
antes de virar bloqueio. Quando o Cloudflare não responde, liberamos (fail-open) e
registramos: uma queda do Cloudflare não pode derrubar o login da barbearia.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

from fastapi import HTTPException

from server import db

URL_VERIFICACAO = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TIMEOUT_S = 6


def site() -> str:
    return (os.environ.get("MAGNO_TURNSTILE_SITE") or "").strip()


def segredo() -> str:
    return (os.environ.get("MAGNO_TURNSTILE_SECRET") or "").strip()


def modo() -> str:
    escolhido = (os.environ.get("MAGNO_TURNSTILE_MODO") or "").strip().lower()
    if escolhido in ("off", "log", "on"):
        return escolhido
    return "on" if (site() and segredo()) else "off"


def ativo() -> bool:
    """Só vale a pena verificar com segredo e modo ligado."""
    return modo() in ("log", "on") and bool(segredo())


def verificar(token: str | None, ip: str | None) -> tuple[bool, str]:
    """(passou, detalhe). Sem token, com token inválido ou fora do ar, o detalhe explica."""
    if not segredo():
        return True, "sem_segredo"
    if not token:
        return False, "sem_token"
    corpo = urllib.parse.urlencode({"secret": segredo(), "response": token,
                                    "remoteip": ip or ""}).encode()
    requisicao = urllib.request.Request(
        URL_VERIFICACAO, data=corpo,
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(requisicao, timeout=TIMEOUT_S) as resposta:
            dados = json.loads(resposta.read().decode("utf-8", "replace"))
    except Exception as erro:                      # DNS, timeout, 5xx do Cloudflare…
        return True, f"indisponivel:{type(erro).__name__}"
    if dados.get("success"):
        return True, "ok"
    return False, ",".join(dados.get("error-codes") or ["falhou"])


def exigir(request, token: str | None) -> None:
    """Chamado no começo das ações sensíveis. Em `log` nunca levanta exceção."""
    if not ativo():
        return
    from server import limites                    # import tardio: evita ciclo

    ok, detalhe = verificar(token, limites.ip_do_cliente(request))
    if ok:
        if detalhe.startswith("indisponivel"):
            db.registrar_evento("captcha_indisponivel", payload=json.dumps({"detalhe": detalhe}))
        return
    db.registrar_evento("captcha_falhou", payload=json.dumps({"detalhe": detalhe}))
    if modo() == "log":
        return
    raise HTTPException(status_code=400, detail={
        "erro": "Não consegui confirmar que você não é um robô. Recarregue a página e tente de novo.",
        "codigo": "captcha",
    })


def estado() -> dict:
    """Resumo para /api/saude (a chave pública é pública de propósito)."""
    return {"modo": modo(), "ativo": ativo(), "chave_site": site() if modo() != "off" else ""}
