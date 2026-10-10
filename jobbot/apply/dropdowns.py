"""Dropdowns, autocomplete boxes and Workday listbox buttons: open, search, and choose the option that
really is the answer (never just the first option that contains the typed text)."""
import re

def matching_option(options, typed, guess=""):
    """Index of the option that is our answer, or None. Accepts an option that starts with the typed text as
    a whole word ("India" -> "India +91", "Hyderabad" -> "Hyderabad, Telangana, India") or one containing every
    word of the full answer; never just any option that contains the text somewhere."""
    words = lambda t: set(re.findall(r"[a-z0-9]+", (t or "").lower()))
    want = words(guess or typed) - {"of", "the", "and", "in"}
    for i, o in enumerate(options or []):   # every word of the full answer: "(BHU), Varanasi", "Telangana"
        if want and want <= words(o):
            return i
    t = (typed or "").strip().lower()
    if t and words(t) >= want:   # we typed the whole answer: "India" -> "India +91", not "British Indian Ocean..."
        for i, o in enumerate(options or []):
            if re.match(re.escape(t) + r"(?![a-z0-9])", o.strip().lower()):
                return i
    return None


def fill_dropdown(self, page, f, resolver, note):
    """React-select comboboxes, autocomplete boxes, Workday listbox buttons and Workday's
    searchable, nested "prompt" lists (category -> sub-option)."""
    label = f["label"]
    loc = page.locator(f'[data-jobbot-id="{f["id"]}"]')
    self._open_dropdown(loc)
    page.wait_for_timeout(700)
    options = self._visible_options(page)
    if not options:
        loc.press("ArrowDown")  # some menus open only on a key press
        page.wait_for_timeout(600)
        options = self._visible_options(page)
    typed, path, ans = False, [], None
    for _ in range(3):  # Workday nests up to a couple of levels
        if not options and f["kind"] == "combo" and not typed:
            options, typed = self._search_options(page, loc, resolver, label), True
        if not options:
            break
        ans = resolver.resolve(label, "choice", options=options, required=f["required"], quick=True)
        if ans is None and f["kind"] == "combo" and not typed:
            # The answer may just not be visible yet (long lists): search for it first.
            found = self._search_options(page, loc, resolver, label)
            typed = True
            options = found or self._reopen(page, loc) or options
        if ans is None and typed and getattr(self, "_typed", ""):
            # an autocomplete answered our own search ("Hyderabad" -> "Hyderabad, Telangana, India"), but only
            # an option that really is the answer: "India" must not pick "British Indian Ocean Territory".
            hit = matching_option(options, self._typed, getattr(self, "_guess", ""))
            if hit is None and re.search(r"school|university|college|institut", label, re.I):
                aliases = self.profile.get("education.school") or []
                aliases = [aliases] if isinstance(aliases, str) else aliases
                generic = {"indian", "institute", "technology", "of", "the", "university", "college", "school", "and", "iit", "it", "univ"}
                for alias in aliases:
                    if not set(re.findall(r"[a-z]+", alias.lower())) - generic:
                        continue
                    found = self._search_options(page, loc, resolver, label, term=alias)
                    hit = matching_option(found, alias, alias)
                    if hit is not None:
                        options = found
                        break
            if hit is not None:
                from ..answers import Answer
                ans = Answer(hit, "rule", options[hit])
        if ans is None:
            ans = resolver.resolve(label, "choice", options=options, required=f["required"])
        if ans is None:
            break
        chosen = options[ans.value]
        self._click_option(page, chosen, ans.value)
        path.append(chosen)
        page.wait_for_timeout(900)
        after = self._visible_options(page)
        if not after or after == options or chosen in after:
            break  # a leaf was selected (the list closed or stayed the same)
        options = after  # a category opened a sub-list; choose again inside it
    if self._visible_options(page):
        page.keyboard.press("Escape")
    if not path:
        return False
    note(f, label, ans if len(path) == 1 and ans is not None else " › ".join(path), expected=path[-1])
    return True

def open_dropdown(loc):
    """Open a dropdown whose input may be covered by the widget's own overlay (react-select and
    similar): a normal click, then a forced one, then focus and the keyboard."""
    for attempt in (lambda: loc.click(timeout=3000), lambda: loc.click(force=True, timeout=3000),
                    lambda: (loc.focus(), loc.press("ArrowDown"))):
        try:
            attempt()
            return
        except Exception:
            continue
    raise RuntimeError("could not open this dropdown")

def search_options(self, page, loc, resolver, label, term=None):
    """Type the answer we would give (or `term`) into the box and return the matching options."""
    if term is None:
        guess = resolver.resolve(label, "text", required=False)
        if not guess:
            return []
        self._guess = str(guess.value)
        term = self._guess.split(",")[0].split("(")[0].strip()
    self._typed = term
    loc.fill(self._typed)
    if self._ats == "workday":
        loc.press("Enter")  # Workday searches on Enter; react-select would pick the first hit
    page.wait_for_timeout(1800)
    return self._visible_options(page)

def reopen(self, page, loc):
    """Clear a search that found nothing and bring back the full list."""
    try:
        loc.fill("")
        if self._ats == "workday":
            loc.press("Enter")
        loc.click()
        page.wait_for_timeout(900)
    except Exception:
        return []
    return self._visible_options(page)

def click_option(page, text, index):
    try:
        page.get_by_role("option", name=text, exact=True).first.click(timeout=4000)
    except Exception:
        page.locator('[role="option"]:visible').nth(index).click(timeout=4000)

def visible_options(page):
    return [t.strip() for t in page.locator('[role="option"]:visible').all_inner_texts()]
