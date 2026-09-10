# Login — como funciona e o que falta para ligar (e-mail e Google)

## Como o cliente entra (ordem de importância)

| Forma | Estado | Observação |
|---|---|---|
| **E-mail + código de 5 dígitos** | ✅ funcionando | entrada principal, **sem senha** (D23) |
| **Google** | ⚠️ código pronto, rodando com provedor de teste | falta colar as credenciais (D22) |
| **Telefone + PIN** | ✅ | atalho para quem quer, e para conta criada no balcão (D16) |
| **Senha opcional** | ✅ | quem quiser cria em Minha conta; pode apagar depois |

O fluxo do e-mail: digita o e-mail → recebe um código de 5 dígitos → digita o código → entrou.
Não existe tela de "criar conta": a conta nasce no primeiro código confirmado.

**Cuidados já implementados:** código com hash no banco (nunca em claro), validade de 10 minutos,
uso único, 5 tentativas por código, no máximo 3 envios por 15 min e 1 por minuto por e-mail+IP,
código novo invalida o anterior.

## ⚠️ Enviar e-mail: o que o domínio precisa

Levantado em 2026-09-10, no DNS de `autoava.us`:

- **MX aponta para a Cloudflare** (`route1/2/3.mx.cloudflare.net`). Ou seja: o domínio
  **recebe** e-mail pelo Cloudflare Email Routing (a caixa que o `cf_email_catcher` lê).
  **Roteamento da Cloudflare não envia** — não dá para mandar código de cliente por ali.
  (Email Workers da Cloudflare só entregam para endereços já verificados na conta: serve para
  os seus, não para os clientes.)
- **Não existe SPF nem DMARC** no domínio hoje. Mandar e-mail sem isso = cai em spam.

Então precisamos de um provedor de envio + registros de DNS (5 minutos no painel Cloudflare):

