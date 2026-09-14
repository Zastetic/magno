/* Barbearia Magnum — login: código por e-mail (principal), Google, senha e telefone+PIN.
   O token de sessão vive em sessionStorage: some quando a aba fecha, e não é cookie. */
(function () {
  "use strict";

  var CHAVE = "magno_token";
  var aviso = document.getElementById("aviso");
  var formEmail = document.getElementById("formEmail");
  var formCodigo = document.getElementById("formCodigo");
  var formSenha = document.getElementById("formEntrarSenha");
  var formTelefone = document.getElementById("formEntrarTelefone");
  var emailEmUso = "";

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

  function destinoSeguro() {
    var destino = new URLSearchParams(location.search).get("next");
    var permitidos = ["/account", "/perfil"];
    return permitidos.indexOf(destino) >= 0 ? destino : "/account";
  }

  function encerrarSessao() {
    var token = lerSessao();
    // Logout é revogação no servidor; a limpeza local acontece mesmo sem rede.
    if (!token) { sair(); return Promise.resolve(); }
    return fetch("/api/auth/logout", {
      method: "POST",
      headers: { "Authorization": "Bearer " + token, "Content-Type": "application/json" },
    }).catch(function () { /* offline: o token local ainda é removido */ }).then(function () { sair(); });
  }

  function pedir(caminho, opcoes) {
    var cfg = opcoes || {};
    cfg.headers = Object.assign({ "Content-Type": "application/json" }, cfg.headers || {});
    var token = lerSessao();
    if (token) cfg.headers.Authorization = "Bearer " + token;
    return fetch(caminho, cfg).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (corpo) {
        if (!r.ok) {
          throw Object.assign(new Error(corpo.erro || "Deu erro. Tente de novo."),
                              { corpo: corpo, status: r.status });
        }
        return corpo;
      });
    });
  }

  window.MagnoAuth = { pedir: pedir, guardarSessao: guardarSessao, lerSessao: lerSessao, sair: sair, encerrarSessao: encerrarSessao };

  function concluirLogin(token) {
    guardarSessao(token);
    location.replace(destinoSeguro());
  }
  // o callback redireciona com #entrar=<token> — guarda e limpa a URL na hora
  if (location.hash.indexOf("entrar=") >= 0) {
    var valor = location.hash.split("entrar=")[1].split("&")[0];
    if (valor) {
      guardarSessao(decodeURIComponent(valor));
      history.replaceState(null, "", location.pathname + location.search);
      concluirLogin(decodeURIComponent(valor));
      return;
    }
  }

  var erro = new URLSearchParams(location.search).get("erro");
  var notice = new URLSearchParams(location.search).get("notice");
  if (notice === "logout") mostrar("Você saiu da sua conta.", "ok");
  if (erro) {
    var mensagens = {
      google_cancelado: "Você cancelou a entrada com o Google.",
      state_invalido: "A entrada expirou. Tente de novo.",
      google_falhou: "Não consegui falar com o Google agora. Tente pelo e-mail.",
      google_sem_email: "Sua conta Google não devolveu e-mail.",
    };
    mostrar(mensagens[erro] || "Não consegui entrar. Tente de novo.", "erro");
  }

  // ------------------------------------------------------------ passo 1: e-mail
  function focarCodigo() {
    var campo = document.getElementById("codigo");
    if (campo) campo.focus();
  }

  function pedirCodigo(email, botao) {
    if (botao) botao.disabled = true;
    mostrar("");
    return pedir("/api/auth/codigo", { method: "POST", body: JSON.stringify({ email: email }) })
      .then(function (r) {
        emailEmUso = email;
        document.getElementById("emailEnviado").textContent = email;
        document.getElementById("validadeCodigo").textContent = r.minutos + " minutos";
        formEmail.hidden = true;
        formCodigo.hidden = false;
        var sub = document.getElementById("subtitulo");
        if (sub) sub.textContent = "Confira seu e-mail e digite o código de 5 dígitos.";
        mostrar("Código enviado. Confira a caixa de entrada (e o spam).", "ok");
        focarCodigo();
      })
      .catch(function (e) {
        mostrar(e.message, "erro");
        throw e;
      })
      .finally(function () { if (botao) botao.disabled = false; });
  }

  if (formEmail) {
    formEmail.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var email = document.getElementById("email").value.trim();
      if (!email || email.indexOf("@") < 0) {
        mostrar("Digite um e-mail válido.", "erro");
        return;
      }
      pedirCodigo(email, formEmail.querySelector("button[type=submit]"))
        .catch(function () { /* a mensagem já foi mostrada */ });
    });
  }

  // ------------------------------------------------------------ passo 2: código
  if (formCodigo) {
    formCodigo.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var botao = formCodigo.querySelector("button[type=submit]");
      botao.disabled = true;
      mostrar("");
      pedir("/api/auth/verificar", {
        method: "POST",
        body: JSON.stringify({ email: emailEmUso, codigo: document.getElementById("codigo").value }),
      })
        .then(function (r) {
          concluirLogin(r.token);
        })
        .catch(function (e) { mostrar(e.message, "erro"); })
        .finally(function () { botao.disabled = false; });
    });

    var btnReenviar = document.getElementById("btnReenviar");
    if (btnReenviar) {
      btnReenviar.addEventListener("click", function () {
        pedirCodigo(emailEmUso, null).catch(function () { /* mensagem já tratada */ });
      });
    }

    var btnTrocar = document.getElementById("btnTrocarEmail");
    if (btnTrocar) {
      btnTrocar.addEventListener("click", function () {
        formCodigo.hidden = true;
        formEmail.hidden = false;
        document.getElementById("codigo").value = "";
        mostrar("");
        document.getElementById("email").focus();
      });
    }
  }

  // ----------------------------------------------------- alternativas de entrada
  function mostrarSomente(qual) {
    [formEmail, formCodigo, formSenha, formTelefone].forEach(function (f) {
      if (f) f.hidden = f !== qual;
    });
    mostrar("");
    if (qual) {
      var primeiro = qual.querySelector("input");
      if (primeiro) primeiro.focus();
    }
  }

  var btnModoSenha = document.getElementById("btnModoSenha");
  if (btnModoSenha) {
    btnModoSenha.addEventListener("click", function () { mostrarSomente(formSenha); });
  }
  var btnModoTelefone = document.getElementById("btnModoTelefone");
  if (btnModoTelefone) {
    btnModoTelefone.addEventListener("click", function () { mostrarSomente(formTelefone); });
  }
  var btnVoltarSenha = document.getElementById("btnVoltarSenha");
  if (btnVoltarSenha) btnVoltarSenha.addEventListener("click", function () { mostrarSomente(formEmail); });

  if (formSenha) {
    formSenha.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var botao = formSenha.querySelector("button[type=submit]");
      botao.disabled = true;
      mostrar("");
      pedir("/api/auth/entrar-senha", {
        method: "POST",
        body: JSON.stringify({
          email: document.getElementById("entrarEmailSenha").value.trim(),
          senha: document.getElementById("entrarSenha").value,
        }),
      })
        .then(function (r) {
          concluirLogin(r.token);
        })
        .catch(function (e) { mostrar(e.message, "erro"); })
        .finally(function () { botao.disabled = false; });
    });
  }

  if (formTelefone) {
    formTelefone.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var botao = formTelefone.querySelector("button[type=submit]");
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
          concluirLogin(r.token);
        })
        .catch(function (e) { mostrar(e.message, "erro"); })
        .finally(function () { botao.disabled = false; });
    });
  }

  // ------------------------------------------------------- botão do Google
  var btnGoogle = document.getElementById("btnGoogle");
  if (btnGoogle) {
    btnGoogle.href = "/api/auth/google/iniciar?destino=" + encodeURIComponent(destinoSeguro());
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
            mostrar("O login com Google ainda não está ligado nesta loja — falta colar as credenciais. Enquanto isso, entre pelo e-mail.", "erro");
          }
        });
      })
      .catch(function () { /* sem rede: o link segue o fluxo normal */ });
  }

  var ano = document.getElementById("ano");
  if (ano) ano.textContent = String(new Date().getFullYear());

  // A tela de login continua disponível mesmo com uma sessão aberta.
  // Isso permite trocar de pessoa neste navegador; o próximo login substitui o Bearer.
})();
