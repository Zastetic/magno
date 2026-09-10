# Deploy — Barbearia Magnum (magnum.autoava.us)

## Estado atual (2026-09-10 00:25)

| Peça | Estado |
|---|---|
| Servidor local | ✅ `magno-server.service` (systemd --user) — uvicorn `127.0.0.1:8100`, `enabled` |
| Conector do túnel | ✅ `magno-tunnel.service` — túnel **dedicado** `c0c5fc61-8ecf-4fde-a6a1-b7e03345bdcc` conectado |
| DNS `magnum.autoava.us` | ✅ existe — A record proxied (172.67.128.147 / 104.21.2.16) |
| Ingress no túnel | ⚠️ existe, com o **protocolo errado** — 1 campo para corrigir (abaixo) |
| Banco | ✅ `/home/vh450/.local/share/magno/magno.db` (ext4 nativo) |

O Okai criou um túnel novo e dedicado para o magno (mesma conta `e50bc5dd...`, tunnel
`c0c5fc61-8ecf-4fde-a6a1-b7e03345bdcc`). O conector já roda com o token dele. O DNS já
resolve. O ingress remoto que a Cloudflare entrega é:

```json
{"ingress":[
  {"hostname":"magnum.autoava.us","service":"https://127.0.0.1:8100"},
  {"service":"http_status:404"}],
 "warp-routing":{"enabled":false}}
```

## O que falta: trocar HTTPS por HTTP (1 campo, ~15 s)

O `uvicorn` serve **HTTP** na 8100, mas o hostname foi cadastrado como `https://`. O log do
cloudflared mostra o erro exato:

```
ERR Unable to reach the origin service ... tls: first record does not look like a TLS handshake
    ingressRule=0 originService=https://127.0.0.1:8100
```

Isso é o 502 que o domínio devolve hoje. Correção:

1. `dash.cloudflare.com` → autoava.us → **Zero Trust** → **Networks → Tunnels**.
2. Abrir o túnel do magno (`c0c5fc61-8ecf-4fde-a6a1-b7e03345bdcc`).
3. Aba **Public Hostname** → clicar em `magnum.autoava.us` → **Edit**.
4. Trocar **Type** de `HTTPS` para **`HTTP`**, mantendo a URL `127.0.0.1:8100`.
5. **Save**. O cloudflared puxa a config sozinho em segundos — não precisa reiniciar nada.

> O `autoava.us` usa exatamente esse padrão (`HTTP → 127.0.0.1:8000`). Não é para servir TLS
> na origem: quem faz o HTTPS com o certificado válido é a própria Cloudflare (a origem fica
> em loopback, e por isso HTTP é o correto).

## Verificação (depois de salvar)

```bash
curl -o /dev/null -w "%{http_code}\n" https://magnum.autoava.us/            # 200
curl -o /dev/null -w "%{http_code}\n" https://magnum.autoava.us/api/saude   # 200
journalctl --user -u magno-tunnel -f                                        # sem ERR
```

`502` = conector ok, origem inalcançável (conferir Type/URL do Public Hostname).
`404` = chegou no túnel mas o hostname não casa com nenhuma regra de ingress.

## Alternativa: eu corrijo por API

Criar um token em `dash.cloudflare.com` → **My Profile → API Tokens → Create Token → Custom**:

- **Account → Cloudflare Tunnel → Edit**
- **Zone → DNS → Edit** (zone `autoava.us`)

Com o token eu ajusto o ingress (`PATCH /accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations`),
crio/corrijo DNS e publico novos serviços sem passar pelo painel. Guardado no `.env.local`
(fora do git).

## Operação

```bash
export XDG_RUNTIME_DIR=/run/user/1000
systemctl --user status magno-server magno-tunnel      # estado
systemctl --user restart magno-server                  # reiniciar o site
journalctl --user -u magno-tunnel -f                   # acompanhar o túnel
```

Link público temporário (sem domínio, morre quando o processo cai):
```bash
./scripts/demo.sh
```

## Túneis e o autoava.us

- `magno-tunnel.service` usa `/home/vh450/magno/.cloudflared_token` (**túnel dedicado do magno**).
  Antes disso, o conector do magno rodou por alguns minutos com o token do autoava e devolveu
  `autoava.us` para 530 (sem conector) ao ser trocado — ou seja, o autoava voltou ao estado em
  que estava (o site já estava fora do ar, `autoava-server` parado).
- Se quiser o autoava no ar de novo: `systemctl --user enable --now autoava-server autoava-tunnel`.
