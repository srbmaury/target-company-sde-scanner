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
  const reading = body === undefined;
  opts.signal = AbortSignal.timeout(reading ? 12000 : 25000);
  let res, data;
  try {
    res = await fetch("/api/" + path, opts);
    data = await res.json();
  } catch (e) {
    if (e.name === "TimeoutError" || e.name === "AbortError") {
      throw new Error(reading ? "The dashboard request timed out. Try again." :
        "The dashboard did not confirm the action. Check its status before retrying.");
    }
    if (res && e instanceof SyntaxError) throw new Error("The dashboard returned an unreadable response.");
    connection("Can't reach jobbot. Is <code>./jobbot.sh ui</code> still running?");
    throw e;
  }
  if (res.status === 401) {
    location.replace("/?session=expired");
    throw new Error("Sign in to Jobbot.");
  }
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
const pageLoads = new Map();

function loadPage(name, label, load) {
  if (pageLoads.has(name)) return pageLoads.get(name);
  const panel = $("#tab-" + name);
  let status = panel.querySelector(".page-load");
  if (!status) {
    status = document.createElement("div");
    status.className = "page-load";
    status.setAttribute("role", "status");
    panel.querySelector(".page-heading").after(status);
  }
  status.hidden = false;
  status.innerHTML = `<span class="live-spinner" aria-hidden="true"></span> Loading ${label}…`;
  panel.setAttribute("aria-busy", "true");
  const pending = Promise.resolve().then(load).then(() => {
    status.hidden = true;
  }).catch((error) => {
    status.textContent = `Could not load ${label}. ${error.message} `;
    const retry = document.createElement("button");
    retry.type = "button";
    retry.textContent = "Retry";
    retry.addEventListener("click", () => loadPage(name, label, load));
    status.append(retry);
  }).finally(() => {
    panel.removeAttribute("aria-busy");
    pageLoads.delete(name);
  });
  pageLoads.set(name, pending);
  return pending;
}

