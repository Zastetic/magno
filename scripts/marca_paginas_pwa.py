"""Insere as tags do PWA nas páginas do site (idempotente).

Uso: python3 scripts/marca_paginas_pwa.py
"""
from __future__ import annotations

import pathlib

RAIZ = pathlib.Path(__file__).resolve().parent.parent / "web"
PAGINAS = ("index.html", "index-b.html", "conta.html", "perfil.html", "entrar.html",
           "privacidade.html", "termos.html", "status.html", "offline.html")

CABECA = """<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Barbearia Magnum">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
"""
RODAPE = '<script src="pwa.js?v=pwa-1" defer></script>\n'


def marca(caminho: pathlib.Path) -> str:
    texto = caminho.read_text(encoding="utf-8")
    if "manifest.webmanifest" in texto:
        return "já estava"
    if "</head>" not in texto or "</body>" not in texto:
        return "SEM </head> ou </body> — pulado"
    texto = texto.replace("</head>", CABECA + "</head>", 1)
    if "pwa.js" not in texto:
        texto = texto.replace("</body>", RODAPE + "</body>", 1)
    caminho.write_text(texto, encoding="utf-8")
    return "marcada"


for nome in PAGINAS:
    alvo = RAIZ / nome
    print(f"  {nome:18} {marca(alvo) if alvo.exists() else 'não existe'}")
