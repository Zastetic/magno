#!/usr/bin/env python3
"""Verificação ao vivo do Bearer — roda contra o servidor de verdade (127.0.0.1:8100).

Cada item imprime [OK]/[FALHOU]; sai com código 1 se qualquer um falhar.
Não mexe em banco: usa só a API pública e cria uma conta nova descartável.

    ./venv/bin/python scripts/testa_bearer.py
"""
from __future__ import annotations

import json
import random
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "http://127.0.0.1:8100"
ok = falhas = 0


def checa(nome: str, condicao: bool, extra: str = "") -> None:
    global ok, falhas
    if condicao:
        ok += 1
        print(f"  [OK] {nome}")
    else:
        falhas += 1
        print(f"  [FALHOU] {nome} {extra}")


def pedir(metodo: str, caminho: str, corpo: dict | None = None, token: str | None = None,
          cabecalho_cru: str | None = None) -> tuple[int, dict]:
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(BASE + caminho, data=dados, method=metodo)
    req.add_header("Content-Type", "application/json")
    if cabecalho_cru is not None:
        req.add_header("Authorization", cabecalho_cru)
    elif token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as resposta:
            texto = resposta.read().decode()
            try:
                return resposta.status, json.loads(texto)
            except json.JSONDecodeError:
                return resposta.status, {"_texto": texto}
    except urllib.error.HTTPError as erro:
        texto = erro.read().decode()
        try:
            return erro.code, json.loads(texto)
        except json.JSONDecodeError:
            return erro.code, {"_texto": texto}


