#!/usr/bin/env python3
"""E2E do login por código de 5 dígitos no e-mail — sobe um servidor descartável próprio.

Nada é enviado para fora: o servidor de teste roda em `MAGNO_EMAIL_MODO=arquivo` (porta 8101,
banco em /tmp) e o código fica em logs/emails/enviados.jsonl, de onde este script o lê.
Assim o teste não depende do provedor real (Resend) nem manda e-mail para ninguém.

    /home/vh450/.hermes/hermes-agent/venv/bin/python scripts/testa_email_login.py
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

RAIZ = pathlib.Path(__file__).resolve().parent.parent
PORTA = 8123          # 8100 é o servidor real; 8101 é o proxy do Mistral (outro projeto)
BASE = f"http://127.0.0.1:{PORTA}"
BANCO = pathlib.Path("/tmp/magno-teste-email.db")
INDICE = RAIZ / "logs" / "emails" / "enviados.jsonl"
ok = falhas = 0


def checa(nome: str, condicao: bool, extra: str = "") -> None:
    global ok, falhas
    if condicao:
        ok += 1
        print(f"  [OK] {nome}")
    else:
        falhas += 1
        print(f"  [FALHOU] {nome} {extra}")


def linhas_do_indice() -> int:
    if not INDICE.exists():
        return 0
    return len(INDICE.read_text(encoding="utf-8").splitlines())


def esperar_codigo(email: str, a_partir_de: int, timeout=15) -> str:
    """Lê o código que o provedor `arquivo` gravou depois do início deste teste."""
    fim = time.time() + timeout
    alvo = email.lower()
    while time.time() < fim:
        if INDICE.exists():
            for linha in reversed(INDICE.read_text(encoding="utf-8").splitlines()[a_partir_de:]):
                if not linha.strip():
                    continue
                registro = json.loads(linha)
                if registro["para"] == alvo:
                    return registro["codigo"]
        time.sleep(0.3)
    raise AssertionError(f"nenhum código novo para {alvo}")


def subir_servidor() -> subprocess.Popen:
    for sufixo in ("", "-wal", "-shm"):
        try:
            os.remove(str(BANCO) + sufixo)
        except OSError:
            pass
    ambiente = {**os.environ, "MAGNO_DB": str(BANCO), "MAGNO_PORTA": str(PORTA),
                "MAGNO_EMAIL_MODO": "arquivo", "MAGNO_URL_BASE": BASE,
                "GOOGLE_FAKE": "1", "MAGNO_SEED_DEV": "1", "PYTHONUNBUFFERED": "1"}
    processo = subprocess.Popen(
        [str(RAIZ / "venv" / "bin" / "uvicorn"), "server.main:app", "--host", "127.0.0.1",
         "--port", str(PORTA)], cwd=RAIZ, env=ambiente,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(80):
        try:
            with urllib.request.urlopen(f"{BASE}/api/saude", timeout=3) as resposta:
                if json.loads(resposta.read().decode())["ok"]:
                    return processo
        except (urllib.error.URLError, OSError, KeyError, ValueError):
            time.sleep(0.5)
    processo.terminate()
    raise SystemExit("o servidor de teste não subiu na 8101")


servidor = subir_servidor()
inicio_indice = linhas_do_indice()
email = f"e2e.magno{int(time.time())}@exemplo.test"

try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=2,
                            locale="pt-BR", timezone_id="America/Sao_Paulo")
        pg = ctx.new_page()
        erros: list[str] = []
        pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: erros.append(str(e)))

        print("1) tela de entrar (e-mail primeiro)")
        pg.goto(f"{BASE}/login", wait_until="networkidle")
        checa("pede o e-mail", pg.locator("#email").count() == 1)
        checa("formulário de código começa escondido", pg.eval_on_selector("#formCodigo", "el => el.hidden"))
        checa("não existe mais aba de 'criar conta'", pg.locator("#abaCriar").count() == 0)

        print("2) pedir o código")
        pg.fill("#email", email)
        pg.click("#formEmail button[type=submit]")
        pg.wait_for_selector("#formCodigo:not([hidden])", timeout=15000)
        checa("passou para o passo do código", pg.eval_on_selector("#formCodigo", "el => !el.hidden"))
        checa("mostra para qual e-mail foi", email in pg.inner_text("#emailEnviado"))
        codigo = esperar_codigo(email, inicio_indice)
        checa("código de 5 dígitos gerado", len(codigo) == 5 and codigo.isdigit(), codigo)
        with urllib.request.urlopen(f"{BASE}/api/saude", timeout=5) as resposta:
            saude = json.loads(resposta.read().decode())
        checa("o servidor de teste está em modo arquivo (nada sai para a internet)",
              saude["login"]["email_modo"] == "arquivo", saude["login"]["email_modo"])

        print("3) código errado é recusado e não cria sessão")
        errado = "00000" if codigo != "00000" else "11111"
        pg.fill("#codigo", errado)
        pg.click("#formCodigo button[type=submit]")
        pg.wait_for_timeout(1500)
        checa("mostra erro em português", "não confere" in pg.inner_text("#aviso"), pg.inner_text("#aviso"))
        checa("continua na tela de entrar", "/login" in pg.url, pg.url)
        checa("sem token guardado depois do erro",
              not pg.evaluate("sessionStorage.getItem('magno_token')"))

        print("4) código certo entra e cai no /perfil (conta nova não tem idade)")
        pg.fill("#codigo", codigo)
        pg.click("#formCodigo button[type=submit]")
        pg.wait_for_url("**/perfil", timeout=15000)
        pg.wait_for_selector("#caixaPerfil:visible")
        checa("conta criada pelo e-mail abriu o /perfil", pg.url.endswith("/perfil"), pg.url)
        checa("passo 1 pede o nome", "Como você quer ser chamado?" in pg.inner_text("#tituloPerfil"))
        checa("a idade ainda está escondida", pg.is_hidden("#formIdade"))

        print("5) nome -> idade -> agenda")
        pg.fill("#nome", "Cliente do E-mail")
        pg.click("#formNome button[type=submit]")
        pg.wait_for_selector("#formIdade:visible")
        pg.fill("#idade", "30")
        pg.click("#formIdade button[type=submit]")
        pg.wait_for_url("**/account", timeout=15000)
        pg.wait_for_selector("#accountContent:visible", timeout=10000)
        checa("agenda aberta depois do perfil", pg.url.endswith("/account"), pg.url)
        checa("o nome aparece na tela de agendamento",
              pg.inner_text("#clientName") == "Cliente do E-mail", pg.inner_text("#clientName"))
        checa("o e-mail virou a identidade da conta",
              pg.inner_text("#clientSubtext").startswith("30 anos"), pg.inner_text("#clientSubtext"))
        pg.screenshot(path="/tmp/email_login_conta.png", full_page=True)

        print("6) mobile")
        m = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                          locale="pt-BR").new_page()
        m.goto(f"{BASE}/login", wait_until="networkidle")
        ov = m.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        checa("mobile sem rolagem horizontal", ov <= 0, ov)

        print("7) integridade")
        reais = [e for e in erros if "401" not in e and "Failed to load resource" not in e]
        checa("nenhum erro de JS", not reais, str(reais[:3]))
        b.close()
finally:
    servidor.terminate()
    servidor.wait(timeout=15)

print(f"\n{ok} verificações OK, {falhas} falhas")
raise SystemExit(1 if falhas else 0)
