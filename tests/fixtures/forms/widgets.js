// Minimal look-alikes of the widgets real job sites use, with the same quirks jobbot has to handle.
// React-select style combobox: the chosen value is shown next to the input, not in it.
function reactSelect(root, options, { overlay = false, typeahead = false } = {}) {
  const input = root.querySelector('input'), menu = root.querySelector('[role=listbox]'), shown = root.querySelector('.sv');
  const render = () => {
    const q = input.value.toLowerCase();
    if (typeahead && q.length < 2) { menu.hidden = true; return; }
    menu.innerHTML = options.filter(o => !q || o.toLowerCase().includes(q))
      .map(o => `<div role="option" class="opt">${o}</div>`).join('');
    menu.hidden = !menu.children.length;
    input.setAttribute('aria-expanded', String(!menu.hidden));
  };
  const open = () => { if (!typeahead) render(); };
  root.addEventListener('mousedown', e => { if (!menu.contains(e.target)) open(); });   // opens from the control, not the menu
  input.addEventListener('keydown', e => { if (e.key === 'ArrowDown') open(); if (e.key === 'Escape') menu.hidden = true; });
  input.addEventListener('input', render);
  menu.addEventListener('click', e => {
    const o = e.target.closest('[role=option]'); if (!o) return;
    shown.textContent = o.textContent; root.dataset.value = o.textContent; input.value = ''; menu.hidden = true;
  });
  if (overlay) {                                      // placeholder div covering the input: plain clicks are intercepted
    const cover = document.createElement('div'); cover.className = 'cover'; cover.textContent = 'Select...';
    root.querySelector('.ctl').appendChild(cover);
  }
}
// Workday style list button, optionally with nested categories.
function listButton(btn, tree) {
  const pop = document.createElement('div'); pop.setAttribute('role', 'listbox'); pop.hidden = true; pop.className = 'pop';
  btn.after(pop);
  const show = items => { pop.innerHTML = items.map(i => `<div role="option">${typeof i === 'string' ? i : i.name}</div>`).join(''); pop.hidden = false; };
  btn.addEventListener('click', () => show(tree));
  pop.addEventListener('click', e => {
    const o = e.target.closest('[role=option]'); if (!o) return;
    const item = tree.find(i => (typeof i === 'string' ? i : i.name) === o.textContent)
      || tree.flatMap(i => i.children || []).find(c => c === o.textContent);
    if (item && item.children) { show(item.children); return; }
    btn.textContent = o.textContent; pop.hidden = true;
  });
}
