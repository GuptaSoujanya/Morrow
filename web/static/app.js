'use strict';

// The control site's page: one hash route per section, everything else comes from /api.

const SECTIONS = [
  ['overview', 'Overview', 'grid'],
  ['naukri', 'Apply on Naukri', 'send'],
  ['sites', 'Company sites', 'globe'],
  ['profile', 'Naukri profile', 'refresh'],
  ['linkedin', 'LinkedIn post', 'pen'],
  ['resume', 'Tailor resume', 'file'],
  ['reports', 'Reports', 'chart'],
  ['study', 'Study', 'book'],
  ['todo', 'Your to-dos', 'check'],
  ['setup', 'Setup', 'sliders'],
];

const ICONS = {
  grid: ['M4 4h6.5v6.5H4z', 'M13.5 4H20v6.5h-6.5z', 'M4 13.5h6.5V20H4z', 'M13.5 13.5H20V20h-6.5z'],
  send: ['M21 3 10 14', 'M21 3l-6.5 18-3.5-7-7-3.5z'],
  globe: ['M12 3a9 9 0 1 0 0 18 9 9 0 1 0 0-18z', 'M3 12h18', 'M12 3c2.4 2.6 3.6 5.6 3.6 9s-1.2 6.4-3.6 9c-2.4-2.6-3.6-5.6-3.6-9S9.6 5.6 12 3z'],
  refresh: ['M20 11a8 8 0 0 0-14.6-4.4L4 8', 'M4 3.5V8h4.5', 'M4 13a8 8 0 0 0 14.6 4.4L20 16', 'M20 20.5V16h-4.5'],
  pen: ['M4 20h4L19 9l-4-4L4 16z', 'M13 7l4 4'],
  file: ['M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z', 'M14 3v5h5', 'M9 13h6', 'M9 17h6'],
  chart: ['M4 20h16', 'M7 16v-4', 'M12 16V7', 'M17 16v-6'],
  book: ['M4 4.5A1.5 1.5 0 0 1 5.5 3H20v15H5.5A1.5 1.5 0 0 0 4 19.5z', 'M4 19.5A1.5 1.5 0 0 0 5.5 21H20'],
  check: ['M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z', 'M8 12l3 3 5-6'],
  sliders: ['M4 6h9', 'M17 6h3', 'M15 4v4', 'M4 12h3', 'M11 12h9', 'M9 10v4', 'M4 18h11', 'M19 18h1', 'M17 16v4'],
  external: ['M14 4h6v6', 'M20 4l-9 9', 'M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5'],
  play: ['M8 5v14l11-7z'],
  stop: ['M7 7h10v10H7z'],
  copy: ['M9 9h11v11H9z', 'M5 15H4V4h11v1'],
  trash: ['M4 7h16', 'M10 11v6', 'M14 11v6', 'M6 7l1 13h10l1-13', 'M9 7V4h6v3'],
  up: ['M6 15l6-6 6 6'],
  down: ['M6 9l6 6 6-6'],
  left: ['M15 6l-6 6 6 6'],
  right: ['M9 6l6 6-6 6'],
  x: ['M6 6l12 12', 'M18 6 6 18'],
  folder: ['M3 6a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z'],
  tick: ['M5 12.5l4.5 4.5L19 7.5'],
  edit: ['M4 20h4L19 9l-4-4L4 16z'],
};

const S = {
  meta: null,
  status: null,
  course: null,
  route: { name: 'overview', arg: '' },
  overview: null,
  overviewDays: [7, 14, 30, 0].includes(Number(localStorage.getItem('overview-days') ?? 14)) ? Number(localStorage.getItem('overview-days') ?? 14) : 14,
  overviewLoading: null,
  funnelGroup: 'all',
  searchesOpen: false,
  forms: {},
  drafts: {},
  previews: {},
  runButtons: {},
  reports: {},
  runNext: 0,
  runStartedAt: 0,
  seenLast: false,
  lastFinished: null,
  pendingRender: false,
  signature: '',
  online: true,
};

const content = document.getElementById('content');

// --- small helpers -------------------------------------------------------------------------------

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'text') el.textContent = value;
    else if (key === 'dataset') Object.assign(el.dataset, value);
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else if (key in el && typeof value !== 'string') el[key] = value;
    else el.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

function icon(name, cls = 'icon') {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('class', cls);
  svg.setAttribute('aria-hidden', 'true');
  for (const d of ICONS[name] || []) {
    const path = document.createElementNS(ns, 'path');
    path.setAttribute('d', d);
    svg.append(path);
  }
  return svg;
}

function counted(n, noun, plural = noun + 's') {
  return `${n} ${n === 1 ? noun : plural}`;
}

function sentence(text) {
  text = String(text || '').trim();
  if (!text) return '';
  text = text[0].toUpperCase() + text.slice(1);
  return /[.!?…]$/.test(text) ? text : text + '.';
}

function elapsed(seconds) {
  seconds = Math.max(0, Math.floor(seconds));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

function localDay(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d);
}

// en-GB writes September as "Sept"; every other month keeps three letters.
function shortDate(iso) {
  return localDay(iso).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' }).replace('Sept', 'Sep');
}

function longDate(iso) {
  const day = localDay(iso);
  const weekday = day.toLocaleDateString('en-GB', { weekday: 'long' });
  const rest = day.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
  return `${weekday}, ${rest}`;
}

const ACRONYMS = { pan: 'PAN', pf: 'PF', ctc: 'CTC', lpa: 'LPA', url: 'URL', id: 'ID', uan: 'UAN', gst: 'GST', ifsc: 'IFSC', dob: 'Date of birth' };

function humanKey(key) {
  const words = key.split(/[_\s.]+/).filter(Boolean).map((w) => ACRONYMS[w.toLowerCase()] || w.toLowerCase());
  if (!words.length) return key;
  if (words[0] === words[0].toLowerCase()) words[0] = words[0][0].toUpperCase() + words[0].slice(1);
  return words.join(' ');
}

function safeUrl(url) {
  return /^https?:\/\//i.test(url || '') ? url : null;
}

function isTyping(el = document.activeElement) {
  return !!el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName));
}

async function api(path, body) {
  const options = body === undefined
    ? {}
    : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  let reply;
  try {
    reply = await fetch(path, options);
  } catch {
    setOnline(false);
    throw new Error('Can’t reach the site’s server.');
  }
  setOnline(true);
  const data = await reply.json().catch(() => ({}));
  if (!reply.ok) {
    const error = new Error(sentence(data.error || `${reply.status} ${reply.statusText}`));
    error.status = reply.status;
    throw error;
  }
  return data;
}

function setOnline(online) {
  if (S.online === online) return;
  S.online = online;
  document.getElementById('offline').hidden = online;
}

// --- toasts and dialogs --------------------------------------------------------------------------

function toast(text, tone = 'info', ms = 4500) {
  const box = h('div', { class: `toast toast-${tone}`, role: tone === 'error' ? 'alert' : 'status' },
    h('span', { class: 'toast-text', text }),
    h('button', { class: 'icon-btn', 'aria-label': 'Dismiss', onclick: () => box.remove() }, icon('x')));
  document.getElementById('toasts').append(box);
  setTimeout(() => box.classList.add('leaving'), ms);
  setTimeout(() => box.remove(), ms + 250);
}

function confirmDialog({ title, body, ok = 'Continue', tone = 'primary' }) {
  const dialog = document.getElementById('confirm');
  return new Promise((resolve) => {
    const finish = (answer) => { dialog.close(); resolve(answer); };
    const yes = h('button', { class: `btn btn-${tone}`, text: ok, onclick: () => finish(true) });
    dialog.replaceChildren(h('form', { method: 'dialog', class: 'confirm-body', onsubmit: (e) => e.preventDefault() },
      h('h2', { class: 'confirm-title', text: title }),
      body ? h('p', { class: 'confirm-text', text: body }) : null,
      h('div', { class: 'row end' },
        h('button', { class: 'btn', type: 'button', text: 'Cancel', onclick: () => finish(false) }),
        yes)));
    dialog.oncancel = (e) => { e.preventDefault(); finish(false); };
    dialog.showModal();
    yes.focus();
  });
}

// --- the file editor -----------------------------------------------------------------------------

const FILE_TITLES = {
  answers: 'Answers to screening questions',
  profile: 'Facts about you',
  company_sites: 'Company-site applications',
  env: 'Settings',
};

async function openEditor(name) {
  let file;
  try {
    file = await api(`/api/file?name=${encodeURIComponent(name)}`);
  } catch (error) {
    toast(error.message, 'error');
    return;
  }
  const dialog = document.getElementById('editor');
  const area = h('textarea', { class: 'editor-text', spellcheck: false, 'aria-label': file.path });
  area.value = file.text;
  const where = h('span', { class: 'muted tabular' });
  const save = h('button', { class: 'btn btn-primary', type: 'button', text: 'Save' });
  const dirty = () => area.value !== file.text;
  const showWhere = () => {
    const line = area.value.slice(0, area.selectionStart).split('\n').length;
    where.textContent = `Line ${line}${dirty() ? ' · unsaved changes' : ''}`;
  };
  const close = async () => {
    if (dirty() && !(await confirmDialog({ title: 'Close without saving?', body: 'Your changes to this file will be lost.', ok: 'Discard changes', tone: 'danger' }))) return;
    dialog.close();
  };
  const store = async () => {
    try {
      await api('/api/file', { name, text: area.value });
    } catch (error) {
      toast(error.message, 'error');
      return;
    }
    file.text = area.value;
    dialog.close();
    toast(`Saved ${file.path}.`, 'ok');
    refreshStatus();
  };
  save.onclick = store;
  area.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      store();
    } else if (e.key === 'Tab' && !e.shiftKey) {
      e.preventDefault();
      if (!document.execCommand('insertText', false, '  ')) area.setRangeText('  ', area.selectionStart, area.selectionEnd, 'end');
    }
  });
  area.addEventListener('input', showWhere);
  area.addEventListener('click', showWhere);
  area.addEventListener('keyup', showWhere);

  dialog.replaceChildren(
    h('header', { class: 'editor-head' },
      h('div', {},
        h('h2', { class: 'editor-title', text: FILE_TITLES[name] || file.path }),
        h('p', { class: 'muted mono small', text: file.exists ? file.path : `${file.path} (new file)` })),
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Close', onclick: close }, icon('x'))),
    area,
    h('footer', { class: 'editor-foot' },
      where,
      h('span', { class: 'spacer' }),
      h('span', { class: 'muted small', text: '⌘S saves' }),
      h('button', { class: 'btn', type: 'button', text: 'Cancel', onclick: close }),
      save));
  dialog.oncancel = (e) => { e.preventDefault(); close(); };
  dialog.showModal();
  area.focus();
  if (file.line) {
    const lines = area.value.split('\n');
    const offset = lines.slice(0, file.line - 1).reduce((sum, l) => sum + l.length + 1, 0);
    const end = offset + (lines[file.line - 1] || '').length;
    area.setSelectionRange(end, end);
    const lineHeight = parseFloat(getComputedStyle(area).lineHeight) || 20;
    area.scrollTop = Math.max(0, (file.line - 4) * lineHeight);
  } else {
    area.setSelectionRange(0, 0);
  }
  showWhere();
}

