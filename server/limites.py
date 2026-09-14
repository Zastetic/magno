"""Limites de requisição por IP — anti-abuso do site público.

Janela deslizante em memória: o serviço roda em um único worker (systemd `magno-server`),
então um dicionário com trava basta e não adiciona dependência (sem Redis).

Duas camadas:
  · REGRAS  — limites específicos por ação (cadastro, pedir código, login, agendamento…);
  · PADRAO  — teto geral para qualquer rota /api, para ninguém varrer a API.

O IP vem do Cloudflare (`CF-Connecting-IP`) quando existe, senão do X-Forwarded-For (o
túnel) e por último da conexão. Isso é seguro porque o serviço só escuta em 127.0.0.1:
o único caminho até aqui é o cloudflared, que reescreve esses cabeçalhos.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

# (método, prefixo do caminho, máximo, janela em segundos)
REGRAS: tuple[tuple[str, str, int, int], ...] = (
    ("POST", "/api/auth/cadastro", 5, 3600),      # criar conta: 5/hora por IP
    ("POST", "/api/auth/codigo", 6, 3600),        # pedir código por e-mail: 6/hora
    ("POST", "/api/auth/verificar", 12, 900),     # tentar código: 12/15min
    ("POST", "/api/auth/login", 15, 900),         # telefone+PIN: 15/15min
    ("POST", "/api/auth/entrar-senha", 15, 900),  # e-mail+senha: 15/15min
    ("POST", "/api/auth/telefone", 8, 3600),      # vincular telefone
    ("POST", "/api/auth/senha", 8, 3600),         # criar/trocar senha
    ("POST", "/api/bookings", 12, 3600),          # agendar: 12/hora
    ("POST", "/api/auth/google/iniciar", 25, 3600),
    ("PATCH", "/api/account/profile", 25, 3600),
)
PADRAO: tuple[int, int] = (600, 60)   # teto geral: 600 requisições/minuto por IP

# Quanto maior o teto, mais memória; 20k chaves cobre com folga um dia de movimento.
MAX_CHAVES = 20_000

_trava = threading.Lock()
_janelas: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_bloqueios: dict[tuple[str, str], float] = {}


def atras_de_proxy() -> bool:
    """Só confia em CF-Connecting-IP/X-Forwarded-For quando estamos atrás do túnel."""
    return (os.environ.get("MAGNO_ATRAS_DE_PROXY") or "1").strip() not in ("0", "false", "nao", "não")


def ip_do_cliente(request) -> str:
    if atras_de_proxy():
        for cabecalho in ("cf-connecting-ip", "x-real-ip", "x-forwarded-for"):
            valor = request.headers.get(cabecalho)
            if valor:
                return valor.split(",")[0].strip()[:64]
    cliente = getattr(request, "client", None)
    return (getattr(cliente, "host", None) or "desconhecido")[:64]


def _regra(metodo: str, caminho: str) -> tuple[str, str, int, int]:
    for m, prefixo, maximo, janela in REGRAS:
        if metodo == m and caminho.startswith(prefixo):
            return m, prefixo, maximo, janela
    return "", caminho.split("?")[0], PADRAO[0], PADRAO[1]


def permitir(metodo: str, caminho: str, ip: str) -> tuple[bool, int]:
    """Registra o hit e devolve (liberado, segundos_para_esperar).

    Quando estoura, o chamador responde 429 com Retry-After — nunca 500.
    """
    _, chave_rota, maximo, janela = _regra(metodo, caminho)
    chave = (ip, f"{metodo} {chave_rota}")
    agora = time.monotonic()
    with _trava:
        if len(_janelas) > MAX_CHAVES:
            _podar(agora)
        fila = _janelas[chave]
        limite = agora - janela
        while fila and fila[0] < limite:
            fila.popleft()
        if len(fila) >= maximo:
            esperar = max(1, int(janela - (agora - fila[0])) + 1)
            _bloqueios[chave] = agora
            return False, esperar
        fila.append(agora)
    return True, 0


def _podar(agora: float) -> None:
    """Descarta janelas velhas. Chamado com a trava na mão."""
    for chave in list(_janelas):
        fila = _janelas[chave]
        if not fila or agora - fila[-1] > 3600:
            _janelas.pop(chave, None)
            _bloqueios.pop(chave, None)


def limpar() -> None:
    """Usado pelos testes e pelo ciclo de vida do app entre execuções."""
    with _trava:
        _janelas.clear()
        _bloqueios.clear()


def estado() -> dict:
    with _trava:
        ativos = sum(1 for fila in _janelas.values() if fila)
    return {
        "regras": [{"metodo": m, "rota": p, "maximo": mx, "janela_s": j} for m, p, mx, j in REGRAS],
        "padrao": {"maximo": PADRAO[0], "janela_s": PADRAO[1]},
        "chaves_ativas": ativos,
    }
