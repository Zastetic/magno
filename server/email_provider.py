"""Envio de e-mail do Barbearia Magno.

Modos (variável MAGNO_EMAIL_MODO):

  · `arquivo` (padrão) — NÃO envia nada para fora. Grava o e-mail em `logs/emails/` e o
    código em `logs/emails/enviados.jsonl`, para desenvolver e testar sem provedor nenhum.
  · `smtp`   — qualquer servidor SMTP (Gmail com senha de app, Brevo, Mailgun, SES…).
  · `resend` — API do Resend (MAGNO_EMAIL_CHAVE).
  · `brevo`  — API do Brevo (MAGNO_EMAIL_CHAVE).

O remetente padrão é `magnum@autoava.us`. OBSERVAÇÃO: o domínio autoava.us hoje RECEBE
e-mail pela Cloudflare (MX route*.mx.cloudflare.net) — roteamento da Cloudflare não envia.
Para mandar e-mail para os clientes é preciso um provedor de envio E os registros de
SPF/DKIM no DNS, senão cai em spam. Ver docs/06-LOGIN.md.
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA_EMAILS = RAIZ / "logs" / "emails"
TEMPO_LIMITE_S = 15

ASSUNTO_CODIGO = "Seu código de acesso — Barbearia Magnum"


def modo() -> str:
    return (os.environ.get("MAGNO_EMAIL_MODO") or "arquivo").strip().lower()


def remetente() -> str:
    return (os.environ.get("MAGNO_EMAIL_DE") or "magnum@autoava.us").strip()


def nome_remetente() -> str:
    return (os.environ.get("MAGNO_EMAIL_NOME") or "Barbearia Magnum").strip()


def configurado() -> bool:
    if modo() == "arquivo":
        return True
    if modo() == "smtp":
        return bool(os.environ.get("MAGNO_SMTP_HOST") and remetente())
    if modo() in ("resend", "brevo"):
        return bool(os.environ.get("MAGNO_EMAIL_CHAVE"))
    return False


# ------------------------------------------------------------------ template
def template_codigo(codigo: str, nome: str | None = None) -> str:
    """E-mail com estilos embutidos (cliente de e-mail ignora <style>)."""
    oi = f"Oi, {nome.split()[0]}." if nome else "Oi."
    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>{ASSUNTO_CODIGO}</title></head>
<body style="margin:0;padding:24px;background:#14100b;font-family:-apple-system,'Segoe UI',Roboto,Arial,sans-serif;color:#f1e7d7">
  <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="max-width:480px;margin:0 auto;background:#1d1610;border:1px solid rgba(214,178,124,.28);border-radius:3px">
    <tr><td style="padding:28px 30px 8px">
      <p style="margin:0 0 18px;font-size:11px;letter-spacing:.26em;text-transform:uppercase;color:#c69347">Barbearia Magnum</p>
      <p style="margin:0 0 6px;font-size:17px;color:#f1e7d7">{oi}</p>
      <p style="margin:0 0 22px;font-size:15px;line-height:1.55;color:#b4a18b">
        Use o código abaixo para entrar. Ele vale por {int(TEMPO_VALIDADE_MIN)} minutos e só funciona uma vez.
      </p>
      <p style="margin:0 0 22px;font-size:38px;letter-spacing:.34em;font-family:'Courier New',monospace;color:#e0b26a">{codigo}</p>
      <p style="margin:0 0 22px;font-size:14px;line-height:1.55;color:#b4a18b">
        Depois de entrar você pode marcar corte, barba ou navalha com hora marcada.
      </p>
    </td></tr>
    <tr><td style="padding:0 30px 26px;border-top:1px solid rgba(214,178,124,.14)">
      <p style="margin:18px 0 0;font-size:12px;line-height:1.5;color:#8f7f6b">
        Não pediu esse código? Pode ignorar este e-mail — ninguém entra na sua conta sem ele.
      </p>
    </td></tr>
  </table>
</body></html>"""


TEMPO_VALIDADE_MIN = 10


def texto_simples(codigo: str) -> str:
    return (f"Barbearia Magnum\n\nSeu código de acesso: {codigo}\n"
            f"Ele vale por {TEMPO_VALIDADE_MIN} minutos e só funciona uma vez.\n\n"
            "Não pediu esse código? Pode ignorar este e-mail.")


# ------------------------------------------------------------------ envio
def enviar(para: str, assunto: str, html: str, texto: str | None = None) -> dict:
    """Envia pelo provedor configurado. Devolve {"ok": bool, "modo": str, "detalhe": str}."""
    if not configurado():
        return {"ok": False, "modo": modo(),
                "detalhe": f"provedor de e-mail '{modo()}' sem configuração"}

    if modo() == "arquivo":
        return _gravar_em_arquivo(para, assunto, html)

    try:
        if modo() == "smtp":
            _enviar_smtp(para, assunto, html, texto)
        elif modo() == "resend":
            _enviar_resend(para, assunto, html, texto)
        elif modo() == "brevo":
            _enviar_brevo(para, assunto, html, texto)
        else:
            return {"ok": False, "modo": modo(), "detalhe": "modo desconhecido"}
        return {"ok": True, "modo": modo(), "detalhe": "enviado"}
    except Exception as erro:                      # nunca derruba a requisição do cliente
        return {"ok": False, "modo": modo(), "detalhe": f"{type(erro).__name__}: {erro}"}