// --- running commands ----------------------------------------------------------------------------

function running() {
  return !!(S.status && S.status.run.running);
}

function form(action) {
  return (S.forms[action] = S.forms[action] || {});
}

function schedulePreview(action) {
  clearTimeout((S.previews[action] || {}).timer);
  S.previews[action] = S.previews[action] || {};
  S.previews[action].timer = setTimeout(() => preview(action), 200);
}

async function preview(action) {
  const box = document.getElementById(`preview-${action}`);
  if (!box) return;
  const state = S.previews[action] || (S.previews[action] = {});
  try {
    const reply = await api('/api/preview', { action, options: form(action) });
    if (reply.needed) throw new Error(sentence(reply.needed));
    state.error = '';
    box.replaceChildren(h('span', { class: 'preview-label', text: 'Will run' }), h('code', { text: `$ ${reply.shown}` }));
    box.classList.remove('preview-error');
  } catch (error) {
    state.error = error.message;
    box.replaceChildren(h('span', { class: 'preview-label', text: 'Needed' }), h('span', { text: error.message }));
    box.classList.add('preview-error');
  }
  updateRunButtons();
}

function updateRunButtons() {
  const busy = running();
  for (const [key, button] of Object.entries(S.runButtons)) {
    if (!button.isConnected) {
      delete S.runButtons[key];
      continue;
    }
    const action = button.dataset.action;
    const blocked = (S.previews[action] || {}).error;
    button.disabled = busy || !!blocked;
    button.title = busy ? `${S.status.run.label} is running. Stop it or wait for it to finish.` : blocked || '';
  }
}

async function run(action, options, { confirm } = {}) {
  if (confirm && !(await confirmDialog(confirm))) return;
  try {
    const reply = await api('/api/run', { action, options: options || {} });
    const consoleBox = document.getElementById('console');
    if (consoleBox.dataset.size === 'collapsed') setConsoleSize('normal');
    toast(`Started ${reply.label}.`, 'info', 2500);
  } catch (error) {
    toast(error.message, 'error');
  }
  await refreshStatus();
  pollRun();
}

async function stopRun() {
  try {
    const reply = await api('/api/stop', {});
    toast(reply.message, reply.ok ? 'info' : 'warn');
  } catch (error) {
    toast(error.message, 'error');
  }
  refreshStatus();
}

function runButton(action, label, { tone = 'primary', confirm, options } = {}) {
  const button = h('button', {
    class: `btn btn-${tone}`,
    type: 'button',
    dataset: { action },
    onclick: () => run(action, options ? options() : form(action), { confirm: typeof confirm === 'function' ? confirm() : confirm }),
  }, icon('play', 'icon icon-sm'), label);
  S.runButtons[`${action}:${label}`] = button;
  return button;
}

function quickButton(action, label, options = {}, extra = {}) {
  const button = h('button', {
    class: `btn ${extra.tone ? `btn-${extra.tone}` : ''}`,
    type: 'button',
    dataset: { action: `${action}-fixed` },
    onclick: () => run(action, options, { confirm: extra.confirm }),
  }, label);
  S.runButtons[`${action}-fixed:${label}`] = button;
  return button;
}

// --- form fields ---------------------------------------------------------------------------------

function toggle(action, key, label, hint) {
  const values = form(action);
  const input = h('input', {
    type: 'checkbox',
    class: 'switch',
    checked: !!values[key],
    onchange: (e) => { values[key] = e.target.checked; schedulePreview(action); },
  });
  return h('label', { class: 'toggle' }, input, h('span', { class: 'toggle-text' }, h('span', { text: label }), hint ? h('span', { class: 'muted small', text: hint }) : null));
}

function field(label, control, hint) {
  return h('label', { class: 'field' }, h('span', { class: 'field-label', text: label }), control, hint ? h('span', { class: 'field-hint', text: hint }) : null);
}

function textInput(action, key, { placeholder = '', type = 'text', inputmode, onEnter } = {}) {
  const values = form(action);
  return h('input', {
    class: 'input',
    type,
    inputmode,
    placeholder,
    value: values[key] ?? '',
    oninput: (e) => { values[key] = e.target.value; schedulePreview(action); },
    onkeydown: (e) => { if (e.key === 'Enter' && onEnter) { e.preventDefault(); onEnter(); } },
  });
}

function selectInput(action, key, choices, fallback = '') {
  const values = form(action);
  if (values[key] === undefined) values[key] = fallback;
  const select = h('select', {
    class: 'input',
    onchange: (e) => { values[key] = e.target.value; schedulePreview(action); },
  }, choices.map((c) => h('option', { value: c.value, text: c.label })));
  select.value = values[key];
  return select;
}

function previewLine(action) {
  schedulePreview(action);
  return h('p', { class: 'preview', id: `preview-${action}` }, h('span', { class: 'preview-label', text: 'Will run' }), h('span', { class: 'muted', text: '…' }));
}

// --- page pieces ---------------------------------------------------------------------------------

function pageHead(title, text) {
  return h('header', { class: 'page-head' }, h('h1', { text: title }), text ? h('p', { class: 'lead', text }) : null);
}

function section(title, ...children) {
  return h('section', { class: 'block' }, title ? h('h2', { class: 'block-title', text: title }) : null, children);
}

function card(...children) {
  return h('div', { class: 'card' }, children);
}

function row(...children) {
  return h('div', { class: 'row' }, children);
}

function link(href, label, external = false) {
  return h('a', { class: 'link', href, target: external ? '_blank' : null, rel: external ? 'noopener noreferrer' : null }, label, external ? icon('external', 'icon icon-xs') : null);
}

function empty(text, ...extra) {
  return h('div', { class: 'empty' }, h('p', { text }), extra);
}

function openPath(path) {
  api('/api/open', { what: 'path', path }).catch((error) => toast(error.message, 'error'));
}

// --- charts --------------------------------------------------------------------------------------

const SVG_NS = 'http://www.w3.org/2000/svg';

function svg(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'text') el.textContent = value;
    else el.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) if (child) el.append(child);
  return el;
}

function num(n) {
  return Number(n || 0).toLocaleString('en-IN');
}

function share(part, whole) {
  if (!whole) return '–';
  const percent = (part / whole) * 100;
  return percent > 0 && percent < 1 ? '<1%' : `${Math.round(percent)}%`;
}

