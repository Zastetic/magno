#!/usr/bin/env python3
"""E2E das entradas alternativas no browser: telefone+PIN e Google (provedor de teste).

O caminho principal (e-mail + código) tem o seu próprio script: testa_email_login.py.
Roda com o python que tem playwright:
    /home/vh450/.hermes/hermes-agent/venv/bin/python scripts/testa_login.py
"""
from __future__ import annotations

import random
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8100"
ok = falhas = 0


def checa(nome: str, condicao: bool, extra: object = "") -> None:
    global ok, falhas
    if condicao:
        ok += 1
        print(f"  [OK] {nome}")
    else:
        falhas += 1
        print(f"  [FALHOU] {nome} {extra}")


def criar_conta(nome: str, telefone: str) -> dict:
    import json
    corpo = json.dumps({"nome": nome, "telefone": telefone, "pin": "9471",
                        "consentimento_lgpd": True}).encode()
    req = urllib.request.Request(BASE + "/api/auth/cadastro", data=corpo, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as resposta:
        return json.loads(resposta.read().decode())


BALCAO = f"55139978{random.randint(10000, 99999)}"
conta = criar_conta("Cliente do Balcão", BALCAO)

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=2,
                        locale="pt-BR", timezone_id="America/Sao_Paulo")
    pg = ctx.new_page()
    erros: list[str] = []
    pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: erros.append(str(e)))

    print("1) tela de entrar: e-mail como caminho principal")
    pg.goto(f"{BASE}/login", wait_until="networkidle")
    pg.wait_for_selector("#caixaPerfil, #formEmail", timeout=10000)
    checa("campo de e-mail visível", not pg.eval_on_selector("#formEmail", "el => el.hidden"))
    checa("botão do Google presente", pg.locator("#btnGoogle").count() == 1)
    checa("atalho para senha", pg.locator("#btnModoSenha").count() == 1)
    checa("atalho para telefone e PIN", pg.locator("#btnModoTelefone").count() == 1)

    print("2) PIN errado mostra erro em português (e não vaza se o telefone existe)")
    pg.click("#btnModoTelefone")
    pg.fill("#loginTelefone", BALCAO)
    pg.fill("#loginPin", "9999")
    pg.click("#formEntrarTelefone button[type=submit]")
    pg.wait_for_timeout(1500)
    checa("erro genérico de credencial", "não conferem" in pg.inner_text("#aviso"), pg.inner_text("#aviso"))

    print("3) telefone + PIN entra e a conta nova cai no /perfil")
    pg.fill("#loginPin", "9471")
    pg.click("#formEntrarTelefone button[type=submit]")
    pg.wait_for_url("**/perfil", timeout=15000)
    pg.wait_for_selector("#caixaPerfil:visible")
    checa("guardou o destino: /account manda para /perfil", pg.url.endswith("/perfil"), pg.url)
    checa("nome do balcão já vem no campo", pg.input_value("#nome") == "Cliente do Balcão")
    checa("token não ficou na URL", "#entrar=" not in pg.url, pg.url)

    print("4) Google (consentimento de teste) entra e mostra o nome do Google na agenda")
    pg.goto(f"{BASE}/login", wait_until="networkidle")
    pg.click("#btnGoogle")
    pg.wait_for_selector("p.kicker:text-is('Ambiente de teste')", timeout=15000)
    checa("foi para o consentimento de teste", "_fake" in pg.url, pg.url)
    pg.click("text=Entrar como Maria Teste")
    pg.wait_for_url(lambda u: u.endswith("/perfil") or u.endswith("/account"), timeout=20000)
    if pg.url.endswith("/perfil"):
        # primeira vez desta identidade: passa pelas duas perguntas do primeiro acesso
        pg.wait_for_selector("#caixaPerfil:visible")
        checa("nome veio do Google", pg.input_value("#nome") == "Maria Teste", pg.input_value("#nome"))
        pg.click("#formNome button[type=submit]")
        pg.wait_for_selector("#formIdade:visible")
        pg.fill("#idade", "31")
        pg.click("#formIdade button[type=submit]")
        pg.wait_for_url("**/account", timeout=15000)
    pg.wait_for_selector("#accountContent:visible", timeout=10000)
    checa("agenda aberta com o nome do Google", pg.inner_text("#clientName") == "Maria Teste", pg.inner_text("#clientName"))
    checa("token saiu da URL", "#entrar=" not in pg.url, pg.url)

    print("5) o Bearer do navegador é o mesmo que a API aceita")
    token = pg.evaluate("sessionStorage.getItem('magno_token')")
    checa("Bearer guardado em sessionStorage", bool(token))
    minha_conta = ctx.request.get(f"{BASE}/api/account", headers={"Authorization": f"Bearer {token}"})
    checa("GET /api/account com o Bearer do navegador -> 200", minha_conta.status == 200, minha_conta.status)
    checa("é a conta da Maria Teste", minha_conta.json()["usuario"]["nome"] == "Maria Teste")
    sem_bearer = ctx.request.get(f"{BASE}/api/account")
    checa("sem Bearer a mesma rota -> 401", sem_bearer.status == 401, sem_bearer.status)

    print("6) sair revoga o Bearer de verdade")
    ctx.request.patch(f"{BASE}/api/account/profile",
                      headers={"Authorization": f"Bearer {token}"},
                      data={"nome": "Maria Teste", "idade": 31})
    pg.goto(f"{BASE}/account", wait_until="networkidle")
    pg.wait_for_selector("#accountContent:visible", timeout=10000)
    checa("depois do perfil completo a agenda abre com o nome",
          pg.inner_text("#clientName") == "Maria Teste", pg.inner_text("#clientName"))
    pg.click("#logoutButton")
    pg.wait_for_url("**/login**", timeout=15000)
    checa("voltou para o login avisando que saiu", "notice=logout" in pg.url, pg.url)
    pg.goto(f"{BASE}/account", wait_until="networkidle")
    pg.wait_for_url("**/login**", timeout=10000)
    checa("agenda exige login de novo", "/login?next=/account" in pg.url, pg.url)
    revogado = ctx.request.get(f"{BASE}/api/account", headers={"Authorization": f"Bearer {token}"})
    checa("o token revogado devolve 401 na API", revogado.status == 401, revogado.status)

    print("7) integridade da tela")
    reais = [e for e in erros if "401" not in e and "Failed to load resource" not in e]
    checa("nenhum erro de JS", not reais, str(reais[:3]))
    pg.goto(f"{BASE}/login", wait_until="networkidle")
    ov = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    checa("sem rolagem horizontal", ov <= 0, ov)
    pg.screenshot(path="/tmp/login_formas_de_entrar.png", full_page=True)
    b.close()

print(f"\n{ok} verificações OK, {falhas} falhas")
raise SystemExit(1 if falhas else 0)
