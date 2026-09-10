"""E2E das entradas alternativas: telefone+PIN e Google (a principal, por e-mail, tem
o seu próprio script: testa_email_login.py)."""
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8100"
ok, falhas = 0, 0


def checa(nome, cond, extra=""):
    global ok, falhas
    if cond:
        ok += 1
        print(f"  [OK] {nome}")
    else:
        falhas += 1
        print(f"  [FALHOU] {nome} {extra}")


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=2,
                        locale="pt-BR", timezone_id="America/Sao_Paulo")
    pg = ctx.new_page()
    erros = []
    pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: erros.append(str(e)))

    print("1) tela de entrar: e-mail como caminho principal")
    pg.goto(f"{BASE}/entrar.html", wait_until="networkidle")
    pg.wait_for_timeout(700)
    checa("campo de e-mail visível", not pg.eval_on_selector("#formEmail", "el => el.hidden"))
    checa("botão do Google presente", pg.locator("#btnGoogle").count() == 1)
    checa("atalho para senha", pg.locator("#btnModoSenha").count() == 1)
    checa("atalho para telefone e PIN", pg.locator("#btnModoTelefone").count() == 1)

    print("2) conta de balcão (telefone+PIN) criada pela API e login pela tela")
    criada = ctx.request.post(f"{BASE}/api/auth/cadastro", data={
        "nome": "Cliente do Balcão", "telefone": "(13) 99763-0784", "pin": "9471",
        "consentimento_lgpd": True,
    })
    checa("API criou a conta", criada.status == 200, criada.status)

    pg.click("#btnModoTelefone")
    pg.wait_for_timeout(400)
    checa("formulário de telefone aparece", pg.eval_on_selector("#formEntrarTelefone", "el => !el.hidden"))
    pg.fill("#loginTelefone", "(13) 99763-0784")
    pg.fill("#loginPin", "9471")
    pg.screenshot(path="/tmp/login_telefone.png")
    pg.click("#formEntrarTelefone button[type=submit]")
    pg.wait_for_url("**/conta.html", timeout=15000)
    pg.wait_for_timeout(900)
    checa("entrou com telefone e PIN", "Cliente do Balcão" in pg.inner_text("#nomeUsuario"))
    checa("etiqueta diz telefone + PIN", "pin" in pg.inner_text("#nomeUsuario").lower())

    print("3) PIN errado mostra erro em português")
    pg.click("#btnSair")
    pg.wait_for_url("**/entrar.html", timeout=15000)
    pg.wait_for_timeout(700)
    pg.click("#btnModoTelefone")
    pg.wait_for_timeout(300)
    pg.fill("#loginTelefone", "(13) 99763-0784")
    pg.fill("#loginPin", "9999")
    pg.click("#formEntrarTelefone button[type=submit]")
    pg.wait_for_timeout(1500)
    checa("erro genérico de credencial", "não conferem" in pg.inner_text("#aviso"), pg.inner_text("#aviso"))

    print("4) entrar com Google (consentimento de teste)")
    pg.click("#btnGoogle")
    pg.wait_for_timeout(1200)
    checa("foi para o consentimento", "_fake" in pg.url, pg.url)
    pg.click("text=Entrar como Maria Teste")
    pg.wait_for_url("**/conta.html*", timeout=20000)
    pg.wait_for_timeout(1200)
    nome = pg.inner_text("#nomeUsuario")
    checa("entrou pelo Google", "Maria Teste" in nome, nome)
    checa("etiqueta diz Google", "google" in nome.lower(), nome)
    checa("token não ficou na URL", "#entrar=" not in pg.url, pg.url)
    checa("pede o telefone (conta só-Google)", not pg.eval_on_selector("#formTelefone", "el => el.hidden"))
    pg.screenshot(path="/tmp/conta_google.png")

    print("5) completar o telefone pelo formulário da conta")
    pg.fill("#telefone", "(13) 98888-7777")
    pg.click("#formTelefone button[type=submit]")
    pg.wait_for_timeout(1600)
    checa("telefone salvo", "salvo" in pg.inner_text("#aviso").lower(), pg.inner_text("#aviso"))
    checa("formulário de telefone sumiu", pg.eval_on_selector("#formTelefone", "el => el.hidden"))
    checa("telefone aparece na conta", "(13) 98888-7777" in pg.inner_text("#detalheUsuario"))

    print("6) íntegridade")
    checa("nenhum erro de JS", len([e for e in erros if "401" not in e]) == 0, erros[:3])
    pg.goto(f"{BASE}/conta.html", wait_until="networkidle")
    pg.wait_for_timeout(600)
    ov = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    checa("sem rolagem horizontal", ov <= 0, ov)
    b.close()

print(f"\n=== {ok} OK, {falhas} FALHAS ===")
raise SystemExit(1 if falhas else 0)
