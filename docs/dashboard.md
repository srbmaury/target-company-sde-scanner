# Dashboard

```bash
./jobbot.sh ui
```

Opens a local dashboard in your browser (`http://127.0.0.1:8765`). It uses the same tracker,
profile and logs as the commands.

| Tab | What you can do |
| --- | --- |
| **Jobs** | Ranked roles with fit scores and reasons, a text filter and minimum fit, and views: **New** (roles you can apply to), **Possibly applied**, **Applied**, **Dismissed**, **Excluded** (companies in `preferences.exclude_companies`, which `apply` skips), **All**, each with its count. Tick roles (or **Select top** *N*, the best *N* in the current view and order, or **Select all shown**) and click **Apply to selected** (or **Dry run**). Applied and dismissed roles can't be ticked |
| **Runs** | The running batch (live activity, queue, questions for you, the final Submit) and earlier runs. After a run: what needs you, with the reason, **Open posting** and **Retry** / **Retry all**. History survives restarts |
| **Applications** | Every application with status pills and history; click one to change its status, notes, company, role or posting link; add applications made elsewhere |
| **Actions** | Run Scan, Rank, and Gmail sync in the background and watch their output; connect Gmail |
| **Logs** | What `apply` filled, corrected and checked, page by page, with a filter |
| **Profile** | Edit `profile.yaml`, including learned answers. Invalid YAML is refused, and a backup is kept |

**Refresh jobs** (top of the Jobs tab) syncs Gmail first (if connected, so roles you applied to elsewhere drop out), then runs `scan` and `rank`, shows progress beside the
button, and reloads the list when it finishes.
### Possibly applied

A role is *possibly applied* when it looks like an application you already have: the same title at the
same company posted later (big employers reuse titles), or an application whose email didn't name the
role. Each such role says which application it resembles, with two buttons:

- **Not a duplicate**: it's a different opening. It moves to **New**, and jobbot remembers.
- **Same role, hide it**: dismisses it.

In the **Possibly applied** view you can also tick several and **Mark selected as not duplicates**.
The quickest fix for an application listed as "(role not stated in email)" is to open it in
**Applications** and type its role: one edit can clear dozens of possible matches at that company.

### Applying from the dashboard

Tick roles in **Jobs**, then click **Apply to selected**. **Submit verified applications**
is selected by default: the batch starts directly, runs without questions, and submits each
application only after deterministic checks pass and Ollama explicitly approves every field
on every step. Unknown answers, sign-in/CAPTCHA gates and rejected reviews skip that role
with a reason and continue the batch. No confirmation after a Submit click is listed for
checking; jobbot does not repeat that click blindly.

Set `automation.parallel_workers` in your profile for the number of concurrent application
browsers (default 1, capped by the number of selected jobs). Each browser uses its own profile.
There is no daily cap by default; an optional positive cap limits the batch before workers start. Ollama must be
available. **Dry run** never submits. Uncheck automatic submission to use the interactive
review and Submit controls. Only one batch runs at a time.

The dashboard listens only on `127.0.0.1`, and each run generates a random access token that is
embedded in the page, so other websites in your browser can't call it. Stop it with Ctrl+C.

While a run is going, a strip at the top of the **Jobs** tab shows its progress ("Applying 3/10 · a question is waiting for you") with a **View run** link.
The **Docs** tab shows these pages.

---

[← Docs index](README.md) · [Project README](../README.md)
