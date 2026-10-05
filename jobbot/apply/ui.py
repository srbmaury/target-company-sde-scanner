"""Terminal prompts used while filling an application."""


def _input(prompt):
    try:
        return input(prompt)
    except EOFError:  # piped input ran out: behave like "skip" / "quit"
        return "q" if prompt.rstrip().endswith(":") and "[q]uit" in prompt else ""


class TerminalUI:
    def info(self, msg):
        print(f"  {msg}")

    def warn(self, msg):
        print(f"  ! {msg}")

    def wait_for_user(self, msg):
        _input(f"\n  {msg} ")

    def confirm(self, msg):
        return _input(f"\n  {msg} [y/N] ").strip().lower() in ("y", "yes")

    def ask(self, question, options, required, suggestion, reason):
        """Return an option index, free text, or None to leave the field blank."""
        print(f"\n  ? {question[:300]}")
        print(f"    ({reason}{', required' if required else ', optional'})")
        if options:
            for i, o in enumerate(options):
                print(f"      {i + 1}. {o}")
            raw = _input("    number (Enter to skip): ").strip()
            if raw.isdigit() and 1 <= int(raw) <= len(options):
                return int(raw) - 1
            return raw or None
        if suggestion:
            print("    suggested answer:\n      " + suggestion.replace("\n", "\n      "))
            raw = _input("    Enter to accept, type a replacement, or '-' to leave blank: ")
            if raw.strip() == "-":
                return None
            return raw.strip() or suggestion
        raw = _input("    answer (Enter to skip): ").strip()
        return raw or None

    def report(self, report, check=None, step=None):
        print(f"\n  Page {step} filled:" if step else "\n  Filled:")
        for label, ans in report["filled"]:
            src = getattr(ans, "source", "")
            print(f"    - {label[:70]:70s} → {str(ans)[:60]}  [{src}]")
        if check is None:
            if report["skipped"]:
                print("  Still needs you (required):")
                for label in report["skipped"]:
                    print(f"    - {label[:110]}")
            return
        if check.ok:
            print(f"  ✓ Check passed: {len(report.get('records', []))} values read back correctly, "
                  "no empty required fields, no errors on the page.")
        else:
            print("  ✗ Check found problems:")
            for line in check.lines():
                print(f"    - {line}")

    def next_action(self, can_submit, can_next, dry_run, check_ok=True):
        if can_submit and check_ok:
            print("\n  This is the final step and every check passed. Review the browser window, then submit.")
        else:
            print("\n  Review the browser window, fix anything, solve any CAPTCHA.")
        menu = []
        if can_submit:
            menu.append("[s]ubmit")
        if can_next:
            menu.append("[n]ext step")
        menu += ["[r]efill this page", "[d]one, I submitted it myself", "[q]uit without submitting"]
        if dry_run:
            print("  Dry run: jobbot will not click submit.")
        keys = {"s": "submit", "n": "next", "r": "refill", "d": "done", "q": "quit"}
        while True:
            raw = _input("  " + "  ".join(menu) + ": ").strip().lower()[:1]
            choice = keys.get(raw)
            if choice == "submit" and not can_submit:
                continue
            if choice == "next" and not can_next:
                continue
            if choice:
                return choice
