import { h } from "../dom.js";
import { api } from "../api.js";
import { S, hooks } from "../state.js";
import { panel, loadingState, errorState } from "../components/panel.js";
import { longDate } from "../format.js";
import { quickButton } from '../forms.js';
import { dateControl } from '../components/controls.js';
import { journeyBanner } from '../components/journey.js';
import { richIcon } from '../components/identity.js';
import { READER_STYLE } from '../components/reader.js';
import {selectControl} from '../components/controls.js';

const cache = new Map();
let loadingDay = null;

function dayLabel(day) {
  return day === S.status.date ? `Today, ${longDate(day)}` : longDate(day);
}

async function loadReport(day, fresh=false) {
  if (loadingDay === day) return;
  loadingDay = day;
  try {
    const data = await api(`/api/report?day=${encodeURIComponent(day)}`,undefined,{fresh});
    cache.set(day, { data, error: "" });
  } catch (error) {
    cache.set(day, { data: null, error: error.message });
  } finally {
    loadingDay = null;
  }
  if (S.route.name === "reports" && (!S.route.arg || S.route.arg === day)) hooks.requestRender(false);
}

export function renderReports(argDay) {
  const today = S.status.date;
  const days = S.status.report.days && S.status.report.days.length ? S.status.report.days : S.status.report.ready ? [today] : [];
  const day = argDay || days[0] || today;
  const entry = cache.get(day);
  if (!entry) loadReport(day);

  const select = dateControl({label:'Report date',value:day,marked:days,commitOnly:true,onChange:value=>{window.location.hash=value?`#/reports/${value}`:'#/reports';}});

  let body;
  if (!entry) {
    body = loadingState("Reading the report…");
  } else if (entry.error) {
    body = errorState(entry.error, () => loadReport(day));
  } else if (!entry.data.exists) {
    body = h("p", { class: "panel-empty", text: "No report was written for this day yet." });
  } else {
    const frame = h("iframe", {
      title: entry.data.title,
      sandbox: "allow-popups",
      style: { width: "100%", height: "70vh", border: "none", borderRadius: "10px", background: "#1b1d24" },
    });
    frame.srcdoc = READER_STYLE + entry.data.html;
    body = frame;
  }

  return h(
    "div",
    { class: "page reports-page" },
    h("header", { class: "page-head" }, h("div", {}, h("h1", { text: "Reports" }), h("p", { class: "lead", text: "A written summary the bots leave after every run." })), h("div", { class: "head-actions" }, select)),
    h('div',{class:'report-toolbar'},h('div',{class:'report-context'},richIcon('file'),h('div',{},h('strong',{text:`${days.length} saved reports`}),h('span',{class:'muted small',text:'Choose a day, then read at your own pace.'}))),
      selectControl({label:'Saved report',value:day,options:[...new Set([day,...days])].map(value=>({value,label:dayLabel(value)})),onChange:value=>{window.location.hash=`#/reports/${value}`;}})),
    panel(entry?.data?.exists ? entry.data.title : dayLabel(day), {cls:'focus-reader',tools:h('div',{class:'row'},quickButton('report','Build report',{day}),h('button',{class:'btn btn-sm',type:'button',text:'Refresh',onclick:()=>loadReport(day,true)}))},body),
  );
}
