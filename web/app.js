(() => {
  const menuButton = document.querySelector('#menuBotao');
  const navigation = document.querySelector('#nav');
  const year = document.querySelector('#ano');

  function toggleMenu() {
    const isOpen = navigation.classList.toggle('aberto');
    menuButton.setAttribute('aria-expanded', String(isOpen));
  }

  menuButton?.addEventListener('click', toggleMenu);
  year.textContent = new Date().getFullYear();
})();
