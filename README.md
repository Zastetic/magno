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
| Agenda (serviço/profissional/dia/horário) e painel da loja | ⏳ F2–F4 do backlog |
| Envio real de e-mail e credenciais do Google | ⏳ esperando o provedor (`docs/06-LOGIN.md`) →

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
MAGNO_DB=/tmp/test-magno.db ./venv/bin/pytest tests/ -v   # suíte da aplicação (F1+)
python3 scripts/valida_schema.py                          # valida o schema e as regras críticas
```

Os testes usam banco descartável — o banco de desenvolvimento nunca é tocado.
`valida_schema.py` já passa 17/17: schema, CHECKs, overbooking com buffer, trava de
duplicidade, corrida de duas threads e o cálculo de disponibilidade.

## Estrutura

```
docs/    planejamento (plano, dados, API, decisões, backlog, schema)
server/  main.py (rotas/middlewares), auth.py, db.py, agenda.py, relatorios.py
web/     SPA: index.html, app.js, styles.css
tests/   suíte pytest (banco descartável)
scripts/ run.sh, backup.sh
data/    magno.db + backups (fora do git)
```

## Status

**F0 fechada** e a **home institucional pronta** (`web/index.html`, com variante em
`web/index-b.html`). Planejamento completo em `docs/`. Próximo passo do sistema: **F1**
(login por telefone + PIN, token revogável, rate limit e papéis).

O deploy está a **um passo no painel Cloudflare**: Public Hostname `magnum.autoava.us` →
`HTTP 127.0.0.1:8100`. Servidor e túnel já rodam como serviço (`docs/05-DEPLOY.md`).
