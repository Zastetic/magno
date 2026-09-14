/* Cloudflare Turnstile nas ações sensíveis (cadastro, código por e-mail, login, agendamento).
 *
 * O site funciona igual quando o servidor não tem chave: nesse caso nada é carregado,
 * `ativo()` é false e o back-end também não exige token (`modo: off`).
 *
 * Com chave configurada, o widget é criado em modo invisível — sem mexer no layout — e
 * `executar()` devolve o token para quem for enviar o formulário. Token do Turnstile é de
 * uso único: depois de uma falha o back-end responde `captcha` e aqui a gente reinicia o
 * widget sozinho (ver auth.js).
 */
(() => {
  'use strict';

  const SCRIPT = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
  const estado = { ativo: false, chave: '', token: '', widget: null, carregando: null };
  let resolverToken = null;

  function criaContainer() {
    const caixa = document.createElement('div');
    caixa.id = 'magno-captcha';
    caixa.style.position = 'fixed';
    caixa.style.right = '12px';
    caixa.style.bottom = '12px';
    caixa.style.zIndex = '60';
    document.body.appendChild(caixa);
    return caixa;
  }

  function carregaScript() {
    if (estado.carregando) return estado.carregando;
    estado.carregando = new Promise((resolver, rejeitar) => {
      if (window.turnstile) return resolver();
      const tag = document.createElement('script');
      tag.src = SCRIPT;
      tag.async = true;
      tag.defer = true;
      tag.onload = () => resolver();
      tag.onerror = () => rejeitar(new Error('captcha_indisponivel'));
      document.head.appendChild(tag);
    });
    return estado.carregando;
  }

  async function preparar() {
    let config = {};
    try {
      const r = await fetch('/api/publica/config', { headers: { 'Accept': 'application/json' } });
      config = await r.json();
    } catch (e) {
      return;                       // servidor fora do ar: o login já vai reclamar disso
    }
    const captcha = (config && config.captcha) || {};
    if (!captcha.chave_site || captcha.modo === 'off') return;
    estado.chave = captcha.chave_site;
    try {
      await carregaScript();
      estado.widget = window.turnstile.render(criaContainer(), {
        sitekey: estado.chave,
        size: 'invisible',
        callback: (token) => {
          estado.token = token;
          if (resolverToken) { resolverToken(token); resolverToken = null; }
        },
        'error-callback': () => {
          if (resolverToken) { resolverToken(''); resolverToken = null; }
        },
      });
      estado.ativo = true;
    } catch (e) {
      estado.ativo = false;         // sem captcha o site continua utilizável
    }
  }

  function executar() {
    if (!estado.ativo) return Promise.resolve('');
    if (estado.token) return Promise.resolve(estado.token);
    return new Promise((resolver) => {
      resolverToken = resolver;
      try {
        window.turnstile.execute(estado.widget);
      } catch (e) {
        resolver('');
        resolverToken = null;
      }
      setTimeout(() => {           // nunca deixa o botão travado esperando o widget
        if (resolverToken) { resolver(''); resolverToken = null; }
      }, 8000);
    });
  }

  function reiniciar() {
    estado.token = '';
    try {
      if (estado.widget !== null) window.turnstile.reset(estado.widget);
    } catch (e) { /* widget antigo: o próximo executar() resolve */ }
  }

  window.MagnoTurnstile = {
    preparar: preparar,
    ativo: () => estado.ativo,
    token: () => estado.token,
    executar: executar,
    reiniciar: reiniciar,
  };

  preparar();
})();
