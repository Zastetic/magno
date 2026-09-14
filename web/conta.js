/* Barbearia Magnum — /account: agenda do cliente.
   O nome e a idade vêm do perfil (/perfil). Sem Bearer válido, esta tela não mostra nada. */
(() => {
  'use strict';

  const state = { service: 'Corte masculino', price: 'R$ 45', duration: '30 min', barber: 'Rafael', date: 'Qua, 17', dateISO: '2026-09-17', time: '14:00' };
  const content = document.querySelector('#accountContent');
  const summary = document.querySelector('#bookingSummary');
  const feedback = document.querySelector('#bookingFeedback');
  const form = document.querySelector('#bookingForm');
  const submit = document.querySelector('.confirm-booking');
  let usuario = null;

  function login() { location.replace('/login?next=/account'); }
  function irParaPerfil() { location.replace('/perfil'); }
  function initials(name) { return (name || '—').trim().slice(0, 1).toUpperCase(); }
  function updateSummary() {
    summary.innerHTML = `<span>${state.service} · ${state.barber}</span><b>${state.date} às ${state.time}</b><small>${state.duration} · ${state.price}</small>`;
  }
  function selectOption(container, button, onSelect) {
    container.querySelectorAll('button').forEach((item) => item.classList.remove('selected'));
    button.classList.add('selected');
    onSelect(button);
    updateSummary();
  }
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
    const when = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'long', timeStyle: 'short', timeZone: 'America/Sao_Paulo' }).format(date);
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

  document.querySelector('#serviceOptions').addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (button) selectOption(event.currentTarget, button, (item) => Object.assign(state, { service: item.dataset.service, price: item.dataset.price, duration: item.dataset.duration }));
  });
  document.querySelector('#barberOptions').addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (button) selectOption(event.currentTarget, button, (item) => { state.barber = item.dataset.barber; });
  });
  document.querySelector('#dateList').addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (button) selectOption(event.currentTarget, button, (item) => { state.date = `${item.querySelector('span').textContent}, ${item.querySelector('b').textContent}`; state.dateISO = item.dataset.date; });
  });
  document.querySelector('#timeOptions').addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (button) selectOption(event.currentTarget, button, (item) => { state.time = item.textContent; });
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    submit.disabled = true;
    feedback.textContent = 'Confirmando seu horário…';
    try {
      const response = await window.MagnoAuth.pedir('/api/bookings', { method: 'POST', body: JSON.stringify({ name: usuario.nome, phone: document.querySelector('#phone').value.trim(), service: state.service, barber: state.barber, date: state.dateISO, time: state.time }) });
      feedback.textContent = `Fechado. Código ${response.agendamento.codigo} — ${state.date} às ${state.time}.`;
      const refreshed = await window.MagnoAuth.pedir('/api/account');
      renderUser(refreshed.usuario);
      renderBookings(refreshed.agendamentos);
    } catch (error) {
      if (!handleError(error)) feedback.textContent = error.message || 'Não consegui confirmar agora. Tente novamente.';
    } finally { submit.disabled = false; }
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
      renderBookings(result.agendamentos);
      content.hidden = false;
      document.body.classList.remove('account-loading');
    } catch (error) { if (!handleError(error)) login(); }
  }
  document.querySelector('#year').textContent = new Date().getFullYear();
  start();
})();
