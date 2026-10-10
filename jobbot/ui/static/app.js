"use strict";
// jobbot dashboard. Talks to the local server (jobbot/ui/server.py) with the per-run token.

const TOKEN = document.querySelector('meta[name="jobbot-token"]').content;
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const state = { selected: new Set(), run: null, runPoll: null, tab: "jobs", jobs: [], apps: [], summary: null, jobSort: ["fit_score", -1], appSort: ["applied_on", -1], polling: null };

async function api(path, body) {
  const opts = { headers: { "X-Jobbot-Token": TOKEN } };
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try { res = await fetch("/api/" + path, opts); } catch (e) {
    connection("Can't reach jobbot. Is <code>./jobbot.sh ui</code> still running?");
    throw e;
  }
  const data = await res.json().catch(() => ({}));
  if (res.status === 403 && /token/.test(data.error || "")) {
    // A page left open across a restart holds the old access token: every call fails until it reloads.
    connection("jobbot was restarted, so this page is out of date.", true);
  } else connection(null);
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function connection(msg, reload) {
  const el = document.getElementById("conn-banner");
  if (!el) return;
  el.hidden = !msg;
  if (!msg) return;
  el.innerHTML = msg + (reload ? ' <button class="primary">Reload</button>' : "");
  if (reload) el.querySelector("button").addEventListener("click", () => location.reload());   // CSP: no inline handlers
}

function debounce(fn, ms = 250) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

function remember(key, value) { try { localStorage.setItem("jobbot." + key, value); } catch (e) { /* private mode */ } }
function recall(key) { try { return localStorage.getItem("jobbot." + key); } catch (e) { return null; } }

// ---------- tabs ----------
function showTab(name) {
  state.tab = name;
  remember("tab", name);
  $$(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  $$(".panel").forEach((p) => (p.hidden = p.id !== "tab-" + name));
  ({ jobs: () => { loadJobs(); loadTasks(); }, apply: () => { state.viewing = false; loadRun(); }, applications: loadApps, actions: loadTasks, logs: loadLogs, profile: loadProfile, docs: () => loadDocs() }[name])();
}

// ---------- summary ----------
async function loadSummary() {
  const s = (state.summary = await api("summary"));
  const a = s.applications;
  const cards = [
    ["Open roles", s.open_jobs], ["Applications", s.total], ["Waiting response", a.applied || 0],
    ["Assessments", a.assessment || 0], ["Interviews", a.interview || 0], ["Offers", a.offer || 0],
    ["Rejected", a.rejected || 0], ["Response rate", s.response_rate + "%"],
  ];
  const tips = {
    "Open roles": "Roles in the New view: listed today, not applied to, not dismissed or excluded",
    "Applications": "Every application in your tracker, whatever its status",
    "Waiting response": "Applications still at status \"applied\": sent, with no reply yet",
    "Response rate": "Applications that got any reply (assessment, interview, offer or rejection)",
  };
  $("#stats").innerHTML = cards.map(([l, v]) => `<div class="stat" title="${esc(tips[l] || "")}"><div class="label">${esc(l)}</div><div class="value">${esc(v)}</div></div>`).join("");
  const dot = (ok) => `<span class="dot" style="background:${ok ? "var(--good)" : "var(--border)"}"></span>`;
  $("#status").innerHTML = `<span>${dot(s.gmail)}Gmail ${s.gmail ? "connected" : "not connected"}</span>
    <span>${dot(s.ollama)}Ollama ${s.ollama ? "running" : "off"}</span>`;
  $("#gmail-text").textContent = s.gmail
    ? "Import application emails, and read verification codes and links for sign-ups."
    : "Connect Gmail (read-only) to import your applications. Needs the one-time OAuth client from the README.";
  $("#gmail-sync").disabled = !s.gmail;
  const sel = $("#apps-status");
  if (sel.options.length === 1) s.statuses.forEach((st) => sel.add(new Option(st, st)));
}

// ---------- jobs ----------
function sortRows(rows, [key, dir]) {
  return rows.slice().sort((a, b) => {
    const x = a[key] ?? "", y = b[key] ?? "";
    return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y))) * dir;
  });
}

function markSorted(table, [key, dir]) {
  $$("th", table).forEach((th) => {
    th.classList.toggle("sorted", th.dataset.sort === key);
    th.classList.toggle("asc", th.dataset.sort === key && dir === 1);
  });
}

async function loadJobs() {
  const params = new URLSearchParams({
    q: $("#jobs-q").value, min_fit: $("#jobs-min").value,
    include_applied: "1", include_dismissed: "1",   // every role; the view buttons choose which to show
  });
  state.allJobs = await api("jobs?" + params);
  state.jobCatalog = state.jobCatalog || new Map();
  state.allJobs.forEach((j) => state.jobCatalog.set(String(j.n), j));
  renderJobs();
}

function fitClass(f) { return f == null ? "" : f >= 80 ? "high" : f >= 60 ? "mid" : "low"; }

// Which roles a view shows. "New" = ones you can apply to: not applied, not possibly applied, not dismissed.
const VIEWS = [
  ["new", "New", (j) => !j.dismissed && !j.applied && !j.excluded && !j.gone],
  ["possible", "Possibly applied", (j) => !j.dismissed && !j.excluded && !j.gone && j.applied === "possible"],
  ["applied", "Applied", (j) => !j.dismissed && (j.applied === "exact" || j.applied === "likely")],
  ["dismissed", "Dismissed", (j) => !!j.dismissed],
  ["excluded", "Excluded", (j) => !j.dismissed && j.applied !== "exact" && j.applied !== "likely" && !j.gone && !!j.excluded],
  ["gone", "No longer listed", (j) => !j.dismissed && !j.applied && !!j.gone],
  ["all", "All", () => true],
];

async function markNotDuplicates() {
  const keys = Array.from(state.selected);
  if (!keys.length) return;
  for (const k of keys) await api(`jobs/${k}/not-duplicate`, {});
  state.selected.clear();
  await Promise.all([loadJobs(), loadSummary()]);
}

function renderViews() {
  const all = state.allJobs || [];
  $("#jobs-views").innerHTML = VIEWS.map(([key, label, test]) =>
    `<button role="tab" data-view="${key}" aria-selected="${state.view === key}">${label} <span class="n">${all.filter(test).length}</span></button>`).join("");
}