function duration(seconds) {
  if (seconds < 60) return `${seconds} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  return `${Math.floor(seconds / 3600)} h ${Math.round((seconds % 3600) / 60)} min`;
}

// Gridlines at 1, 2 or 5 times a power of ten, whole numbers only, the top one at or above max.
function niceTicks(max, count = 4) {
  const raw = Math.max(1, max) / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = Math.max(1, [1, 2, 5, 10].map((m) => m * magnitude).find((s) => s >= raw));
  const ticks = [];
  for (let tick = 0; tick < max + step; tick += step) ticks.push(tick);
  return ticks.length > 1 ? ticks : [0, step];
}

// Charts are drawn at their real pixel width so text never scales; they redraw when the box resizes.
function chartBox({ height, label, draw }) {
  const box = h('div', { class: 'chart', role: 'img', 'aria-label': label, style: `height: ${height}px` });
  let drawn = 0;
  const observer = new ResizeObserver(() => {
    if (!box.isConnected) {
      observer.disconnect();
      return;
    }
    const width = Math.floor(box.clientWidth);
    if (!width || width === drawn) return;
    drawn = width;
    box.replaceChildren();
    draw(box, width, height);
  });
  observer.observe(box);
  return box;
}

function chartTip(box) {
  const tip = h('div', { class: 'chart-tip', 'aria-hidden': 'true', hidden: true });
  box.append(tip);
  return {
    show(left, right, children) {
      tip.replaceChildren(...children.filter(Boolean));
      tip.hidden = false;
      const width = tip.offsetWidth;
      tip.style.left = `${right + 10 + width <= box.clientWidth ? right + 10 : Math.max(0, left - 10 - width)}px`;
    },
    hide() { tip.hidden = true; },
  };
}

function tipTitle(text) {
  return h('div', { class: 'tip-title', text });
}

function tipRow(text, value, swatch) {
  return h('div', { class: 'tip-row' }, h('span', { class: `swatch ${swatch || 'swatch-none'}` }), h('span', { text }), h('span', { class: 'tip-value tabular', text: value }));
}

function yAxis(root, ticks, y, left, right) {
  for (const tick of ticks) {
    root.append(svg('line', { class: tick ? 'chart-grid' : 'chart-axis', x1: left, x2: right, y1: y(tick), y2: y(tick) }));
    root.append(svg('text', { class: 'chart-label', x: left - 8, y: y(tick), 'text-anchor': 'end', 'dominant-baseline': 'middle', text: num(tick) }));
  }
}

// Stacked columns, one per row: rows [{...}], series [{key, label, cls}], tip(row, total) -> nodes.
function columnsChart({ rows, series, label, xLabel, tip, height = 230 }) {
  return chartBox({ height, label, draw(box, width) {
    const pad = { top: 10, right: 4, bottom: 26, left: 34 };
    const inner = { w: width - pad.left - pad.right, h: height - pad.top - pad.bottom };
    const totals = rows.map((r) => series.reduce((sum, s) => sum + (r[s.key] || 0), 0));
    const ticks = niceTicks(Math.max(0, ...totals));
    const top = ticks[ticks.length - 1];
    const y = (v) => pad.top + inner.h - (v / top) * inner.h;
    const band = inner.w / rows.length;
    const bar = Math.max(2, Math.min(34, band * 0.62));
    const every = Math.max(1, Math.ceil(rows.length / Math.max(1, Math.floor(inner.w / 56))));
    const root = svg('svg', { class: 'chart-svg', width, height, viewBox: `0 0 ${width} ${height}` });
    const hover = svg('rect', { class: 'chart-hover', x: -1000, y: pad.top, width: band, height: inner.h, rx: 4 });
    root.append(hover);
    yAxis(root, ticks, y, pad.left, width - pad.right);
    box.append(root);
    const tipper = chartTip(box);
    rows.forEach((r, i) => {
      const x0 = pad.left + i * band;
      const x = x0 + (band - bar) / 2;
      let base = 0;
      for (const s of series) {
        const value = r[s.key] || 0;
        if (!value) continue;
        const top1 = y(base + value);
        const gap = base ? 1 : 0;
        root.append(svg('rect', { class: `bar ${s.cls}`, x, y: top1, width: bar, height: Math.max(1, y(base) - top1 - gap), rx: Math.min(2, bar / 4) }));
        base += value;
      }
      if ((rows.length - 1 - i) % every === 0) {
        root.append(svg('text', { class: 'chart-label', x: x0 + band / 2, y: height - 7, 'text-anchor': 'middle', text: xLabel(r) }));
      }
      const hit = svg('rect', { class: 'chart-hit', x: x0, y: 0, width: band, height });
      hit.addEventListener('pointerenter', () => {
        hover.setAttribute('x', x0);
        tipper.show(x0, x0 + band, tip(r, totals[i]));
      });
      root.append(hit);
    });
    root.addEventListener('pointerleave', () => {
      hover.setAttribute('x', -1000);
      tipper.hide();
    });
  } });
}

// Five-point score buckets on a 0–100 axis, with the minimum score marked where it falls.
function scoreKind(bin, minimum) {
  return bin.from >= minimum ? 'over' : bin.to <= minimum ? 'under' : 'mixed';
}

function scoreRange(bin) {
  return bin.to === 100 ? `${bin.from} to 100` : `${bin.from} to under ${bin.to}`;
}

function scoresChart(bins, minimum, over) {
  const scored = bins.reduce((sum, b) => sum + b.count, 0);
  return chartBox({
    height: 210,
    label: `Match scores of ${num(scored)} scored jobs in five-point buckets; ${num(over)} scored ${minimum} or more.`,
    draw(box, width, height) {
      const pad = { top: 22, right: 10, bottom: 26, left: 34 };
      const inner = { w: width - pad.left - pad.right, h: height - pad.top - pad.bottom };
      const ticks = niceTicks(Math.max(0, ...bins.map((b) => b.count)));
      const top = ticks[ticks.length - 1];
      const y = (v) => pad.top + inner.h - (v / top) * inner.h;
      const x = (score) => pad.left + (score / 100) * inner.w;
      const root = svg('svg', { class: 'chart-svg', width, height, viewBox: `0 0 ${width} ${height}` });
      const hover = svg('rect', { class: 'chart-hover', x: -1000, y: pad.top, width: x(5) - x(0), height: inner.h, rx: 3 });
      root.append(hover);
      yAxis(root, ticks, y, pad.left, width - pad.right);
      box.append(root);
      const tipper = chartTip(box);
      for (let score = 0; score <= 100; score += 10) {
        root.append(svg('text', { class: 'chart-label', x: x(score), y: height - 7, 'text-anchor': 'middle', text: String(score) }));
      }
      const notes = { over: `At or above the minimum of ${minimum}`, under: `Below the minimum of ${minimum}`, mixed: `The minimum of ${minimum} falls inside this bucket` };
      for (const bin of bins) {
        const x0 = x(bin.from);
        const x1 = x(bin.to);
        const kind = scoreKind(bin, minimum);
        if (bin.count) {
          root.append(svg('rect', { class: `bar score-${kind}`, x: x0 + 1.5, y: y(bin.count), width: Math.max(1, x1 - x0 - 3), height: Math.max(1, y(0) - y(bin.count)), rx: 2 }));
        }
        const hit = svg('rect', { class: 'chart-hit', x: x0, y: 0, width: x1 - x0, height });
        hit.addEventListener('pointerenter', () => {
          hover.setAttribute('x', x0);
          tipper.show(x0, x1, [tipTitle(`Score ${scoreRange(bin)}`), tipRow(counted(bin.count, 'job'), share(bin.count, scored), `score-${kind}`), h('div', { class: 'tip-note', text: notes[kind] })]);
        });
        root.append(hit);
      }
      const mx = x(minimum);
      root.append(svg('line', { class: 'chart-marker', x1: mx, x2: mx, y1: pad.top - 6, y2: pad.top + inner.h }));
      const flip = mx > width - 200;
      root.append(svg('text', { class: 'chart-marker-label', x: flip ? mx - 6 : mx + 6, y: pad.top - 9, 'text-anchor': flip ? 'end' : 'start', text: `Minimum ${minimum} · ${num(over)} at or above` }));
      root.addEventListener('pointerleave', () => {
        hover.setAttribute('x', -1000);
        tipper.hide();
      });
    },
  });
}

function sparkline(values) {
  const width = 120;
  const height = 34;
  const max = Math.max(1, ...values);
  const step = values.length > 1 ? width / (values.length - 1) : 0;
  const points = values.map((v, i) => [values.length > 1 ? i * step : width / 2, height - 2 - (v / max) * (height - 6)]);
  const line = points.map(([px, py], i) => `${i ? 'L' : 'M'}${px.toFixed(1)},${py.toFixed(1)}`).join('');
  const area = `${line}L${points[points.length - 1][0].toFixed(1)},${height}L${points[0][0].toFixed(1)},${height}Z`;
  return svg('svg', { class: 'spark', viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: 'none', 'aria-hidden': 'true' },
    svg('path', { class: 'spark-area', d: area }),
    svg('path', { class: 'spark-line', d: line, 'vector-effect': 'non-scaling-stroke' }));
}

function meter(fraction, cls = '') {
  const percent = Math.max(0, Math.min(100, fraction * 100));
  return h('span', { class: 'meter', 'aria-hidden': 'true' }, h('span', { class: cls, style: `width: ${percent}%` }));
}

function segmented(label, choices, value, onChange) {
  return h('div', { class: 'segmented', role: 'radiogroup', 'aria-label': label },
    choices.map(([key, text]) => h('button', {
      type: 'button',
      role: 'radio',
      class: key === value ? 'on' : '',
      'aria-checked': key === value ? 'true' : 'false',
      onclick: () => { if (key !== value) onChange(key); },
      text,
    })));
}

function panel(title, { sub, tools, cls } = {}, ...body) {
  return h('section', { class: `panel ${cls || ''}` },
    h('header', { class: 'panel-head' },
      h('div', { class: 'panel-heading' }, h('h2', { class: 'panel-title', text: title }), sub ? h('p', { class: 'panel-sub', text: sub }) : null),
      tools || null),
    body);
}

function dataTable(columns, rows) {
  return h('div', { class: 'table-wrap' }, h('table', { class: 'data-table' },
    h('thead', {}, h('tr', {}, columns.map(([text, cls]) => h('th', { class: cls || '', scope: 'col', text })))),
    h('tbody', {}, rows)));
}

// --- sections ------------------------------------------------------------------------------------

const VIEWS = {};

// --- overview ------------------------------------------------------------------------------------

const RANGES = [[7, '7 days'], [14, '14 days'], [30, '30 days'], [0, 'All time']];
const CHANNELS = [
  { key: 'naukri', label: 'Naukri', cls: 's-naukri' },
  { key: 'boards', label: 'Job boards', cls: 's-boards' },
  { key: 'company', label: 'Company sites', cls: 's-company' },
];
const KINDS = [
  ['sent', 'Sent'],
  ['waiting', 'Needs you'],
  ['skipped', 'Not tried'],
  ['failed', 'Failed'],
];
const NOT_SENT = {
  waiting: (n) => `${num(n)} ${n === 1 ? 'needs' : 'need'} you`,
  skipped: (n) => `${num(n)} not tried`,
  failed: (n) => `${num(n)} failed`,
};
const FUNNELS = [['all', 'All'], ['naukri', 'Naukri'], ['boards', 'Job boards']];

async function loadOverview() {
  const days = S.overviewDays;
  if (S.overviewLoading === days) return;
  S.overviewLoading = days;
  try {
    const data = await api(`/api/overview?days=${days}`);
    if (days === S.overviewDays) S.overview = { days, data, at: Date.now(), error: '' };
  } catch (error) {
    if (days === S.overviewDays) S.overview = { ...(S.overview || {}), days, at: Date.now(), error: error.message };
  } finally {
    if (S.overviewLoading === days) S.overviewLoading = null;
  }
  if (S.route.name === 'overview') maybeRender();
}

function setRange(days) {
  S.overviewDays = days;
  localStorage.setItem('overview-days', String(days));
  loadOverview();
  render(false);
}

function rangeText(d) {
  if (!d.days) return d.first ? `Since ${shortDate(d.first)}` : 'Nothing recorded yet';
  return `${shortDate(d.start)} – ${shortDate(d.end)}`;
}

function changeFrom(now, earlier, days) {
  if (earlier === null || earlier === undefined || (!now && !earlier)) return null;
  const diff = now - earlier;
  const text = diff === 0 ? `Same as the ${days} days before` : `${num(Math.abs(diff))} ${diff > 0 ? 'more' : 'fewer'} than the ${days} days before`;
  return h('span', { class: 'kpi-change', text });
}

function kpi({ label, value, unit, sub, change, extra, href }) {
  return h(href ? 'a' : 'div', { class: `kpi ${href ? 'kpi-link' : ''}`, href },
    h('span', { class: 'kpi-label', text: label }),
    h('span', { class: 'kpi-value' }, h('span', { class: 'tabular', text: value }), unit ? h('span', { class: 'kpi-unit', text: unit }) : null),
    sub ? h('span', { class: 'kpi-sub', text: sub }) : null,
    change || null,
    extra || null);
}

function kpis(d) {
  const st = S.status;
  const period = d.days ? `in the last ${d.days} days` : 'since the first run';
  const waiting = st.questions.length + st.facts.length + st.sites.length;
  const quota = d.quota;
  return h('div', { class: 'kpis' },
    kpi({
      label: `Sent ${period}`,
      value: num(d.sent.total),
      sub: `${num(d.sent.naukri)} on Naukri · ${num(d.sent.boards)} on job boards · ${num(d.sent.company)} on company sites`,
      change: changeFrom(d.sent.total, d.sent.before, d.days),
      extra: sparkline(d.daily.map((r) => r.naukri + r.boards + r.company)),
    }),
    kpi({
      label: 'Naukri’s daily limit',
      value: num(quota.used),
      unit: `of ${num(quota.limit)}`,
      sub: `Used in the last 24 hours; ${num(Math.max(0, quota.limit - quota.used))} left`,
      extra: meter(quota.limit ? quota.used / quota.limit : 0, quota.used >= quota.limit ? 'meter-full' : ''),
    }),
    kpi({
      label: `Jobs found ${period}`,
      value: num(d.found.total),
      sub: `${num(d.found.over)} scored ${d.min_score} or more`,
      change: changeFrom(d.found.total, d.found.before, d.days),
      extra: meter(d.found.total ? d.found.over / d.found.total : 0),
    }),
    kpi({
      label: 'Waiting for you',
      value: num(waiting),
      sub: [counted(st.questions.length, 'question'), counted(st.facts.length, 'blank fact'), counted(st.sites.length, 'company site')].join(' · '),
      href: st.questions.length + st.facts.length ? '#/todo' : '#/sites',
    }));
}

function sentPanel(d) {
  const rows = d.daily;
  const short = rows.length <= 8;
  const xLabel = (r) => localDay(r.day).toLocaleDateString('en-GB', short ? { weekday: 'short', day: 'numeric' } : { day: 'numeric', month: 'short' }).replace('Sept', 'Sep');
  const tip = (r, total) => {
    const unsent = Object.entries(NOT_SENT).filter(([key]) => r[key]).map(([key, phrase]) => phrase(r[key]));
    return [
      tipTitle(longDate(r.day)),
      ...CHANNELS.map((c) => tipRow(c.label, num(r[c.key]), c.cls)),
      tipRow('Sent', num(total)),
      unsent.length ? h('div', { class: 'tip-note', text: `Not sent: ${unsent.join(', ')}.` }) : null,
    ];
  };
  const best = rows.reduce((top, r) => (r.naukri + r.boards + r.company > top.n ? { n: r.naukri + r.boards + r.company, day: r.day } : top), { n: 0, day: '' });
  const label = `Applications sent per day, ${rangeText(d)}: ${num(d.sent.total)} in all${best.n ? `, most on ${longDate(best.day)} (${num(best.n)})` : ''}.`;
  return panel('Applications sent per day', {
    sub: best.n ? `Busiest day: ${shortDate(best.day)}, ${counted(best.n, 'application')}` : 'Nothing sent in this period',
    tools: h('div', { class: 'legend' }, CHANNELS.map((c) => h('span', { class: 'legend-item' }, h('span', { class: `swatch ${c.cls}` }), c.label))),
    cls: 'span-8',
  }, columnsChart({ rows, series: CHANNELS, label, xLabel, tip }));
}

function todayPanel() {
  const st = S.status;
  const questions = st.questions.length;
  const facts = st.facts.length;
  const sites = st.sites.length;
  const items = [];
  items.push(st.report.ready
    ? statusItem('ok', 'Today’s report is ready.', link('#/reports', 'Read it'))
    : statusItem('idle', 'No report yet today. Each run writes one at the end.', link('#/reports', 'Reports')));
  if (questions) items.push(statusItem('warn', `${counted(questions, 'question')} ${questions === 1 ? 'waits' : 'wait'} for your answer; jobs that ask ${questions === 1 ? 'it' : 'them'} are skipped.`, link('#/todo', 'Answer')));
  if (facts) items.push(statusItem('warn', `${counted(facts, 'fact')} in your profile ${facts === 1 ? 'is' : 'are'} blank; forms that need ${facts === 1 ? 'it' : 'them'} are left for you.`, link('#/todo', 'Fill in')));
  if (sites) items.push(statusItem('warn', `${counted(sites, 'company-site application')} ${sites === 1 ? 'waits' : 'wait'} for you.`, link('#/sites', 'See them')));
  const today = st.study.today;
  if (today) items.push(statusItem('study', `Study ${today.title}, day ${today.number} of ${today.total}${today.revising ? ' (revision)' : ''}.`, h('a', { class: 'link', href: readerHref(today.path), text: 'Read' })));
  if (!questions && !facts && !sites) items.push(statusItem('ok', 'Nothing else waits for you.'));
  return panel('Today', { cls: 'span-4' },
    h('ul', { class: 'status-list' }, items),
    h('div', { class: 'panel-foot' },
      quickButton('report', 'Build today’s report', {}, { tone: 'sm' }),
      quickButton('linkedin', 'Draft a LinkedIn post', { mode: 'dry-run' }, { tone: 'sm' })));
}

function funnelBody(group, d) {
  const f = d.funnel[group];
  const out = d.funnel.left_out;
  const skipped = [
    out.practice ? counted(out.practice, 'practice run') : '',
    out.older ? `${counted(out.older, 'older run')} that didn’t record these steps` : '',
    out.unfinished ? `${counted(out.unfinished, 'run')} with no end recorded` : '',
  ].filter(Boolean);
  const note = skipped.length ? h('p', { class: 'panel-note', text: `Left out: ${skipped.join(', ')}.` }) : null;
  if (!f.runs) return [h('p', { class: 'panel-empty', text: 'No finished real runs in this period.' }), note];
  const first = f.steps[0].count;
  const rows = f.steps.map((step, i) => h('div', { class: 'funnel-row' },
    h('span', { class: 'funnel-label', text: step.label }),
    h('span', { class: 'funnel-track' }, h('span', { class: `funnel-bar step-${step.key}`, style: `width: ${first ? (step.count / first) * 100 : 0}%` })),
    h('span', { class: 'funnel-count tabular', text: num(step.count) }),
    h('span', { class: 'funnel-kept tabular', text: i ? share(step.count, f.steps[i - 1].count) : '' })));
  const reasons = (title, list) => (list.length ? h('p', { class: 'funnel-why' },
    h('span', { class: 'funnel-why-title', text: title }),
    list.map((r) => h('span', { class: 'chip-soft' }, `${r.label} `, h('b', { class: 'tabular', text: num(r.count) })))) : null);
  return [
    h('div', { class: 'funnel' },
      h('div', { class: 'funnel-row funnel-head' }, h('span', {}), h('span', {}), h('span', { text: 'Jobs' }), h('span', { text: 'Kept' })),
      rows),
    reasons('Dropped before Eligible', f.dropped),
    reasons('Tried but not sent', f.unsent),
    h('p', { class: 'panel-note', text: `From ${counted(f.runs, 'finished real run')}. “Kept” is the share of the step above.` }),
    note,
  ];
}

function funnelPanel(d) {
  const body = h('div', { class: 'panel-body' });
  const tools = h('div', {});
  const draw = (group) => {
    S.funnelGroup = group;
    tools.replaceChildren(segmented('Which runs', FUNNELS, group, draw));
    body.replaceChildren(...funnelBody(group, d));
  };
  draw(S.funnelGroup || 'all');
  return panel('Where the jobs went', { sub: 'Each run’s steps, added up', tools, cls: 'span-6' }, body);
}

function outcomesPanel(d) {
  const total = d.attempts;
  if (!total) return panel('What happened to each attempt', { cls: 'span-6' }, h('p', { class: 'panel-empty', text: 'No attempts in this period.' }));
  const byKind = Object.fromEntries(KINDS.map(([key]) => [key, d.outcomes.filter((o) => o.kind === key).reduce((sum, o) => sum + o.count, 0)]));
  const present = KINDS.filter(([key]) => byKind[key]);
  return panel('What happened to each attempt', { sub: `${counted(total, 'attempt')} in this period`, cls: 'span-6' },
    h('div', { class: 'stackbar', role: 'img', 'aria-label': present.map(([key, text]) => `${text}: ${num(byKind[key])}`).join(', ') },
      present.map(([key, text]) => h('span', { class: `kind-${key}`, style: `flex-grow: ${byKind[key]}`, title: `${text}: ${num(byKind[key])} (${share(byKind[key], total)})` }))),
    h('div', { class: 'legend legend-wide' }, present.map(([key, text]) => h('span', { class: 'legend-item' },
      h('span', { class: `swatch kind-${key}` }), `${text} `, h('b', { class: 'tabular', text: num(byKind[key]) }), h('span', { class: 'muted tabular', text: ` ${share(byKind[key], total)}` })))),
    h('ul', { class: 'outcomes' }, d.outcomes.map((o) => h('li', { class: 'outcome' },
      h('span', { class: `swatch kind-${o.kind}` }),
      h('span', { class: 'outcome-label', text: o.label }),
      meter(o.count / total, `kind-${o.kind}`),
      h('span', { class: 'outcome-count tabular', text: num(o.count) })))));
}

function scoresPanel(d) {
  const scored = d.scores.reduce((sum, b) => sum + b.count, 0);
  if (!scored) return panel('Match scores', { cls: 'span-6' }, h('p', { class: 'panel-empty', text: 'No scored jobs in this period.' }));
  return panel('Match scores', {
    sub: `${num(scored)} jobs scored${d.found.unscored ? `; ${num(d.found.unscored)} were never scored` : ''}`,
    cls: 'span-6',
  },
  scoresChart(d.scores, d.min_score, d.found.over),
  h('div', { class: 'legend' },
    h('span', { class: 'legend-item' }, h('span', { class: 'swatch score-over' }), `${d.min_score} or more`),
    d.scores.some((b) => b.count && scoreKind(b, d.min_score) === 'mixed')
      ? h('span', { class: 'legend-item' }, h('span', { class: 'swatch score-mixed' }), `Bucket with ${d.min_score} in it`) : null,
    h('span', { class: 'legend-item' }, h('span', { class: 'swatch score-under' }), `Under ${d.min_score}`)));
}

function overCell(item) {
  return h('td', {}, h('div', { class: 'cell-meter' },
    meter(item.found ? item.over / item.found : 0, 'score-over'),
    h('span', { class: 'tabular', text: num(item.over) }),
    h('span', { class: 'muted tabular', text: share(item.over, item.found) })));
}

function boardsPanel(d) {
  if (!d.boards.length) return panel('Job boards', { cls: 'span-6' }, h('p', { class: 'panel-empty', text: 'No jobs found in this period.' }));
  return panel('Job boards', { sub: 'Jobs first seen in this period, and what was sent from them', cls: 'span-6' },
    dataTable([['Board'], ['Found', 'num'], [`Scored ${d.min_score}+`], ['Average', 'num'], ['Sent', 'num']],
      d.boards.map((b) => h('tr', {},
        h('th', { scope: 'row', text: b.name }),
        h('td', { class: 'num tabular', text: num(b.found) }),
        overCell(b),
        h('td', { class: 'num tabular', text: b.average === null ? '–' : b.average.toFixed(1) }),
        h('td', { class: 'num tabular', text: num(b.sent) })))));
}

function searchesPanel(d) {
  const all = d.searches;
  if (!all.length) return panel('Searches', { cls: 'span-8' }, h('p', { class: 'panel-empty', text: 'No jobs found in this period.' }));
  const body = h('div', {});
  const draw = (open) => {
    S.searchesOpen = open;
    const shown = open ? all : all.slice(0, 8);
    body.replaceChildren(
      dataTable([['Search or feed'], ['Found', 'num'], [`Scored ${d.min_score}+`], ['Average', 'num']],
        shown.map((s) => h('tr', {},
          h('th', { scope: 'row' }, h('span', { class: 'search-name', text: s.search }), h('span', { class: 'search-boards', text: s.boards.join(' · ') })),
          h('td', { class: 'num tabular', text: num(s.found) }),
          overCell(s),
          h('td', { class: 'num tabular', text: s.average === null ? '–' : s.average.toFixed(1) })))),
      all.length > 8 ? h('button', { class: 'btn btn-ghost btn-sm more', type: 'button', onclick: () => draw(!open), text: open ? 'Show the top 8' : `Show all ${all.length}` }) : null);
  };
  draw(!!S.searchesOpen);
  return panel('Searches that find matches', { sub: `Sorted by how many jobs scored ${d.min_score} or more`, cls: 'span-8' }, body);
}

function studyPanel() {
  const c = S.course;
  const today = c.today;
  return panel('Study', { sub: `${c.read} of ${counted(c.total, 'module')} read`, cls: 'span-4' },
    today ? h('a', { class: 'study-today', href: readerHref(today.path) },
      h('span', { class: 'study-day', text: `Today · day ${today.number} of ${today.total}${today.revising ? ' · revision' : ''}` }),
      h('span', { class: 'study-title', text: today.title }),
      h('span', { class: 'study-next', text: `Tomorrow: ${today.tomorrow.title}` })) : null,
    h('ul', { class: 'tracks-mini' }, c.tracks.map((t) => {
      const read = t.modules.filter((m) => m.read).length;
      return h('li', {},
        h('span', { class: 'track-name', title: t.name, text: t.name }),
        meter(read / t.modules.length, 'study'),
        h('span', { class: 'tabular muted', text: `${read}/${t.modules.length}` }));
    })),
    h('div', { class: 'panel-foot' }, link('#/study', 'Open Study')));
}

function runsPanel(d) {
  if (!d.runs.length) return panel('Recent runs', { cls: 'span-12' }, h('p', { class: 'panel-empty', text: 'No runs in this period.' }));
  const cell = (value) => h('td', { class: 'num tabular', text: value === null || value === undefined ? '–' : num(value) });
  return panel('Recent runs', { sub: `The last ${counted(d.runs.length, 'run')} in this period, newest first`, cls: 'span-12' },
    dataTable([['Started'], ['Bot'], ['Kind'], ['Took'], ['Found', 'num'], ['Eligible', 'num'], ['Tried', 'num'], ['Sent', 'num']],
      d.runs.map((r) => h('tr', { class: r.finished ? '' : 'row-faint' },
        h('th', { scope: 'row', class: 'tabular', text: `${shortDate(r.day)}, ${r.time}` }),
        h('td', { text: r.bot }),
        h('td', {}, r.practice ? h('span', { class: 'pill pill-accent', text: 'Practice' }) : h('span', { class: 'muted', text: 'Real' })),
        h('td', { class: 'tabular', text: r.finished ? duration(r.seconds) : 'No end recorded' }),
        cell(r.found), cell(r.eligible), cell(r.tried), cell(r.sent)))));
}

VIEWS.overview = () => {
  const st = S.status;
  const ov = S.overview;
  if (!ov || ov.days !== S.overviewDays || Date.now() - ov.at > 60000) loadOverview();
  const d = ov && ov.data;
  const head = h('header', { class: 'page-head hello overview-head' },
    h('div', {},
      h('h1', { text: `${st.greeting}${st.name ? `, ${st.name}` : ''}.` }),
      h('p', { class: 'lead', text: st.date_long })),
    h('div', { class: 'head-actions' },
      quickButton('naukri', 'Practice run', { dry_run: true }),
      quickButton('naukri', 'Apply now', {}, { tone: 'primary', confirm: applyConfirm() })));
  const bar = h('div', { class: 'range-bar' },
    h('p', { class: 'range-text' }, d ? rangeText(d) : 'Loading…', ov && ov.days !== S.overviewDays ? h('span', { class: 'muted', text: ' · updating…' }) : null),
    segmented('Period', RANGES, S.overviewDays, setRange));
  if (!d) {
    const failed = ov && ov.error;
    return h('div', { class: 'page page-wide overview' }, head, bar,
      h('div', { class: 'dash' },
        panel('The numbers', { cls: 'span-8' }, failed
          ? h('div', { class: 'panel-empty' }, h('p', { text: failed }), h('button', { class: 'btn btn-sm', type: 'button', onclick: loadOverview, text: 'Try again' }))
          : h('p', { class: 'panel-empty', text: 'Reading the bots’ database…' })),
        todayPanel()));
  }
  const stale = ov.days !== S.overviewDays;
  if (!d.first) {
    return h('div', { class: 'page page-wide overview' }, head, bar,
      h('div', { class: 'dash' },
        panel('Nothing to chart yet', { cls: 'span-8' },
          h('p', { class: 'panel-empty', text: 'The charts fill in once a bot has run. Press Practice run to rank today’s jobs without applying anything.' })),
        todayPanel(),
        studyPanel()));
  }
  return h('div', { class: `page page-wide overview ${stale ? 'is-stale' : ''}` }, head, bar,
    kpis(d),
    h('div', { class: 'dash' },
      sentPanel(d),
      todayPanel(),
      funnelPanel(d),
      outcomesPanel(d),
      scoresPanel(d),
      boardsPanel(d),
      searchesPanel(d),
      studyPanel(),
      runsPanel(d)));
};


function statusItem(tone, text, action) {
  return h('li', { class: `status status-${tone}` }, h('span', { class: 'status-dot', 'aria-hidden': 'true' }), h('span', { class: 'status-text', text }), action || null);
}

function applyConfirm() {
  return {
    title: 'Apply on Naukri now?',
    body: 'It applies to real jobs with your current settings. Use Practice run to only rank them.',
    ok: 'Apply now',
  };
}

VIEWS.naukri = () => {
  const a = 'naukri';
  const values = form(a);
  return h('div', { class: 'page' },
    pageHead('Apply on Naukri', 'Finds fresh jobs that match your resume, ranks them, and applies to the best ones (Naukri allows 50 a day). Jobs that send you to a company site are tried there too. Writes today’s report at the end.'),
    card(
      h('div', { class: 'toggles' },
        toggle(a, 'dry_run', 'Practice run', 'Rank and report, never click Apply'),
        toggle(a, 'early_access', 'Also share interest on Early Access roles', 'Uses none of the quota'),
        toggle(a, 'early_access_only', 'Only Early Access', 'No search, no applying'),
        toggle(a, 'headless', 'Hide the browser window', 'Login is challenged more often')),
      h('div', { class: 'grid-2' },
        field('Apply to at most', textInput(a, 'limit', { placeholder: 'as many as today’s quota allows', inputmode: 'numeric' })),
        field('Screening answers', selectInput(a, 'answer_mode', S.meta.answer_modes)),
        field('Keywords', textInput(a, 'keywords', { placeholder: 'from your resume (e.g. GenAI, LLM, Python)' })),
        field('Location', textInput(a, 'location', { placeholder: 'from .env' }))),
      previewLine(a),
      row(runButton(a, 'Run', { confirm: () => (values.dry_run || values.early_access_only ? null : applyConfirm()) }))));
};

VIEWS.sites = () => {
  const st = S.status;
  const a = 'external';
  const list = st.sites.length
    ? h('div', { class: 'site-list' }, st.sites.map(siteCard))
    : empty('No company-site applications wait for you.');
  return h('div', { class: 'page' },
    pageHead('Company sites', 'Jobs whose Apply button leads to the company’s own website. The bot fills what it can and lists the rest in data/inputs/company_sites.md.'),
    section(st.sites.length ? `Waiting for you · ${st.sites.length}` : 'Waiting for you',
      card(
        toggle('assist', 'dry_run', 'Preview only', 'Show what would be filled, change nothing'),
        previewLine('assist'),
        row(runButton('assist', 'Fill waiting forms'),
          h('button', { class: 'btn', type: 'button', onclick: () => openEditor('company_sites') }, icon('edit', 'icon icon-sm'), 'Edit the list'))),
      list),
    section('Apply on one page',
      card(
        h('div', { class: 'grid-2' },
          field('Application link', textInput(a, 'url', { placeholder: 'https://…', type: 'url' }), 'The page with the application form'),
          field('Job title', textInput(a, 'title', { placeholder: 'for the tailored resume' })),
          field('Company', textInput(a, 'company'))),
        h('div', { class: 'toggles' },
          toggle(a, 'dry_run', 'Fill the form but do not press Submit'),
          toggle(a, 'no_tailor', 'Send the base resume instead of a tailored one'),
          toggle(a, 'headless', 'Hide the browser window')),
        previewLine(a),
        row(runButton(a, 'Apply on this page')))));
};

function siteCard(site) {
  const left = site['left for you'] || '';
  const why = left ? '' : site.why || '';
  const filled = site['already filled'] || '';
  const resume = site['resume to send'] || '';
  const siteUrl = safeUrl(site.site);
  const naukriUrl = safeUrl(site.naukri);
  return h('article', { class: 'site' },
    h('header', { class: 'site-head' },
      h('div', {},
        h('h3', { class: 'site-company', text: site.company || site.name }),
        site.title ? h('p', { class: 'site-title', text: site.title }) : null),
      h('div', { class: 'site-meta' },
        site.status ? h('span', { class: `pill ${/error|fail/i.test(site.status) ? 'pill-err' : 'pill-warn'}`, text: site.status }) : null,
        site.when ? h('span', { class: 'muted small tabular', text: site.when }) : null)),
    left ? h('p', { class: 'site-line' }, h('span', { class: 'site-key', text: 'Left for you' }), h('span', { text: left })) : null,
    why ? h('p', { class: 'site-line' }, h('span', { class: 'site-key', text: 'Why' }), h('span', { text: sentence(why) })) : null,
    filled ? h('p', { class: 'site-line muted' }, h('span', { class: 'site-key', text: 'Already filled' }), h('span', { text: filled })) : null,
    h('div', { class: 'row' },
      siteUrl ? h('a', { class: 'btn btn-primary', href: siteUrl, target: '_blank', rel: 'noopener noreferrer' }, 'Open the application', icon('external', 'icon icon-sm')) : null,
      naukriUrl ? h('a', { class: 'btn', href: naukriUrl, target: '_blank', rel: 'noopener noreferrer' }, 'Naukri listing', icon('external', 'icon icon-sm')) : null,
      resume ? h('button', { class: 'btn', type: 'button', title: resume, onclick: () => openPath(resume) }, icon('file', 'icon icon-sm'), 'Open the resume') : null));
}

VIEWS.profile = () => {
  const a = 'profile';
  return h('div', { class: 'page' },
    pageHead('Naukri profile', 'Recruiters see recently updated profiles first. This toggles a dot on your resume headline so the profile counts as updated. Uses none of the apply quota.'),
    card(
      h('div', { class: 'toggles' },
        toggle(a, 'dry_run', 'Check only', 'Open the headline editor, save nothing'),
        toggle(a, 'if_due', 'Only if a daily slot is due', '09:00, 13:30 and 18:30'),
        toggle(a, 'headless', 'Hide the browser window')),
      previewLine(a),
      row(runButton(a, 'Refresh now'))),
    section('Daily schedule',
      card(
        h('p', { class: 'muted', text: 'A macOS schedule can refresh the profile at each slot, even when this page is closed.' }),
        row(quickButton('profile_status', 'Schedule status'),
          quickButton('profile_install', 'Turn on the daily schedule', {}, {
            confirm: { title: 'Turn on the daily profile schedule?', body: 'It installs a macOS launch agent that refreshes the profile at 09:00, 13:30 and 18:30.', ok: 'Turn it on' },
          })))));
};

VIEWS.linkedin = () => {
  const a = 'linkedin';
  const values = form(a);
  return h('div', { class: 'page' },
    pageHead('LinkedIn post', 'One post a day: a fresh article on your topics, a short reaction in your own words, and an image card. Drafts land in data/linkedin/drafts/.'),
    card(
      h('div', { class: 'grid-2' },
        field('What to do', selectInput(a, 'mode', S.meta.linkedin_modes, 'dry-run')),
        field('Draft to publish', textInput(a, 'draft', { placeholder: 'today’s saved draft' }), 'Only used when publishing')),
      h('div', { class: 'toggles' }, toggle(a, 'headless', 'Hide the browser window')),
      previewLine(a),
      row(runButton(a, 'Run', {
        confirm: () => (values.mode === 'post'
          ? { title: 'Publish the draft on LinkedIn now?', body: 'Everyone in your network will see it.', ok: 'Publish', tone: 'danger' }
          : null),
      }))),
    section('Daily schedule',
      card(
        h('p', { class: 'muted', text: 'A macOS schedule can draft and post on its own each day.' }),
        row(quickButton('linkedin_status', 'Schedule status'),
          quickButton('linkedin_install', 'Turn on the daily schedule', {}, {
            confirm: { title: 'Turn on the daily LinkedIn schedule?', body: 'It installs a macOS launch agent that drafts and posts each day.', ok: 'Turn it on' },
          })))));
};

VIEWS.resume = () => {
  const a = 'resume';
  const values = form(a);
  const jd = h('textarea', {
    class: 'input textarea',
    rows: 10,
    placeholder: 'Paste the whole job description here.',
    oninput: (e) => { values.jd_text = e.target.value; schedulePreview(a); },
  });
  jd.value = values.jd_text || '';
  return h('div', { class: 'page' },
    pageHead('Tailor resume', 'Rewrites your resume for one job, using only what is true about you, and builds the PDF in data/resume/out/tailored/.'),
    card(
      h('div', { class: 'grid-2' },
        field('Job title', textInput(a, 'title')),
        field('Company', textInput(a, 'company'))),
      field('Job description', jd),
      field('…or a file with it', textInput(a, 'jd_file', { placeholder: 'path/to/job.txt' }), 'Used only when nothing is pasted above'),
      h('div', { class: 'toggles' }, toggle(a, 'headless', 'Hide the browser window')),
      previewLine(a),
      row(runButton(a, 'Tailor'),
        h('button', { class: 'btn', type: 'button', onclick: () => api('/api/open', { what: 'resumes' }).catch((e) => toast(e.message, 'error')) },
          icon('folder', 'icon icon-sm'), 'Open the resume folder'))));
};

VIEWS.reports = (arg) => {
  const st = S.status;
  const day = arg || st.date;
  const days = st.report.days.includes(st.date) ? st.report.days : [st.date, ...st.report.days];
  const picker = h('input', { class: 'input', type: 'date', max: st.date, value: day, 'aria-label': 'Pick a day',
    onchange: (e) => { if (e.target.value) location.hash = `#/reports/${e.target.value}`; } });
  const article = h('div', { class: 'report-body' }, h('p', { class: 'muted', text: 'Loading…' }));
  loadReport(day, article);
  return h('div', { class: 'page page-wide' },
    pageHead('Reports', 'One report a day: what was applied to, what is left for you, and the study module for today.'),
    h('div', { class: 'reports' },
      h('nav', { class: 'report-days', 'aria-label': 'Days' },
        picker,
        h('ul', {}, days.map((d) => h('li', {},
          h('a', { class: `day ${d === day ? 'active' : ''}`, href: `#/reports/${d}`, 'aria-current': d === day ? 'page' : null },
            h('span', { text: d === st.date ? 'Today' : shortDate(d) }),
            d === st.date ? h('span', { class: 'muted small', text: shortDate(d) }) : null))))),
      article));
};

