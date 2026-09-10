/* Barbearia Magnum — interações da home (sem framework, sem build).
   Tudo aqui é progressive enhancement: sem JS a página continua legível. */
(function () {
  "use strict";

  // ------------------------------------------------------------ menu mobile
  var botao = document.getElementById("menuBotao");
  var nav = document.getElementById("nav");
  if (botao && nav) {
    botao.addEventListener("click", function () {
      var aberto = nav.classList.toggle("aberto");
      botao.setAttribute("aria-expanded", aberto ? "true" : "false");
      botao.setAttribute("aria-label", aberto ? "Fechar menu" : "Abrir menu");
    });
    nav.addEventListener("click", function (e) {
      if (e.target.tagName === "A") {
        nav.classList.remove("aberto");
        botao.setAttribute("aria-expanded", "false");
      }
    });
  }

  // ------------------------------------------------------------- ano no rodapé
  var ano = document.getElementById("ano");
  if (ano) ano.textContent = String(new Date().getFullYear());

  // ------------------------------------------------------ aberto / fechado
  // Horário de funcionamento (mesma tabela do sistema — docs/schema.sql).
  var HORARIOS = {
    0: null,                  // domingo fechado
    1: ["09:00", "19:00"],
    2: ["09:00", "19:00"],
    3: ["09:00", "19:00"],
    4: ["09:00", "19:00"],
    5: ["09:00", "20:00"],
    6: ["08:00", "18:00"]
  };
  var DIAS = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"];

  // Lê "agora" no fuso da loja, independente do fuso de quem abre a página.
  var fmtLoja = new Intl.DateTimeFormat("pt-BR", {
    timeZone: "America/Sao_Paulo",
    hour: "2-digit", minute: "2-digit", hour12: false
  });
  var fmtDia = new Intl.DateTimeFormat("en-US", { timeZone: "America/Sao_Paulo", weekday: "short" });
  var CHAVES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

  function agoraNaLoja() {
    var hora = fmtLoja.format(new Date()).replace(/^24:/, "00:");  // h24 do Intl em alguns casos
    var idx = CHAVES.indexOf(fmtDia.format(new Date()));
    return { dia: idx < 0 ? 1 : idx, hora: hora };
  }

  var horaHoje = document.getElementById("horaHoje");
  var selo = document.getElementById("seloStatus");
  if (horaHoje || selo) {
    var agora = agoraNaLoja();
    var hoje = HORARIOS[agora.dia];
    var texto, cor;

    if (!hoje) {
      texto = "Fechado hoje · volta " + DIAS[proximoDia(agora.dia)] + " às " + abreDe(proximoDia(agora.dia));
      cor = "fechado";
      if (horaHoje) horaHoje.textContent = "Fechado";
    } else if (agora.hora < hoje[0]) {
      texto = "Fechado agora · abre às " + hoje[0];
      cor = "fechado";
    } else if (agora.hora >= hoje[1]) {
      var prox = proximoDia(agora.dia);
      texto = "Fechado agora · abre " + DIAS[prox] + " às " + abreDe(prox);
      cor = "fechado";
    } else {
      texto = "Aberto agora · fecha às " + hoje[1];
      cor = "aberto";
    }

    if (horaHoje && hoje) horaHoje.textContent = hoje[0] + " — " + hoje[1];
    if (selo) {
      selo.classList.toggle("fechado", cor === "fechado");
      var alvo = selo.querySelector("span");
      if (alvo) alvo.textContent = texto;
    }
  }

  function proximoDia(dia) {
    for (var i = 1; i <= 7; i++) {
      var d = (dia + i) % 7;
      if (HORARIOS[d]) return d;
    }
    return 1;
  }
  function abreDe(dia) {
    return HORARIOS[dia] ? HORARIOS[dia][0] : "";
  }

  // --------------------------------------------------------- revelar ao rolar
  // NÃO usar animação de entrada aqui: em print de página inteira, em impressão
  // e em PDF o conteúdo abaixo da dobra sairia invisível (opacity 0). O site
  // fica todo visível desde o primeiro paint — de propósito.
})();