function renderJobs() {
  state.view = state.view || "new";
  renderViews();
  const test = VIEWS.find(([k]) => k === state.view)[2];
  state.jobs = (state.allJobs || []).filter(test);
  const rows = sortRows(state.jobs, state.jobSort);
  markSorted($("#jobs-table"), state.jobSort);
  $("#jobs-count").textContent = `${rows.length} role${rows.length === 1 ? "" : "s"}`;
  $("#jobs-table tbody").innerHTML = rows.length ? rows.map((j) => {
    const applied = j.applied === "exact" || j.applied === "likely"
      ? `<span class="pill applied" title="${esc(j.applied_note)}">applied</span>`
      : j.applied === "possible" ? `<span class="pill maybe" title="${esc(j.applied_note)}">possibly applied</span>` : "";
    const dup = j.applied === "possible" && !j.dismissed ? `<div class="dup">Looks like your application ${esc(j.applied_note)}.
        <button class="link" data-job="${j.n}" data-act="not-duplicate">Not a duplicate</button>
        <button class="link" data-job="${j.n}" data-act="dismiss">Same role, hide it</button></div>` : "";
    const lock = j.dismissed ? "" : (j.applied === "exact" || j.applied === "likely") ? "disabled title=\"Already applied\""
      : j.excluded ? "disabled title=\"Excluded in your profile (preferences.exclude_companies)\"" : "";
    const excl = (j.excluded ? `<span class="pill" title="preferences.exclude_companies in your profile">excluded</span>` : "")
      + (j.gone ? `<span class="pill withdrawn" title="The last scan read this company's board and the role was not on it">no longer listed</span>` : "");
    return `<tr class="${j.dismissed ? "dim" : ""}">
      <td class="num">${j.n}</td>
      <td><span class="fit ${fitClass(j.fit_score)}">${j.fit_score ?? "–"}</span></td>
      <td>${esc(j.company)}</td>
      <td class="role"><a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a> ${applied}${excl}
        ${j.fit_reason ? `<div class="reason">${esc(j.fit_reason)}</div>` : ""}${dup}</td>
      <td>${esc(j.location)}</td>
      <td class="num" title="${esc(j.evidence)}">${esc(j.experience)}</td>
      <td>${esc(j.fit_resume || "")}</td>
      <td class="num"><label class="check"><input type="checkbox" data-select="${j.n}" ${state.selected.has(String(j.n)) ? "checked" : ""} ${j.dismissed ? "disabled" : lock}> Select</label>
        <button class="link" data-job="${j.n}" data-act="${j.dismissed ? "restore" : "dismiss"}">${j.dismissed ? "Restore" : "Dismiss"}</button></td>
    </tr>`;
  }).join("") : `<tr><td colspan="8" class="empty">${state.view === "new" ? "No new roles match. Try <b>Refresh jobs</b>, or check the other views." : "Nothing in this view."}</td></tr>`;
  updateSelection();
}

// Roles "select all" picks: the ones shown, minus dismissed and already-applied roles (apply skips those anyway).
function selectable() {
  return state.jobs.filter((j) => !j.dismissed && !j.excluded && j.applied !== "exact" && j.applied !== "likely").map((j) => String(j.n));
}

// ---------- selection & apply runs ----------
function updateSelection() {
  if (state.pendingRun && !state.runStarting) cancelRun();
  const n = state.selected.size;
  $("#notdup-selected").hidden = state.view !== "possible";
  $("#notdup-selected").disabled = !n;
  $("#sel-count").textContent = n ? `${n} selected` : "None selected";
  $("#apply-selected").disabled = $("#dry-selected").disabled = !n;
  $("#sel-clear").classList.toggle("invisible", !n);   // keeps its space: buttons never shift under the cursor
  const keys = selectable(), picked = keys.filter((k) => state.selected.has(k)).length;
  const all = keys.length > 0 && picked === keys.length;
  const box = $("#sel-all-box");
  box.checked = all;
  box.indeterminate = picked > 0 && !all;
  box.disabled = !keys.length;
  $("#sel-all").disabled = !keys.length || all;
  $("#sel-all").textContent = keys.length ? `Select all shown (${keys.length})` : "Select all shown";
}

// The best N roles you can apply to, in the order the table shows them.
function selectTop(n) {
  const ok = new Set(selectable());
  state.selected.clear();
  sortRows(state.jobs, state.jobSort).map((j) => String(j.n)).filter((k) => ok.has(k)).slice(0, n)
    .forEach((k) => state.selected.add(k));
  remember("topN", n);
  renderJobs();
}

function selectAll(on) {
  for (const k of selectable()) on ? state.selected.add(k) : state.selected.delete(k);
  renderJobs();
}

function startRun(dry) {
  const jobs = Array.from(state.selected);
  if (!jobs.length) return;
  dry = dry || ($("#validate-steps").checked && !$("#auto-submit").checked);
  state.pendingRun = { jobs, dry_run: dry || $("#validate-steps").checked, unattended: $("#unattended").checked, validation: $("#validate-steps").checked, auto_next: $("#unattended").checked || !$("#validate-steps").checked };
  if (!dry && $("#auto-submit").checked) {
    state.pendingRun = {jobs, dry_run: false, unattended: true, validation: true, auto_next: true, auto_submit: true};
  }
  const box = $("#run-confirmation");
  const roles = jobs.map((key) => state.jobCatalog.get(key)).filter(Boolean);
  box.hidden = false;
  box.innerHTML = `<h4>${dry ? "Confirm dry run" : "Confirm application run"}</h4>
    <p>${dry ? "Dry-run" : "Apply to"} ${jobs.length} role${jobs.length === 1 ? "" : "s"}? Chrome will open in its own window.
    ${dry ? "Forms may be filled and resumes uploaded; nothing will be submitted." : state.pendingRun.auto_submit ? "Completed applications will be submitted automatically after every check passes." : state.pendingRun.unattended ? "jobbot works through every role without stopping. Finished applications wait for your Submit, and roles that need you are listed at the end." : "You’ll confirm each Submit here."}</p>
    <details><summary>Review selected roles</summary><ul>${roles.map((j) => `<li>${esc(j.company)} — ${esc(j.title)}</li>`).join("")}</ul></details>
    <p id="run-confirm-error" role="alert"></p>
    <div class="actions"><button class="primary" id="run-confirm-start">${dry ? "Start dry run" : "Start applications"}</button>
    <button id="run-confirm-cancel">Cancel</button></div>`;
  $("#run-confirm-start").addEventListener("click", confirmRun);
  $("#run-confirm-cancel").addEventListener("click", cancelRun);
  $("#run-confirm-start").focus();
  if (state.pendingRun.auto_submit) {
    box.hidden = true;
    confirmRun();
  }
}

