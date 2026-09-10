"""E2E do login: criar conta, sair, entrar, e entrar com Google (provedor falso)."""
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

    print("1) tela de login")
    pg.goto(f"{BASE}/entrar.html", wait_until="networkidle")
    pg.wait_for_timeout(600)
    checa("título da tela", "Entrar" in pg.title(), pg.title())
    checa("botão do Google presente", pg.locator("#btnGoogle").count() == 1)
    checa("botão do Google ATIVO (provedor de teste ligado)",
          "desligado" not in (pg.get_attribute("#btnGoogle", "class") or ""))
    pg.screenshot(path="/tmp/login_tela.png")

    print("2) criar conta com telefone + PIN")
    pg.click("#abaCriar")
    pg.wait_for_timeout(300)
    checa("formulário de criar conta apareceu", pg.eval_on_selector("#formCriar", "el => !el.hidden"))
    pg.fill("#criarNome", "João da Silva")
    pg.fill("#criarTelefone", "(13) 99763-0784")
    pg.fill("#criarPin", "9471")
    pg.check("#criarConsentimento")
    pg.screenshot(path="/tmp/login_criar.png")
    pg.click("#formCriar button[type=submit]")
    pg.wait_for_url("**/conta.html", timeout=15000)
    pg.wait_for_timeout(900)
    checa("caiu na área da conta", "/conta.html" in pg.url, pg.url)
    nome = pg.inner_text("#nomeUsuario")
    checa("mostra o nome do cliente", "João da Silva" in nome, nome)
    detalhe = pg.inner_text("#detalheUsuario")
    checa("mostra o telefone formatado", "(13) 99763-0784" in detalhe, detalhe)
    checa("etiqueta diz que entrou por telefone + PIN", "pin" in nome.lower(), nome)
    checa("não pede telefone (conta já tem)", pg.eval_on_selector("#formTelefone", "el => el.hidden"))
    pg.screenshot(path="/tmp/conta_cliente.png")

    print("3) sair e entrar de novo")
    pg.click("#btnSair")
    pg.wait_for_url("**/entrar.html", timeout=15000)
    pg.wait_for_timeout(700)
    checa("voltou para a tela de entrar", "/entrar.html" in pg.url, pg.url)
    pg.fill("#loginTelefone", "13997630784")
    pg.fill("#loginPin", "9471")
    pg.click("#formEntrar button[type=submit]")
    pg.wait_for_url("**/conta.html", timeout=15000)
    pg.wait_for_timeout(800)
    checa("entrou com telefone + PIN", "João da Silva" in pg.inner_text("#nomeUsuario"))

    print("4) PIN errado mostra erro em português")
    pg.click("#btnSair")
    pg.wait_for_url("**/entrar.html", timeout=15000)
    pg.fill("#loginTelefone", "13997630784")
    pg.fill("#loginPin", "9999")
    pg.click("#formEntrar button[type=submit]")
    pg.wait_for_timeout(1200)
    aviso = pg.inner_text("#aviso")
    checa("erro de credencial genérico", "não conferem" in aviso, aviso)
    pg.screenshot(path="/tmp/login_erro.png")

    print("5) entrar com Google (consentimento de teste)")
    pg.click("#btnGoogle")
    pg.wait_for_timeout(1200)
    checa("foi para a tela de consentimento", "_fake" in pg.url, pg.url)
    pg.screenshot(path="/tmp/login_google_teste.png")
    pg.click("text=Entrar como João Teste")
    pg.wait_for_url("**/conta.html*", timeout=20000)
    pg.wait_for_timeout(1200)
    nome_g = pg.inner_text("#nomeUsuario")
    detalhe_g = pg.inner_text("#detalheUsuario")
    checa("voltou logado pelo Google", "João Teste" in nome_g, nome_g)
    checa("etiqueta diz Google", "google" in nome_g.lower(), nome_g)
    checa("e-mail do Google aparece", "joao.teste@exemplo.test" in detalhe_g, detalhe_g)
    checa("token não ficou na URL", "#entrar=" not in pg.url, pg.url)
    checa("pede o telefone (conta só-Google)",
          not pg.eval_on_selector("#formTelefone", "el => el.hidden"))
    pg.screenshot(path="/tmp/conta_google.png")

    print("6) completar o telefone")
    pg.fill("#telefone", "(13) 98888-7777")
    pg.click("#formTelefone button[type=submit]")
    pg.wait_for_timeout(1500)
    aviso_ok = pg.inner_text("#aviso")
    checa("telefone salvo com confirmação", "salvo" in aviso_ok.lower(), aviso_ok)
    checa("formulário de telefone sumiu", pg.eval_on_selector("#formTelefone", "el => el.hidden"))
    checa("telefone aparece no cabeçalho da conta", "(13) 98888-7777" in pg.inner_text("#detalheUsuario"))
    pg.screenshot(path="/tmp/conta_google_completa.png")

    print("7) o site passa a cumprimentar quem está logado")
    pg.goto(f"{BASE}/", wait_until="networkidle")
    pg.wait_for_timeout(1200)
    link = pg.inner_text("#linkConta")
    checa("cabeçalho mostra o nome", link.startswith("Olá,"), link)
    checa("e leva para a conta", "conta.html" in pg.get_attribute("#linkConta", "href"))

    print("8) integridade das telas")
    for pagina in ("/entrar.html", "/conta.html"):
        pg.goto(BASE + pagina, wait_until="networkidle")
        pg.wait_for_timeout(400)
        ov = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        checa(f"sem rolagem horizontal em {pagina}", ov <= 0, ov)
    # o login com PIN errado da etapa 4 gera um 401 esperado — o resto tem que estar limpo
    inesperados = [e for e in erros if "401" not in e]
    checa("nenhum erro de console inesperado", len(inesperados) == 0, inesperados[:3])
    checa("o 401 do PIN errado foi o único registro", len(erros) <= 1, erros)

    print("9) mobile")
    ctx2 = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                         locale="pt-BR", timezone_id="America/Sao_Paulo")
    m = ctx2.new_page()
    m.goto(f"{BASE}/entrar.html", wait_until="networkidle")
    m.wait_for_timeout(600)
    ov_m = m.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    checa("login sem rolagem horizontal no celular", ov_m <= 0, ov_m)
    m.screenshot(path="/tmp/login_mobile.png")

    b.close()

print(f"\n=== {ok} OK, {falhas} FALHAS ===")
raise SystemExit(1 if falhas else 0)
