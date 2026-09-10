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

  window.MagnoAuth = { pedir: pedir, guardarSessao: guardarSessao, lerSessao: lerSessao, sair: sair };

  // ---------------------------------------------------- token vindo do Google
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
          guardarSessao(r.token);
          location.href = "conta.html";
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
          guardarSessao(r.token);
          location.href = "conta.html";
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
            mostrar("O login com Google ainda não está ligado nesta loja — falta colar as credenciais. Enquanto isso, entre pelo e-mail.", "erro");
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
  if (formEmail && lerSessao()) {
    pedir("/api/auth/me")
      .then(function () { location.replace("conta.html"); })
      .catch(function () { sair(); });
  }
})();
