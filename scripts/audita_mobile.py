#!/usr/bin/env python3
"""Auditoria de mobile do site — mede o que o olho não vê em cada largura.

Para cada página x largura: rolagem horizontal, elementos que estouram a viewport, alvos de
toque menores que 44 px (WCAG 2.5.5), campos com fonte < 16 px (o iOS dá zoom sozinho) e erros
de console/rede. Também salva um print por combinação em /tmp/mobile/.

    /home/vh450/.hermes/hermes-agent/venv/bin/python scripts/audita_mobile.py [--prints]
"""
from __future__ import annotations

import json
import pathlib
import random
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8100"
PASTA = pathlib.Path("/tmp/mobile")
LARGURAS = (("360x640", 360, 640), ("390x844", 390, 844), ("414x896", 414, 896), ("768x1024", 768, 1024))
PAGINAS = ("/", "/index-b.html", "/login", "/perfil", "/account", "/status.html", "/offline.html")
PAGINAS_SEM_MENU = ("/status.html", "/offline.html")   # páginas internas, sem navegação de site

MEDE = """(() => {
  const largura = window.innerWidth;
  const visivel = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return false;
    const s = getComputedStyle(el);
    return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
  };
  const estouros = [];
  const clipado = (el) => {
    let p = el.parentElement;
    while (p && p !== document.body) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === 'hidden' || ox === 'auto' || ox === 'scroll' || ox === 'clip') return true;
      p = p.parentElement;
    }
    return false;
  };
  document.querySelectorAll('body *').forEach((el) => {
    if (!visivel(el) || clipado(el)) return;
    const r = el.getBoundingClientRect();
    if (r.right > largura + 1 || r.left < -1) {
      estouros.push({ tag: el.tagName.toLowerCase(), cls: el.className && el.className.toString().slice(0, 40),
                      id: el.id, dir: r.left < -1 ? 'esquerda' : 'direita', extra: Math.round(Math.max(r.right - largura, -r.left)) });
    }
  });
  const alvos = [];
  document.querySelectorAll('a, button, input, select, textarea, [role=button]').forEach((el) => {
    if (!visivel(el)) return;
    const r = el.getBoundingClientRect();
    if (r.height < 44 || r.width < 44) {
      alvos.push({ tag: el.tagName.toLowerCase(), cls: el.className && el.className.toString().slice(0, 32),
                   id: el.id, w: Math.round(r.width), h: Math.round(r.height),
                   texto: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 26) });
    }
  });
  const zoom = [];
  document.querySelectorAll('input, select, textarea').forEach((el) => {
    if (!visivel(el)) return;
    const fs = parseFloat(getComputedStyle(el).fontSize);
    if (fs < 16) zoom.push({ id: el.id, fs });
  });
  const pequenos = [];
  document.querySelectorAll('p, li, small, dd, dt, span, em, b').forEach((el) => {
    if (!visivel(el) || !el.innerText || !el.innerText.trim()) return;
    const fs = parseFloat(getComputedStyle(el).fontSize);
    if (fs < 12) pequenos.push({ tag: el.tagName.toLowerCase(), fs, texto: el.innerText.trim().slice(0, 26) });
  });
  return { rolagem: document.documentElement.scrollWidth - largura, estouros: estouros.slice(0, 8),
           alvos: alvos.slice(0, 10), n_alvos: alvos.length, zoom, n_pequenos: pequenos.length, pequenos: pequenos.slice(0, 5) };
})()"""


def criar_conta(token_destino: dict) -> None:
    telefone = f"55139979{random.randint(10000, 99999)}"
    corpo = json.dumps({"nome": "Auditoria Mobile", "telefone": telefone, "pin": "9471",
                        "consentimento_lgpd": True}).encode()
    req = urllib.request.Request(BASE + "/api/auth/cadastro", data=corpo, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as resposta:
        token_destino["token"] = json.loads(resposta.read().decode())["token"]
    # completa o perfil para /account não redirecionar para /perfil
    req = urllib.request.Request(BASE + "/api/account/profile", method="PATCH",
                                 data=json.dumps({"nome": "Auditoria Mobile", "idade": 33}).encode())
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + token_destino["token"])
    urllib.request.urlopen(req, timeout=10).read()