function cancelRun() {
  state.pendingRun = null;
  $("#run-confirmation").hidden = true;
}

async function confirmRun() {
  if (!state.pendingRun || state.runStarting) return;
  state.runStarting = true;
  $("#run-confirm-start").disabled = true;
  try {
    await api("apply", state.pendingRun);
    cancelRun();
    state.selected.clear(); updateSelection();
    showTab("apply");
  } catch (e) {
    $("#run-confirmation").hidden = false;
    $("#run-confirm-error").textContent = e.message;
    $("#run-confirm-start").disabled = false;
  } finally { state.runStarting = false; }
}

async function loadRun() {
  let run;
  try { run = await api("apply"); } catch (e) { return; }
  state.run = run;
  const active = ["starting", "running", "waiting"].includes(run.status);
  $("#apply-badge").hidden = run.status !== "waiting";
  document.title = run.status === "waiting" ? "● jobbot needs you" : "jobbot";
  if (active && !state.runPoll) state.runPoll = setInterval(loadRun, 1000);
  if (!active && state.runPoll) { clearInterval(state.runPoll); state.runPoll = null; loadSummary(); state.historyStale = true; }
  renderStrip(run, active);
  if (state.tab === "apply" && !state.viewing) renderRun(run);
  if (state.tab === "apply" && (state.historyStale || !state.historyLoaded)) loadHistory();
}

// The Jobs tab's one-line view of a run in progress.
function renderStrip(run, active) {
  const strip = $("#run-strip");
  if (!active) { strip.hidden = true; return; }
  const done = Object.keys(run.results || {}).length, total = (run.jobs || []).length;
  const waiting = run.status === "waiting";
  strip.hidden = false;
  strip.className = "run-strip" + (waiting ? " waiting" : "");
  strip.innerHTML = (total ? `${run.dry_run ? "Dry run" : "Applying"} ${Math.min(done + 1, total)}/${total}` : "Starting a run…") +
    (waiting ? " · <b>a question is waiting for you</b>" : " · working in Chrome") +
    ` <button class="link" data-view-run>View run →</button>`;
}

async function loadHistory() {
  state.historyLoaded = true; state.historyStale = false;
  let runs = [];
  try { runs = await api("runs"); } catch (e) { return; }
  const label = (r) => Object.entries(r.counts || {}).map(([k, v]) => `${v} ${k}`).join(", ") || "nothing finished";
  $("#history").innerHTML = runs.length ? runs.map((r) => `<li><a href="#" data-run="${esc(r.id)}">${esc((r.started || "").replace("T", " ").slice(0, 16))}</a>
      <span class="sub">${r.dry_run ? "dry run · " : ""}${r.unattended ? "unattended · " : ""}${esc(r.status || "")} · ${esc(label(r))}</span></li>`).join("")
    : `<li class="muted">None yet.</li>`;
}

function renderRun(run) {
  if (run.status === "idle") {
    $("#run-title").textContent = "No runs yet";
    $("#run-status").textContent = ""; $("#run-progress").textContent = "";
    $("#prompt").innerHTML = `<div class="empty"><p><b>To start a run:</b> tick roles in the Jobs tab, then <b>Apply to selected</b>
      (or <b>Dry run</b> to fill and check without submitting).</p><p>Tick <b>Don't stop for me</b> to run the whole batch unattended:
      jobs that need you are listed here, and finished applications wait for your Submit.</p></div>`;
    $("#feed").innerHTML = ""; $("#queue").innerHTML = ""; $("#needs").innerHTML = ""; $("#run-stop").hidden = true;
    return;
  }
  const active = ["starting", "running", "waiting"].includes(run.status);
  const when = (run.started || "").replace("T", " ").slice(0, 16);
  $("#run-title").textContent = (run.history ? (state.viewing ? "Run of " + when : "Last run · " + when) + " · " : "")
    + (run.dry_run ? "Dry run" : run.unattended ? "Unattended run" : "Applying");
  $("#run-status").textContent = run.status;
  $("#run-status").className = "pill " + ({ waiting: "maybe", running: "interview", done: "applied", failed: "rejected", stopped: "withdrawn" }[run.status] || "");
  const done = Object.keys(run.results).length;
  $("#run-progress").textContent = run.jobs.length ? `${done} of ${run.jobs.length} finished` : "";
  $("#run-stop").hidden = !active;
  $("#queue").innerHTML = run.jobs.map((j, i) => {
    const r = run.results[j.url];
    const gone = r && /^posting unavailable/.test(r.note || "");
    const label = gone ? "posting gone" : r && r.status;
    const pill = r ? `<span class="pill ${r.status === "applied" ? "applied" : r.status === "ready" ? "interview" : r.status === "needs you" ? "maybe" : gone ? "withdrawn" : "rejected"}" title="${esc(r.note || "")}">${esc(label)}</span>` : i === run.current ? `<span class="pill interview">now</span>` : "";
    return `<li class="${i === run.current ? "now" : ""}">${esc(j.company)} ${pill}<span class="sub">${esc(j.title)}</span></li>`;
  }).join("");
  const feed = $("#feed");
  const nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 60;
  feed.innerHTML = run.events.map(renderEvent).join("");
  if (nearBottom) feed.scrollTop = feed.scrollHeight;
  $("#page-preview").hidden = !run.preview;
  if (run.preview && $("#page-preview-image").dataset.run !== run.id + ":" + run.events.length) {
    $("#page-preview-image").src = "data:image/jpeg;base64," + run.preview;
    $("#page-preview-image").dataset.run = run.id + ":" + run.events.length;
  }
  renderPrompt(run.history ? null : run.prompt);
  renderNeeds(run, active);
}

