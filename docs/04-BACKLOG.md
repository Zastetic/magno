# Backlog por fase — Barbearia Magno v1

Legenda: `[ ]` pendente · `[x]` feito · cada fase só fecha com a suíte de testes verde.
Porta 8100 · banco `data/magno.db` (testes usam `MAGNO_DB=/tmp/test-magno.db`).

## F0 — Esqueleto do projeto ✅ (fechada 2026-09-09)
- [x] `scripts/run.sh` (cria/ativa venv, sobe uvicorn em 8100 com `--reload` em dev)
- [x] `server/main.py` com FastAPI + `/api/saude` + static de `web/` (lifespan, sem `on_event`)
- [x] `server/db.py`: executa `docs/schema.sql`, seed idempotente, `PRAGMA foreign_keys=ON`, WAL, `busy_timeout=5000`
- [x] `docs/schema.sql` com `IF NOT EXISTS` em tudo → boot repetido não recria/duplica nada
- [x] `.env.local` + `.env.example` (`MAGNO_DB` no ext4, ver D21)
- [x] `.gitignore` (`.env.local`, `.cloudflared_token`, `data/*.db`, `venv/`, `__pycache__`)
- [x] `README.md` com como rodar
- [x] `tests/test_smoke.py` — 7 testes, **7 passaram** (schema idempotente, 11 tabelas, 8 índices,
      `/api/saude`, headers de segurança, 413 de corpo grande, SPA na mesma origem)
- [x] `git commit "feat: F0 — esqueleto, banco SQLite e health-check"`
- **Pronto quando:** `curl 127.0.0.1:8100/api/saude` responde `{"ok":true}` e o banco nasce com as 4 configurações, 7 horários e 4 serviços do seed. **Verificado:** `ok: true`, 12 configurações, 7 horários, 4 serviços, `integridade: ok`.
- ⚠️ Observado: o boot leva ~15 s porque o venv e o código estão em `/mnt/d` (9p). Opcional depois:
  criar o venv em `~/.local/share/magno/venv` para reload rápido — não é bloqueio.

## F1 — Auth e segurança
- [ ] `server/auth.py`: `pbkdf2_sha256`, token opaco (`sha256` no banco), TTL 24 h, logout revogando
- [ ] Rate limit + lockout no login (5 falhas / 15 min por telefone+IP) + PIN trivial recusado no cadastro
- [ ] Middlewares: headers de segurança, CSP, limite de corpo 1 MB, `Cache-Control: no-store` em `/api`
- [ ] Dependências `get_usuario` / `require_papel("barbeiro"|"admin")`
- [ ] Rotas: `/api/auth/cadastro`, `/login`, `/logout`, `/me` + validação/normalização de telefone E.164
- [ ] Testes: cadastro, login, PIN trivial recusado, token expirado (`MAGNO_TOKEN_TTL_MIN=0`), logout revoga, lockout, papéis
- **Pronto quando:** suíte de auth verde e rota de admin devolve 403 para cliente.

## F2 — Catálogo + site institucional (a parte que não é agenda)
- [x] Home institucional **interativa** (antecipada para a apresentação): relógio da loja,
      aberto/fechado real, grade de horários calculada (funcionamento − almoço − ocupados −
      antecedência de 1 h), seleção de serviço/barbeiro/horário, passo de confirmação com
      validação e link de WhatsApp. Dados ainda de exemplo no HTML (`web/app.js`, `web/index.html`).
- [x] Variante de composição: `web/index-b.html` ("placa"), mesmo sistema e mesmas dinâmicas.
- [x] 26 verificações de browser (`/tmp/testa_dinamico.py`) + 8 testes de servidor passando.
- [ ] CRUD admin de serviços, profissionais (cria usuário barbeiro), horários, exceções, bloqueios
- [ ] `GET/PUT /api/admin/config` (regras + textos da home)
- [ ] `GET /api/publica/site|servicos|equipe` — e a home passa a ler daqui em vez dos `data-*`
- [ ] SPA: home institucional (hero, serviços+preços, equipe, endereço, horário, WhatsApp)
- [ ] Tema claro/escuro com script no `<head>` (sem flash) e CSS com variáveis
- [ ] Testes: CRUD, permissões, catálogo público só mostra ativos
- **Pronto quando:** home renderiza serviços e equipe vindos do banco e o admin muda um preço e vê na home.

