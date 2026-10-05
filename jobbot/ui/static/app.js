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
  const res = await fetch("/api/" + path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
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
  ({ jobs: loadJobs, apply: loadRun, applications: loadApps, actions: loadTasks, logs: loadLogs, profile: loadProfile }[name])();
}

// ---------- summary ----------
async function loadSummary() {
  const s = (state.summary = await api("summary"));
  const a = s.applications;
  const cards = [
    ["Open roles", s.open_jobs], ["Applications", s.total], ["Applied", a.applied || 0],
    ["Assessments", a.assessment || 0], ["Interviews", a.interview || 0], ["Offers", a.offer || 0],
    ["Rejected", a.rejected || 0], ["Response rate", s.response_rate + "%"],
  ];
  $("#stats").innerHTML = cards.map(([l, v]) => `<div class="stat"><div class="label">${esc(l)}</div><div class="value">${esc(v)}</div></div>`).join("");
  const dot = (ok) => `<span class="dot" style="background:${ok ? "var(--good)" : "var(--border)"}"></span>`;
  $("#status").innerHTML = `<span>${dot(s.gmail)}Gmail ${s.gmail ? "connected" : "not connected"}</span>
    <span>${dot(s.ollama)}Ollama ${s.ollama ? "running" : "off"}</span>`;
  $("#gmail-text").textContent = s.gmail
    ? "Import application emails into the tracker (read-only)."
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
    include_applied: $("#jobs-applied").checked ? "1" : "", include_dismissed: $("#jobs-dismissed").checked ? "1" : "",
  });
  state.jobs = await api("jobs?" + params);
  renderJobs();
}

function fitClass(f) { return f == null ? "" : f >= 80 ? "high" : f >= 60 ? "mid" : "low"; }

function renderJobs() {
  const rows = sortRows(state.jobs, state.jobSort);
  markSorted($("#jobs-table"), state.jobSort);
  $("#jobs-count").textContent = `${rows.length} role${rows.length === 1 ? "" : "s"}`;
  $("#jobs-table tbody").innerHTML = rows.length ? rows.map((j) => {
    const applied = j.applied === "exact" || j.applied === "likely"
      ? `<span class="pill applied" title="${esc(j.applied_note)}">applied</span>`
      : j.applied === "possible" ? `<span class="pill maybe" title="${esc(j.applied_note)}">possibly applied</span>` : "";
    return `<tr class="${j.dismissed ? "dim" : ""}">
      <td class="num">${j.n}</td>
      <td><span class="fit ${fitClass(j.fit_score)}">${j.fit_score ?? "–"}</span></td>
      <td>${esc(j.company)}</td>
      <td class="role"><a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a> ${applied}
        ${j.fit_reason ? `<div class="reason">${esc(j.fit_reason)}</div>` : ""}</td>
      <td>${esc(j.location)}</td>
      <td class="num" title="${esc(j.evidence)}">${esc(j.experience)}</td>
      <td>${esc(j.fit_resume || "")}</td>
      <td class="num"><label class="check"><input type="checkbox" data-select="${j.n}" ${state.selected.has(String(j.n)) ? "checked" : ""} ${j.dismissed ? "disabled" : ""}> Select</label>
        <button class="link" data-job="${j.n}" data-act="${j.dismissed ? "restore" : "dismiss"}">${j.dismissed ? "Restore" : "Dismiss"}</button></td>
    </tr>`;
  }).join("") : `<tr><td colspan="8" class="empty">No roles match. Try Actions → Run scan.</td></tr>`;
  updateSelection();
}

// Roles "select all" picks: the ones shown, minus dismissed and already-applied roles (apply skips those anyway).
function selectable() {
  return state.jobs.filter((j) => !j.dismissed && j.applied !== "exact" && j.applied !== "likely").map((j) => String(j.n));
}

