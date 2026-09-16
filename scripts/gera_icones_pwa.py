#!/usr/bin/env python3
"""Gera os ícones do PWA (web/icons/) a partir do poste de barbeiro, no design do site.

Não existe arte-fonte em PNG: o desenho é o mesmo SVG do favicon (poste listrado em latão),
então o ícone é renderizado pelo Chromium (Playwright) — reproduzível e sem depender de
editor de imagem. Rodar com o python do Hermes, que tem playwright:

    /home/vh450/.hermes/hermes-agent/venv/bin/python scripts/gera_icones_pwa.py

Saída (o que o Chrome exige para "Instalar app" + o que o iOS usa):
    icon-192.png, icon-512.png            → purpose "any" (fundo escuro da loja)
    maskable-512.png                      → purpose "maskable" (poste dentro da zona segura)
    apple-touch-icon.png (180x180)        → iOS "Adicionar à Tela de Início"
    icone.svg                             → fonte editável, versionada junto
"""
from __future__ import annotations

import pathlib

from playwright.sync_api import sync_playwright

RAIZ = pathlib.Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "web" / "icons"
FUNDO = "#14100b"
LATAO = "#c69347"

# O poste: corpo arredondado + três listras na diagonal (mesmo desenho do favicon/letreiro).
POSTE = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 18 30">
  <defs><clipPath id="clipe"><rect x="2" y="2" width="14" height="26" rx="7"/></clipPath></defs>
  <g clip-path="url(#clipe)" stroke="{latao}" stroke-width="1.6" opacity=".9">
    <line x1="-1" y1="12" x2="19" y2="4"/>
    <line x1="-1" y1="20" x2="19" y2="12"/>
    <line x1="-1" y1="28" x2="19" y2="20"/>
  </g>
  <rect x="2" y="2" width="14" height="26" rx="7" fill="none" stroke="{latao}" stroke-width="1.6"/>
</svg>
"""


def pagina_html(escala: float, com_fundo: bool) -> str:
    """Uma página só com o poste: `escala` é quanto do quadrado o desenho ocupa."""
    fundo = f"background:{FUNDO};" if com_fundo else ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
      html,body {{ margin:0; padding:0; {fundo} }}
      .caixa {{ width:100vw; height:100vh; display:grid; place-items:center; }}
      svg {{ height:{escala * 100}%; width:auto; display:block; }}
    </style></head><body><div class="caixa">{POSTE.format(latao=LATAO)}</div></body></html>"""


def gerar(pg, nome: str, tamanho: int, escala: float, com_fundo: bool = True) -> None:
    pg.set_viewport_size({"width": tamanho, "height": tamanho})
    pg.set_content(pagina_html(escala, com_fundo))
    caminho = DESTINO / nome
    pg.screenshot(path=str(caminho), omit_background=not com_fundo)
    print(f"  {caminho.relative_to(RAIZ)}  {tamanho}x{tamanho}  ({caminho.stat().st_size / 1024:.1f} kB)")


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    (DESTINO / "icone.svg").write_text(POSTE.format(latao=LATAO).strip() + "\n", encoding="utf-8")
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pg = navegador.new_page(device_scale_factor=1)
        print("ícones do PWA:")
        # "any": poste grande, fundo da loja
        gerar(pg, "icon-192.png", 192, 0.82)
        gerar(pg, "icon-512.png", 512, 0.82)
        # "maskable": o Android recorta em círculo/quadrado arredondado — desenho menor,
        # dentro da zona segura (80% central), senão as pontas do poste são cortadas
        gerar(pg, "maskable-512.png", 512, 0.55)
        # iOS não aceita o maskable e ignora o manifest: usa o apple-touch-icon
        gerar(pg, "apple-touch-icon.png", 180, 0.78)
        navegador.close()


if __name__ == "__main__":
    main()
