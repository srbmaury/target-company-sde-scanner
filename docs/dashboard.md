# Dashboard

```bash
./jobbot.sh ui
```

Opens a local dashboard in your browser (`http://127.0.0.1:8765`). It uses the same tracker,
profile and logs as the commands.

| Tab | What you can do |
| --- | --- |
| **Jobs** | Ranked roles with fit scores and reasons, filters (text, minimum fit, already applied, dismissed), links to postings, dismiss/restore. Tick roles (or **Select all shown**, which follows your filters and leaves out applied and dismissed roles) and click **Apply to selected** (or **Dry run**) |
| **Apply** | The running application batch: a live activity feed (what was filled, corrected and checked on each page), the queue, and any question jobbot needs you to answer |
| **Applications** | Every application with status pills and history; click one to change its status or notes; add applications made elsewhere |
| **Actions** | Run Scan, Rank, and Gmail sync in the background and watch their output; connect Gmail |
| **Logs** | What `apply` filled, corrected and checked, page by page, with a filter |
| **Profile** | Edit `profile.yaml`, including learned answers. Invalid YAML is refused, and a backup is kept |

**Refresh jobs** (top of the Jobs tab) runs `scan` and then `rank`, shows progress beside the
button, and reloads the list when it finishes.

### Applying from the dashboard

Tick roles in **Jobs**, then click **Apply to selected**. jobbot opens its own Chrome window, as
`apply` does, and the **Apply** tab shows its progress. When it needs you (an unanswered question,
a verification code, a sign-in or CAPTCHA, or the final **Submit application**), the question
appears at the top of the Apply tab, a red dot appears on the tab, and the browser tab title shows
"● jobbot needs you". Nothing is submitted until you click Submit. **Dry run** fills and checks
every page but never submits. **Stop after this step** ends the batch without submitting the
current application. Only one run happens at a time. Skipping rules match `apply`: already-applied
and dismissed roles are skipped, and for possible matches you are asked first.

The dashboard listens only on `127.0.0.1`, and each run generates a random access token that is
embedded in the page, so other websites in your browser can't call it. Stop it with Ctrl+C.

---

[← Docs index](README.md) · [Project README](../README.md)
