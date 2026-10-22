import { h } from '../dom.js';
import { icon } from '../icons.js';

let uid = 0;
function anchorMenu(menu, trigger, width) {
  if (innerWidth <= 600 && menu.classList.contains('calendar-menu')) {
    Object.assign(menu.style,{width:`${innerWidth-24}px`,left:'12px',top:'auto',bottom:'12px',maxHeight:`${innerHeight-24}px`});
    return;
  }
  const r = trigger.getBoundingClientRect();
  const w = Math.min(width || Math.max(r.width, 240), innerWidth - 24);
  const roomBelow = innerHeight - r.bottom - 16;
  const above = roomBelow < Math.min(menu.scrollHeight, 270) && r.top > roomBelow;
  Object.assign(menu.style, { width: `${w}px`, left: `${Math.max(12, Math.min(r.left, innerWidth - w - 12))}px`,
    top: above ? 'auto' : `${r.bottom + 8}px`, bottom: above ? `${innerHeight - r.top + 8}px` : 'auto',
    maxHeight: `${Math.max(120, above ? r.top - 24 : roomBelow)}px` });
}

/** One tab stop; selection stays on the combobox while arrows move its active descendant. */
export function selectControl({ options, value = '', label, onChange }) {
  const id = `orbit-select-${++uid}`;
  let current = String(value), active = 0, search = '', timer, lifecycle;
  const caption = h('span', { class: 'select-caption' });
  const trigger = h('button', { type: 'button', class: 'input select-trigger', role: 'combobox',
    'aria-label': label, 'aria-expanded': 'false', 'aria-haspopup': 'listbox', 'aria-controls': id }, caption, icon('chevron-down', 'icon icon-sm'));
  const menu = h('div', { id, class: 'control-menu select-menu', popover: 'auto', role: 'listbox', 'aria-label': label || 'Options' });
  const root = h('div', { class: 'select-control' }, trigger, menu);
  if(label) trigger.dataset.focusKey = `select:${label}`;
  root.controlElement = trigger;
  const opened = () => menu.matches(':popover-open');
  function highlight(index) {
    active = Math.max(0, Math.min(options.length - 1, index));
    [...menu.children].forEach((el, i) => el.classList.toggle('is-active', i === active));
    if (opened() && options.length) {
      trigger.setAttribute('aria-activedescendant', `${id}-${active}`);
      menu.children[active]?.scrollIntoView({ block: 'nearest' });
    }
  }
  function sync() {
    const chosen = options.find(o => String(o.value) === current);
    caption.textContent = chosen?.label || 'Choose an option';
    trigger.dataset.value = current;
    menu.replaceChildren(...options.map((o, i) => h('div', { id: `${id}-${i}`, class: 'select-option', role: 'option',
      'aria-selected': String(o.value) === current ? 'true' : 'false', dataset: { value: o.value },
      onpointerdown: e => e.preventDefault(), onpointermove: () => highlight(i), onclick: () => choose(i) },
      h('span', { text: o.label }), String(o.value) === current ? icon('check', 'icon icon-sm') : null)));
  }
  function close() { if (opened()) menu.hidePopover(); clearTimeout(timer);search='';trigger.setAttribute('aria-expanded','false');trigger.removeAttribute('aria-activedescendant'); }
  function choose(index) {
    if (!options[index]) return;
    current = String(options[index].value); sync(); close(); trigger.focus(); onChange?.(current);
  }
  function open() {
    if (opened()) return;
    sync(); menu.showPopover(); trigger.setAttribute('aria-expanded','true');anchorMenu(menu, trigger);
    highlight(Math.max(0, options.findIndex(o => String(o.value) === current)));
    const name = trigger.getAttribute('aria-labelledby');
    if (name) menu.setAttribute('aria-labelledby', name);
  }
  menu.addEventListener('toggle', e => {
    trigger.setAttribute('aria-expanded', e.newState === 'open' ? 'true' : 'false');
    lifecycle?.abort();
    if (e.newState === 'open') {
      lifecycle = new AbortController();
      const opts = { signal: lifecycle.signal };
      window.addEventListener('resize', close, opts); window.addEventListener('hashchange', close, opts);
    } else trigger.removeAttribute('aria-activedescendant');
  });
  trigger.addEventListener('click', () => opened() ? close() : open());
  trigger.addEventListener('keydown', e => {
    if (['ArrowDown','ArrowUp','Home','End'].includes(e.key)) {
      e.preventDefault(); const wasOpen = opened(); open();
      highlight(e.key === 'Home' ? 0 : e.key === 'End' ? options.length - 1 : active + (wasOpen ? (e.key === 'ArrowDown' ? 1 : -1) : 0));
    } else if (['Enter',' '].includes(e.key)) { e.preventDefault(); opened() ? choose(active) : open(); }
    else if (e.key === 'Escape') { e.preventDefault(); close(); }
    else if (e.key === 'Tab') close();
    else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey) {
      e.preventDefault(); clearTimeout(timer); search += e.key.toLowerCase();
      const exact = options.findIndex(o => o.label.toLowerCase() === search);
      const index = exact >= 0 ? exact : options.findIndex(o => o.label.toLowerCase().startsWith(search));
      open(); if (index >= 0) highlight(index); timer = setTimeout(() => { search = ''; }, 700);
    }
  });
  Object.defineProperty(root, 'value', { get: () => current, set: v => { current = String(v); sync(); } });
  root.setOptions = next => { options = next; sync(); };
  sync(); return root;
}

