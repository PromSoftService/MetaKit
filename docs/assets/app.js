document.addEventListener('DOMContentLoaded', () => {
  const search = document.querySelector('[data-component-search]');
  const kind = document.querySelector('[data-kind-filter]');
  const category = document.querySelector('[data-category-filter]');
  const cards = [...document.querySelectorAll('.component-card')];
  const empty = document.querySelector('[data-empty-state]');

  const applyFilters = () => {
    if (!cards.length) return;
    const query = (search?.value || '').trim().toLocaleLowerCase('ru');
    const kindValue = kind?.value || '';
    const categoryValue = category?.value || '';
    let visible = 0;
    cards.forEach((card) => {
      const matchesQuery = !query || (card.dataset.search || '').includes(query);
      const matchesKind = !kindValue || card.dataset.kind === kindValue;
      const matchesCategory = !categoryValue || card.dataset.category === categoryValue;
      card.hidden = !(matchesQuery && matchesKind && matchesCategory);
      if (!card.hidden) visible += 1;
    });
    if (empty) empty.style.display = visible ? 'none' : 'block';
  };

  search?.addEventListener('input', applyFilters);
  kind?.addEventListener('change', applyFilters);
  category?.addEventListener('change', applyFilters);

  document.querySelectorAll('[data-copy]').forEach((button) => {
    button.addEventListener('click', async () => {
      const target = document.getElementById(button.dataset.copy);
      if (!target) return;
      await navigator.clipboard.writeText(target.textContent || '');
      const previous = button.textContent;
      button.textContent = 'Скопировано';
      window.setTimeout(() => { button.textContent = previous; }, 1400);
    });
  });

  const mobileButton = document.querySelector('[data-mobile-nav]');
  const sidebar = document.querySelector('.sidebar');
  mobileButton?.addEventListener('click', () => sidebar?.classList.toggle('open'));
});