// ---------- selection & apply runs ----------
function updateSelection() {
  const n = state.selected.size;
  $("#sel-count").textContent = n ? `${n} role${n === 1 ? "" : "s"} selected` : "Select roles with the checkboxes to apply from here.";
  $("#apply-selected").disabled = $("#dry-selected").disabled = !n;
  $("#sel-clear").hidden = !n;
  const keys = selectable(), picked = keys.filter((k) => state.selected.has(k)).length;
  const all = keys.length > 0 && picked === keys.length;
  const box = $("#sel-all-box");
  box.checked = all;
  box.indeterminate = picked > 0 && !all;
  box.disabled = !keys.length;
  $("#sel-all").disabled = !keys.length || all;
  $("#sel-all").textContent = keys.length ? `Select all shown (${keys.length})` : "Select all shown";
}

function selectAll(on) {
  for (const k of selectable()) on ? state.selected.add(k) : state.selected.delete(k);
  renderJobs();
}

async function startRun(dry) {
  const jobs = Array.from(state.selected);
  const msg = `${dry ? "Dry-run" : "Apply to"} ${jobs.length} role${jobs.length === 1 ? "" : "s"}? Chrome will open in its own window.` +
    (dry ? "" : " You'll confirm each Submit here.");
  if (!confirm(msg)) return;
  try {
    await api("apply", { jobs, dry_run: dry });
    state.selected.clear(); updateSelection();
    showTab("apply");
  } catch (e) { alert(e.message); }
}

async function loadRun() {
  let run;
  try { run = await api("apply"); } catch (e) { return; }
  state.run = run;
  const active = ["starting", "running", "waiting"].includes(run.status);
  $("#apply-badge").hidden = run.status !== "waiting";
  document.title = run.status === "waiting" ? "● jobbot needs you" : "jobbot";
  if (active && !state.runPoll) state.runPoll = setInterval(loadRun, 1000);
  if (!active && state.runPoll) { clearInterval(state.runPoll); state.runPoll = null; loadSummary(); }
  if (state.tab === "apply") renderRun(run);
}

function renderRun(run) {
  if (run.status === "idle") {
    $("#run-title").textContent = "No apply run yet";
    $("#run-status").textContent = ""; $("#run-progress").textContent = "";
    $("#prompt").innerHTML = `<div class="empty">Select roles in the Jobs tab and choose “Apply to selected”.</div>`;
    $("#feed").innerHTML = ""; $("#queue").innerHTML = ""; $("#run-stop").hidden = true;
    return;
  }
  const active = ["starting", "running", "waiting"].includes(run.status);
  $("#run-title").textContent = run.dry_run ? "Dry run" : "Applying";
  $("#run-status").textContent = run.status;
  $("#run-status").className = "pill " + ({ waiting: "maybe", running: "interview", done: "applied", failed: "rejected", stopped: "withdrawn" }[run.status] || "");
  const done = Object.keys(run.results).length;
  $("#run-progress").textContent = run.jobs.length ? `${done} of ${run.jobs.length} finished` : "";
  $("#run-stop").hidden = !active;
  $("#queue").innerHTML = run.jobs.map((j, i) => {
    const r = run.results[j.url];
    const pill = r ? `<span class="pill ${r.status === "applied" ? "applied" : "rejected"}">${esc(r.status)}</span>` : i === run.current ? `<span class="pill interview">now</span>` : "";
    return `<li class="${i === run.current ? "now" : ""}">${esc(j.company)} ${pill}<span class="sub">${esc(j.title)}</span></li>`;
  }).join("");
  const feed = $("#feed");
  const nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 60;
  feed.innerHTML = run.events.map(renderEvent).join("");
  if (nearBottom) feed.scrollTop = feed.scrollHeight;
  renderPrompt(run.prompt);
}

