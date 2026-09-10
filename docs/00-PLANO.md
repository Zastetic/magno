# Barbearia Magno — Plano mestre (v1)

> **Domínio:** https://magnum.autoava.us · **Pasta:** `~/magno` → `/mnt/d/projetos_wsl/magno`
> **Status:** planejamento fechado, aguardando 5 decisões do Okai (ver `03-DECISOES.md`)
> **Última atualização:** 2026-09-09

---

## 1. Problema e objetivo

A barbearia agenda por WhatsApp de forma manual: o cliente manda mensagem, o barbeiro
confere a agenda na cabeça e responde. Isso gera buracos na agenda, conflitos de horário
e nenhum histórico.

**Objetivo do sistema:** substituir esse vai-e-vem por um agendamento online com duas
visões — a do cliente (escolher serviço, dia e horário; ver e administrar os próprios
agendamentos) e a da loja (agenda dos próximos atendimentos, com poder de ler, alterar e
remover).

**Métrica de sucesso v1:** um cliente consegue agendar em menos de 60 segundos pelo
celular, sem falar com ninguém, e o barbeiro vê esse agendamento na agenda do dia
imediatamente.

---

## 2. Escopo

### 2.1 Dentro do escopo (v1)

**Agenda (núcleo)**
- Catálogo de serviços com duração e preço.
- Disponibilidade real calculada por profissional (grade + horário de funcionamento +
  bloqueios − agendamentos existentes).
- Agendamento pelo cliente (serviço → profissional → dia → horário → confirmação).
- Área "Meus agendamentos": listar futuros e passados, remarcar (atualizar data/hora) e
  cancelar.
- Painel da loja: agenda em dia/semana por profissional e visão "próximos atendimentos";
  alterar horário, mudar status (concluído / não compareceu), cancelar e excluir.

**Complementar (a "parte mínima que não é agenda")**
- Site institucional: home com apresentação, serviços e preços, equipe, endereço, horário
  de funcionamento e contato (WhatsApp/Instagram).
- Catálogo público *data-driven*: o que a home mostra sai do banco, editável pelo admin —
  não é HTML fixo. A mesma entidade (`servicos`, `profissionais`) alimenta a agenda.

**Transversal**
- Autenticação por papel (cliente / barbeiro / admin) com token opaco revogável.
- LGPD: consentimento no cadastro, Política de Privacidade + Termos, exclusão de conta
  com anonimização do histórico.
- Exportação da agenda em CSV (admin) e "adicionar ao calendário" (.ics) para o cliente.

### 2.2 Fora do escopo (v1) — explicitamente adiado

Pagamento online / sinal, fidelidade e cashback, estoque e venda de produtos, comissão de
barbeiro, múltiplas unidades, e-mail transacional, lembretes automáticos por WhatsApp API
(paga), app nativo, fila de espera, avaliações com nota.

> Regra: nada disso entra no código da v1. Ficam registrados aqui para não virarem
> "flexibilidade preventiva" (YAGNI).

---

## 3. Atores e permissões

| Ação | Cliente | Barbeiro | Admin (dono) |
|---|---|---|---|
| Ver serviços/preços/horários | ✅ | ✅ | ✅ |
| Criar agendamento (próprio) | ✅ | ✅ | ✅ |
| Ver agenda de todos | ❌ | ✅ (a própria + dia inteiro da loja) | ✅ |
| Remarcar / cancelar o próprio | ✅ (até o limite da política) | ✅ | ✅ |
| Cancelar agendamento de outro cliente | ❌ | ✅ | ✅ |
| Excluir (remover) atendimento futuro | ❌ | ✅ | ✅ |
| Marcar concluído / não compareceu | ❌ | ✅ | ✅ |
| CRUD serviços, profissionais, horários, bloqueios | ❌ | ❌ | ✅ |
| Editar textos do site e configurações | ❌ | ❌ | ✅ |
| Ver relatório/CSV e histórico de clientes | ❌ | parcial (do próprio dia) | ✅ |

Barbeiro e admin compartilham a API de agenda; o que separa é a dependência
`require_papel("barbeiro")` vs `require_papel("admin")` nas rotas de cadastro.

---

## 4. Regras de negócio (as "lacunas" que ficam fechadas)

Todas as constantes abaixo vivem na tabela `configuracoes` e são editáveis pelo admin —
nada hardcoded no código.

1. **Grade de horários:** o dia é dividido em slots de `slot_min` (padrão 30 min); um
   serviço ocupa `ceil(duracao_min / slot_min)` slots consecutivos.