async function loadReport(day, article) {
  let report = S.reports[day];
  if (!report) {
    try {
      report = await api(`/api/report?day=${encodeURIComponent(day)}`);
    } catch (error) {
      article.replaceChildren(empty(error.message));
      return;
    }
    if (report.exists) S.reports[day] = report;
  }
  const build = quickButton('report', report.exists ? 'Rebuild' : 'Build it', { day: report.day }, { tone: report.exists ? null : 'primary' });
  const toolbar = h('div', { class: 'report-toolbar' },
    h('span', { class: 'muted mono small', text: `data/reports/${report.day}/report.md` }),
    h('span', { class: 'spacer' }),
    report.exists ? h('button', { class: 'btn btn-ghost', type: 'button', onclick: () => openPath(`${S.meta.apply}/data/reports/${report.day}/report.md`) }, 'Open in an app') : null,
    build);
  const body = report.exists
    ? h('article', { class: 'prose' })
    : empty('No report for this day yet. Build it from what the bots recorded.');
  // The server renders the report with raw HTML turned off, so its markup is safe to insert.
  if (report.exists) body.innerHTML = report.html;
  article.replaceChildren(toolbar, body);
  updateRunButtons();
}

// --- study ---------------------------------------------------------------------------------------

function modules() {
  return S.course ? S.course.tracks.flatMap((t) => t.modules.map((m) => ({ ...m, track: t.name }))) : [];
}

