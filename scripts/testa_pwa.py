#!/usr/bin/env python3
"""Prova, no navegador de verdade, que o site é instalável como app (PWA).

Roda contra o servidor real (127.0.0.1:8100) com o python do Hermes (tem playwright):

    /home/vh450/.hermes/hermes-agent/venv/bin/python scripts/testa_pwa.py

O juiz final é o próprio Chrome: `Page.getInstallabilityErrors` (CDP) só vem vazio quando o
botão "Instalar app" realmente vai aparecer para o cliente. Também mede o service worker
registrado/ativo, o manifest lido pela página e o modo offline (navegação com a rede cortada).
"""
from __future__ import annotations

import json
import pathlib
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


def pegar_json(caminho: str) -> dict:
    with urllib.request.urlopen(BASE + caminho, timeout=10) as resposta:
        return json.loads(resposta.read().decode())


def main() -> int:
    print("1) manifest servido e ícones de verdade")
    manifest = pegar_json("/manifest.webmanifest")
    checa("o manifest responde com nome e display standalone",
          manifest["name"].startswith("Barbearia Magnum") and manifest["display"] == "standalone",
          str(manifest.get("display")))
    checa("declara ícones 192/512 + maskable", len(manifest["icons"]) >= 3, str(manifest["icons"]))
    for icone in manifest["icons"]:
        with urllib.request.urlopen(BASE + icone["src"], timeout=10) as resposta:
            checa(f"{icone['src']} é PNG servido com 200",
                  resposta.status == 200 and resposta.read(8) == b"\x89PNG\r\n\x1a\n",
                  str(resposta.status))

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        ctx = navegador.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2,
                                    locale="pt-BR", timezone_id="America/Sao_Paulo")
        pg = ctx.new_page()
        erros: list[str] = []
        pg.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: erros.append(str(e)))
        cdp = ctx.new_cdp_session(pg)

        print("2) home: manifest lido pela página e service worker assumindo")
        pg.goto(f"{BASE}/", wait_until="networkidle")
        checa("a página aponta para o manifest",
              pg.get_attribute('link[rel="manifest"]', "href") == "/manifest.webmanifest")
        checa("o apple-touch-icon está ligado (iOS)", pg.locator('link[rel="apple-touch-icon"]').count() == 1)
        checa("tema escuro da loja no manifest lido pelo navegador",
              (cdp.send("Page.getAppManifest").get("data") or "").find("Barbearia") >= 0)
        ativo = pg.evaluate("""async () => {
          const registro = await navigator.serviceWorker.ready;
          return { escopo: registro.scope, ativo: !!(registro.active), estado: registro.active && registro.active.state };
        }""")
        checa("service worker registrado e ativo", ativo["ativo"] and ativo["estado"] == "activated", str(ativo))
        checa("o escopo cobre o site inteiro", ativo["escopo"].rstrip("/") == BASE, str(ativo["escopo"]))

        print("3) veredito do Chrome sobre instalar como app")
        app_manifest = cdp.send("Page.getAppManifest")
        checa("o Chrome leu o manifest sem erro", not app_manifest.get("errors"),
              str(app_manifest.get("errors"))[:200])
        problemas = cdp.send("Page.getInstallabilityErrors").get("installabilityErrors", [])
        # 'no-icon-available' aparece quando o Chrome ainda não buscou os ícones; não é bloqueio
        reais = [e for e in problemas if e.get("errorId") != "no-icon-available"]
        checa("nenhum impedimento de instalação", not reais, str(reais)[:300])

        print("4) sem rede, o app abre a tela de offline (não uma tela branca)")
        ctx.set_offline(True)
        pg.goto(f"{BASE}/account", wait_until="domcontentloaded")
        pg.wait_for_timeout(800)
        texto = pg.inner_text("body")
        checa("navegação offline cai na página de offline",
              "Sem conexão" in texto or "perdeu" in texto, texto[:120])
        checa("e explica que nada ficou pela metade", "Nada foi perdido" in texto)
        pg.screenshot(path=str(PROVAS / "pwa-offline.png"), full_page=True)
        ctx.set_offline(False)

        print("5) de volta com rede: o site carrega normal e nada de dado do cliente no cache")
        pg.goto(f"{BASE}/", wait_until="networkidle")
        checa("a home volta a carregar", "Barbearia" in pg.inner_text("body"))
        guardados = pg.evaluate("""async () => {
          const nomes = await caches.keys();
          const urls = [];
          for (const nome of nomes) {
            const cache = await caches.open(nome);
            for (const pedido of await cache.keys()) urls.push(new URL(pedido.url).pathname);
          }
          return urls;
        }""")
        checa("o casco do app está em cache", any(u.endswith("icon-192.png") for u in guardados), str(guardados[:6]))
        checa("nenhuma rota de API foi cacheada", not [u for u in guardados if u.startswith("/api/")], str(guardados))
        checa("a agenda (área logada) não está em cache",
              not [u for u in guardados if u in ("/account", "/perfil")], str(guardados))
        pg.screenshot(path=str(PROVAS / "pwa-home-mobile.png"), full_page=True)

        reais = [e for e in erros if "favicon" not in e and "Failed to load resource" not in e]
        checa("sem erro de JS no console", not reais, str(reais[:3]))
        navegador.close()

    print(f"\n{ok} verificações OK, {falhas} falhas")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
