"""Discover form fields on the current page, including inside open shadow roots.

Each field gets a `data-jobbot-id` attribute so Playwright can address it later
(Playwright's CSS engine pierces open shadow DOM).
"""

# Prefer the committed widget value. Never search ancestors for the expected
# answer: a label, hint or sibling can contain it even when selection failed.
COMBO_VALUE_JS = r"""el => {
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const root = el.getRootNode();
  const active = root.getElementById?.(el.getAttribute('aria-activedescendant'));
  if (active?.getAttribute('aria-selected') === 'true') return clean(active.innerText);
  let node = el;
  for (let i = 0; i < 2; i++) {
    node = node.parentElement;
    if (!node) break;
    if (node.querySelectorAll('input, select, textarea').length !== 1) break;
    const copy = node.cloneNode(true);
    copy.querySelectorAll('input, label, legend, small, [role="listbox"], [role="option"], [role="status"], [role="alert"], [class*="placeholder" i], .cover')
      .forEach(x => x.remove());
    const excluded = clean([el.getAttribute('aria-labelledby'), el.getAttribute('aria-describedby')].filter(Boolean).join(' '));
    const refs = new Set(excluded ? excluded.split(/\s+/) : []);
    copy.querySelectorAll('[id]').forEach(x => { if (refs.has(x.id)) x.remove(); });
    const t = clean(copy.textContent);
    if (t && !/^(select|choose|please select)(?: one)?[\s.…]*$/i.test(t)) return t;
  }
  return clean(el.value);
}"""

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
  const shownValue = COMBO_VALUE;
  const required = (el, label) => {
    if (el.closest('.ashby-application-form-texting-consent-description')) return !!el.required;
    const labels = Array.from(el.labels || []);
    const field = el.closest('[data-field-path], .ashby-application-form-field-entry, fieldset');
    if (field) labels.push(field.querySelector(':scope > label'));
    const marked = labels.filter(Boolean).some(l => /(?:^|[ _-])required(?:[ _-]|$)/i.test(l.className || '') || /\*\s*$/.test(l.innerText || ''));
    return !!(el.required || el.getAttribute('aria-required') === 'true' || marked || /\*\s*$/.test(label) || /\brequired\b/i.test(el.getAttribute('aria-label') || ''));
  };

  const caption = (text, source) => ({ label: clean(text).slice(0, 800), label_source: source });
  const references = (el, attr) => clean(el.getAttribute(attr)).split(/\s+/).filter(Boolean).map(id => byId(el, id)).filter(Boolean);
  const labelFor = el => {
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const t = clean(lb.split(/\s+/).map(id => textOf(byId(el, id))).join(' '));
      if (t) return caption(t, 'aria-labelledby');
    }
    if (el.id) {
      const r = el.getRootNode();
      const l = r.querySelector && r.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (l && meaningful(textOf(l))) return caption(textOf(l), 'linked label');
    }
    const wrap = el.closest('label');
    if (wrap) {
      // A label that wraps its control also "contains" the control's text (a select's options, a
      // textarea's value): read the label without them.
      const copy = wrap.cloneNode(true);
      copy.querySelectorAll('select, option, textarea, input, button, [role="listbox"], [role="option"]').forEach(x => x.remove());
      const t = clean(copy.textContent);
      if (meaningful(t)) return caption(t, 'wrapping label');
    }
    const aria = el.getAttribute('aria-label');
    if (aria) return caption(aria, 'aria-label');
    let node = el;
    for (let i = 0; i < 6 && node; i++) {
      node = parentOf(node);
      if (!node || !node.querySelector || ['FORM', 'BODY', 'HTML'].includes(node.tagName)) break;
      // A broad wrapper may contain a different field's heading. Never borrow
      // a label explicitly associated with another control.
      if (node.querySelectorAll('input:not([type="hidden"]), select, textarea, button[aria-haspopup="listbox"]').length > 1) break;
      const cand = node.querySelector(':scope > label, :scope > legend, :scope > [class*="label" i], :scope > [class*="question" i], :scope > [class*="title" i]');
      if (cand && !cand.contains(el) && (!cand.control || cand.control === el) && meaningful(textOf(cand)))
        return caption(textOf(cand), 'nearby heading');
    }
    const placeholder = clean(el.getAttribute('placeholder'));
    const name = clean(el.name);
    if (meaningful(placeholder)) return caption(placeholder, 'placeholder');
    return meaningful(name) ? caption(name, 'input name') : caption('', 'unidentified');
  };

  // The question for a radio/checkbox group: the smallest ancestor holding every
  // member, with the option labels stripped out of its text.
  const groupQuestion = (members, optionLabels) => {
    const messaging = members[0].closest('.ashby-application-form-texting-consent-description');
    if (messaging) return caption(optionLabels.some(o => /WhatsApp/i.test(o)) ? 'WhatsApp messages' : 'SMS text messages', 'form group');
    const entry = members[0].closest('[data-field-path], .ashby-application-form-field-entry');
    if (entry) { const title = entry.querySelector(':scope > label'); if (title && textOf(title)) return caption(textOf(title), 'group label'); }
    const fs = members[0].closest('fieldset');
    if (fs) { const lg = fs.querySelector(':scope > legend, :scope > label'); if (lg && textOf(lg)) return caption(textOf(lg), 'group label'); }
    const rg = members[0].closest('[role="radiogroup"],[role="group"]');
    if (rg) {
      const lb = rg.getAttribute('aria-labelledby');
      if (lb) { const t = clean(lb.split(/\s+/).map(id => textOf(byId(rg, id))).join(' ')); if (t) return caption(t, 'group label'); }
      if (rg.getAttribute('aria-label')) return caption(rg.getAttribute('aria-label'), 'group label');
    }
    let node = members[0];
    for (let i = 0; i < 8 && node; i++) {
      node = parentOf(node);
      if (!node || !node.contains || ['FORM', 'BODY', 'HTML'].includes(node.tagName)) break;
      if (members.every(m => node.contains(m))) {
        let t = textOf(node);
        for (const o of optionLabels) t = t.replace(o, ' ');
        t = clean(t);
        if (t) return caption(t.slice(0, 400), 'nearby group text');
      }
    }
    return caption('', 'unidentified');
  };

  const all = [];
  const walk = root => root.querySelectorAll('*').forEach(el => { all.push(el); if (el.shadowRoot) walk(el.shadowRoot); });
  walk(document);

  const controllers = all.filter(el => el.hasAttribute('aria-controls'));
  const metadata = (el, title, group = null, members = [el]) => {
    const fieldset = el.closest('fieldset');
    const legend = fieldset?.querySelector(':scope > legend');
    const wrapper = el.closest('[data-field-path], .ashby-application-form-field-entry, .form-group');
    const descriptionNodes = [...new Set([...members, group, wrapper].filter(Boolean))]
      .flatMap(node => references(node, 'aria-describedby'))
      .filter(node => !['alert', 'status'].includes(node.getAttribute('role')) &&
        !/error|invalid/i.test(node.className || ''));
    const context = {
      instructions: [...new Set(descriptionNodes.map(textOf))].filter(t => t && t !== title.label).join(' ').slice(0, 600),
      group: textOf(legend).slice(0, 240),
    };
    if (context.group === title.label) context.group = '';
    if (/^(if|when)\b|please explain|please specify/i.test(title.label)) {
      const controlling = controllers.filter(control => references(control, 'aria-controls')
        .some(target => target === el || (target !== el.form && target.contains(el) && !target.contains(control))));
      const parent = controlling.length === 1 && controlling[0];
      if (parent) {
        const question = labelFor(parent).label;
        const value = parent.tagName === 'SELECT' ? textOf(parent.selectedOptions[0]) :
          parent.type === 'radio' || parent.type === 'checkbox' ? (parent.checked ? 'Yes' : 'No') : '';
        if (question && (parent.tagName === 'SELECT' || ['radio', 'checkbox'].includes(parent.type))) {
          context.parent = { question, answer: value };
        }
      }
    }
    return { ...title, context };
  };

  const groups = new Map();
  const groupKeys = new Map();
  for (const el of all) {
    const t = el.tagName.toLowerCase();
    // Bot traps (Workday's "beecatcher" boxes): filling one flags the application as automated.
    if (el.closest && el.closest('[data-automation-id="beecatcher"]')) continue;
    if (t === 'input' || t === 'select' || t === 'textarea') {
      const type = (el.getAttribute('type') || t).toLowerCase();
      // Never touch passwords; jobbot leaves sign-in to the user.
      if (['hidden', 'submit', 'button', 'image', 'reset', 'password'].includes(type)) continue;
      if (type === 'search' && !el.getAttribute('role')) continue;
      if (type === 'file') { const title = labelFor(el); out.push({ id: tag(el), kind: 'file', ...metadata(el, title), name: el.name || el.id || '', required: required(el, title.label), value: Array.from(el.files || []).map(f => f.name).join(', ') }); continue; }
      if (type === 'radio' || type === 'checkbox') {
        if (el.hidden || el.closest('.ashby-application-form-input-yesno')) continue; // Backing state is handled through the buttons.
        // Identical names can occur in different forms or question groups.
        const owner = el.closest('[role="radiogroup"], [role="group"], fieldset, [data-field-path], .ashby-application-form-field-entry') ||
          (el.name ? el.form || el.getRootNode() : parentOf(el)) || el;
        if (!groupKeys.has(owner)) groupKeys.set(owner, groupKeys.size);
        const key = JSON.stringify([groupKeys.get(owner), type, el.name || '']);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(el);
        continue;
      }
      if (!visible(el) || el.disabled || el.readOnly && !el.getAttribute('role')) continue;
      const title = labelFor(el);
      const label = title.label;
      const role = (el.getAttribute('role') || '').toLowerCase();
      const combo = role === 'combobox' || el.getAttribute('aria-autocomplete') || el.getAttribute('aria-haspopup') === 'listbox';
      out.push({
        id: tag(el), kind: t === 'select' ? 'select' : combo ? 'combo' : (t === 'textarea' ? 'textarea' : 'text'),
        type, ...metadata(el, title), required: required(el, label), value: el.value || '', maxlength: el.maxLength || -1,
        inputmode: el.getAttribute('inputmode') || '',
        unit: (el.closest('.form-group, .field, [data-field-path]')?.innerText || '').match(/\bLPA\b|\blakhs?\b|₹|\bINR\b/i)?.[0] || '',
        text: t === 'select' && el.selectedIndex >= 0 ? clean(el.options[el.selectedIndex].text) : '',
        shown: combo ? shownValue(el) : '',
        options: t === 'select' ? Array.from(el.options).map(o => clean(o.text)) : [],
      });
    } else if (t === 'button' && el.getAttribute('aria-haspopup') === 'listbox' && visible(el)) {
      // Workday-style dropdown buttons
      const title = labelFor(el);
      const label = title.label;
      // a site's header controls (Workday's language picker, "Settings") are not application questions
      if (!label && el.closest('header, nav, [role="banner"], [data-automation-id*="header" i], [data-automation-id*="utility" i]')) continue;
      out.push({ id: tag(el), kind: 'listbutton', ...metadata(el, title), required: required(el, label), value: textOf(el) });
    }
  }

  for (const members of groups.values()) {
    const shown = members.filter(m => visible(m) || (m.labels && m.labels[0] && visible(m.labels[0])));
    if (!shown.length) continue;
    const optionLabels = shown.map(m => (m.labels && m.labels[0] ? textOf(m.labels[0]) : '') || clean(m.getAttribute('aria-label') || m.value));
    const type = (shown[0].getAttribute('type') || '').toLowerCase();
    const title = shown.length === 1 && type === 'checkbox'
      ? caption(optionLabels[0], labelFor(shown[0]).label_source) : groupQuestion(shown, optionLabels);
    const question = title.label;
    const group = shown[0].closest('[role="radiogroup"], [role="group"], fieldset');
    out.push({
      id: shown.map(tag).join(','), kind: type === 'radio' ? 'radio' : (shown.length === 1 ? 'checkbox' : 'checkgroup'),
      ...metadata(shown[0], title, group, shown), options: optionLabels, required: shown.some(m => required(m, question)) || /\*/.test(question),
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
    let title = labelFor(kids[0]);
    let node = el;
    for (let i = 0; i < 4 && !title.label; i++) {
      node = parentOf(node);
      if (!node) break;
      title = caption(textOf(node).replace(/\bYes\b\s*\bNo\b\s*$/, ''), 'nearby group text');
    }
    out.push({ id: kids.map(tag).join(','), kind: 'yesno', ...metadata(kids[0], title, el, kids), options: ['Yes', 'No'],
               required: required(kids[0], title.label), value: kids.map(k => k.getAttribute('aria-pressed') === 'true' || /selected|active/i.test(k.className)) });
  }
  return out;
}
""".replace("COMBO_VALUE", COMBO_VALUE_JS)

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
