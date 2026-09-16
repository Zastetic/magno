# Barbearia Magno — sistema de agendamento

Agendamento online para barbearia: o cliente escolhe serviço, profissional, dia e horário;
a loja vê e administra os próximos atendimentos em formato de agenda.

- **Produção:** https://magnum.autoava.us
- **Repositório:** https://github.com/Zastetic/magno (privado)
- **Local:** http://127.0.0.1:8100 (systemd: `magno-server`, `magno-tunnel`)
- **Stack:** FastAPI + SQLite + SPA servida pelo próprio backend (mesma origem)
- **Hospedagem:** WSL + `systemd --user` + Cloudflare Tunnel (mesmo esquema do autoava.us)

## Estado hoje

| Área | Estado |
|---|---|
| Site institucional (marca, serviços, horários, dinâmica) | ✅ no ar |
| Login por **e-mail + código de 5 dígitos** (sem senha) | ✅ funcionando |
| Login com **Google** | ✅ código pronto, rodando com provedor de teste |
| **Telefone + PIN** (balcão) e senha opcional | ✅ |
| **Primeiro acesso** (`/perfil`): nome → idade → agenda | ✅ feito (D25) |
| **Agenda do cliente** em `/account` com o nome de quem entrou | ✅ fluxo real; a grade de dias/horas ainda é fixa no HTML (ver backlog F4) |
| **Bearer token** (sessões, revogação, expiração, conta desativada) | ✅ verificado: 140 testes + 34 checagens ao vivo + 24 no browser |
| Painel da loja (barbeiro/admin) | ⏳ F5 do backlog |
| Envio real de e-mail (Resend) | ✅ ligado; falta SPF/DKIM no DNS para não cair em spam |
| Credenciais reais do Google | ⏳ esperando o Okai (`docs/06-LOGIN.md`) |

## Documentação (leia nesta ordem)

| Arquivo | Conteúdo |
|---|---|
| `docs/00-PLANO.md` | escopo, atores, regras de negócio, arquitetura, telas, riscos, fases |
| `docs/01-MODELO-DE-DADOS.md` | tabelas, convenções, consultas críticas, migração |
| `docs/schema.sql` | schema executável + seed (validado) |
| `docs/02-API.md` | contrato de todas as rotas, payloads e códigos de erro |
| `docs/03-DECISOES.md` | decisões tomadas e as pendentes do Okai |
| `docs/04-BACKLOG.md` | tarefas por fase, com critério de pronto |

## Rodar em desenvolvimento

```bash
cd ~/magno
./scripts/run.sh            # cria/ativa o venv e sobe em http://127.0.0.1:8100
```

Variáveis (`.env.local`): `MAGNO_PORTA` (default 8100), `MAGNO_DB` (default
`/home/vh450/.local/share/magno/magno.db`), `MAGNO_TOKEN_TTL_MIN` (default 1440).

> **O banco NÃO fica em `/mnt/d`.** O sistema de arquivos do Windows montado no WSL (DrvFs/9p)
> é centenas de vezes mais lento para gravar: medi 200 gravações em 0,46 s lá contra 0,002 s
> no ext4 nativo (238x). Como só o `.db` precisa de velocidade, ele fica no ext4
> (`~/.local/share/magno/`) e o backup diário copia para `~/magno/data/backups/` no D:.
> Código e versionamento continuam em `~/magno` → `/mnt/d/projetos_wsl/magno`.

## Testes

```bash
MAGNO_DB=/tmp/test-magno.db ./venv/bin/pytest tests/ -v      # suíte da aplicação (140 testes)
./venv/bin/python scripts/testa_bearer.py                    # API ao vivo em 8100 (34 checagens)
./venv/bin/python scripts/valida_schema.py                   # valida o schema e as regras críticas
```

Testes de browser (precisam do python que tem Playwright instalado) — o servidor tem que estar no ar:

```bash
P=/home/vh450/.hermes/hermes-agent/venv/bin/python
$P scripts/testa_perfil.py         # primeiro acesso: nome → idade → agenda + reserva (24 checagens, gera prints em docs/provas/)
$P scripts/testa_login.py          # telefone+PIN, Google, guarda do /perfil e revogação (22)
$P scripts/testa_email_login.py    # login por código: sobe um servidor descartável na 8123 em modo arquivo (18)
$P scripts/audita_mobile.py        # celular: 6 páginas × 4 larguras (alvo de toque, texto, rolagem) — tem que dar 0
```

Os testes usam banco descartável — o banco de desenvolvimento nunca é tocado.
`valida_schema.py` já passa 17/17: schema, CHECKs, overbooking com buffer, trava de
duplicidade, corrida de duas threads e o cálculo de disponibilidade.

## Estrutura

```
docs/    planejamento (plano, dados, API, decisões, backlog, schema) + provas/ (prints)
server/  main.py (rotas + páginas), auth.py (sessões/Bearer, PIN, código, Google), db.py, email_provider.py, google_auth.py
web/     entrar.html (/login), perfil.html (/perfil), conta.html (/account), index.html, styles.css
tests/   suíte pytest (banco descartável)
scripts/ run.sh, testa_bearer.py, testa_perfil.py, testa_login.py, testa_email_login.py, valida_schema.py
data/    backups do .db (o banco em uso fica no ext4, ver D21)
```

## Status

**F0, F1 e F3 fechadas.** Além do login (e-mail com código, Google, telefone + PIN), o cliente já
tem **primeiro acesso** em `/perfil` (nome → idade → agenda, D25) e a **agenda em `/account`**
mostrando o nome de quem entrou, com reserva real por `POST /api/bookings`. A grade de dias e
horas **vem do servidor** (`GET /api/publica/disponibilidade`, D28): serviço, barbeiro, dia e
hora saem do banco, e o `POST` valida pelo mesmo motor que desenha a grade — marcou, o horário
sai da grade de todo mundo (e da própria tela, na hora). O Bearer foi verificado de ponta a
ponta: suíte do servidor, checagens na API ao vivo e navegação no browser.
Próximo passo do sistema: **F5** (painel da loja) e o que falta da **F4** (remarcar/cancelar).

Os dois barbeiros de exemplo (Rafael e Bruno) nascem com `MAGNO_SEED_DEV=1`, hoje ligado no
ambiente do serviço (`~/.config/magno/magno.env`) só para a demonstração funcionar — em produção,
cadastrar os barbeiros de verdade e remover essa linha.

O deploy está a **um passo no painel Cloudflare**: Public Hostname `magnum.autoava.us` →
`HTTP 127.0.0.1:8100`. Servidor e túnel já rodam como serviço (`docs/05-DEPLOY.md`).