def enviar_codigo(para: str, codigo: str, nome: str | None = None) -> dict:
    resultado = enviar(para, ASSUNTO_CODIGO, template_codigo(codigo, nome), texto_simples(codigo))
    if resultado["ok"] and modo() == "arquivo":
        # modo de desenvolvimento: deixa o código num índice para os testes lerem
        PASTA_EMAILS.mkdir(parents=True, exist_ok=True)
        with (PASTA_EMAILS / "enviados.jsonl").open("a", encoding="utf-8") as indice:
            indice.write(json.dumps({
                "para": para, "codigo": codigo,
                "criado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "assunto": ASSUNTO_CODIGO,
            }, ensure_ascii=False) + "\n")
    return resultado


# ------------------------------------------------------------------ modos
def _gravar_em_arquivo(para: str, assunto: str, html: str) -> dict:
    PASTA_EMAILS.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    arquivo = PASTA_EMAILS / f"{carimbo}-{para.replace('@', '_at_')}.html"
    arquivo.write_text(html, encoding="utf-8")
    return {"ok": True, "modo": "arquivo", "detalhe": str(arquivo)}


def _enviar_smtp(para: str, assunto: str, html: str, texto: str | None) -> None:
    host = os.environ["MAGNO_SMTP_HOST"]
    porta = int(os.environ.get("MAGNO_SMTP_PORTA") or 587)
    usuario = os.environ.get("MAGNO_SMTP_USUARIO") or remetente()
    senha = os.environ.get("MAGNO_SMTP_SENHA") or ""

    mensagem = EmailMessage()
    mensagem["From"] = f"{nome_remetente()} <{remetente()}>"
    mensagem["To"] = para
    mensagem["Subject"] = assunto
    mensagem.set_content(texto or "Abra este e-mail em um cliente com HTML.")
    mensagem.add_alternative(html, subtype="html")

    if porta == 465:
        with smtplib.SMTP_SSL(host, porta, timeout=TEMPO_LIMITE_S,
                              context=ssl.create_default_context()) as servidor:
            if usuario:
                servidor.login(usuario, senha)
            servidor.send_message(mensagem)
    else:
        with smtplib.SMTP(host, porta, timeout=TEMPO_LIMITE_S) as servidor:
            servidor.ehlo()
            servidor.starttls(context=ssl.create_default_context())
            if usuario:
                servidor.login(usuario, senha)
            servidor.send_message(mensagem)


def _enviar_resend(para: str, assunto: str, html: str, texto: str | None) -> None:
    _post_json("https://api.resend.com/emails",
               {"Authorization": f"Bearer {os.environ['MAGNO_EMAIL_CHAVE']}"},
               {"from": f"{nome_remetente()} <{remetente()}>", "to": [para],
                "subject": assunto, "html": html, "text": texto})


def _enviar_brevo(para: str, assunto: str, html: str, texto: str | None) -> None:
    _post_json("https://api.brevo.com/v3/smtp/email",
               {"api-key": os.environ["MAGNO_EMAIL_CHAVE"]},
               {"sender": {"email": remetente(), "name": nome_remetente()},
                "to": [{"email": para}], "subject": assunto,
                "htmlContent": html, "textContent": texto})


def _post_json(url: str, cabecalhos: dict, corpo: dict) -> None:
    dados = json.dumps(corpo).encode()
    cabecalhos = dict(cabecalhos, **{"Content-Type": "application/json",
                                     "User-Agent": "magno/1.0"})
    requisicao = urllib.request.Request(url, data=dados, headers=cabecalhos, method="POST")
    try:
        with urllib.request.urlopen(requisicao, timeout=TEMPO_LIMITE_S) as resposta:
            resposta.read()
    except urllib.error.HTTPError as erro:
        detalhe = erro.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"HTTP {erro.code}: {detalhe}") from erro


def ultimo_codigo_enviado(email: str) -> str | None:
    """Só para desenvolvimento/teste: lê o último código gravado pelo modo `arquivo`."""
    if modo() != "arquivo":
        return None
    arquivo = PASTA_EMAILS / "enviados.jsonl"
    if not arquivo.exists():
        return None
    for linha in reversed(arquivo.read_text(encoding="utf-8").splitlines()):
        try:
            registro = json.loads(linha)
        except json.JSONDecodeError:
            continue
        if registro.get("para") == email:
            return registro.get("codigo")
    return None
