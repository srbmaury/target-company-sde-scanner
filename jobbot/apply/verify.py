"""Read back what jobbot filled and look for anything a site would reject.

Run before every Next and Submit. A page passes only when every value jobbot set
still reads back as intended, no required field is empty, no validation error is
showing, and no CAPTCHA is waiting.
"""

import re
from dataclasses import dataclass, field

READBACK_JS = r"""
(records) => {
  const find = id => {
    let hit = null;
    const walk = root => {
      if (hit) return;
      const el = root.querySelector('[data-jobbot-id="' + id + '"]');
      if (el) { hit = el; return; }
      root.querySelectorAll('*').forEach(e => { if (!hit && e.shadowRoot) walk(e.shadowRoot); });
    };
    walk(document);
    return hit;
  };
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  return records.map(r => {
    const el = find(r.id);
    if (!el) return { id: r.id, found: false, value: '' };
    const tag = el.tagName.toLowerCase();
    let value = '';
    if (tag === 'select') value = el.selectedIndex >= 0 ? clean(el.options[el.selectedIndex].text) : '';
    else if (el.type === 'checkbox' || el.type === 'radio') value = el.checked ? 'checked' : '';
    else if (tag === 'button' && r.kind === 'yesno') value = (el.getAttribute('aria-pressed') === 'true' || /selected|active|checked/i.test(el.className)) ? 'checked' : '';
    else if (tag === 'button') value = clean(el.innerText);
    else if (r.kind === 'combo') {
      // react-select and friends show the chosen value next to the input, not in it
      let node = el, text = el.value || '';
      for (let i = 0; i < 4 && node && !clean(text); i++) { node = node.parentElement; text = node ? node.innerText : ''; }
      if (node && !(text || '').toLowerCase().includes((r.expected || '').toLowerCase().slice(0, 12))) {
        for (let i = 0; i < 3 && node; i++) { node = node.parentElement; if (node && node.innerText.toLowerCase().includes((r.expected || '').toLowerCase().slice(0, 12))) { text = node.innerText; break; } }
      }
      value = clean(text);
    } else value = clean(el.value);
    return { id: r.id, found: true, value };
  });
}
"""

PAGE_PROBLEMS_JS = r"""
() => {
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const visible = el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
  const errors = new Set();
  const all = [];
  const walk = root => root.querySelectorAll('*').forEach(e => { all.push(e); if (e.shadowRoot) walk(e.shadowRoot); });
  walk(document);
  for (const el of all) {
    if (!visible(el)) continue;
    const role = el.getAttribute('role');
    const cls = (el.className && el.className.baseVal === undefined) ? String(el.className) : '';
    const text = clean(el.innerText || '');
    if (!text || text.length > 200) continue;
    if (role === 'alert' || /(^|[\s_-])(error|invalid|field-error|errorMessage)([\s_-]|$)/i.test(cls) ||
        el.getAttribute('data-automation-id') === 'errorMessage') {
      if (/required|invalid|please|must|error|cannot be blank|enter a valid/i.test(text)) errors.add(text);
    }
  }
  const invalid = all.filter(e => e.getAttribute && e.getAttribute('aria-invalid') === 'true' && visible(e)).length;
  const captcha = Array.from(document.querySelectorAll('iframe')).some(f =>
      /recaptcha\/api2\/bframe|hcaptcha\.com.*challenge|challenges\.cloudflare/.test(f.src || '') && visible(f))
      || /verify (that )?you are (a )?human|i.?m not a robot/i.test(document.body.innerText.slice(0, 5000));
  return { errors: Array.from(errors).slice(0, 10), invalid, captcha };
}
"""


@dataclass
class Check:
    mismatches: list = field(default_factory=list)   # (label, expected, actual)
    missing: list = field(default_factory=list)      # required fields still empty / unanswered
    errors: list = field(default_factory=list)       # validation messages on the page
    captcha: bool = False

    @property
    def ok(self):
        return not (self.mismatches or self.missing or self.errors or self.captcha)

    def lines(self):
        out = [f"value changed: {l[:60]} (wanted “{e[:40]}”, page shows “{a[:40]}”)" for l, e, a in self.mismatches]
        out += [f"still empty: {m[:90]}" for m in self.missing]
        out += [f"page says: {e[:120]}" for e in self.errors]
        if self.captcha:
            out.append("a CAPTCHA is waiting")
        return out


def _norm(s):
    return re.sub(r"[^a-z0-9+@.]", "", (s or "").lower())


def matches(expected, actual, kind):
    if kind in ("radio", "checkgroup", "yesno", "checkbox", "consent"):
        return actual == "checked"
    e, a = _norm(expected), _norm(actual)
    if not e:
        return True
    if kind in ("text", "textarea"):
        # sites reformat phones and trim whitespace; compare digits for numbers
        if re.fullmatch(r"[+\d\s()-]{6,}", expected or ""):
            return re.sub(r"\D", "", expected)[-10:] == re.sub(r"\D", "", actual)[-10:]
        return e == a or (len(e) > 40 and a.startswith(e[:40]))
    return e in a or a in e


def check_page(page, records, unresolved, fields_now):
    """records: dicts with id, kind, label, expected (what jobbot set)."""
    result = Check()
    if records:
        actual = {r["id"]: r for r in page.evaluate(READBACK_JS, records)}
        for r in records:
            got = actual.get(r["id"], {})
            if not got.get("found"):
                continue  # the page re-rendered the field; the required-field scan below still applies
            if not matches(r["expected"], got.get("value", ""), r["kind"]):
                result.mismatches.append((r["label"], r["expected"], got.get("value", "")))
    result.missing.extend(unresolved)
    for f in fields_now:
        if not f.get("required"):
            continue
        kind, value = f["kind"], f.get("value")
        empty = (kind in ("text", "textarea") and not value) or \
                (kind == "select" and (not value or value in ("0", "-1"))) or \
                (kind in ("radio", "checkgroup", "yesno") and not any(value or [])) or \
                (kind == "checkbox" and not (value and value[0])) or \
                (kind == "listbutton" and (not value or value.lower().startswith("select")))
        if empty and f["label"] and f["label"] not in result.missing:
            result.missing.append(f["label"])
    problems = page.evaluate(PAGE_PROBLEMS_JS)
    result.errors = problems["errors"]
    result.captcha = problems["captcha"]
    return result
