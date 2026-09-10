# Barbearia Magno — sistema de agendamento

Agendamento online para barbearia: o cliente escolhe serviço, profissional, dia e horário;
a loja vê e administra os próximos atendimentos em formato de agenda.

- **Produção:** https://magnum.autoava.us
- **Local:** http://127.0.0.1:8100
- **Stack:** FastAPI + SQLite + SPA servida pelo próprio backend (mesma origem)
- **Hospedagem:** WSL + `systemd --user` + Cloudflare Tunnel (mesmo esquema do autoava.us)

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

Variáveis (`.env.local`): `MAGNO_PORTA` (default 8100), `MAGNO_DB` (default `data/magno.db`),
`MAGNO_TOKEN_TTL_MIN` (default 1440).

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

Planejamento fechado. Aguardando as 5 decisões de `docs/03-DECISOES.md` para começar a F0.