function showTab(name) {
  if (state.tab !== name) $("main").scrollTop = 0;
  state.tab = name;
  remember("tab", name);
  $$(".tabs [role=tab]").forEach((button) => {
    const active = button.dataset.tab === name;
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  });
  $$("main > [role=tabpanel]").forEach((p) => (p.hidden = p.id !== "tab-" + name));
  const pages = {
    jobs: ["jobs", loadJobs],
    apply: ["application runs", () => {
      state.viewing = false;
      loadHistory();
      return loadRun({strict: true, history: false});
    }],
    applications: ["applications", loadApps],
    actions: ["activity", () => loadTasks(true)],
    logs: ["logs", loadLogs],
    profile: ["profile", () => loadProfile(true)],
    docs: ["documentation", loadDocs],
  };
  if (name === "jobs") loadTasks();
  return loadPage(name, ...pages[name]);
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
    <span>${dot(s.llm_available)}${esc(s.llm_provider === "openai" ? "OpenAI API" : "Ollama")} ${s.llm_available ? (s.llm_provider === "openai" ? "key configured" : "running") : "unavailable"}</span>`;
  $("#gmail-text").textContent = s.gmail
    ? "Import application emails, and read verification codes and links for sign-ups."
    : s.account ? "Connect your Google account to import application emails with read-only access."
      : "Connect Gmail to import your applications. Needs the one-time OAuth client from the README.";
  $("#account-signout").hidden = !s.account;
  $("#gmail-disconnect").hidden = !(s.account && s.gmail);
  $("#gmail-login").hidden = !!(s.account && s.gmail);
  $("#gmail-state").textContent = s.gmail ? "Connected" : "Not connected";
  $("#gmail-state").classList.toggle("applied", Boolean(s.gmail));
  $("#workspace-mode").textContent = s.account ? "Hosted account" : "Local workspace";
  $("#workspace-mode").hidden = false;
  $("#hosted-apply-note").hidden = !s.account;
  $("#apply-selected").textContent = s.account ? "Fill for review" : "Apply to selected";
  $("#local-run-options").hidden = Boolean(s.account);
  $("#hosted-run-options").hidden = !s.account;
  $("#local-run-hint").hidden = Boolean(s.account);
  setAccountProfile(Boolean(s.account));
  $("#employer-auth").hidden = !s.account;
  $("#employer-auth-state").textContent = s.employer_password_configured
    ? "Employer password configured on the host." : "Employer password is missing. Sign in manually during runs.";
  setRunAvailability();
  $("#gmail-sync").disabled = !s.gmail;
  const sel = $("#apps-status");
  if (sel.options.length === 1) s.statuses.forEach((st) => sel.add(new Option(st, st)));
  if (state.tab === "logs") renderLogs();
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

async function loadTablePage(name, params, append, render) {
  const current = state[name + "Page"];
  if (append && (!current || current.next_offset == null || current.loading)) return;
  const page = append ? current : {};
  state[name + "Page"] = page;
  page.loading = true;
  const button = $("#" + name + "-more");
  button.disabled = true;
  if (!append) button.hidden = true;
  $(".err", button.parentElement)?.remove();
  button.textContent = append ? "Loading…" : "Load more";
  params.set("offset", append ? page.next_offset : 0);
  try {
    const result = await api((name === "apps" ? "applications" : name) + "?" + params);
    if (state[name + "Page"] !== page) return;
    // Older servers still return the full list.
    Object.assign(page, Array.isArray(result) ? {rows: result, total: result.length, next_offset: null} : result, {
      paged: !Array.isArray(result),
      rows: append ? [...new Map([...page.rows, ...result.rows].map((row) => [row.n ?? row.id, row])).values()] : result.rows || result,
    });
    button.hidden = page.next_offset == null;
    render(page);
  } finally {
    if (state[name + "Page"] === page) {
      page.loading = false;
      button.disabled = false;
      button.textContent = "Load more";
    }
  }
}

async function loadJobs(append = false) {
  const [sort, dir] = state.jobSort;
  const params = new URLSearchParams({
    q: $("#jobs-q").value, min_fit: $("#jobs-min").value,
    include_applied: "1", include_dismissed: "1", view: state.view || "new",
    sort, direction: dir === 1 ? "asc" : "desc",
  });
  await loadTablePage("jobs", params, append, (page) => {
    state.allJobs = page.rows;
    state.jobCatalog = state.jobCatalog || new Map();
    state.allJobs.forEach((j) => state.jobCatalog.set(String(j.n), j));
    renderJobs();
  });
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
    `<button role="tab" data-view="${key}" aria-selected="${state.view === key}">${label} <span class="n">${state.jobsPage?.counts ? state.jobsPage.counts[key] || 0 : all.filter(test).length}</span></button>`).join("");
}

function renderJobs() {
  state.view = state.view || "new";
  renderViews();
  const test = VIEWS.find(([k]) => k === state.view)[2];
  state.jobs = (state.allJobs || []).filter(test);
  const rows = state.jobsPage?.counts ? state.jobs : sortRows(state.jobs, state.jobSort);
  markSorted($("#jobs-table"), state.jobSort);
  $("#jobs-count").textContent = state.jobsPage?.next_offset != null ? `${rows.length} of ${state.jobsPage.total} roles` : `${rows.length} role${rows.length === 1 ? "" : "s"}`;
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
function setRunAvailability() {
  const hosted = Boolean(state.summary?.account);
  for (const button of [$("#apply-selected"), $("#dry-selected")]) {
    button.disabled = !state.summary || !state.selected.size;
    if (hosted) button.setAttribute("aria-describedby", "hosted-apply-note");
    else button.removeAttribute("aria-describedby");
  }
}

function updateSelection() {
  if (state.pendingRun && !state.runStarting) cancelRun();
  const n = state.selected.size;
  $("#notdup-selected").hidden = state.view !== "possible";
  $("#notdup-selected").disabled = !n;
  $("#sel-count").textContent = n ? `${n} selected` : "None selected";
  setRunAvailability();
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
  (state.jobsPage?.counts ? state.jobs : sortRows(state.jobs, state.jobSort)).map((j) => String(j.n)).filter((k) => ok.has(k)).slice(0, n)
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
  if (!jobs.length || !state.summary) return;
  const hosted = Boolean(state.summary.account);
  if (!hosted) dry = dry || ($("#validate-steps").checked && !$("#auto-submit").checked);
  state.pendingRun = hosted ? {jobs, dry_run: dry, auto_submit: !dry && $("#hosted-auto-submit").checked} : { jobs, dry_run: dry || $("#validate-steps").checked, unattended: $("#unattended").checked, validation: $("#validate-steps").checked, auto_next: $("#unattended").checked || !$("#validate-steps").checked };
  if (!hosted && !dry && $("#auto-submit").checked) {
    state.pendingRun = {jobs, dry_run: false, unattended: true, validation: true, auto_next: true, auto_submit: true};
  }
  const box = $("#run-confirmation");
  const roles = jobs.map((key) => state.jobCatalog.get(key)).filter(Boolean);
  box.hidden = false;
  box.innerHTML = `<h4>${dry ? "Confirm dry run" : "Confirm application run"}</h4>
    <p>${dry ? "Dry-run" : hosted ? "Fill" : "Apply to"} ${jobs.length} role${jobs.length === 1 ? "" : "s"}?
    ${hosted ? "Chromium runs on the host. Follow progress in Runs." : "Chrome will open in its own window."}
    ${dry ? "Forms may be filled and resumes uploaded; nothing will be submitted." : state.pendingRun.auto_submit ? "Completed applications will be submitted automatically after every check passes." : state.pendingRun.unattended ? "jobbot works through every role without stopping. Finished applications wait for your Submit, and roles that need you are listed at the end." : "You’ll confirm each Submit here."}</p>
    <details><summary>Review selected roles</summary><ul>${roles.map((j) => `<li>${esc(j.company)} — ${esc(j.title)}</li>`).join("")}</ul></details>
    <p id="run-confirm-error" role="alert"></p>
    <div class="actions"><button class="primary" id="run-confirm-start">${dry ? "Start dry run" : hosted && !state.pendingRun.auto_submit ? "Start filling" : "Start applications"}</button>
    <button id="run-confirm-cancel">Cancel</button></div>`;
  $("#run-confirm-start").addEventListener("click", confirmRun);
  $("#run-confirm-cancel").addEventListener("click", cancelRun);
  $("#run-confirm-start").focus();
  // Auto-submit runs send applications without asking again, so they are confirmed like every other run.
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

async function pollRun() {
  if (document.hidden || state.pollingRun || pageLoads.has("apply")) return;
  state.pollingRun = true;
  try {
    await loadRun();
  } finally {
    state.pollingRun = false;
  }
}

async function loadRun({strict = false, history = true} = {}) {
  // The initial Runs view owns its loading and error state until it settles.
  if (!strict && pageLoads.has("apply")) return;
  const request = state.runRequest = (state.runRequest || 0) + 1;
  let run;
  try {
    run = await api("apply");
    if (!run || typeof run.status !== "string") throw new Error("Invalid application run response.");
  } catch (e) {
    if (strict) throw e;
    return;
  }
  if (request !== state.runRequest) return;
  state.run = run;
  const active = ["starting", "running", "waiting"].includes(run.status);
  $("#apply-badge").hidden = run.status !== "waiting";
  document.title = run.status === "waiting" ? "● jobbot needs you" : "jobbot";
  if (active && !state.runPoll) state.runPoll = setInterval(pollRun, 1000);
  if (!active && state.runPoll) { clearInterval(state.runPoll); state.runPoll = null; loadSummary().catch(() => {}); state.historyStale = true; }
  renderStrip(run, active);
  if (active) state.viewing = false;
  if (state.tab === "apply" && !state.viewing) renderRun(run);
  if (state.tab === "apply" && state.historyLoaded) renderHistory();
  if (history && state.tab === "apply" && (state.historyStale || !state.historyLoaded)) loadHistory();
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
    (waiting ? " · <b>a question is waiting for you</b>" : state.summary?.account ? " · working in hosted Chromium" : "") +
    ` <button class="link" data-view-run>View run →</button>`;
}

const runActive = (status) => ["starting", "running", "waiting"].includes(status);
const runStatus = (status) => ({
  starting: "Starting", running: "Filling", waiting: "Needs review", done: "Finished",
  failed: "Failed", stopped: "Stopped", interrupted: "Interrupted",
})[status] || status;
const runDate = (value) => {
  if (!value) return "Unknown date";
  // Older snapshots have no UTC offset. Preserve their original host time.
  return /(?:Z|[+-]\d{2}:\d{2})$/.test(value)
    ? taskTime.format(new Date(value))
    : value.replace("T", " ") + " (host time)";
};

function historyMessage(message) {
  $("#history-message").textContent = message;
  $("#history-message").hidden = !message;
}

async function loadHistory() {
  if (state.loadingHistory) return;
  state.loadingHistory = true;
  const message = $("#history-message");
  historyMessage("Loading run history…");
  try {
    state.historyRuns = await api("runs");
    if (!Array.isArray(state.historyRuns)) throw new Error("Invalid run history.");
    state.historyLoaded = true;
    state.historyStale = false;
    renderHistory();
    historyMessage("");
  } catch (error) {
    historyMessage("Could not load run history. " + error.message + " ");
    const retry = document.createElement("button");
    retry.type = "button";
    retry.textContent = "Retry history";
    retry.addEventListener("click", loadHistory);
    message.append(retry);
  } finally {
    state.loadingHistory = false;
  }
}

function renderHistory() {
  const runs = state.historyRuns || [];
  const active = runActive(state.run?.status);
  const markup = runs.length ? runs.map((run) => {
    const selected = (state.viewing || state.run?.id) === run.id;
    const outcomes = Object.entries(run.counts || {}).map(([key, count]) => `${count} ${key}`).join(" · ");
    const label = [run.dry_run ? "Dry run" : "", runStatus(run.status), outcomes || `${run.total} queued`].filter(Boolean).join(" · ");
    return `<li${selected ? ' class="selected"' : ""}>
      <div><button type="button" class="link" data-run="${esc(run.id)}" ${active || runActive(run.status) ? "disabled" : ""}
        ${selected ? 'aria-current="true"' : ""}>${esc(runDate(run.started))}</button>
        <span class="sub">${esc(label)}</span></div>
      ${!runActive(run.status) ? `<button type="button" class="run-delete" data-delete-run="${esc(run.id)}"
        aria-label="Delete run from ${esc(runDate(run.started))}">Delete</button>` : ""}
    </li>`;
  }).join("") : '<li class="muted">No saved runs yet.</li>';
  if (state.historyMarkup !== markup) {
    $("#history").innerHTML = markup;
    state.historyMarkup = markup;
  }
}

const live = { prompt: null, control: null, frame: null, busy: false, timer: null, inputs: [] };

function resetLivePreview() {
  clearTimeout(live.timer);
  live.prompt = live.control = live.frame = null;
  live.inputs.length = 0;
  $("#live-image").removeAttribute("src");
  $("#live-input").value = "";
  $("#live-input").type = "text";
  $("#live-mask").checked = false;
  $("#live-message").textContent = "";
}

function renderLivePreview(run) {
  const prompt = !run.history && run.status === "waiting" && run.prompt?.interactive ? run.prompt.id : null;
  if (live.prompt !== prompt) {
    resetLivePreview();
    live.prompt = prompt;
  }
  $("#live-preview").hidden = !prompt;
  $("#live-open").hidden = Boolean(live.control);
  $("#live-open").textContent = run.dry_run ? "Open live view" : "Take control";
  $("#live-release").textContent = run.dry_run ? "Close live view" : "Return control and recheck";
  $("#live-viewport").hidden = !live.control;
  $("#live-help").textContent = run.dry_run
    ? "Dry-run view is read-only. Use the dashboard prompts to continue."
    : "Click or scroll the page. Use the keyboard or the text box below to enter answers. Use Next field to send Tab. Return control to recheck the page.";
  $("#live-text").hidden = $("#live-direct").hidden = $("#live-scroll-controls").hidden = Boolean(run.dry_run);
  $("#live-refresh").hidden = $("#live-release").hidden = !live.control;
  $("#prompt").inert = Boolean(live.control);
  $("#page-preview").hidden = Boolean(live.control) || !run.preview || Boolean(run.history);
}

const browserActionLabels = {
  open: "Opening browser…", frame: "Refreshing…", click: "Clicking…", scroll: "Scrolling…",
  text: "Typing…", key: "Sending key…", release: "Returning control…",
};

async function browserCommand(action, extra = {}, background = false) {
  if (!live.prompt) return false;
  if (live.busy) {
    if (action === "scroll" && live.inputs.at(-1)?.[0] === "scroll") {
      const previous = live.inputs.at(-1)[1];
      previous.delta = Math.max(-1600, Math.min(1600, previous.delta + extra.delta));
    } else if (!background && action !== "open" && live.inputs.length < 12) {
      live.inputs.push([action, extra]);
    } else if (!background && action !== "open") {
      $("#live-message").textContent = "Browser is catching up. Wait before sending more input.";
    }
    return false;
  }
  clearTimeout(live.timer);
  const prompt = live.prompt;
  const spinner = $("#live-spinner");
  const message = $("#live-message");
  live.busy = true;
  $("#live-send").disabled = true;
  if (!background) {
    spinner.hidden = false;
    message.textContent = browserActionLabels[action];
  }
  try {
    const reply = await api("apply/preview", {
      prompt_id: prompt, control: live.control, frame_id: live.frame, action, ...extra,
    });
    if (live.prompt !== prompt) return false;
    if (action === "release") {
      resetLivePreview();
      renderLivePreview(state.run);
      await loadRun();
      return true;
    }
    live.control = reply.control;
    renderLivePreview(state.run);
    const image = $("#live-image");
    const source = "data:image/jpeg;base64," + reply.image;
    const next = new Image();
    next.src = source;
    await next.decode();
    if (live.prompt !== prompt) return false;
    image.src = source;
    image.width = reply.width;
    image.height = reply.height;
    live.frame = reply.frame_id;
    if (!background) message.textContent = state.run.dry_run ? "Live view · read-only" : "You have control. Jobbot is paused.";
    renderLivePreview(state.run);
    if (action === "open") image.focus({preventScroll: true});
    return true;
  } catch (error) {
    if (live.prompt === prompt) {
      message.textContent = error.message;
      // Stop queued gestures after a failed command. The employer may have
      // received the input even when its updated frame could not be captured.
      live.inputs.length = 0;
    }
    return false;
  } finally {
    live.busy = false;
    spinner.hidden = true;
    $("#live-send").disabled = false;
    if (live.control && live.prompt === prompt) {
      if (live.inputs.length) browserCommand(...live.inputs.shift());
      else if (state.tab === "apply" && state.run?.dry_run) live.timer = setTimeout(() => browserCommand("frame", {}, true), 2500);
    }
  }
}

function wireLivePreview() {
  $("#live-mask").addEventListener("change", (event) => {
    $("#live-input").type = event.target.checked ? "password" : "text";
  });
  $("#live-open").addEventListener("click", () => browserCommand("open"));
  $("#live-release").addEventListener("click", () => browserCommand("release"));
  $("#live-refresh").addEventListener("click", () => browserCommand("frame"));
  $$("[data-live-scroll]").forEach((button) => button.addEventListener("click", () => {
    if (!state.run?.dry_run) browserCommand("scroll", {x: .5, y: .5, delta: Number(button.dataset.liveScroll)});
  }));
  $("#live-tab").addEventListener("click", () => browserCommand("key", {key: "Tab"}));
  const frame = $("#live-image");
  const coords = (event) => {
    const rect = frame.getBoundingClientRect();
    const normalize = (value, size) => Math.max(0, Math.min(1, value / size));
    return {
      x: normalize(event.clientX - rect.left - frame.clientLeft, frame.clientWidth),
      y: normalize(event.clientY - rect.top - frame.clientTop, frame.clientHeight),
    };
  };
  frame.addEventListener("click", (event) => {
    if (!state.run?.dry_run) {
      frame.focus({preventScroll: true});
      browserCommand("click", coords(event));
    }
  });
  frame.addEventListener("wheel", (event) => {
    if (state.run?.dry_run) return;
    event.preventDefault();
    const unit = event.deltaMode === 1 ? 40 : event.deltaMode === 2 ? frame.height : frame.height / frame.clientHeight;
    browserCommand("scroll", { ...coords(event), delta: Math.max(-1600, Math.min(1600, event.deltaY * unit)) });
  }, {passive: false});
  frame.addEventListener("keydown", (event) => {
    if (state.run?.dry_run || event.ctrlKey || event.altKey || event.metaKey) return;
    // Leave Tab and Escape to the dashboard so keyboard users can leave the viewport.
    if (!["Enter", "Backspace", "Delete", "Home", "End", "ArrowLeft", "ArrowRight", "ArrowUp",
      "ArrowDown", "PageUp", "PageDown"].includes(event.key) && event.key.length !== 1) return;
    event.preventDefault();
    if (event.key.length === 1) browserCommand("text", { text: event.key });
    else browserCommand("key", { key: event.key });
  });
  $("#live-text").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = $("#live-input");
    const text = input.value;
    if (text && !live.busy && await browserCommand("text", {text})) {
      if (input.value === text) input.value = "";
      frame.focus({preventScroll: true});
    }
  });
}

function renderRun(run) {
  run = {jobs: [], results: {}, events: [], ...run};
  state.displayedRun = run;
  renderLivePreview(run);
  $("#run-current").hidden = !state.viewing;
  $("#run-activity").hidden = !run.events?.length;
  $("#run-queue-card").hidden = !run.jobs?.length;
  if (run.status === "idle") {
    $("#run-title").textContent = "No runs yet";
    $("#run-status").textContent = ""; $("#run-progress").textContent = "";
    $("#prompt").innerHTML = state.summary?.account
      ? '<div class="workspace-notice"><div><strong>No hosted run yet</strong><p>Select roles in Jobs, then choose Fill for review or Dry run.</p></div><button type="button" data-go="jobs">Go to Jobs</button></div>'
      : `<div class="empty"><p><b>To start a run:</b> tick roles in the Jobs tab, then <b>Apply to selected</b>
      (or <b>Dry run</b> to fill and check without submitting).</p><p>Tick <b>Don't stop for me</b> to run the whole batch unattended:
      jobs that need you are listed here, and finished applications wait for your Submit.</p></div>`;
    $("#feed").innerHTML = ""; $("#queue").innerHTML = ""; $("#needs").innerHTML = ""; $("#run-stop").hidden = true;
    return;
  }
  const active = ["starting", "running", "waiting"].includes(run.status);
  const when = runDate(run.started);
  $("#run-title").textContent = (run.history || !active ? when + " · " : "")
    + (run.dry_run ? "Dry run" : run.unattended ? "Unattended run" : "Application run");
  $("#run-status").textContent = runStatus(run.status);
  $("#run-status").className = "pill " + ({ waiting: "maybe", running: "interview", done: "applied", failed: "rejected", stopped: "withdrawn" }[run.status] || "");
  const done = Object.keys(run.results || {}).length;
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
  const preview = $("#page-preview-image");
  if (run.preview && !run.history) {
    const source = "data:image/jpeg;base64," + run.preview;
    if (preview.getAttribute("src") !== source) preview.src = source;
  } else {
    preview.removeAttribute("src");
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
    const [name, , localHint] = needGroup(results[j.url].note);
    const hint = state.summary?.account && ["Sign-in or account", "CAPTCHA"].includes(name)
      ? "For live runs, use Take control when prompted. If that does not work, finish on the employer site." : localHint;
    if (!groups.has(name)) groups.set(name, { hint, jobs: [] });
    groups.get(name).jobs.push(j);
  }
  $("#needs").innerHTML = tally + `<div class="needs"><h4>Needs you (${needs.length})</h4>` + [...groups].map(([name, g]) => `
    <details open><summary><b>${esc(name)}</b> (${g.jobs.length})
      ${active ? "" : `<button class="link" data-retry-all="${esc(g.jobs.map((j) => j.n || j.url).join("\n"))}">Retry ${g.jobs.length > 1 ? "these " + g.jobs.length : "it"}</button>`}</summary>
      <p class="hint">${esc(g.hint)}</p>
      <ul>${g.jobs.map((j) => `<li><b>${esc(j.company)}</b> — ${esc(j.title)}<div class="reason">${esc((results[j.url].note || "").replace(/\s*Screenshot:\s+\S+\.png/gi, ""))}</div>
        <a href="${esc(j.url)}" target="_blank" rel="noopener">Open posting</a>
        ${active ? "" : `<button class="link" data-retry="${esc(String(j.n || j.url))}">Retry</button>`}</li>`).join("")}</ul></details>`).join("")
    + (active || needs.length < 2 ? "" : `<button data-retry-all="${esc(needs.map((j) => j.n || j.url).join("\n"))}">Retry all ${needs.length}</button>`)
    + `</div>`;
}

async function retry(keys) {
  const run = state.displayedRun;
  try {
    // a retry keeps the run's mode: auto-submit runs submit again, dry runs stay dry
    await api("apply", run.auto_submit ? { jobs: keys, auto_submit: true }
      : { jobs: keys, unattended: !run.validation, validation: !!run.validation, dry_run: !!run.dry_run });
    state.viewing = false;
    loadRun();
  } catch (e) { alertInline($("#needs"), e.message); }
}

function renderEvent(e) {
  if (e.kind === "audit") {
    return `<details class="ev"><summary>${esc(e.t)} Page ${e.step}, revision ${e.round} — ${e.ok ? "verified" : "needs revision"} (${e.fields.length} fields)</summary>
      <table class="grid"><thead><tr><th>Extracted question</th><th>Expected answer</th><th>Page value</th><th>Result</th></tr></thead><tbody>${e.fields.map((f) => `<tr><td>${esc(f.label || "(unidentified)")}${f.required ? " *" : ""}
        ${[f.label_source, f.context?.group, f.context?.instructions,
            f.context?.parent && `Follow-up to “${f.context.parent.question}” — ${f.context.parent.answer}`]
          .filter(Boolean).map((t) => `<div class="muted">${esc(t)}</div>`).join("")}</td>
        <td>${esc(f.expected ?? "Not set by jobbot")}${f.answer_source ? `<div class="muted">${esc(f.answer_source)}</div>` : ""}</td><td>${esc(f.actual)}</td><td>${esc(f.status)}</td></tr>`).join("")}</tbody></table>
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
  const hosted = Boolean(state.summary?.account);
  if (!p) {
    const run = state.run;
    box.innerHTML = run && ["starting", "running"].includes(run.status)
      ? `<div class="empty">Working… Jobbot is filling and checking the page in ${hosted ? "hosted Chromium" : "Chrome"}.</div>` : "";
    box.dataset.pid = "";
    return;
  }
  if (box.dataset.pid === p.id) return;   // keep what you are typing while polling
  box.dataset.pid = p.id;
  const q = `<div class="q">${esc(p.question || "")}</div>`;
  let html = "";
  if (p.kind === "action") {
    const labels = { submit: p.check_ok ? "Review and submit" : "Review unresolved issues", next: "Next step", refill: "Revise and re-check", done: "I submitted it myself", quit: "Quit without submitting" };
    // With problems open, re-checking is the safe default; Submit is only primary once every check passed.
    const primary = p.check_ok ? (p.final ? "submit" : "next") : "refill";
    const head = p.final && p.check_ok ? "Final step: every check passed" : p.check_ok ? "Review the page in Chrome" : "The check found problems";
    const job = currentJob();
    const audit = currentAudit();
    const problems = p.check_ok ? [] : (audit?.problems || []);
    const fields = (audit?.fields || []).filter((f) => f.label && !/password|verification code|one.time code/i.test(f.label) && f.kind !== "password");
    const review = fields.length ? `<details class="field-review"><summary>Review filled fields (${fields.length})</summary>
      <dl>${fields.map((f) => `<div><dt>${esc(f.label)}</dt><dd>${esc(f.actual || "Blank")}${f.answer_source ? ` <span class="pill">${esc(f.answer_source)}</span>` : ""}</dd></div>`).join("")}</dl></details>` : "";
    const hint = hosted
      ? (p.dry_run ? "Review the filled fields and page preview. Nothing will be submitted."
                   : "Review the filled fields and page preview before continuing.")
      : p.final && p.check_ok
      ? (p.dry_run ? "Dry run: this is the last page and nothing will be submitted. Look it over in Chrome, then quit." : "Look over the application in jobbot's Chrome window, then submit.")
      : problems.length ? "Fix these in jobbot's Chrome window, or correct a field below, then re-check:" : "Look over the page in jobbot's Chrome window, then choose:";
    html = `<div class="prompt ${p.final && p.check_ok ? "final" : ""}"><h4>${esc(head)}</h4>
      ${job ? `<div class="prompt-job">${esc(job.company)} — ${esc(job.title)}</div>` : ""}
      <div class="q">${hint}</div>
      ${problems.length ? `<ul class="problems">${problems.slice(0, 8).map((l) => `<li>${esc(l.replace(/^page says: /, ""))}</li>`).join("")}</ul>` : ""}
      ${review}
      <div class="actions">${p.choices.filter((c) => !(p.dry_run && ["done", "submit"].includes(c))).map((c) =>
        `<button ${c === "submit" ? 'data-submit-review' : `data-answer="${esc(c)}"`} class="${c === primary ? "primary" : ""}">${esc(labels[c] || c)}</button>`).join("")}</div>
      ${!p.dry_run && p.choices.includes("submit") ? `<div class="workspace-notice submit-review" data-submit-confirm hidden>
        <div><strong>Submit this application?</strong><p>${p.check_ok ? "This sends one application to the employer." : "Some checks have not passed. Confirm only if you reviewed the employer page and want to send it."}</p></div>
        <div class="actions"><button data-submit-back>Back to review</button><button class="primary" data-answer="submit">Confirm submission</button></div>
      </div>` : ""}
      ${p.dry_run ? `<p class="reason">Dry run: submitting is disabled.</p>` : ""}</div>`;
  } else if (p.kind === "confirm") {
    html = `<div class="prompt"><h4>Confirm</h4>${q}<div class="actions"><button class="primary" data-answer="true">Yes</button><button data-answer="false">No</button><button data-answer="skip">Skip this role</button></div></div>`;
  } else if (p.kind === "wait" && p.interactive) {
    html = `<div class="prompt"><h4>Browser needs your input</h4>${q}<p>Use Take control below, then return control to Jobbot.</p><div class="actions"><button data-answer="skip">Skip this role</button></div></div>`;
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
    const fields = (currentAudit()?.fields || []).filter((f) =>
      ["text", "textarea", "select", "radio", "yesno"].includes(f.kind) && f.label &&
      !/consent|agree|terms|certify|gender|race|ethnic|veteran|disability|signature|password|verification code|security code|one.time|\botp\b/i.test(f.label));
    const needsAttention = (f) => /needs revision|required, empty|question unclear/.test(f.status || "");
    fields.sort((a, b) => Number(needsAttention(b)) - Number(needsAttention(a)));
    if (fields.length) {
      html += `<details class="prompt correction-panel">
        <summary>Edit a field</summary>
        <div class="correction-editor">
          <label for="correction-field">Field</label>
          <select id="correction-field">${fields.map((f, i) => `<option value="${i}">${esc(f.label)}${needsAttention(f) ? " · Needs review" : ""}</option>`).join("")}</select>
          <label for="correction-value">Answer</label>
          <div id="correction-control"></div>
          <div class="actions"><button type="button" class="primary" data-correct>Save and re-check</button>
            <span id="correction-status" role="status"></span></div>
        </div>
      </details>`;
    }
    state.correctionFields = fields;
  }
  box.innerHTML = html;
  if ($("#correction-field", box)) renderCorrection();
  const input = $("#p-text", box);
  if (input) input.focus();
}

