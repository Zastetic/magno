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
| GET | `/api/saude` | health-check (`{"ok":true,"hora":"...","banco":{...},"regras":{...}}`) |
| GET | `/api/publica/config` | o que o site pode saber sem login (chave do CAPTCHA, WhatsApp) |
| GET | `/api/publica/site` | textos institucionais, endereço, WhatsApp, Instagram, horários de funcionamento *(backlog F2)* |
| GET | `/api/publica/servicos` | serviços ativos (`id`, `nome`, `descricao`, `duracao_min`, `preco_centavos`, `preco` e `duracao` já formatados, `imagem_url`) |
| GET | `/api/publica/equipe?servico_id=` | profissionais ativos (`id`, `nome`, `apelido`, `bio`, `foto_url`, `servicos[]`); com `servico_id`, só quem executa aquele serviço |
| GET | `/api/publica/disponibilidade` | **a grade de verdade** — slots livres por profissional |
| POST | `/api/publica/agendar` | cria agendamento sem login *(backlog: o fluxo de hoje é `POST /api/bookings` com Bearer)* |
| GET | `/api/agendamentos/{codigo}/ics` | arquivo `.ics` do agendamento *(backlog)* |

### `GET /api/publica/disponibilidade`

`servico_id` é obrigatório; `profissional_id` é opcional (sem ele, devolve todos os
habilitados). A janela vem em **uma das duas formas**:

- `data=YYYY-MM-DD` (hora local da loja) → slots livres daquele dia;
- `de`/`ate` (até 31 dias) → contagem por dia, para a tira de dias do site (uma requisição
  em vez de 21).

Resposta 200 com `data`:
```json
{
  "servico_id": 1, "duracao_min": 30, "fuso": "America/Sao_Paulo", "data": "2026-09-15",
  "profissionais": [
    { "profissional_id": 1, "nome": "Rafael", "apelido": "Rafael",
      "slots": ["2026-09-15T12:00:00Z", "2026-09-15T13:00:00Z", "2026-09-15T17:30:00Z"],
      "motivo_vazio": null }
  ],
  "motivo_vazio": null,
  "motivo_texto": null
}
```

Resposta 200 com `de`/`ate`:
```json
{
  "servico_id": 1, "duracao_min": 30, "fuso": "America/Sao_Paulo",
  "de": "2026-09-15", "ate": "2026-09-21",
  "dias": [
    {"data": "2026-09-15", "livres": 12, "primeiro": "2026-09-15T12:00:00Z",
     "motivo_vazio": null, "motivo_texto": null},
    {"data": "2026-09-20", "livres": 0, "primeiro": null,
     "motivo_vazio": "loja_fechada", "motivo_texto": "A loja está fechada nesse dia."}
  ]
}
```

Os slots saem em **UTC ISO** (quem formata é o navegador, com o `fuso` da resposta). O dia só
aparece com slot se o serviço **cabe** no funcionamento daquele dia (grade de `slot_min` a
partir da abertura, sem slot parcial no fim), o horário está fora do prazo morto
(`antecedencia_min_h`), dentro da `janela_dias`, o profissional não tem agendamento ativo nem
`bloqueio` encostando (o buffer do candidato conta) e a loja está aberta (`horarios` +
`excecoes`, com exceção vencendo o horário semanal).

`motivo_vazio` explica quando não há slot nenhum: `"loja_fechada"`, `"fora_da_janela"`,
`"sem_profissional_habilitado"`, `"antecedencia_minima"`, `"dia_lotado"`, `"sem_espaco_no_dia"`.
`motivo_texto` traz a mesma coisa em pt-BR, pronta para a tela mostrar (nunca tela vazia).

Erros: `400 validacao` (falta `data`/`de`+`ate`, data mal formada, mais de 31 dias) e
`404 nao_encontrado` (serviço inexistente/inativo, ou barbeiro que não faz o serviço).

### `POST /api/bookings` (cliente autenticado)

```json
{"name": "João da Silva", "phone": "13997630784", "service": "Corte masculino",
 "barber": "Rafael", "date": "2026-09-15", "time": "13:00"}
```
- `201` → `{"agendamento": {"codigo": "mg-7f3a91c2", "inicio": "...Z", "servico": "...", "barbeiro": "Rafael", "duracao_min": 30, "preco_centavos": 4500}}`
- `409 horario_ocupado` — alguém chegou antes (ou o buffer do atendimento anterior encosta no horário)
- `409 ja_tem_agendamento` — o próprio cliente já tem outro agendamento ativo sobreposto
- `400 horario_passado` — no passado ou dentro de `antecedencia_min_h`
- `400 horario_invalido` — fora da grade (minuto quebrado, fora do funcionamento, dia fechado, fora da `janela_dias`)
- `404 indisponivel` — serviço/barbeiro inativo ou combinação que não existe em `servico_profissional`
- `401 sessao_invalida` sem Bearer · `429` no freio de 12 agendamentos/hora por IP

O horário pedido é conferido por `server/agenda.py:conferir()` — **a mesma função que desenha
a grade** — e gravado por `agenda.marcar()` em `BEGIN IMMEDIATE` (checagem + `INSERT` na mesma
transação; o índice único parcial é a segunda linha de defesa). `fim` já inclui o `buffer_min`.

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
| POST | `/api/bookings` 🔒 | `{name, phone, service, barber, date, time}` → `201 {agendamento}` · `409 horario_ocupado` (ocupado/buffer) · `409 ja_tem_agendamento` (dois horários do mesmo cliente) · `400 horario_passado` · `400 horario_invalido` (fora da grade/fechado/fora da janela) — a grade vem de `/api/publica/disponibilidade` |

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
| 409 | `horario_ocupado` / `ja_tem_agendamento` | conflito de horário, buffer, ou o cliente já tem agendamento sobreposto |
| 400 | `horario_passado` / `horario_invalido` | horário no passado, sem a antecedência mínima, fora da grade ou dia fechado |
| 413 | `corpo_grande` | corpo acima de 1 MB |
| 429 | `rate_limit` / `lockout` | anti-spam e login |
