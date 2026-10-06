"""Discover form fields on the current page, including inside open shadow roots.

Each field gets a `data-jobbot-id` attribute so Playwright can address it later
(Playwright's CSS engine pierces open shadow DOM).
"""

SCAN_JS = r"""
() => {
  const out = [];
  let n = 0;
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const textOf = el => el ? clean(el.innerText || el.textContent) : '';
  const byId = (el, id) => {
    const r = el.getRootNode();
    return (r.getElementById ? r.getElementById(id) : null) || document.getElementById(id);
  };
  const parentOf = el => el.parentElement || (el.getRootNode && el.getRootNode().host) || null;
  const visible = el => {
    if (!el.getClientRects().length) return false;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || st.display === 'none') return false;
    // react-select and similar widgets keep an invisible input just for form validation
    if (el.getAttribute('aria-hidden') === 'true' || (el.tabIndex === -1 && parseFloat(st.opacity) === 0)) return false;
    return true;
  };
  const tag = el => { const id = 'f' + (n++); el.setAttribute('data-jobbot-id', id); return id; };
  const required = (el, label) =>
    !!(el.required || el.getAttribute('aria-required') === 'true' || /\*\s*$/.test(label) || /\brequired\b/i.test(el.getAttribute('aria-label') || ''));

  const labelFor = el => {
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const t = clean(lb.split(/\s+/).map(id => textOf(byId(el, id))).join(' '));
      if (t) return t;
    }
    if (el.id) {
      const r = el.getRootNode();
      const l = r.querySelector && r.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (l && textOf(l)) return textOf(l);
    }
    const wrap = el.closest('label');
    if (wrap && textOf(wrap)) return textOf(wrap);
    const aria = el.getAttribute('aria-label');
    if (aria) return clean(aria);
    let node = el;
    for (let i = 0; i < 6 && node; i++) {
      node = parentOf(node);
      if (!node || !node.querySelector) break;
      const cand = node.querySelector(':scope > label, :scope > legend, :scope > [class*="label" i], :scope > [class*="question" i], :scope > [class*="title" i]');
      if (cand && !cand.contains(el) && textOf(cand)) return textOf(cand);
    }
    return clean(el.getAttribute('placeholder') || el.name || '');
  };

  // The question for a radio/checkbox group: the smallest ancestor holding every
  // member, with the option labels stripped out of its text.
  const groupQuestion = (members, optionLabels) => {
    const fs = members[0].closest('fieldset');
    if (fs) { const lg = fs.querySelector('legend'); if (lg && textOf(lg)) return textOf(lg); }
    const rg = members[0].closest('[role="radiogroup"],[role="group"]');
    if (rg) {
      const lb = rg.getAttribute('aria-labelledby');
      if (lb) { const t = clean(lb.split(/\s+/).map(id => textOf(byId(rg, id))).join(' ')); if (t) return t; }
      if (rg.getAttribute('aria-label')) return clean(rg.getAttribute('aria-label'));
    }
    let node = members[0];
    for (let i = 0; i < 8 && node; i++) {
      node = parentOf(node);
      if (!node || !node.contains) break;
      if (members.every(m => node.contains(m))) {
        let t = textOf(node);
        for (const o of optionLabels) t = t.replace(o, ' ');
        t = clean(t);
        if (t) return t.slice(0, 400);
      }
    }
    return '';
  };

  const all = [];
  const walk = root => root.querySelectorAll('*').forEach(el => { all.push(el); if (el.shadowRoot) walk(el.shadowRoot); });
  walk(document);

  const groups = {};
  for (const el of all) {
    const t = el.tagName.toLowerCase();
    if (t === 'input' || t === 'select' || t === 'textarea') {
      const type = (el.getAttribute('type') || t).toLowerCase();
      // Never touch passwords; jobbot leaves sign-in to the user.
      if (['hidden', 'submit', 'button', 'image', 'reset', 'password'].includes(type)) continue;
      if (type === 'search' && !el.getAttribute('role')) continue;
      if (type === 'file') { out.push({ id: tag(el), kind: 'file', label: labelFor(el), name: el.name || el.id || '' }); continue; }
      if (type === 'radio' || type === 'checkbox') {
        const key = (el.name || '') + '|' + (el.name ? '' : (parentOf(el) ? Array.from(all).indexOf(parentOf(el)) : n));
        (groups[key] = groups[key] || []).push(el);
        continue;
      }
      if (!visible(el) || el.disabled || el.readOnly && !el.getAttribute('role')) continue;
      const label = labelFor(el);
      const role = (el.getAttribute('role') || '').toLowerCase();
      const combo = role === 'combobox' || el.getAttribute('aria-autocomplete') || el.getAttribute('aria-haspopup') === 'listbox';
      out.push({
        id: tag(el), kind: t === 'select' ? 'select' : combo ? 'combo' : (t === 'textarea' ? 'textarea' : 'text'),
        type, label, required: required(el, label), value: el.value || '', maxlength: el.maxLength || -1,
        text: t === 'select' && el.selectedIndex >= 0 ? clean(el.options[el.selectedIndex].text) : '',
        options: t === 'select' ? Array.from(el.options).map(o => clean(o.text)) : [],
      });
    } else if (t === 'button' && el.getAttribute('aria-haspopup') === 'listbox' && visible(el)) {
      // Workday-style dropdown buttons
      const label = labelFor(el);
      out.push({ id: tag(el), kind: 'listbutton', label, required: required(el, label), value: textOf(el) });
    }
  }

  for (const members of Object.values(groups)) {
    const shown = members.filter(m => visible(m) || (m.labels && m.labels[0] && visible(m.labels[0])));
    if (!shown.length) continue;
    const optionLabels = shown.map(m => (m.labels && m.labels[0] ? textOf(m.labels[0]) : '') || clean(m.getAttribute('aria-label') || m.value));
    const type = (shown[0].getAttribute('type') || '').toLowerCase();
    const question = shown.length === 1 && type === 'checkbox' ? optionLabels[0] : groupQuestion(shown, optionLabels);
    out.push({
      id: shown.map(tag).join(','), kind: type === 'radio' ? 'radio' : (shown.length === 1 ? 'checkbox' : 'checkgroup'),
      label: question, options: optionLabels, required: shown.some(m => required(m, question)) || /\*/.test(question),
      value: shown.map(m => m.checked),
    });
  }

  // Ashby-style Yes/No button pairs
  for (const el of all) {
    if (!el.children || el.children.length !== 2) continue;
    const kids = Array.from(el.children);
    if (!kids.every(k => k.tagName === 'BUTTON')) continue;
    const names = kids.map(k => textOf(k).toLowerCase());
    if (names[0] !== 'yes' || names[1] !== 'no' || !visible(el)) continue;
    let question = '';
    let node = el;
    for (let i = 0; i < 4 && !question; i++) {
      node = parentOf(node);
      if (!node) break;
      question = clean(textOf(node).replace(/\bYes\b\s*\bNo\b\s*$/, ''));
    }
    out.push({ id: kids.map(tag).join(','), kind: 'yesno', label: question.slice(0, 400), options: ['Yes', 'No'],
               required: /\*/.test(question), value: kids.map(k => k.getAttribute('aria-pressed') === 'true' || /selected|active/i.test(k.className)) });
  }
  return out;
}
"""

BUTTONS_JS = r"""
(args) => {
  const [pattern, links] = Array.isArray(args) ? args : [args, false];
  const re = new RegExp(pattern, 'i');
  const hits = [];
  const sel = 'button, input[type=submit], a[role=button], [role=button]' + (links ? ', a[href]' : '');
  const walk = root => root.querySelectorAll(sel).forEach(el => {
    const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
    if (re.test(text) && el.getClientRects().length && !el.disabled) {
      const id = 'b' + Math.random().toString(36).slice(2, 9);
      el.setAttribute('data-jobbot-btn', id);
      hits.push({ id, text });
    }
  });
  walk(document);
  document.querySelectorAll('*').forEach(el => { if (el.shadowRoot) walk(el.shadowRoot); });
  return hits;
}
"""