def main() -> int:
    token: dict = {}
    criar_conta(token)
    PASTA.mkdir(parents=True, exist_ok=True)
    problemas = 0
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        for rotulo, largura, altura in LARGURAS:
            ctx = navegador.new_context(viewport={"width": largura, "height": altura}, device_scale_factor=2,
                                        locale="pt-BR", timezone_id="America/Sao_Paulo")
            pg = ctx.new_page()
            # sessão: o token vive em sessionStorage, então entra antes de navegar
            pg.goto(f"{BASE}/login", wait_until="domcontentloaded")
            pg.evaluate("(t) => sessionStorage.setItem('magno_token', t)", token["token"])
            for rota in PAGINAS:
                erros: list[str] = []
                pg.on("console", lambda m: erros.append(f"console: {m.text[:80]}") if m.type == "error" else None)
                pg.on("pageerror", lambda e: erros.append(f"pageerror: {str(e)[:80]}"))
                pg.on("requestfailed", lambda r: erros.append(f"falhou: {r.url[-50:]}"))
                pg.goto(BASE + rota, wait_until="networkidle")
                pg.wait_for_timeout(500)
                erros.clear()   # descarta requisições abortadas pela navegação anterior (fontes)
                dados = pg.evaluate(MEDE)
                print(f"\n=== {rota} @ {rotulo} ===")
                print(f"  rolagem horizontal: {dados['rolagem']}px")
                if dados["rolagem"] > 0 or dados["estouros"]:
                    problemas += 1
                    for e in dados["estouros"]:
                        print(f"    ESTOURA {e['extra']}px ({e['dir']}): <{e['tag']} class='{e['cls']}' id='{e['id']}'>")
                if dados["n_alvos"]:
                    print(f"  alvos de toque < 44px: {dados['n_alvos']}")
                    for a in dados["alvos"][:6]:
                        print(f"    {a['w']}x{a['h']} <{a['tag']} id='{a['id']}' class='{a['cls']}'> {a['texto']!r}")
                if dados["zoom"]:
                    print(f"  campos com fonte < 16px (iOS dá zoom): {dados['zoom']}")
                if dados["n_pequenos"]:
                    print(f"  textos < 12px: {dados['n_pequenos']} {dados['pequenos'][:3]}")
                reais = [e for e in erros if "favicon" not in e]
                if reais:
                    problemas += 1
                    print(f"  ERROS: {reais[:3]}")
                nome = rota.strip("/").replace(".html", "").replace("/", "") or "home"
                if "--prints" in sys.argv:
                    pg.screenshot(path=str(PASTA / f"{nome}-{rotulo}.png"), full_page=True)
                if largura <= 700 and rota not in PAGINAS_SEM_MENU and pg.locator("#menuBotao").count():
                    pg.click("#menuBotao")
                    pg.wait_for_timeout(250)
                    menu = pg.evaluate("""(() => {
                      const nav = document.querySelector('#nav');
                      const itens = [...nav.querySelectorAll('a, button')].filter((el) => el.offsetParent !== null);
                      return { aberto: nav.classList.contains('aberto') && getComputedStyle(nav).display !== 'none',
                               itens: itens.length,
                               altura: itens.map((el) => Math.round(el.getBoundingClientRect().height)),
                               rolagem: document.documentElement.scrollWidth - window.innerWidth };
                    })()""")
                    print(f"  menu do celular: aberto={menu['aberto']} itens={menu['itens']} alturas={menu['altura']} rolagem={menu['rolagem']}")
                    if not menu["aberto"] or not menu["itens"] or min(menu["altura"] or [0]) < 44 or menu["rolagem"] > 0:
                        problemas += 1
                        print("    PROBLEMA no menu do celular")
                    elif "--prints" in sys.argv and rota == "/account":
                        pg.screenshot(path=str(PASTA / f"menu-aberto-{rotulo}.png"))
                        pg.click("#menuBotao")   # fecha para não afetar a próxima página
                        pg.wait_for_timeout(200)
                if largura <= 700 and rota not in PAGINAS_SEM_MENU and pg.locator("#menuBotao").count() == 0:
                    problemas += 1
                    print("    PROBLEMA: sem botão de menu no celular")
                if "--prints" in sys.argv:
                    nome = rota.strip("/").replace(".html", "").replace("/", "") or "home"
                    pg.screenshot(path=str(PASTA / f"{nome}-{rotulo}.png"), full_page=True)
            ctx.close()
        navegador.close()
    print(f"\ncombinações com problema: {problemas} (de {len(PAGINAS) * len(LARGURAS)})")
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
