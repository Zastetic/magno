/* Barbearia Magnum — /perfil: primeiro acesso em duas perguntas (nome → idade) e
   segue para os agendamentos. Nada é exibido sem um Bearer válido (mesma regra da conta). */
(() => {
  'use strict';

  const caixa = document.querySelector('#caixaPerfil');
  const aviso = document.querySelector('#aviso');
  const formNome = document.querySelector('#formNome');
  const formIdade = document.querySelector('#formIdade');
  const campoNome = document.querySelector('#nome');
  const campoIdade = document.querySelector('#idade');
  const marcaPasso1 = document.querySelector('#marcaPasso1');
  const marcaPasso2 = document.querySelector('#marcaPasso2');
  const btnVoltar = document.querySelector('#btnVoltarNome');
  const btnNome = formNome.querySelector('button[type=submit]');
  const btnIdade = formIdade.querySelector('button[type=submit]');
  const linkAgenda = document.querySelector('#linkAgenda');
  const dica = document.querySelector('#dicaPerfil');
  const IDADE_MIN = 13;
  const IDADE_MAX = 120;
  let perfil = { nome: '', idade: null };

  function mostrar(msg, tipo) {
    aviso.textContent = msg || '';
    aviso.hidden = !msg;
    aviso.className = 'aviso ' + (tipo || '');
  }

  function paraLogin() {
    location.replace('/login?next=/perfil');
  }

  function mostrarPasso(passo) {
    const primeiro = passo === 1;
    formNome.hidden = !primeiro;
    formIdade.hidden = primeiro;
    marcaPasso1.classList.toggle('ativo', primeiro);
    marcaPasso2.classList.toggle('ativo', !primeiro);
    document.querySelector('#tituloPerfil').textContent = primeiro
      ? 'Como você quer ser chamado?'
      : 'Quantos anos você tem?';
    document.querySelector('#subtituloPerfil').textContent = primeiro
      ? 'É só o seu nome: com ele a barbearia sabe quem está chegando para o horário.'
      : 'A idade fica na sua ficha e ajuda a barbearia a acertar o serviço. Depois é só marcar.';
    mostrar('');
    (primeiro ? campoNome : campoIdade).focus();
  }

  function nomeLimpo(valor) {
    return valor.trim().replace(/\s+/g, ' ');
  }

  formNome.addEventListener('submit', (evento) => {
    evento.preventDefault();
    const nome = nomeLimpo(campoNome.value);
    if (nome.length < 2) {
      mostrar('Digite seu nome com pelo menos 2 letras.', 'erro');
      campoNome.focus();
      return;
    }
    if (nome.length > 80) {
      mostrar('O nome pode ter até 80 caracteres.', 'erro');
      return;
    }
    perfil.nome = nome;
    document.querySelector('#nomeConfirmado').textContent = nome;
    mostrarPasso(2);
  });

  btnVoltar.addEventListener('click', () => mostrarPasso(1));

  formIdade.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    const idade = Number.parseInt(campoIdade.value, 10);
    if (!Number.isInteger(idade) || idade < IDADE_MIN || idade > IDADE_MAX) {
      mostrar(`Digite uma idade entre ${IDADE_MIN} e ${IDADE_MAX}.`, 'erro');
      campoIdade.focus();
      return;
    }
    const auth = window.MagnoAuth;
    if (!auth || !auth.lerSessao()) return paraLogin();

    btnIdade.disabled = true;
    try {
      const resposta = await auth.pedir('/api/account/profile', {
        method: 'PATCH',
        body: JSON.stringify({ nome: perfil.nome, idade }),
      });
      perfil = { nome: resposta.usuario.nome, idade: resposta.usuario.idade };
      mostrar('Tudo certo! Levando você para os agendamentos…', 'ok');
      location.replace('/account');
    } catch (erro) {
      if (erro.status === 401) {
        auth.sair();
        return paraLogin();
      }
      mostrar(erro.message || 'Não consegui salvar agora. Tente de novo.', 'erro');
    } finally {
      btnIdade.disabled = false;
    }
  });

  async function iniciar() {
    const auth = window.MagnoAuth;
    // Sem Bearer não existe dado pessoal na tela: manda para o login e volta para cá.
    if (!auth || !auth.lerSessao()) return paraLogin();
    try {
      const { usuario } = await auth.pedir('/api/account');
      perfil = { nome: usuario.nome || '', idade: usuario.idade ?? null };
      campoNome.value = perfil.nome;
      campoIdade.value = perfil.idade ?? '';
      linkAgenda.hidden = !usuario.perfil_completo;
      if (usuario.perfil_completo) {
        dica.textContent = 'Mudou algo? Atualize aqui — a agenda continua no mesmo lugar, em Minha agenda.';
      }
      caixa.hidden = false;
      document.body.classList.remove('account-loading');
      // Sempre começa pelo nome: o nome conta o primeiro acesso e é o que aparece na agenda.
      mostrarPasso(1);
    } catch (erro) {
      if (erro.status === 401) {
        auth.sair();
        return paraLogin();
      }
      caixa.hidden = false;
      document.body.classList.remove('account-loading');
      mostrarPasso(1);
      mostrar(erro.message || 'Não consegui carregar seu perfil agora.', 'erro');
    }
  }

  document.querySelector('#ano').textContent = new Date().getFullYear();
  iniciar();
})();
