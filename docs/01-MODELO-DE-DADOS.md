# Modelo de dados — Barbearia Magno v1

Arquivo executável: `docs/schema.sql` (validado no SQLite — criação + seed rodam limpos).

## Visão geral das relações

```
usuarios 1───1 profissionais ───N:N─── servicos        (servico_profissional)
   │                 │
   │                 └──N bloqueios
   └──N agendamentos ──N──┘
                         └── servicos
horarios (7 linhas fixas)   excecoes (datas)   configuracoes (chave/valor)   eventos (auditoria)
sessoes (token_hash → usuarios)
```

## Convenções (valem para todo o banco)

| Item | Regra | Por quê |
|---|---|---|
| Timestamps | UTC ISO-8601 com `Z` (`2026-09-10T18:00:00Z`) | comparação e ordenação ficam triviais; conversão só na borda |
| Dinheiro | inteiro em centavos | nunca float em preço |
| Telefone | E.164 só dígitos (`5513997630784`) | identificador natural do cliente, `UNIQUE` |
| Dias "fechados"/"ativo" | `INTEGER 0/1` com `CHECK` | SQLite não tem boolean |
| Datas de exceção | `YYYY-MM-DD` local | feriado é conceito local, não UTC |
| Exclusão | soft (status/motivo) por padrão; hard delete só do admin, sempre com evento | auditoria e relatório |

## Tabelas

### `usuarios`
Todo mundo que entra no sistema: cliente, barbeiro e admin — a diferença é `papel`.
- `telefone` é o login do cliente (único). `email` é opcional.
- `senha_hash` = `pbkdf2_sha256$<iter>$<salt>$<hash>`.
- `consentimento_lgpd_em` guarda a data do aceite; `anonimizado_em` marca conta excluída
  (o registro fica para o relatório, mas sem dado pessoal).

### `profissionais`
Perfil público do barbeiro, 1:1 com `usuarios` (papel `barbeiro`). Separada porque tem
dados próprios (bio, foto, ordem de exibição, ativo) sem poluir `usuarios`.

### `servicos` + `servico_profissional`
Catálogo. `duracao_min` alimenta a grade; `preco_centavos` é copiado para o agendamento no
momento da criação (snapshot — mudar o preço depois não reescreve o histórico).
`servico_profissional` define quem executa o quê (a UI só oferece barbeiros habilitados).

### `horarios`
7 linhas fixas (0=domingo … 6=sábado) com `abre`/`fecha` em hora local. Base da grade.
`ativo = 0` fecha o dia inteiro (ex: domingo).

### `excecoes`
Uma linha por data especial: `fechado = 1` (feriado) ou horário diferente nesse dia.
Vence `horarios`.

### `bloqueios`
Indisponibilidade pontual de um profissional em UTC (almoço, folga, curso). Vence a grade
normal e nunca gera slot.

### `agendamentos`
O coração. Campos importantes:
- `codigo` — id público (`mg-7f3a91c2`) usado em link de consulta, `.ics` e confirmação,
  sem expor o id sequencial.
- `inicio`/`fim` em UTC; `fim` **já inclui o buffer** (o cliente vê 10:00–10:30, a agenda
  reserva 10:00–10:35).
- `duracao_min` e `preco_centavos` são snapshots.
- `status`: `agendado` → `confirmado` → `concluido`; saídas `cancelado_cliente`,
  `cancelado_loja`, `nao_compareceu`.
- `origem` distingue quem criou (cliente pelo site ou balcão).

**Índices e travas de integridade:**
- `idx_ag_slot_unico` — índice único parcial em `(profissional_id, inicio)` para status
  ativos: é a trava dura contra two-writes no mesmo horário, mesmo com duas requisições
  simultâneas (a checagem em código é complementar, não a única defesa).
- `idx_ag_prof_inicio` — a consulta da agenda e o cálculo de disponibilidade usam este.
- `idx_ag_cliente` — "meus agendamentos".
- `idx_ag_status_inicio` — "próximos atendimentos" e o job de expiração sob demanda.

### `sessoes`
Token opaco: o banco guarda apenas `sha256(token)`. Logout real = `revogada_em = agora`
(401 imediato). Purga de sessões velhas a cada login.

### `eventos`
Auditoria append-only: criação, remarcação, cancelamento, exclusão, mudança de status e
exclusão de conta. É o que permite responder "quem apagou o atendimento das 15h?".

