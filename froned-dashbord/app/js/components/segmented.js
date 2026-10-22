import { h } from "../dom.js";

export function segmented(label, choices, value, onChange) {
  return h(
    "div",
    { class: "segmented", role: "group", "aria-label": label },
    choices.map(([v, text]) =>
      h("button", { type: "button", dataset: { focusKey: `${label}:${v}` }, "aria-pressed": String(v === value), onclick: () => onChange(v), text }),
    ),
  );
}
