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

    print("\n6) agendamento autenticado de verdade (grade calculada pelo servidor)")
    # A grade não está mais no HTML: o script pergunta ao servidor qual o primeiro horário
    # livre dos próximos dias — assim ele nunca chuta domingo, feriado nem hora fora da grade.
    fuso_local = timezone(timedelta(hours=-3))
    _, servicos = pedir("GET", "/api/publica/servicos")
    checa("GET /api/publica/servicos -> 200", isinstance(servicos, dict) and bool(servicos.get("servicos")))
    corte = next((s for s in servicos.get("servicos", []) if s["nome"] == "Corte masculino"), None)
    _, equipe = pedir("GET", f"/api/publica/equipe?servico_id={corte['id'] if corte else 1}")
    rafael = next((p for p in equipe.get("profissionais", []) if p["apelido"] == "Rafael"), None)
    checa("o catálogo e a equipe vêm do banco", bool(corte) and bool(rafael), str(equipe)[:120])

    dia = hora = ""
    de = datetime.now(fuso_local).strftime("%Y-%m-%d")
    ate = (datetime.now(fuso_local) + timedelta(days=20)).strftime("%Y-%m-%d")
    _, grade = pedir("GET", f"/api/publica/disponibilidade?servico_id={corte['id']}&profissional_id={rafael['id']}"
                            f"&de={de}&ate={ate}")
    dias_com_vaga = [d for d in grade.get("dias", []) if d["livres"]]
    checa("a disponibilidade pública traz dias com vaga (sem login)", bool(dias_com_vaga),
          str(grade.get("dias"))[:160])
    if dias_com_vaga:
        dia = dias_com_vaga[0]["data"]
        _, do_dia = pedir("GET", f"/api/publica/disponibilidade?servico_id={corte['id']}"
                                 f"&profissional_id={rafael['id']}&data={dia}")
        slots = do_dia.get("profissionais", [{}])[0].get("slots", [])
        checa("o dia escolhido devolve slots em UTC", bool(slots) and slots[0].endswith("Z"), str(slots[:2]))
        if slots:
            hora = (datetime.strptime(slots[0], "%Y-%m-%dT%H:%M:%SZ")
                    .replace(tzinfo=timezone.utc).astimezone(fuso_local).strftime("%H:%M"))

    corpo_reserva = {"name": "Okai Verificação", "phone": telefone, "service": "Corte masculino",
                     "barber": "Rafael", "date": dia, "time": hora}
    status, reserva = pedir("POST", "/api/bookings", corpo_reserva, token=token)
    checa("POST /api/bookings com Bearer -> 201", status == 201, f"{status} {reserva} ({dia} {hora})")
    codigo = reserva.get("agendamento", {}).get("codigo")
    checa("devolve código do agendamento", bool(codigo), str(reserva))
    status, repetida = pedir("POST", "/api/bookings", corpo_reserva, token=token)
    checa("mesmo horário duas vezes -> 409 horario_ocupado",
          status == 409 and repetida.get("codigo") == "horario_ocupado", f"{status} {repetida}")
    _, depois = pedir("GET", f"/api/publica/disponibilidade?servico_id={corte['id']}"
                             f"&profissional_id={rafael['id']}&data={dia}")
    ainda = [s for s in depois.get("profissionais", [{}])[0].get("slots", [])
             if s == datetime.strptime(f"{dia} {hora}", "%Y-%m-%d %H:%M").replace(tzinfo=fuso_local)
                  .astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")]
    checa("o horário marcado saiu da disponibilidade de todo mundo", not ainda, str(ainda))
    _, fora = pedir("POST", "/api/bookings", dict(corpo_reserva, time="14:07"), token=token)
    checa("horário fora da grade -> 400 horario_invalido",
          fora.get("codigo") == "horario_invalido", f"{fora}")
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