function renderCorrection() {
  const field = state.correctionFields[Number($("#correction-field").value)];
  const control = ["select", "radio", "yesno"].includes(field.kind)
    ? `<select id="correction-value">${[...new Set([field.actual || "", ...(field.options || [])])].map((option) =>
      `<option value="${esc(option)}">${esc(option || "Choose an answer")}</option>`).join("")}</select>`
    : field.kind === "textarea"
    ? `<textarea id="correction-value" rows="3">${esc(field.actual)}</textarea>`
    : `<input id="correction-value" type="text" value="${esc(field.actual)}">`;
  $("#correction-control").innerHTML = control;
  $("#correction-status").textContent = "";
}

async function answerPrompt(raw) {
  const p = state.run && state.run.prompt;
  if (!p || (raw === "submit" && (p.dry_run || !p.choices?.includes("submit")))) return;
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
  if ($("#prompt").dataset.pid === p.id) {
    $("#prompt").innerHTML = '<p role="status">Answer sent to Jobbot…</p>';
  }
  await loadRun();
}

// ---------- applications ----------
async function loadApps(append = false) {
  const [sort, dir] = state.appSort;
  const params = new URLSearchParams({ q: $("#apps-q").value, status: $("#apps-status").value,
    page: "1", sort, direction: dir === 1 ? "asc" : "desc" });
  await loadTablePage("apps", params, append, (page) => {
    state.apps = page.rows;
    renderApps();
  });
}