function renderEvent(e) {
  if (e.kind === "report") {
    const items = e.filled.map((f) => `<li><b>${esc(f.label)}</b> → ${esc(f.value)} <span class="muted">${esc(f.source)}</span></li>`).join("");
    const probs = (e.problems || []).map((p) => `<li style="color:var(--bad)">${esc(p)}</li>`).join("");
    const status = e.ok === null ? "" : e.ok ? " · ✓ all checks passed" : " · ✗ problems found";
    return `<div class="ev report ${e.ok === false ? "bad" : ""}"><span class="t">${esc(e.t)}</span>${esc(e.text)} — ${e.filled.length} field(s) set${status}<ul>${items}${probs}</ul></div>`;
  }
  return `<div class="ev ${esc(e.kind)}"><span class="t">${esc(e.t)}</span>${esc(e.text)}</div>`;
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
    const labels = { submit: "Submit application", next: "Next step", refill: "Re-fill this page", done: "I submitted it myself", quit: "Quit without submitting" };
    const head = p.final ? "Final step: every check passed" : p.check_ok ? "Review the page in Chrome" : "The check found problems";
    html = `<div class="prompt ${p.final ? "final" : ""}"><h4>${esc(head)}</h4>
      <div class="q">${p.final ? "Look over the application in the Chrome window, then submit." : "Fix anything in the Chrome window if needed, then choose:"}</div>
      <div class="actions">${p.choices.map((c) => `<button data-answer="${c}" class="${c === "submit" ? "primary" : ""}">${esc(labels[c] || c)}</button>`).join("")}</div>
      ${p.dry_run ? `<p class="reason">Dry run: submitting is disabled.</p>` : ""}</div>`;
  } else if (p.kind === "confirm") {
    html = `<div class="prompt"><h4>Confirm</h4>${q}<div class="actions"><button class="primary" data-answer="true">Yes</button><button data-answer="false">No</button></div></div>`;
  } else if (p.kind === "wait") {
    html = `<div class="prompt"><h4>Your turn in Chrome</h4>${q}<div class="actions"><button class="primary" data-answer="null">Done, continue</button></div></div>`;
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
  try { await api("apply/answer", { prompt_id: p.id, value }); } catch (e) { alert(e.message); }
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
    <div class="row"><label>Status</label><select name="status">${statuses}</select></div>
    <div class="row"><label>Note for this change (optional)</label><input type="text" name="change_note" placeholder="e.g. system design round on Friday"></div>
    <div class="row"><label>Notes</label><textarea name="note" rows="3">${esc(a.notes || "")}</textarea></div>
    <div class="row"><label>History</label><ol class="history">${history}</ol></div>
    <div class="actions"><button value="cancel">Close</button><button class="primary" value="save">Save</button></div>`,
    async (form) => {
      if (form.status.value !== a.status) await api(`applications/${id}/status`, { status: form.status.value, note: form.change_note.value });
      if (form.note.value !== (a.notes || "")) await api(`applications/${id}/note`, { note: form.note.value });
      await Promise.all([loadApps(), loadSummary()]);
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
  try { await api("tasks/" + name, {}); } catch (e) { alert(e.message); }
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
  const running = tasks.some((t) => t.status === "running");
  $$("[data-task]").forEach((b) => (b.disabled = running && !b.dataset.task.startsWith("gmail") ? true : b.disabled));
  if (running && !state.polling) state.polling = setInterval(loadTasks, 1500);
  if (!running && state.polling) {
    clearInterval(state.polling);
    state.polling = null;
    $$("[data-task]").forEach((b) => (b.disabled = false));
    await loadSummary();
  }
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
}

async function saveProfile() {
  const msg = $("#profile-msg");
  try {
    await api("profile", { text: $("#profile-text").value });
    msg.textContent = "Saved."; msg.style.color = "var(--good)";
  } catch (e) {
    msg.textContent = e.message; msg.style.color = "var(--bad)";
  }
}

// ---------- wiring ----------
document.addEventListener("DOMContentLoaded", async () => {
  $$(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  const reloadJobs = debounce(loadJobs);
  ["#jobs-q", "#jobs-min"].forEach((s) => $(s).addEventListener("input", reloadJobs));
  ["#jobs-applied", "#jobs-dismissed"].forEach((s) => $(s).addEventListener("change", loadJobs));
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
  $("#sel-all-box").addEventListener("change", (ev) => selectAll(ev.target.checked));
  $("#prompt").addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-answer]");
    if (b) answerPrompt(b.dataset.answer);
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
  $("#logs-date").addEventListener("change", () => loadLogs($("#logs-date").value));
  $("#logs-q").addEventListener("input", debounce(renderLogs, 150));
  $("#profile-save").addEventListener("click", saveProfile);

  await loadSummary();
  showTab(recall("tab") || "jobs");
  loadRun();   // picks up a run that is already in progress (and keeps polling while it is)
});