function readerHref(path) {
  return `#/study/read/${path}`;
}

async function markRead(path, read) {
  try {
    await api('/api/course/read', { path, read });
  } catch (error) {
    toast(error.message, 'error');
    return false;
  }
  await refreshCourse();
  return true;
}

VIEWS.study = (arg) => {
  if (arg.startsWith('read/')) return reader(arg.slice(5));
  const course = S.course;
  const today = course.today;
  const percent = course.total ? Math.round((course.read / course.total) * 100) : 0;
  const todayCard = today
    ? card(
      h('p', { class: 'eyebrow', text: `${today.revising ? 'Revision' : 'Today'} · day ${today.number} of ${today.total}` }),
      h('h2', { class: 'study-title', text: today.title }),
      h('p', { class: 'muted', text: `${today.track} · tomorrow: ${today.tomorrow.title}` }),
      row(h('a', { class: 'btn btn-primary', href: readerHref(today.path) }, icon('book', 'icon icon-sm'), 'Read today’s module')))
    : card(h('p', { class: 'muted', text: 'The study plan has no module for today. Pick any module below.' }));

  return h('div', { class: 'page' },
    pageHead('Study', 'PrepForge, your interview course. Diagrams and code are drawn as on the course site.'),
    todayCard,
    section('Progress',
      h('div', { class: 'progress-row' },
        h('div', { class: 'progress', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': String(course.total), 'aria-valuenow': String(course.read) },
          h('span', { style: `width: ${percent}%` })),
        h('span', { class: 'muted tabular', text: `${course.read} of ${course.total} read` }))),
    section('Every module',
      h('div', { class: 'tracks' }, course.tracks.map((track) => {
        const read = track.modules.filter((m) => m.read).length;
        const hasToday = track.modules.some((m) => m.today);
        return h('details', { class: 'track', open: hasToday },
          h('summary', {},
            h('span', { class: 'track-name', text: track.name }),
            h('span', { class: 'muted small tabular', text: `${read} of ${track.modules.length}` })),
          h('ul', {}, track.modules.map((m) => h('li', { class: 'module' },
            h('button', {
              class: `read-mark ${m.read ? 'on' : ''}`,
              type: 'button',
              'aria-pressed': String(m.read),
              'aria-label': m.read ? `Mark ${m.title} not read` : `Mark ${m.title} read`,
              onclick: () => markRead(m.path, !m.read),
            }, icon('tick', 'icon icon-xs')),
            h('a', { class: 'module-link', href: readerHref(m.path), text: m.title }),
            m.today ? h('span', { class: 'pill pill-accent', text: 'Today' }) : null))));
      }))));
};

function reader(path) {
  const all = modules();
  let index = all.findIndex((m) => m.path === path);
  if (index < 0) index = 0;
  const title = h('span', { class: 'reader-title' });
  const track = h('span', { class: 'muted small' });
  const readButton = h('button', { class: 'btn', type: 'button' });
  const prev = h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Previous module' }, icon('left'));
  const next = h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Next module' }, icon('right'));
  const newTab = h('a', { class: 'btn btn-ghost', target: '_blank', rel: 'noopener' }, 'New tab', icon('external', 'icon icon-sm'));
  const frame = h('iframe', { class: 'reader-frame', title: 'Course module' });

  const show = (i, load) => {
    index = i;
    const m = all[i];
    if (!m) return;
    title.textContent = m.title;
    track.textContent = `${m.track} · ${i + 1} of ${all.length}`;
    readButton.replaceChildren(icon('tick', 'icon icon-sm'), m.read ? 'Read' : 'Mark read');
    readButton.className = `btn ${m.read ? 'btn-done' : ''}`;
    readButton.setAttribute('aria-pressed', String(m.read));
    prev.disabled = i === 0;
    next.disabled = i === all.length - 1;
    newTab.href = `/course/#/${m.route}`;
    history.replaceState(null, '', readerHref(m.path));
    S.route = { name: 'study', arg: `read/${m.path}` };
    if (load) frame.src = `/course/#/${m.route}`;
  };
  prev.onclick = () => show(index - 1, true);
  next.onclick = () => show(index + 1, true);
  readButton.onclick = async () => {
    const m = all[index];
    if (await markRead(m.path, !m.read)) {
      m.read = !m.read;
      show(index, false);
    }
  };
  frame.addEventListener('load', () => {
    const win = frame.contentWindow;
    const follow = () => {
      const route = decodeURIComponent((win.location.hash || '').replace(/^#\/?/, '').split('?')[0]);
      const found = all.findIndex((m) => m.route === route || m.route === route.replace(/\/$/, '') || `${m.route}/` === route);
      if (found >= 0 && found !== index) show(found, false);
    };
    try {
      win.addEventListener('hashchange', follow);
    } catch {
      // The course is served by this site, so this only fails if the frame navigated elsewhere.
    }
  });
  show(index, true);

  return h('div', { class: 'reader' },
    h('div', { class: 'reader-bar' },
      h('a', { class: 'btn btn-ghost', href: '#/study' }, icon('left', 'icon icon-sm'), 'Study'),
      h('div', { class: 'reader-heading' }, title, track),
      h('span', { class: 'spacer' }),
      prev, next, readButton, newTab),
    frame);
}

// --- to-dos --------------------------------------------------------------------------------------

async function saveTodo(kind, line, value) {
  try {
    await api(kind === 'q' ? '/api/answer' : '/api/fact', kind === 'q' ? { line, answer: value } : { line, value });
  } catch (error) {
    toast(error.message, 'error');
    return;
  }
  delete S.drafts[`${kind}${line}`];
  toast('Saved. The next run uses it.', 'ok');
  S.signature = '';
  await refreshStatus();
}

function todoRow(kind, line, label, { multiline, placeholder }) {
  const key = `${kind}${line}`;
  const control = h(multiline ? 'textarea' : 'input', {
    class: `input ${multiline ? 'textarea textarea-short' : ''}`,
    rows: multiline ? 2 : null,
    placeholder,
    'aria-label': label,
    oninput: (e) => { S.drafts[key] = e.target.value; },
    onkeydown: (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (control.value.trim()) saveTodo(kind, line, control.value);
      }
    },
  });
  control.value = S.drafts[key] || '';
  return h('li', { class: 'todo' },
    h('div', { class: 'todo-label' }, label),
    h('div', { class: 'todo-input' },
      control,
      h('button', { class: 'btn', type: 'button', onclick: () => {
        if (!control.value.trim()) { toast('Write an answer first.', 'warn'); control.focus(); return; }
        saveTodo(kind, line, control.value);
      } }, 'Save')));
}

VIEWS.todo = () => {
  const st = S.status;
  const questions = st.questions.length
    ? h('ul', { class: 'todos' }, st.questions.map((q) => todoRow('q', q.line,
      h('div', {}, q.questions.map((text) => h('p', { class: 'question', text }))),
      { multiline: true, placeholder: 'Your answer' })))
    : empty('No questions wait for you.');
  const facts = st.facts.length
    ? h('ul', { class: 'todos' }, st.facts.map((f) => todoRow('f', f.line,
      h('div', {}, h('p', { class: 'question', text: humanKey(f.key) }), h('p', { class: 'muted mono small', text: f.key })),
      { placeholder: 'Its value' })))
    : empty('No facts are blank.');
  return h('div', { class: 'page' },
    pageHead('Your to-dos', 'Things only you can do. Whatever you fill in here is used on the next run.'),
    section(st.questions.length ? `Questions employers asked · ${st.questions.length}` : 'Questions employers asked',
      h('p', { class: 'muted small' }, h('span', { class: 'mono', text: S.meta.files.answers }), ' · Enter saves an answer, Shift+Enter starts a new line.'),
      card(questions, row(h('button', { class: 'btn btn-ghost', type: 'button', onclick: () => openEditor('answers') }, icon('edit', 'icon icon-sm'), 'Edit the whole file')))),
    section(st.facts.length ? `Facts left blank · ${st.facts.length}` : 'Facts left blank',
      h('p', { class: 'muted small' }, h('span', { class: 'mono', text: S.meta.files.profile }), ' · Enter saves.'),
      card(facts, row(h('button', { class: 'btn btn-ghost', type: 'button', onclick: () => openEditor('profile') }, icon('edit', 'icon icon-sm'), 'Edit the whole file')))),
    section('Company-site applications',
      card(
        h('p', {}, st.sites.length
          ? `${counted(st.sites.length, 'application')} ${st.sites.length === 1 ? 'needs' : 'need'} you to finish on the company’s site.`
          : 'None wait for you.'),
        row(h('a', { class: 'btn', href: '#/sites' }, 'Company sites'),
          h('button', { class: 'btn btn-ghost', type: 'button', onclick: () => openEditor('company_sites') }, icon('edit', 'icon icon-sm'), 'Edit the list')))));
};

// --- setup ---------------------------------------------------------------------------------------

VIEWS.setup = () => {
  const item = (title, text, ...actions) => h('li', { class: 'setup-item' },
    h('div', {}, h('h3', { class: 'setup-title', text: title }), h('p', { class: 'muted', text })),
    h('div', { class: 'row' }, actions));
  return h('div', { class: 'page' },
    pageHead('Setup', 'One-time things, and checks when something looks wrong.'),
    card(h('ul', { class: 'setup' },
      item('Google sign-in', 'Sign in to Google once in the bot’s browser, so “Sign in with Google” works on company sites. Quit that Chrome window (⌘Q) when you are done.',
        quickButton('google', 'Sign in to Google')),
      item('Settings', 'Logins, search, schedule times. Kept in .env, which git never commits.',
        h('button', { class: 'btn', type: 'button', onclick: () => openEditor('env') }, icon('edit', 'icon icon-sm'), 'Edit settings')),
      item('Requirements', 'Install or update what the bots need.', quickButton('install', 'Install requirements')),
      item('Tests', 'Check that everything still works.', quickButton('tests', 'Run the tests')))));
};

// --- routing and rendering -----------------------------------------------------------------------

function parseRoute() {
  const raw = decodeURIComponent(location.hash.replace(/^#\/?/, ''));
  const [first, ...rest] = raw.split('/');
  const name = first === 'today' ? 'overview' : first;
  const known = SECTIONS.some(([key]) => key === name);
  return { name: known ? name : 'overview', arg: known ? rest.join('/') : '' };
}

function signatureFor(name) {
  const st = S.status;
  if (!st) return '';
  const parts = {
    overview: [st.date, st.report.ready, st.questions, st.facts, st.sites, st.study, st.greeting, S.overviewDays,
      S.overview && [S.overview.days, S.overview.data, S.overview.error], S.course],
    sites: [st.sites],
    todo: [st.questions, st.facts, st.sites.length],
    reports: [st.date, st.report.days],
    study: [S.course],
  }[name];
  return parts ? JSON.stringify(parts) : name;
}

function render(scrollTop = true) {
  if (!S.status || !S.meta || !S.course) return;
  const { name, arg } = S.route;
  const view = VIEWS[name];
  S.pendingRender = false;
  S.signature = `${name}/${arg}/${signatureFor(name)}`;
  content.replaceChildren(view(arg));
  if (scrollTop) content.scrollTop = 0;
  const title = SECTIONS.find(([key]) => key === name)[1];
  document.title = `${title} · Job hunt`;
  document.body.dataset.section = name;
  renderNav();
  updateRunButtons();
}

function maybeRender() {
  const { name, arg } = S.route;
  if (name === 'study' && arg.startsWith('read/')) return;
  const signature = `${name}/${arg}/${signatureFor(name)}`;
  if (signature === S.signature) return;
  if (content.contains(document.activeElement) && isTyping()) {
    S.pendingRender = true;
    return;
  }
  render(false);
}

content.addEventListener('focusout', () => setTimeout(() => {
  if (S.pendingRender && !(content.contains(document.activeElement) && isTyping())) maybeRender();
}, 0));

function renderNav() {
  const nav = document.getElementById('nav');
  const st = S.status;
  const badges = st ? { sites: st.sites.length, todo: st.questions.length + st.facts.length } : {};
  nav.replaceChildren(...SECTIONS.map(([key, title, iconName], i) => h('a', {
    class: `nav-item ${S.route.name === key ? 'active' : ''}`,
    href: `#/${key}`,
    title: `${title} (${(i + 1) % 10})`,
    'aria-current': S.route.name === key ? 'page' : null,
  },
  icon(iconName),
  h('span', { class: 'nav-title', text: title }),
  badges[key] ? h('span', { class: 'badge', 'aria-label': `${badges[key]} waiting`, text: String(badges[key]) }) : null,
  h('kbd', { class: 'nav-key', text: String((i + 1) % 10) }))));
}

function renderChips() {
  const st = S.status;
  const chips = document.getElementById('chips');
  if (!st) return;
  const out = [];
  out.push(st.report.ready
    ? h('a', { class: 'chip chip-ok', href: '#/reports' }, h('span', { class: 'dot' }), 'Today’s report ready')
    : h('a', { class: 'chip', href: '#/reports' }, h('span', { class: 'dot' }), 'No report yet today'));
  if (st.questions.length) out.push(h('a', { class: 'chip chip-warn', href: '#/todo' }, h('span', { class: 'dot' }), `${counted(st.questions.length, 'question')} ${st.questions.length === 1 ? 'needs' : 'need'} you`));
  if (st.facts.length) out.push(h('a', { class: 'chip chip-warn', href: '#/todo' }, h('span', { class: 'dot' }), `${counted(st.facts.length, 'blank fact')}`));
  const r = st.run;
  out.push(h('span', { class: 'spacer' }));
  if (r.running) {
    out.push(h('span', { class: 'chip chip-run' }, h('span', { class: 'dot pulse' }),
      h('span', { text: r.stopping ? `Stopping ${r.label}` : r.label }),
      h('span', { class: 'tabular run-clock', text: elapsed((Date.now() - S.runStartedAt) / 1000) })));
    out.push(h('button', { class: 'btn btn-danger btn-sm', type: 'button', onclick: stopRun }, icon('stop', 'icon icon-sm'), r.stopping ? 'Force stop' : 'Stop'));
  } else {
    out.push(h('span', { class: 'chip chip-idle' }, h('span', { class: 'dot' }), 'Nothing running'));
  }
  chips.replaceChildren(...out);
}

// --- the output console --------------------------------------------------------------------------

const consoleParts = {};

function buildConsole() {
  const box = document.getElementById('console');
  consoleParts.status = h('span', { class: 'console-status muted small' });
  consoleParts.stop = h('button', { class: 'btn btn-danger btn-sm', type: 'button', hidden: true, onclick: stopRun }, icon('stop', 'icon icon-sm'), 'Stop');
  consoleParts.size = h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Bigger output', onclick: () => cycleConsole() }, icon('up'));
  consoleParts.lines = h('div', { class: 'console-lines', role: 'log', 'aria-live': 'off' });
  consoleParts.empty = h('p', { class: 'console-empty', text: 'Pick a task, set its options and press Run. Its output streams here. Every command is one you could type in apply/ yourself.' });
  consoleParts.jump = h('button', { class: 'btn btn-sm console-jump', type: 'button', hidden: true, onclick: () => scrollConsole(true) }, icon('down', 'icon icon-sm'), 'Jump to latest');
  consoleParts.body = h('div', { class: 'console-body' }, consoleParts.empty, consoleParts.lines);
  consoleParts.body.addEventListener('scroll', () => { if (nearBottom()) consoleParts.jump.hidden = true; });
  box.replaceChildren(
    h('div', { class: 'console-head' },
      h('button', { class: 'console-title', type: 'button', onclick: () => cycleConsole() }, h('span', { text: 'Output' })),
      consoleParts.status,
      h('span', { class: 'spacer' }),
      consoleParts.stop,
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Copy the output', title: 'Copy', onclick: copyConsole }, icon('copy')),
      h('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Clear the output', title: 'Clear', onclick: clearConsole }, icon('trash')),
      consoleParts.size),
    consoleParts.body,
    consoleParts.jump);
  setConsoleSize(localStorage.getItem('console-size') || 'collapsed');
}

function setConsoleSize(size) {
  const box = document.getElementById('console');
  box.dataset.size = size;
  localStorage.setItem('console-size', size);
  const bigger = size !== 'expanded';
  consoleParts.size.replaceChildren(icon(bigger ? 'up' : 'down'));
  consoleParts.size.setAttribute('aria-label', bigger ? 'Bigger output' : 'Smaller output');
  consoleParts.size.title = bigger ? 'Bigger' : 'Smaller';
  if (size !== 'collapsed') scrollConsole(true);
}

function cycleConsole() {
  const order = ['collapsed', 'normal', 'expanded'];
  const box = document.getElementById('console');
  setConsoleSize(order[(order.indexOf(box.dataset.size) + 1) % order.length]);
}

function nearBottom() {
  const b = consoleParts.body;
  return b.scrollHeight - b.scrollTop - b.clientHeight < 40;
}

function scrollConsole(force) {
  const b = consoleParts.body;
  if (force || nearBottom()) {
    b.scrollTop = b.scrollHeight;
    consoleParts.jump.hidden = true;
  } else {
    consoleParts.jump.hidden = false;
  }
}

function lineClass(text) {
  if (text.startsWith('→ ')) return 'line-cmd';
  if (text.startsWith('✓ ')) return 'line-ok';
  if (text.startsWith('× ')) return 'line-err';
  if (text.startsWith('○ ')) return 'line-stop';
  if (/\b(ERROR|CRITICAL|Traceback)\b/.test(text)) return 'line-err';
  if (/\bWARNING\b/.test(text)) return 'line-warn';
  return '';
}

function appendLines(lines) {
  if (!lines.length) return;
  const follow = nearBottom();
  const frag = document.createDocumentFragment();
  for (const [, text] of lines) frag.append(h('div', { class: `line ${lineClass(text)}`, text: text || '\u00a0' }));
  consoleParts.lines.append(frag);
  while (consoleParts.lines.childElementCount > 5000) consoleParts.lines.firstElementChild.remove();
  consoleParts.empty.hidden = true;
  if (follow) scrollConsole(true);
  else consoleParts.jump.hidden = false;
}

function clearConsole() {
  consoleParts.lines.replaceChildren();
  consoleParts.empty.hidden = false;
  consoleParts.jump.hidden = true;
}

async function copyConsole() {
  const text = [...consoleParts.lines.children].map((l) => l.textContent.replace(/\u00a0/g, '')).join('\n');
  try {
    await navigator.clipboard.writeText(text);
    toast(text ? 'Copied the output.' : 'The output is empty.', 'info', 2000);
  } catch {
    toast('The browser didn’t allow copying.', 'warn');
  }
}

function renderConsoleStatus() {
  const r = S.status && S.status.run;
  if (!r) return;
  consoleParts.stop.hidden = !r.running;
  consoleParts.stop.lastChild.textContent = r.stopping ? 'Force stop' : 'Stop';
  if (r.running) {
    consoleParts.status.textContent = `${r.label} · ${elapsed((Date.now() - S.runStartedAt) / 1000)}`;
  } else if (r.last) {
    const l = r.last;
    const outcome = l.exit === 0 ? 'done in' : l.stopped ? 'stopped after' : `failed (exit ${l.exit}) after`;
    consoleParts.status.textContent = `${l.label} · ${outcome} ${elapsed(l.seconds)}`;
  } else {
    consoleParts.status.textContent = '';
  }
}

// --- polling -------------------------------------------------------------------------------------

function takeRun(run) {
  if (run.running) S.runStartedAt = Date.now() - run.seconds * 1000;
  if (S.status) {
    const was = S.status.run.running;
    S.status.run = { ...S.status.run, ...run };
    delete S.status.run.lines;
    if (was !== run.running) {
      renderChips();
      updateRunButtons();
    }
  }
  handleLast(run.last);
  renderConsoleStatus();
}

function handleLast(last) {
  const finished = last ? last.finished : null;
  if (!S.seenLast) {
    S.seenLast = true;
    S.lastFinished = finished;
    return;
  }
  if (!last || finished === S.lastFinished) return;
  S.lastFinished = finished;
  if (last.exit === 0) toast(`${last.label}: done in ${elapsed(last.seconds)}.`, 'ok');
  else if (last.stopped) toast(`${last.label}: stopped after ${elapsed(last.seconds)}.`, 'warn');
  else toast(`${last.label} failed (exit ${last.exit}). The output shows why.`, 'error', 8000);
  if (last.action === 'report' || last.action === 'naukri') S.reports = {};
  refreshStatus();
  refreshCourse();
  loadOverview();
  if (last.action === 'report' && last.exit === 0 && last.day) {
    const target = `#/reports/${last.day}`;
    if (location.hash === target) render(false);
    else location.hash = target;
  }
}

async function refreshStatus() {
  try {
    S.status = await api('/api/status');
  } catch {
    return;
  }
  takeRun(S.status.run);
  renderChips();
  updateRunButtons();
  if (document.getElementById('nav').childElementCount) renderNav();
  maybeRender();
}

async function refreshCourse() {
  try {
    S.course = await api('/api/course');
  } catch {
    return;
  }
  if (S.status) S.status.study = { today: S.course.today, read: S.course.read, total: S.course.total };
  maybeRender();
}

let runTimer = null;

async function pollRun() {
  clearTimeout(runTimer);
  try {
    const run = await api(`/api/run?after=${S.runNext}`);
    if (run.next < S.runNext) S.runNext = 0;
    appendLines(run.lines.filter(([n]) => n >= S.runNext));
    S.runNext = run.next;
    takeRun(run);
  } catch {
    // The offline banner already says the server is gone; keep trying.
  }
  runTimer = setTimeout(pollRun, running() ? 700 : 3000);
}

setInterval(() => {
  if (!running()) return;
  const clock = document.querySelector('.run-clock');
  if (clock) clock.textContent = elapsed((Date.now() - S.runStartedAt) / 1000);
  renderConsoleStatus();
}, 1000);

setInterval(() => {
  if (document.hidden) return;
  refreshStatus();
  if (S.route.name === 'overview' && S.overview && Date.now() - S.overview.at > 60000) loadOverview();
}, 5000);
window.addEventListener('focus', () => {
  refreshStatus();
  if (S.route.name === 'overview' && (!S.overview || Date.now() - S.overview.at > 15000)) loadOverview();
});

// --- keys ----------------------------------------------------------------------------------------

document.addEventListener('keydown', (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target) || document.querySelector('dialog[open]')) return;
  if (/^[0-9]$/.test(e.key)) {
    const index = (Number(e.key) + 9) % 10;
    location.hash = `#/${SECTIONS[index][0]}`;
    e.preventDefault();
  } else if (e.key === 'x' && running()) {
    stopRun();
  } else if (e.key === 'o') {
    cycleConsole();
  } else if (e.key === 'Escape' && S.route.name === 'study' && S.route.arg) {
    location.hash = '#/study';
  }
});

window.addEventListener('hashchange', () => {
  const next = parseRoute();
  if (next.name === S.route.name && next.arg === S.route.arg) return;
  S.route = next;
  render();
  content.focus({ preventScroll: true });
});

// --- start ---------------------------------------------------------------------------------------

async function start() {
  buildConsole();
  S.route = parseRoute();
  renderNav();
  if (!content.childElementCount) content.append(h('p', { class: 'loading muted', text: 'Loading…' }));
  try {
    [S.meta, S.status, S.course] = await Promise.all([api('/api/meta'), api('/api/status'), api('/api/course')]);
  } catch (error) {
    content.replaceChildren(empty(error.message));
    setTimeout(start, 3000);
    return;
  }
  takeRun(S.status.run);
  renderChips();
  render();
  pollRun();
}

start();
