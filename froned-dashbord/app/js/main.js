import './dev-tools.js';
import { h } from './dom.js';
import { api } from './api.js';
import { S, hooks } from './state.js';
import { parseRoute, SECTIONS, navigate } from './router.js';
import { renderNav } from './components/nav.js';
import { initConsole, appendRunLines, clearConsoleLines, updateConsoleStatus } from './components/console.js';
import { updateRunButtons } from './forms.js';
import { loadingState, errorState } from './components/panel.js';
import { createRouteShell } from './route-shell.js';
import { invalidateReads } from './query-client.js';
const refreshBots=()=>import('./views/bots.js').then(m=>m.refreshBots());
const content = document.getElementById('content');
const shell=createRouteShell(content);
document.querySelector('.skip-link').addEventListener('click', event => { event.preventDefault(); content.focus(); });
let booting = false;
let timer;
let deferredRender;
S.forms = { naukri: { dry_run: true }, external: { dry_run: true }, profile: { dry_run: true },
  boards: { dry_run: true }, pipeline: { dry_run: true }, linkedin: { mode: 'dry-run' },
  linkedin_profile:{dry_run:true}, cold_email:{dry_run:true} };

function online(value) {
  const changed = S.online !== value;
  S.online = value;
  document.getElementById('offline').hidden = value;
  if (changed) renderNav();
}

function render(scroll = false) {
  if (!S.meta || !S.status || !S.course) return;
  clearTimeout(deferredRender);
  if (!scroll && content.querySelector(':popover-open')) {
    deferredRender = setTimeout(() => render(false), 180);
    return;
  }
  const focusKey = S.pendingFocusKey || (!scroll && document.activeElement?.dataset.focusKey);
  S.pendingFocusKey=null;
  const selection = focusKey && typeof document.activeElement.selectionStart === 'number' ? [document.activeElement.selectionStart,document.activeElement.selectionEnd] : null;
  const route={...S.route};
  shell.route(route,()=>{
    const page=content.querySelector('.page');
    if (['naukri','boards','sites','profile','linkedin','resume','outreach','linkedin-profile'].includes(route.name)) {
      page?.prepend(h('a',{class:'back-link',href:'#/bots',text:'← Bot Crew'}));
    }
    if(scroll && !window.matchMedia('(prefers-reduced-motion: reduce)').matches)page?.animate([{opacity:0,transform:'translateY(8px)'},{opacity:1,transform:'translateY(0)'}],{duration:260,easing:'cubic-bezier(.22,.8,.25,1)'});
    document.title=`${SECTIONS.find(([name])=>name===route.name)?.[1]||'Launchpad'} · Morrow`;
    updateRunButtons();
    if(focusKey){const target=[...content.querySelectorAll('[data-focus-key]')].find(el=>el.dataset.focusKey===focusKey);target?.focus({preventScroll:true});if(selection&&target?.setSelectionRange)target.setSelectionRange(...selection);}
    if(scroll){window.scrollTo(0,0);content.focus({preventScroll:true});}
  },()=>render(false));
  renderNav();
}

hooks.requestRender = (scroll = false) => {
  if (S.pendingRender) return;
  S.pendingRender = true;
  requestAnimationFrame(() => { S.pendingRender = false; render(scroll); });
};
hooks.refreshStatus = async () => {
  const previous = S.status;
  S.status = await api('/api/status', undefined, { onOnline: online });
  updateConsoleStatus(S.status.run);
  updateRunButtons();
  if(previous?.study && JSON.stringify(previous.study)!==JSON.stringify(S.status.study))await hooks.refreshCourse();
  if (JSON.stringify(previous && { ...previous, run: null }) !== JSON.stringify({ ...S.status, run: null })) {
    renderNav();
    if (['overview', 'todo', 'sites'].includes(S.route.name) && !content.contains(document.activeElement)) render();
  }
};
hooks.refreshCourse = async () => {
  S.course = await api('/api/course',undefined,{fresh:true});
  S.status.study = { today: S.course.today, read: S.course.read, total: S.course.total };
  if (S.route.name === 'study') render();
};

async function poll() {
  clearTimeout(timer);
  if (!document.hidden && S.meta) {
    try {
      const run = await api(`/api/run?after=${S.runNext}`, undefined, { onOnline: online });
      const finished = S.status.run.running && !run.running;
      if (run.next < S.runNext) clearConsoleLines();
      S.runNext = run.next;
      appendRunLines(run.lines || []);
      S.status.run = run;
      updateConsoleStatus(run);
      updateRunButtons();
      await hooks.refreshStatus();
      if (['overview', 'bots'].includes(S.route.name)) await refreshBots();
      if (finished || (S.route.name === 'overview' && S.overview && Date.now() - S.overview.at > 60000)) {
        S.overview = null;
        S.pipeline = null;
        if (finished) { await invalidateReads(); S.library=null; S.document=null; S.dataHub=null; }
        if (['overview', 'analytics', 'bots', 'pipeline', 'reports', 'research', 'records','data'].includes(S.route.name)) render();
      }
    } catch { online(false); }
  }
  timer = setTimeout(poll, S.status?.run.running ? 1200 : 5000);
}

async function boot() {
  if (booting) return;
  booting = true;
  shell.state(loadingState('Opening your workspace…'));
  try {
    // Load the first-screen data together: avoid rendering, then fetching, then replacing
    // the same headline twice while the overview and crew inventory arrive in sequence.
    const days=S.overviewDays;
    const initialRoute=parseRoute().name;
    const needsOverview=['overview','analytics'].includes(initialRoute);
    const needsBots=['overview','bots'].includes(initialRoute);
    const [meta,status,course,overview,bots]=await Promise.all([
      ...['/api/meta','/api/status','/api/course'].map(path=>api(path)),
      (needsOverview?api(`/api/overview?days=${days}`).then(data=>({days,data,at:Date.now(),error:''})).catch(error=>({days,at:Date.now(),error:error.message})):Promise.resolve(null)),
      (needsBots?api('/api/bots').then(data=>({data,at:Date.now()})).catch(error=>({at:Date.now(),error:error.message})):Promise.resolve(null)),
      shell.preload(initialRoute).catch(()=>{}),
    ]);
    S.meta=meta;S.status=status;S.course=course;S.overview=overview;S.bots=bots;
    online(true);
    S.route = parseRoute();
    updateConsoleStatus(S.status.run);
    render();
    clearTimeout(timer);
    timer = setTimeout(poll, 5000);
  } catch (error) {
    online(false);
    shell.state(errorState(`Your workspace is unavailable. ${error.message || 'Start the dashboard server, then reconnect.'}`, boot));
    timer = setTimeout(boot, 5000);
  } finally { booting = false; }
}

window.addEventListener('hashchange', () => { S.route = parseRoute(); render(true); });
window.addEventListener('beforeunload', event => {
  if (Object.values(S.loadedFiles).some(file => file.draft !== file.text)) { event.preventDefault(); event.returnValue = ''; }
});
document.addEventListener('visibilitychange', () => { if (!document.hidden) { clearTimeout(timer); S.meta ? poll() : boot();if(S.meta&&S.route.name==='study')hooks.refreshCourse().catch(()=>{}); } });
document.addEventListener('keydown', event => {
  if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || event.target.closest('input, textarea, select, [contenteditable], dialog, [role="combobox"], [role="slider"], [popover]')) return;
  if (/^[1-9]$/.test(event.key)) { event.preventDefault(); navigate(SECTIONS[Number(event.key) - 1][0]); }
});
initConsole();
renderNav();
boot();
