# Decisões — Barbearia Magno v1

Todas as decisões de projeto estão fechadas. Nada mais bloqueia o início da F0.

## Decididas pelo Okai (2026-09-09)

| # | Pergunta | Decisão | Consequência técnica |
|---|---|---|---|
| D16 | Login do cliente | **Telefone + PIN de 4 a 6 dígitos** | `usuarios.telefone` é o login (E.164 único) e `senha_hash` guarda o PIN em `pbkdf2_sha256`. Sem e-mail obrigatório, sem SMS. **Segurança obrigatória por causa do PIN curto:** lockout de 5 falhas / 15 min por telefone+IP, mensagem sempre genérica, PIN com no mínimo 4 dígitos e bloqueio de PINs triviais (`1234`, `0000`, data de nascimento = igual aos 6 últimos do telefone), e o token de sessão segue sendo o mecanismo real de autorização. |
| D17 | Parte que não é agenda | **Site institucional + catálogo de serviços/preços editável pelo admin** | Home, equipe, endereço, horário e contato saem da tabela `configuracoes` + `servicos` + `profissionais`. Nada de HTML fixo: o dono edita pela tela de Configurações/Serviços. Sem galeria de fotos própria (só `imagem_url` por serviço/profissional) e sem caixa/faturamento na v1. |
| D18 | Frontend | **SPA vanilla servida pelo backend** | `web/index.html` + `app.js` + `styles.css`, sem build, sem CORS, CSP estrita. `web/` é servido pelo mesmo uvicorn na 8100. |
| D19 | Modelo da agenda | **Agenda por profissional** | Um agendamento pertence a um profissional; a disponibilidade é calculada por profissional; a UI da loja mostra colunas por barbeiro (dia/semana) e o cliente escolhe com quem cortar. `servico_profissional` filtra quem executa o quê. |
| D20 | Lembretes | **Sem envio automático** | `.ics` (link "adicionar ao calendário") + botão de WhatsApp com mensagem pronta no comprovante. Zero custo, zero dependência externa. E-mail/SMS/WhatsApp-API ficam registrados como pós-v1. |

## Decisões técnicas do plano (mantidas)

| # | Decisão | Escolha | Motivo |
|---|---|---|---|
| D1 | Stack backend | FastAPI + SQLite, servindo também o SPA | mesmo padrão do `biblioteca_escolar/mvp`, já em produção no WSL |
| D2 | Porta local | 8100 | verificada livre (8080 e 8099 ocupadas) |
| D3 | Pasta | `~/magno` → `/mnt/d/projetos_wsl/magno` | convenção dos projetos do Okai (D: guarda os dados) |
| D4 | Timestamps | UTC ISO-8601 no banco, `America/Sao_Paulo` na tela | evita horário deslocado |
| D5 | Dinheiro | inteiro em centavos | nunca float em preço |
| D6 | Telefone | identificador natural do cliente (E.164, único) | barbeiro pensa em telefone, não em e-mail |
| D7 | Cancelamento | não apaga: marca `cancelado_*` + motivo | preserva histórico e relatório |
| D8 | Exclusão pelo admin | definitiva para atendimento **futuro**, com evento em `eventos` | pedido explícito do dono ("ler e deletar futuros atendimentos") |
| D9 | Overbooking | `BEGIN IMMEDIATE` + checagem de overlap + índice único parcial | duas defesas — já provado no teste de concorrência |
| D10 | Buffer | 5 min depois de cada atendimento, embutido em `fim` | evita encavalamento real no balcão |
| D11 | Dia da loja | 00:00–23:59 em SP convertido para UTC na query | agenda funciona por dia local |
| D12 | Túnel | reaproveitar o túnel Cloudflare do `autoava.us` com novo Public Hostname | um conector serve os dois sites |
| D13 | Build | nenhum (front vanilla) | conforme D18 |
| D14 | Turnstile | hook pronto, **desligado** | sitekey é presa ao domínio; ativar só com o domínio fixo |
| D15 | Backup | cópia diária do `.db` (14 versões, `PRAGMA quick_check`) via cronjob do Hermes | mesmo esquema da biblioteca |

## Ainda em aberto (não bloqueia; resolver antes do deploy)

1. **Nome e domínio estão com grafias diferentes:** o pedido cita a barbearia "Magno" e o
   domínio `magnum.autoava.us`. O plano usa o domínio como veio e mantém `Barbearia Magno`
   como marca — se for para alinhar, o ajuste é trocar o texto `loja_nome` em `configuracoes`
   (nada no código depende disso). Confirmar antes de subir.
2. **Dados reais da loja** na tela de Configurações: endereço, WhatsApp, Instagram, horário
   real de funcionamento e preços verdadeiros. Hoje o seed tem valores de exemplo.
3. **Quem é o admin** (dono) e quais barbeiros existem — cada um vira um `usuarios` com papel
   `barbeiro` e entra em `profissionais`. As senhas iniciais são trocadas no primeiro acesso.

## Ação que só o Okai pode fazer (bloqueia o deploy, não o código)

`magnum.autoava.us` **ainda não existe no DNS** (conferido: não resolve). O ingress do túnel
vem do painel e o token do conector não permite editar por CLI. Passos:

1. Entrar em `dash.cloudflare.com` → domínio `autoava.us` → **Zero Trust**.
2. **Networks → Tunnels** → abrir o túnel do autoava (`b584ba18-040b-4dfd-bf7b-47d890a767d6`).
3. Aba **Public Hostname** → **Add a public hostname**.
4. Subdomain `magnum` · Domain `autoava.us` · Service `HTTP` → `127.0.0.1:8100`.
5. Salvar. O cloudflared puxa a config sozinho (`Updated to new configuration` no log) e a
   Cloudflare cria o CNAME automaticamente.

Estado atual conferido: as units `autoava-server` e `autoava-tunnel` estão **paradas/disabled**
e não há `cloudflared` rodando — ou seja, hoje o `autoava.us` também está fora do ar. O
`magno-tunnel` vai subir com o mesmo token de conector, então os dois sites sobem juntos se
você quiser reativar o autoava.
