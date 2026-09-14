"""Converte o roteiro da apresentação (Markdown) em PDF com acentuação correta.

O Markdown fica em `docs/07-APRESENTACAO.md`; este script gera o .pdf e o .txt (UTF-8 com BOM,
para abrir no Notepad/Word do Windows sem virar "Ã§Ã£").

Uso:  python scripts/gera_apresentacao_pdf.py
"""
from __future__ import annotations

import pathlib
import re

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, HRFlowable, PageBreak,
                                PageTemplate, Paragraph, Spacer)

RAIZ = pathlib.Path(__file__).resolve().parent.parent
ORIGEM = RAIZ / "docs" / "07-APRESENTACAO.md"
PDF = RAIZ / "docs" / "07-APRESENTACAO.pdf"
TXT = RAIZ / "docs" / "07-APRESENTACAO.txt"

FONTES = pathlib.Path("/usr/share/fonts/truetype/dejavu")
LATAO = "#c69347"
TINTA = "#14100b"


def registrar_fontes() -> None:
    """Fontes com acentuação completa (as Helvetica padrão só cobrem Latin-1 básico)."""
    pdfmetrics.registerFont(TTFont("Magno", str(FONTES / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("Magno-Bold", str(FONTES / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("Magno-Mono", str(FONTES / "DejaVuSansMono.ttf")))
    pdfmetrics.registerFontFamily("Magno", normal="Magno", bold="Magno-Bold",
                                  italic="Magno", boldItalic="Magno-Bold")


def estilos() -> dict[str, ParagraphStyle]:
    base = "Magno"
    return {
        "h1": ParagraphStyle("h1", fontName="Magno-Bold", fontSize=21, leading=26,
                             textColor=TINTA, spaceAfter=10),
        "h2": ParagraphStyle("h2", fontName="Magno-Bold", fontSize=16, leading=21,
                             textColor="#7a4c12", spaceBefore=6, spaceAfter=8),
        "h3": ParagraphStyle("h3", fontName="Magno-Bold", fontSize=12.5, leading=17,
                             textColor=TINTA, spaceBefore=10, spaceAfter=4),
        "p": ParagraphStyle("p", fontName=base, fontSize=10.2, leading=14.6,
                            textColor="#1b1712", alignment=TA_LEFT, spaceAfter=4),
        "li": ParagraphStyle("li", fontName=base, fontSize=10.2, leading=14.2,
                             textColor="#1b1712", leftIndent=16, bulletIndent=3,
                             spaceAfter=3),
        "rodape": ParagraphStyle("rodape", fontName=base, fontSize=8, textColor="#8f7f6b"),
    }


EMOJI_EM_TEXTO = {"✅": "ligado", "❌": "não", "⚠️": "atenção:", "⚠": "atenção:",
                  "🎉": "", "🔒": ""}


def inline(texto: str) -> str:
    """**negrito** -> <b>, `codigo` -> fonte mono, preservando o resto como texto."""
    texto = texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # a fonte do PDF não tem emoji: viraria quadradinho. Traduz para texto antes.
    for emoji, troca in EMOJI_EM_TEXTO.items():
        texto = texto.replace(emoji, troca)
    texto = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", texto)
    texto = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", texto)
    texto = re.sub(r"`(.+?)`", r"<font face='Magno-Mono' size='9'>\1</font>", texto)
    return texto


def montar(est: dict[str, ParagraphStyle]) -> list:
    linhas = ORIGEM.read_text(encoding="utf-8").splitlines()
    fluxo: list = []
    baldes: list[str] = []
    parag: list[str] = []

    def fechar_lista() -> None:
        if not baldes:
            return
        # Parágrafo com bulletText: o recuo vive no estilo, então as linhas quebradas
        # continuam alinhadas com o texto (o ListItem deixava a continuação na margem).
        for texto in baldes:
            fluxo.append(Paragraph(inline(texto), est["li"], bulletText="\u2022"))
        fluxo.append(Spacer(1, 3))
        baldes.clear()

    def fechar_paragrafo() -> None:
        """Junta as linhas quebradas do Markdown num único parágrafo (sem quebra falsa)."""
        if parag:
            fluxo.append(Paragraph(inline(" ".join(parag)), est["p"]))
            parag.clear()

    for bruta in linhas:
        linha = bruta.rstrip()
        if linha.startswith("- "):
            fechar_paragrafo()
            baldes.append(linha[2:].strip())
            continue
        # continuação de um bullet: no Markdown a linha quebrada vem indentada
        if baldes and linha[:1] in (" ", "\t") and linha.strip():
            baldes[-1] = f"{baldes[-1].rstrip()} {linha.strip()}"
            continue
        if not linha.strip():
            fechar_paragrafo()
            fechar_lista()
            continue
        fechar_lista()
        if linha.startswith("### "):
            fluxo.append(Paragraph(inline(linha[4:]), est["h3"]))
        elif linha.startswith("## "):
            fechar_paragrafo()
            fluxo.append(PageBreak())            # cada tópico começa em página nova
            fluxo.append(HRFlowable(width="100%", thickness=2, color=LATAO,
                                    spaceBefore=2, spaceAfter=6))
            fluxo.append(Paragraph(inline(linha[3:]), est["h2"]))
        elif linha.startswith("# "):
            fechar_paragrafo()
            fluxo.append(Paragraph(inline(linha[2:]), est["h1"]))
            fluxo.append(HRFlowable(width="100%", thickness=2.4, color=LATAO,
                                    spaceBefore=0, spaceAfter=10))
        elif linha.strip() == "---":
            fechar_paragrafo()
            fluxo.append(Spacer(1, 4))
            fluxo.append(HRFlowable(width="100%", thickness=0.6, color="#cbbda6",
                                    dash=(2, 3), spaceBefore=2, spaceAfter=8))
        else:
            parag.append(linha.strip())
    fechar_paragrafo()
    fechar_lista()
    return fluxo


def numero_de_pagina(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("Magno", 7.5)
    canvas.setFillColor("#8f7f6b")
    rodape = "Apresentação — código do site da Barbearia Magnum"
    canvas.drawString(doc.leftMargin, 12 * mm, rodape)
    canvas.drawRightString(A4[0] - doc.rightMargin, 12 * mm, f"página {doc.page}")
    canvas.restoreState()


def main() -> None:
    registrar_fontes()
    est = estilos()
    doc = BaseDocTemplate(str(PDF), pagesize=A4, title="Apresentação — Barbearia Magnum",
                          author="Okai", subject="Roteiro de slides sobre o código do site",
                          leftMargin=16 * mm, rightMargin=16 * mm,
                          topMargin=15 * mm, bottomMargin=18 * mm)
    quadro = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="corpo")
    doc.addPageTemplates([PageTemplate(id="pagina", frames=[quadro], onPage=numero_de_pagina)])
    doc.build(montar(est))

    TXT.write_text(ORIGEM.read_text(encoding="utf-8"), encoding="utf-8-sig")
    print(f"PDF: {PDF} ({PDF.stat().st_size} bytes)")
    print(f"TXT: {TXT} (UTF-8 com BOM)")


if __name__ == "__main__":
    main()
