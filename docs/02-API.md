# Contrato da API — Barbearia Magno v1

Base: `https://magnum.autoava.us/api` (dev: `http://127.0.0.1:8100/api`).
Auth: header `Authorization: Bearer <token>` (token opaco). Sessão em `sessoes`, TTL 24 h.
Erros: sempre JSON `{"erro": "<mensagem em pt-BR>", "codigo": "<slug>"}`.
Convenções: datas/horas de entrada e saída em UTC ISO-8601; preços em centavos;
`409` = conflito de horário; `403` = política/permissão; `429` = rate limit.

---

## 1. Público (sem autenticação)

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/saude` | health-check (`{"ok":true,"hora":"..."}`) |
| GET | `/api/publica/site` | textos institucionais, endereço, WhatsApp, Instagram, horários de funcionamento |
| GET | `/api/publica/servicos` | serviços ativos (id, nome, descrição, `duracao_min`, `preco_centavos`, imagem) |
| GET | `/api/publica/equipe` | profissionais ativos (id, nome/apelido, bio, foto, serviços que executa) |
| GET | `/api/publica/disponibilidade` | slots livres |
| POST | `/api/publica/agendar` | cria agendamento sem exigir login (ver decisão nº 1) |
| GET | `/api/agendamentos/{codigo}/ics` | arquivo `.ics` do agendamento (link "adicionar ao calendário") |

### `GET /api/publica/disponibilidade`

Query: `servico_id` (obrigatório), `profissional_id` (opcional — sem ele, devolve a união
dos profissionais habilitados), `data=YYYY-MM-DD` (obrigatório, hora local) **ou**
`de`/`ate` (até 31 dias).

Resposta 200:
```json
{
  "data": "2026-09-15",
  "servico_id": 3,
  "duracao_min": 60,
  "profissionais": [
    {
      "profissional_id": 2,
      "nome": "Rafael",
      "slots": ["2026-09-15T12:00:00Z", "2026-09-15T13:00:00Z", "2026-09-15T17:30:00Z"]
    }
  ],
  "motivo_vazio": null
}
```
`motivo_vazio` explica quando não há slot nenhum: `"loja_fechada"`, `"fora_da_janela"`,
`"sem_profissional_habilitado"`, `"dia_lotado"` — o front mostra a mensagem certa em vez de
uma tela vazia.

Regras aplicadas no cálculo: grade de `slot_min`, `duracao_min` do serviço, `buffer_min`,
`antecedencia_min_h`, `janela_dias`, `horarios`, `excecoes`, `bloqueios` e agendamentos
ativos (concluído também ocupa, para não reescrever histórico).

### `POST /api/publica/agendar`
```json
{
  "servico_id": 3,
  "profissional_id": 2,
  "inicio": "2026-09-15T13:00:00Z",
  "nome": "João da Silva",
  "telefone": "13997630784",
  "observacao": "máquina 2 nas laterais",
  "consentimento_lgpd": true
}
```
- `201` → `{"codigo":"mg-7f3a91c2","inicio":"...","fim":"...","profissional":"Rafael","servico":"Corte + barba","preco_centavos":7000,"cancelamento_limite":"2026-09-15T11:00:00Z"}`
- `409` se o slot já foi tomado (`{"erro":"Esse horário acabou de ser reservado. Escolha outro.","codigo":"slot_ocupado"}`)
- `400` validação (telefone inválido, consentimento ausente, `servico_id` inativo, slot fora da grade/fora de `antecedencia_min_h`)
- `429` anti-spam (máx. 5 agendamentos por IP/hora)

## 2. Autenticação

O token de sessão é **opaco** (nunca JWT): o servidor guarda só `sha256(token)` em `sessoes`,
vale 24 h (`MAGNO_TOKEN_TTL_MIN`) e é revogável de verdade no logout. O cliente manda
`Authorization: Bearer <token>` — o esquema é case-insensitive (`bearer`, `BEARER`), o token não.

Legenda: 🔒 = rota que exige `Authorization: Bearer`, senão `401 {"codigo":"sessao_invalida"}`.

| Método | Rota | Body / Resposta |
|---|---|---|
| POST | `/api/auth/cadastro` | `{nome, telefone, pin, email?, consentimento_lgpd}` → `200 {token, usuario}` |
| POST | `/api/auth/login` | `{telefone, pin}` → `200 {token, usuario}` · `401` genérico · `429` lockout |
| POST | `/api/auth/codigo` | `{email, nome?}` → `200 {enviado, expira_em, minutos}` · `429 aguarde` (1/min, 3/15 min por e-mail+IP) |
| POST | `/api/auth/verificar` | `{email, codigo, nome?}` → `200 {token, usuario, conta_nova}` · `401 codigo_invalido` |
| POST | `/api/auth/entrar-senha` | `{email, senha}` → `200 {token, usuario}` (senha é atalho opcional) |
| POST | `/api/auth/senha` 🔒 | `{senha}` — cria/troca a senha da conta logada |
| GET | `/api/auth/google/iniciar?destino=/account` | redireciona ao consentimento do Google (`state` de uso único, 10 min) |
| GET | `/api/auth/google/callback` | volta para `/login?next=<destino>#entrar=<token>` |
| GET | `/api/auth/me` 🔒 | dados do usuário logado |
| PATCH | `/api/auth/telefone` 🔒 | `{telefone}` — conta só-Google completa o número |
| POST | `/api/auth/logout` 🔒 | revoga a sessão atual → `{ok:true}` |
| POST | `/api/auth/logout-all` 🔒 | revoga todas as sessões da conta (recuperação) → `{ok:true}` |