2. **Buffer:** após cada atendimento há `buffer_min` (padrão 5 min) de intervalo, para
   limpeza/troca. O buffer não aparece para o cliente, mas ocupa a agenda.
3. **Antecedência mínima:** não se agenda para menos de `antecedencia_min_h` (padrão 1 h)
   no futuro. Também bloqueia horários que já começaram.
4. **Janela máxima:** o cliente vê no máximo `janela_dias` (padrão 60 dias) à frente.
5. **Política de cancelamento/remarcação:** o cliente só pode cancelar ou remarcar até
   `cancelamento_limite_h` (padrão 2 h) antes do início. Depois disso só a loja cancela
   (mensagem orienta a ligar/WhatsApp). A loja cancela/remarca a qualquer momento.
6. **Sem overbooking:** para o mesmo profissional, dois intervalos ativos **nunca** se
   sobrepõem. Garantido na transação (`BEGIN IMMEDIATE` + checagem de overlap + `UNIQUE`),
   não só na UI. Buffer entra no cálculo do overlap.
7. **Sem conflito para o cliente:** o mesmo cliente não pode ter dois agendamentos ativos
   sobrepostos (evita marcar dois serviços no mesmo horário).
8. **Status do agendamento:** `agendado → confirmado → concluido`, com saídas para
   `cancelado_cliente`, `cancelado_loja` e `nao_compareceu`. Transições válidas são
   validadas por rota; estado final não volta (exceto admin, que pode reabrir para
   `agendado` com registro em auditoria).
9. **Exclusão:** o admin pode *remover* um atendimento futuro. Cancelamento grava o motivo
   e mantém o registro (auditoria + relatório). Exclusão definitiva é permitida apenas ao
   admin, gera evento em `eventos` e some da agenda — decisão em aberto nº 4.
10. **Horário da loja:** por dia da semana (`horarios`), com exceções por data
    (`excecoes`: feriado fechado, ou horário especial). Bloqueio pontual por profissional
    (`bloqueios`: almoço, curso, folga) vence qualquer cálculo.
11. **Fuso horário:** tudo é gravado em **UTC ISO-8601** (`2026-09-10T18:00:00Z`) e
    exibido em `America/Sao_Paulo`. Conversão só na borda (entrada e saída).
12. **Identidade do cliente:** o telefone é o identificador natural — normalizado para
    E.164 só dígitos (`5513997630784`), validado por tamanho e DDD. Telefone é `UNIQUE`.
13. **Remarcação = novo horário, mesma identidade:** remarcar altera `inicio`/`fim` do
    mesmo agendamento (mantém histórico) em vez de criar outro registro.
14. **Fee/valores:** preço é congelado no agendamento (`preco_centavos`) no momento da
    criação; mudar o preço do serviço depois não reescreve o passado.
15. **Cliente não logado:** pode navegar e ver disponibilidade; só a confirmação exige
    cadastro/login (decisão nº 1 define o formato).

---

## 5. Arquitetura

```
Cliente (celular) ─┐
Barbeiro (tablet) ─┼─ HTTPS ─> Cloudflare (magnum.autoava.us)
Admin (PC)       ─┘                │ tunnel cloudflared (connector token)
                                   ▼
                       127.0.0.1:8100  ── FastAPI (uvicorn) ── SQLite (magno.db)
                       serve também o SPA em web/ (mesma origem, sem CORS)
```

- **Backend:** Python 3.11 + FastAPI + SQLite (mesmo padrão do `~/biblioteca_escolar/mvp`
  que já funciona em produção — reaproveitar auth, middlewares de segurança, camada de
  config e os testes).
- **Frontend:** SPA servida pelo próprio backend (mesma origem → sem CORS, cookie/token
  simples, CSP estrita). Roteador por hash, temas claro/escuro, mobile-first.
- **Sem build:** JS/CSS estáticos servidos de `web/`. Decisão nº 3 abre a alternativa
  React+Vite.
- **Porta:** 8100 (verificada livre). Serve APP + API na mesma origem.
- **Hospedagem:** WSL + `systemd --user` (`magno-server`, `magno-tunnel`) + pasta Startup
  do Windows, exatamente como o autoava.us.

### Estrutura de pastas