function renderApps() {
  const rows = state.appsPage?.paged ? state.apps : sortRows(state.apps, state.appSort);
  markSorted($("#apps-table"), state.appSort);
  $("#apps-count").textContent = state.appsPage?.next_offset != null ? `${rows.length} of ${state.appsPage.total} applications` : `${rows.length} application${rows.length === 1 ? "" : "s"}`;
  $("#apps-table tbody").innerHTML = rows.length ? rows.map((a) => `<tr class="clickable" data-app="${a.id}">
      <td class="num">${a.id}</td><td>${esc(a.company)}</td>
      <td class="role">${a.url ? `<a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a>` : esc(a.title)}
        ${a.notes ? `<div class="reason">${esc(a.notes).slice(0, 140)}</div>` : ""}</td>
      <td><span class="pill ${esc(a.status)}">${esc(a.status)}</span></td>
       <td>${a.resume ? esc(a.resume) : `<span class="muted" title="No resume recorded for this application">Not recorded</span>`}</td>
      <td class="num">${esc(a.applied_on || "")}</td><td class="num">${esc((a.updated_on || "").slice(0, 10))}</td>
      <td>${esc(a.source || "")}</td></tr>`).join("")
    : `<tr><td colspan="8" class="empty">No applications yet.</td></tr>`;
}

