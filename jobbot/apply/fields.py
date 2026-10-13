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
  const meaningful = s => /[A-Za-z]{2}/.test(s || '');
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
  // A fresh prefix per scan: fields from an earlier step of a multi-page form keep their old ids, and a
  // repeated id would make every action on the new field ambiguous.
  const scan = Date.now().toString(36) + Math.random().toString(36).slice(2, 5);
  const tag = el => { const existing = el.getAttribute('data-jobbot-id'); if (existing) return existing; const id = 'f' + scan + '_' + (n++); el.setAttribute('data-jobbot-id', id); return id; };
  // What a combobox shows as chosen (react-select keeps it next to the input, not in it), ignoring its
  // option list and "Select..." placeholders.
  const shownValue = el => {
    let node = el;
    for (let i = 0; i < 2 && node; i++) {
      node = parentOf(node);
      if (!node) break;
      const copy = node.cloneNode(true);
      copy.querySelectorAll('[role="listbox"], [role="option"], input, label').forEach(x => x.remove());
      const t = clean(copy.textContent).replace(/^(select|choose|please select)\b[\s.…]*/i, '');
      if (t) return t;
    }
    return '';
  };
  const required = (el, label) => {
    if (el.closest('.ashby-application-form-texting-consent-description')) return !!el.required;
    const labels = Array.from(el.labels || []);
    const field = el.closest('[data-field-path], .ashby-application-form-field-entry, fieldset');
    if (field) labels.push(field.querySelector(':scope > label'));
    const marked = labels.filter(Boolean).some(l => /(?:^|[ _-])required(?:[ _-]|$)/i.test(l.className || '') || /\*\s*$/.test(l.innerText || ''));
    return !!(el.required || el.getAttribute('aria-required') === 'true' || marked || /\*\s*$/.test(label) || /\brequired\b/i.test(el.getAttribute('aria-label') || ''));
  };

  const labelFor = el => {
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const t = clean(lb.split(/\s+/).map(id => textOf(byId(el, id))).join(' '));
      if (t) return t;
    }
    if (el.id) {
      const r = el.getRootNode();
      const l = r.querySelector && r.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (l && meaningful(textOf(l))) return textOf(l);
    }
    const wrap = el.closest('label');
    if (wrap) {
      // A label that wraps its control also "contains" the control's text (a select's options, a
      // textarea's value): read the label without them.
      const copy = wrap.cloneNode(true);
      copy.querySelectorAll('select, option, textarea, input, button, [role="listbox"], [role="option"]').forEach(x => x.remove());
      const t = clean(copy.textContent);
      if (meaningful(t)) return t;
    }
    const aria = el.getAttribute('aria-label');
    if (aria) return clean(aria);
    let node = el;
    for (let i = 0; i < 6 && node; i++) {
      node = parentOf(node);
      if (!node || !node.querySelector) break;
      const cand = node.querySelector(':scope > label, :scope > legend, :scope > [class*="label" i], :scope > [class*="question" i], :scope > [class*="title" i]');
      if (cand && !cand.contains(el) && meaningful(textOf(cand))) return textOf(cand);
    }
    const fallback = clean(el.getAttribute('placeholder') || el.name || '');
    return meaningful(fallback) && !/^(rec-form_|field_)?[0-9]+$/.test(fallback) ? fallback : '';
  };

  // The question for a radio/checkbox group: the smallest ancestor holding every
  // member, with the option labels stripped out of its text.
  const groupQuestion = (members, optionLabels) => {
    const messaging = members[0].closest('.ashby-application-form-texting-consent-description');
    if (messaging) return optionLabels.some(o => /WhatsApp/i.test(o)) ? 'WhatsApp messages' : 'SMS text messages';
    const entry = members[0].closest('[data-field-path], .ashby-application-form-field-entry');
    if (entry) { const title = entry.querySelector(':scope > label'); if (title && textOf(title)) return textOf(title); }
    const fs = members[0].closest('fieldset');
    if (fs) { const lg = fs.querySelector(':scope > legend, :scope > label'); if (lg && textOf(lg)) return textOf(lg); }
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
      if (type === 'file') { out.push({ id: tag(el), kind: 'file', label: labelFor(el), name: el.name || el.id || '', required: required(el, labelFor(el)), value: Array.from(el.files || []).map(f => f.name).join(', ') }); continue; }
      if (type === 'radio' || type === 'checkbox') {
        if (el.hidden || el.closest('.ashby-application-form-input-yesno')) continue; // Backing state is handled through the buttons.
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
        inputmode: el.getAttribute('inputmode') || '',
        unit: (el.closest('.form-group, .field, [data-field-path]')?.innerText || '').match(/\bLPA\b|\blakhs?\b|₹|\bINR\b/i)?.[0] || '',
        text: t === 'select' && el.selectedIndex >= 0 ? clean(el.options[el.selectedIndex].text) : '',
        shown: combo ? shownValue(el) : '',
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
    if (!el.children) continue;
    const kids = Array.from(el.children).filter(k => k.tagName === 'BUTTON');
    if (kids.length !== 2) continue;
    const names = kids.map(k => textOf(k).toLowerCase());
    if (names[0] !== 'yes' || names[1] !== 'no' || !visible(el)) continue;
    let question = labelFor(kids[0]);
    let node = el;
    for (let i = 0; i < 4 && !question; i++) {
      node = parentOf(node);
      if (!node) break;
      question = clean(textOf(node).replace(/\bYes\b\s*\bNo\b\s*$/, ''));
    }
    out.push({ id: kids.map(tag).join(','), kind: 'yesno', label: question.slice(0, 400), options: ['Yes', 'No'],
               required: required(kids[0], question), value: kids.map(k => k.getAttribute('aria-pressed') === 'true' || /selected|active/i.test(k.className)) });
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
