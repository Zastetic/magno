# Decisões — Barbearia Magno v1

## Decisionos já tomadas (recomendadas pelo plano, podem ser revertidas)

| # | Decisão | Escolha | Motivo |
|---|---|---|---|
| D1 | Stack backend | FastAPI + SQLite, servindo também o SPA | mesmo padrão do `biblioteca_escolar/mvp`, já em produção no WSL; sem servidor extra |
| D2 | Porta local | 8100 | verificada livre (8080 e 8099 ocupadas por outros projetos) |
| D3 | Pasta | `~/magno` → `/mnt/d/projetos_wsl/magno` | convenção dos projetos do Okai (D: guarda os dados) |
| D4 | Timestamps | UTC ISO-8601 no banco, `America/Sao_Paulo` na tela | evita o bug clássico de horário deslocado |
| D5 | Dinheiro | inteiro em centavos | nunca float em preço |
| D6 | Telefone | identificador natural do cliente (E.164, único) | barbeiro pensa em telefone, não em e-mail |
| D7 | Cancelamento | não apaga: marca `cancelado_*` + motivo | preserva histórico e relatório |
| D8 | Exclusão pelo admin | permitida e definitiva para atendimento **futuro**, com registro em `eventos` | é o pedido explícito do dono ("ler e deletar futuros atendimentos") |
| D9 | Overbooking | `BEGIN IMMEDIATE` + checagem de overlap + índice único parcial | duas defesas: nenhuma corrida passa |
| D10 | Buffer | 5 min depois de cada atendimento (configurável) | evita encavalamento real no balcão |
| D11 | Fuso do dia | dia "da loja" = 00:00–23:59 em SP, convertido para UTC na query | agenda funciona por dia local |
| D12 | Túnel | reaproveitar o túnel Cloudflare existente (`autoava.us`), com novo Public Hostname | um conector serve os dois sites; nada de criar túnel novo |
| D13 | Sem build no front | SPA vanilla servida pelo backend | MVP mais rápido de subir e depurar (ver D-P3) |
| D14 | Turnstile | hook pronto, **desligado** | sitekey é presa ao domínio; ativar só com domínio fixo no ar |
| D15 | Backup | cópia diária do `.db` (14 versões, `PRAGMA quick_check`) via cronjob do Hermes | mesmo esquema da biblioteca |

## Pendentes — preciso da sua resposta antes de codar

### P1. Login do cliente (define a arquitetura de auth)
- **(a) Telefone + PIN de 4–6 dígitos** — *recomendado*. Cadastro em 20 s no balcão:
  nome, telefone e PIN. Sem e-mail, sem confirmação, sem custo.
- (b) Telefone + senha comum — igual à (a), mais fricção ao digitar no celular.
- (c) Telefone + código por SMS — melhor UX, mas exige gateway pago (não temos).
- (d) Sem conta: o cliente agenda com nome+telefone e gerencia pelo link/código enviado
  (`magnum.autoava.us/a/mg-7f3a91c2`) — zero cadastro, porém qualquer um com o código vê o
  agendamento.

### P2. A "parte mínima que não é agenda" (qual escopo?)
- **(a) Site institucional + catálogo de serviços/preços editável** — *recomendado*: home
  (sobre, serviços com preço e duração, equipe com foto/bio, endereço, horário, WhatsApp,
  Instagram). Sai do banco, então o dono edita sem programador, e é a mesma base da agenda.
- (b) (a) + galeria de cortes (upload de fotos por serviço/barbeiro).
- (c) (a) + caixa simples do dia (total atendido, faturamento, ticket médio).
- (d) Só um landing estático de apresentação (menor esforço, quase nada para demonstrar).

### P3. Frontend
- **(a) SPA vanilla (JS/CSS puros) servida pelo backend** — *recomendado*: zero build,
  sobe em minutos, casa com o padrão `secure-fastapi-backend`; mais fácil de eu depurar.
- (b) React + Vite como no `autoava` — mais familiar para você, porém exige `npm run build`
  a cada mudança e um passo de build no deploy.

### P4. Modelo de agenda
- **(a) Um profissional por agendamento, com agenda individual** — *recomendado*: cada
  barbeiro tem a própria coluna/grade; o cliente escolhe com quem cortar.
- (b) Agenda única da loja (sem escolher barbeiro) — mais simples, mas o barbeiro A fica
  "ocupado" por um atendimento do barbeiro B.

### P5. Lembretes
- **(a) Sem envio automático: link "adicionar ao calendário" (.ics) + botão de WhatsApp com
  mensagem pronta** — *recomendado*: custo zero, funciona igual ao que a loja já faz na mão.
- (b) E-mail de confirmação/lembrete (exige endereço de e-mail do cliente e um SMTP).
- (c) WhatsApp automático (API oficial ou gateway não-oficial) — melhor resultado, tem custo
  mensal e risco de bloqueio do número.

## Ação que só você pode fazer (bloqueia o deploy, não o código)

`magnum.autoava.us` **ainda não existe no DNS** (conferido: não resolve). O ingress do
túnel vem do painel, o token do conector não permite editar por CLI. Passos:

1. Entre em `dash.cloudflare.com` → domínio `autoava.us` → **Zero Trust**.
2. **Networks → Tunnels** → abra o túnel do autoava (`b584ba18-040b-4dfd-bf7b-47d890a767d6`).
3. Aba **Public Hostname** → **Add a public hostname**.
4. Subdomain `magnum` · Domain `autoava.us` · Service `HTTP` → `127.0.0.1:8100`.
5. Salvar. O cloudflared puxa a config sozinho (`Updated to new configuration` no log) — e o
   CNAME do DNS é criado automaticamente pela Cloudflare.

Até isso existir, o site fica acessível só em `http://127.0.0.1:8100` ou por um quick tunnel
temporário (`*.trycloudflare.com`) para demonstração.
