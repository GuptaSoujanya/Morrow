/** Tiny hyperscript helper. Every string ever placed on screen goes through `text`
 * (which sets `.textContent`, never `.innerHTML`) or through child nodes built the same way. */

const BOOL_ATTRS = new Set(["disabled", "checked", "hidden", "selected", "readOnly", "required", "open"]);

export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  applyProps(el, props || {});
  appendChildren(el, children);
  return el;
}

function applyProps(el, props) {
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined) continue;
    if (key === "text") {
      el.textContent = value;
    } else if (key === "class") {
      el.className = value;
    } else if (key === "dataset") {
      for (const [k, v] of Object.entries(value)) el.dataset[k] = v;
    } else if (key === "style" && typeof value === "object") {
      Object.assign(el.style, value);
    } else if (key.startsWith("on") && typeof value === "function") {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key in el && BOOL_ATTRS.has(key)) {
      el[key] = !!value;
    } else if (key === "value") {
      el.value = value;
    } else {
      el.setAttribute(key, String(value));
    }
  }
}

function appendChildren(el, children) {
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function clear(el) {
  el.replaceChildren();
}

export function svg(tag, attrs = {}, ...children) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined) continue;
    if (key.startsWith("on") && typeof value === "function") {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else {
      el.setAttribute(key, String(value));
    }
  }
  appendChildren(el, children);
  return el;
}
