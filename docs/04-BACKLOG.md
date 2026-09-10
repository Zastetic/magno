# Backlog por fase — Barbearia Magno v1

Legenda: `[ ]` pendente · `[x]` feito · cada fase só fecha com a suíte de testes verde.
Porta 8100 · banco `data/magno.db` (testes usam `MAGNO_DB=/tmp/test-magno.db`).

## F0 — Esqueleto do projeto
- [ ] `scripts/run.sh` (cria/ativa venv, sobe uvicorn em 8100 com `--reload` em dev)
- [ ] `server/main.py` com FastAPI + `/api/saude` + static de `web/`
- [ ] `server/db.py`: executa `docs/schema.sql`, seed idempotente, `PRAGMA foreign_keys=ON`, WAL
- [ ] `.env.local` (`MAGNO_DB`, `MAGNO_PORTA`, `MAGNO_TOKEN_TTL_MIN`) + `.env.example`
- [ ] `.gitignore` (`.env.local`, `.cloudflared_token`, `data/*.db`, `venv/`, `__pycache__`)
- [ ] `README.md` com como rodar
- [ ] `git add -A && git commit -m "chore: esqueleto do projeto + schema v1"`
- **Pronto quando:** `curl 127.0.0.1:8100/api/saude` responde `{"ok":true}` e o banco nasce com as 4 configurações, 7 horários e 4 serviços do seed.

## F1 — Auth e segurança
- [ ] `server/auth.py`: `pbkdf2_sha256`, token opaco (`sha256` no banco), TTL 24 h, logout revogando
- [ ] Rate limit + lockout no login (5 falhas / 15 min por telefone+IP)
- [ ] Middlewares: headers de segurança, CSP, limite de corpo 1 MB, `Cache-Control: no-store` em `/api`
- [ ] Dependências `get_usuario` / `require_papel("barbeiro"|"admin")`
- [ ] Rotas: `/api/auth/cadastro`, `/login`, `/logout`, `/me` + validação/normalização de telefone E.164
- [ ] Testes: cadastro, login, token expirado (`MAGNO_TOKEN_TTL_MIN=0`), logout revoga, lockout, papéis
- **Pronto quando:** suíte de auth verde e rota de admin devolve 403 para cliente.

## F2 — Catálogo + site institucional (a parte que não é agenda)
- [ ] CRUD admin de serviços, profissionais (cria usuário barbeiro), horários, exceções, bloqueios
- [ ] `GET/PUT /api/admin/config` (regras + textos da home)
- [ ] `GET /api/publica/site|servicos|equipe`
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

## F7 — Deploy
- [ ] `~/.config/systemd/user/magno-server.service` + `magno-tunnel.service` (token do conector, `--token-file`)
- [ ] Ativar: `systemctl --user enable --now magno-server magno-tunnel` (com `XDG_RUNTIME_DIR=/run/user/1000`)
- [ ] Public Hostname `magnum.autoava.us` → `HTTP 127.0.0.1:8100` no painel Cloudflare (ação do Okai)
- [ ] Conferir `Updated to new configuration` + `Registered tunnel connection` no log
- [ ] `curl -o /dev/null -w "%{http_code}" https://magnum.autoava.us/api/saude` → 200
- [ ] Criar barbeiro admin real e trocar as senhas de exemplo
- **Pronto quando:** HTTP 200 no domínio com HTTPS e o agendamento de teste aparece no painel.

## Depois da v1 (não fazer agora)
Confirmação por WhatsApp API, sinal/entrada paga, fidelidade, comissão, estoque de produtos,
múltiplas unidades, avaliação com nota, fila de espera, PWA instalável.
