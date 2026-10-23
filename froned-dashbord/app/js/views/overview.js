import { h, svg } from "../dom.js";
import { recordTable } from './records.js';
import { stageName } from './automations.js';
import { BOTS, selectBot, botIcon, refreshBots } from './bots.js';
import { avatar, workspaceAvatar, brandMark, richIcon } from '../components/identity.js';
import { icon } from '../icons.js';
import { api } from "../api.js";
import { S, setOverviewDays } from "../state.js";
import { panel, empty, dataTable } from "../components/panel.js";
import { kpiCard } from "../components/kpi.js";
import { segmented } from "../components/segmented.js";
import { meter, donutChart, sparkline, columnsChart, scoresChart, scoreKind } from "../components/charts.js";
import { quickButton, liveRunConfirm } from "../forms.js";
import { num, counted, share, shortDate, longDate, localDay, duration, rangeText, changeFrom } from "../format.js";
import { routeHref } from "../router.js";
import { hooks } from "../state.js";

export const RANGES = [[7, "7 days"], [14, "14 days"], [30, "30 days"], [0, "All time"]];
const CHANNELS = [
  { key: "naukri", label: "Naukri", cls: "s-naukri" },
  { key: "boards", label: "Job boards", cls: "s-boards" },
  { key: "company", label: "Company sites", cls: "s-company" },
];
const KINDS = [
  ["sent", "Sent"],
  ["waiting", "Needs you"],
  ["skipped", "Not tried"],
  ["failed", "Failed"],
];
const NOT_SENT = {
  waiting: (n) => `${num(n)} ${n === 1 ? "needs" : "need"} you`,
  skipped: (n) => `${num(n)} not tried`,
  failed: (n) => `${num(n)} failed`,
};
const FUNNELS = [["all", "All"], ["naukri", "Naukri"], ["boards", "Job boards"]];

async function loadOverview(fresh=false) {
  const days = S.overviewDays;
  if (S.overviewLoading === days) return;
  S.overviewLoading = days;
  try {
    const data = await api(`/api/overview?days=${days}`,undefined,{fresh:!!fresh});
    if (days === S.overviewDays) S.overview = { days, data, at: Date.now(), error: "" };
  } catch (error) {
    if (days === S.overviewDays) S.overview = { ...(S.overview || {}), days, at: Date.now(), error: error.message };
  } finally {
    if (S.overviewLoading === days) S.overviewLoading = null;
  }
  if (["overview", "analytics"].includes(S.route.name)) hooks.requestRender(false);
}

function setRange(days) {
  setOverviewDays(days);
  loadOverview();
  hooks.requestRender(false);
}

function applyConfirm() {
  return liveRunConfirm("This submits real applications on Naukri, not a practice run.");
}

function kpis(d) {
  const st = S.status;
  const period = d.days ? `in the last ${d.days} days` : "since the first run";
  const waiting = st.questions.length + st.facts.length + st.sites.length;
  const quota = d.quota;
  return h(
    "div",
    { class: "kpis" },
    kpiCard({
      label: 'Applications sent',
      value: num(d.sent.total),
      sub: `${num(d.sent.naukri)} on Naukri · ${num(d.sent.boards)} on job boards · ${num(d.sent.company)} on company sites`,
      change: changeFrom(d.sent.total, d.sent.before, d.days),
      extra: sparkline(d.daily.map((r) => r.naukri + r.boards + r.company)),
    }),
    kpiCard({
      label: "Daily application quota",
      value: num(quota.used),
      unit: `of ${num(quota.limit)}`,
      sub: `Used in the last 24 hours; ${num(Math.max(0, quota.limit - quota.used))} left`,
      extra: meter(quota.limit ? quota.used / quota.limit : 0, quota.used >= quota.limit ? "meter-full" : ""),
    }),
    kpiCard({
      label: 'Opportunities found',
      value: num(d.found.total),
      sub: `${num(d.found.over)} scored ${d.min_score} or more`,
      change: changeFrom(d.found.total, d.found.before, d.days),
      extra: meter(d.found.total ? d.found.over / d.found.total : 0),
    }),
    kpiCard({
      label: 'Needs your attention',
      value: num(waiting),
      sub: [counted(st.questions.length, "question"), counted(st.facts.length, "blank fact"), counted(st.sites.length, "company site")].join(" · "),
      href: st.questions.length + st.facts.length ? routeHref("todo") : routeHref("sites"),
    }),
  );
}