async function openApp(id) {
  const a = await api("applications/" + id);
  const statuses = state.summary.statuses.map((s) => `<option ${s === a.status ? "selected" : ""}>${esc(s)}</option>`).join("");
  const history = a.events.map((e) => `<li>${esc(e.at.replace("T", " "))} · <b>${esc(e.status)}</b> ${esc(e.note || "")}</li>`).join("");
  openDialog(`<h2>${esc(a.company)} — ${esc(a.title)}</h2>
    <div class="muted">${esc(a.location || "")} ${a.applied_on ? "· applied " + esc(a.applied_on) : ""} · via ${esc(a.source || "?")}</div>
    ${a.url ? `<p><a href="${esc(a.url)}" target="_blank" rel="noopener">Open posting</a></p>` : ""}
    <div class="row"><label>Resume used</label><span>${a.resume ? esc(a.resume) : `<span class="muted">Not recorded</span>`}</span></div>
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
  try {
    if (name === "gmail-login" && state.summary?.account) {
      const r = await api("account/gmail/connect", {});
      location.assign(r.url);
      return;
    }
    await api("tasks/" + name, {});
  } catch (e) { alertInline($(`[data-task="${name}"]`)?.closest(".card") || $("#tasks"), e.message); }
  loadTasks();
}

const taskNames = {
  scan: "Job scan", rank: "Job ranking", refresh: "Refresh jobs",
  resumes: "Resume scan", "sync-gmail": "Gmail sync", "gmail-login": "Gmail sign-in",
};
const taskTime = new Intl.DateTimeFormat(undefined, {
  month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short",
});

function renderTask(t) {
  const activity = Object.values(t.activity || {});
  const scan = t.activity?.scan;
  const resumes = t.activity?.resumes?.resumes;
  const lines = t.lines.filter((line) => line.trim() && !line.startsWith("$ "));
  const latest = lines.at(-1);
  const status = {done: "Completed", failed: "Failed", running: "Running"}[t.status];
  const tone = {done: "applied", failed: "rejected", running: "interview"}[t.status];
  return `<div class="task" data-run-task="${esc(t.id)}">
    <div class="task-head"><div><b>${esc(taskNames[t.name] || t.name)}</b>
      <time class="when" datetime="${esc(t.started)}">${esc(taskTime.format(new Date(t.started)))}</time></div>
      <span class="pill ${tone}">${status}</span></div>
    <div class="task-body">
      ${activity.map((entry) => `<p>${esc(entry.summary)}</p>${entry.detail ? `<p>${esc(entry.detail)}</p>` : ""}`).join("")}
      ${t.status === "running" && !latest ? "<p>Starting…</p>" : ""}
      ${latest && (t.status !== "done" || !activity.length) ? `<p>${esc(latest)}</p>` : ""}
      ${scan?.jobs.length ? `<details data-task-detail="results"><summary>Scan results</summary>
        <ul class="task-results">${scan.jobs.map((job) => `<li><div><b>${esc(job.title)}</b>
        <small>${esc(job.company)} · ${esc(job.location)}${job.new ? " · New" : ""}</small></div>
        <span>${esc(job.experience)}</span></li>`).join("")}</ul>
        ${scan.total > scan.jobs.length ? `<p>Showing ${scan.jobs.length} of ${scan.total} matches.</p>` : ""}
        <button type="button" data-go="jobs">View Jobs</button></details>` : ""}
      ${resumes?.length ? `<details data-task-detail="resumes"><summary>Resume variants</summary>
        <ul>${resumes.map((key) => `<li>${esc(key)}</li>`).join("")}</ul></details>` : ""}
      ${lines.length ? `<details data-task-detail="output"><summary>Task output</summary>
        <pre>${esc(t.lines.join("\n"))}</pre></details>` : ""}
    </div></div>`;
}

async function loadTasks(strict = false) {
  if (state.loadingTasks) return;
  state.loadingTasks = true;
  try {
    const tasks = await api("tasks");
    const id = (detail) => detail.closest("[data-run-task]").dataset.runTask + ":" + detail.dataset.taskDetail;
    const root = $("#tasks");
    const open = new Map($$("details[open]", root).map((d) => [id(d), d.querySelector("pre")?.scrollTop]));
    const focused = document.activeElement?.closest("details");
    const focusKey = focused && root.contains(focused) && document.activeElement.matches("summary") ? id(focused) : null;
    const markup = tasks.length ? tasks.map(renderTask).join("") : '<div class="empty">No recent activity.</div>';
    if (state.taskMarkup !== markup) {
      root.innerHTML = markup;
      state.taskMarkup = markup;
      $$("details", root).forEach((detail) => {
        detail.open = open.has(id(detail));
        if (detail.open && detail.querySelector("pre")) detail.querySelector("pre").scrollTop = open.get(id(detail)) || 0;
        if (id(detail) === focusKey) detail.querySelector("summary").focus({preventScroll: true});
      });
    }
    root.querySelector(":scope > .err")?.remove();
    renderRefresh(tasks);
    const active = tasks.filter((t) => t.status === "running").map((t) => t.name);
    const jobTasks = ["scan", "rank", "refresh"];
    $$("[data-task]").forEach((button) => {
      const name = button.dataset.task;
      button.disabled = active.includes(name) ||
        (jobTasks.includes(name) && active.some((task) => jobTasks.includes(task))) ||
        (name === "sync-gmail" && (!state.summary?.gmail || active.includes("refresh")));
    });
    if (active.length && !state.polling) state.polling = setInterval(loadTasks, 1500);
    if (!active.length && state.polling) {
      clearInterval(state.polling);
      state.polling = null;
      await loadSummary();
      if (state.tab === "jobs") await loadJobs();
    }
  } catch (e) {
    if (strict) throw e;
    alertInline($("#tasks"), e.message);
  } finally {
    state.loadingTasks = false;
  }
}

// The Jobs tab's "Refresh jobs" = scan + rank. Shows the latest such task's progress.
function renderRefresh(tasks) {
  const t = tasks.find((x) => ["refresh", "scan", "rank"].includes(x.name));
  const el = $("#refresh-status"), btn = $("#jobs-refresh");
  const busy = t && t.status === "running";
  btn.disabled = Boolean(busy || tasks.some((task) => task.name === "sync-gmail" && task.status === "running"));
  const steps = { track: ["Syncing Gmail…", "Reading application emails"], scan: ["Scanning…", "Scanning job boards"], rank: ["Ranking…", "Ranking new roles"] };
  const order = t && t.name === "refresh" ? ["track", "scan", "rank"] : [];
  const [short, long] = (t && steps[t.step]) || steps.scan;
  const of = order.includes(t && t.step) ? ` (${order.indexOf(t.step) + 1}/3)` : "";
  btn.textContent = busy ? short : "Refresh jobs";
  if (!t) { el.hidden = true; return; }
  const last = (t.status === "done" && Object.values(t.activity || {}).at(-1)?.summary) ||
    t.lines.filter((l) => l.trim() && !l.startsWith("$ ")).at(-1) || "";
  el.hidden = false;
  el.className = "refresh-status " + (t.status === "failed" ? "bad" : "");
  el.textContent = busy ? `${long}${of}… ${last}`
    : t.status === "failed" ? `${t.name} failed: ${last} (details in Actions)`
    : `Last ${t.name} finished ${t.ended ? taskTime.format(new Date(t.ended)) : ""}. ${last}`;
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
  }).join("\n") || (q ? "No log lines match this filter." : state.summary?.account
    ? "Open Runs for hosted browser activity, or Actions for background task output."
    : "No log lines yet. Application runs write here as they fill applications.");
}

// ---------- profile and resume library ----------
function setAccountProfile(hosted) {
  $("#account-resume").hidden = !hosted;
  $("#local-profile-heading").hidden = hosted;
  $("#local-profile-hint").hidden = hosted;
  $("#profile-editor-heading").textContent = hosted ? "Advanced settings · Profile YAML" : "Profile YAML";
  if (state.profileHosted !== hosted) $("#profile-advanced").open = !hosted;
  state.profileHosted = hosted;
}

function applyProfile(p) {
  state.profileMtime = p.mtime;
  state.savedProfile = p.text;
  state.resumeKeys = p.resume_keys || [];
  $("#profile-text").value = p.text;
}

function resumeNotice(message, failed = false) {
  const box = $("#resume-list-msg");
  box.hidden = !message;
  box.textContent = message || "";
  box.classList.toggle("resume-error", failed);
}

async function loadProfile(strict = false) {
  try {
    const p = await api("profile");
    setAccountProfile(Array.isArray(p.resume_keys));
    $("#profile-path").textContent = p.path;
    // Switching tabs must not discard unsaved edits.
    if (state.savedProfile === undefined || $("#profile-text").value === state.savedProfile) applyProfile(p);
    if (state.profileHosted && !await loadResumeKeys() && strict) throw new Error("Resume library unavailable.");
  } catch (e) {
    if (strict) throw e;
    $("#profile-msg").textContent = e.message;
    if (state.profileHosted) resumeNotice(e.message, true);
  }
}

async function saveProfile() {
  if (state.resumeBusy) return;
  const msg = $("#profile-msg"), text = $("#profile-text").value;
  state.resumeBusy = true;
  $("#profile-save").disabled = true;
  try {
    const r = await api("profile", { text, mtime: state.profileMtime });
    state.profileMtime = r.mtime;
    state.savedProfile = text;
    if (Array.isArray(r.resume_keys)) {
      state.resumeKeys = r.resume_keys;
      renderResumeKeys();
    }
    msg.textContent = "Saved.";
    msg.style.color = "var(--good)";
  } catch (e) {
    msg.textContent = e.message;
    msg.style.color = "var(--bad)";
  } finally {
    state.resumeBusy = false;
    $("#profile-save").disabled = false;
  }
}

async function loadResumeKeys() {
  try {
    const r = await api("account/resumes");
    state.uploadedResumes = r.resumes || r.keys.map(key => ({ key }));
    renderResumeKeys();
    return true;
  } catch (e) {
    resumeNotice("Could not refresh the resume library. " + e.message, true);
    return false;
  }
}

function resumeName(key) {
  return key.replace(/[_-]+/g, " ").replace(/\b\w/g, letter => letter.toUpperCase());
}

function renderResumeKeys() {
  const uploaded = new Map((state.uploadedResumes || []).map(item => [item.key, item]));
  const configured = new Set(state.resumeKeys || []);
  const keys = [...new Set([...uploaded.keys(), ...configured])].sort();
  $("#resume-count").textContent = `${uploaded.size} uploaded · ${[...uploaded.keys()].filter(k => configured.has(k)).length} used for ranking`;
  $("#resume-list").innerHTML = keys.map(key => {
    const active = configured.has(key), file = uploaded.get(key), name = file?.name || resumeName(key);
    const status = !file ? "missing" : active ? "active" : "ready";
    return `<li class="resume-row" data-key="${esc(key)}">
      <div class="resume-identity"><span class="resume-file-icon" aria-hidden="true">PDF</span><div>
        <strong>${esc(name)}</strong><code>${esc(key)}</code></div></div>
      <span class="resume-badge ${status}">${!file ? "PDF missing" : active ? "Used for ranking" : "Uploaded only"}</span>
      <div class="resume-actions">
        ${file ? `${active ? "" : '<button class="link" type="button" data-action="add">Use for ranking</button>'}<button type="button" data-action="view">View PDF</button>`
                 : '<button type="button" data-action="upload">Upload PDF</button>'}
        <details class="resume-more"><summary aria-label="More actions for ${esc(name)}">⋯</summary><div class="resume-menu">
          ${file ? '<button type="button" data-action="rename">Rename</button><button type="button" data-action="copy">Copy to new key</button>' : ""}
          ${active ? '<button type="button" data-action="remove">Remove from ranking</button>' : ""}
          ${file ? '<button type="button" class="resume-danger" data-action="delete">Delete PDF</button>' : ""}
        </div></details>
      </div></li>`;
  }).join("") || '<li class="resume-empty"><strong>No resumes yet</strong><span>Upload a PDF to start ranking jobs.</span></li>';
}

function openResumeDialog(title, description, fields, label, action) {
  const dialog = $("#resume-dialog");
  $("#resume-dialog-title").textContent = title;
  $("#resume-dialog-description").textContent = description;
  $("#resume-dialog-fields").innerHTML = fields;
  $("#resume-dialog-error").hidden = true;
  $("#resume-dialog-submit").textContent = label;
  $("#resume-dialog-submit").classList.toggle("danger", label === "Delete PDF");
  state.resumeSubmit = action;
  dialog.showModal();
}

function resumeFields(name = "", key = "") {
  return `<label>Display name<input name="display" type="text" required maxlength="80" value="${esc(name)}"></label>
    <label>Resume key<input name="key" type="text" required maxlength="48" pattern="[A-Za-z0-9_\\-]{1,48}" value="${esc(key)}">
    <small>Letters, numbers, underscores, or dashes.</small></label>`;
}

function requireSavedProfile() {
  if ($("#profile-text").value !== state.savedProfile) {
    $("#profile-advanced").open = true;
    throw new Error("Save your Profile YAML changes first, then try again.");
  }
}

async function finishResumeChange(r, message, reload = true) {
  if (typeof r.text === "string") {
    if ($("#profile-text").value === state.savedProfile) applyProfile(r);
    else {
      state.profileMtime = null;
      r.warning = "Profile changed while you were editing. Copy your edits and reload before saving.";
    }
  }
  if (reload && !await loadResumeKeys()) return;
  if (!reload) renderResumeKeys();
  resumeNotice(r.warning || message, !!r.warning);
}

function openResumeUpload(key = "") {
  const item = (state.uploadedResumes || []).find(x => x.key === key);
  openResumeDialog("Upload PDF", "Choose a PDF up to 5 MiB. Review the name and key before saving.",
    `<label>PDF file<input name="pdf" type="file" accept=".pdf,application/pdf" required></label>
    ${resumeFields(item?.name || (key ? resumeName(key) : ""), key)}
    <label class="resume-check"><input name="ranking" type="checkbox" checked> Use for ranking</label>
    <label class="resume-check" id="resume-replace" hidden><input name="replace" type="checkbox"> Replace the PDF already stored under this key</label>`,
    "Upload PDF", async f => {
      const file = f.get("pdf"), target = f.get("key").trim();
      if (!f.get("display").trim()) throw new Error("Enter a display name.");
      if (!file?.size || file.size > 5 * 1024 * 1024) throw new Error("Choose a PDF up to 5 MiB.");
      if (f.has("ranking")) requireSavedProfile();
      const current = (state.uploadedResumes || []).find(x => x.key === target);
      if (current && !f.has("replace")) {
        $("#resume-replace").hidden = false;
        throw new Error("That key already has a PDF. Confirm replacement or choose a different key.");
      }
      const bytes = new Uint8Array(await file.arrayBuffer());
      const chunks = [];
      for (let i = 0; i < bytes.length; i += 8192) chunks.push(String.fromCharCode(...bytes.subarray(i, i + 8192)));
      const result = await api("account/resume", { key: target, name: f.get("display").trim(), pdf: btoa(chunks.join("")),
        use_for_ranking: f.has("ranking"), mtime: state.profileMtime, replace_version: current?.version || "" });
      await finishResumeChange(result, current ? "PDF replaced." : "PDF uploaded.");
    });
  const form = $("#resume-form");
  form.elements.key.addEventListener("input", () => {
    form.elements.replace.checked = false;
    $("#resume-replace").hidden = true;
  });
  form.elements.pdf.addEventListener("change", () => {
    const filename = form.elements.pdf.files[0]?.name.replace(/\.pdf$/i, "");
    if (!filename) return;
    if (!form.elements.display.value) form.elements.display.value = filename.replace(/[_-]+/g, " ").slice(0, 80);
    if (!form.elements.key.value) form.elements.key.value = filename.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 48);
  });
}

async function changeResume(event) {
  const action = event.target.closest("[data-action]")?.dataset.action;
  if (!action || state.resumeBusy) return;
  const key = event.target.closest("[data-key]").dataset.key;
  const item = (state.uploadedResumes || []).find(x => x.key === key);
  const name = item?.name || resumeName(key);
  const active = (state.resumeKeys || []).includes(key);
  const menu = event.target.closest(".resume-more");
  if (menu) menu.open = false;
  resumeNotice("");
  if (action === "view") {
    const url = "/resume-file/" + encodeURIComponent(key);
    $("#resume-preview-title").textContent = name;
    $("#resume-preview-frame").src = url;
    $("#resume-download").href = url + "?download=1";
    $("#resume-download").download = key + ".pdf";
    $("#resume-preview").showModal();
    return;
  }
  if (action === "upload") return openResumeUpload(key);
  if (action === "rename" || action === "copy") {
    const copy = action === "copy";
    return openResumeDialog(copy ? "Copy resume" : "Rename resume",
      copy ? "Keep the original and create a copy under a new key." : "The display name is shown in the library. The key identifies the resume in your profile.",
      resumeFields(name, copy ? "" : key), copy ? "Copy PDF" : "Save changes", async f => {
        const target = f.get("key").trim(), display = f.get("display").trim();
        if (!display) throw new Error("Enter a display name.");
        if (copy && target === key) throw new Error("Choose a different key for the copy.");
        if (!copy && target !== key) requireSavedProfile();
        const body = copy ? { source: key, key: target, name: display } :
          { action: "rename", key, target, name: display, mtime: state.profileMtime };
        const r = await api(copy ? "account/resume/copy" : "account/resume/profile", body);
        await finishResumeChange(r, copy ? "PDF copied. Choose Use for ranking to enable the copy." : "Renamed to " + display + ".");
      });
  }
  if (action === "delete") {
    return openResumeDialog("Delete PDF?", `${name} will be permanently deleted${active ? " and removed from ranking" : ""}. Past applications are unchanged.`,
      "", "Delete PDF", async () => {
        requireSavedProfile();
        const r = await api("account/resume/delete", { key, mtime: state.profileMtime, confirm: true,
          version: item?.version, remove_from_ranking: active });
        await finishResumeChange(r, "PDF deleted.");
      });
  }
  state.resumeBusy = true;
  const button = event.target.closest("button");
  button.disabled = true;
  try {
    requireSavedProfile();
    const r = await api("account/resume/profile", { key, action, mtime: state.profileMtime });
    await finishResumeChange(r, action === "add" ? "Resume is now used for ranking." : "Removed from ranking. The PDF was kept.", false);
  } catch (e) {
    resumeNotice(e.message, true);
  } finally {
    button.disabled = false;
    state.resumeBusy = false;
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
  if (target) target.scrollIntoView({ block: "start" });
}

// ---------- wiring ----------
document.addEventListener("DOMContentLoaded", async () => {
  wireLivePreview();
  $("#account-signout").addEventListener("click", async () => {
    try { await api("account/logout", {}); location.replace("/"); }
    catch (e) { alertInline($("#status"), e.message); }
  });
  $("#gmail-disconnect").addEventListener("click", async () => {
    if (!confirm("Disconnect Gmail and revoke Jobbot’s access?")) return;
    try { await api("account/gmail/disconnect", {}); await loadSummary(); }
    catch (e) { alertInline($("#gmail-text"), e.message); }
  });
  $("#resume-list").addEventListener("click", changeResume);
  $("#resume-upload-open").addEventListener("click", () => { if (!state.resumeBusy) openResumeUpload(); });
  document.addEventListener("click", event => {
    $$(".resume-more[open]").forEach(menu => { if (!menu.contains(event.target)) menu.open = false; });
  });
  $("#resume-list").addEventListener("keydown", event => {
    if (event.key !== "Escape") return;
    const menu = event.target.closest(".resume-more[open]");
    if (menu) { menu.open = false; menu.querySelector("summary").focus(); }
  });
  $("#resume-dialog-close").addEventListener("click", () => $("#resume-dialog").close());
  $("#resume-dialog").addEventListener("cancel", e => { if (state.resumeBusy) e.preventDefault(); });
  $("#resume-preview-close").addEventListener("click", () => $("#resume-preview").close());
  $("#resume-preview").addEventListener("close", () => $("#resume-preview-frame").removeAttribute("src"));
  $("#resume-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (state.resumeBusy) return;
    const form = event.currentTarget, error = $("#resume-dialog-error");
    state.resumeBusy = true;
    $("#resume-dialog-submit").disabled = $("#resume-dialog-close").disabled = true;
    error.hidden = true;
    try {
      await state.resumeSubmit(new FormData(form));
      $("#resume-dialog").close();
    } catch (e) {
      error.hidden = false;
      error.textContent = e.message;
    } finally {
      state.resumeBusy = false;
      $("#resume-dialog-submit").disabled = $("#resume-dialog-close").disabled = false;
    }
  });
  const tabs = $$(".tabs [role=tab]");
  tabs.forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  $(".tabs").addEventListener("keydown", (event) => {
    const current = tabs.indexOf(event.target);
    if (current < 0) return;
    const vertical = getComputedStyle($(".tabs")).flexDirection === "column";
    const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
      : event.key === (vertical ? "ArrowDown" : "ArrowRight") ? (current + 1) % tabs.length
      : event.key === (vertical ? "ArrowUp" : "ArrowLeft") ? (current - 1 + tabs.length) % tabs.length : -1;
    if (next < 0) return;
    event.preventDefault();
    tabs[next].click();
    tabs[next].focus();
  });
  $("main").addEventListener("click", (event) => {
    const link = event.target.closest("button[data-go]");
    if (!link) return;
    showTab(link.dataset.go);
    tabs.find((tab) => tab.dataset.tab === link.dataset.go)?.focus();
  });
  const tableAction = (name, load) => load().catch((error) => alertInline($("#" + name + "-page-controls"), error.message));
  const reloadJobs = debounce(() => tableAction("jobs", loadJobs));
  $("#jobs-more").addEventListener("click", () => tableAction("jobs", () => loadJobs(true)));
  $("#apps-more").addEventListener("click", () => tableAction("apps", () => loadApps(true)));
  ["#jobs-q", "#jobs-min"].forEach((s) => $(s).addEventListener("input", reloadJobs));
  $("#notdup-selected").addEventListener("click", markNotDuplicates);
  $("#jobs-views").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-view]");
    if (b) { state.view = b.dataset.view; tableAction("jobs", loadJobs); }
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
  $("#prompt").addEventListener("change", (ev) => {
    if (ev.target.id === "correction-field") renderCorrection();
  });
  $("#prompt").addEventListener("click", async (ev) => {
    const review = ev.target.closest("[data-submit-review], [data-submit-back]");
    if (review) {
      const confirm = $("[data-submit-confirm]", $("#prompt"));
      confirm.hidden = review.hasAttribute("data-submit-back");
      (confirm.hidden ? $("[data-submit-review]", $("#prompt")) : $("[data-submit-back]", confirm)).focus();
      return;
    }
    const b = ev.target.closest("button[data-answer]");
    if (b) answerPrompt(b.dataset.answer);
    const correction = ev.target.closest("button[data-correct]");
    if (correction) {
      const p = state.run?.prompt;
      if (!p) return;
      const picker = $("#correction-field");
      const input = $("#correction-value");
      const status = $("#correction-status");
      const field = state.correctionFields[Number(picker.value)];
      const controls = $$("#prompt button, #prompt select, #prompt input, #prompt textarea").filter((el) => !el.disabled);
      controls.forEach((el) => { el.disabled = true; });
      status.textContent = "Saving and re-checking…";
      try {
        await api("apply/answer", {prompt_id: p.id, value: {action: "correct", field: field.id, value: input.value}});
        await loadRun();
      } catch (error) {
        status.textContent = error.message;
        controls.forEach((el) => { el.disabled = false; });
      }
    }
  });
  $("#run-stop").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await api("apply/stop", {});
      await loadRun();
    } catch (error) {
      alertInline($("#run-stop").parentElement, error.message);
    } finally {
      button.disabled = false;
    }
  });
  $("#jobs-table tbody").addEventListener("click", async (ev) => {
    const b = ev.target.closest("button[data-job]");
    if (!b) return;
    await api(`jobs/${b.dataset.job}/${b.dataset.act}`, {});
    await Promise.all([loadJobs(), loadSummary()]);
  });
  $("#apps-q").addEventListener("input", debounce(() => tableAction("apps", loadApps)));
  $("#apps-status").addEventListener("change", () => tableAction("apps", loadApps));
  $("#apps-add").addEventListener("click", addApp);
  $("#apps-table tbody").addEventListener("click", (ev) => {
    if (ev.target.closest("a")) return;
    const tr = ev.target.closest("tr[data-app]");
    if (tr) openApp(tr.dataset.app);
  });
  for (const [name, key, load] of [["jobs", "jobSort", loadJobs], ["apps", "appSort", loadApps]]) {
    const table = "#" + name + "-table";
    $$(`${table} th[data-sort]`).forEach((th) => th.addEventListener("click", () => {
      const [cur, dir] = state[key];
      state[key] = [th.dataset.sort, cur === th.dataset.sort ? -dir : -1];
      tableAction(name, load);
    }));
  }
  $$("[data-task]").forEach((b) => b.addEventListener("click", () => startTask(b.dataset.task)));
  $("#jobs-refresh").addEventListener("click", () => startTask("refresh"));
  $("#run-strip").addEventListener("click", (ev) => { if (ev.target.closest("[data-view-run]")) { state.viewing = false; showTab("apply"); } });
  $("#tab-apply").addEventListener("click", async (ev) => {
    const r = ev.target.closest("[data-retry]"), all = ev.target.closest("[data-retry-all]");
    const item = ev.target.closest("[data-run]"), remove = ev.target.closest("[data-delete-run]");
    if (r) retry([r.dataset.retry]);
    if (all) retry(all.dataset.retryAll.split("\n"));
    if (ev.target.closest("#run-current")) {
      state.viewing = false;
      await loadRun();
    }
    if (item || remove) {
      historyMessage("");
      try {
        if (item && !runActive(state.run?.status)) {
          const saved = await api("runs/" + encodeURIComponent(item.dataset.run));
          if (runActive(state.run?.status)) return;
          state.viewing = saved.id;
          renderRun(saved);
          renderHistory();
          $("#run-title").scrollIntoView({block: "nearest"});
        }
        if (remove) {
          const id = remove.dataset.deleteRun;
          if (!window.confirm("Delete this run from history? Tracked applications will be kept.")) return;
          remove.disabled = true;
          await api("runs/" + encodeURIComponent(id) + "/delete", {});
          if (state.viewing === id) state.viewing = false;
          await loadHistory();
          await loadRun();
          $("#history").querySelector("[data-run]:enabled")?.focus({preventScroll: true});
          historyMessage("Run deleted.");
        }
      } catch (e) {
        if (remove) remove.disabled = false;
        historyMessage(e.message);
      }
    }
  });
  $("#tab-docs").addEventListener("click", (ev) => {
    const a = ev.target.closest("a[data-doc], a[data-anchor]");
    if (!a) return;
    ev.preventDefault();
    if (a.dataset.doc) loadPage("docs", "documentation", () => loadDocs(a.dataset.doc, a.dataset.anchor));
    else document.getElementById(a.dataset.anchor)?.scrollIntoView({ block: "start" });
  });
  $("#logs-date").addEventListener("change", () => loadLogs($("#logs-date").value));
  $("#logs-q").addEventListener("input", debounce(renderLogs, 150));
  $("#profile-save").addEventListener("click", saveProfile);

  showTab(tabs.some((tab) => tab.dataset.tab === recall("tab")) ? recall("tab") : "jobs");   // before any await, so a tab you click while it loads stays chosen
  loadSummary().catch(() => { $("#status").textContent = "Workspace status unavailable."; });
  if (state.tab !== "apply") loadRun();
  // Keeps the counts fresh and notices a restarted or stopped dashboard even when nothing else polls.
  setInterval(() => { if (!document.hidden) loadSummary().catch(() => {}); }, 30000);   // picks up a run that is already in progress (and keeps polling while it is)
});
