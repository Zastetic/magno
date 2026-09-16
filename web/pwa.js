/* Barbearia Magnum — registra o service worker (PWA).
 *
 * Arquivo separado de propósito: a CSP é estrita (`script-src 'self'`), então script inline
 * não roda. Carregado com `defer` em todas as páginas: se o navegador não tiver serviceWorker,
 * nada acontece e o site funciona igual.
 */
(() => {
  'use strict';
  if (!('serviceWorker' in navigator)) return;
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => { /* sem PWA, o site segue */ });
  });
})();