function sentPanel(d) {
  const rows = d.daily;
  const short = rows.length <= 8;
  const xLabel = (r) =>
    localDay(r.day)
      .toLocaleDateString("en-GB", short ? { weekday: "short", day: "numeric" } : { day: "numeric", month: "short" })
      .replace("Sept", "Sep");
  const detailFor = r => Object.entries(NOT_SENT).filter(([key])=>r[key]).map(([key,phrase])=>phrase(r[key])).join(', ');
  const best = rows.reduce((top, r) => (r.naukri + r.boards + r.company > top.n ? { n: r.naukri + r.boards + r.company, day: r.day } : top), { n: 0, day: "" });
  const label = `Applications sent per day, ${rangeText(d)}: ${num(d.sent.total)} in all${best.n ? `, most on ${longDate(best.day)} (${num(best.n)})` : ""}.`;
  return panel(
    "Application activity",
    {
      sub: best.n ? `Busiest day: ${shortDate(best.day)}, ${counted(best.n, "application")}` : "Nothing sent in this period",
      cls: "span-8 activity-panel",
    },
    columnsChart({ rows, series: CHANNELS, label, xLabel, detailFor }),
    h('details', { class: 'chart-table' }, h('summary', { text: 'View daily breakdown' }), dataTable([['Date'], ...CHANNELS.map(c => [c.label, 'num'])], rows.map(r => h('tr', {}, h('th', { scope: 'row', text: shortDate(r.day) }), ...CHANNELS.map(c => h('td', { class: 'num tabular', text: num(r[c.key]) })))))),
  );
}

function statusItem(tone, text, extra) {
  return h("li", { class: "status-item" }, h("span", { class: `status-dot ${tone}` }), h("div", {}, h("span", { text }), extra ? h("div", {}, extra) : null));
}

function readerHref(route) {
  return `${(S.meta && S.meta.course) || "/course/"}#/${route}`;
}

function todayPanel() {
  const st = S.status;
  const questions = st.questions.length;
  const facts = st.facts.length;
  const sites = st.sites.length;
  const items = [];
  items.push(
    st.report.ready
      ? statusItem("ok", "Today’s report is ready.", h("a", { href: routeHref("reports"), text: "Read it" }))
      : statusItem("idle", "Today’s report hasn’t been built.", h("a", { href: routeHref("reports"), text: "View reports" })),
  );
  if (questions) items.push(statusItem("warn", `${counted(questions, "screening question")} to answer.`, h("a", { href: routeHref("todo"), text: "Add answers" })));
  if (facts) items.push(statusItem("warn", `${counted(facts, "profile detail")} to complete.`, h("a", { href: routeHref("todo"), text: "Complete profile" })));
  if (sites) items.push(statusItem("warn", `${counted(sites, "company application")} to finish.`, h("a", { href: routeHref("sites"), text: "Review applications" })));
  const today = st.study.today;
  if (today) items.push(statusItem("study", `Study ${today.title}, day ${today.number} of ${today.total}${today.revising ? " (revision)" : ""}.`, h("a", { class: "link", href: readerHref(today.route), target: "_blank", rel: "noopener", text: "Read" })));
  if (!questions && !facts && !sites) items.push(statusItem("ok", "Nothing else waits for you."));
  return panel(
    "On your radar",
    { cls: "span-4" },
    h("ul", { class: "status-list" }, items),
    h("div", { class: "panel-foot" }, quickButton("report", "Build today’s report", {}, { tone: "sm" }), quickButton("linkedin", "Draft a LinkedIn post", { mode: "dry-run" }, { tone: "sm" })),
  );
}

