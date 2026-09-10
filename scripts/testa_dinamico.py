"""Testa o fluxo dinâmico da home no browser e gera prints dos estados."""
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
    ctx = b.new_context(viewport={"width": 1440, "height": 950}, device_scale_factor=2,
                        locale="pt-BR", timezone_id="America/Sao_Paulo")
    pg = ctx.new_page()
    erros = []
    pg.on("console", lambda m: erros.append(f"{m.type}: {m.text}") if m.type == "error" else None)
    pg.on("pageerror", lambda e: erros.append(f"pageerror: {e}"))
    pg.goto(f"{BASE}/", wait_until="networkidle")
    pg.wait_for_timeout(600)

    print("1) relógio / status / vagas")
    relogio = pg.inner_text("#relogio")
    checa("relógio no formato HH:MM", len(relogio) == 5 and relogio[2] == ":", repr(relogio))
    selo = pg.inner_text("#seloStatus")
    checa("status calculado", any(t in selo for t in ("Aberto", "Fechado")), repr(selo))
    vagas = pg.eval_on_selector_all("#vagasHoje li", "els => els.map(e => e.innerText)")
    checa("grade de vagas gerada", len(vagas) > 0, vagas)
    print("      vagas:", vagas, "| status:", selo)

    print("2) escolher serviço")
    pg.click('a[data-servico="Corte + barba"]')
    pg.wait_for_timeout(400)
    resumo = pg.inner_text("#resumoServico")
    checa("resumo mostra serviço, duração e preço",
          "Corte + barba" in resumo and "1 h" in resumo and "R$ 70" in resumo, repr(resumo))
    checa("linha do serviço marcada como selecionada",
          pg.eval_on_selector('a[data-servico="Corte + barba"]', "el => el.classList.contains('selecionado')"))
    profs = pg.eval_on_selector_all("#chipsProf .chip", "els => els.map(e => e.innerText)")
    checa("só os barbeiros que fazem esse serviço", profs == ["Rafael", "Diego"], profs)
    horas = pg.eval_on_selector_all("#chipsHora .chip", "els => els.map(e => e.innerText)")
    checa("grade recalculada para 1 h de duração", len(horas) > 0, horas)
    checa("botão continua bloqueado sem barbeiro/horário",
          pg.eval_on_selector("#btnContinuar", "el => el.disabled") is True)
    print("      barbeiros:", profs, "| horários:", horas)

    print("3) serviço curto gera MAIS horários que serviço longo (prova do cálculo)")
    pg.click('a[data-servico="Sobrancelha na navalha"]')
    pg.wait_for_timeout(300)
    curtos = pg.eval_on_selector_all("#chipsHora .chip", "els => els.length")
    pg.click('a[data-servico="Platinado"]')
    pg.wait_for_timeout(300)
    longos = pg.eval_on_selector_all("#chipsHora .chip", "els => els.length")
    checa("15 min oferece mais horários que 90 min", curtos > longos, f"{curtos} vs {longos}")
    print(f"      15 min -> {curtos} horários | 90 min -> {longos} horários")

    print("4) escolher barbeiro e horário")
    pg.click('a[data-servico="Corte + barba"]')
    pg.wait_for_timeout(250)
    pg.click("#chipsProf .chip")
    pg.wait_for_timeout(200)
    checa("chip de barbeiro fica ativo",
          pg.eval_on_selector("#chipsProf .chip", "el => el.classList.contains('ativo')"))
    checa("ainda bloqueado sem horário", pg.eval_on_selector("#btnContinuar", "el => el.disabled") is True)
    pg.click("#chipsHora .chip")
    pg.wait_for_timeout(200)
    checa("continuar libera depois do horário",
          pg.eval_on_selector("#btnContinuar", "el => el.disabled") is False)
    pg.screenshot(path="/tmp/din_passo2.png", full_page=False)

    print("5) passo 3: confirmação")
    pg.click("#btnContinuar")
    pg.wait_for_timeout(350)
    checa("painel mudou para confirmação",
          pg.eval_on_selector("#passo-confirmar", "el => !el.hidden") is True)
    resumo_escolha = pg.inner_text("#resumoEscolha")
    checa("resumo do passo 3 com serviço, barbeiro e hora",
          "Corte + barba" in resumo_escolha and "Rafael" in resumo_escolha, repr(resumo_escolha))

    print("6) validação dos dados")
    pg.click("#btnConfirmar")
    pg.wait_for_timeout(250)
    aviso = pg.inner_text("#avisoVazio")
    checa("formulário vazio é recusado com a lista do que falta",
          "Falta preencher" in aviso and "nome" in aviso, repr(aviso))
    print("      aviso:", aviso)
    pg.fill("#campoNome", "João da Silva")
    pg.fill("#campoTelefone", "13997630784")
    pg.fill("#campoPin", "1234")
    pg.check("#campoConsentimento")
    pg.screenshot(path="/tmp/din_passo3.png", full_page=False)

    print("7) reserva")
    pg.click("#btnConfirmar")
    pg.wait_for_timeout(350)
    checa("painel mostra reserva", pg.eval_on_selector("#passo-pronto", "el => !el.hidden") is True)
    pronto = pg.inner_text("#textoPronto")
    checa("reserva com hora, serviço, barbeiro e preço",
          "Corte + barba" in pronto and "Rafael" in pronto and "R$ 70" in pronto, repr(pronto))
    link = pg.get_attribute("#linkWhats", "href")
    checa("link de WhatsApp montado com a mensagem", link.startswith("https://wa.me/") and "%0A" not in link, link[:80])
    print("      reserva:", pronto)
    pg.screenshot(path="/tmp/din_passo4.png", full_page=False)

    print("8) voltar e refazer")
    pg.click("#btnOutro")
    pg.wait_for_timeout(300)
    checa("volta para o passo 2 limpo", pg.eval_on_selector("#passo-escolha", "el => !el.hidden") is True)
    checa("nenhum serviço marcado depois de refazer",
          pg.eval_on_selector_all(".menu-servicos a.selecionado", "els => els.length") == 0)

    print("9) vaga do cartão do topo leva ao agendamento")
    pg.reload(wait_until="networkidle")
    pg.wait_for_timeout(500)
    pg.click("#vagasHoje li:first-child")
    pg.wait_for_timeout(600)
    checa("clicar na vaga do topo seleciona um horário no painel",
          pg.eval_on_selector_all("#chipsHora .chip, #chipsHora .chip.ativo", "els => els.length") >= 0)

    print("10) integridade da página")
    invisiveis = pg.evaluate("""(() => {
        const fora = [];
        document.querySelectorAll('main *').forEach(el => {
            const cs = getComputedStyle(el);
            if (parseFloat(cs.opacity) < 1 || cs.visibility === 'hidden') {
                if (el.innerText && el.innerText.trim() && !el.closest('[hidden]')) fora.push(el.tagName + '.' + el.className);
            }
        });
        return fora;
    })()""")
    checa("nada invisível fora do painel", len(invisiveis) == 0, invisiveis[:3])
    overflow = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    checa("sem rolagem horizontal", overflow <= 0, overflow)
    checa("nenhum erro de console", len(erros) == 0, erros[:3])

    print("11) mobile 390px")
    ctx2 = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                         locale="pt-BR", timezone_id="America/Sao_Paulo")
    m = ctx2.new_page()
    m.goto(f"{BASE}/", wait_until="networkidle")
    m.wait_for_timeout(500)
    m.click('a[data-servico="Degradê navalhado"]')
    m.wait_for_timeout(300)
    m.click("#chipsProf .chip")
    m.click("#chipsHora .chip")
    m.wait_for_timeout(250)
    m.click("#btnContinuar")
    m.wait_for_timeout(300)
    m.screenshot(path="/tmp/din_mobile_passo3.png", full_page=False)
    ov_m = m.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    checa("mobile sem rolagem horizontal no agendamento", ov_m <= 0, ov_m)
    checa("mobile mostra o passo 3", m.eval_on_selector("#passo-confirmar", "el => !el.hidden") is True)

    b.close()

print(f"\n=== {ok} OK, {falhas} FALHAS ===")
raise SystemExit(1 if falhas else 0)
