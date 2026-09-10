# Deploy — Barbearia Magnum (magnum.autoava.us)

## Estado atual (2026-09-10 00:15)

| Peça | Estado |
|---|---|
| Servidor local | ✅ `magno-server.service` (systemd --user) — uvicorn em `127.0.0.1:8100`, `enabled` |
| Conector do túnel | ✅ `magno-tunnel.service` — cloudflared conectado (4 conexões, gru14/gru08/gru19) |
| Banco | ✅ `/home/vh450/.local/share/magno/magno.db` (ext4 nativo) |
| DNS `magnum.autoava.us` | ❌ **não existe** — falta 1 passo no painel Cloudflare (abaixo) |
| Ingress no túnel | ❌ sem regra para `magnum.autoava.us` (hoje cai no catch-all `http_status:404`) |

O túnel já está no ar reusando o conector do `autoava.us`. O log confirma o ingress remoto (autoritativo):

```json
{"ingress":[
  {"hostname":"autoava.us","service":"http://127.0.0.1:8000"},
  {"hostname":"www.autoava.us","service":"http://127.0.0.1:8000"},
  {"service":"http_status:404"}],
 "warp-routing":{"enabled":false}}
```

Falta só uma linha nessa lista — e ela só pode ser editada no painel (o token do conector
permite conectar, não editar configuração).

## Passo que só o dono faz (~40 segundos, 1x só)

O jeito mais direto, que já cria o DNS e o ingress juntos:

1. `dash.cloudflare.com` → domínio **autoava.us** → **Zero Trust**.
2. **Networks → Tunnels** → abrir o túnel `b584ba18-040b-4dfd-bf7b-47d890a767d6`.
3. Aba **Public Hostname** → **Add a public hostname**.
4. Preencher:
   - Subdomain: `magnum`
   - Domain: `autoava.us`
   - Type: `HTTP` · URL: `127.0.0.1:8100`
5. **Save**.

A Cloudflare cria o CNAME `magnum.autoava.us` → `<uuid>.cfargotunnel.com` automaticamente.
O cloudflared puxa a config sozinho em segundos (não precisa reiniciar nada) e o log mostra
`Updated to new configuration` com a regra nova.

## Verificação (depois do passo acima)

```bash
python3 -c "import socket; print(socket.gethostbyname('magnum.autoava.us'))"   # resolve?
curl -o /dev/null -w "%{http_code}\n" https://magnum.autoava.us/               # 200
curl -o /dev/null -w "%{http_code}\n" https://magnum.autoava.us/api/saude      # 200
```

502 = conector ok mas origem errada (conferir se o Service ficou `127.0.0.1:8100`, não 8000).

## Alternativa: eu faço sozinho (se criar um token de API)

Criar em `dash.cloudflare.com` → **My Profile → API Tokens → Create Token → Custom**:

- Permissão **Account → Cloudflare Tunnel → Edit**
- Permissão **Zone → DNS → Edit** (zone: autoava.us)

Colando o token aqui, eu adiciono o hostname e o CNAME por API em segundos, sem painel — e
fico apto a fazer isso para os próximos serviços também. O token é guardado só no
`.env.local` (que é ignorado pelo git).

## Operação

```bash
export XDG_RUNTIME_DIR=/run/user/1000
systemctl --user status magno-server magno-tunnel      # ver estado
systemctl --user restart magno-server                  # reiniciar o site
journalctl --user -u magno-tunnel -f                   # acompanhar o túnel
```

Link público temporário (sem domínio, morre quando o processo cai):
```bash
./scripts/demo.sh
```

## Observação sobre o autoava.us

Ao subir o conector, `autoava.us` e `www.autoava.us` passaram de *1033 (sem conector)* para
**502** — o túnel está apontando para `127.0.0.1:8000`, mas o `autoava-server.service` está
parado. Nada que funcionava quebrou (o site já estava fora do ar), mas se quiser religar:

```bash
systemctl --user enable --now autoava-server
```