function funnelBody(group, d) {
  const f = d.funnel[group];
  const out = d.funnel.left_out;
  const skipped = [
    out.practice ? counted(out.practice, "practice run") : "",
    out.older ? `${counted(out.older, "older run")} that didn’t record these steps` : "",
    out.unfinished ? `${counted(out.unfinished, "run")} with no end recorded` : "",
  ].filter(Boolean);
  const note = skipped.length ? h("p", { class: "panel-note", text: `Left out: ${skipped.join(", ")}.` }) : null;
  if (!f.runs) return [h("p", { class: "panel-empty", text: "No finished real runs in this period." }), note];
  const first = f.steps[0].count;
  const rows = f.steps.map((step, i) =>
    h(
      "div",
      { class: "funnel-row" },
      h("span", { class: "funnel-label", text: step.label }),
      h("span", { class: "funnel-track" }, h("span", { class: `funnel-bar step-${step.key}`, style: { width: `${first ? (step.count / first) * 100 : 0}%` } })),
      h("span", { class: "funnel-count tabular", text: num(step.count) }),
      h("span", { class: "funnel-kept tabular", text: i ? share(step.count, f.steps[i - 1].count) : "" }),
    ),
  );
  const reasons = (title, list) =>
    list.length
      ? h("p", { class: "funnel-why" }, h("span", { class: "funnel-why-title", text: title }), list.map((r) => h("span", { class: "chip-soft" }, `${r.label} `, h("b", { class: "tabular", text: num(r.count) }))))
      : null;
  return [
    h("div", { class: "funnel" }, h("div", { class: "funnel-row funnel-head" }, h("span", {}), h("span", {}), h("span", { text: "Jobs" }), h("span", { text: "Kept" })), rows),
    reasons("Dropped before Eligible", f.dropped),
    reasons("Tried but not sent", f.unsent),
    h("p", { class: "panel-note", text: `From ${counted(f.runs, "finished real run")}. “Kept” is the share of the step above.` }),
    note,
  ];
}

function funnelPanel(d) {
  const body = h("div", { class: "panel-body" });
  const tools = h("div", {});
  const draw = (group) => {
    S.funnelGroup = group;
    tools.replaceChildren(segmented("Which runs", FUNNELS, group, draw));
    body.replaceChildren(...funnelBody(group, d));
  };
  draw(S.funnelGroup || "all");
  return panel("Where the jobs went", { sub: "Each run’s steps, added up", tools, cls: "span-6" }, body);
}

function outcomesPanel(d) {
  const total = d.attempts;
  if (!total) return panel("What happened to each attempt", { cls: "span-6" }, h("p", { class: "panel-empty", text: "No attempts in this period." }));
  const byKind = Object.fromEntries(KINDS.map(([key]) => [key, d.outcomes.filter((o) => o.kind === key).reduce((sum, o) => sum + o.count, 0)]));
  const present = KINDS.filter(([key]) => byKind[key]);
  return panel(
    "What happened to each attempt",
    { sub: `${counted(total, "attempt")} in this period`, cls: "span-6" },
    h('div',{class:'outcome-summary'},donutChart(present.map(([key,label])=>({key,label,value:byKind[key]})),total),
      h('div',{class:'outcome-legend'},present.map(([key,text])=>h('div',{class:'outcome-legend-row'},h('span',{class:`swatch kind-${key}`}),h('span',{text}),h('strong',{class:'tabular',text:num(byKind[key])}),h('span',{class:'muted tabular',text:share(byKind[key],total)}))))),
    h(
      "ul",
      { class: "outcomes" },
      d.outcomes.map((o) =>
        h(
          "li",
          { class: "outcome" },
          h("span", { class: `swatch kind-${o.kind}` }),
          h("span", { class: "outcome-label", text: o.label }),
          meter(o.count / total, `kind-${o.kind}`),
          h("span", { class: "outcome-count tabular", text: num(o.count) }),
        ),
      ),
    ),
  );
}

function scoresPanel(d) {
  const scored = d.scores.reduce((sum, b) => sum + b.count, 0);
  if (!scored) return panel("Match scores", { cls: "span-6" }, h("p", { class: "panel-empty", text: "No scored jobs in this period." }));
  return panel(
    "Match scores",
    { sub: `${num(scored)} jobs scored${d.found.unscored ? `; ${num(d.found.unscored)} were never scored` : ""}`, cls: "span-6" },
    scoresChart(d.scores, d.min_score, d.found.over),
    h(
      "div",
      { class: "legend" },
      h("span", { class: "legend-item" }, h("span", { class: "swatch score-over" }), `${d.min_score} or more`),
      d.scores.some((b) => b.count && scoreKind(b, d.min_score) === "mixed") ? h("span", { class: "legend-item" }, h("span", { class: "swatch score-mixed" }), `Bucket with ${d.min_score} in it`) : null,
      h("span", { class: "legend-item" }, h("span", { class: "swatch score-under" }), `Under ${d.min_score}`),
    ),
  );
}

