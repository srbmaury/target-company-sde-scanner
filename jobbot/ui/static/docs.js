"use strict";
(() => {
  const { esc } = window.JobbotHtml;
  const { api } = window.JobbotNetwork;
  const $ = (selector) => document.querySelector(selector);

  let activePage = "README";
  let docsIndex;

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

  async function loadDocs(name = activePage, anchor = "") {
    if (!docsIndex) docsIndex = await api("docs");
    $("#docs-nav").innerHTML = docsIndex.map((p) =>
      `<a href="#" data-doc="${esc(p.name)}" class="${p.name === name ? "on" : ""}">${esc(p.title)}</a>`).join("");
    const page = await api("docs/" + encodeURIComponent(name));
    activePage = name;
    $("#docs-page").innerHTML = md(page.text);
    const target = anchor && document.getElementById(anchor);
    if (target) target.scrollIntoView({ block: "start" });
  }

  function wireDocs() {
    $("#tab-docs").addEventListener("click", (ev) => {
      const a = ev.target.closest("a[data-doc], a[data-anchor]");
      if (!a) return;
      ev.preventDefault();
      if (a.dataset.doc) loadDocs(a.dataset.doc, a.dataset.anchor);
      else document.getElementById(a.dataset.anchor)?.scrollIntoView({ block: "start" });
    });
  }

  window.JobbotDocs = Object.freeze({ loadDocs, wireDocs });
})();
