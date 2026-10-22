import {journeyBanner,progressRing} from '../components/journey.js';
import { h } from '../dom.js';
import { api } from '../api.js';
import { S, hooks } from '../state.js';
import { avatar } from '../components/identity.js';
import { selectControl } from '../components/controls.js';
import { panel, empty, errorState } from '../components/panel.js';
import { field, selectInput, textInput, toggle, previewBox, runButton, quickButton, liveRunConfirm, schedulePreview } from '../forms.js';

const choices = entries => entries.map(([value, label]) => ({ value, label }));
const boardNames={naukri:'Naukri',linkedin:'LinkedIn',hirist:'Hirist',instahyre:'Instahyre',cutshort:'Cutshort',wellfound:'Wellfound'};
const stageChoices=[['learn','Learning'],['research:resume','Resume research'],...Object.entries(boardNames).map(([key,name])=>['profile:'+key,name+' profile']),...Object.entries(boardNames).filter(([key])=>key!=='linkedin').map(([key,name])=>['apply:'+key,name+' applications']),...Object.entries({goal:'Career goals','system-design':'System design',papers:'Research papers','tech-news':'Technology news',companies:'Company research'}).map(([key,name])=>['brief:'+key,name])];
export const stageName=key=>stageChoices.find(([id])=>id===key)?.[1] || key.replaceAll(':',' / ');
export function renderBoards(arg='') {
  const [board,mode]=arg.split('/');
  if (['hirist', 'instahyre', 'cutshort', 'wellfound'].includes(board) && S.boardRouteArg !== arg) {
    S.forms.boards = { ...(S.forms.boards || {}), board, mode:mode==='profile'?'profile':'apply' };
    S.boardRouteArg = arg;
  } else if (!board) S.boardRouteArg = '';
  const applyOptions=h('div',{hidden:S.forms.boards.mode==='profile'},field('Application limit per board',textInput('boards','limit',{type:'number',min:1,max:500,placeholder:'Use configured limit'})),toggle('boards','update_profile','Refresh profile before applying','Update the saved board profile at the beginning of an application run.'));
  const modeInput=selectControl({label:'Action',options:choices([['apply','Find & apply'],['profile','Create or refresh profile']]),value:S.forms.boards.mode||'apply',onChange:value=>{S.forms.boards.mode=value;applyOptions.hidden=value==='profile';schedulePreview('boards');}});
  return h('div', { class: 'page' }, h('header', { class: 'page-head' }, h('div', {}, h('p', { class: 'eyebrow', text: 'Explore more opportunities' }), h('h1', { text: 'Job boards' }), h('p', { class: 'lead', text: 'One place to run applications and refresh profiles across your boards.' }))),
    h('div', { class: 'dash' }, panel('Configure a run', { cls: 'span-7' },
      h('div', { class: 'form-grid' }, field('Job board', selectInput('boards', 'board', choices([['all', 'All boards'], ['hirist', 'Hirist'], ['instahyre', 'Instahyre'], ['cutshort', 'Cutshort'], ['wellfound', 'Wellfound']]), 'all')),
        field('Action',modeInput)),applyOptions,
      toggle('boards', 'dry_run', 'Practice run', 'Preview the selected action without saving profile changes or submitting applications.'),
      previewBox('boards'),
      runButton('boards', 'Start run', { confirm: () => S.forms.boards.dry_run ? null : liveRunConfirm('This can submit applications or update your profiles on the selected boards.') })),
      panel('Your job boards', { cls: 'span-5', sub: 'Sign-in is checked when a run starts.' },
        h('ul', { class: 'plain-list board-list' }, ['Hirist', 'Instahyre', 'Cutshort', 'Wellfound'].map((name, i) => h('li', {}, avatar(16+i,'board-avatar'), h('div', {}, h('strong', { text: name }), h('p', { class: 'muted small', text: 'Applications & profile updates' })), h('a', { class: 'text-link', href:'#/boards/'+name.toLowerCase()+'/profile', text: 'Edit profile' })))))));
}

let loading = false;
async function loadPipeline() {
  if (loading) return;
  loading = true;
  try { S.pipeline = { data: await api('/api/pipeline'), at: Date.now() }; }
  catch (error) { S.pipeline = { error: error.message, at: Date.now() }; }
  finally { loading = false; }
  if (S.route.name === 'pipeline') hooks.requestRender();
}


function flowTimeline(stages) {
  const groups=[['learn','Learning'],['profile','Profile updates'],['apply','Applications'],['research','Research'],['brief','Daily briefing']];
  for(const stage of stages){const prefix=stage.name.split(':')[0];if(!groups.some(([key])=>key===prefix))groups.push([prefix,stageName(prefix)]);}
  return h('div',{class:'flow-groups'},groups.map(([key,title])=>{
    const entries=stages.map((stage,i)=>({...stage,index:i})).filter(stage=>stage.name.split(':')[0]===key);
    if(!entries.length)return null;
    const done=entries.filter(stage=>stage.status==='done').length;
    return h('details',{class:'flow-group',open:done<entries.length},h('summary',{},h('strong',{text:title}),h('span',{text:`${done} / ${entries.length}`}),h('span',{class:done===entries.length?'group-complete':'group-next',text:done===entries.length?'Complete':'View stages'})),
      h('ol',{class:'plain-list pipeline-list flow-timeline'},entries.map(stage=>h('li',{class:`flow-stage stage-${stage.status}`},h('span',{class:'stage-number',text:String(stage.index+1).padStart(2,'0')}),
        h('div',{class:'stage-detail'},h('a',{href:'#/pipeline/'+encodeURIComponent(stage.name),text:stageName(stage.name)}),h('p',{class:'small muted',text:`${stage.attempts||0} attempts${stage.detail?' · '+stage.detail:''}`})),
        h('span',{class:`pill ${stage.status==='done'?'pill-accent':''}`,text:({done:'Complete',pending:'Not started',running:'In progress (saved)',failed:'Needs attention'})[stage.status]||stage.status})))));
  }));
}