### `configuracoes`
Chave/valor com as regras de negócio (slot, buffer, antecedência, janela, política de
cancelamento, textos do site). Editável pelo admin na tela de Configurações — **nenhuma
dessas constantes vive no código**.

## Consultas críticas (as que precisam estar certas)

**1. Conflito de horário (overbooking)** — roda dentro de `BEGIN IMMEDIATE`:
```sql
SELECT 1 FROM agendamentos
 WHERE profissional_id = ?
   AND status IN ('agendado','confirmado','concluido')
   AND inicio < :fim_novo AND fim > :inicio_novo     -- overlap de intervalos
 LIMIT 1;
```

**2. Agenda de um dia** (`de`/`ate` em UTC, filtro opcional por profissional):
```sql
SELECT a.*, u.nome AS cliente_nome, s.nome AS servico_nome
  FROM agendamentos a
  LEFT JOIN usuarios u ON u.id = a.cliente_id
  JOIN servicos  s ON s.id = a.servico_id
 WHERE a.inicio >= :de AND a.inicio < :ate
   AND a.status IN ('agendado','confirmado')
 ORDER BY a.inicio;
```

**3. Ocupação para o motor de disponibilidade** (uma query só por dia/profissional —
nada de N+1). Está em `server/agenda.py:ocupacao()`:
```sql
SELECT inicio, fim FROM agendamentos
 WHERE profissional_id = ? AND status IN ('agendado','confirmado','concluido')
   AND inicio >= :de AND inicio < :ate
 UNION ALL
SELECT inicio, fim FROM bloqueios
 WHERE profissional_id = ? AND inicio < :ate AND fim > :de;
```

**4. Expiração sob demanda (sem cron):** ao ler a agenda/próximos, roda
```sql
UPDATE agendamentos SET status='nao_compareceu', atualizado_em=:agora
 WHERE status IN ('agendado','confirmado') AND fim < :agora_menos_6h;
```
idempotente e barato — o barbeiro não precisa marcar no-show manualmente.

## Pitfalls já comprovados (script `scripts/valida_schema.py`, 17 checks)

- **O buffer vive dentro de `fim`, não numa coluna à parte.** Consequência: o próximo
  atendimento pode começar exatamente em `fim` (13:00–13:30 + 5 min → `fim` 13:35, e um novo
  às 13:35 não conflita), enquanto o slot seguinte da grade (13:30) é recusado. Se o buffer
  fosse só um offset na hora de checar, o mesmo par geraria dois resultados diferentes
  dependendo da ordem das checagens. `fim = inicio + duracao_min + buffer_min`, calculado
  **uma vez** na criação e na remarcação.
- **Python + sqlite3 deixa a transação aberta depois de uma exceção.** Sem `rollback()` após
  um erro esperado (ex: violação de índice único), a conexão continua segurando o lock e
  qualquer outra conexão recebe `database is locked` — foi exatamente o que derrubou o teste
  de concorrência na primeira execução. Regra para o F3: todo `except IntegrityError` faz
  `rollback()` antes de responder 409.
- **`BEGIN IMMEDIATE` + índice único parcial são complementares** e ambos passaram no teste
  de duas threads simultâneas: uma escrita criou (201), a outra foi recusada — e a query de
  auditoria confirmou zero horários duplicados. É o que `agenda.marcar()` faz: `BEGIN
  IMMEDIATE` → `conferir()` de novo dentro da transação → `INSERT` → `commit`, com `rollback`
  em todo caminho de erro.
- **Quem entra na conta do buffer é o candidato, não a linha ocupada.** Ao procurar vaga, o
  motor testa `[inicio, inicio + duracao + buffer)` contra o que já está marcado — por isso
  marcar 09:00 (30 min) tira da grade 09:00 **e** 09:30, e 10:00 continua livre. Linhas antigas,
  criadas antes do motor entrar no ar, têm `fim` sem o buffer (o `POST` daquela época somava só
  a duração); o cálculo de vaga trata as duas formas como intervalo, sem quebrar.
- **Índice único parcial com `status IN (...)`** precisa ser criado **depois** de a tabela
  existir com a coluna `status` (ordem do script importa numa migração futura).


## Migração futura
SQLite sem Alembic: cada migração nova é `PRAGMA table_info(...)` → se faltar coluna,
`ALTER TABLE ADD COLUMN`; mudança estrutural → recriar tabela (foreign_keys OFF → CREATE
novo → INSERT SELECT com transformação → DROP → RENAME → recriar índices → ON).
Todo seed novo usa `INSERT OR IGNORE` por chave (nunca `if COUNT == 0`).