// Jobs that need you, as actions: open the posting, or retry once you've sorted it out.
// What needs you after a run, grouped by why, each group with its own Retry.
const NEED_GROUPS = [
  ["Sign-in or account", /sign in|account|password|log ?in/i, "Store a password with `jobbot password` (jobbot then signs in or signs up), or sign in once in jobbot's Chrome window."],
  ["CAPTCHA", /captcha/i, "Solve the CAPTCHA in jobbot's Chrome window, then retry."],
  ["Site down", /maintenance/i, "The job site was down; retry later."],
  ["Unanswered questions", /unanswered|still empty|requires your answer/i, "Answer in the browser, or add an answers: rule in your profile, then retry."],
  ["Stuck or slow page", /gave up after|blocked|timeout|tab was closed|no application fields/i, "Usually fixed by a retry."],
];

function needGroup(note) {
  return NEED_GROUPS.find(([, rx]) => rx.test(note || "")) || ["Other", null, "Open the posting to see what it needs, then retry."];
}

function renderNeeds(run, active) {
  const results = run.results || {};
  const needs = run.jobs.filter((j) => (results[j.url] || {}).status === "needs you");
  const submitted = run.jobs.filter((j) => (results[j.url] || {}).status === "applied").length;
  const tally = run.jobs.length ? `<p class="hint"><b>${submitted}</b> submitted · <b>${needs.length}</b> need you · ${Object.keys(results).length} of ${run.jobs.length} done</p>` : "";
  if (!needs.length) {
    $("#needs").innerHTML = tally + (run.history && !active ? `<div class="empty">Nothing from this run needs you.</div>` : "");
    return;
  }
  const groups = new Map();
  for (const j of needs) {
    const [name, , hint] = needGroup(results[j.url].note);
    if (!groups.has(name)) groups.set(name, { hint, jobs: [] });
    groups.get(name).jobs.push(j);
  }
  $("#needs").innerHTML = tally + `<div class="needs"><h4>Needs you (${needs.length})</h4>` + [...groups].map(([name, g]) => `
    <details open><summary><b>${esc(name)}</b> (${g.jobs.length})
      ${active ? "" : `<button class="link" data-retry-all="${esc(g.jobs.map((j) => j.n || j.url).join("\n"))}">Retry ${g.jobs.length > 1 ? "these " + g.jobs.length : "it"}</button>`}</summary>
      <p class="hint">${esc(g.hint)}</p>
      <ul>${g.jobs.map((j) => `<li><b>${esc(j.company)}</b> — ${esc(j.title)}<div class="reason">${esc(results[j.url].note || "")}</div>
        <a href="${esc(j.url)}" target="_blank" rel="noopener">Open posting</a>
        ${active ? "" : `<button class="link" data-retry="${esc(String(j.n || j.url))}">Retry</button>`}</li>`).join("")}</ul></details>`).join("")
    + (active || needs.length < 2 ? "" : `<button data-retry-all="${esc(needs.map((j) => j.n || j.url).join("\n"))}">Retry all ${needs.length}</button>`)
    + `</div>`;
}

async function retry(keys) {
  try {
    // a retry keeps the run's mode: auto-submit runs submit again, dry runs stay dry
    await api("apply", state.run.auto_submit ? { jobs: keys, auto_submit: true }
      : { jobs: keys, unattended: !state.run.validation, validation: !!state.run.validation, dry_run: !!state.run.dry_run });
    state.viewing = false;
    loadRun();
  } catch (e) { alertInline($("#needs"), e.message); }
}

function renderEvent(e) {
  if (e.kind === "audit") {
    return `<details class="ev"><summary>${esc(e.t)} Page ${e.step}, revision ${e.round} — ${e.ok ? "verified" : "needs revision"} (${e.fields.length} fields)</summary>
      <table class="grid"><thead><tr><th>Field</th><th>Expected</th><th>Page value</th><th>Result</th></tr></thead><tbody>${e.fields.map((f) => `<tr><td>${esc(f.label)}${f.required ? " *" : ""}</td><td>${esc(f.expected ?? "Not set by jobbot")}</td><td>${esc(f.actual)}</td><td>${esc(f.status)}</td></tr>`).join("")}</tbody></table>
      <ul>${(e.problems || []).map((p) => `<li>${esc(p)}</li>`).join("")}</ul></details>`;
  }
  if (e.kind === "report") {
    const items = e.filled.map((f) => `<li><b>${esc(f.label)}</b> → ${esc(f.value)} <span class="muted">${esc(f.source)}</span></li>`).join("");
    const probs = (e.problems || []).map((p) => `<li style="color:var(--bad)">${esc(p)}</li>`).join("");
    const status = e.ok === null ? "" : e.ok ? " · ✓ all checks passed" : " · ✗ problems found";
    return `<div class="ev report ${e.ok === false ? "bad" : ""}"><span class="t">${esc(e.t)}</span>${esc(e.text)} — ${e.filled.length} field(s) set${status}<ul>${items}${probs}</ul></div>`;
  }
  return `<div class="ev ${esc(e.kind)}"><span class="t">${esc(e.t)}</span>${esc(e.text)}</div>`;
}

// The role a run is on now, and the latest read-back of its newest page.
function currentJob() {
  const run = state.run;
  return run && run.current != null ? (run.jobs || [])[run.current] : null;
}

function currentAudit() {
  const job = currentJob(), audits = (state.run && state.run.audits) || [];
  const mine = job ? audits.filter((a) => a.job && a.job.url === job.url) : audits;
  return mine.reduce((best, a) => (!best || a.step >= best.step ? a : best), null);
}

