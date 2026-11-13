"""Dropdowns, autocomplete boxes and Workday listbox buttons: open, search, and choose the option that
really is the answer (never just the first option that contains the typed text)."""
import re

def matching_option(options, typed, guess=""):
    """Index of the option that is our answer, or None. Accepts an option that starts with the typed text as
    a whole word ("India" -> "India +91", "Hyderabad" -> "Hyderabad, Telangana, India") or one containing every
    word of the full answer; never just any option that contains the text somewhere."""
    words = lambda t: set(re.findall(r"[a-z0-9]+", (t or "").lower()))
    want = words(guess or typed) - {"of", "the", "and", "in"}
    options = options or []
    exact = [i for i, o in enumerate(options) if o.strip().casefold() == (guess or typed or "").strip().casefold()]
    if exact:
        return exact[0] if len(exact) == 1 else None
    full = [i for i, o in enumerate(options) if want and want <= words(o)]
    if full:
        return full[0] if len(full) == 1 else None
    shorter = [i for i, o in enumerate(options)
               if (ow := words(o) - {"of", "the", "and", "in"}) and ow <= want and words(typed) <= ow]
    return shorter[0] if len(shorter) == 1 else None


def fill_dropdown(self, page, f, resolver, note):
    """React-select comboboxes, autocomplete boxes, Workday listbox buttons and Workday's
    searchable, nested "prompt" lists (category -> sub-option)."""
    label, context = f["label"], f.get("context")
    self._typed = self._guess = ""
    loc = page.locator(f'[data-jobbot-id="{f["id"]}"]')
    self._open_dropdown(loc)
    page.wait_for_timeout(700)
    options = self._visible_options(page)
    if not options:
        loc.press("ArrowDown")  # some menus open only on a key press
        page.wait_for_timeout(600)
        options = self._visible_options(page)
    typed, chosen_answer = False, None
    for _ in range(3):  # Workday nests up to a couple of levels
        if not options and f["kind"] == "combo" and not typed:
            options, typed = self._search_options(page, loc, resolver, label, context=context), True
        if not options:
            break
        ans = resolver.resolve(label, "choice", options=options, required=f["required"], quick=True, context=context)
        if ans is None and f["kind"] == "combo" and not typed:
            # The answer may just not be visible yet (long lists): search for it first.
            found = self._search_options(page, loc, resolver, label, context=context)
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
                if hit is None:
                    # Many school lists do not have your college: after every alias, leave it blank, or
                    # pick "Other" when the site requires an answer. Never another college, never asking you.
                    found = self._search_options(page, loc, resolver, label, term="Other") if f["required"] else []
                    hit = next((i for i, o in enumerate(found or []) if re.fullmatch(r"\s*other\s*", o, re.I)), None)
                    if hit is None:
                        break
                    options = found
            if hit is not None:
                from ..answers import Answer
                ans = Answer(hit, "rule", options[hit])
        if ans is None:
            ans = resolver.resolve(label, "choice", options=options, required=f["required"], context=context)
        if ans is None:
            break
        chosen = ans.display
        # Never use a resolver index: placeholder filtering changes those indices.
        if options.count(chosen) != 1 or not self._click_option(page, chosen):
            break
        page.wait_for_timeout(900)
        if f["kind"] == "combo" and typed and not _took(loc, chosen):
            # Some autocompletes (SmartRecruiters' City) ignore a mouse pick: retype, then choose by keyboard.
            try:
                loc.fill("")
                loc.press_sequentially(getattr(self, "_typed", "") or chosen.split(",")[0], delay=60)
                page.wait_for_timeout(1500)
                again = self._visible_options(page)
                if again.count(chosen) == 1:
                    for _ in range(again.index(chosen) + 1):
                        loc.press("ArrowDown")
                    loc.press("Enter")
                    page.wait_for_timeout(900)
                else:
                    page.keyboard.press("Escape")
            except Exception:
                pass
        after = self._visible_options(page)
        if not after or after == options or chosen in after:
            chosen_answer = ans
            break  # a leaf was selected (the list closed or stayed the same)
        options = after  # a category opened a sub-list; choose again inside it
    if self._visible_options(page):
        page.keyboard.press("Escape")
    if chosen_answer is None:
        if typed:
            loc.fill("")
            page.keyboard.press("Escape")
        return False
    note(f, label, chosen_answer, expected=chosen_answer.display)
    return True

def _took(loc, chosen):
    """Check the current value, not arbitrary nearby text."""
    from .fields import COMBO_VALUE_JS
    from .verify import choice_matches
    try:
        return choice_matches(chosen, loc.evaluate(COMBO_VALUE_JS))
    except Exception:
        return False


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

def search_options(self, page, loc, resolver, label, term=None, context=None):
    """Type the answer we would give (or `term`) into the box and return the matching options."""
    if term is None:
        guess = resolver.resolve(label, "text", required=False, context=context)
        if not guess:
            return []
        self._guess = str(guess.value)
        term = self._guess.split(",")[0].split("(")[0].strip()
    else:
        self._guess = term
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

def click_option(page, text):
    options = page.locator('[role="option"]:visible')
    labels = [" ".join(option.split()) for option in options.all_inner_texts()]
    if labels.count(text) != 1:
        return False
    # Re-check the text via the locator at click time, not its previous array position.
    matching = options.filter(has_text=re.compile(r"^\s*" + r"\s+".join(map(re.escape, text.split())) + r"\s*$"))
    if matching.count() != 1:
        return False
    matching.click(timeout=4000)
    return True


def visible_options(page):
    return [" ".join(t.split()) for t in page.locator('[role="option"]:visible').all_inner_texts()]
