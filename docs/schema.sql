-- Barbearia Magno — schema v2 (SQLite)
-- Regras: timestamps em UTC ISO-8601 ('2026-09-10T18:00:00Z'); dinheiro em centavos (inteiro);
-- telefone em E.164 só dígitos (ex: 5513997630784). SQL 100% parametrizado na aplicação.
--
-- v2 (login): usuarios passa a aceitar duas formas de entrada — telefone+PIN (cliente da loja)
-- ou Google (login social). Por isso `telefone` e `senha_hash` são NULÁVEIS e `google_sub`
-- guarda o identificador do Google. A regra "todo usuário tem como entrar" virou CHECK.
-- v3 (código por e-mail): a entrada principal passa a ser e-mail + código de 5 dígitos.
-- Senha (PIN) vira OPCIONAL — quem quiser entra sem senha nenhuma. Tabela `codigos_email`
-- guarda o código com hash, validade curta e limite de tentativas.
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- pessoas
CREATE TABLE IF NOT EXISTS usuarios (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  nome                 TEXT    NOT NULL,
  idade                INTEGER CHECK (idade BETWEEN 13 AND 120),
  telefone             TEXT    UNIQUE,         -- E.164 sem '+' — NULL se não informado ainda
  email                TEXT,                   -- entrada principal (código por e-mail)
  email_verificado_em  TEXT,                   -- quando o código foi confirmado
  senha_hash           TEXT,                   -- OPCIONAL (PIN/senha de quem quiser atalho)
  google_sub           TEXT,                   -- 'sub' do Google (NULL se nunca usou Google)
  foto_url             TEXT,                   -- foto do perfil Google
  papel                TEXT    NOT NULL DEFAULT 'cliente'
                               CHECK (papel IN ('cliente','barbeiro','admin')),
  ativo                INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1)),
  consentimento_lgpd_em TEXT,                  -- data do aceite (LGPD)
  anonimizado_em       TEXT,                   -- preenchido na exclusão de conta
  ultimo_login_em      TEXT,
  criado_em            TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  atualizado_em        TEXT,
  -- sem senha, sem Google e sem e-mail a conta não teria como entrar
  CHECK (senha_hash IS NOT NULL OR google_sub IS NOT NULL OR email IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_usuarios_papel ON usuarios(papel, ativo);
-- um e-mail só pode pertencer a uma conta (ignorando maiúsculas); NULLs não contam
CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_email
  ON usuarios(lower(email)) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_google
  ON usuarios(google_sub) WHERE google_sub IS NOT NULL;

-- códigos de verificação enviados por e-mail (login sem senha)
CREATE TABLE IF NOT EXISTS codigos_email (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  email       TEXT    NOT NULL,             -- sempre minúsculo
  codigo_hash TEXT    NOT NULL,             -- pbkdf2 do código: o código em claro não fica no banco
  expira_em   TEXT    NOT NULL,
  tentativas  INTEGER NOT NULL DEFAULT 0,   -- 5 tentativas e o código morre
  usado_em    TEXT,
  ip          TEXT,
  criado_em   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_codigos_email ON codigos_email(email, criado_em DESC);

-- profissional = usuario com papel barbeiro (1:1). Tabela separada para perfil público.
CREATE TABLE IF NOT EXISTS profissionais (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  usuario_id INTEGER NOT NULL UNIQUE REFERENCES usuarios(id) ON DELETE CASCADE,
  apelido    TEXT,
  bio        TEXT,
  foto_url   TEXT,
  ordem      INTEGER NOT NULL DEFAULT 0,
  ativo      INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1))
);

-- ---------------------------------------------------------------- catálogo
CREATE TABLE IF NOT EXISTS servicos (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  nome           TEXT    NOT NULL,
  descricao      TEXT,
  duracao_min    INTEGER NOT NULL CHECK (duracao_min BETWEEN 5 AND 480),
  preco_centavos INTEGER NOT NULL CHECK (preco_centavos >= 0),
  imagem_url     TEXT,
  ordem          INTEGER NOT NULL DEFAULT 0,
  ativo          INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1)),
  criado_em      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- quais profissionais executam quais serviços (N:N)
CREATE TABLE IF NOT EXISTS servico_profissional (
  servico_id      INTEGER NOT NULL REFERENCES servicos(id) ON DELETE CASCADE,
  profissional_id INTEGER NOT NULL REFERENCES profissionais(id) ON DELETE CASCADE,
  PRIMARY KEY (servico_id, profissional_id)
);

-- ---------------------------------------------------------------- disponibilidade
-- horário de funcionamento recorrente da loja (0=domingo ... 6=sábado)
CREATE TABLE IF NOT EXISTS horarios (
  dia_semana INTEGER PRIMARY KEY CHECK (dia_semana BETWEEN 0 AND 6),
  abre       TEXT NOT NULL,            -- 'HH:MM' local (America/Sao_Paulo)
  fecha      TEXT NOT NULL,
  ativo      INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0,1)),
  CHECK (fecha > abre)
);

-- exceções por data (feriado fechado / horário especial)
CREATE TABLE IF NOT EXISTS excecoes (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  data    TEXT NOT NULL UNIQUE,        -- 'YYYY-MM-DD' local
  fechado INTEGER NOT NULL DEFAULT 1 CHECK (fechado IN (0,1)),
  abre    TEXT,
  fecha   TEXT,
  motivo  TEXT
);

