/* Barbearia Magnum — login (telefone+PIN e Google) e sessão no navegador.
   O token de sessão vive em sessionStorage: some quando a aba fecha, e não é cookie. */
(function () {
  "use strict";

  var CHAVE = "magno_token";
  var aviso = document.getElementById("aviso");

  function mostrar(msg, tipo) {
    if (!aviso) return;
    aviso.textContent = msg || "";
    aviso.hidden = !msg;
    aviso.className = "aviso " + (tipo || "");
  }

  function guardarSessao(token) {
    try { sessionStorage.setItem(CHAVE, token); } catch (e) { /* modo privado */ }
  }

  function lerSessao() {
    try { return sessionStorage.getItem(CHAVE) || ""; } catch (e) { return ""; }
  }

  function sair() {
    try { sessionStorage.removeItem(CHAVE); } catch (e) { /* ignora */ }
  }

  function pedir(caminho, opcoes) {
    var cfg = opcoes || {};
    cfg.headers = Object.assign({ "Content-Type": "application/json" }, cfg.headers || {});
    var token = lerSessao();
    if (token) cfg.headers.Authorization = "Bearer " + token;
    return fetch(caminho, cfg).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (corpo) {
        if (!r.ok) throw Object.assign(new Error(corpo.erro || "Deu erro. Tente de novo."), { corpo: corpo, status: r.status });
        return corpo;
      });
    });
  }

  window.MagnoAuth = { pedir: pedir, guardarSessao: guardarSessao, lerSessao: lerSessao, sair: sair };

  // ---------------------------------------------------------- token vindo do Google
  // o callback redireciona com #entrar=<token> — guarda e limpa a URL na hora
  if (location.hash.indexOf("entrar=") >= 0) {
    var valor = location.hash.split("entrar=")[1].split("&")[0];
    if (valor) {
      guardarSessao(decodeURIComponent(valor));
      history.replaceState(null, "", location.pathname + location.search);
      location.replace("conta.html");
      return;
    }
  }

  var erro = new URLSearchParams(location.search).get("erro");
  if (erro) {
    var mensagens = {
      google_cancelado: "Você cancelou a entrada com o Google.",
      state_invalido: "A entrada expirou. Tente de novo.",
      google_falhou: "Não consegui falar com o Google agora. Tente pelo telefone.",
      google_sem_email: "Sua conta Google não devolveu e-mail.",
    };
    mostrar(mensagens[erro] || "Não consegui entrar. Tente de novo.", "erro");
  }

  // ------------------------------------------------------------------ abas
  var abaEntrar = document.getElementById("abaEntrar");
  var abaCriar = document.getElementById("abaCriar");
  var formEntrar = document.getElementById("formEntrar");
  var formCriar = document.getElementById("formCriar");
  var titulo = document.getElementById("titulo");
  var subtitulo = document.getElementById("subtitulo");

  function trocarAba(qual) {
    var entrarAtivo = qual === "entrar";
    abaEntrar.classList.toggle("ativa", entrarAtivo);
    abaCriar.classList.toggle("ativa", !entrarAtivo);
    formEntrar.hidden = !entrarAtivo;
    formCriar.hidden = entrarAtivo;
    titulo.textContent = entrarAtivo ? "Entrar" : "Criar conta";
    subtitulo.textContent = entrarAtivo
      ? "Veja seus agendamentos, remarque ou cancele sem precisar ligar."
      : "Nome, telefone e um PIN. Depois é só marcar o horário.";
    mostrar("");
  }
  if (abaEntrar && abaCriar) {
    abaEntrar.addEventListener("click", function () { trocarAba("entrar"); });
    abaCriar.addEventListener("click", function () { trocarAba("criar"); });
  }

  // ------------------------------------------------------------------ entrar
  if (formEntrar) {
    formEntrar.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var botao = formEntrar.querySelector("button[type=submit]");
      botao.disabled = true;
      mostrar("");
      pedir("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({
          telefone: document.getElementById("loginTelefone").value,
          pin: document.getElementById("loginPin").value,
        }),
      })
        .then(function (r) {
          guardarSessao(r.token);
          location.href = "conta.html";
        })
        .catch(function (e) {
          mostrar(e.message + (e.corpo && e.corpo.codigo === "lockout" ? " Aguarde e tente de novo." : ""), "erro");
        })
        .finally(function () { botao.disabled = false; });
    });
  }

  // ------------------------------------------------------------- criar conta
  if (formCriar) {
    formCriar.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var botao = formCriar.querySelector("button[type=submit]");
      botao.disabled = true;
      mostrar("");
      pedir("/api/auth/cadastro", {
        method: "POST",
        body: JSON.stringify({
          nome: document.getElementById("criarNome").value,
          telefone: document.getElementById("criarTelefone").value,
          pin: document.getElementById("criarPin").value,
          email: document.getElementById("criarEmail").value || null,
          consentimento_lgpd: document.getElementById("criarConsentimento").checked,
        }),
      })
        .then(function (r) {
          guardarSessao(r.token);
          location.href = "conta.html";
        })
        .catch(function (e) { mostrar(e.message, "erro"); })
        .finally(function () { botao.disabled = false; });
    });
  }

  // ------------------------------------------------------- botão do Google
  var btnGoogle = document.getElementById("btnGoogle");
  if (btnGoogle) {
    fetch("/api/saude")
      .then(function (r) { return r.json(); })
      .then(function (d) {
        var pronto = d.login && d.login.google;
        if (!pronto) {
          btnGoogle.classList.add("desligado");
          btnGoogle.setAttribute("href", "#");
        }
        btnGoogle.addEventListener("click", function (ev) {
          if (!pronto) {
            ev.preventDefault();
            mostrar("O login com Google ainda não está ligado nesta loja — falta colar as credenciais. Enquanto isso, entre com telefone e PIN.", "erro");
          }
        });
      })
      .catch(function () { /* sem rede: o link segue o fluxo normal */ });
  }

  var ano = document.getElementById("ano");
  if (ano) ano.textContent = String(new Date().getFullYear());

  // Se já está logado, não faz sentido ficar na tela de entrar.
  // IMPORTANTE: só na tela de entrar — este arquivo também carrega em conta.html, e
  // redirecionar de dentro da própria conta gera loop de recarregamento.
  if (formEntrar && lerSessao()) {
    pedir("/api/auth/me")
      .then(function () { location.replace("conta.html"); })
      .catch(function () { sair(); });
  }
})();
