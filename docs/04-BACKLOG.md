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

## F1 — Auth e segurança ✅ (fechada 2026-09-10)
- [x] `server/auth.py`: `pbkdf2_sha256`, token opaco (`sha256` no banco), TTL 24 h, logout revogando
- [x] Rate limit + lockout no login (5 falhas / 15 min por telefone+IP) + PIN trivial recusado no cadastro
- [x] Middlewares: headers de segurança, CSP, limite de corpo 1 MB, `Cache-Control: no-store` em `/api`
- [x] Dependências `get_usuario` / `require_papel("barbeiro"|"admin")`
- [x] Rotas: `/api/auth/cadastro`, `/login`, `/logout`, `/me`, `/telefone` + normalização de telefone E.164
- [x] **Login com Google** (`server/google_auth.py`): OAuth authorization code, `state` de uso único,
      vínculo por e-mail, provedor de teste local (`GOOGLE_FAKE`) — falta só colar as credenciais
- [x] Telas `/login` (`entrar.html`), `/perfil` e `/account` no mesmo design; o cabeçalho da área logada cumprimenta pelo nome (vindo do Bearer, nunca do HTML)
- [x] Testes: 71 no servidor (auth, google, migração) + 28 verificações de browser
- **Bugs reais achados pelos testes:** (1) o lockout nunca disparava — o contador era zerado a cada
  tentativa; (2) e-mail repetido estourava 500 em vez de 409; (3) o "já estou logado" rodava também
  na página da conta e causava loop de recarregamento.
- **Pronto quando:** suíte de auth verde e rota de admin devolve 403 para cliente. ✅
- Passo a passo das credenciais do Google: `docs/06-LOGIN.md`

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

## F3 — Motor de disponibilidade + agendamento (o coração) ✅ (fechada 2026-09-16)
- [x] `server/agenda.py`: grade de slots, `buffer_min`, `antecedencia_min_h`, `janela_dias`
- [x] Respeitar `horarios`, `excecoes` (feriado/especial), `bloqueios` e agendamentos ativos
- [x] `motivo_vazio` explicando dia sem slots (`loja_fechada`, `fora_da_janela`,
      `sem_profissional_habilitado`, `antecedencia_minima`, `dia_lotado`, `sem_espaco_no_dia`)
      + `motivo_texto` em pt-BR pronto para a tela
- [x] `GET /api/publica/disponibilidade` (dia ou `de`/`ate` até 31 dias) + `GET /api/publica/servicos`
      e `/api/publica/equipe` para o site montar serviço/barbeiro/dia/hora do banco
- [x] `POST /api/bookings` valida pelo **mesmo motor** que desenha a grade (`agenda.conferir`) e
      grava em `BEGIN IMMEDIATE` (`agenda.marcar`): checagem de overlap + índice único parcial.
      `fim` já inclui o buffer; o candidato é testado com `[início, início+duração+buffer)`
- [x] Reuso de cliente por telefone (a conta do Bearer ganha o nome/telefone que ele digitou)
- [x] Anti-spam: 12 agendamentos/IP/hora + teto de 600 req/min (`server/limites.py`)
- [x] Testes: `tests/test_agenda.py` (21 testes) — grade, slot parcial no fim do dia, serviço que
      não cabe, antecedência, janela, feriado, horário especial, bloqueio, buffer, fuso com
      horário de verão, dois pedidos simultâneos no mesmo slot (5×2 threads → 5 criam, 5 recebem
      conflito) e **marcar → o horário sai da disponibilidade de todo mundo**
- [x] `web/conta.js` consome a grade do servidor: tira de dias só com dias que têm vaga, horários
      recarregados a cada seleção, e recarrega sozinha depois de confirmar e ao voltar para a aba
- **Pronto quando:** teste concorrente passa 20/20 vezes e nenhuma combinação gera horário
  duplicado. **Verificado:** 5 slots × 2 threads simultâneas → 5×201 e 5×409, zero duplicados na
  auditoria do banco; 174 testes de servidor, 35 verificações de browser (`scripts/testa_perfil.py`),
  40 na API ao vivo (`scripts/testa_bearer.py`).

## F4 — Área do cliente
- [x] **Primeiro acesso** (`/perfil`): pergunta o nome e depois a idade antes de liberar a agenda — D25
      (`PATCH /api/account/profile`; `perfil_completo` no `usuario`; `conta.js` guarda a rota)
- [x] **Agenda do cliente** em `/account` com o nome de quem está logado + `POST /api/bookings` com Bearer
      (409 em horário ocupado, 400 em horário passado)
- [x] Verificação do Bearer de ponta a ponta: `tests/test_bearer.py` (suíte), `scripts/testa_bearer.py`
      (40 checagens ao vivo em 8100), `scripts/testa_perfil.py` (35 no browser, com prints)
