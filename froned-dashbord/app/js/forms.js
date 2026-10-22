import { h } from "./dom.js";
import { icon } from "./icons.js";
import { api } from "./api.js";
import { toast } from "./components/toast.js";
import { confirmDialog } from "./components/dialog.js";
import { setConsoleSize } from "./components/console.js";
import { S, form, running, hooks } from "./state.js";
import { sentence } from "./format.js";
import { selectControl, dateControl } from './components/controls.js';
export { form } from "./state.js";

let fieldId = 0;
export function field(label, control, hint) {
  const id = `field-${++fieldId}`;
  const target = control.controlElement || control;
  target.dataset.focusKey = `field:${label}`;
  if (!target.id) target.id = id;
  target.setAttribute('aria-labelledby', `${id}-label`);
  const descriptions = [target.getAttribute('aria-describedby'), hint ? `${id}-hint` : null].filter(Boolean);
  const error = h('span', { id: `${id}-error`, class: 'field-error', role: 'status', hidden: true });
  if (target.matches('input:not(.date-input),textarea')) {
    descriptions.push(error.id);
    const validate = () => {
      let message = '';
      if (target.validity.rangeUnderflow) message = `Use ${target.min} or more.`;
      else if (target.validity.rangeOverflow) message = `Use ${target.max} or less.`;
      else if (target.validity.typeMismatch) message = target.type === 'email' ? 'Enter a complete email address, like name@example.com.' : 'Enter a valid web address.';
      else if (target.validity.stepMismatch || target.validity.badInput) message = 'Enter a valid number within the allowed range.';
      target.setAttribute('aria-invalid', String(!!message)); error.hidden = !message; error.textContent = message;
    };
    target.addEventListener('blur', validate);
    target.addEventListener('input', () => { if (target.getAttribute('aria-invalid') === 'true') validate(); });
  }
  if (descriptions.length) target.setAttribute('aria-describedby', descriptions.join(' '));
  return h("div", { class: "field" }, h("label", { class: "field-label", id: `${id}-label`, for:target.id, text: label }), control, hint ? h("span", { class: "field-hint", id: `${id}-hint`, text: hint }) : null, error);
}

export function toggle(action, key, label, hint) {
  const values = form(action);
  const input = h("input", {
    type: "checkbox",
    class: "switch",
    checked: !!values[key],
    onchange: (e) => {
      values[key] = e.target.checked;
      schedulePreview(action);
    },
  });
  return h("label", { class: "toggle" }, input, h("span", { class: "toggle-text" }, h("span", { text: label }), hint ? h("span", { class: "muted small", text: hint }) : null));
}

export function textInput(action, key, { placeholder = "", type = "text", inputmode, onEnter, min, max, step } = {}) {
  const values = form(action);
  if (type === 'date') return dateControl({value: values[key] ?? '', onChange: value => { values[key] = value; schedulePreview(action); }});
  return h("input", {
    class: "input",
    type,
    inputmode,
    min, max, step,
    placeholder,
    value: values[key] ?? "",
    oninput: (e) => {
      values[key] = e.target.value;
      schedulePreview(action);
    },
    onkeydown: (e) => {
      if (e.key === "Enter" && onEnter) {
        e.preventDefault();
        onEnter();
      }
    },
  });
}

export function textArea(action, key, { placeholder = "", rows = 5 } = {}) {
  const values = form(action);
  const el = h("textarea", {
    class: "textarea",
    placeholder,
    rows,
    oninput: (e) => {
      values[key] = e.target.value;
      schedulePreview(action);
    },
  });
  el.value = values[key] ?? "";
  return el;
}

export function selectInput(action, key, choices, fallback = "") {
  const values = form(action);
  if (values[key] === undefined) values[key] = fallback;
  return selectControl({options: choices, value: values[key], onChange: value => { values[key] = value; schedulePreview(action); }});
}

/** The required preview-before-run box: always rendered, always calls the backend `/api/preview`
 * before any run button becomes clickable. */
export function previewBox(action) {
  const box = h("div", { class: "preview", id: `preview-${action}` }, h("span", { class: "muted small", text: "Checking…" }));
  schedulePreview(action);
  return h('details', {class:'run-details'}, h('summary', {text:'Run details'}), box);
}

