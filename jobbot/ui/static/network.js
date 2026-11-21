"use strict";
// Dashboard API transport and connection-status handling.
(() => {
  const TOKEN = document.querySelector('meta[name="jobbot-token"]').content;
async function api(path, body) {
  const opts = { headers: { "X-Jobbot-Token": TOKEN } };
  if (body !== undefined) {
    opts.method = "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res, data;
  try {
    res = await fetch("/api/" + path, opts);
    data = await res.json();
  } catch (e) {
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
  if (!res.ok) throw Object.assign(new Error(data.error || res.statusText), {status: res.status});
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

  window.JobbotNetwork = Object.freeze({ api, connection });
})();
