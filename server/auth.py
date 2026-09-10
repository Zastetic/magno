"""Autenticação do Barbearia Magno — PIN do cliente, sessão opaca revogável e papéis.

Decisões que estão aqui dentro (docs/03-DECISOES.md):
  · D16 — cliente entra com telefone + PIN de 4 a 6 dígitos
  · token opaco (nunca JWT): o banco guarda só sha256(token), logout revoga de verdade
  · lockout de 5 falhas / 15 min por telefone+IP, resposta sempre genérica
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, Header, HTTPException

from server import db

TTL_MIN = int(os.environ.get("MAGNO_TOKEN_TTL_MIN", "1440"))
ITERACOES = 200_000
LIMITE_FALHAS = 5
JANELA_FALHAS_S = 15 * 60

_falhas: dict[str, dict[str, float]] = {}


# ------------------------------------------------------------------ telefone
def normalizar_telefone(bruto: str | None) -> str | None:
    """Aceita (13) 99763-0784, 13997630784, +55 13 99763-0784 → 5513997630784.

    Regra de plausibilidade brasileira: 13 dígitos = celular (o 9 depois do DDD),
    12 dígitos = fixo (começa com 2 a 5). Devolve None quando não fecha.
    """
    digitos = re.sub(r"\D", "", bruto or "")
    if not digitos:
        return None
    if digitos.startswith("0055"):
        digitos = digitos[2:]
    if not (digitos.startswith("55") and len(digitos) in (12, 13)) and len(digitos) in (10, 11):
        digitos = "55" + digitos          # veio sem o código do país
    if not (len(digitos) in (12, 13) and digitos.startswith("55")):
        return None
    ddd = int(digitos[2:4])
    if not 11 <= ddd <= 99:
        return None
    if len(digitos) == 13:
        if digitos[4] != "9":
            return None
    elif digitos[4] not in "2345":
        return None
    if len(set(digitos[4:])) < 3:          # 99999999 / 11111111 não é telefone
        return None
    return digitos


def telefone_formatado(e164: str | None) -> str:
    if not e164 or len(e164) < 12:
        return e164 or ""
    ddd, resto = e164[2:4], e164[4:]
    if len(resto) == 9:
        return f"({ddd}) {resto[:5]}-{resto[5:]}"
    return f"({ddd}) {resto[:4]}-{resto[4:]}"


# ------------------------------------------------------------------- PIN
def validar_pin(pin: str | None, telefone: str | None = None) -> tuple[bool, str]:
    if not pin or not re.fullmatch(r"\d{4,6}", pin):
        return False, "O PIN precisa ter de 4 a 6 dígitos, só números."
    if len(set(pin)) == 1:
        return False, "Escolha um PIN que não seja o mesmo dígito repetido."
    for sequencia in ("0123456789", "9876543210"):
        if pin in sequencia:
            return False, "Escolha um PIN que não seja uma sequência (1234, 4321…)."
    if telefone and pin in telefone:
        return False, "O PIN não pode ser um pedaço do seu próprio telefone."
    return True, ""


def hash_pin(pin: str) -> str:
    sal = secrets.token_bytes(16)
    derivado = hashlib.pbkdf2_hmac("sha256", pin.encode(), sal, ITERACOES)
    return f"pbkdf2_sha256${ITERACOES}${sal.hex()}${derivado.hex()}"


def conferir_pin(pin: str, guardado: str | None) -> bool:
    if not guardado:
        return False
    try:
        _, iteracoes, sal, esperado = guardado.split("$")
        derivado = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(sal), int(iteracoes))
        return hmac.compare_digest(derivado.hex(), esperado)
    except (ValueError, TypeError):
        return False


# ------------------------------------------------------- limite de tentativas
def _chave(telefone: str, ip: str | None) -> str:
    return f"{telefone}|{ip or '?'}"


def bloqueio_restante(telefone: str, ip: str | None) -> int:
    """Segundos que faltam para liberar o login. 0 = pode tentar."""
    agora = time.monotonic()
    registro = _falhas.get(_chave(telefone, ip))
    if not registro or registro["ate"] <= agora:
        return 0
    return int(registro["ate"] - agora)


def registrar_falha(telefone: str, ip: str | None) -> None:
    """Conta a falha e, ao chegar no limite, fecha a janela de bloqueio.

    O contador vive dentro de uma janela (`primeira`): falhas espaçadas além da janela
    recomeçam do zero. A versão anterior comparava com `ate` (0.0 = sem bloqueio) e
    reiniciava o contador a cada tentativa — o lockout nunca disparava.
    """
    agora = time.monotonic()
    chave = _chave(telefone, ip)
    registro = _falhas.get(chave)
    if not registro or (registro["ate"] <= agora and agora - registro["primeira"] > JANELA_FALHAS_S):
        registro = {"n": 0, "primeira": agora, "ate": 0.0}
    registro["n"] += 1
    if registro["n"] >= LIMITE_FALHAS:
        registro["ate"] = agora + JANELA_FALHAS_S
        registro["n"] = 0
        registro["primeira"] = agora
    _falhas[chave] = registro
    if len(_falhas) > 5000:                 # não deixa crescer sem limite
        for k in [k for k, v in _falhas.items() if v["ate"] <= agora][:1000]:
            _falhas.pop(k, None)


def limpar_falhas(telefone: str, ip: str | None) -> None:
    _falhas.pop(_chave(telefone, ip), None)


# ------------------------------------------------------------------ sessões
def _agora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def criar_sessao(usuario_id: int, ip: str | None = None, user_agent: str | None = None) -> str:
    token = secrets.token_urlsafe(32)
    expira = (datetime.now(timezone.utc) + timedelta(minutes=TTL_MIN)).strftime("%Y-%m-%dT%H:%M:%SZ")
    con = db.conectar()
    try:
        con.execute("DELETE FROM sessoes WHERE expira_em < ? OR revogada_em IS NOT NULL",
                    (_agora_iso(),))     # purge barato a cada login
        con.execute(
            "INSERT INTO sessoes (token_hash, usuario_id, expira_em, ip, user_agent) VALUES (?, ?, ?, ?, ?)",
            (_hash_token(token), usuario_id, expira, ip, (user_agent or "")[:200]),
        )
        con.execute("UPDATE usuarios SET ultimo_login_em = ? WHERE id = ?", (_agora_iso(), usuario_id))
        con.commit()
    finally:
        con.close()
    return token


def usuario_por_token(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    con = db.conectar()
    try:
        linha = con.execute(
            """SELECT u.*, s.expira_em AS sessao_expira_em
                 FROM sessoes s JOIN usuarios u ON u.id = s.usuario_id
                WHERE s.token_hash = ? AND s.revogada_em IS NULL
                  AND s.expira_em > ? AND u.ativo = 1""",
            (_hash_token(token), _agora_iso()),
        ).fetchone()
        return dict(linha) if linha else None
    finally:
        con.close()


def revogar_sessao(token: str | None) -> None:
    if not token:
        return
    con = db.conectar()
    try:
        con.execute("UPDATE sessoes SET revogada_em = ? WHERE token_hash = ? AND revogada_em IS NULL",
                    (_agora_iso(), _hash_token(token)))
        con.commit()
    finally:
        con.close()


def revogar_todas(usuario_id: int) -> None:
    con = db.conectar()
    try:
        con.execute("UPDATE sessoes SET revogada_em = ? WHERE usuario_id = ? AND revogada_em IS NULL",
                    (_agora_iso(), usuario_id))
        con.commit()
    finally:
        con.close()


# ------------------------------------------------------------------ usuários
def buscar_por_telefone(telefone: str) -> dict[str, Any] | None:
    con = db.conectar()
    try:
        linha = con.execute("SELECT * FROM usuarios WHERE telefone = ?", (telefone,)).fetchone()
        return dict(linha) if linha else None
    finally:
        con.close()


def buscar_por_email(email: str) -> dict[str, Any] | None:
    con = db.conectar()
    try:
        linha = con.execute("SELECT * FROM usuarios WHERE lower(email) = lower(?)", (email.strip(),)).fetchone()
        return dict(linha) if linha else None
    finally:
        con.close()


def buscar_por_google(sub: str) -> dict[str, Any] | None:
    con = db.conectar()
    try:
        linha = con.execute("SELECT * FROM usuarios WHERE google_sub = ?", (sub,)).fetchone()
        return dict(linha) if linha else None
    finally:
        con.close()


def buscar_por_id(usuario_id: int) -> dict[str, Any] | None:
    con = db.conectar()
    try:
        linha = con.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        return dict(linha) if linha else None
    finally:
        con.close()


def publico(usuario: dict[str, Any]) -> dict[str, Any]:
    """O que o front pode saber sobre o usuário logado — nunca o hash nem o sub do Google."""
    return {
        "id": usuario["id"],
        "nome": usuario["nome"],
        "papel": usuario["papel"],
        "telefone": usuario.get("telefone"),
        "telefone_formatado": telefone_formatado(usuario.get("telefone")),
        "email": usuario.get("email"),
        "foto_url": usuario.get("foto_url"),
        "tem_pin": bool(usuario.get("senha_hash")),
        "tem_google": bool(usuario.get("google_sub")),
        # conta só-Google ainda não tem telefone: precisa completar antes de agendar
        "precisa_telefone": not bool(usuario.get("telefone")),
    }


# ------------------------------------------------------- dependências FastAPI
def _token_do_header(authorization: str) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def usuario_atual(authorization: str = Header(default="")) -> dict[str, Any]:
    usuario = usuario_por_token(_token_do_header(authorization))
    if not usuario:
        raise HTTPException(401, {"erro": "Sessão expirada. Entre de novo.",
                                  "codigo": "sessao_invalida"})
    return usuario


def exigir_papel(*papeis: str):
    def dependencia(usuario: dict[str, Any] = Depends(usuario_atual)) -> dict[str, Any]:
        if usuario["papel"] not in papeis:
            raise HTTPException(403, {"erro": "Sua conta não tem acesso a isso.",
                                      "codigo": "sem_permissao"})
        return usuario
    return dependencia