export function schedulePreview(action) {
  clearTimeout((S.previews[action] || {}).timer);
  S.previews[action] = S.previews[action] || {};
  S.previews[action].error = 'Checking these options…';
  S.previews[action].version = (S.previews[action].version || 0) + 1;
  updateRunButtons();
  S.previews[action].timer = setTimeout(() => preview(action), 200);
}

async function preview(action) {
  const box = document.getElementById(`preview-${action}`);
  if (!box) return;
  const state = S.previews[action] || (S.previews[action] = {});
  const version = state.version;
  try {
    const reply = await api("/api/preview", { action, options: form(action) });
    if (version !== state.version) return;
    if (reply.needed) throw new Error(sentence(reply.needed));
    state.error = "";
    state.shown = reply.shown;
    box.replaceChildren(h("span", { class: "preview-label", text: "Will run" }), h("code", { text: `$ ${reply.shown}` }));
    box.classList.remove("preview-error");
  } catch (error) {
    if (version !== state.version) return;
    state.error = error.message;
    state.shown = "";
    box.replaceChildren(h("span", { class: "preview-label", text: "Needed" }), h("span", { text: error.message }));
    box.classList.add("preview-error");
    box.parentElement.open = true;
  }
  updateRunButtons();
}

/** Every run — dry or real — previews the exact command it is about to start, with the exact
 * options this call uses (not just whatever a mounted form last previewed), then asks for
 * explicit confirmation before anything happens. Returns null if the user does not confirm. */
async function previewThenConfirm(action, options, confirm) {
  let shown = "";
  try {
    const reply = await api("/api/preview", { action, options: options || {} });
    if (reply.needed) {
      toast(sentence(reply.needed), "warn");
      return false;
    }
    shown = reply.shown;
  } catch (error) {
    toast(error.message, "error");
    return false;
  }
  const dialog = confirm
    ? { ok: "Run it", tone: "primary", ...confirm, code: shown }
    : { title: "Run this?", body: "This is the exact command that will run:", code: shown, ok: "Run it" };
  return confirmDialog(dialog);
}

export function updateRunButtons() {
  const busy = running();
  for (const [key, button] of Object.entries(S.runButtons)) {
    if (!button.isConnected) {
      delete S.runButtons[key];
      continue;
    }
    const action = button.dataset.action;
    const blocked = (S.previews[action] || {}).error;
    button.disabled = busy || !!blocked;
    button.title = busy ? `${S.status.run.label} is running. Stop it or wait for it to finish.` : blocked || "";
  }
}

async function run(action, options, { confirm } = {}) {
  if (!(await previewThenConfirm(action, options, confirm))) return;
  try {
    const reply = await api("/api/run", { action, options: options || {} });
    if (S.consoleSize === "collapsed") setConsoleSize("normal");
    toast(`Started ${reply.label}.`, "info", 2500);
  } catch (error) {
    toast(error.message, "error");
  }
  try { await hooks.refreshStatus(); } catch (error) { toast(error.message, 'error'); }
}

export function runButton(action, label, { tone = "primary", confirm, options } = {}) {
  const button = h("button", {
    class: `btn btn-${tone}`,
    type: "button",
    dataset: { action },
    onclick: () => run(action, options ? options() : form(action), { confirm: typeof confirm === "function" ? confirm() : confirm }),
  }, icon("play", "icon icon-sm"), label);
  S.runButtons[`${action}:${label}`] = button;
  return button;
}

export function quickButton(action, label, options = {}, extra = {}) {
  const button = h("button", {
    class: `btn ${extra.tone ? `btn-${extra.tone}` : ""}`,
    type: "button",
    dataset: { action: `${action}-fixed` },
    onclick: () => run(action, options, { confirm: typeof extra.confirm === "function" ? extra.confirm() : extra.confirm }),
  }, label);
  S.runButtons[`${action}-fixed:${label}`] = button;
  return button;
}

/** A real-world run (not a dry run) always gets this confirmation. */
export function liveRunConfirm(what = "This applies for real, not a practice run.") {
  return { title: "Run for real?", body: what, ok: "Run it", tone: "primary" };
}