## F3 — Motor de disponibilidade + agendamento (o coração)
- [ ] `server/agenda.py`: grade de slots, `buffer_min`, `antecedencia_min_h`, `janela_dias`
- [ ] Respeitar `horarios`, `excecoes` (feriado/especial), `bloqueios` e agendamentos ativos
- [ ] `motivo_vazio` explicando dia sem slots
- [ ] `POST /api/publica/agendar` em `BEGIN IMMEDIATE` + checagem de overlap + índice único
- [ ] Anti-spam: 5 agendamentos/IP/hora; reuso de cliente por telefone
- [ ] Testes: conflito (dois POST simultâneos → 1×201 + 1×409), buffer, antecedência, janela, feriado, bloqueio, slot parcial no fim do dia, mudança de horário de verão do fuso
- **Pronto quando:** teste concorrente passa 20/20 vezes e nenhuma combinação gera horário duplicado.

## F4 — Área do cliente
- [ ] Fluxo de agendamento em 4 passos (serviço → profissional → dia → hora) + confirmação
- [ ] `GET /api/meus-agendamentos` (futuros e histórico) + `GET/POST /api/agendamentos`
- [ ] `PATCH /api/agendamentos/{id}` (remarcar) e `POST .../cancelar` com `cancelamento_limite_h`
- [ ] `.ics` e botão de WhatsApp com mensagem pronta
- [ ] `DELETE /api/me/conta` anonimizando (LGPD) + páginas de Privacidade e Termos
- [ ] Testes: dono vs terceiro (403), prazo excedido, remarcar para slot ocupado, LGPD sem resíduo de telefone
- **Pronto quando:** um cliente cria conta, agenda, remarca, cancela e exclui a conta pelo celular sem ajuda.

## F5 — Painel da loja
- [ ] `GET /api/admin/agenda?de&ate&profissional_id` (dia e semana) + `/proximos`
- [ ] `PATCH /api/admin/agendamentos/{id}` (horário, profissional, status) com transições validadas
- [ ] `DELETE /api/admin/agendamentos/{id}` (admin) + evento de auditoria
- [ ] Expiração sob demanda: `agendado` vencido há >6 h → `nao_compareceu`
- [ ] Telas: Agenda (colunas por profissional, mobile em lista), Próximos, Clientes, Configurações
- [ ] Testes: transição inválida → 400; barbeiro não deleta? (admin deleta); eventos gravados
- **Pronto quando:** o barbeiro lê a agenda do dia, marca concluído/no-show e o admin remove um atendimento futuro.

## F6 — Polimento
- [ ] `GET /api/admin/relatorio` CSV com BOM (`;`) — agendamentos, clientes, faturamento
- [ ] Revisão mobile (alvos ≥44 px, agenda em coluna única <700 px) com screenshots de prova
- [ ] Acessibilidade: labels, foco visível, contraste AA, teclado no fluxo de agendamento
- [ ] Rate limit geral por IP, mensagens de erro em pt-BR revisadas
- [ ] Backup diário (`scripts/backup.sh` + cronjob Hermes `no_agent`)
- **Pronto quando:** suíte completa verde + navegação do fluxo inteiro no celular sem zoom.

## F7 — Deploy (parcial: falta 1 passo no painel)
- [x] `~/.config/systemd/user/magno-server.service` + `magno-tunnel.service` (token do conector, `--token-file`)
- [x] Ativar: `systemctl --user enable --now magno-server magno-tunnel` — ambos `active` + `enabled`
- [x] Conector conectado (4 conexões) — log confirma ingress remoto com `autoava.us`/`www.autoava.us`
- [ ] Public Hostname `magnum.autoava.us` → `HTTP 127.0.0.1:8100` no painel Cloudflare (**ação do Okai**)
- [ ] `curl -o /dev/null -w "%{http_code}" https://magnum.autoava.us/api/saude` → 200
- [ ] Criar o admin real e trocar as credenciais de exemplo
- **Pronto quando:** HTTP 200 no domínio com HTTPS.
- Passo a passo, verificação e alternativa por API: `docs/05-DEPLOY.md`
- Link público temporário para demonstração: `./scripts/demo.sh`

## Depois da v1 (não fazer agora)
Confirmação por WhatsApp API, sinal/entrada paga, fidelidade, comissão, estoque de produtos,
múltiplas unidades, avaliação com nota, fila de espera, PWA instalável.