function watchPanel(data) {
  if (!data?.watch) return null;
  return panel('Watch the bots', { sub: 'With “Each bot in its own container”, each site’s screen. A screen connects once its container runs.' },
    h('ul', { class: 'plain-list watch-list' }, data.watch.map(({ site, url }) => h('li', {}, h('a', { href: url, target: '_blank', rel: 'noopener', text: `${site} screen` })))));
}

export function renderPipeline(group) {
  if (['learn', 'brief', 'research', 'apply', 'profile',...stageChoices.map(([id])=>id)].includes(group) && S.pipelineRouteArg !== group) {
    S.forms.pipeline = { ...(S.forms.pipeline || {}), group };
    S.pipelineRouteArg = group;
  } else if (!group) S.pipelineRouteArg = '';
  if (!S.pipeline || Date.now() - S.pipeline.at > 15000) loadPipeline();
  const data = S.pipeline?.data;
  const done = data?.stages.filter(stage => stage.status === 'done').length || 0;
  return h('div', { class: 'page' }, h('header', { class: 'page-head' }, h('div', {}, h('p', { class: 'eyebrow', text: 'YOUR DAILY ROUTINE, AUTOMATED' }), h('h1', { text: 'Flows' }), h('p', { class: 'lead', text: 'Learning, profile updates, applications and research in one workflow.' })), h('button', { class: 'btn', type: 'button', text: 'Refresh progress', onclick: loadPipeline })),
    journeyBanner({image:28,eyebrow:'YOUR DAILY FLOW',title:done?'Your routine is taking shape.':'Set the pace. Let your crew help.',body:data?.stages.length?`${done} of ${data.stages.length} stages complete in the saved checkpoint. Refresh progress to see the latest saved stages.`:'Choose a full routine or just the stages you need. Start with a practice run to check your setup.',progress:progressRing(done,data?.stages.length||0,'complete')}),
    h('div', { class: 'dash flow-grid' },
      panel('Today’s progress', { cls: 'span-7', sub: data?.stages.length ? `Saved checkpoint · ${done} of ${data.stages.length} stages complete · ${data.date}` : 'Your saved pipeline checkpoint' },
        S.pipeline?.error ? errorState(S.pipeline.error, loadPipeline) : !data ? empty('Reading your checkpoint…') : !data.stages.length ? empty('No pipeline has been started today. Configure a run to begin.') :
          flowTimeline(data.stages)),
      h('div', { class: 'span-5 stack pipeline-controls' }, panel('Configure your flow', {},
        field('Stages to run', selectInput('pipeline', 'group', choices([['', 'All stages'], ['profile', 'All profile updates'], ['apply', 'All applications'], ['brief', 'All daily briefing agents'], ['research', 'All research'],...stageChoices]), '')),
        h('div',{class:'form-grid'},field('AI CLI',selectInput('pipeline','cli',choices([['','Use configured CLI'],['both','Claude & Kiro'],['claude','Claude'],['kiro','Kiro']]),'')),field('Research agents',textInput('pipeline','agents',{type:'number',min:1,max:8,placeholder:'Use configured count'})),field('Pipeline date',textInput('pipeline','date',{type:'date'}),'Leave blank for today.'),field('Skip stages',selectInput('pipeline','skip',choices([['','Do not skip'],['profile','Profile updates'],['apply','Applications'],['brief','Daily briefing'],['research','Research'],['learn','Learning']]),'')),field('Bots at once',textInput('pipeline','bots',{type:'number',min:1,max:6,placeholder:'One after another'}),'Each site in its own process and Chrome profile.')),
        toggle('pipeline','containers','Each bot in its own container','Every site runs at once in its own Docker container. Watch them below. Needs docker compose build and a sign-in per site.'),
        toggle('pipeline','redo','Rerun selected stages','Run the selected stage or group again, even if its checkpoint is complete.'),
        toggle('pipeline','fresh','Fresh daily run','Reset the checkpoint for this date before starting. Completed work can run again.'),
        toggle('pipeline', 'dry_run', 'Practice run', 'Bots use dry-run mode. Learning and research may still use your AI CLI.'),
        previewBox('pipeline'), runButton('pipeline', 'Continue pipeline', { confirm: () => S.forms.pipeline.dry_run ? null : liveRunConfirm('This continues unfinished stages, including live applications and profile updates.') })),
        watchPanel(data),
        panel('Review & diagnose', {}, h('p', { class: 'muted', text: 'Inspect the checkpoint or validate today’s research and study material.' }), h('div', { class: 'panel-foot' }, quickButton('pipeline', 'Check status', { command: 'status' }), quickButton('pipeline', 'Validate material', { command: 'check' }))))));
}
