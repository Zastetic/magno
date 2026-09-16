# App no celular — PWA hoje, APK quando valer

Decisão: **D29** (`docs/03-DECISOES.md`). O site já é instalável como app; APK/loja ficou
para depois, com o passo a passo abaixo pronto para quando for a hora.

## 1. O que já está no ar (PWA)

Instalar:

- **Android (Chrome):** abrir `https://magnum.autoava.us` → menu ⋮ → **Instalar app**
  (o Chrome também oferece sozinho, numa faixa, depois de duas visitas).
- **iPhone (Safari):** Compartilhar → **Adicionar à Tela de Início**. O iOS ignora o manifest
  e usa o `apple-touch-icon`.
- Abre em tela cheia (sem barra de endereço), com ícone do poste e cor da loja.

Arquivos:

| Arquivo | Papel |
|---|---|
| `web/manifest.webmanifest` | nome, `start_url`, `display: standalone`, ícones 192/512 + maskable, atalhos para `/account` e `/login` |
| `web/sw.js` | service worker: guarda o **casco** (ícones, CSS, `offline.html`) |
| `web/pwa.js` | registra o service worker (arquivo separado porque a CSP é `script-src 'self'`) |
| `web/offline.html` | o que o cliente vê sem rede — explica que nada ficou pela metade |
| `web/icons/*` | ícones; **gerados**, não desenhados à mão: `scripts/gera_icones_pwa.py` |

Regras do cache (de propósito, não é descuido):

- `/api/*` **nunca** é cacheado — horário é dado vivo e cache de agenda mentiria para o cliente;
- `/account` e `/perfil` também ficam de fora: são tela com dado pessoal;
- navegação é **rede primeiro**, cache só como rede de segurança (offline → `offline.html`);
- `sw.js` sai com `Cache-Control: no-cache`, senão o celular fica preso numa versão antiga.

Trocar o `VERSAO` no topo do `sw.js` invalida os caches antigos no `activate`.

Regenerar os ícones (o python do Hermes tem playwright):

```bash
/home/vh450/.hermes/hermes-agent/venv/bin/python scripts/gera_icones_pwa.py
```

Conferir tudo (19 verificações, incluindo o veredito do Chrome):

```bash
cd ~/magno && /home/vh450/.hermes/hermes-agent/venv/bin/python scripts/testa_pwa.py
MAGNO_DB=/tmp/test.db ./venv/bin/pytest tests/test_pwa.py -q
```

O juiz da instalação é o próprio Chrome: `Page.getInstallabilityErrors` (CDP) só vem vazio
quando o botão "Instalar app" realmente aparece. `no-icon-available` é transitório (o Chrome
ainda não baixou os ícones) e não conta como impedimento.

## 2. APK de verdade (quando for a hora)

**Pré-requisito obrigatório: fazer junto do cookie `HttpOnly`.** Com o token em
`sessionStorage`, cada abertura do app é uma aba nova e o cliente **loga de novo toda vez** —
um app assim nasce chato de usar. Ver a seção "Sessão: cookie HttpOnly" no skill do projeto.

O que falta nesta máquina (checado em 16/09/2026): **Android SDK** (`cmdline-tools` +
`platform-tools` + `build-tools`, ~1 GB + aceitar licenças). Já tem: JDK 21, `keytool`,
Node 22 / npm 10.9.8. O `gradle` do sistema (4.4.1) é velho, mas tanto o Bubblewrap quanto o
Gradle Wrapper baixam a versão certa — não é problema.

Caminho A — TWA com Bubblewrap (Chrome por dentro, apk de ~1 MB, ~1 h na primeira vez):

```bash
# 1. SDK (uma vez)
mkdir -p ~/android-sdk/cmdline-tools && cd ~/android-sdk/cmdline-tools
# baixar commandlinetools-linux-*.zip, descompactar como "latest"
export ANDROID_HOME=~/android-sdk
yes | ~/android-sdk/cmdline-tools/latest/bin/sdkmanager --licenses
~/android-sdk/cmdline-tools/latest/bin/sdkmanager "platform-tools" "platforms;android-35" "build-tools;35.0.0"

# 2. chave de assinatura (GUARDAR: sem ela não dá para atualizar o app depois)
keytool -genkeypair -v -keystore ~/magno/android/magno.keystore -alias magno \
  -keyalg RSA -keysize 2048 -validity 10000

# 3. projeto
cd ~/magno && npx @bubblewrap/cli init --manifest https://magnum.autoava.us/manifest.webmanifest
npx @bubblewrap/cli build            # gera app-release-signed.apk / .aab
```

Depois do primeiro build, o `assetlinks.json` precisa existir no domínio com o SHA-256 da
chave (`keytool -list -v -keystore ... | grep SHA256`):

```
https://magnum.autoava.us/.well-known/assetlinks.json   → hoje 404
```

Sem esse arquivo o app **abre com a barra de endereço do Chrome** — funciona, mas parece
navegador. Para servir: um arquivo em `web/.well-known/assetlinks.json` (o mount da SPA já
entrega) — conferir que o túnel não bloqueia `/.well-known/*`.

Caminho B — PWABuilder (nuvem, sem SDK local, 40–60 min): subir a URL, ele devolve APK/AAB.
Ainda precisa do manifest (feito) e do `assetlinks.json`.

Caminho C — Capacitor/WebView: **evitar**. WebView quebra o "Entrar com Google" (o Google
bloqueia user-agent de WebView) e não traz nada que o TWA não dê. Só valeria por plugin nativo
(push, câmera).

Publicar na Play Store é outro bloco: US$ 25 de conta de dev, AAB assinado, formulário de
segurança de dados e revisão de 1 a 7 dias. Enquanto for barbearia de bairro, mandar o APK no
WhatsApp resolve (o Play Protect avisa uma vez).