`destino` aceita **só** `/account` e `/perfil`: qualquer outro valor (inclusive URL externa)
cai em `/account` — proteção contra open redirect no retorno do OAuth.

**PIN (D16):** 4 a 6 dígitos, só números. No cadastro são recusados PINs triviais
(`0000`, `1234`, `4321`, sequências, todos os dígitos iguais e igual aos 4–6 últimos dígitos
do próprio telefone). O PIN é gravado em `pbkdf2_sha256`, nunca em claro.

Login: máx. 5 falhas / 15 min por telefone+IP → `429` com `{"esperar_seg": n}`.
Mensagem de credencial inválida é sempre a mesma (não revela se o telefone existe).
Turnstile: campo opcional `captcha_token` — só é validado se `TURNSTILE_SECRET_KEY`
estiver configurada (hook inerte por padrão).

### `usuario` (o que o front recebe sobre a conta)

```json
{"id": 17, "nome": "João da Silva", "idade": 24, "papel": "cliente",
 "telefone": "5513997630784", "telefone_formatado": "(13) 99763-0784",
 "email": "joao@exemplo.test", "email_verificado": true, "foto_url": null,
 "tem_senha": false, "tem_google": true, "precisa_telefone": false, "perfil_completo": true}
```
`perfil_completo` é `nome` preenchido **e** `idade` informada. Quem tem `false` é levado para
`/perfil` antes de ver a agenda (e o backend recusa agendar sem isso, via a própria tela).
Nunca sai daqui o hash do PIN/senha nem o `google_sub`.

## 3. Cliente autenticado

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/account` 🔒 | `{usuario, agendamentos[]}` — sempre só a própria conta |
| PATCH | `/api/account/profile` 🔒 | `{nome, idade}` → `{usuario}` (grava o perfil do primeiro acesso) |
| POST | `/api/bookings` 🔒 | `{name, phone, service, barber, date, time}` → `201 {agendamento}` · `409 horario_ocupado` · `400 horario_passado` |

Páginas (HTML, servidas na mesma origem, sem dado pessoal nenhum — o JS só libera a tela
depois de validar o Bearer em `/api/account`):

| Rota | Arquivo | Papel |
|---|---|---|
| `/login` | `web/entrar.html` | entrar: e-mail+código (principal), Google, senha, telefone+PIN |
| `/perfil` | `web/perfil.html` | primeiro acesso: nome → idade → agenda (`no-store`) |
| `/account` | `web/conta.html` | agenda do cliente, com o nome vindo do perfil (`no-store`) |

Ainda no backlog da F4 (não implementado): `/api/meus-agendamentos`, remarcar
(`PATCH /api/agendamentos/{id}`), cancelar, `.ics` e `DELETE /api/me/conta` (LGPD).

Regras: só o dono enxerga/altera o próprio agendamento (senão `403`, nunca `404` vazando
existência); cancelar/remarcar respeita `cancelamento_limite_h` (depois disso →
`403 {"codigo":"prazo_excedido"}`) e apenas para status `agendado|confirmado`.

## 4. Loja — barbeiro e admin

### Agenda (barbeiro ✅ / admin ✅)

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/admin/agenda?de=&ate=&profissional_id=` | agendamentos do período (default: hoje, hora local) |
| GET | `/api/admin/proximos?limite=20&profissional_id=` | próximos atendimentos ordenados |
| PATCH | `/api/admin/agendamentos/{id}` | `{inicio?, profissional_id?, status?, observacao?}` |
| DELETE | `/api/admin/agendamentos/{id}` | remove atendimento futuro (hard delete, só admin) |
| GET | `/api/admin/clientes?busca=` | clientes com contagem e último atendimento |
| GET | `/api/admin/clientes/{id}` | histórico do cliente + no-shows |

