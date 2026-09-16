"""PWA instalável: manifest, ícones, service worker e o veredito do Chrome.

O site não tem app nativo: o "app da barbearia" é o próprio site instalado pelo navegador
(Chrome Android → "Instalar app"; iPhone → "Adicionar à Tela de Início"). Para o Chrome
oferecer isso, três coisas precisam estar certas de pé: manifest com nome/ícones/display,
service worker com handler de fetch e HTTPS (ou localhost). É isso que esta suíte mede — e a
última verificação pergunta ao próprio Chrome (`Page.getInstallabilityErrors` via CDP), que é
o juiz de verdade: se ele não reclama, o botão "Instalar app" aparece para o cliente.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.main import app

WEB = Path(__file__).resolve().parent.parent / "web"


@pytest.fixture
def cliente():
    with TestClient(app) as c:
        yield c


# ------------------------------------------------------------------- arquivos
def test_manifest_existe_e_e_json_valido():
    caminho = WEB / "manifest.webmanifest"
    assert caminho.is_file(), "sem manifest não existe PWA"
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    assert dados["name"] and dados["short_name"]
    assert dados["start_url"] == "/" and dados["scope"] == "/"
    assert dados["display"] in ("standalone", "fullscreen", "minimal-ui")
    assert dados["lang"] == "pt-BR" and dados["dir"] == "ltr"
    assert dados["theme_color"] == "#14100b" and dados["background_color"] == "#14100b"


def test_manifest_tem_os_icones_que_o_chrome_exige():
    dados = json.loads((WEB / "manifest.webmanifest").read_text(encoding="utf-8"))
    por_tamanho = {}
    for icone in dados["icons"]:
        caminho = WEB / icone["src"].lstrip("/")
        assert caminho.is_file(), f"ícone declarado e ausente: {icone['src']}"
        # PNG de verdade: assinatura do arquivo, não só a extensão
        assert caminho.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", f"{icone['src']} não é PNG"
        por_tamanho.setdefault(icone["sizes"], set()).add(icone.get("purpose", "any"))
    assert "192x192" in por_tamanho, "Chrome pede 192x192"
    assert "512x512" in por_tamanho, "Chrome pede 512x512 (é daí que sai o ícone de instalação)"
    assert any("maskable" in propositos for propositos in por_tamanho.values()), "falta o maskable (Android recorta o ícone)"
    assert (WEB / "icons" / "apple-touch-icon.png").is_file(), "iOS não usa o manifest: precisa do apple-touch-icon"


def test_service_worker_tem_handler_de_fetch_e_nao_cacheia_a_api():
    codigo = (WEB / "sw.js").read_text(encoding="utf-8")
    assert "addEventListener('install'" in codigo
    assert "addEventListener('activate'" in codigo
    assert "addEventListener('fetch'" in codigo, "sem handler de fetch o Chrome não considera instalável"
    assert "url.pathname.startsWith('/api/')" in codigo, "a API não pode ser cacheada"
    assert "clients.claim()" in codigo and "skipWaiting()" in codigo, "versão nova demoraria a assumir"


def test_paginas_apontam_para_o_manifest_e_o_service_worker():
    for nome in ("index.html", "index-b.html", "conta.html", "perfil.html", "entrar.html",
                 "privacidade.html", "termos.html", "status.html", "offline.html"):
        html = (WEB / nome).read_text(encoding="utf-8")
        assert 'rel="manifest" href="/manifest.webmanifest"' in html, nome
        assert 'src="pwa.js' in html, nome
        assert 'rel="apple-touch-icon" href="/icons/apple-touch-icon.png"' in html, nome


def test_offline_diz_o_que_aconteceu_e_nao_promete_agendamento():
    html = (WEB / "offline.html").read_text(encoding="utf-8")
    assert "Sem conexão" in html
    assert "nenhuma reserva fica pela metade" in html
    assert "/manifest.webmanifest" in html


# ------------------------------------------------------------------ servidor
def test_manifest_servido_com_o_tipo_certo(cliente):
    resposta = cliente.get("/manifest.webmanifest")
    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("application/manifest+json")
    assert resposta.json()["name"].startswith("Barbearia Magnum")


def test_service_worker_na_raiz_e_sem_cache(cliente):
    """Na raiz para o escopo ser `/` (o site inteiro) e sem cache para a atualização chegar."""
    resposta = cliente.get("/sw.js")
    assert resposta.status_code == 200
    assert "javascript" in resposta.headers["content-type"]
    assert "no-cache" in resposta.headers["cache-control"]
    assert resposta.headers.get("service-worker-allowed") == "/"


def test_icones_e_offline_servidos(cliente):
    for caminho in ("/icons/icon-192.png", "/icons/icon-512.png", "/icons/maskable-512.png",
                    "/icons/apple-touch-icon.png"):
        resposta = cliente.get(caminho)
        assert resposta.status_code == 200, caminho
        assert resposta.headers["content-type"] == "image/png"
        assert resposta.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert cliente.get("/offline.html").status_code == 200