const iso = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
function parseDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const [y,m,d] = value.split('-').map(Number), date = new Date(y,m-1,d);
  return iso(date) === value ? date : null;
}
export function dateControl({ value = '', label, onChange, marked = [], commitOnly = false }) {
  const id = `orbit-calendar-${++uid}`;
  let selected = value, cursor = parseDate(value) || new Date(), month = new Date(cursor.getFullYear(),cursor.getMonth(),1);
  const error = h('span', { id: `${id}-error`, class: 'field-error', role: 'status', hidden: true });
  const input = h('input', { class: 'input date-input', type: 'text', placeholder: 'YYYY-MM-DD', value, inputmode: 'numeric',
    'aria-label': label, 'aria-describedby': error.id, autocomplete: 'off' });
  const button = h('button', { class: 'date-open', type: 'button', 'aria-label': label ? `Choose ${label.toLowerCase()}` : 'Choose date',
    'aria-haspopup': 'dialog', 'aria-expanded': 'false', 'aria-controls': id }, icon('calendar', 'icon'));
  const menu = h('div', { id, class: 'control-menu calendar-menu', popover: 'auto', role: 'dialog', 'aria-label': label ? `${label} calendar` : 'Choose a date' });
  const root = h('div', { class: 'date-control' }, h('div', { class: 'date-entry' }, input, button), error, menu);
  root.controlElement = input;
  function validate() {
    const invalid = !!input.value && !parseDate(input.value);
    input.setAttribute('aria-invalid', String(invalid)); error.hidden = !invalid;
    error.textContent = invalid ? 'Enter a real date as YYYY-MM-DD, or choose one from the calendar.' : '';
    return !invalid;
  }
  function close(focus = true) { if (menu.matches(':popover-open')) menu.hidePopover(); if (focus) button.focus(); }
  function choose(date) { selected = date ? iso(date) : ''; input.value = selected; validate(); close(); onChange?.(selected); }
  function moveMonth(delta) { month = new Date(month.getFullYear(),month.getMonth()+delta,1); cursor = new Date(month); draw(); }
  function focusCursor() { menu.querySelector(`[data-date="${iso(cursor)}"]`)?.focus({preventScroll:true}); }
  function draw() {
    const title = month.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
    const grid = h('div', { class: 'calendar-grid', role: 'grid', 'aria-label': title });
    grid.append(h('div', { class: 'calendar-week', role: 'row' }, ['Mo','Tu','We','Th','Fr','Sa','Su'].map(d => h('span', { role: 'columnheader', text: d }))));
    const start = new Date(month); start.setDate(1 - (start.getDay()+6)%7);
    for (let w = 0; w < 6; w++) {
      const row = h('div', { class: 'calendar-week', role: 'row' });
      for (let j = 0; j < 7; j++) {
        const day = new Date(start); day.setDate(start.getDate()+w*7+j);
        const key = iso(day), outside = day.getMonth() !== month.getMonth();
        const b = h('button', { type: 'button', class: `calendar-day${outside?' is-outside':''}${key===selected?' is-selected':''}${marked.includes(key)?' has-report':''}`,
          tabindex: key === iso(cursor) ? '0' : '-1', dataset: { date: key }, 'aria-label': day.toLocaleDateString(undefined,{weekday:'long',day:'numeric',month:'long',year:'numeric'}) + (marked.includes(key)?', saved report':''),
          'aria-current': key===iso(new Date())?'date':null, onclick: () => choose(day), text: String(day.getDate()),
          onkeydown: e => {
            const offset = { ArrowLeft:-1,ArrowRight:1,ArrowUp:-7,ArrowDown:7 }[e.key];
            if (offset || ['Home','End','PageUp','PageDown'].includes(e.key)) {
              e.preventDefault(); cursor = new Date(day);
              if (offset) cursor.setDate(cursor.getDate()+offset);
              else if (e.key === 'Home') cursor.setDate(cursor.getDate()-(cursor.getDay()+6)%7);
              else if (e.key === 'End') cursor.setDate(cursor.getDate()+6-(cursor.getDay()+6)%7);
              else {
                const wanted=cursor.getDate(),next=cursor.getMonth()+(e.key==='PageUp'?-1:1);
                cursor=new Date(cursor.getFullYear(),next,1);
                cursor.setDate(Math.min(wanted,new Date(cursor.getFullYear(),cursor.getMonth()+1,0).getDate()));
              }
              month = new Date(cursor.getFullYear(),cursor.getMonth(),1); draw(); focusCursor();
            }
          } });
        row.append(h('div', { role: 'gridcell', 'aria-selected': String(key===selected) }, b));
      }
      grid.append(row);
    }
    menu.replaceChildren(h('div', { class: 'calendar-head' }, h('button', { class: 'btn btn-icon', type: 'button', 'aria-label': 'Previous month', onclick: () => { moveMonth(-1); menu.querySelector('[aria-label="Previous month"]').focus(); } }, icon('chevron-left')),
      h('strong', { text: title, 'aria-live':'polite' }), h('button', { class: 'btn btn-icon', type: 'button', 'aria-label': 'Next month', onclick: () => { moveMonth(1); menu.querySelector('[aria-label="Next month"]').focus(); } }, icon('chevron-right'))),
      grid, h('div', { class: 'calendar-foot' }, h('button', { class: 'btn btn-sm', type: 'button', text: 'Clear date', onclick: () => choose(null) }), h('button', { class: 'btn btn-sm btn-primary', type: 'button', text: 'Today', onclick: () => choose(new Date()) })));
  }
  input.addEventListener('input', () => { selected=input.value; if(input.getAttribute('aria-invalid')==='true')validate(); if(!commitOnly)onChange?.(selected); });
  input.addEventListener('blur', () => { if(validate()&&commitOnly)onChange?.(input.value); });
  input.addEventListener('keydown', e=>{if(e.key==='Enter'&&validate()&&commitOnly){e.preventDefault();onChange?.(input.value);}});
  button.addEventListener('click', () => {
    if (menu.matches(':popover-open')) return close();
    cursor=parseDate(input.value)||new Date(); month=new Date(cursor.getFullYear(),cursor.getMonth(),1);
    draw(); menu.showPopover(); anchorMenu(menu, button, 332); focusCursor();
  });
  menu.addEventListener('toggle', e => button.setAttribute('aria-expanded', String(e.newState==='open')));
  menu.addEventListener('keydown', e => {
    if(e.key==='Escape'){e.preventDefault();close();}
    if(e.key==='Tab'){
      const tabs=[...menu.querySelectorAll('button:not([tabindex="-1"])')];
      if(e.shiftKey&&document.activeElement===tabs[0]){e.preventDefault();tabs.at(-1).focus();}
      else if(!e.shiftKey&&document.activeElement===tabs.at(-1)){e.preventDefault();tabs[0].focus();}
    }
  });
  return root;
}
