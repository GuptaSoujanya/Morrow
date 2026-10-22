import { h } from './dom.js';
import { api } from './api.js';
import { S, hooks } from './state.js';
import { parseRoute, SECTIONS, navigate } from './router.js';
import { renderNav } from './components/nav.js';
import { initConsole, appendRunLines, clearConsoleLines, updateConsoleStatus } from './components/console.js';
import { updateRunButtons } from './forms.js';
import { loadingState, errorState } from './components/panel.js';
import { renderOverview, renderAnalytics } from './views/overview.js';
import { renderNaukri } from './views/naukri.js';
import { renderSites } from './views/sites.js';
import { renderProfile } from './views/profile.js';
import { renderLinkedin } from './views/linkedin.js';
import { renderResume } from './views/resume.js';
import { renderReports } from './views/reports.js';
import { renderStudy } from './views/study.js';
import { renderTodo } from './views/todo.js';
import { renderFiles } from './views/files.js';
import { renderSetup } from './views/setup.js';
import { renderBoards, renderPipeline } from './views/automations.js';

import { renderBots, refreshBots } from './views/bots.js';
import { renderRecords } from './views/records.js';
import { renderResearch } from './views/research.js';
import { renderData } from './views/data.js';
import { renderOutreach, renderLinkedinProfile } from './views/outreach.js';

const views = { bots: renderBots, analytics: renderAnalytics, overview: renderOverview, naukri: renderNaukri, sites: renderSites, profile: renderProfile,
  linkedin: renderLinkedin, resume: renderResume, reports: renderReports, study: renderStudy,
  todo: renderTodo, files: renderFiles, setup: renderSetup, boards: renderBoards, pipeline: renderPipeline,
  records:renderRecords, research:renderResearch, data:renderData, outreach:renderOutreach, 'linkedin-profile':renderLinkedinProfile };
const content = document.getElementById('content');
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
  try {
    const focusKey = !scroll && document.activeElement?.dataset.focusKey;
    const selection = focusKey && typeof document.activeElement.selectionStart === 'number' ? [document.activeElement.selectionStart,document.activeElement.selectionEnd] : null;
    content.classList.remove('route-enter');
    content.replaceChildren(views[S.route.name](S.route.arg));
    if (['naukri','boards','sites','profile','linkedin','resume','outreach','linkedin-profile'].includes(S.route.name)) {
      content.firstElementChild.prepend(h('a', {class:'back-link',href:'#/bots',text:'← Bot Crew'}));
    }
    if (scroll) { content.classList.remove('route-enter'); void content.offsetWidth; content.classList.add('route-enter'); }
    document.title = `${SECTIONS.find(([name]) => name === S.route.name)?.[1] || 'Launchpad'} · Orbit`;
    renderNav();
    updateRunButtons();
    if (focusKey) {
      const target = [...content.querySelectorAll('[data-focus-key]')].find(el => el.dataset.focusKey === focusKey);
      target?.focus({ preventScroll:true });
      if (selection && target?.setSelectionRange) target.setSelectionRange(...selection);
    }
    if (scroll) { window.scrollTo(0, 0); content.focus({ preventScroll: true }); }
  } catch (error) {
    console.error(error);
    content.replaceChildren(errorState('This view could not be loaded. Please try again.', () => render()));
  }
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
  if (JSON.stringify(previous && { ...previous, run: null }) !== JSON.stringify({ ...S.status, run: null })) {
    renderNav();
    if (['overview', 'todo', 'sites'].includes(S.route.name) && !content.contains(document.activeElement)) render();
  }
};
hooks.refreshCourse = async () => {
  S.course = await api('/api/course');
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
        if (finished) { S.library=null; S.document=null; S.dataHub=null; }
        if (['overview', 'analytics', 'bots', 'pipeline', 'reports', 'research', 'records','data'].includes(S.route.name)) render();
      }
    } catch { online(false); }
  }
  timer = setTimeout(poll, S.status?.run.running ? 1200 : 5000);
}

async function boot() {
  if (booting) return;
  booting = true;
  content.replaceChildren(loadingState('Opening your workspace…'));
  try {
    // Load the first-screen data together: avoid rendering, then fetching, then replacing
    // the same headline twice while the overview and crew inventory arrive in sequence.
    const days=S.overviewDays;
    const [meta,status,course,overview,bots]=await Promise.all([
      ...['/api/meta','/api/status','/api/course'].map(path=>api(path)),
      api(`/api/overview?days=${days}`).then(data=>({days,data,at:Date.now(),error:''})).catch(error=>({days,at:Date.now(),error:error.message})),
      api('/api/bots').then(data=>({data,at:Date.now()})).catch(error=>({at:Date.now(),error:error.message})),
    ]);
    S.meta=meta;S.status=status;S.course=course;S.overview=overview;S.bots=bots;
    online(true);
    S.route = parseRoute();
    updateConsoleStatus(S.status.run);
    render();
    clearTimeout(timer);
    timer = setTimeout(poll, 5000);
  } catch {
    online(false);
    content.replaceChildren(errorState('Your workspace is unavailable. Start the dashboard server, then reconnect.', boot));
    timer = setTimeout(boot, 5000);
  } finally { booting = false; }
}

window.addEventListener('hashchange', () => { S.route = parseRoute(); render(true); });
window.addEventListener('beforeunload', event => {
  if (Object.values(S.loadedFiles).some(file => file.draft !== file.text)) { event.preventDefault(); event.returnValue = ''; }
});
document.addEventListener('visibilitychange', () => { if (!document.hidden) { clearTimeout(timer); S.meta ? poll() : boot(); } });
document.addEventListener('keydown', event => {
  if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || event.target.closest('input, textarea, select, [contenteditable], dialog, [role="combobox"], [role="slider"], [popover]')) return;
  if (/^[1-9]$/.test(event.key)) { event.preventDefault(); navigate(SECTIONS[Number(event.key) - 1][0]); }
});
initConsole();
renderNav();
boot();