### Opção A — Brevo (grátis, 300 e-mails/dia) · mais rápida de começar
1. Criar conta em [brevo.com](https://www.brevo.com) (plano grátis).
2. **Senders & IP → Senders → Add a sender**: `magnum@autoava.us`. Como esse endereço **recebe**
   pelo seu Cloudflare, o e-mail de confirmação chega na sua caixa e você clica no link — dá para
   verificar **sem mexer no DNS**.
3. **SMTP & API → SMTP**: pegar host, usuário e a chave SMTP.
4. (Recomendado, melhora a entrega) **Domains → autenticar domínio**: a Brevo mostra os registros
   SPF/DKIM para colar no Cloudflare.

### Opção B — Resend (grátis, 100 e-mails/dia) · melhor entrega
1. Criar conta em [resend.com](https://resend.com).
2. **Domains → Add domain**: `autoava.us` → ele mostra os registros **SPF/DKIM** para colar no
   Cloudflare (aqui não dá para verificar só o endereço).
3. **API Keys → Create**: guardar a chave.

### Opção C — Gmail com senha de app (grátis, 500/dia)
Só vale com conta Google **do domínio** (Workspace). Em Gmail comum, "enviar como"
`magnum@autoava.us` exige alias verificado e a entrega piora (SPF não alinhado).
Precisa: conta Google + verificação em duas etapas + **Senha de app**.

### O que eu preciso que você me passe (uma das três)
```
MAGNO_EMAIL_MODO=smtp | resend | brevo
# se smtp:
MAGNO_SMTP_HOST=...      MAGNO_SMTP_PORTA=587
MAGNO_SMTP_USUARIO=...   MAGNO_SMTP_SENHA=...
# se api:
MAGNO_EMAIL_CHAVE=...
```
Nada disso vai para o git (fica no `.env.local`). Depois: `systemctl --user restart magno-server`
e o `/api/saude` passa a mostrar `"email_modo": "smtp"` em vez de `"arquivo"`.

> **O código não muda**: o envio já está isolado em `server/email_provider.py` com três modos
> (`arquivo`, `smtp`, `resend`/`brevo`) — é trocar variáveis de ambiente. Sem nada configurado,
> roda o modo `arquivo`, que grava o e-mail em `logs/emails/` e o código em
> `logs/emails/enviados.jsonl` (nenhuma mensagem sai).

## Login com Google: o que só o dono da conta faz

São ~3 minutos no [console.cloud.google.com](https://console.cloud.google.com), uma vez só.

1. **Criar projeto** → nome `Barbearia Magnum` (ou reaproveitar um projeto seu).
2. **APIs e serviços → Tela de permissão OAuth**: tipo **Externo** → Criar. Nome
   `Barbearia Magnum`, seus e-mails de suporte e de desenvolvedor. Escopos: só
   `userinfo.email` e `userinfo.profile` (**não sensíveis** — dispensam verificação do Google e
   domínio verificado). Em **Teste**, só entram os e-mails listados; para uso geral, **Publicar app**.
3. **APIs e serviços → Credenciais → Criar credenciais → ID do cliente OAuth** → tipo
   **Aplicativo da Web**, nome `Magnum Web`:
   - **Origens JavaScript autorizadas**
     ```
     https://magnum.autoava.us
     http://localhost:8100
     ```
   - **URIs de redirecionamento autorizados** (idêntico ao abaixo, sem barra no fim)
     ```
     https://magnum.autoava.us/api/auth/google/callback
     http://localhost:8100/api/auth/google/callback
     ```
4. **Criar** → o Google mostra **ID do cliente** e **Segredo do cliente**. Me manda (ou cola em
   `~/magno/.env.local`) e apaga o `GOOGLE_FAKE=1`:

```
GOOGLE_CLIENT_ID=....apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=....
```

## Enquanto nada disso está configurado

- **E-mail**: modo `arquivo` — nada sai; o código fica em `logs/emails/`. O fluxo inteiro funciona
  (testes e navegador), só não chega na caixa de entrada de verdade.
- **Google**: `GOOGLE_FAKE=1` liga um provedor de teste local (`/api/auth/google/_fake`) com duas
  identidades falsas. O fluxo testado é o de verdade — `state` de uso único, callback,
  criação/vínculo de conta, sessão.

**Nunca deixar `GOOGLE_FAKE=1` nem `MAGNO_EMAIL_MODO=arquivo` em produção.**

## Segurança (decidido, não negociável)

- Segredos (chave SMTP/API, segredo do Google) **nunca vão para o navegador**.
- **`state` de uso único, com validade de 10 min** (`logins_pendentes`) — proteção contra CSRF no
  retorno do Google. Estado reaproveitado ou inventado volta para o login com erro.
- O token de sessão volta no **fragmento da URL** (`#entrar=...`), que não é enviado ao servidor
  nem entra em log, e é apagado da barra de endereços no primeiro instante.
- Código de e-mail: hash no banco, uso único, 10 min, 5 tentativas, limite de envio por e-mail+IP.
  A resposta nunca revela se o e-mail existe.
- Todo usuário precisa de **pelo menos uma forma de entrar** (senha, Google ou e-mail) — garantido
  por `CHECK` no banco, não só por código.

## Dados que a barbearia pede (e por quê)

| Dado | Obrigatório? | Por quê |
|---|---|---|
| e-mail | sim, no cadastro pelo site | é como a pessoa entra (código) |
| telefone | sim, **para agendar** | a loja confirma e avisa pelo WhatsApp |
| nome | sim | é como o barbeiro chama o cliente |
| senha | **não** | atalho opcional para quem não quer esperar o e-mail |

Conta criada pela loja (balcão) pode nascer só com telefone + PIN, sem e-mail.

## Arquivos

```
server/auth.py           PIN/senha (pbkdf2), código de e-mail, sessões, rate limit, papéis
server/email_provider.py envio em 3 modos + template da marca (arquivo/smtp/resend/brevo)
server/google_auth.py    OAuth do Google + provedor de teste
server/main.py           rotas /api/auth/*
docs/schema.sql          usuarios v3 (senha opcional, e-mail verificado) + codigos_email
web/entrar.html          entrar: e-mail+código (principal), Google, senha, telefone+PIN
web/conta.html           área logada: identidade, telefone, agendamentos, senha opcional
web/auth.js / conta.js   sessão no navegador e os formulários
tests/test_email_codigo.py  fluxo do código, limites, expiração, senha opcional
tests/test_auth.py          PIN, telefone, lockout, sessão, papéis
tests/test_google.py        fluxo OAuth completo (com provedor de teste)
tests/test_migracao.py      migração v1 → v3 sem perder dados
scripts/testa_email_login.py  E2E do login por código (21 verificações)
scripts/testa_login.py        E2E de telefone+PIN e Google (19 verificações)
```