function overCell(item) {
  return h("td", {}, h("div", { class: "cell-meter" }, meter(item.found ? item.over / item.found : 0, "score-over"), h("span", { class: "tabular", text: num(item.over) }), h("span", { class: "muted tabular", text: share(item.over, item.found) })));
}

function boardsPanel(d) {
  if (!d.boards.length) return panel("Job boards", { cls: "span-6" }, h("p", { class: "panel-empty", text: "No jobs found in this period." }));
  return panel(
    "Job boards",
    { sub: "Jobs first seen in this period, and what was sent from them", cls: "span-6" },
    dataTable(
      [["Board"], ["Found", "num"], [`Scored ${d.min_score}+`], ["Average", "num"], ["Sent", "num"]],
      d.boards.map((b) => h("tr", {}, h("th", { scope: "row", text: b.name }), h("td", { class: "num tabular", text: num(b.found) }), overCell(b), h("td", { class: "num tabular", text: b.average === null ? "–" : b.average.toFixed(1) }), h("td", { class: "num tabular", text: num(b.sent) }))),
    ),
  );
}

function searchesPanel(d) {
  const all = d.searches;
  if (!all.length) return panel("Searches", { cls: "span-8" }, h("p", { class: "panel-empty", text: "No jobs found in this period." }));
  const body = h("div", {});
  const draw = (open) => {
    S.searchesOpen = open;
    const shown = open ? all : all.slice(0, 8);
    body.replaceChildren(
      dataTable(
        [["Search or feed"], ["Found", "num"], [`Scored ${d.min_score}+`], ["Average", "num"]],
        shown.map((s) => h("tr", {}, h("th", { scope: "row" }, h("span", { class: "search-name", text: s.search }), h("span", { class: "search-boards", text: s.boards.join(" · ") })), h("td", { class: "num tabular", text: num(s.found) }), overCell(s), h("td", { class: "num tabular", text: s.average === null ? "–" : s.average.toFixed(1) }))),
      ),
      all.length > 8 ? h("button", { class: "btn btn-ghost btn-sm", type: "button", onclick: () => draw(!open), text: open ? "Show the top 8" : `Show all ${all.length}` }) : null,
    );
  };
  draw(!!S.searchesOpen);
  return panel("Searches that find matches", { sub: `Sorted by how many jobs scored ${d.min_score} or more`, cls: "span-12" }, body);
}

function runsPanel(d) {
  if (!d.runs.length) return panel("Recent runs", { cls: "span-12" }, h("p", { class: "panel-empty", text: "No runs in this period." }));
  const cell = (value) => h("td", { class: "num tabular", text: value === null || value === undefined ? "–" : num(value) });
  return panel(
    "Recent runs",
    { sub: `The last ${counted(d.runs.length, "run")} in this period, newest first`, cls: "span-12" },
    dataTable(
      [["Started"], ["Bot"], ["Kind"], ["Took"], ["Found", "num"], ["Eligible", "num"], ["Tried", "num"], ["Sent", "num"]],
      d.runs.map((r) =>
        h(
          "tr",
          { class: r.finished ? "" : "row-faint" },
          h("th", { scope: "row", class: "tabular", text: `${shortDate(r.day)}, ${r.time}` }),
          h("td", { text: r.bot }),
          h("td", {}, r.practice ? h("span", { class: "pill pill-accent", text: "Practice" }) : h("span", { class: "muted", text: "Real" })),
          h("td", { class: "tabular", text: r.finished ? duration(r.seconds) : "No end recorded" }),
          cell(r.found),
          cell(r.eligible),
          cell(r.tried),
          cell(r.sent),
        ),
      ),
    ),
  );
}

