# Troubleshooting

| Problem | Fix |
| --- | --- |
| `profile is already in use` | A jobbot Chrome window is still open from an earlier run. Quit that run (`q`, or **Stop** in the dashboard) or close the window. |
| Workday stops at "Create Account/Sign In" | Expected for many employers. Sign in or create the account in the jobbot window, then press Enter (or click **Done, continue** in the dashboard). |
| `apply` stops with "This site needs you to sign in" | Expected on Amazon, Google, Apple and many Workday employers. Sign in (or create the account) in the jobbot window, then press Enter. Sign-ins are remembered per site. |
| Sign-in or account creation is refused in the jobbot window (Microsoft, Google) | Update jobbot: its Chrome no longer identifies itself as automated, which those sign-in pages reject. If a site still refuses, use its email-link or one-time-code option. |
| A job seems stuck | Check `./jobbot.sh logs` for the last page and round. If a field keeps failing, jobbot lists it for you instead of retrying; fix it in the browser and press `r`. |
| `Ollama is not running` | `brew services start ollama`, or pass `--llm none` |
| A question gets a wrong or missing answer | Add a rule under `answers:` in your profile (see [Your profile](profile.md)) |
| The scanner errors on one company | That board moved or was retired. The rest of the scan continues; see [Contributing](../CONTRIBUTING.md) to fix the registry entry. |
| `bad interpreter` after moving the folder | Recreate the virtualenv: `rm -rf .venv && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` |

---

[← Docs index](README.md) · [Project README](../README.md)
