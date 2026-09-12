document.addEventListener('DOMContentLoaded', () => {
  const search = document.querySelector('[data-component-search]');
  const buttons = [...document.querySelectorAll('[data-kind-button]')];
  const cards = [...document.querySelectorAll('[data-component-grid] .component-card')];
  const empty = document.querySelector('[data-empty-state]');
  let selectedKind = '';

  const filterCards = () => {
    const query = (search?.value || '').trim().toLocaleLowerCase('ru');
    let visible = 0;
    cards.forEach((card) => {
      const matchesText = !query || (card.dataset.search || '').includes(query);
      const matchesKind = !selectedKind || card.dataset.kind === selectedKind;
      card.hidden = !(matchesText && matchesKind);
      if (!card.hidden) visible += 1;
    });
    if (empty) empty.hidden = visible !== 0;
  };

  search?.addEventListener('input', filterCards);
  buttons.forEach((button) => button.addEventListener('click', () => {
    selectedKind = button.dataset.kindButton || '';
    buttons.forEach((item) => item.classList.toggle('active', item === button));
    filterCards();
  }));

  const navButton = document.querySelector('[data-mobile-nav]');
  const sidebar = document.querySelector('[data-sidebar]');
  navButton?.addEventListener('click', () => sidebar?.classList.toggle('open'));
});