-- indisponibilidade pontual de um profissional (almoço, folga, curso)
CREATE TABLE IF NOT EXISTS bloqueios (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  profissional_id INTEGER NOT NULL REFERENCES profissionais(id) ON DELETE CASCADE,
  inicio          TEXT NOT NULL,       -- UTC ISO
  fim             TEXT NOT NULL,
  motivo          TEXT,
  criado_em       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  CHECK (fim > inicio)
);
CREATE INDEX IF NOT EXISTS idx_bloqueios_prof ON bloqueios(profissional_id, inicio);

-- ---------------------------------------------------------------- agenda
CREATE TABLE IF NOT EXISTS agendamentos (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  codigo             TEXT    NOT NULL UNIQUE,          -- id público (link/consulta/ics)
  cliente_id         INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
  profissional_id    INTEGER NOT NULL REFERENCES profissionais(id),
  servico_id         INTEGER NOT NULL REFERENCES servicos(id),
  inicio             TEXT    NOT NULL,                 -- UTC ISO
  fim                TEXT    NOT NULL,                 -- UTC ISO (inclui buffer)
  duracao_min        INTEGER NOT NULL,                 -- snapshots (preço/duração não mudam depois)
  preco_centavos     INTEGER NOT NULL,
  status             TEXT    NOT NULL DEFAULT 'agendado'
                             CHECK (status IN ('agendado','confirmado','concluido',
                                               'cancelado_cliente','cancelado_loja','nao_compareceu')),
  observacao         TEXT,                             -- pedido do cliente (ex: "máquina 2")
  origem             TEXT    NOT NULL DEFAULT 'cliente' CHECK (origem IN ('cliente','loja')),
  criado_em          TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  atualizado_em      TEXT,
  cancelado_em       TEXT,
  cancelado_por      INTEGER REFERENCES usuarios(id),
  motivo_cancelamento TEXT,
  CHECK (fim > inicio)
);
CREATE INDEX IF NOT EXISTS idx_ag_prof_inicio  ON agendamentos(profissional_id, inicio);
CREATE INDEX IF NOT EXISTS idx_ag_cliente      ON agendamentos(cliente_id, inicio DESC);
CREATE INDEX IF NOT EXISTS idx_ag_status_inicio ON agendamentos(status, inicio);
-- trava dura contra overbooking: um profissional não tem dois atendimentos no mesmo instante
CREATE UNIQUE INDEX IF NOT EXISTS idx_ag_slot_unico
  ON agendamentos(profissional_id, inicio)
  WHERE status IN ('agendado','confirmado','concluido');

-- ---------------------------------------------------------------- sessões e auditoria
CREATE TABLE IF NOT EXISTS sessoes (
  token_hash TEXT PRIMARY KEY,        -- sha256(token) — o token em claro nunca é gravado
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  criada_em  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  expira_em  TEXT NOT NULL,
  revogada_em TEXT,
  ip         TEXT,
  user_agent TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessoes_usuario ON sessoes(usuario_id);

-- estados temporários do login Google (proteção CSRF): o `state` vive aqui até o retorno
CREATE TABLE IF NOT EXISTS logins_pendentes (
  state      TEXT PRIMARY KEY,
  criado_em  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  expira_em  TEXT NOT NULL,
  destino    TEXT,
  ip         TEXT
);

CREATE TABLE IF NOT EXISTS eventos (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  tipo        TEXT NOT NULL,          -- agendamento.criado, usuario.excluido, login.google...
  ator_id     INTEGER REFERENCES usuarios(id),
  agendamento_id INTEGER,
  payload     TEXT,                   -- JSON
  criado_em   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_eventos_tipo ON eventos(tipo, criado_em DESC);

-- ---------------------------------------------------------------- configurações
CREATE TABLE IF NOT EXISTS configuracoes (
  chave  TEXT PRIMARY KEY,
  valor  TEXT NOT NULL,
  descricao TEXT
);

-- ---------------------------------------------------------------- seed (idempotente)
INSERT OR IGNORE INTO configuracoes (chave, valor, descricao) VALUES
  ('slot_min',              '30',                    'Granularidade da grade, em minutos'),
  ('buffer_min',            '5',                     'Intervalo entre atendimentos'),
  ('antecedencia_min_h',    '1',                     'Antecedência mínima para agendar'),
  ('janela_dias',           '60',                    'Máximo de dias à frente exibidos ao cliente'),
  ('cancelamento_limite_h', '2',                     'Prazo mínimo para o cliente cancelar/remarcar'),
  ('fuso',                  'America/Sao_Paulo',     'Fuso de exibição'),
  ('loja_nome',             'Barbearia Magno',       'Nome exibido no site'),
  ('loja_telefone',         '',                      'WhatsApp da loja (E.164)'),
  ('loja_endereco',         '',                      'Endereço exibido no site'),
  ('loja_instagram',        '',                      'Instagram exibido no site'),
  ('loja_sobre',            '',                      'Texto institucional da home'),
  ('site_publico',          '1',                     'Site institucional no ar (1/0)');

INSERT OR IGNORE INTO horarios (dia_semana, abre, fecha, ativo) VALUES
  (0,'09:00','13:00',0),   -- domingo fechado
  (1,'09:00','19:00',1),(2,'09:00','19:00',1),(3,'09:00','19:00',1),
  (4,'09:00','19:00',1),(5,'09:00','20:00',1),(6,'08:00','18:00',1);

INSERT OR IGNORE INTO servicos (id, nome, descricao, duracao_min, preco_centavos, ordem) VALUES
  (1,'Corte masculino','Corte na tesoura ou máquina, finalização com pomada.',30,4500,1),
  (2,'Barba','Barba na navalha com toalha quente.',30,3500,2),
  (3,'Corte + barba','Combo completo.',60,7000,3),
  (4,'Degradê navalhado','Fade com acabamento na navalha.',45,5500,4);
