import { h } from "../dom.js";

/** Every destructive or real-world action (a non-dry-run run, force stop, saving a secret)
 * goes through this before it happens. Resolves true/false; never auto-accepts. */
export function confirmDialog({ title, body, code, ok = "Continue", tone = "primary" }) {
  const dialog = document.getElementById("confirm");
  if (dialog.open) return Promise.resolve(false);
  const previous = document.activeElement;
  dialog.setAttribute('aria-labelledby', 'confirm-title');
  return new Promise((resolve) => {
    const finish = (answer) => {
      dialog.close();
      previous?.focus();
      resolve(answer);
    };
    const yes = h("button", { class: `btn btn-${tone}`, type: "button", text: ok, onclick: () => finish(true) });
    dialog.replaceChildren(
      h(
        "form",
        { method: "dialog", class: "confirm-body", onsubmit: (e) => e.preventDefault() },
        h("h2", { class: "confirm-title", id: 'confirm-title', text: title }),
        body ? h("p", { class: "confirm-text", text: body }) : null,
        code ? h("pre", { class: "confirm-code" }, h("code", { text: code })) : null,
        h(
          "div",
          { class: "row end" },
          h("button", { class: "btn", type: "button", text: "Cancel", onclick: () => finish(false) }),
          yes,
        ),
      ),
    );
    dialog.oncancel = (e) => {
      e.preventDefault();
      finish(false);
    };
    dialog.showModal();
    dialog.querySelector('button').focus();
  });
}