Transições de status aceitas: `agendado|confirmado → concluido`, `→ nao_compareceu`,
`→ cancelado_loja`; `cancelado_*`/`concluido` → `agendado` **só admin** (reabertura
registrada em `eventos`). Qualquer transição fora disso → `400 codigo=transicao_invalida`.

### Cadastros e configuração (só admin)

| Método | Rota | Descrição |
|---|---|---|
| GET/POST | `/api/admin/servicos` | lista / cria (nome, duração, preço, ativo, ordem, imagem) |
| PATCH/DELETE | `/api/admin/servicos/{id}` | edita / desativa (DELETE vira `ativo=0` se houver histórico) |
| GET/POST | `/api/admin/profissionais` | lista (com serviços) / cria barbeiro (cria o `usuario` + senha inicial) |
| PATCH | `/api/admin/profissionais/{id}` | edita bio, foto, ordem, ativo, serviços habilitados |
| GET/PUT | `/api/admin/horarios` | funcionamento por dia da semana |
| GET/POST/PATCH/DELETE | `/api/admin/excecoes` | feriados e horários especiais |
| GET/POST/DELETE | `/api/admin/bloqueios` | folgas/almoço por profissional (intervalo UTC) |
| GET/PUT | `/api/admin/config` | regras de negócio (`slot_min`, `buffer_min`, `antecedencia_min_h`, `janela_dias`, `cancelamento_limite_h`, textos da home) |
| GET | `/api/admin/relatorio?tipo=agendamentos&de=&ate=` | CSV (`;`, BOM UTF-8) — agendamentos, clientes, faturamento por período |

## 5. Padrão de resposta da agenda

```json
{
  "periodo": {"de": "2026-09-15T03:00:00Z", "ate": "2026-09-16T03:00:00Z", "fuso": "America/Sao_Paulo"},
  "profissionais": [{"id": 2, "nome": "Rafael", "cor": "#c08a3e"}],
  "agendamentos": [
    {
      "id": 91, "codigo": "mg-7f3a91c2",
      "inicio": "2026-09-15T13:00:00Z", "fim": "2026-09-15T14:05:00Z",
      "cliente": {"id": 17, "nome": "João da Silva", "telefone": "5513997630784"},
      "profissional_id": 2, "servico": {"id": 3, "nome": "Corte + barba"},
      "status": "agendado", "preco_centavos": 7000, "observacao": "máquina 2",
      "pode_cancelar_cliente": false
    }
  ]
}
```
Nota: cliente vê só o próprio telefone; barbeiro vê o do dia (precisa ligar para o cliente).

## 6. Códigos de erro padronizados

| HTTP | `codigo` | Quando |
|---|---|---|
| 400 | `validacao` | payload inválido (campo/mensagem por campo) |
| 401 | `sessao_invalida` | token ausente, expirado ou revogado |
| 403 | `sem_permissao` | papel insuficiente |
| 403 | `prazo_excedido` | política de cancelamento do cliente |
| 404 | `nao_encontrado` | recurso inexistente (ou de outro dono) |
| 409 | `slot_ocupado` | conflito de horário / buffer |
| 413 | `corpo_grande` | corpo acima de 1 MB |
| 429 | `rate_limit` / `lockout` | anti-spam e login |
