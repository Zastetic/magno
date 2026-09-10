# Login — como funciona e o que falta para ligar o Google

## O que já está no ar (F1)

| Peça | Estado |
|---|---|
| Cadastro e login com **telefone + PIN** | ✅ funcionando (`/entrar.html`) |
| Sessão com **token opaco revogável** (24 h, `sha256` no banco) | ✅ |
| **Lockout** de 5 falhas / 15 min por telefone+IP | ✅ (testado) |
| Papéis (`cliente` / `barbeiro` / `admin`) com guarda nas rotas | ✅ |
| **Login com Google** (OAuth 2.0, authorization code) | ⚠️ código pronto, rodando com **provedor de teste** |
| Área da conta (`/conta.html`) com sair e completar telefone | ✅ |
| Telas no mesmo design (marrom escuro, latão, serifada) | ✅ |
| Cabeçalho do site cumprimenta quem está logado | ✅ |

Provas: **71 testes** de servidor (`pytest`) e **28 verificações** de browser incluindo o fluxo
completo do Google (state de uso único, callback, criação de conta, sessão, completar telefone).

## O que o Google pede (e só o dono da conta pode fazer)

São ~3 minutos no [console.cloud.google.com](https://console.cloud.google.com), uma vez só.

### 1. Criar o projeto e a tela de consentimento
1. **Criar projeto** → nome `Barbearia Magnum` (ou reaproveitar um projeto seu).
2. **APIs e serviços → Tela de permissão OAuth**:
   - Tipo de usuário: **Externo** → **Criar**.
   - Nome do app: `Barbearia Magnum` · e-mail de suporte: o seu · e-mail do desenvolvedor: o seu.
   - Escopos: deixar só `userinfo.email` e `userinfo.profile` (são **não sensíveis** — não precisa
     de verificação do Google nem de domínio verificado).
   - Usuários de teste: enquanto o app estiver em **Teste**, só entram os e-mails listados ali.
     Para uso geral, clicar em **Publicar app** (como os escopos são básicos, publica na hora).

### 2. Criar a credencial
3. **APIs e serviços → Credenciais → Criar credenciais → ID do cliente OAuth**:
   - Tipo: **Aplicativo da Web**. Nome: `Magnum Web`.
   - **Origens JavaScript autorizadas**
     ```
     https://magnum.autoava.us
     http://localhost:8100
     ```
   - **URIs de redirecionamento autorizados** (tem que ser idêntico, sem barra no fim)
     ```
     https://magnum.autoava.us/api/auth/google/callback
     http://localhost:8100/api/auth/google/callback
     ```
4. **Criar** → o Google mostra **ID do cliente** e **Segredo do cliente**.

### 3. Me passar (ou colar você mesmo)
O lugar certo é o `.env.local` do projeto (que é ignorado pelo git):

```
GOOGLE_CLIENT_ID=....apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=....
GOOGLE_FAKE=          # ← apaga o 1 daqui
```

Pode colar aqui no chat que eu escrevo no arquivo, ou abrir o arquivo e colar você mesmo
(`~/magno/.env.local`). Depois é só reiniciar:

```bash
export XDG_RUNTIME_DIR=/run/user/1000
systemctl --user restart magno-server
```

O `/api/saude` passa a mostrar `"google": true` com `"google_modo_teste": false`, e eu testo o
fluxo real de ponta a ponta (login, criação de conta, vínculo com conta existente por e-mail).

## Enquanto o Google não está ligado

`GOOGLE_FAKE=1` liga um **provedor de teste local**: a tela de consentimento é servida por nós
(`/api/auth/google/_fake`) com duas identidades falsas. O fluxo testado é o de verdade — `state`
de uso único, callback, criação/vinculo de conta, sessão. Serve para você ver funcionando hoje e
para a suíte de testes rodar sem depender do Google.

**Nunca deixar `GOOGLE_FAKE=1` em produção**: qualquer um entraria como qualquer identidade.

## Segurança (decidido, não negociável)

- O **segredo do cliente nunca sai do servidor**: a troca do `code` por `access_token` acontece
  no backend; o navegador só recebe o nosso token de sessão.
- **`state` de uso único e com validade de 10 min**, guardado em `logins_pendentes` — é a proteção
  contra CSRF no retorno do Google. Estado reaproveitado ou inventado → volta para o login com erro.
- O token de sessão volta no **fragmento da URL** (`#entrar=...`), que não é enviado ao servidor
  nem entra em log, e é apagado da barra de endereços no primeiro instante.
- Conta criada pelo Google **não tem telefone**: a tela da conta pede o número (a barbearia precisa
  dele para confirmar o atendimento). Conta que já existia com o mesmo e-mail é **vinculada**, não
  duplicada — o índice único de e-mail sustenta isso.
- Todo usuário precisa de **pelo menos uma forma de entrar** (PIN ou Google) — garantido por
  `CHECK` no banco, não só por código.

## Arquivos

```
server/auth.py         PIN (pbkdf2), sessões, lockout, papéis
server/google_auth.py  OAuth do Google + provedor de teste
server/main.py         rotas /api/auth/* e /api/auth/google/*
docs/schema.sql        usuarios v2 (telefone/senha opcionais, google_sub, e-mail único)
web/entrar.html        tela de entrar / criar conta
web/conta.html         área logada
web/auth.js            sessão no navegador, abas, formulários e botão do Google
web/conta.js           dados da conta, completar telefone, sair
tests/test_auth.py     PIN, telefone, cadastro, login, lockout, sessão, papéis
tests/test_google.py   fluxo OAuth completo (com provedor de teste)
tests/test_migracao.py migração v1 → v2 sem perder dados
```
