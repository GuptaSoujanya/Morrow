import { h } from "../dom.js";
import { icon } from "../icons.js";

export function toast(text, tone = "info", ms = 4500) {
  const box = h(
    "div",
    { class: `toast toast-${tone}`, role: tone === "error" ? "alert" : "status" },
    h("span", { class: "toast-text", text }),
    h("button", { class: "icon-btn", type: "button", "aria-label": "Dismiss", onclick: () => box.remove() }, icon("x", "icon icon-sm")),
  );
  document.getElementById("toasts").append(box);
  setTimeout(() => box.classList.add("leaving"), ms);
  setTimeout(() => box.remove(), ms + 250);
  return box;
}
