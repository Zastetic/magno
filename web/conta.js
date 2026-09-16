/* Barbearia Magnum — /account: agenda do cliente.
   O nome e a idade vêm do perfil (/perfil). Sem Bearer válido, esta tela não mostra nada.

   Dias e horários NÃO estão no HTML: vêm de GET /api/publica/disponibilidade, que é o mesmo
   motor que o servidor usa para aceitar a reserva. Consequência: quando alguém marca, o
   horário sai da grade na consulta seguinte — inclusive na do próprio cliente, que recarrega
   a grade depois de confirmar e quando volta para a aba. */
(() => {
  'use strict';

  const FUSO_PADRAO = 'America/Sao_Paulo';
  const DIAS_NA_TIRA = 6;    // quantos dias com vaga aparecem na tira de dias
  const DIAS_CONSULTA = 21;  // quantos dias são consultados de uma vez (o servidor aceita até 31)
  const SEGUNDOS_ENTRE_RECARGAS = 20;

  const DIAS_CURTOS = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'];
  const MESES_CURTOS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

  const state = {
    servicoId: null, servico: '', preco: '', duracao: '', duracaoMin: 0,
    profissionalId: null, barbeiro: '',
    dia: null, diaRotulo: '', hora: null,
    fuso: FUSO_PADRAO, equipe: [], carregando: false,
  };
  const content = document.querySelector('#accountContent');
  const summary = document.querySelector('#bookingSummary');
  const feedback = document.querySelector('#bookingFeedback');
  const form = document.querySelector('#bookingForm');
  const submit = document.querySelector('.confirm-booking');
  const serviceBox = document.querySelector('#serviceOptions');
  const barberBox = document.querySelector('#barberOptions');
  const dateList = document.querySelector('#dateList');
  const timeBox = document.querySelector('#timeOptions');
  const hoursLabel = document.querySelector('#hoursLabel');
  let usuario = null;
  let ultimaRecarga = 0;

  function login() { location.replace('/login?next=/account'); }
  function irParaPerfil() { location.replace('/perfil'); }
  function initials(name) { return (name || '—').trim().slice(0, 1).toUpperCase(); }

  /* A CSP é estrita e o texto vem do banco: tudo que entra em innerHTML passa por aqui. */
  function escapar(texto) {
    return String(texto == null ? '' : texto)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function publico(caminho) {
    return fetch(caminho).then((resposta) => resposta.json()
      .catch(() => ({}))
      .then((corpo) => {
        if (!resposta.ok) {
          throw Object.assign(new Error(corpo.erro || 'Não consegui falar com o servidor.'),
                              { status: resposta.status, corpo: corpo });
        }
        return corpo;
      }));
  }

  /* --------------------------------------------------------------- datas */
  function isoLocal(deslocamento) {
    const hoje = new Date();
    const dia = new Date(hoje.getFullYear(), hoje.getMonth(), hoje.getDate() + deslocamento);
    return [dia.getFullYear(),
            String(dia.getMonth() + 1).padStart(2, '0'),
            String(dia.getDate()).padStart(2, '0')].join('-');
  }

  /* Rótulo do dia sem passar por fuso do navegador: a data do servidor é local da loja. */
  function partes(iso) {
    const [ano, mes, dia] = iso.split('-').map(Number);
    return { ano: ano, mes: mes, dia: dia, semana: DIAS_CURTOS[new Date(Date.UTC(ano, mes - 1, dia)).getUTCDay()] };
  }

  function rotuloDia(iso) {
    const p = partes(iso);
    return `${p.semana.charAt(0).toUpperCase()}${p.semana.slice(1)}, ${p.dia}`;
  }

  function horaLocal(iso, fuso) {
    try {
      return new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit', hour12: false,
                                                timeZone: fuso }).format(new Date(iso));
    } catch (erro) { return iso.slice(11, 16); }
  }

  /* ----------------------------------------------------------- desenho */
  function renderServicos(servicos) {
    serviceBox.setAttribute('aria-busy', 'false');
    if (!servicos.length) {
      serviceBox.innerHTML = '<p class="grade-aviso">Nenhum serviço disponível no momento.</p>';
      return;
    }
    serviceBox.innerHTML = servicos.map((servico, indice) =>
      `<button type="button" class="service-option${indice === 0 ? ' selected' : ''}"` +
      ` data-servico-id="${servico.id}" data-servico="${escapar(servico.nome)}"` +
      ` data-preco="${escapar(servico.preco)}" data-duracao="${escapar(servico.duracao)}"` +
      ` data-duracao-min="${servico.duracao_min}">` +
      `<b>${escapar(servico.nome)}</b><span>${escapar(servico.duracao)} · ${escapar(servico.preco)}</span></button>`
    ).join('');
  }

  function renderBarbeiros() {
    barberBox.setAttribute('aria-busy', 'false');
    const daCasa = state.equipe.filter((p) => (p.servicos || []).includes(state.servicoId));
    if (!daCasa.length) {
      barberBox.innerHTML = '<p class="grade-aviso">Nenhum barbeiro faz esse serviço.</p>';
      state.profissionalId = null;
      state.barbeiro = '';
      return;
    }
    if (!daCasa.some((p) => p.id === state.profissionalId)) {
      state.profissionalId = daCasa[0].id;
      state.barbeiro = daCasa[0].apelido;
    }
    barberBox.innerHTML = daCasa.map((p) =>
      `<button type="button" class="barber-option${p.id === state.profissionalId ? ' selected' : ''}"` +
      ` data-profissional-id="${p.id}" data-barber="${escapar(p.apelido)}">` +
      `<i>${escapar(initials(p.nome))}</i><span><b>${escapar(p.nome)}</b>` +
      `<small>${escapar(p.bio || 'Barbeiro da casa')}</small></span></button>`
    ).join('');
  }

  function renderDias(dias) {
    dateList.setAttribute('aria-busy', 'false');
    const comVaga = dias.filter((dia) => dia.livres > 0).slice(0, DIAS_NA_TIRA);
    if (!comVaga.length) {
      const vazio = dias.find((dia) => dia.motivo_texto) || {};
      dateList.innerHTML = `<p class="grade-aviso"><b>Nenhum horário livre no período.</b> ` +
                           `${escapar(vazio.motivo_texto || 'Tente outro serviço ou barbeiro.')}</p>`;
      state.dia = null;
      return false;
    }
    dateList.innerHTML = comVaga.map((dia) => {
      const p = partes(dia.data);
      return `<button type="button" class="date-option" data-date="${dia.data}"` +
             ` title="${dia.livres} horário(s) livre(s)">` +
             `<span>${p.semana}</span><b>${p.dia}</b><small>${MESES_CURTOS[p.mes - 1]}</small></button>`;
    }).join('');
    if (!state.dia || !comVaga.some((dia) => dia.data === state.dia)) {
      state.dia = comVaga[0].data;
    }
    marcarDiaEscolhido();
    return true;
  }

  function marcarDiaEscolhido() {
    dateList.querySelectorAll('.date-option').forEach((botao) => {
      botao.classList.toggle('selected', botao.dataset.date === state.dia);
    });
  }

  function renderHorarios(slots, motivo) {
    timeBox.setAttribute('aria-busy', 'false');
    state.diaRotulo = state.dia ? rotuloDia(state.dia) : '';
    hoursLabel.textContent = state.diaRotulo ? `Horários livres · ${state.diaRotulo.toLowerCase()}` : 'Horários livres';
    timeBox.innerHTML = '';
    if (!slots.length) {
      timeBox.innerHTML = `<p class="grade-aviso">${escapar(motivo)}</p>`;
      state.hora = null;
      atualizarResumo();
      return;
    }
    timeBox.innerHTML = slots.map((slot) =>
      `<button type="button" data-hora="${slot.hora}"${slot.hora === state.hora ? ' class="selected"' : ''}>` +
      `${slot.hora}</button>`).join('');
    if (state.hora && !slots.some((slot) => slot.hora === state.hora)) state.hora = null;
    atualizarResumo();
  }

  function atualizarResumo() {
    const quando = state.hora ? `${state.diaRotulo} às ${state.hora}` : 'Escolha um horário livre';
    summary.innerHTML = `<span>${escapar(state.servico || 'Serviço')} · ${escapar(state.barbeiro || 'barbeiro')}</span>` +
                        `<b>${escapar(quando)}</b><small>${escapar(state.duracao)} · ${escapar(state.preco)}</small>`;
    submit.disabled = !state.hora || state.carregando;
  }

  /* ------------------------------------------------------------- consulta */
  /* O cliente já pode ter outro agendamento no mesmo horário (regra 7 do plano): o servidor
     recusa, então nem oferecemos o slot para ele. */
  function euOcupado(iso) {
    const inicio = new Date(iso).getTime();
    const fim = inicio + (state.duracaoMin || 30) * 60000;
    return (state.meus || []).some((agendamento) => {
      if (!['agendado', 'confirmado'].includes(agendamento.status)) return false;
      return new Date(agendamento.inicio).getTime() < fim && new Date(agendamento.fim).getTime() > inicio;
    });
  }

  async function carregarDias() {
    const de = isoLocal(-1);  // um dia atrás cobre quem abre o site em outro fuso
    const ate = isoLocal(DIAS_CONSULTA);
    const resposta = await publico(`/api/publica/disponibilidade?servico_id=${state.servicoId}` +
                                   `&profissional_id=${state.profissionalId}&de=${de}&ate=${ate}`);
    state.fuso = resposta.fuso || FUSO_PADRAO;
    return renderDias(resposta.dias || []);
  }

  async function carregarHorarios() {
    if (!state.servicoId || !state.profissionalId || !state.dia) {
      renderHorarios([], 'Nenhum barbeiro disponível para esse serviço.');
      return;
    }
    const resposta = await publico(`/api/publica/disponibilidade?servico_id=${state.servicoId}` +
                                   `&profissional_id=${state.profissionalId}&data=${state.dia}`);
    state.fuso = resposta.fuso || state.fuso;
    const barbeiro = (resposta.profissionais || [])[0] || {};
    const todos = (barbeiro.slots || []).map((iso) => ({ iso: iso, hora: horaLocal(iso, state.fuso) }));
    const livres = todos.filter((slot) => !euOcupado(slot.iso));
    if (todos.length && !livres.length) {
      renderHorarios([], 'Você já tem um agendamento nesse horário.');
      return;
    }
    renderHorarios(livres, resposta.motivo_texto || 'Sem vaga nesse dia — escolha outro.');
  }

  async function atualizarGrade(recarregarDias = true) {
    if (!state.servicoId) return;
    state.carregando = true;
    atualizarResumo();
    try {
      if (recarregarDias && !(await carregarDias())) {
        renderHorarios([], 'Escolha outro dia.');
        return;
      }
      await carregarHorarios();
    } catch (erro) {
      dateList.innerHTML = `<p class="grade-aviso">${escapar(erro.message || 'Não consegui carregar os dias agora.')}</p>`;
      renderHorarios([], 'Não consegui carregar os horários agora.');
    } finally {
      state.carregando = false;
      ultimaRecarga = Date.now();
      atualizarResumo();
    }
  }

  async function carregarCatalogo() {
    const [catalogo, equipe] = await Promise.all([publico('/api/publica/servicos'),
                                                  publico('/api/publica/equipe')]);
    const servicos = catalogo.servicos || [];
    state.equipe = equipe.profissionais || [];
    if (servicos.length) {
      const primeiro = servicos[0];
      state.servicoId = primeiro.id;
      state.servico = primeiro.nome;
      state.preco = primeiro.preco;
      state.duracao = primeiro.duracao;
      state.duracaoMin = primeiro.duracao_min;
    }
    renderServicos(servicos);
    renderBarbeiros();
    await atualizarGrade();
  }

  /* -------------------------------------------------------------- eventos */
  serviceBox.addEventListener('click', (evento) => {
    const botao = evento.target.closest('button');
    if (!botao || botao.dataset.servicoId === String(state.servicoId)) return;
    serviceBox.querySelectorAll('button').forEach((item) => item.classList.remove('selected'));
    botao.classList.add('selected');
    state.servicoId = Number(botao.dataset.servicoId);
    state.servico = botao.dataset.servico;
    state.preco = botao.dataset.preco;
    state.duracao = botao.dataset.duracao;
    state.duracaoMin = Number(botao.dataset.duracaoMin);
    state.hora = null;
    state.dia = null;
    renderBarbeiros();
    atualizarResumo();
    atualizarGrade();
  });

  barberBox.addEventListener('click', (evento) => {
    const botao = evento.target.closest('button');
    if (!botao || botao.dataset.profissionalId === String(state.profissionalId)) return;
    barberBox.querySelectorAll('button').forEach((item) => item.classList.remove('selected'));
    botao.classList.add('selected');
    state.profissionalId = Number(botao.dataset.profissionalId);
    state.barbeiro = botao.dataset.barber;
    state.hora = null;
    state.dia = null;
    atualizarGrade();
  });

  dateList.addEventListener('click', (evento) => {
    const botao = evento.target.closest('button');
    if (!botao || botao.dataset.date === state.dia) return;
    state.dia = botao.dataset.date;
    marcarDiaEscolhido();
    atualizarGrade(false);   // a tira de dias não mudou: só os horários
  });

  timeBox.addEventListener('click', (evento) => {
    const botao = evento.target.closest('button');
    if (!botao) return;
    timeBox.querySelectorAll('button').forEach((item) => item.classList.remove('selected'));
    botao.classList.add('selected');
    state.hora = botao.dataset.hora;
    atualizarResumo();
  });

  // Voltou para a aba? A grade pode ter mudado (outra pessoa marcou).
  document.addEventListener('visibilitychange', () => {
    if (document.hidden || !usuario || !state.servicoId) return;
    if (Date.now() - ultimaRecarga < SEGUNDOS_ENTRE_RECARGAS * 1000) return;
    atualizarGrade();
  });

  form.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    if (!state.hora) {
      feedback.textContent = 'Escolha um horário livre para confirmar.';
      return;
    }
    submit.disabled = true;
    feedback.textContent = 'Confirmando seu horário…';
    try {
      const resposta = await window.MagnoAuth.pedir('/api/bookings', {
        method: 'POST',
        body: JSON.stringify({ name: usuario.nome, phone: document.querySelector('#phone').value.trim(),
                               service: state.servico, barber: state.barbeiro,
                               date: state.dia, time: state.hora }),
      });
      const quando = `${state.diaRotulo} às ${state.hora}`;
      feedback.textContent = `Fechado. Código ${resposta.agendamento.codigo} — ${quando}.`;
      const conta = await window.MagnoAuth.pedir('/api/account');
      renderUser(conta.usuario);
      renderBookings(conta.agendamentos);
      state.meus = conta.agendamentos || [];
      state.hora = null;
      // O horário que acabou de ser marcado já não aparece mais para ninguém.
      await atualizarGrade();
    } catch (erro) {
      if (!handleError(erro)) {
        feedback.textContent = erro.message || 'Não consegui confirmar agora. Tente novamente.';
        if (erro.status === 409) atualizarGrade();  // alguém chegou antes: mostra a grade nova
      }
    } finally {
      submit.disabled = false;
      atualizarResumo();
    }
  });

  /* ---------------------------------------------------------------- conta */
  function renderUser(user) {
    usuario = user;
    document.querySelector('#clientName').textContent = user.nome;
    document.querySelector('#clientAvatar').textContent = initials(user.nome);
    document.querySelector('#clientAvatar').setAttribute('aria-label', `Conta de ${user.nome}`);
    document.querySelector('#clientSubtext').textContent = user.idade
      ? `${user.idade} anos · sua agenda, do seu jeito.`
      : 'Sua agenda, do seu jeito.';
    // O agendamento é sempre em nome de quem está logado — o nome vive no perfil.
    document.querySelector('#bookingName').textContent = user.nome;
    document.querySelector('#bookingMeta').textContent = [user.idade ? `${user.idade} anos` : '', user.telefone_formatado || 'sem telefone cadastrado'].filter(Boolean).join(' · ');
    document.querySelector('#phone').value = user.telefone_formatado || '';
  }
  function renderBookings(bookings) {
    if (!bookings.length) return;
    const booking = bookings.find((item) => ['agendado', 'confirmado'].includes(item.status)) || bookings[0];
    const date = new Date(booking.inicio);
    const when = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'long', timeStyle: 'short', timeZone: state.fuso || FUSO_PADRAO }).format(date);
    document.querySelector('#upcomingTitle').textContent = 'Seu próximo horário está reservado.';
    document.querySelector('#upcomingText').textContent = `${when} · código ${booking.codigo}`;
    document.querySelector('#upcomingSymbol').textContent = '✓';
  }
  function handleError(error) {
    if (error && error.status === 401) {
      window.MagnoAuth.sair();
      login();
      return true;
    }
    return false;
  }

  document.querySelector('#switchAccount').addEventListener('click', async () => {
    await window.MagnoAuth.encerrarSessao();
    login();
  });

  document.querySelector('#logoutButton').addEventListener('click', async () => {
    await window.MagnoAuth.encerrarSessao();
    location.replace('/login?notice=logout');
  });

  // O avatar é o botão da conta: clicar nele abre o menu com "Meu perfil" e "Sair".
  const avatar = document.querySelector('#clientAvatar');
  const menuConta = document.querySelector('#menuConta');
  function fecharMenu() {
    if (!menuConta || menuConta.hidden) return;
    menuConta.hidden = true;
    avatar.setAttribute('aria-expanded', 'false');
  }
  function alternarMenu() {
    const abrir = menuConta.hidden;
    menuConta.hidden = !abrir;
    avatar.setAttribute('aria-expanded', String(abrir));
    if (abrir) {
      const primeiro = menuConta.querySelector('[role="menuitem"]');
      if (primeiro) primeiro.focus();
    }
  }
  avatar.addEventListener('click', (evento) => {
    evento.stopPropagation();
    alternarMenu();
  });
  document.addEventListener('click', (evento) => {
    if (!menuConta.contains(evento.target) && evento.target !== avatar) fecharMenu();
  });
  document.addEventListener('keydown', (evento) => {
    if (evento.key === 'Escape') {
      fecharMenu();
      avatar.focus();
    }
  });
  document.querySelector('#menuSair').addEventListener('click', async () => {
    await window.MagnoAuth.encerrarSessao();
    location.replace('/login?notice=logout');
  });

  async function start() {
    const auth = window.MagnoAuth;
    // Um Bearer válido libera a conta em qualquer navegação. Sem ele, nunca exibimos dados.
    if (!auth || !auth.lerSessao()) return login();
    try {
      const result = await auth.pedir('/api/account');
      // Conta sem nome/idade ainda passa por /perfil antes de ver a agenda.
      if (!result.usuario.perfil_completo) return irParaPerfil();
      renderUser(result.usuario);
      state.meus = result.agendamentos || [];
      renderBookings(result.agendamentos);
      content.hidden = false;
      document.body.classList.remove('account-loading');
      await carregarCatalogo();
    } catch (error) { if (!handleError(error)) login(); }
  }
  document.querySelector('#year').textContent = new Date().getFullYear();
  start();
})();
