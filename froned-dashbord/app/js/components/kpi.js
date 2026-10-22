import { h } from "../dom.js";

export function kpiCard({ label, value, unit, sub, change, extra, href }) {
  return h(
    "div",
    { class: "kpi" },
    h("span", { class: "kpi-label", text: label }),
    h(
      "div",
      { class: "kpi-value-row" },
      h("span", { class: "kpi-value", text: value }),
      unit ? h("span", { class: "kpi-unit", text: unit }) : null,
      change ? h("span", { class: `kpi-change ${change.dir}`, text: `${change.dir === "up" ? "▲" : change.dir === "down" ? "▼" : "–"} ${change.text}` }) : null,
    ),
    sub ? h("p", { class: "kpi-sub", text: sub }) : null,
    extra || null,
    href ? h("a", { class: "kpi-link", href, text: "See what’s waiting" }) : null,
  );
}
