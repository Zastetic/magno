"""Prova que as animações existem e se movem — e que continuam corretas em print e reduced-motion."""
import time
from PIL import Image
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
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2,
                        locale="pt-BR", timezone_id="America/Sao_Paulo")
    pg = ctx.new_page()
    erros = []
    pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.goto(f"{BASE}/", wait_until="networkidle")
    pg.wait_for_timeout(600)

    print("1) o poste gira (listras mudam de posição)")
    pos1 = pg.eval_on_selector(".trilho", "el => getComputedStyle(el).backgroundPosition")
    nome = pg.eval_on_selector(".trilho", "el => getComputedStyle(el).animationName")
    pg.wait_for_timeout(1300)
    pos2 = pg.eval_on_selector(".trilho", "el => getComputedStyle(el).backgroundPosition")
    checa("animação declarada no CSS", nome == "girar-poste", nome)
    checa("listras se deslocam com o tempo", pos1 != pos2, f"{pos1} -> {pos2}")
    print(f"      {pos1}  ->  {pos2}")

    print("2) o letreiro corre")
    t1 = pg.eval_on_selector(".letreiro-faixa", "el => getComputedStyle(el).transform")
    pg.wait_for_timeout(1500)
    t2 = pg.eval_on_selector(".letreiro-faixa", "el => getComputedStyle(el).transform")
    checa("faixa do letreiro se desloca", t1 != t2, f"{t1} -> {t2}")
    palavras = pg.eval_on_selector_all(".letreiro span", "els => els.map(e => e.textContent)")
    checa("letreiro tem conteúdo duplicado (loop sem emenda)", len(palavras) == 16, len(palavras))
    print(f"      {palavras[:4]} ... ({len(palavras)} itens)")

    print("3) o ponteiro anda com a hora real da loja")
    a1 = pg.eval_on_selector(".ponteiro .agulha", "el => el.style.transform")
    pg.wait_for_timeout(2200)
    a2 = pg.eval_on_selector(".ponteiro .agulha", "el => el.style.transform")
    checa("agulha avança", a1 != a2, f"{a1} -> {a2}")
    graus1 = float(a1.replace("rotate(", "").replace("deg)", ""))
    graus2 = float(a2.replace("rotate(", "").replace("deg)", ""))
    checa("agulha anda em sentido horário (graus aumentam)", graus2 > graus1, f"{graus1} -> {graus2}")
    print(f"      {a1} -> {a2}")

    print("4) revelar ao rolar usa só transform (nada invisível)")
    sobe = pg.eval_on_selector_all(".sobe", "els => els.length")
    invisivel = pg.evaluate("""(() => {
        let n = 0;
        document.querySelectorAll('main *').forEach(el => {
            const cs = getComputedStyle(el);
            if (parseFloat(cs.opacity) < 1) n++;
        });
        return n;
    })()""")
    checa("blocos abaixo da dobra prontos para subir", sobe > 0, sobe)
    checa("nenhum elemento com opacity < 1 (print sai inteiro)", invisivel == 0, invisivel)
    pg.screenshot(path="/tmp/mov_hero.png")
    pg.screenshot(path="/tmp/mov_pagina.png", full_page=True)

    print("5) quadros para provar o movimento (recortes em 3 tempos)")
    caixa_trilho = pg.eval_on_selector(".trilho", "el => { const r = el.getBoundingClientRect(); return {x:r.x, y:r.y, w:r.width, h:r.height}; }")
    caixa_letreiro = pg.eval_on_selector(".letreiro", "el => { const r = el.getBoundingClientRect(); return {x:0, y:r.y, w:1440, h:r.height}; }")
    for i in range(3):
        if i:
            pg.wait_for_timeout(1400)
        pg.screenshot(path=f"/tmp/mov_quadro_{i}.png", clip={
            "x": 0, "y": max(0, caixa_letreiro["y"] - caixa_trilho["h"] - 8),
            "width": 1440,
            "height": caixa_letreiro["h"] + caixa_trilho["h"] + 16,
        })

    print("6) print/PDF continua completo")
    pg.emulate_media(media="print")
    pg.wait_for_timeout(1400)   # espera a transição de 0.7s terminar antes de medir
    transform_print = pg.eval_on_selector_all(".sobe", "els => els.map(e => getComputedStyle(e).transform).filter(t => t !== 'none').length")
    anim_print = pg.eval_on_selector(".trilho", "el => getComputedStyle(el).animationName")
    checa("nada deslocado no print", transform_print == 0, transform_print)
    checa("animação do poste desligada no print", anim_print == "none", anim_print)
    pg.emulate_media(media="screen")

    print("7) reduced-motion respeitado")
    ctx2 = b.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce",
                         locale="pt-BR", timezone_id="America/Sao_Paulo")
    pg2 = ctx2.new_page()
    pg2.goto(f"{BASE}/", wait_until="networkidle")
    pg2.wait_for_timeout(1200)
    anim2 = pg2.eval_on_selector(".trilho", "el => getComputedStyle(el).animationName")
    letreiro2 = pg2.eval_on_selector(".letreiro-faixa", "el => getComputedStyle(el).animationName")
    sobe2 = pg2.eval_on_selector_all(".sobe", "els => els.length")
    checa("poste parado com reduced-motion", anim2 == "none", anim2)
    checa("letreiro parado com reduced-motion", letreiro2 == "none", letreiro2)
    checa("sem reveal com reduced-motion", sobe2 == 0, sobe2)

    print("8) integridade")
    checa("nenhum erro de console", len(erros) == 0, erros[:3])
    ov = pg.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    checa("sem rolagem horizontal", ov <= 0, ov)
    b.close()

# comparação visual: 3 recortes empilhados
quads = [Image.open(f"/tmp/mov_quadro_{i}.png") for i in range(3)]
larg = quads[0].width
total = sum(q.height for q in quads) + 20 * (len(quads) - 1)
comparacao = Image.new("RGB", (larg, total), (20, 16, 11))
y = 0
for q in quads:
    comparacao.paste(q.convert("RGB"), (0, y))
    y += q.height + 20
comparacao.save("/tmp/mov_comparacao.png")
print("comparação de quadros:", comparacao.size)

print(f"\n=== {ok} OK, {falhas} FALHAS ===")
raise SystemExit(1 if falhas else 0)
