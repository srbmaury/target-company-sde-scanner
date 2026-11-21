"use strict";
(() => {
  const { esc } = window.JobbotHtml;
  const { api } = window.JobbotNetwork;
  const $ = (selector) => document.querySelector(selector);

  let logLines = [];

  async function loadLogs(date, hosted) {
    const data = await api("logs?" + new URLSearchParams({ date: date || $("#logs-date").value || "" }));
    const sel = $("#logs-date");
    sel.innerHTML = data.dates.map((d) => `<option ${d === data.date ? "selected" : ""}>${esc(d)}</option>`).join("") || "<option value=''>No logs yet</option>";
    logLines = data.lines || [];
    renderLogs(hosted);
  }

  function renderLogs(hosted) {
    const q = $("#logs-q").value.toLowerCase();
    const lines = logLines.filter((l) => !q || l.toLowerCase().includes(q));
    $("#logs").innerHTML = lines.map((l) => {
      const cls = l.includes(" ! ") || /\s!\s/.test(l) ? "warn" : l.includes("===") ? "head" : "";
      return `<span class="${cls}">${esc(l)}</span>`;
    }).join("\n") || (q ? "No log lines match this filter." : hosted
      ? "Open Runs for hosted browser activity, or Actions for background task output."
      : "No log lines yet. Application runs write here as they fill applications.");
  }

  window.JobbotLogs = Object.freeze({ loadLogs, renderLogs });
})();
