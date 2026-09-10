/* Barbearia Magnum — área logada. Sem token válido, volta para a tela de entrar. */
(function () {
  "use strict";

  var auth = window.MagnoAuth;
  var aviso = document.getElementById("aviso");
  var cartao = document.getElementById("cartao");
  var carregando = document.getElementById("carregando");
  var formTelefone = document.getElementById("formTelefone");

  function mostrar(msg, tipo) {
    if (!aviso) return;
    aviso.textContent = msg || "";
    aviso.hidden = !msg;
    aviso.className = "aviso " + (tipo || "");
  }

  function voltarParaEntrar() {
    auth.sair();
    location.replace("entrar.html");
  }

  function desenhar(usuario) {
    cartao.hidden = false;
    if (carregando) carregando.hidden = true;

    document.getElementById("nomeUsuario").textContent = usuario.nome;

    var via = document.createElement("span");
    via.className = "etiqueta-via";
    via.textContent = usuario.tem_google ? "Google" : (usuario.tem_senha ? "telefone + PIN" : "código por e-mail");
    var nome = document.getElementById("nomeUsuario");
    nome.appendChild(via);

    var partes = [];
    if (usuario.telefone_formatado) partes.push(usuario.telefone_formatado);
    if (usuario.email) partes.push(usuario.email);
    partes.push(usuario.papel === "cliente" ? "cliente" : usuario.papel);
    document.getElementById("detalheUsuario").textContent = partes.join(" · ");

    var avatar = document.getElementById("avatar");
    avatar.textContent = "";
    if (usuario.foto_url) {
      var img = document.createElement("img");
      img.src = usuario.foto_url;
      img.alt = "";
      avatar.appendChild(img);
    } else {
      avatar.textContent = (usuario.nome || "?").trim().charAt(0).toUpperCase();
    }

    if (formTelefone) formTelefone.hidden = !usuario.precisa_telefone;

    var rotuloSenha = document.getElementById("rotuloSenha");
    var btnSalvarSenha = document.getElementById("btnSalvarSenha");
    if (rotuloSenha) rotuloSenha.textContent = usuario.tem_senha ? "Trocar a senha (opcional)" : "Senha (opcional)";
    if (btnSalvarSenha) btnSalvarSenha.textContent = usuario.tem_senha ? "Trocar senha" : "Salvar senha";
  }

  if (!auth || !auth.lerSessao()) {
    voltarParaEntrar();
    return;
  }

  auth.pedir("/api/auth/me")
    .then(function (r) { desenhar(r.usuario); })
    .catch(function () { voltarParaEntrar(); });

  if (formTelefone) {
    formTelefone.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var botao = formTelefone.querySelector("button");
      botao.disabled = true;
      mostrar("");
      auth.pedir("/api/auth/telefone", {
        method: "PATCH",
        body: JSON.stringify({ telefone: document.getElementById("telefone").value }),
      })
        .then(function (r) {
          desenhar(r.usuario);
          mostrar("Telefone salvo.", "ok");
        })
        .catch(function (e) { mostrar(e.message, "erro"); })
        .finally(function () { botao.disabled = false; });
    });
  }

  // senha é opcional: quem quiser um atalho cria aqui
  var formSenha = document.getElementById("formSenha");
  if (formSenha) {
    formSenha.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var botao = document.getElementById("btnSalvarSenha");
      var campo = document.getElementById("novaSenha");
      botao.disabled = true;
      mostrar("");
      auth.pedir("/api/auth/senha", { method: "POST", body: JSON.stringify({ senha: campo.value }) })
        .then(function (r) {
          campo.value = "";
          desenhar(r.usuario);
          mostrar("Senha salva. Agora você pode entrar com e-mail e senha.", "ok");
        })
        .catch(function (e) { mostrar(e.message, "erro"); })
        .finally(function () { botao.disabled = false; });
    });
  }

  function sairAgora(ev) {
    if (ev) ev.preventDefault();
    auth.pedir("/api/auth/logout", { method: "POST" })
      .catch(function () { /* mesmo falhando, a sessão local sai */ })
      .finally(voltarParaEntrar);
  }
  var btnSair = document.getElementById("btnSair");
  if (btnSair) btnSair.addEventListener("click", sairAgora);
  var linkSair = document.getElementById("linkSair");
  if (linkSair) linkSair.addEventListener("click", sairAgora);

  var ano = document.getElementById("ano");
  if (ano) ano.textContent = String(new Date().getFullYear());
})();
