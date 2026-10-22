import { h } from "../dom.js";
import { api } from "../api.js";
import { S } from "../state.js";
import { panel, empty } from "../components/panel.js";
import { field, toggle, textInput, previewBox, runButton, liveRunConfirm, form, schedulePreview } from "../forms.js";
import { toast } from "../components/toast.js";

const LINK_KEYS = [["site", "Site"], ["naukri", "Naukri listing"]];

function entryCard(entry) {
  const extra = Object.entries(entry).filter(([k]) => !["when", "company", "title", "name"].includes(k));
  return h(
    "li",
    { class: "panel", style: { marginBottom: "16px" } },
    h(
      "div",
      { class: "panel-head" },
      h("div", {}, h("h3", { class: "panel-title", text: entry.name || entry.title }), h("p", { class: "panel-sub", text: entry.when })),
      entry.status ? h("span", { class: "pill pill-accent", text: entry.status }) : null,
    ),
    entry.why ? h("p", { class: "muted small", style: { marginBottom: "12px" } }, entry.why) : null,
    h(
      "div",
      { class: "row", style: { flexWrap: "wrap", gap: "8px", marginBottom: "12px" } },
      LINK_KEYS.filter(([k]) => entry[k]).map(([k, label]) => h("a", { class: "btn btn-sm", href: entry[k], target: "_blank", rel: "noopener noreferrer", text: label })),
      entry["resume to send"]
        ? h("button", { class: "btn btn-sm", type: "button", text: "Open resume", onclick: () => openPath(entry["resume to send"]) })
        : null,
    ),
    extra
      .filter(([k]) => !LINK_KEYS.some(([lk]) => lk === k) && k !== "resume to send" && k !== "status" && k !== "why")
      .map(([k, v]) => h("p", { class: "small muted", text: `${k}: ${v}` })),
    h(
      "div",
      { class: "panel-foot" },
      h("button", { class: "btn btn-sm", type: "button", text: "Fill in this form", onclick: () => fillFrom(entry) }),
    ),
  );
}

function openPath(path) {
  api("/api/open", { what: "path", path }).catch((error) => toast(error.message, "error"));
}

function fillFrom(entry) {
  const values = form("external");
  values.url = entry.site || "";
  values.title = entry.title || "";
  values.company = entry.company || "";
  schedulePreview('external');
  document.getElementById("external-form")?.scrollIntoView({ behavior: "smooth", block: "start" });
  document.querySelectorAll("#external-form input").forEach((el) => {
    if (el.dataset.key === "url") el.value = values.url;
    if (el.dataset.key === "title") el.value = values.title;
    if (el.dataset.key === "company") el.value = values.company;
  });
}

export function renderSites() {
  const sites = S.status.sites;
  let shown = 10;
  const list = h('ul', { class: 'plain-list' });
  const summary = h('p', { class: 'small muted', role: 'status' });
  const more = h('button', { class: 'btn', type: 'button', text: 'Show more applications', onclick: () => { shown += 10; draw(); } });
  const search = h('input', { class: 'input', type: 'search', 'aria-label': 'Search company applications', placeholder: 'Search company, role or status…', value: S.siteQuery || '', oninput: event => { S.siteQuery = event.target.value; shown = 10; draw(); } });
  function draw() {
    const matches = sites.filter(entry => [entry.name, entry.title, entry.company, entry.status].join(' ').toLowerCase().includes((S.siteQuery || '').toLowerCase()));
    list.replaceChildren(...matches.slice(0, shown).map(entryCard));
    if (!matches.length) list.append(h('li', {}, empty('No applications match your search.')));
    summary.textContent = `Showing ${Math.min(shown, matches.length)} of ${matches.length} applications`;
    more.hidden = matches.length <= shown;
  }
  draw();
  return h(
    "div",
    { class: "page" },
    h("header", { class: "page-head" }, h("div", {}, h("h1", { text: "Company sites" }), h("p", { class: "lead", text: "Applications the bot started on a company’s own site and could not finish." }))),
    h(
      "div",
      { class: "dash" },
      h(
        "section",
        { class: "span-7" },
        sites.length
          ? h('div', {}, field('Find an application', search), h('div', { class: 'editor-toolbar' }, summary), list, more)
          : panel("Nothing waiting", {}, empty("No company-site applications need you right now.")),
      ),
      h(
        "div",
        { class: "span-5", id: "external-form" },
        panel(
          "Try a company site by hand",
          { sub: "Paste a link and the bot fills what it can." },
          field("Job URL", withKey(textInput("external", "url", { placeholder: "https://…" }), "url")),
          field("Title", withKey(textInput("external", "title", { placeholder: "Job title" }), "title")),
          field("Company", withKey(textInput("external", "company", { placeholder: "Company" }), "company")),
          toggle("external", "dry_run", "Dry run", "Fill the form without submitting it."),
          toggle("external", "no_tailor", "Skip resume tailoring", "Use the base resume instead of tailoring one for this job."),
          toggle("external", "headless", "Headless browser"),
          previewBox("external"),
          runButton("external", "Run", { confirm: () => (S.forms.external && S.forms.external.dry_run ? null : liveRunConfirm("This submits a real application on the company’s site.")) }),
        ),
      ),
    ),
  );
}

function withKey(el, key) {
  el.dataset.key = key;
  return el;
}
