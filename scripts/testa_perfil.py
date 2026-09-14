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

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8100"
PROVAS = pathlib.Path(__file__).resolve().parent.parent / "docs" / "provas"
ok = falhas = 0


def checa(nome: str, condicao: bool, extra: str = "") -> None:
    global ok, falhas
    if condicao:
        ok += 1
        print(f"  [OK] {nome}")
    else:
        falhas += 1
        print(f"  [FALHOU] {nome} {extra}")


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

    print("4) reservar de verdade com o Bearer do navegador")
    # Dias/horas/barbeiros são os do HTML fixo: roda as combinações até achar cadeira livre.
    # (cada execução consome uma vaga dessa grade — por isso a F3 do backlog é urgente)
    feedback = ""
    tentativas = 0
    for barbeiro in ("Rafael", "Bruno"):
        pg.click(f"#barberOptions button[data-barber='{barbeiro}']")
        for dia in ("2026-09-18", "2026-09-19", "2026-09-20", "2026-09-16", "2026-09-17"):
            for hora in ("15:30", "17:00", "10:30", "09:30", "18:00"):
                tentativas += 1
                pg.click(f"#dateList button[data-date='{dia}']")
                pg.click(f"#timeOptions button:text-is('{hora}')")
                pg.click(".confirm-booking")
                # sem wait_for_function: a CSP estrita da loja (script-src 'self') proíbe eval na página
                feedback = ""
                for _ in range(40):
                    feedback = pg.inner_text("#bookingFeedback")
                    if feedback.startswith("Fechado") or "ocupado" in feedback or "telefone" in feedback:
                        break
                    pg.wait_for_timeout(250)
                if feedback.startswith("Fechado"):
                    break
            if feedback.startswith("Fechado"):
                break
        if feedback.startswith("Fechado"):
            break
    checa("o servidor confirmou o horário", "Fechado. Código" in feedback, f"{feedback} ({tentativas} tentativas)")
    checa("o próximo horário aparece preenchido",
          "reservado" in pg.inner_text("#upcomingTitle"), pg.inner_text("#upcomingTitle"))
    pg.screenshot(path=str(PROVAS / "agenda-agendamento-confirmado.png"), full_page=True)

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
