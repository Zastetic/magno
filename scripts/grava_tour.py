"""Grava um tour curto da home para virar GIF — prova visual do movimento."""
import shutil
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8100"
SAIDA = Path("/tmp/mov_video")
if SAIDA.exists():
    shutil.rmtree(SAIDA)
SAIDA.mkdir(parents=True)


def rolar(pg, destino, passos=18, pausa=70):
    """Rolagem suave até a posição destino, para o reveal acontecer no ritmo certo."""
    atual = pg.evaluate("window.scrollY")
    salto = (destino - atual) / passos
    for _ in range(passos):
        atual += salto
        pg.evaluate(f"window.scrollTo(0, {atual})")
        pg.wait_for_timeout(pausa)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(
        viewport={"width": 1280, "height": 780},
        record_video_dir=str(SAIDA),
        record_video_size={"width": 1280, "height": 780},
        locale="pt-BR", timezone_id="America/Sao_Paulo",
    )
    pg = ctx.new_page()
    pg.goto(f"{BASE}/", wait_until="networkidle")
    pg.wait_for_timeout(3500)                     # poste girando + letreiro correndo

    pg.hover('a[data-servico="Corte + barba"]')
    pg.wait_for_timeout(900)
    rolar(pg, 620)
    pg.wait_for_timeout(1200)                     # hover na linha de preço

    rolar(pg, 1500)
    pg.wait_for_timeout(900)                      # equipe com o reveal

    rolar(pg, 2400)
    pg.wait_for_timeout(800)                      # passos

    rolar(pg, 3000)
    pg.wait_for_timeout(700)
    pg.click('a[data-servico="Degradê navalhado"]')
    pg.wait_for_timeout(500)
    pg.click("#chipsProf .chip")
    pg.wait_for_timeout(400)
    pg.click("#chipsHora .chip")
    pg.wait_for_timeout(1400)                     # chips acendem

    ctx.close()                                   # fecha e grava o vídeo
    b.close()

videos = list(SAIDA.glob("*.webm"))
print("video:", videos[0] if videos else "NÃO GRAVOU")
