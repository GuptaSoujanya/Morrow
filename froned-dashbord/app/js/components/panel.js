import { h } from "../dom.js";

export function panel(title, { sub, tools, cls = "" } = {}, ...body) {
  return h(
    "section",
    { class: `panel ${cls}` },
    h(
      "div",
      { class: "panel-head" },
      h("div", {}, h("h2", { class: "panel-title", text: title }), sub ? h("p", { class: "panel-sub", text: sub }) : null),
      tools || null,
    ),
    h("div", { class: "panel-body" }, ...body),
  );
}

export function empty(text, extra) {
  return h("div", { class: "state-empty" }, h("p", { text }), extra || null);
}

export function loadingState(text = "Loading…") {
  return h("div", { class: "state-loading", role:'status' }, h("p", { class: "muted", text }));
}

export function errorState(text, retry) {
  return h(
    "div",
    { class: "state-error", role:'alert' },
    h("p", { text }),
    retry ? h("button", { class: "btn btn-sm", type: "button", text: "Try again", onclick: retry }) : null,
  );
}

export function dataTable(columns, rows) {
  return h(
    "div",
    { class: "table-wrap" },
    h(
      "table",
      { class: "table" },
      h("thead", {}, h("tr", {}, columns.map(([text, cls]) => h("th", { class: cls || null, text, scope: "col" })))),
      h("tbody", {}, rows),
    ),
  );
}
