"use strict";
// Centralize HTML escaping and URL-scheme validation for rendered links.
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeHref = (value) => {
  try {
    const url = new URL(String(value), location.origin);
    return ["http:", "https:"].includes(url.protocol) ? esc(url.href) : "#";
  } catch { return "#"; }
};
window.JobbotHtml = Object.freeze({ esc, safeHref });