function dashboardHeader(title, sub, d, analytics = false) {
  return h('header',{class:'page-head'},h('div',{},h('p',{class:'eyebrow',text:analytics ? 'Insights' : S.status.date_long}),h('h1',{text:title}),h('p',{class:'lead',text:sub})),
    h('div',{class:'head-actions'},h('button',{class:'btn',type:'button',disabled:!d,onclick:()=>exportDaily(d)},icon('download','icon icon-sm'),'Export data'),h('a',{class:'btn btn-primary',href:'#/bots'},icon('bot','icon icon-sm'),'Open bot center')));
}
function compactMetrics(d) {
  const items=[
    ['Confirmed submissions',num(d.sent.total),'Submission records in this period','#/records/applications/submitted'],
    ['Jobs discovered',num(d.found.total),'Unique jobs first seen in this period','#/records/jobs'],
    ['Above match threshold',num(d.found.over),`Latest score of ${d.min_score} or higher`,'#/records/jobs/matched'],
    ['Naukri daily quota',num(d.quota.used),`of ${num(d.quota.limit)} used · rolling 24 hours`,'#/naukri'],
  ];
  return h('div',{class:'kpis compact-kpis'},items.map(([label,value,sub,href],i)=>h('a',{class:'kpi',href},
    h('div',{class:'metric-top'},h('span',{class:'kpi-label',text:label}),icon('arrow-up-right','icon icon-sm metric-arrow')),
    h('div',{class:'kpi-value',text:value}),h('p',{class:'kpi-sub',text:sub}),i===3 ? meter(d.quota.limit?d.quota.used/d.quota.limit:0) : null)));
}
function attentionPanel() {
  const st=S.status;
  const rows=[['todo','check','Screening questions',st.questions.length,'Add reusable answers'],['todo','person','Missing profile details',st.facts.length,'Complete your saved facts'],['sites','globe','Company follow-ups',st.sites.length,'Review your company worklist']];
  return panel('Needs your attention',{cls:'span-4 attention-panel',sub:'Current worklist · independent of date range'},
    h('div',{class:'attention-list'},rows.map(([route,name,title,count,sub])=>h('a',{class:'attention-item',href:routeHref(route)},h('span',{class:'attention-icon'},icon(name)),h('span',{class:'attention-copy'},h('strong',{text:title}),h('small',{text:sub})),h('span',{class:'attention-count',text:num(count)}),icon('arrow-up-right','icon icon-sm')))),
    h('div',{class:'attention-bottom'},icon(st.report.ready?'check':'file','icon icon-sm'),h('span',{text:st.report.ready ? 'Today’s report is ready' : 'Today’s report has not been built'}),h('a',{href:'#/reports',text:st.report.ready?'Read report':'Open reports'})));
}
function periodBar(d) {
  return h('div',{class:'range-bar'},h('div',{class:'data-freshness'},h('span',{class:'range-text',text:d ? rangeText(d) : 'Loading your activity…'}),d?.source ? h('span',{class:'freshness-time',text:`Updated ${new Date(d.source.updated_at).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'})}`}) : null,h('button',{class:'icon-btn',type:'button','aria-label':'Refresh overview',onclick:loadOverview},icon('refresh','icon icon-sm'))),segmented('Period',RANGES,S.overviewDays,setRange));
}
function pipelineSummary(d){
  const p=d.workspace?.pipeline;
  return panel('Your daily flow',{cls:'span-4 pipeline-summary',sub:'Saved progress · open Activity for live runs'},
    d.workspace_error ? h('p',{class:'inline-notice',text:d.workspace_error}) : !p?.total ? empty('No pipeline checkpoint for today.',h('a',{class:'btn',href:'#/pipeline',text:'Configure pipeline'})) : [
      h('div',{class:'pipeline-total'},h('strong',{text:`${p.done} / ${p.total}`}),h('span',{text:'stages complete'})),meter(p.done/p.total),
      h('ul',{class:'plain-list checkpoint-list'},p.stages.slice(0,5).map(stage=>h('li',{},icon(stage.status==='done'?'check':'activity','icon icon-sm'),h('a',{href:'#/pipeline/'+encodeURIComponent(stage.name),text:stageName(stage.name)}),h('span',{text:({done:'Done',pending:'Queued',running:'Saved as running',failed:'Needs attention'})[stage.status] || stage.status})))),
      h('a',{class:'text-link',href:'#/pipeline',text:`View all ${p.total} stages →`})]);
}
function platformSummary(d){
  return panel('Platform performance',{cls:'span-8 platform-panel',sub:'Discovered jobs and confirmed submissions in the selected period',tools:h('a',{class:'text-link',href:'#/analytics',text:'Full analytics →'})},
    dataTable([['Platform'],['Discovered','num'],['Matched','num'],['Submitted','num'],['Controls']],(d.boards || []).map(board=>h('tr',{},
      h('th',{scope:'row',text:({naukri:'Naukri',hirist:'Hirist',instahyre:'Instahyre',cutshort:'Cutshort',wellfound:'Wellfound',external:'Company sites'})[board.key] || board.label || board.key}),
      h('td',{class:'num tabular',text:num(board.found)}),h('td',{class:'num tabular',text:num(board.over)}),h('td',{class:'num tabular',text:num(board.sent)}),
      h('td',{},h('a',{class:'text-link',href:board.key==='naukri'?'#/naukri':board.key==='external'?'#/sites':'#/boards/'+board.key,'aria-label':'Configure '+board.key,text:'Configure'}))))));
}
function orbitHeader(d){
  const input=h('input',{type:'search',placeholder:'Find an application…','aria-label':'Search applications'});
  const search=h('form',{class:'launch-search',onsubmit:event=>{event.preventDefault();S.pendingRecordQuery=input.value;window.location.hash='#/records';}},icon('search'),input,h('button',{type:'submit','aria-label':'Search applications',class:'icon-btn'},icon('arrow-up-right','icon icon-sm')));
  return h('header',{class:'page-head orbit-head'},h('div',{},h('p',{class:'eyebrow',text:'YOUR LAUNCHPAD'}),h('h1',{text:`Hey${S.status.name?', '+S.status.name:''}. Let’s make moves.`}),h('p',{class:'lead',text:'Your applications, your crew, your next chapter.'})),h('div',{class:'orbit-utilities'},search,h('button',{class:'icon-btn export-button',type:'button','aria-label':'Export data',title:'Export daily activity',disabled:!d,onclick:()=>exportDaily(d)},icon('download')),h('a',{href:'#/files/profile','aria-label':'Open your profile'},avatar(workspaceAvatar(),'header-avatar'))));
}
function careerCard(d){
  return h('section',{class:'career-card','aria-label':'Application summary'},h('div',{class:'career-card-copy'},h('div',{class:'career-card-label'},brandMark('career-mark'),h('span',{text:'YOUR CAREER, IN MOTION'})),h('p',{class:'career-number'},h('strong',{text:num(d.sent.total)}),h('span',{text:'applications sent'})),h('p',{class:'career-context',text:`${num(d.sent.naukri)} on Naukri · ${num(d.sent.boards)} on job boards · ${num(d.sent.company)} on company sites`}),h('div',{class:'career-actions'},h('a',{class:'btn btn-primary',href:'#/records/applications/submitted'},'View applications',icon('arrow-up-right','icon icon-sm')),h('a',{class:'btn btn-ghost',href:'#/pipeline'},richIcon('refresh'),'Open Flows'))),h('div',{class:'career-art','aria-hidden':'true'},h('span',{class:'orbital-ring orbital-ring-back'}),avatar(12,'hero-avatar'),h('span',{class:'orbital-ring orbital-ring-front'}),h('span',{class:'orbit-satellite'})));
}
function orbitMetrics(d){
  return h('div',{class:'orbit-metrics'},[
    ['Jobs on your radar',num(d.found.total),'Unique jobs discovered','#/records/jobs','mint','search'],
    ['Worth a closer look',num(d.found.over),`Match score ≥ ${d.min_score}`,'#/records/jobs/matched','peach','check'],
    ['Naukri daily quota',`${num(d.quota.used)} / ${num(d.quota.limit)}`,'Used in the last 24 hours','#/naukri','lilac','activity'],
  ].map(([title,value,sub,href,tone,glyph])=>h('a',{class:`kpi orbit-metric metric-${tone}`,href},h('div',{class:'metric-top'},h('span',{class:'kpi-label',text:title}),icon('arrow-up-right','icon icon-sm')),h('strong',{class:'kpi-value',text:value}),h('p',{class:'kpi-sub',text:sub}))));
}
function crewShortcuts(){
  if(!S.bots || Date.now()-S.bots.at>15000)refreshBots();
  const picks=['naukri','hirist','linkedin','resume'].map(id=>BOTS.find(b=>b.id===id));
  return panel('Your Bot Crew',{cls:'crew-shortcuts',sub:'Specialists for your next step.',tools:h('span',{class:'crew-count',text:String(BOTS.length)})},h('div',{class:'crew-shortcut-grid'},picks.map(bot=>h('button',{type:'button',class:'crew-shortcut','aria-label':`Configure ${bot.name}`,onclick:()=>selectBot(bot)},botIcon(bot),h('span',{text:bot.id==='linkedin'?'LinkedIn':bot.id==='resume'?'Resume':bot.name})))),h('a',{class:'btn crew-all',href:'#/bots'},'Meet the whole crew',icon('arrow-up-right','icon icon-sm')));
}
export function renderOverview() {
  const ov=S.overview;
  if(!ov || ov.days!==S.overviewDays || Date.now()-ov.at>60000) loadOverview();
  const d=ov?.data;
  return h('div',{class:'page page-wide overview-page orbit-overview'},
    orbitHeader(d),
    periodBar(d),
    h('div',{class:'workspace-portals'},[[25,'Research Studio','Your .research notes, briefings & ideas','#/research'],[26,'Data hub','Records, saved files & resume downloads','#/data']].map(([art,title,sub,href])=>h('a',{class:'workspace-portal',href},avatar(art,'portal-art'),h('div',{},h('strong',{text:title}),h('span',{text:sub})),icon('arrow-up-right','icon icon-sm')))),
    ov?.error ? h('div',{class:'inline-notice',role:'alert'},d ? 'Could not refresh. Showing the last loaded records. ' : ov.error+' ',h('button',{class:'text-link',type:'button',text:'Try again',onclick:loadOverview})) : null,
    d && d.days!==S.overviewDays ? h('p',{class:'inline-notice',role:'status',text:'Updating the selected period. The records below still show the previous period.'}) : null,
    h('div',{class:'orbit-dashboard'},h('div',{class:'orbit-main'},d?.first ? [careerCard(d),orbitMetrics(d),sentPanel(d)] : panel(d ? 'Nothing to chart yet' : 'Your activity',{},empty(ov?.error || (d ? 'Start a practice run with your Bot Crew to discover opportunities.' : 'Reading your application history…'),h('a',{class:'btn',href:'#/bots',text:'Meet your crew'}))),
      d ? panel('Your latest moves',{cls:'recent-panel',sub:'Recent recorded attempts · all outcomes',tools:h('a',{class:'text-link',href:'#/records',text:'All applications →'})},d.recent?.length ? recordTable(d.recent,true) : empty('No application attempts in this period.')) : null,d ? platformSummary(d) : null),
      h('aside',{class:'orbit-aside','aria-label':'Crew and next steps'},crewShortcuts(),attentionPanel(),d ? pipelineSummary(d) : null,d ? panel('Make room to grow',{cls:'learning-summary',sub:'Your research, ready when you are.'},h('div',{class:'growth-illustration'},avatar(11,'growth-avatar'),h('div',{},h('strong',{text:d.workspace?num(d.workspace.research_count):'—'}),h('span',{text:'saved documents'}))),h('p',{class:'muted',text:d.workspace?`${num(d.workspace.learning_done)} learning days complete. Pick up a briefing, explore a skill, or prepare your next interview.`:'Research summary is unavailable. Open the library to retry.'}),h('div',{class:'panel-foot'},h('a',{class:'btn',href:'#/research',text:'Open Research Studio'}),h('a',{class:'text-link',href:'#/outreach',text:'Prepare recruiter drafts →'}))) : null)),
    h('div',{class:'overview-footer'},h('span',{},icon('info','icon icon-sm'),'Submission counts are recorded events, not unique roles.'),h('a',{class:'text-link',href:'#/records',text:'Inspect source records →'})));
}
export function renderAnalytics() {
  const ov=S.overview;
  if(!ov || ov.days!==S.overviewDays || Date.now()-ov.at>60000) loadOverview();
  const d=ov?.data;
  return h('div',{class:'page page-wide'},dashboardHeader('Insights','See what’s working. Decide where to go next.',d,true),periodBar(d),
    d?.first ? [kpis(d),h('div',{class:'dash'},sentPanel(d),todayPanel(),funnelPanel(d),outcomesPanel(d),scoresPanel(d),boardsPanel(d),searchesPanel(d),runsPanel(d))] : panel('Nothing to chart yet',{},empty(ov?.error || 'Your results will appear here once a bot has run.')));
}

function exportDaily(data) {
  if (!data) return;
  const keys = ['day', 'naukri', 'boards', 'company', 'waiting', 'skipped', 'failed'];
  const csv = [keys.join(','), ...data.daily.map(row => keys.map(key => row[key] ?? 0).join(','))].join('\r\n');
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const link = h('a', { href: url, download: `job-hunt-${data.start}-${data.end}.csv` });
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