```
~/magno/
├── docs/              # este plano, modelo de dados, API, decisões, backlog
├── server/
│   ├── main.py        # app FastAPI: rotas + middlewares + static
│   ├── auth.py        # sessões (token opaco), rate limit/lockout, papéis
│   ├── db.py          # schema, seed, migração, expiração sob demanda
│   ├── agenda.py      # motor de disponibilidade e validação de conflito
│   └── relatorios.py  # CSV (BOM) e .ics
├── web/               # SPA: index.html, app.js, styles.css, ícones
├── tests/             # pytest + suite de API (banco descartável)
├── scripts/           # run.sh, backup.sh, deploy de systemd
├── data/              # magno.db, backups/  (fora do git)
├── logs/
├── .env.local         # segredos/porta (fora do git)
└── README.md
```

### Decisões de segurança herdadas (obrigatórias, não opcionais)

- Token **opaco** (`secrets.token_urlsafe(32)`), guardado como `sha256` na tabela
  `sessoes`, TTL 24 h, logout revoga de verdade (`revogada_em`).
- Login: 5 falhas / 15 min → 429 com tempo restante (por telefone+IP). Mensagem genérica
  (não revela se o telefone existe).
- Headers: `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `Cache-Control: no-store` em `/api`, HSTS, CSP com `script-src 'self'` (zero handler
  inline) e `style-src 'self' 'unsafe-inline'`.
- Limite de corpo ~1 MB → 413. SQL 100% parametrizado. CORS same-origin.
- Hook Turnstile pronto mas **desligado** (sitekey é vinculada ao domínio — só ativar com
  o domínio fixo; no tunnel `trycloudflare`/localhost falha).
- Rate limit específico no `POST /api/publica/agendar` (anti-spam de bots).

---

## 6. API (resumo — contrato completo em `02-API.md`)

**Público**
- `GET /api/publica/site` — textos, endereço, horários, WhatsApp, redes
- `GET /api/publica/servicos` — catálogo ativo (nome, duração, preço)
- `GET /api/publica/equipe` — profissionais ativos
- `GET /api/publica/disponibilidade?servico_id&profissional_id&data` — slots livres
- `POST /api/publica/agendar` — cria agendamento (cliente novo ou existente)
- `GET /api/agendamentos/{codigo}/ics` — arquivo de calendário

**Autenticação**
- `POST /api/auth/cadastro` · `POST /api/auth/login` · `POST /api/auth/logout` · `GET /api/auth/me`

**Cliente**
- `GET /api/meus-agendamentos` · `PATCH /api/agendamentos/{id}` (remarcar) ·
  `POST /api/agendamentos/{id}/cancelar` · `DELETE /api/me/conta` (LGPD)

**Loja (barbeiro/admin)**
- `GET /api/admin/agenda?de&ate&profissional_id` — agenda do período
- `GET /api/admin/proximos` — próximos N atendimentos
- `PATCH /api/admin/agendamentos/{id}` — horário, status, profissional
- `DELETE /api/admin/agendamentos/{id}` — remover (admin)
- CRUD: `/api/admin/servicos`, `/api/admin/profissionais`, `/api/admin/horarios`,
  `/api/admin/excecoes`, `/api/admin/bloqueios`
- `GET /api/admin/clientes` — histórico do cliente
- `GET|PUT /api/admin/config` — regras de negócio
- `GET /api/admin/relatorio?tipo&de&ate` — CSV com BOM

---

## 7. Telas

**Públicas / cliente**
1. Home institucional (hero, serviços e preços, equipe, endereço + mapa, horário, WhatsApp)
2. Agendar — passo 1 serviço · passo 2 profissional · passo 3 dia (calendário) · passo 4 hora (slots) · passo 5 confirmação
3. Entrar / Criar conta
4. Meus agendamentos (futuros e histórico; remarcar, cancelar, adicionar ao calendário)
5. Política de Privacidade / Termos

**Loja**
6. Agenda (visão dia e semana, colunas por profissional, filtro por barbeiro)
7. Próximos atendimentos (lista ordenada, ações rápidas)
8. Serviços (CRUD, duração, preço, ativo)
9. Equipe (CRUD, serviços habilitados por barbeiro, ativo)
10. Horários & Bloqueios (funcionamento por dia, exceções, folgas)
11. Clientes (busca por telefone/nome, histórico, no-show)
12. Configurações (janela, antecedência, política de cancelamento, textos do site)

---

## 8. Não-funcionais

- **Mobile-first:** 80% dos acessos vêm de celular. Alvos de toque ≥ 44 px, agenda em
  coluna única abaixo de 700 px.
- **Performance:** página inicial < 1 s no 4G; disponibilidade calculada em < 200 ms para
  uma janela de 60 dias (consulta indexada, sem N+1).
- **Disponibilidade:** systemd `Restart=always`; banco em WAL; backup diário do `.db`
  (14 cópias, `PRAGMA quick_check`) via cronjob do Hermes.
- **LGPD:** dados mínimos (nome, telefone, e-mail opcional); consentimento com data;
  política de retenção de 24 meses; exclusão de conta anonimiza o histórico
  (`cliente_id` → NULL + telefone removido).
- **Acessibilidade:** contraste AA, labels em todos os campos, foco visível, navegação por
  teclado no fluxo de agendamento.
- **Idioma/idioma de dados:** PT-BR, moeda R$, datas `dd/mm/aaaa`, preços em centavos no
  banco (inteiro) para nunca ter erro de float.

---

## 9. Testes e critérios de aceite

**Suíte `pytest` contra banco descartável** (`MAGNO_DB=/tmp/test.db`), obrigatória para
fechar cada fase:

- Auth: cadastro, login, token expirado, logout revoga, rate limit/lockout.
- Permissões: cliente não acessa rota de admin (403); barbeiro não edita serviços.
- Disponibilidade: horário de funcionamento, exceção (feriado), bloqueio de barbeiro,
  buffer, antecedência mínima, janela máxima, slot parcial no fim do dia.
- **Concorrência:** dois agendamentos simultâneos no mesmo slot → um 201, um 409 (teste
  com duas threads e `BEGIN IMMEDIATE`).
- Política: cliente cancela 3 h antes (ok) e 30 min antes (403 com mensagem).
- Remarcação: conflito detectado; buffer respeitado.
- LGPD: exclusão anonimiza e não deixa telefone no banco.
- Fuso: criar em horário local, ler em UTC, exibir de volta no local (idêntico).

**Aceite v1 (checklist do dono):** cliente agenda sozinho pelo celular; barbeiro vê na
agenda do dia; cliente cancela e o horário volta a ficar livre; admin remove um atendimento
futuro; site no ar em `magnum.autoava.us` com HTTPS.

---

## 10. Fases

| Fase | Entrega | Critério de saída |
|---|---|---|
| **F0** | Estrutura, venv, `run.sh`, schema, seed, git | servidor sobe em 8100 e responde `/api/saude` |
| **F1** | Auth + segurança (token, rate limit, headers, papéis) | suíte de auth verde |
| **F2** | Catálogo + site institucional (parte não-agenda) | home renderizando serviços/equipe do banco |
| **F3** | Motor de disponibilidade + agendamento | testes de conflito/buffer/política verdes |
| **F4** | Área do cliente (meus agendamentos, remarcar, cancelar) | cliente agenda, remarca e cancela sozinho |
| **F5** | Painel da loja (agenda dia/semana, CRUDs, config) | barbeiro lê e remove atendimento futuro |
| **F6** | Polimento: .ics, CSV, LGPD, responsivo, acessibilidade | suite completa verde + revisão visual |
| **F7** | Deploy: systemd, tunnel, DNS, backup | HTTPS respondendo no domínio |

---

## 11. Riscos e mitigação

| Risco | Impacto | Mitigação |
|---|---|---|
| Ingress do túnel apontar para porta errada (502, já aconteceu no autoava) | site fora | conferir `Updated to new configuration` no log; apontar `127.0.0.1:8100` |
| Subdomínio `magnum.autoava.us` não existe no DNS ainda | site inacessível | ação manual no painel Cloudflare (Public Hostname) — ver Decisões |
| Dois agendamentos no mesmo slot (condição de corrida) | conflito real na loja | `BEGIN IMMEDIATE` + checagem de overlap + teste concorrente |
| Fuso/BST gerando horário deslocado | cliente aparece na hora errada | UTC no banco, conversão única na borda, teste dedicado |
| Cliente cancela em cima da hora | prejuízo | limite de 2 h na política; loja cancela sempre |
| SQLite com escrita concorrente | 500 sob carga | WAL + timeout de 5 s; volume real é baixíssimo |
| Token do conector no git | vazamento | `.gitignore` para `.env.local` e `.cloudflared_token` |

---

## 12. Referências

- `01-MODELO-DE-DADOS.md` + `schema.sql` — tabelas, índices, seed (schema validado)
- `02-API.md` — contrato de todas as rotas
- `03-DECISOES.md` — decisões tomadas e as 5 pendentes do Okai
- `04-BACKLOG.md` — tarefas por fase, com critério de pronto
- Implementação de referência: `~/biblioteca_escolar/mvp/` (FastAPI+SQLite+SPA vanilla)