- [x] **Grade de horários de verdade** (D28): os dias e as horas vinham fixos no HTML (16–20/09/2026)
      e agora saem de `GET /api/publica/disponibilidade` — mesma fonte que o `POST` valida (F3)
- [ ] Campo para criar/trocar a **senha opcional** na interface (a API `POST /api/auth/senha` existe,
      mas a tela antiga de conta saiu na reescrita da agenda)
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
- [x] Revisão mobile (feita antes da hora, 09/2026): alvos ≥44 px, nada de texto < 12 px, campos de
      16 px (sem zoom do iOS), menu hambúrguer em todas as páginas, agenda empilhada abaixo de 940 px,
      lista de dias com rolagem horizontal no celular estreito. Medido por `scripts/audita_mobile.py`
      em 6 páginas × 4 larguras (360/390/414/768): 0 problemas, prints em `/tmp/mobile/`
- [ ] Acessibilidade: labels, foco visível, contraste AA, teclado no fluxo de agendamento
- [x] **Rate limit geral por IP** (`server/limites.py`, D26): regras por ação (cadastro 5/h,
      código 6/h, login 15/15 min, agendamento 12/h) + teto de 600 req/min por IP, 429 com
      `Retry-After`, evento `limite_estourado` na auditoria e mensagem em pt-BR. 10 testes em
      `tests/test_limites.py`; o `conftest` zera os contadores entre testes
- [x] **CAPTCHA Cloudflare Turnstile** (D27): widget invisível em `web/turnstile.js`, verificação
      no servidor (`server/turnstile.py`) em cadastro, código por e-mail, login e agendamento.
      Sem chave o site funciona igual; `MAGNO_TURNSTILE_MODO=log` verifica sem bloquear
- [x] **Páginas de Privacidade e Termos** (`/privacidade`, `/termos`) + links no rodapé de todas
      as páginas e aviso de consentimento nas telas que criam conta
- [x] 404 do site (o `/api` continua JSON), `robots.txt`, `sitemap.xml`, canonical + meta de
      compartilhamento (OG/Twitter) e `Permissions-Policy`/HSTS nos cabeçalhos
- [x] **App no celular (PWA, D29)**: `manifest.webmanifest` (ícones 192/512 + maskable), service
      worker que guarda só o casco (nunca `/api/*` nem as telas logadas), `offline.html` no design
      do site e ícones gerados por `scripts/gera_icones_pwa.py` (do SVG do poste, via Playwright).
      Instalabilidade conferida pelo próprio Chrome (`Page.getInstallabilityErrors` vazio) e
      offline testado com a rede cortada em `scripts/testa_pwa.py` (19 verificações)
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
múltiplas unidades, avaliação com nota, fila de espera.
**App**: o PWA já resolve "ícone na tela do celular" (D29). O passo seguinte, quando valer,
é **APK de verdade** (TWA/Bubblewrap + `.well-known/assetlinks.json` com o SHA-256 da chave de
assinatura) — fazer **junto** do cookie `HttpOnly`, porque com `sessionStorage` o app pediria
login a cada abertura. Ordem de grandeza: ~1 h com o Android SDK no lugar (JDK e Node já tem),
20–30 min por build depois; PWABuilder na nuvem dispensa o SDK. Play Store é outro bloco
(US$ 25, AAB, revisão de 1 a 7 dias). Detalhes em `docs/06-APP.md`.

## Para abrir ao público — o que ainda falta (checado em 2026-09-14)

Proteções e acabamento já estão no código. O que **bloqueia** uma abertura de verdade:

1. **Envio de e-mail de verdade** — hoje `MAGNO_EMAIL_MODO=arquivo` grava o código em
   `logs/emails/`. Cliente real precisa de `smtp`/`resend`/`brevo` + SPF/DKIM (D23/D24).
2. **Chaves do Turnstile** (D27): criar o widget no painel Cloudflare e pôr `MAGNO_TURNSTILE_SITE`
   e `MAGNO_TURNSTILE_SECRET`; começar com `MODO=log` e depois virar `on`.
3. **Credenciais do Google** (`GOOGLE_CLIENT_ID`/`SECRET`) — hoje o botão só funciona com `GOOGLE_FAKE`.
4. **Admin real** criado e credenciais de exemplo trocadas (`MAGNO_SEED_DEV` fora de produção).
5. **Public Hostname no Cloudflare** (`magnum.autoava.us` → `HTTP 127.0.0.1:8100`) e HTTPS conferido.
6. **Backup diário** do banco (`scripts/backup.sh` + cronjob) antes de ter cliente de verdade.

Resolvido em 2026-09-16: a **disponibilidade real** (F3/D28) saiu do caminho — a grade de dias e
horas é calculada no servidor a cada consulta e o `POST` valida pelo mesmo motor, então marcar um
horário o tira da grade de todo mundo. O cartão de agendamento não tem mais data fixa no HTML.