def main() -> int:
    print("1) identidade do servidor")
    status, saude = pedir("GET", "/api/saude")
    checa("GET /api/saude responde 200", status == 200, str(status))
    checa("banco íntegro", saude.get("banco", {}).get("integridade") == "ok", str(saude.get("banco")))
    checa("tem barbeiro cadastrado (agendamento possível)",
          saude.get("banco", {}).get("contagens", {}).get("profissionais", 0) > 0,
          str(saude.get("banco", {}).get("contagens")))

    print("\n2) cadastro devolve um Bearer utilizável")
    sufixo = random.randint(10000, 99999)
    telefone = f"55139976{sufixo}"
    status, cadastro = pedir("POST", "/api/auth/cadastro", {
        "nome": "Verificação Bearer", "telefone": telefone, "pin": "9471", "consentimento_lgpd": True})
    checa("POST /api/auth/cadastro -> 200", status == 200, f"{status} {cadastro}")
    token = cadastro.get("token", "")
    checa("resposta traz token opaco", bool(token) and len(token) > 30)
    checa("usuário do cadastro tem perfil incompleto (sem idade)",
          cadastro.get("usuario", {}).get("perfil_completo") is False, str(cadastro.get("usuario")))

    print("\n3) o que o Bearer abre")
    status, me = pedir("GET", "/api/auth/me", token=token)
    checa("GET /api/auth/me com Bearer -> 200", status == 200, str(status))
    checa("nome confere", me.get("usuario", {}).get("nome") == "Verificação Bearer")
    checa("o hash do PIN nunca sai", "senha_hash" not in me.get("usuario", {}), str(me))
    status, conta = pedir("GET", "/api/account", token=token)
    checa("GET /api/account com Bearer -> 200", status == 200, str(status))
    checa("conta sem agendamentos ainda", conta.get("agendamentos") == [], str(conta))
    status, _ = pedir("GET", "/api/auth/me", cabecalho_cru="bearer " + token)
    checa("esquema 'bearer' minúsculo é aceito (RFC 7235)", status == 200, str(status))

    print("\n4) o que o Bearer fecha")
    status, sem = pedir("GET", "/api/auth/me")
    checa("sem cabeçalho -> 401 sessao_invalida",
          status == 401 and sem.get("codigo") == "sessao_invalida", f"{status} {sem}")
    status, inventado = pedir("GET", "/api/auth/me", token="x" * 43)
    checa("token inventado -> 401", status == 401, f"{status} {inventado}")
    status, _ = pedir("GET", "/api/auth/me", cabecalho_cru="Token " + token)
    checa("esquema errado ('Token') -> 401", status == 401, str(status))
    status, _ = pedir("GET", "/api/auth/me", token=token[:-1])
    checa("token truncado -> 401", status == 401, str(status))
    status, _ = pedir("PATCH", "/api/account/profile", {"nome": "X", "idade": 20})
    checa("PATCH perfil sem token -> 401", status == 401, str(status))
    status, _ = pedir("POST", "/api/bookings", {"name": "A", "phone": telefone, "service": "Corte masculino",
                                               "barber": "Rafael", "date": "2026-09-18", "time": "15:00"})
    checa("POST /api/bookings sem token -> 401", status == 401, str(status))

    print("\n5) página /perfil (nome -> idade -> agenda)")
    status, perfil_html = pedir("GET", "/perfil")
    texto = perfil_html.get("_texto", "")
    checa("GET /perfil -> 200", status == 200, str(status))
    checa("pergunta o nome primeiro", "Como você quer ser chamado?" in texto)
    checa("a etapa da idade começa escondida", 'id="formIdade" hidden' in texto)
    status, profile = pedir("PATCH", "/api/account/profile", {"nome": "Okai Verificação", "idade": 24}, token=token)
    checa("PATCH /api/account/profile com Bearer -> 200", status == 200, f"{status} {profile}")
    checa("agora o perfil está completo", profile.get("usuario", {}).get("perfil_completo") is True,
          str(profile.get("usuario")))
    checa("idade gravada", profile.get("usuario", {}).get("idade") == 24)
    status, conta = pedir("GET", "/api/account", token=token)
    checa("a agenda já mostra o nome novo", conta.get("usuario", {}).get("nome") == "Okai Verificação")

    print("\n6) agendamento autenticado de verdade")
    # dia e hora sorteados: o script é rodado muitas vezes e não pode colidir consigo mesmo
    corpo_reserva, reserva, status = {}, {}, 0
    for _ in range(6):
        dia = (datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-3)))
               + timedelta(days=random.randint(5, 45))).strftime("%Y-%m-%d")
        hora = random.choice([f"{h:02d}:{m:02d}" for h in range(9, 19) for m in (0, 30)])
        corpo_reserva = {"name": "Okai Verificação", "phone": telefone, "service": "Corte masculino",
                         "barber": "Rafael", "date": dia, "time": hora}
        status, reserva = pedir("POST", "/api/bookings", corpo_reserva, token=token)
        if status == 201:
            break
    checa("POST /api/bookings com Bearer -> 201", status == 201, f"{status} {reserva} ({corpo_reserva.get('date')} {corpo_reserva.get('time')})")
    codigo = reserva.get("agendamento", {}).get("codigo")
    checa("devolve código do agendamento", bool(codigo), str(reserva))
    status, repetida = pedir("POST", "/api/bookings", corpo_reserva, token=token)
    checa("mesmo horário duas vezes -> 409 horario_ocupado",
          status == 409 and repetida.get("codigo") == "horario_ocupado", f"{status} {repetida}")
    status, conta = pedir("GET", "/api/account", token=token)
    checa("a conta lista o agendamento criado", len(conta.get("agendamentos", [])) == 1, str(conta))

    print("\n7) revogação")
    status, _ = pedir("POST", "/api/auth/logout", {}, token=token)
    checa("POST /api/auth/logout -> 200", status == 200, str(status))
    status, revogado = pedir("GET", "/api/auth/me", token=token)
    checa("token revogado -> 401", status == 401 and revogado.get("codigo") == "sessao_invalida",
          f"{status} {revogado}")
    status, login = pedir("POST", "/api/auth/login", {"telefone": telefone, "pin": "9471"})
    checa("login por PIN emite Bearer novo", status == 200 and bool(login.get("token")), f"{status} {login}")
    novo = login.get("token", "")
    status, _ = pedir("POST", "/api/auth/logout-all", {}, token=novo)
    checa("logout-all -> 200", status == 200, str(status))
    status, _ = pedir("GET", "/api/auth/me", token=novo)
    checa("todas as sessões caíram -> 401", status == 401, str(status))

    print(f"\n{ok} verificações OK, {falhas} falhas")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
