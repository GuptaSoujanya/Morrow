import { h } from '../dom.js';
import { icon } from '../icons.js';
import { S, hooks } from '../state.js';
import { api } from '../api.js';
import { navigate } from '../router.js';
import { quickButton, updateRunButtons } from '../forms.js';
import { setConsoleSize } from '../components/console.js';
import { num } from '../format.js';
import {avatar} from '../components/identity.js';

export const BOTS = [
  { id:'naukri', name:'Naukri', mark:'n', color:'blue', group:'applications', description:'Find, rank and apply to matching roles.', route:'naukri', action:'naukri' },
  { id:'hirist', name:'Hirist', mark:'h', color:'teal', group:'applications', description:'Discover your next role in technology.', route:'boards', action:'boards' },
  { id:'instahyre', name:'Instahyre', mark:'i', color:'violet', group:'applications', description:'Connect with companies that fit you.', route:'boards', action:'boards' },
  { id:'cutshort', name:'Cutshort', mark:'c', color:'coral', group:'applications', description:'Explore opportunities at growing teams.', route:'boards', action:'boards' },
  { id:'wellfound', name:'Wellfound', mark:'w', color:'slate', group:'applications', description:'Find your place in the startup world.', route:'boards', action:'boards' },
  { id:'external', name:'Company sites', icon:'globe', color:'indigo', group:'applications', description:'Finish applications on company websites.', route:'sites' },
  { id:'profile', name:'Naukri profile', icon:'person', color:'blue', group:'profiles', description:'Keep your Naukri profile and resume fresh.', route:'profile', action:'profile' },
  { id:'linkedin', name:'LinkedIn writer', mark:'in', color:'blue', group:'career', description:'Draft, review and publish your next post.', route:'linkedin', action:'linkedin' },
  { id:'linkedin_profile', name:'LinkedIn profile', icon:'person', color:'slate', group:'profiles', description:'Review and update your profile from saved facts.', route:'linkedin-profile', action:'linkedin_profile' },
  { id:'cold_email', name:'Recruiter drafts', icon:'send', color:'teal', group:'career', description:'Prepare recruiter emails for your review. Drafts only.', route:'outreach', action:'cold_email' },
  { id:'resume', name:'Resume tailor', icon:'file', color:'coral', group:'career', description:'Shape your resume around a specific role.', route:'resume' },
  { id:'learn', name:'Learning assistant', icon:'book', color:'teal', group:'career', description:'Prepare your daily learning material.', route:'pipeline', action:'pipeline', pipeline:'learn' },
  { id:'brief', name:'Daily briefing', icon:'sun', color:'violet', group:'career', description:'Five agents research roles, news and ideas.', route:'pipeline', action:'pipeline', pipeline:'brief' },
  { id:'research', name:'Resume researcher', icon:'search', color:'indigo', group:'career', description:'Research the skills behind your experience.', route:'pipeline', action:'pipeline', pipeline:'research' },
  ...['hirist','instahyre','cutshort','wellfound'].map((board,i)=>({id:board+'_profile',board,name:({hirist:'Hirist',instahyre:'Instahyre',cutshort:'Cutshort',wellfound:'Wellfound'})[board]+' profile',group:'profiles',description:'Create or refresh your profile using your saved facts and resume.',route:'boards',action:'boards',mode:'profile',image:16+i})),
];
let loading = false;
export async function refreshBots() {
  if (loading) return;
  loading = true;
  try {
    const data = await api('/api/bots');
    const changed = JSON.stringify(data.bots) !== JSON.stringify(S.bots?.data?.bots) || S.bots?.error;
    S.bots = { data, at:Date.now() };
    if (changed && ['overview','bots'].includes(S.route.name) && (!document.getElementById('content').contains(document.activeElement) || document.activeElement.id === 'content')) hooks.requestRender();
  } catch (error) {
    S.bots = { ...S.bots, at:Date.now(), error:error.message };
    if (['overview','bots'].includes(S.route.name) && (!document.getElementById('content').contains(document.activeElement) || document.activeElement.id === 'content')) hooks.requestRender();
  }
  finally { loading = false; }
}
export function selectBot(bot) {
  if (bot.route === 'boards') {
    S.forms.boards = { ...(S.forms.boards || {}), board:bot.board||bot.id, mode:bot.mode||'apply' };
    navigate('boards', (bot.board||bot.id)+(bot.mode==='profile'?'/profile':''));
  } else if (bot.pipeline) {
    S.forms.pipeline = { ...(S.forms.pipeline || {}), group:bot.pipeline };
    navigate('pipeline', bot.pipeline);
  } else navigate(bot.route);
}
export function botIcon(bot) {
  return avatar(bot.image??Math.max(0,BOTS.findIndex(b=>b.id===bot.id)),'bot-icon');
}
export function botCard(bot) {
  const state = S.bots?.data?.bots.find(b => b.id === bot.id);
  const record = state?.last_run;
  const stats = S.overview?.data?.boards.find(b => b.key === bot.id);
  const active = state?.running;
  const status = S.bots?.error ? 'Status unavailable' : !state ? 'Checking status' : active ? 'In current run' : 'Idle';
  const latest = record ? `${record.practice ? 'Practice' : bot.group==='profiles'?'Profile run':'Application run'} · ${new Date(record.at).toLocaleDateString(undefined,{month:'short',day:'numeric'})}${record.finished ? '' : ' · no end recorded'}` : bot.group==='profiles'?'No saved profile run history':'No recorded run';
  let primary;
  if (active) primary = h('button', { class:'btn btn-primary', type:'button', onclick:() => setConsoleSize('normal') }, icon('activity'), 'View live run');
  else if (bot.action) {
    const options = bot.pipeline ? { group:bot.pipeline, dry_run:true } : bot.action === 'boards' ? { board:bot.board||bot.id, ...(bot.mode?{mode:bot.mode}:{}), dry_run:true } : bot.id === 'linkedin' ? { mode:'dry-run' } : { dry_run:true };
    primary = quickButton(bot.action, bot.pipeline ? 'Run assistant' : bot.id === 'linkedin' ? 'Draft post' : 'Practice run', options, {
      confirm:{ title:`${bot.pipeline ? 'Run' : 'Preview'} ${bot.name}?`, body:bot.pipeline ? 'This runs the selected pipeline assistant and may use your configured AI CLI.' : 'Run with practice settings. No applications will be submitted and no profile changes will be saved.' }
    });
    primary.setAttribute('aria-label', `${primary.textContent} — ${bot.name}`);
    // Each card needs its own busy-state entry even when it shares a backend action.
    S.runButtons[`bot:${bot.id}`] = primary;
    primary.prepend(icon('play','icon icon-sm'));
  } else primary = h('button', { class:'btn', type:'button', onclick:() => selectBot(bot) }, bot.id === 'external' ? 'Review applications' : 'Tailor a resume', icon('arrow-up-right','icon icon-sm'));
  return h('article', { class:`bot-card ${active ? 'is-running' : ''}`, dataset:{bot:bot.id} },
    h('div', { class:'bot-top' }, botIcon(bot), h('span', { class:`bot-status ${active ? 'is-live' : ''}` }, h('span', {class:'status-pin'}), status)),
    h('h3', {text:bot.name}), h('p', { class:'bot-description', text:bot.description }),
    h('div', { class:'bot-record' }, stats ? h('span', {}, h('strong', {text:num(stats.found)}), ' discovered', h('span',{class:'record-divider',text:'·'}), h('strong',{text:num(stats.sent)}),' sent') : bot.id === 'external' ? h('span',{},h('strong',{text:num(S.status.sites.length)}),' awaiting review') : h('span',{text:bot.group === 'career' ? 'On-demand assistant' : 'Ready to configure'}),
      h('span', {class:'bot-last',text:latest})),
    h('div', { class:'bot-actions' }, primary, h('button', { class:'icon-btn bot-settings', type:'button', 'aria-label':`Configure ${bot.name}`, title:`Configure ${bot.name}`, onclick:() => selectBot(bot) }, icon('sliders'))));
}
export function fleetSection() {
  if (!S.bots || Date.now()-S.bots.at>15000) refreshBots();
  return h('section', {class:'fleet-section', 'aria-labelledby':'fleet-title'},
    h('div',{class:'section-heading'},h('div',{},h('h2',{id:'fleet-title',text:'Your application bots'}),h('p',{text:'Six ways to find your next opportunity.'})),h('a',{class:'text-link',href:'#/bots'},'All bots',icon('arrow-up-right','icon icon-sm'))),
    S.bots?.error ? h('div',{class:'inline-notice',role:'status'},'Bot status is unavailable. ',h('button',{class:'text-link',type:'button',text:'Try again',onclick:async()=>{await refreshBots();hooks.requestRender();}})) : null,
    h('div',{class:'bot-grid'}, BOTS.filter(b=>b.group==='applications').map(botCard)));
}
export function renderBots() {
  if (!S.bots || Date.now()-S.bots.at>15000) refreshBots();
  const grid = h('div',{class:'bot-grid'});
  const count = h('span',{class:'filter-count'});
  const tabs = h('div',{class:'segmented','aria-label':'Bot category'});
  const draw = () => {
    const matches = BOTS.filter(b => (S.botFilter === 'all' || !S.botFilter || b.group === S.botFilter) && `${b.name} ${b.description}`.toLowerCase().includes((S.botQuery || '').toLowerCase()));
    count.textContent = `${matches.length} bots`;
    grid.replaceChildren(...(matches.length ? matches.map(botCard) : [h('div',{class:'panel bot-empty',text:'No bots match your search. Try a different name or category.'})]));
    tabs.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.filter === (S.botFilter || 'all'))));
    if(grid.isConnected) updateRunButtons();
  };
  for (const [key,label] of [['all','All bots'],['applications','Applications'],['profiles','Profile crew'],['career','Career & research']]) tabs.append(h('button',{type:'button',dataset:{filter:key},text:label,onclick:()=>{S.botFilter=key;draw();}}));
  const search = h('label',{class:'search-control'},icon('search'),h('input',{type:'search',placeholder:'Find a bot…','aria-label':'Find a bot',value:S.botQuery || '',oninput:event=>{S.botQuery=event.target.value;draw();}}));
  draw();
  return h('div',{class:'page bot-page'},
    h('header',{class:'page-head'},h('div',{},h('p',{class:'eyebrow',text:'YOUR CAREER, WITH BACKUP'}),h('h1',{text:'Meet your Bot Crew'}),h('p',{class:'lead',text:'18 specialists. Find roles, refresh six platform profiles and make your next move.'})),h('a',{class:'btn btn-primary',href:'#/pipeline'},icon('workflow'),'Build a flow')),
    h('div',{class:'fleet-notice'},icon('info','icon icon-sm'),h('span',{text:S.status.run.running ? `${S.status.run.label} is running. Open Activity to follow or stop it.` : 'Start a practice run, or open a bot’s settings to configure a live run.'})),
    h('div',{class:'bot-toolbar'},tabs,search,count),
    S.bots?.error ? h('div',{class:'inline-notice',role:'alert'},'Bot status is unavailable. ',h('button',{class:'text-link',type:'button',text:'Try again',onclick:async()=>{await refreshBots();hooks.requestRender();}})) : null,
    S.bots?.data?.history_error ? h('p',{class:'inline-notice',text:S.bots.data.history_error}) : null,
    grid,h('p',{class:'fleet-footnote',text:'Status reflects runs started here. Platform sign-in is checked when a bot starts.'}));
}
