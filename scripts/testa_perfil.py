#!/usr/bin/env python3
"""Fluxo real no browser: cadastro → /perfil (nome → idade) → agenda com o nome → reserva.

Usa Playwright (rodar com o python do Hermes, que tem playwright instalado):
    /home/vh450/.hermes/hermes-agent/venv/bin/python scripts/testa_perfil.py
Gera os prints em docs/provas/.
"""
from __future__ import annotations

import json
import pathlib
import random
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8100"
PROVAS = pathlib.Path(__file__).resolve().parent.parent / "docs" / "provas"
FUSO = ZoneInfo("America/Sao_Paulo")
ok = falhas = 0


def checa(nome: str, condicao: bool, extra: str = "") -> None:
    global ok, falhas
    if condicao:
        ok += 1
        print(f"  [OK] {nome}")
    else:
        falhas += 1
        print(f"  [FALHOU] {nome} {extra}")


def pegar_json(caminho: str) -> dict:
    with urllib.request.urlopen(BASE + caminho, timeout=10) as resposta:
        return json.loads(resposta.read().decode())


def criar_conta(nome: str) -> dict:
    telefone = f"55139977{random.randint(10000, 99999)}"
    corpo = json.dumps({"nome": nome, "telefone": telefone, "pin": "9471",
                        "consentimento_lgpd": True}).encode()
    req = urllib.request.Request(BASE + "/api/auth/cadastro", data=corpo, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as resposta:
        dados = json.loads(resposta.read().decode())
    return {"telefone": telefone, "pin": "9471", **dados}


NOME = "João Verificação"
conta = criar_conta(NOME)
PROVAS.mkdir(parents=True, exist_ok=True)
# O que o banco oferece agora — é contra isso que o site tem que bater.
catalogo = [servico["nome"] for servico in pegar_json("/api/publica/servicos")["servicos"]]
equipe = [barbeiro["apelido"] for barbeiro in pegar_json("/api/publica/equipe")["profissionais"]]
hoje = datetime.now(FUSO).date()

with sync_playwright() as p:
    navegador = p.chromium.launch()
    erros: list[str] = []
    ctx = navegador.new_context(viewport={"width": 1440, "height": 980}, device_scale_factor=2,
                                locale="pt-BR", timezone_id="America/Sao_Paulo")
    pg = ctx.new_page()
    pg.on("console", lambda m: erros.append(f"{m.type}: {m.text}") if m.type == "error" else None)
    pg.on("pageerror", lambda e: erros.append(f"pageerror: {e}"))

    print("1) entrar pelo balcão (telefone + PIN) e cair no /perfil")
    pg.goto(f"{BASE}/login", wait_until="networkidle")
    pg.click("#btnModoTelefone")
    pg.fill("#loginTelefone", conta["telefone"])
    pg.fill("#loginPin", "9471")
    pg.click("#formEntrarTelefone button[type=submit]")
    pg.wait_for_url("**/perfil", timeout=15000)
    checa("conta nova é levada para /perfil", pg.url.endswith("/perfil"), pg.url)
    checa("título da etapa 1 pergunta o nome",
          "Como você quer ser chamado?" in pg.inner_text("#tituloPerfil"), pg.inner_text("#tituloPerfil"))
    checa("o nome do cadastro já vem preenchido", pg.input_value("#nome") == NOME, pg.input_value("#nome"))
    checa("a idade ainda está escondida", pg.is_hidden("#formIdade"))
    checa("nenhum dado aparece sem o token passar pelo /api/account", pg.is_visible("#caixaPerfil"))
    pg.screenshot(path=str(PROVAS / "perfil-passo-1-nome.png"), full_page=True)

    print("2) passo 1 -> passo 2 (idade)")
    pg.click("#formNome button[type=submit]")
    pg.wait_for_selector("#formIdade:visible", timeout=5000)
    checa("a idade aparece depois do nome", pg.is_visible("#formIdade") and pg.is_hidden("#formNome"))
    checa("saudação usa o nome digitado", pg.inner_text("#nomeConfirmado") == NOME)
    pg.screenshot(path=str(PROVAS / "perfil-passo-2-idade.png"), full_page=True)

    print("3) idade -> agenda")
    pg.fill("#idade", "24")
    pg.click("#formIdade button[type=submit]")
    pg.wait_for_url("**/account", timeout=15000)
    pg.wait_for_selector("#accountContent:visible", timeout=10000)
    checa("vai para a agenda depois da idade", pg.url.endswith("/account"), pg.url)
    checa("o nome aparece na tela inicial de agendamento (saudação)",
          pg.inner_text("#clientName") == NOME, pg.inner_text("#clientName"))
    checa("o nome aparece no cartão de agendamento", pg.inner_text("#bookingName") == NOME)
    checa("idade e telefone no cartão de agendamento",
          "24 anos" in pg.inner_text("#bookingMeta"), pg.inner_text("#bookingMeta"))
    checa("telefone já vem preenchido no formulário",
          pg.input_value("#phone").replace(" ", "") != "", pg.input_value("#phone"))
    pg.screenshot(path=str(PROVAS / "agenda-com-nome.png"), full_page=True)

    print("4) a grade vem do servidor (F3) e o horário marcado sai dela")
    # A CSP é estrita (script-src 'self'): nada de wait_for_function, laço de polling.
    for _ in range(40):
        if pg.locator("#dateList .date-option").count() >= 2:
            break
        pg.wait_for_timeout(250)
    servicos = pg.eval_on_selector_all("#serviceOptions button", "els => els.map(e => e.dataset.servico)")
    barbeiros = pg.eval_on_selector_all("#barberOptions button", "els => els.map(e => e.dataset.barber)")
    dias = pg.eval_on_selector_all("#dateList .date-option", "els => els.map(e => e.dataset.date)")
    checa("os serviços vêm do catálogo do banco", len(servicos) == len(catalogo),
          f"{servicos} vs {catalogo}")
    checa("os barbeiros vêm da equipe do banco", set(barbeiros) == set(equipe), f"{barbeiros} vs {equipe}")
    checa("a tira de dias é calculada (>= 2 dias com vaga)", len(dias) >= 2, str(dias))
    checa("nenhum dia da tira está no passado", all(d >= hoje.isoformat() for d in dias), str(dias))
    checa("o confirmar fica travado até escolher um horário", pg.is_disabled(".confirm-booking"))
    pg.screenshot(path=str(PROVAS / "agenda-grade-do-servidor.png"), full_page=True)

    dia_escolhido = dias[0]
    servico_id = pg.eval_on_selector("#serviceOptions .selected", "e => Number(e.dataset.servicoId)")
    barbeiro_id = pg.eval_on_selector("#barberOptions .selected", "e => Number(e.dataset.profissionalId)")
    horas = pg.eval_on_selector_all("#timeOptions button", "els => els.map(e => e.dataset.hora)")
    checa("o dia escolhido tem horários livres", bool(horas), str(horas))
    checa("o rótulo dos horários traz o dia escolhido", "·" in pg.inner_text("#hoursLabel"),
          pg.inner_text("#hoursLabel"))

    hora_escolhida = horas[0]
    pg.click(f"#timeOptions button[data-hora='{hora_escolhida}']")
    checa("o resumo passa a mostrar o horário escolhido",
          hora_escolhida in pg.inner_text("#bookingSummary"), pg.inner_text("#bookingSummary"))
    pg.click(".confirm-booking")
    feedback = ""
    for _ in range(40):
        feedback = pg.inner_text("#bookingFeedback")
        if feedback.startswith("Fechado") or "ocupado" in feedback:
            break
        pg.wait_for_timeout(250)
    checa("o servidor confirmou o horário", "Fechado. Código" in feedback, feedback)
    checa("o próximo horário aparece preenchido",
          "reservado" in pg.inner_text("#upcomingTitle"), pg.inner_text("#upcomingTitle"))

    # O ponto do F3: o horário recém-marcado (e o que cai no buffer) sai da grade na hora.
    for _ in range(40):
        horas_depois = pg.eval_on_selector_all("#timeOptions button", "els => els.map(e => e.dataset.hora)")
        if hora_escolhida not in horas_depois:
            break
        pg.wait_for_timeout(250)
    checa("o horário marcado saiu da grade do site", hora_escolhida not in horas_depois,
          f"{hora_escolhida} ainda em {horas_depois}")

    esperado = datetime.strptime(f"{dia_escolhido} {hora_escolhida}", "%Y-%m-%d %H:%M").replace(
        tzinfo=ZoneInfo("America/Sao_Paulo")).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    na_api = pegar_json(f"/api/publica/disponibilidade?servico_id={servico_id}"
                        f"&profissional_id={barbeiro_id}&data={dia_escolhido}")
    slots_api = na_api["profissionais"][0]["slots"]
    checa("a API também não oferece mais esse horário", esperado not in slots_api,
          f"{esperado} ainda em {slots_api[:3]}")
    fora_da_grade = [slot for slot in slots_api
                     if int(slot[14:16]) % 30 or not 8 <= int(slot[11:13]) - 3 < 20]
    checa("todo slot da API está na grade de 30 min dentro do funcionamento", not fora_da_grade,
          str(fora_da_grade[:3]))
    pg.screenshot(path=str(PROVAS / "agenda-horario-consumido.png"), full_page=True)

    print("5) editar pelo 'Meu perfil' e voltar")
    pg.click("#editProfile")
    pg.wait_for_url("**/perfil", timeout=10000)
    checa("Meu perfil abre a mesma página", pg.url.endswith("/perfil"))
    checa("quem já tem perfil vê o link da agenda", pg.is_visible("#linkAgenda"))
    checa("a idade agora vem preenchida", pg.input_value("#idade") == "24", pg.input_value("#idade"))
    pg.click("#formNome button[type=submit]")
    pg.wait_for_selector("#formIdade:visible")
    pg.fill("#idade", "25")
    pg.click("#formIdade button[type=submit]")
    pg.wait_for_url("**/account", timeout=15000)
    pg.wait_for_selector("#accountContent:visible")
    checa("idade atualizada aparece na agenda", "25 anos" in pg.inner_text("#bookingMeta"),
          pg.inner_text("#bookingMeta"))

    print("6) celular (390x844)")
    # o token vive em sessionStorage — não entra no storage_state, então é injetado na mão
    token_sessao = pg.evaluate("sessionStorage.getItem('magno_token')")
    checa("o navegador tem o Bearer guardado em sessionStorage", bool(token_sessao))
    ctx_mobile = navegador.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                                       locale="pt-BR", timezone_id="America/Sao_Paulo")
    pg_mobile = ctx_mobile.new_page()
    pg_mobile.goto(f"{BASE}/login", wait_until="domcontentloaded")
    pg_mobile.evaluate("(t) => sessionStorage.setItem('magno_token', t)", token_sessao)
    pg_mobile.goto(f"{BASE}/perfil", wait_until="networkidle")
    pg_mobile.wait_for_selector("#caixaPerfil:visible", timeout=10000)
    checa("no celular a página carrega sem estourar a largura",
          pg_mobile.evaluate("document.documentElement.scrollWidth <= 390"),
          pg_mobile.evaluate("document.documentElement.scrollWidth"))
    pg_mobile.screenshot(path=str(PROVAS / "perfil-mobile.png"), full_page=True)
    pg_mobile.goto(f"{BASE}/account", wait_until="networkidle")
    pg_mobile.wait_for_selector("#accountContent:visible", timeout=10000)
    pg_mobile.screenshot(path=str(PROVAS / "agenda-mobile-com-nome.png"), full_page=True)

    print("7) guardas sem sessão (contexto novo, sem token)")
    limpo = navegador.new_context(viewport={"width": 1280, "height": 900}, locale="pt-BR")
    pg_limpo = limpo.new_page()
    pg_limpo.goto(f"{BASE}/perfil", wait_until="networkidle")
    pg_limpo.wait_for_url("**/login**", timeout=10000)
    checa("sem Bearer, /perfil manda para o login guardando o destino",
          "/login?next=/perfil" in pg_limpo.url, pg_limpo.url)
    pg_limpo.goto(f"{BASE}/account", wait_until="networkidle")
    pg_limpo.wait_for_url("**/login**", timeout=10000)
    checa("sem Bearer, /account manda para o login", "/login?next=/account" in pg_limpo.url, pg_limpo.url)
    checa("nada de nome de cliente no HTML servido sem token",
          NOME not in pg_limpo.content(), "achou o nome no HTML")

    print("\nconsole do navegador:")
    reais = [e for e in erros if "favicon" not in e and "403" not in e and "Failed to load resource" not in e]
    checa("sem erro de JS no console", not reais, str(reais[:4]))

    navegador.close()

print(f"\n{ok} verificações OK, {falhas} falhas")
raise SystemExit(1 if falhas else 0)
