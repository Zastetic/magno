/* Barbearia Magnum — interações da home (sem framework, sem build).
   Tudo é progressive enhancement: sem JS a página continua legível e completa.
   Nada de handler inline (a CSP é script-src 'self'). */
(function () {
  "use strict";

  var semAnimacao = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------------------------------------------------------------- dados */
  // Horário de funcionamento — mesma tabela de docs/schema.sql (horarios).
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
  var SLOT_MIN = 30;          // configuracoes.slot_min
  var ANTECEDENCIA_MIN = 60;  // configuracoes.antecedencia_min_h
  var LOJA_WHATS = "5513900000000";  // trocar pelo WhatsApp real

  var PROFISSIONAIS = {
    rafael: { nome: "Rafael", funcao: "Degradê e navalha" },
    bruno:  { nome: "Bruno",  funcao: "Clássico na tesoura" },
    diego:  { nome: "Diego",  funcao: "Barba e desenho" }
  };

  /* ------------------------------------------------------- utilidades de tempo */
  var fmtHora = new Intl.DateTimeFormat("pt-BR", {
    timeZone: "America/Sao_Paulo", hour: "2-digit", minute: "2-digit", hour12: false
  });
  var fmtDiaSemana = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Sao_Paulo", weekday: "short"
  });
  var CHAVES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

  function agora() {
    var d = new Date();
    var hora = fmtHora.format(d).replace(/^24:/, "00:");
    var idx = CHAVES.indexOf(fmtDiaSemana.format(d));
    return { dia: idx < 0 ? 1 : idx, hora: hora, minutos: paraMinutos(hora) };
  }

  function paraMinutos(hhmm) {
    var p = String(hhmm).split(":");
    return parseInt(p[0], 10) * 60 + parseInt(p[1], 10);
  }

  function deMinutos(min) {
    var h = Math.floor(min / 60) % 24;
    var m = min % 60;
    return (h < 10 ? "0" : "") + h + ":" + (m < 10 ? "0" : "") + m;
  }

  function proximoDiaAberto(dia) {
    for (var i = 1; i <= 7; i++) {
      var d = (dia + i) % 7;
      if (HORARIOS[d]) return d;
    }
    return 1;
  }

  function horaParaTexto(min) {
    var h = Math.floor(min / 60);
    var m = min % 60;
    if (h === 0) return m + " min";
    return m === 0 ? h + " h" : h + " h " + m;
  }

  /* --------------------------------------------- grade de horários (de verdade) */
  // Mesma lógica do motor de disponibilidade: abre → fecha, de 30 em 30,
  // descontando antecedência mínima, a duração do serviço e o que já está ocupado.
  // "Ocupado" aqui é um padrão fixo de demonstração — quando o sistema estiver
  // ligado, vem de /api/publica/disponibilidade. O almoço (12:00–13:00) entra como
  // bloqueio do profissional, igual à tabela `bloqueios` do banco.
  var ALMOCO = [12 * 60, 13 * 60];

  function blocosDeAlmoco(t, duracaoMin) {
    return t < ALMOCO[1] && t + duracaoMin > ALMOCO[0];
  }

  function slotsDoDia(dia, duracaoMin, incluirPassados) {
    var faixa = HORARIOS[dia];
    if (!faixa) return [];

    var abre = paraMinutos(faixa[0]);
    var fecha = paraMinutos(faixa[1]);
    var agoraAgora = agora();
    var limite = abre;

    if (agoraAgora.dia === dia) {
      limite = Math.max(abre, agoraAgora.minutos + ANTECEDENCIA_MIN);
    }
    // alinha o limite na grade de 30 min
    limite = abre + Math.ceil((limite - abre) / SLOT_MIN) * SLOT_MIN;

    var slots = [];
    for (var t = limite; t + duracaoMin <= fecha; t += SLOT_MIN) {
      var indice = (t - abre) / SLOT_MIN;
      var ocupado = (indice + dia * 3) % 5 === 2;      // <- padrão de demonstração
      if (ocupado) continue;
      if (blocosDeAlmoco(t, duracaoMin)) continue;
      slots.push({ minutos: t, texto: deMinutos(t) });
    }
    if (incluirPassados) return slots;

    // também oferece o próximo dia aberto como alternativa
    var proximo = proximoDiaAberto(dia);
    if (slots.length < 4 && HORARIOS[proximo]) {
      var extras = [];
      var f2 = HORARIOS[proximo];
      for (var u = paraMinutos(f2[0]); u + duracaoMin <= paraMinutos(f2[1]); u += SLOT_MIN) {
        var i2 = (u - paraMinutos(f2[0])) / SLOT_MIN;
        if ((i2 + proximo * 3) % 5 === 2) continue;
        if (blocosDeAlmoco(u, duracaoMin)) continue;
        extras.push({ minutos: u, texto: deMinutos(u), dia: proximo });
        if (extras.length >= 4) break;
      }
      return slots.concat(extras);
    }
    return slots;
  }

  /* ------------------------------------------------------------- topo: menu */
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

  var ano = document.getElementById("ano");
  if (ano) ano.textContent = String(new Date().getFullYear());

  /* ------------------------------------------------ quem está logado agora */
  // Se houver sessão, o link do topo vira o nome da pessoa e leva para a conta.
  var linkConta = document.getElementById("linkConta");
  if (linkConta) {
    var token = "";
    try { token = sessionStorage.getItem("magno_token") || ""; } catch (e) { token = ""; }
    if (token) {
      fetch("/api/auth/me", { headers: { Authorization: "Bearer " + token } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d || !d.usuario) return;
          var primeiro = String(d.usuario.nome || "").trim().split(/\s+/)[0];
          linkConta.textContent = primeiro ? "Olá, " + primeiro : "Minha conta";
          linkConta.href = "conta.html";
        })
        .catch(function () { /* sem sessão válida: segue como "Entrar" */ });
    }
  }

  /* ------------------------------------------- cartão vivo: status + relógio */
  var horaHoje = document.getElementById("horaHoje");
  var selo = document.getElementById("seloStatus");
  var textoRelogio = document.getElementById("relogio");
  var listaVagas = document.getElementById("vagasHoje");

  function atualizarCartao() {
    var a = agora();
    var hoje = HORARIOS[a.dia];
    var texto, fechado = false;

    if (!hoje) {
      var prox = proximoDiaAberto(a.dia);
      texto = "Fechado hoje · volta " + DIAS[prox] + " às " + HORARIOS[prox][0];
      fechado = true;
    } else if (a.minutos < paraMinutos(hoje[0])) {
      texto = "Fechado agora · abre às " + hoje[0];
      fechado = true;
    } else if (a.minutos >= paraMinutos(hoje[1])) {
      var pd = proximoDiaAberto(a.dia);
      texto = "Fechado agora · abre " + DIAS[pd] + " às " + HORARIOS[pd][0];
      fechado = true;
    } else {
      var resta = paraMinutos(hoje[1]) - a.minutos;
      texto = "Aberto agora · fecha em " + horaParaTexto(resta);
    }

    if (horaHoje) horaHoje.textContent = hoje ? hoje[0] + " — " + hoje[1] : "Fechado";
    if (selo) {
      selo.classList.toggle("fechado", fechado);
      var alvo = selo.querySelector("span");
      if (alvo) alvo.textContent = texto;
    }
    if (textoRelogio) textoRelogio.textContent = a.hora;
  }

  // preenche as primeiras vagas do cartão conforme o horário real
  function atualizarVagasDoCartao() {
    if (!listaVagas) return;
    var a = agora();
    var dia = HORARIOS[a.dia] ? a.dia : proximoDiaAberto(a.dia);
    var vagas = slotsDoDia(dia, 30, true).slice(0, 4);
    var rotulo = listaVagas.getAttribute("data-rotulo") || "Horários livres";
    var titulo = document.querySelector('[data-alvo="vagas"]');
    if (titulo) {
      titulo.textContent = a.dia === dia
        ? (vagas.length ? "Horários livres hoje" : "Hoje já encheu")
        : (vagas.length ? "Primeiros horários de " + DIAS[dia] : "Sem vaga nos próximos dias");
    }
    listaVagas.textContent = "";
    if (!vagas.length) {
      var vazio = document.createElement("li");
      vazio.className = "vaga-vazia";
      vazio.textContent = "Sem horário — fale com a loja";
      listaVagas.appendChild(vazio);
      return;
    }
    vagas.forEach(function (v) {
      var li = document.createElement("li");
      li.textContent = v.texto;
      if (v.dia && v.dia !== a.dia) {
        var marca = document.createElement("small");
        marca.textContent = DIAS[v.dia].slice(0, 3);
        li.appendChild(marca);
      }
      li.tabIndex = 0;
      li.addEventListener("click", function () {
        irParaAgendamento(null, null, v.texto);
      });
      listaVagas.appendChild(li);
    });
    if (rotulo) listaVagas.setAttribute("aria-label", rotulo);
  }

  /* --------------------------------------------- faixa: destaca o dia de hoje */
  var faixa = document.querySelector(".faixa");
  if (faixa) {
    var a = agora();
    faixa.querySelectorAll("li[data-dias]").forEach(function (li) {
      var dias = li.getAttribute("data-dias").split(",").map(Number);
      if (dias.indexOf(a.dia) >= 0) {
        li.classList.add("hoje");
        var dt = li.querySelector("dt");
        if (dt && !dt.querySelector(".marca-hoje")) {
          var m = document.createElement("span");
          m.className = "marca-hoje";
          m.textContent = "hoje";
          dt.appendChild(m);
        }
      }
    });
  }

  /* --------------------------------------- nav: marca a seção que está na tela */
  if (nav && "IntersectionObserver" in window) {
    var links = {};
    nav.querySelectorAll('a[href^="#"]').forEach(function (l) {
      links[l.getAttribute("href").slice(1)] = l;
    });
    var obs = new IntersectionObserver(function (entradas) {
      entradas.forEach(function (e) {
        var link = links[e.target.id];
        if (!link) return;
        if (e.isIntersecting) {
          Object.keys(links).forEach(function (k) { links[k].classList.remove("ativo"); });
          link.classList.add("ativo");
        }
      });
    }, { rootMargin: "-45% 0px -50% 0px" });
    Object.keys(links).forEach(function (id) {
      var secao = document.getElementById(id);
      if (secao) obs.observe(secao);
    });
  }

  /* ============================ passo 2 e 3: escolher e confirmar ============ */
  var quadro = document.getElementById("quadro");
  var passoEscolha = document.getElementById("passo-escolha");
  var passoConfirmar = document.getElementById("passo-confirmar");
  var passoPronto = document.getElementById("passo-pronto");
  var resumoServico = document.getElementById("resumoServico");
  var chipsProf = document.getElementById("chipsProf");
  var chipsHora = document.getElementById("chipsHora");
  var avisoVazio = document.getElementById("avisoVazio");
  var btnContinuar = document.getElementById("btnContinuar");
  var resumoEscolha = document.getElementById("resumoEscolha");
  var textoPronto = document.getElementById("textoPronto");
  var linkWhats = document.getElementById("linkWhats");

  var escolha = { servico: null, minutos: 0, preco: "", profissional: null, hora: null };

  function servicosDaPagina() {
    return Array.prototype.slice.call(document.querySelectorAll(".menu-servicos a[data-servico]"));
  }

  function selecionarServico(el) {
    servicosDaPagina().forEach(function (a) { a.classList.remove("selecionado"); });
    el.classList.add("selecionado");
    escolha.servico = el.getAttribute("data-servico");
    escolha.minutos = parseInt(el.getAttribute("data-min"), 10);
    escolha.preco = el.getAttribute("data-preco");
    escolha.profissional = null;
    escolha.hora = null;
    if (quadro) quadro.setAttribute("data-estado", "escolha");
    mostrarPasso("escolha");
    desenharEscolha();
  }

  function irParaAgendamento(servicoEl, profissional, horaTexto) {
    if (servicoEl) selecionarServico(servicoEl);
    if (profissional) escolha.profissional = profissional;
    if (horaTexto) escolha.hora = horaTexto;
    if (quadro) {
      desenharEscolha();
      quadro.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  function desenharEscolha() {
    if (!resumoServico) return;

    if (!escolha.servico) {
      resumoServico.textContent = "Nenhum serviço escolhido ainda — toque em um serviço na lista acima.";
      resumoServico.classList.add("fraco");
      chipsProf.textContent = "";
      chipsHora.textContent = "";
      desenharAviso("Escolha um serviço para ver os horários que cabem na cadeira.");
      definirContinuar(false);
      return;
    }

    resumoServico.classList.remove("fraco");
    resumoServico.innerHTML = "";
    var b = document.createElement("b");
    b.textContent = escolha.servico;
    resumoServico.appendChild(b);
    resumoServico.appendChild(document.createTextNode(
      " · " + horaParaTexto(escolha.minutos) + " na cadeira · " + escolha.preco
    ));

    // barbeiros que atendem esse serviço
    var el = servicosDaPagina().filter(function (a) {
      return a.getAttribute("data-servico") === escolha.servico;
    })[0];
    var permitidos = el ? el.getAttribute("data-prof").split(" ").filter(Boolean) : [];
    chipsProf.textContent = "";
    permitidos.forEach(function (chave) {
      var p = PROFISSIONAIS[chave];
      if (!p) return;
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip";
      chip.textContent = p.nome;
      chip.title = p.funcao;
      chip.setAttribute("aria-pressed", escolha.profissional === chave ? "true" : "false");
      if (escolha.profissional === chave) chip.classList.add("ativo");
      chip.addEventListener("click", function () {
        escolha.profissional = escolha.profissional === chave ? null : chave;
        escolha.hora = null;
        desenharEscolha();
      });
      chipsProf.appendChild(chip);
    });

    // grade de horários para a duração desse serviço (mostra todos os que cabem)
    var a = agora();
    var dia = HORARIOS[a.dia] ? a.dia : proximoDiaAberto(a.dia);
    var vagas = slotsDoDia(dia, escolha.minutos, true).slice(0, 24);
    chipsHora.textContent = "";
    vagas.forEach(function (v) {
      var chip = document.createElement("button");
      chip.type = "button";
      chip.className = "chip hora";
      chip.textContent = v.texto;
      chip.setAttribute("aria-pressed", escolha.hora === v.texto ? "true" : "false");
      if (escolha.hora === v.texto) chip.classList.add("ativo");
      chip.addEventListener("click", function () {
        escolha.hora = escolha.hora === v.texto ? null : v.texto;
        desenharEscolha();
      });
      chipsHora.appendChild(chip);
    });

    var sem = !vagas.length;
    desenharAviso(sem
      ? "Não sobrou horário hoje que caiba " + horaParaTexto(escolha.minutos) +
        " — veja o próximo dia ou chame no WhatsApp."
      : "");
    definirContinuar(!sem && !!escolha.hora);
    if (!vagas.length && chipsHora) {
      var vazio = document.createElement("span");
      vazio.className = "chip vazio";
      vazio.textContent = "nenhum horário hoje";
      chipsHora.appendChild(vazio);
    }
  }

  function desenharAviso(msg) {
    if (!avisoVazio) return;
    avisoVazio.textContent = msg || "";
    avisoVazio.hidden = !msg;
  }

  function definirContinuar(ativo) {
    if (!btnContinuar) return;
    btnContinuar.disabled = !ativo;
    if (!ativo) {
      btnContinuar.textContent = escolha.servico
        ? (escolha.profissional ? "Escolha um horário" : "Escolha o barbeiro")
        : "Escolha um serviço";
    } else {
      btnContinuar.textContent = "Continuar";
    }
  }

  function mostrarPasso(qual) {
    [["escolha", passoEscolha], ["confirmar", passoConfirmar], ["pronto", passoPronto]]
      .forEach(function (par) {
        if (par[1]) par[1].hidden = par[0] !== qual;
      });
  }

  if (quadro) {
    servicosDaPagina().forEach(function (el) {
      el.addEventListener("click", function (ev) {
        ev.preventDefault();
        irParaAgendamento(el);
      });
    });

    if (btnContinuar) {
      btnContinuar.addEventListener("click", function () {
        var p = PROFISSIONAIS[escolha.profissional];
        resumoEscolha.textContent = escolha.servico + " · " + horaParaTexto(escolha.minutos) +
          " · " + escolha.preco + (p ? " · com " + p.nome : "") + " · hoje às " + escolha.hora;
        mostrarPasso("confirmar");
        var primeiro = document.getElementById("campoNome");
        if (primeiro) primeiro.focus();
      });
    }

    var btnVoltar = document.getElementById("btnVoltar");
    if (btnVoltar) {
      btnVoltar.addEventListener("click", function () { mostrarPasso("escolha"); });
    }

    var btnConfirmar = document.getElementById("btnConfirmar");
    if (btnConfirmar) {
      btnConfirmar.addEventListener("click", function () {
        var nome = document.getElementById("campoNome");
        var tel = document.getElementById("campoTelefone");
        var pin = document.getElementById("campoPin");
        var ok = document.getElementById("campoConsentimento");
        var faltas = [];
        if (!nome.value.trim()) faltas.push("nome");
        if (tel.value.replace(/\D/g, "").length < 10) faltas.push("telefone com DDD");
        if (pin.value.replace(/\D/g, "").length < 4) faltas.push("PIN de 4 dígitos");
        if (!ok.checked) faltas.push("aceite dos termos");
        if (faltas.length) {
          textoPronto.textContent = "";
          desenharAviso("Falta preencher: " + faltas.join(", ") + ".");
          return;
        }
        desenharAviso("");
        var p = PROFISSIONAIS[escolha.profissional];
        textoPronto.textContent = escolha.hora + " · " + escolha.servico +
          (p ? " com " + p.nome : "") + " · " + escolha.preco +
          ". (Demonstração: o horário ainda não foi gravado no banco.)";
        if (linkWhats) {
          linkWhats.href = "https://wa.me/" + LOJA_WHATS + "?text=" + encodeURIComponent(
            "Olá! Quero confirmar: " + escolha.servico + " hoje às " + escolha.hora +
            (p ? " com " + p.nome : "") + ". Nome: " + nome.value.trim());
        }
        mostrarPasso("pronto");
      });
    }

    var btnOutro = document.getElementById("btnOutro");
    if (btnOutro) {
      btnOutro.addEventListener("click", function () {
        escolha = { servico: null, minutos: 0, preco: "", profissional: null, hora: null };
        servicosDaPagina().forEach(function (a) { a.classList.remove("selecionado"); });
        mostrarPasso("escolha");
        desenharEscolha();
      });
    }

    mostrarPasso("escolha");
    desenharEscolha();
  }

  /* ------------------------------------------------- ponteiro (hora real) */
  var agulha = document.querySelector(".ponteiro .agulha");
  if (agulha) {
    var fmtSegundo = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Sao_Paulo", second: "2-digit"
    });
    var graus = (parseInt(fmtSegundo.format(new Date()), 10) || 0) * 6;
    agulha.style.transform = "rotate(" + graus + "deg)";
    if (!semAnimacao) {
      // acumula em vez de recalcular: assim a agulha nunca "volta" ao cruzar o 60
      setInterval(function () {
        graus += 6;
        agulha.style.transform = "rotate(" + graus + "deg)";
      }, 1000);
    }
  }

  /* ------------------------------------- revelar ao rolar (só com transform) */
  // Só os blocos que estão ABAIXO da dobra recebem o deslocamento; e é sempre
  // transform, nunca opacity — print de página inteira e PDF saem completos.
  if (!semAnimacao && "IntersectionObserver" in window) {
    var blocos = [];
    document.querySelectorAll(".secao > .limite, .barbeiro, .passo").forEach(function (el) {
      if (el.getBoundingClientRect().top > window.innerHeight * 0.92) blocos.push(el);
    });
    blocos.forEach(function (el) { el.classList.add("sobe"); });
    var obsSobe = new IntersectionObserver(function (entradas) {
      entradas.forEach(function (e) {
        if (e.isIntersecting) {
          e.target.classList.add("visivel");
          obsSobe.unobserve(e.target);
        }
      });
    }, { rootMargin: "0px 0px -6% 0px", threshold: 0.05 });
    blocos.forEach(function (el) { obsSobe.observe(el); });
  }

  /* ---------------------------------------------------------------- ligar */
  atualizarCartao();
  atualizarVagasDoCartao();
  setInterval(function () {
    atualizarCartao();
    atualizarVagasDoCartao();
    if (quadro) desenharEscolha();
  }, 30000);
})();
