/* Barbearia Magnum — service worker do PWA.
 *
 * O que ele faz (e o que NÃO faz):
 *   · guarda o "casco" do site (ícones, página de offline) para o app abrir mesmo sem rede;
 *   · navegação: rede primeiro (a agenda é dado vivo) e cache só como rede de segurança;
 *   · estático (css/js/fonte/imagem): cache na frente, atualizando em segundo plano;
 *   · /api/*: passa direto, nunca cacheia — a API responde `Cache-Control: no-store` e
 *     guardar horário/agendamento no disco do celular seria mentir para o cliente.
 *
 * Trocar o VERSAO invalida os caches antigos no activate.
 */
const VERSAO = 'magno-pwa-2';
const CASCO = [
  '/offline.html',
  '/manifest.webmanifest',
  // o CSS entra sem versão de propósito: a página de offline pede exatamente esta URL e,
  // quando o HTML pede `/styles.css?v=…`, o handler abaixo cai nesta cópia (mesmo arquivo)
  '/styles.css',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/maskable-512.png',
  '/icons/apple-touch-icon.png',
];

self.addEventListener('install', (evento) => {
  evento.waitUntil(
    caches.open(VERSAO)
      // um 404 no casco não pode derrubar a instalação inteira
      .then((cache) => Promise.all(CASCO.map((url) => cache.add(url).catch(() => null))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (evento) => {
  evento.waitUntil(
    caches.keys()
      .then((nomes) => Promise.all(nomes.filter((nome) => nome !== VERSAO).map((nome) => caches.delete(nome))))
      .then(() => self.clients.claim())
  );
});

function estatico(request, url) {
  if (['style', 'script', 'image', 'font'].includes(request.destination)) return true;
  return /\.(css|js|png|jpg|jpeg|webp|svg|ico|woff2?|webmanifest)$/.test(url.pathname);
}

self.addEventListener('fetch', (evento) => {
  const { request } = evento;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // dado do cliente e da loja: sempre rede, nunca cache
  if (url.pathname.startsWith('/api/')) return;

  if (request.mode === 'navigate') {
    evento.respondWith(
      fetch(request).catch(() =>
        caches.match(request).then((guardado) => guardado || caches.match('/offline.html'))
      )
    );
    return;
  }

  if (estatico(request, url)) {
    evento.respondWith(
      caches.match(request).then((guardado) => {
        const daRede = fetch(request)
          .then((resposta) => {
            if (resposta && resposta.ok) {
              const copia = resposta.clone();
              caches.open(VERSAO).then((cache) => cache.put(request, copia)).catch(() => null);
            }
            return resposta;
          })
          .catch(() =>
            // o HTML pede `/styles.css?v=grade-1`: sem rede, essa versão exata pode não estar
            // no cache (o casco guarda a URL sem query) — o arquivo é o mesmo
            guardado || caches.match(new URL(url.pathname, url.origin).toString())
          );
        return guardado || daRede;
      })
    );
    return;
  }

  // qualquer outro GET do site: rede, e se cair, a cópia exata se existir
  evento.respondWith(fetch(request).catch(() => caches.match(request)));
});