function renderPrompt(p) {
  const box = $("#prompt");
  if (!p) {
    const run = state.run;
    box.innerHTML = run && ["starting", "running"].includes(run.status)
      ? `<div class="empty">Working… jobbot is filling and checking the page in Chrome.</div>` : "";
    box.dataset.pid = "";
    return;
  }
  if (box.dataset.pid === p.id) return;   // keep what you are typing while polling
  box.dataset.pid = p.id;
  const q = `<div class="q">${esc(p.question || "")}</div>`;
  let html = "";
  if (p.kind === "action") {
    const labels = { submit: p.check_ok ? "Submit application" : "Submit anyway", next: "Next step", refill: "Revise and re-check", done: "I submitted it myself", quit: "Quit without submitting" };
    // With problems open, re-checking is the safe default; Submit is only primary once every check passed.
    const primary = p.check_ok ? (p.final ? "submit" : "next") : "refill";
    const head = p.final && p.check_ok ? "Final step: every check passed" : p.check_ok ? "Review the page in Chrome" : "The check found problems";
    const job = currentJob();
    const problems = p.check_ok ? [] : ((currentAudit() || {}).problems || []);
    const hint = p.final && p.check_ok
      ? (p.dry_run ? "Dry run: this is the last page and nothing will be submitted. Look it over in Chrome, then quit." : "Look over the application in jobbot's Chrome window, then submit.")
      : problems.length ? "Fix these in jobbot's Chrome window, or correct a field below, then re-check:" : "Look over the page in jobbot's Chrome window, then choose:";
    html = `<div class="prompt ${p.final && p.check_ok ? "final" : ""}"><h4>${esc(head)}</h4>
      ${job ? `<div class="prompt-job">${esc(job.company)} — ${esc(job.title)}</div>` : ""}
      <div class="q">${hint}</div>
      ${problems.length ? `<ul class="problems">${problems.slice(0, 8).map((l) => `<li>${esc(l.replace(/^page says: /, ""))}</li>`).join("")}</ul>` : ""}
      <div class="actions">${p.choices.filter((c) => !(p.dry_run && c === "done")).map((c) => `<button data-answer="${c}" class="${c === primary ? "primary" : ""}">${esc(labels[c] || c)}</button>`).join("")}</div>
      ${p.dry_run ? `<p class="reason">Dry run: submitting is disabled.</p>` : ""}</div>`;
  } else if (p.kind === "confirm") {
    html = `<div class="prompt"><h4>Confirm</h4>${q}<div class="actions"><button class="primary" data-answer="true">Yes</button><button data-answer="false">No</button><button data-answer="skip">Skip this role</button></div></div>`;
  } else if (p.kind === "wait") {
    html = `<div class="prompt"><h4>Your turn in Chrome</h4>${q}<div class="actions"><button class="primary" data-answer="null">Done, continue</button><button data-answer="skip">Skip this role</button></div></div>`;
  } else if (p.kind === "code") {
    html = `<div class="prompt"><h4>Verification code</h4>${q}<input type="text" id="p-text" placeholder="Code from your email" autocomplete="one-time-code">
      <div class="actions"><button class="primary" data-answer="text">Enter code</button><button data-answer="null">Skip</button></div></div>`;
  } else {
    const reason = `<div class="reason">${esc(p.reason || "")}${p.required ? " · required" : " · optional"}</div>`;
    if (p.options && p.options.length) {
      html = `<div class="prompt"><h4>Question</h4>${q}${reason}<div class="opts">${p.options.map((o, i) => `<button data-answer="${i}">${esc(o)}</button>`).join("")}</div>
        <div class="actions"><button class="link" data-answer="null">Leave blank</button></div></div>`;
    } else {
      html = `<div class="prompt"><h4>Question</h4>${q}${reason}<textarea id="p-text" rows="${p.suggestion ? 5 : 3}">${esc(p.suggestion || "")}</textarea>
        <div class="actions"><button class="primary" data-answer="text">${p.suggestion ? "Use this answer" : "Answer"}</button><button data-answer="null">Leave blank</button></div></div>`;
    }
  }
  if (p.kind === "action") {
    const audit = currentAudit();
    const editable = audit ? audit.fields.filter((f) => ["text", "textarea", "select", "radio", "yesno"].includes(f.kind) && !/consent|agree|terms|certify|gender|race|ethnic|veteran|disability|signature|password/i.test(f.label)) : [];
    if (editable.length) html += `<details class="prompt"><summary>Correct a field and re-check</summary>${editable.map((f, i) => `<label>${esc(f.label)}${["select", "radio", "yesno"].includes(f.kind) ? `<select id="correction-${i}">${f.options.map((o) => `<option ${o === f.actual ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>` : `<input id="correction-${i}" type="text" value="${esc(f.actual)}">`}</label><button data-correct="${esc(f.id)}" data-input="correction-${i}">Correct: ${esc(f.label)}</button>`).join("")}</details>`;
  }
  box.innerHTML = html;
  const input = $("#p-text", box);
  if (input) input.focus();
}

async function answerPrompt(raw) {
  const p = state.run && state.run.prompt;
  if (!p) return;
  let value = null;
  if (raw === "text") value = $("#p-text").value;
  else if (raw === "true") value = true;
  else if (raw === "false") value = false;
  else if (raw !== "null") value = /^\d+$/.test(raw) && p.kind === "ask" ? Number(raw) : raw;
  $$("#prompt button").forEach((b) => (b.disabled = true));
  try { await api("apply/answer", { prompt_id: p.id, value }); } catch (e) {
    alertInline($("#prompt"), e.message);
    $$("#prompt button").forEach((b) => (b.disabled = false));
    return;
  }
  await loadRun();
}

// ---------- applications ----------
async function loadApps() {
  const params = new URLSearchParams({ q: $("#apps-q").value, status: $("#apps-status").value });
  state.apps = await api("applications?" + params);
  renderApps();
}

function renderApps() {
  const rows = sortRows(state.apps, state.appSort);
  markSorted($("#apps-table"), state.appSort);
  $("#apps-count").textContent = `${rows.length} application${rows.length === 1 ? "" : "s"}`;
  $("#apps-table tbody").innerHTML = rows.length ? rows.map((a) => `<tr class="clickable" data-app="${a.id}">
      <td class="num">${a.id}</td><td>${esc(a.company)}</td>
      <td class="role">${a.url ? `<a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a>` : esc(a.title)}
        ${a.notes ? `<div class="reason">${esc(a.notes).slice(0, 140)}</div>` : ""}</td>
      <td><span class="pill ${esc(a.status)}">${esc(a.status)}</span></td>
      <td class="num">${esc(a.applied_on || "")}</td><td class="num">${esc((a.updated_on || "").slice(0, 10))}</td>
      <td>${esc(a.source || "")}</td></tr>`).join("")
    : `<tr><td colspan="7" class="empty">No applications yet.</td></tr>`;
}

async function openApp(id) {
  const a = await api("applications/" + id);
  const statuses = state.summary.statuses.map((s) => `<option ${s === a.status ? "selected" : ""}>${esc(s)}</option>`).join("");
  const history = a.events.map((e) => `<li>${esc(e.at.replace("T", " "))} · <b>${esc(e.status)}</b> ${esc(e.note || "")}</li>`).join("");
  openDialog(`<h2>${esc(a.company)} — ${esc(a.title)}</h2>
    <div class="muted">${esc(a.location || "")} ${a.applied_on ? "· applied " + esc(a.applied_on) : ""} · via ${esc(a.source || "?")}</div>
    ${a.url ? `<p><a href="${esc(a.url)}" target="_blank" rel="noopener">Open posting</a></p>` : ""}
    <div class="row"><label>Company</label><input type="text" name="company" value="${esc(a.company)}"></div>
    <div class="row"><label>Role${a.title.startsWith("(role not stated") ? " — naming it stops this application matching every role at the company" : ""}</label>
      <input type="text" name="title" value="${esc(a.title)}"></div>
    <div class="row"><label>Posting link (optional)</label><input type="text" name="url" value="${esc(a.url || "")}"></div>
    <div class="row"><label>Status</label><select name="status">${statuses}</select></div>
    <div class="row"><label>Note for this change (optional)</label><input type="text" name="change_note" placeholder="e.g. system design round on Friday"></div>
    <div class="row"><label>Notes</label><textarea name="note" rows="3">${esc(a.notes || "")}</textarea></div>
    <div class="row"><label>History</label><ol class="history">${history}</ol></div>
    <div class="actions"><button value="cancel">Close</button><button class="primary" value="save">Save</button></div>`,
    async (form) => {
      if (form.company.value !== a.company || form.title.value !== a.title || form.url.value !== (a.url || ""))
        await api(`applications/${id}/edit`, { company: form.company.value, title: form.title.value, url: form.url.value });
      if (form.status.value !== a.status) await api(`applications/${id}/status`, { status: form.status.value, note: form.change_note.value });
      if (form.note.value !== (a.notes || "")) await api(`applications/${id}/note`, { note: form.note.value });
      await Promise.all([loadApps(), loadSummary()]);
      state.allJobs = null;   // matching may have changed
    });
}

function addApp() {
  const statuses = state.summary.statuses.map((s) => `<option ${s === "applied" ? "selected" : ""}>${esc(s)}</option>`).join("");
  openDialog(`<h2>Add an application</h2>
    <p class="muted">For roles you applied to outside jobbot, so it never reopens them.</p>
    <div class="row"><label>Company</label><input type="text" name="company" required></div>
    <div class="row"><label>Role</label><input type="text" name="title" required></div>
    <div class="row"><label>Posting URL (optional, best for exact matching)</label><input type="text" name="url"></div>
    <div class="row"><label>Applied on</label><input type="date" name="applied_on" value="${new Date().toISOString().slice(0, 10)}"></div>
    <div class="row"><label>Status</label><select name="status">${statuses}</select></div>
    <div class="row"><label>Note</label><input type="text" name="note"></div>
    <div class="actions"><button value="cancel" formnovalidate>Cancel</button><button class="primary" value="save">Add</button></div>`,
    async (form) => {
      await api("applications", { company: form.company.value, title: form.title.value, url: form.url.value,
        applied_on: form.applied_on.value, status: form.status.value, note: form.note.value });
      await Promise.all([loadApps(), loadSummary()]);
    });
}

function openDialog(html, onSave) {
  const dlg = $("#dlg"), form = $("#dlg-form");
  form.innerHTML = html;
  dlg.showModal();
  form.onsubmit = async (ev) => {
    if (ev.submitter && ev.submitter.value === "save") {
      ev.preventDefault();
      try { await onSave(form); dlg.close(); } catch (e) { alertInline(form, e.message); }
    }
  };
}

function alertInline(root, msg) {
  let el = $(".err", root);
  if (!el) { el = document.createElement("p"); el.className = "err"; el.style.color = "var(--bad)"; root.appendChild(el); }
  el.textContent = msg;
}

// ---------- actions / tasks ----------
async function startTask(name) {
  try { await api("tasks/" + name, {}); } catch (e) { alertInline($(`[data-task="${name}"]`).closest(".card"), e.message); }
  loadTasks();
}

async function loadTasks() {
  const tasks = await api("tasks");
  $("#tasks").innerHTML = tasks.length ? tasks.map((t) => `<div class="task">
      <div class="task-head"><b>${esc(t.name)}</b><span class="pill ${t.status === "done" ? "applied" : t.status === "failed" ? "rejected" : "interview"}">${esc(t.status)}</span>
        <span class="when">${esc(t.started.replace("T", " "))}</span></div>
      <pre>${esc(t.lines.slice(-200).join("\n")) || "…"}</pre></div>`).join("")
    : `<div class="empty">Nothing has run yet in this session.</div>`;
  $$(".task pre").forEach((p) => (p.scrollTop = p.scrollHeight));
  renderRefresh(tasks);
  const running = tasks.some((t) => t.status === "running");
  $$("[data-task]").forEach((b) => (b.disabled = running && !b.dataset.task.startsWith("gmail") ? true : b.disabled));
  if (running && !state.polling) state.polling = setInterval(loadTasks, 1500);
  if (!running && state.polling) {
    clearInterval(state.polling);
    state.polling = null;
    $$("[data-task]").forEach((b) => (b.disabled = false));
    await loadSummary();
    if (state.tab === "jobs") await loadJobs();
  }
}

// The Jobs tab's "Refresh jobs" = scan + rank. Shows the latest such task's progress.
function renderRefresh(tasks) {
  const t = tasks.find((x) => ["refresh", "scan", "rank"].includes(x.name));
  const el = $("#refresh-status"), btn = $("#jobs-refresh");
  const busy = t && t.status === "running";
  btn.disabled = busy;
  const steps = { track: ["Syncing Gmail…", "Reading application emails"], scan: ["Scanning…", "Scanning job boards"], rank: ["Ranking…", "Ranking new roles"] };
  const order = t && t.name === "refresh" ? ["track", "scan", "rank"] : [];
  const [short, long] = (t && steps[t.step]) || steps.scan;
  const of = order.includes(t && t.step) ? ` (${order.indexOf(t.step) + 1}/3)` : "";
  btn.textContent = busy ? short : "Refresh jobs";
  if (!t) { el.hidden = true; return; }
  const last = t.lines.filter((l) => l.trim() && !l.startsWith("$ ")).slice(-1)[0] || "";
  el.hidden = false;
  el.className = "refresh-status " + (t.status === "failed" ? "bad" : "");
  el.textContent = busy ? `${long}${of}… ${last}`
    : t.status === "failed" ? `${t.name} failed: ${last} (details in Actions)`
    : `Last ${t.name} finished ${t.ended ? t.ended.slice(11, 16) : ""}. ${last}`;
}

// ---------- logs ----------
async function loadLogs(date) {
  const data = await api("logs?" + new URLSearchParams({ date: date || $("#logs-date").value || "" }));
  const sel = $("#logs-date");
  sel.innerHTML = data.dates.map((d) => `<option ${d === data.date ? "selected" : ""}>${esc(d)}</option>`).join("") || "<option value=''>No logs yet</option>";
  state.logLines = data.lines;
  renderLogs();
}

function renderLogs() {
  const q = $("#logs-q").value.toLowerCase();
  const lines = (state.logLines || []).filter((l) => !q || l.toLowerCase().includes(q));
  $("#logs").innerHTML = lines.map((l) => {
    const cls = l.includes(" ! ") || /\s!\s/.test(l) ? "warn" : l.includes("===") ? "head" : "";
    return `<span class="${cls}">${esc(l)}</span>`;
  }).join("\n") || "No log lines. `apply` writes here as it fills applications.";
}

// ---------- profile ----------
async function loadProfile() {
  const p = await api("profile");
  $("#profile-path").textContent = p.path;
  $("#profile-text").value = p.text;
  $("#profile-msg").textContent = "";
  state.profileMtime = p.mtime;
}

async function saveProfile() {
  const msg = $("#profile-msg");
  try {
    const r = await api("profile", { text: $("#profile-text").value, mtime: state.profileMtime });
    state.profileMtime = r.mtime;
    msg.textContent = "Saved."; msg.style.color = "var(--good)";
  } catch (e) {
    msg.textContent = e.message; msg.style.color = "var(--bad)";
  }
}

// ---------- docs ----------
// A small Markdown renderer for our own docs/ pages: everything is escaped first, then a known set of
// constructs (headings, lists, tables, code, bold, links) is turned into HTML.
function md(src) {
  const inline = (t) => esc(t)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, text, href) => {
      const doc = href.match(/^(?:\.\/)?([\w-]+)\.md(?:#([\w-]+))?$/);
      if (doc) return `<a href="#" data-doc="${doc[1]}" data-anchor="${doc[2] || ""}">${text}</a>`;
      if (href.startsWith("#")) return `<a href="#" data-anchor="${href.slice(1)}">${text}</a>`;
      if (/^https?:\/\//.test(href)) return `<a href="${href}" target="_blank" rel="noopener">${text}</a>`;
      return text;   // links outside docs/ (../README.md, LICENSE) are shown as plain text
    });
  const slug = (t) => t.toLowerCase().replace(/[^a-z0-9 -]/g, "").replace(/ /g, "-");
  const lines = src.replace(/\r/g, "").split("\n"), out = [];
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (/^```/.test(l)) {
      const code = []; while (++i < lines.length && !/^```/.test(lines[i])) code.push(lines[i]);
      out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);
    } else if (/^#{1,4} /.test(l)) {
      const level = l.match(/^#+/)[0].length, text = l.replace(/^#+ /, "");
      out.push(`<h${level} id="${slug(text)}">${inline(text)}</h${level}>`);
    } else if (/^\|/.test(l)) {
      const rows = []; i--; while (++i < lines.length && /^\|/.test(lines[i])) rows.push(lines[i]);
      i--;
      const cells = (r) => r.replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map((c) => inline(c.trim().replace(/\\\|/g, "|")));
      const body = rows.filter((r) => !/^\|[\s:|-]+\|$/.test(r));
      out.push(`<table class="grid"><thead><tr>${cells(body[0]).map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>` +
        body.slice(1).map((r) => `<tr>${cells(r).map((c) => `<td>${c}</td>`).join("")}</tr>`).join("") + "</tbody></table>");
    } else if (/^\s*([-*]|\d+\.) /.test(l)) {
      // A list: each item's own text, plus any indented lines under it (wrapped text, a sub-list, a table,
      // code), which are rendered recursively.
      const indent = l.match(/^\s*/)[0].length, ordered = /^\s*\d+\./.test(l);
      const startAt = ordered ? parseInt(l.trim(), 10) : 1;
      const items = [];
      i--;
      while (++i < lines.length) {
        const cur = lines[i], ind = cur.match(/^\s*/)[0].length;
        const isItem = new RegExp(`^\\s{${indent}}${ordered ? "\\d+\\." : "[-*]"} `).test(cur) && ind === indent;
        if (isItem) { items.push({ text: cur.replace(/^\s*([-*]|\d+\.) /, ""), body: [] }); continue; }
        if (!items.length) break;
        if (!cur.trim()) {   // a blank line ends the list unless more indented content follows
          const next = lines.slice(i + 1).find((x) => x.trim());
          if (!next || next.match(/^\s*/)[0].length <= indent) break;
          items[items.length - 1].body.push("");
          continue;
        }
        if (ind <= indent) break;
        items[items.length - 1].body.push(cur);
      }
      i--;
      const renderItem = (it) => {
        const body = it.body.slice(), text = [it.text];
        // wrapped continuation of the item's own sentence
        while (body.length && body[0].trim() && !/^\s*([-*]|\d+\.) |^\s*\||^\s*```/.test(body[0])) text.push(body.shift().trim());
        const rest = body.filter((x, k) => x.trim() || k < body.length - 1);
        const pad = Math.min(...rest.filter((x) => x.trim()).map((x) => x.match(/^\s*/)[0].length), 99);
        return `<li>${inline(text.join(" "))}${rest.some((x) => x.trim()) ? md(rest.map((x) => x.slice(pad)).join("\n")) : ""}</li>`;
      };
      out.push(ordered ? `<ol start="${startAt}">${items.map(renderItem).join("")}</ol>` : `<ul>${items.map(renderItem).join("")}</ul>`);
    } else if (/^> /.test(l)) {
      out.push(`<blockquote>${inline(l.slice(2))}</blockquote>`);
    } else if (/^---+$/.test(l.trim())) {
      out.push("<hr>");
    } else if (l.trim()) {
      const para = [l]; while (i + 1 < lines.length && lines[i + 1].trim() && !/^(#|\||```|>|\s*([-*]|\d+\.) |---)/.test(lines[i + 1])) para.push(lines[++i]);
      out.push(`<p>${inline(para.join(" "))}</p>`);
    }
  }
  return out.join("\n");
}

async function loadDocs(name = state.doc || "README", anchor = "") {
  if (!state.docsIndex) state.docsIndex = await api("docs");
  $("#docs-nav").innerHTML = state.docsIndex.map((p) =>
    `<a href="#" data-doc="${esc(p.name)}" class="${p.name === name ? "on" : ""}">${esc(p.title)}</a>`).join("");
  const page = await api("docs/" + encodeURIComponent(name));
  state.doc = name;
  $("#docs-page").innerHTML = md(page.text);
  const target = anchor && document.getElementById(anchor);
  (target || $("#docs-page")).scrollIntoView({ block: "start" });
}

// ---------- wiring ----------
document.addEventListener("DOMContentLoaded", async () => {
  $$(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  const reloadJobs = debounce(loadJobs);
  ["#jobs-q", "#jobs-min"].forEach((s) => $(s).addEventListener("input", reloadJobs));
  $("#notdup-selected").addEventListener("click", markNotDuplicates);
  $("#jobs-views").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-view]");
    if (b) { state.view = b.dataset.view; renderJobs(); }
  });
  $("#jobs-table tbody").addEventListener("change", (ev) => {
    const cb = ev.target.closest("input[data-select]");
    if (!cb) return;
    cb.checked ? state.selected.add(cb.dataset.select) : state.selected.delete(cb.dataset.select);
    updateSelection();
  });
  $("#apply-selected").addEventListener("click", () => startRun(false));
  $("#dry-selected").addEventListener("click", () => startRun(true));
  $("#sel-clear").addEventListener("click", () => { state.selected.clear(); renderJobs(); });
  $("#sel-all").addEventListener("click", () => selectAll(true));
  $("#sel-top-n").value = recall("topN") || 10;
  $("#sel-top").addEventListener("click", () => selectTop(Math.max(1, parseInt($("#sel-top-n").value, 10) || 10)));
  $("#sel-all-box").addEventListener("change", (ev) => selectAll(ev.target.checked));
  $("#prompt").addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-answer]");
    if (b) answerPrompt(b.dataset.answer);
    const correction = ev.target.closest("button[data-correct]");
    if (correction) {
      const p = state.run.prompt;
      $$("#prompt button").forEach((b) => b.disabled = true);
      api("apply/answer", {prompt_id:p.id, value:{action:"correct", field:correction.dataset.correct, value:$("#" + correction.dataset.input).value}}).then(loadRun).catch((e) => { correction.disabled=false; $("#prompt").insertAdjacentHTML("beforeend", `<p role="alert">${esc(e.message)}</p>`); });
    }
  });
  $("#run-stop").addEventListener("click", async () => { await api("apply/stop", {}); loadRun(); });
  $("#jobs-table tbody").addEventListener("click", async (ev) => {
    const b = ev.target.closest("button[data-job]");
    if (!b) return;
    await api(`jobs/${b.dataset.job}/${b.dataset.act}`, {});
    await Promise.all([loadJobs(), loadSummary()]);
  });
  $("#apps-q").addEventListener("input", debounce(loadApps));
  $("#apps-status").addEventListener("change", loadApps);
  $("#apps-add").addEventListener("click", addApp);
  $("#apps-table tbody").addEventListener("click", (ev) => {
    if (ev.target.closest("a")) return;
    const tr = ev.target.closest("tr[data-app]");
    if (tr) openApp(tr.dataset.app);
  });
  for (const [table, key, render] of [["#jobs-table", "jobSort", renderJobs], ["#apps-table", "appSort", renderApps]]) {
    $$(`${table} th[data-sort]`).forEach((th) => th.addEventListener("click", () => {
      const [cur, dir] = state[key];
      state[key] = [th.dataset.sort, cur === th.dataset.sort ? -dir : -1];
      render();
    }));
  }
  $$("[data-task]").forEach((b) => b.addEventListener("click", () => startTask(b.dataset.task)));
  $("#jobs-refresh").addEventListener("click", () => startTask("refresh"));
  $("#run-strip").addEventListener("click", (ev) => { if (ev.target.closest("[data-view-run]")) { state.viewing = false; showTab("apply"); } });
  $("#tab-apply").addEventListener("click", async (ev) => {
    const r = ev.target.closest("[data-retry]"), all = ev.target.closest("[data-retry-all]"), h = ev.target.closest("a[data-run]");
    if (r) retry([r.dataset.retry]);
    if (all) retry(all.dataset.retryAll.split("\n"));
    if (h) {
      ev.preventDefault();
      const saved = await api("runs/" + encodeURIComponent(h.dataset.run));
      const current = state.run && !state.run.history && ["starting", "running", "waiting"].includes(state.run.status);
      state.viewing = !current;
      if (!current) renderRun(saved);
    }
  });
  $("#tab-docs").addEventListener("click", (ev) => {
    const a = ev.target.closest("a[data-doc], a[data-anchor]");
    if (!a) return;
    ev.preventDefault();
    if (a.dataset.doc) loadDocs(a.dataset.doc, a.dataset.anchor);
    else document.getElementById(a.dataset.anchor)?.scrollIntoView({ block: "start" });
  });
  $("#logs-date").addEventListener("change", () => loadLogs($("#logs-date").value));
  $("#logs-q").addEventListener("input", debounce(renderLogs, 150));
  $("#profile-save").addEventListener("click", saveProfile);

  showTab(recall("tab") || "jobs");   // before any await, so a tab you click while it loads stays chosen
  await loadSummary();
  loadRun();
  // Keeps the counts fresh and notices a restarted or stopped dashboard even when nothing else polls.
  setInterval(() => { if (!document.hidden) loadSummary().catch(() => {}); }, 30000);   // picks up a run that is already in progress (and keeps polling while it is)
});
