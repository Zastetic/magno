"""E2E do login por código de e-mail (provedor de e-mail em modo arquivo)."""
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8100"
INDICE = Path("/mnt/d/projetos_wsl/magno/logs/emails/enviados.jsonl")
ok, falhas = 0, 0


def checa(nome, cond, extra=""):
    global ok, falhas
    if cond:
        ok += 1
        print(f"  [OK] {nome}")
    else:
        falhas += 1
        print(f"  [FALHOU] {nome} {extra}")


def esperar_codigo(email, timeout=10):
    """Lê o código que o 'provedor' de desenvolvimento gravou."""
    fim = time.time() + timeout
    alvo = email.lower()
    while time.time() < fim:
        if INDICE.exists():
            for linha in reversed(INDICE.read_text(encoding="utf-8").splitlines()):
                if not linha.strip():
                    continue
                registro = json.loads(linha)
                if registro["para"] == alvo:
                    return registro["codigo"]
        time.sleep(0.3)
    raise AssertionError(f"nenhum código para {alvo}")


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=2,
                        locale="pt-BR", timezone_id="America/Sao_Paulo")
    pg = ctx.new_page()
    erros = []
    pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: erros.append(str(e)))

    print("1) tela de entrar (e-mail primeiro)")
    pg.goto(f"{BASE}/entrar.html", wait_until="networkidle")
    pg.wait_for_timeout(700)
    checa("pede o e-mail", pg.locator("#email").count() == 1)
    checa("formulário de código começa escondido", pg.eval_on_selector("#formCodigo", "el => el.hidden"))
    checa("não existe mais aba de 'criar conta'", pg.locator("#abaCriar").count() == 0)
    pg.screenshot(path="/tmp/email_login_1.png")

    print("2) pedir o código")
    email = f"e2e.magno{int(time.time())}@exemplo.test"
    pg.fill("#email", email)
    pg.click("#formEmail button[type=submit]")
    pg.wait_for_selector("#formCodigo:not([hidden])", timeout=15000)
    pg.wait_for_timeout(600)
    checa("passou para o passo do código", pg.eval_on_selector("#formCodigo", "el => !el.hidden"))
    checa("mostra para qual e-mail foi", email in pg.inner_text("#emailEnviado"))
    checa("avisa que enviou", "Código enviado" in pg.inner_text("#aviso"), pg.inner_text("#aviso"))
    codigo = esperar_codigo(email)
    checa("código de 5 dígitos gerado", len(codigo) == 5 and codigo.isdigit(), codigo)
    pg.screenshot(path="/tmp/email_login_2.png")

    print("3) código errado é recusado")
    errado = "00000" if codigo != "00000" else "11111"
    pg.fill("#codigo", errado)
    pg.click("#formCodigo button[type=submit]")
    pg.wait_for_timeout(1500)
    checa("mostra erro em português", "não confere" in pg.inner_text("#aviso"), pg.inner_text("#aviso"))
    checa("continua na tela de entrar", "/entrar.html" in pg.url)

    print("4) código certo entra")
    pg.fill("#codigo", codigo)
    pg.click("#formCodigo button[type=submit]")
    pg.wait_for_url("**/conta.html", timeout=15000)
    pg.wait_for_timeout(900)
    nome = pg.inner_text("#nomeUsuario")
    detalhe = pg.inner_text("#detalheUsuario")
    checa("entrou na conta", "João" in nome or email.split("@")[0].replace(".", " ").title() in nome, nome)
    checa("etiqueta diz 'código por e-mail'", "código por e-mail" in nome.lower() or "codigo por e-mail" in nome.lower(), nome)
    checa("mostra o e-mail", email in detalhe, detalhe)
    checa("pede o telefone (a loja precisa do número)",
          not pg.eval_on_selector("#formTelefone", "el => el.hidden"))
    checa("oferece criar senha (opcional)", pg.locator("#formSenha").count() == 1)
    pg.screenshot(path="/tmp/email_conta.png")

    print("5) criar a senha opcional e entrar com ela")
    pg.fill("#novaSenha", "navalha2026")
    pg.click("#btnSalvarSenha")
    pg.wait_for_timeout(1600)
    checa("confirma que salvou a senha", "Senha salva" in pg.inner_text("#aviso"), pg.inner_text("#aviso"))
    pg.click("#btnSair")
    pg.wait_for_url("**/entrar.html", timeout=15000)
    pg.wait_for_timeout(700)
    pg.click("#btnModoSenha")
    pg.wait_for_timeout(400)
    checa("modo senha aparece", pg.eval_on_selector("#formEntrarSenha", "el => !el.hidden"))
    pg.fill("#entrarEmailSenha", email)
    pg.fill("#entrarSenha", "navalha2026")
    pg.click("#formEntrarSenha button[type=submit]")
    pg.wait_for_url("**/conta.html", timeout=15000)
    pg.wait_for_timeout(800)
    checa("entrou com e-mail + senha", email in pg.inner_text("#detalheUsuario"))
    pg.screenshot(path="/tmp/email_login_senha.png")

    print("6) o site cumprimenta quem está logado")
    pg.goto(f"{BASE}/", wait_until="networkidle")
    pg.wait_for_timeout(1200)
    checa("cabeçalho com o nome", pg.inner_text("#linkConta").startswith("Olá,"), pg.inner_text("#linkConta"))

    print("7) integridade")
    checa("nenhum erro de console inesperado",
          len([e for e in erros if "401" not in e]) == 0, erros[:3])
    ov = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    checa("sem rolagem horizontal", ov <= 0, ov)

    print("8) mobile")
    ctx2 = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                         locale="pt-BR", timezone_id="America/Sao_Paulo")
    m = ctx2.new_page()
    m.goto(f"{BASE}/entrar.html", wait_until="networkidle")
    m.wait_for_timeout(600)
    m.fill("#email", "mobile@exemplo.test")
    m.click("#formEmail button[type=submit]")
    m.wait_for_selector("#formCodigo:not([hidden])", timeout=15000)
    m.wait_for_timeout(500)
    ov_m = m.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    checa("mobile sem rolagem horizontal", ov_m <= 0, ov_m)
    m.screenshot(path="/tmp/email_login_mobile.png")

    b.close()

print(f"\n=== {ok} OK, {falhas} FALHAS ===")
raise SystemExit(1 if falhas else 0)
