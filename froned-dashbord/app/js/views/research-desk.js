import {h} from '../dom.js';
import {icon} from '../icons.js';
import {avatar} from '../components/identity.js';
import {panel,empty} from '../components/panel.js';
import {journeyBanner,progressRing,statStrip} from '../components/journey.js';
import {dateControl} from '../components/controls.js';
import {updateRunButtons} from '../forms.js';
import {S,hooks} from '../state.js';
import {api} from '../api.js';
import {confirmDialog} from '../components/dialog.js';
import {setConsoleSize} from '../components/console.js';
import {routeHref} from '../router.js';
import {withQuery} from '../url-state.js';

const art={digest:29,papers:25,tech:28,companies:26,goal:41,design:30};
const explanation={papers:'Research worth understanding, with the original paper links.',tech:'The releases and engineering news in your saved daily brief.',companies:'Companies, relevant roles and the career links your agents found.',goal:'A focused goal, concept map and time-boxed plan for this date.',design:'Your daily system-design explanation, examples and practice.'};
const dateLabel=value=>new Date(value+'T12:00:00').toLocaleDateString(undefined,{day:'numeric',month:'short',year:'numeric'});
const href=(id,query)=>routeHref('research',id)+(query.toString()?'?'+query:'');
function viewLink(view,day){return withQuery('research',{view,date:day});}
function fetchButton(label,group,day,refresh,{existing=false}={}){
  const feedback=h('p',{class:'field-error',role:'alert',hidden:true});
  const button=h('button',{class:'btn',type:'button',dataset:{action:'pipeline-fixed'},text:label,onclick:async()=>{
    button.disabled=true;feedback.hidden=true;
    try{
      const options={group,date:day,redo:true},preview=await api('/api/preview',{action:'pipeline',options});
      if(preview.needed)throw new Error(preview.needed);
      if(!await confirmDialog({title:`${label}?`,body:group==='research:resume'?'Generate missing topics from your saved resume and rebuild its overview. Existing topic files are kept.':`Use your configured research agents for ${dateLabel(day)}. ${existing?'Existing files in this selected section will be refreshed.':'New material will be saved to your workspace.'} You can follow progress in Activity.`,code:preview.shown,ok:group==='research:resume'?'Update resume library':'Fetch research'}))return;
      await api('/api/run',{action:'pipeline',options});
      setConsoleSize('normal');
      try{await hooks.refreshStatus();await refresh();}catch(error){feedback.textContent=`Research started. Refresh the view to check new files. ${error.message}`;feedback.hidden=false;}
    }catch(error){feedback.textContent=`Could not fetch this research. ${error.message}`;feedback.hidden=false;}
    finally{if(button.isConnected)updateRunButtons();}
  }});
  S.runButtons['pipeline-fixed:research:'+group]=button;
  button.dataset.focusKey='research-fetch:'+group;
  return h('div',{class:'research-fetch-control'},button,feedback);
}
function dayToolbar(briefing,view){
  const day=briefing.date;
  return h('div',{class:'research-day-toolbar'},h('div',{},h('strong',{text:'Your research date'}),h('p',{class:'small muted',text:'Read a saved day or fetch the one you need.'})),
    dateControl({label:'Research date',value:day,marked:briefing.available_dates||[],commitOnly:true,onChange:value=>{location.hash=viewLink(view,value||S.status.date);}}),
    day!==S.status.date?h('a',{class:'btn btn-sm',href:viewLink(view,S.status.date),text:'Back to today'}):null);
}
function sourceSection(section,day,query,refresh){
  const doc=section.document;
  return h('section',{class:'panel research-source',tabIndex:-1,dataset:{researchSection:section.key}},
    h('div',{class:'research-source-heading'},avatar(art[section.key]||25,'source-section-art'),h('div',{},h('h2',{text:section.title}),h('p',{class:'small muted',text:dateLabel(day)})),h('span',{class:doc?'pill '+(doc.read?'pill-ok':'pill-accent'):'pill',text:doc?(doc.read?'Read':'Ready to read'):'Not fetched'})),
    doc?h('div',{class:'research-source-body'},doc.preview?.length?h('ul',{class:'research-headlines'},doc.preview.map(line=>h('li',{text:line}))):h('p',{class:'muted',text:doc.excerpt||'Your saved document is ready to read.'}),
      h('div',{class:'research-source-footer'},h('a',{class:'btn btn-primary',href:href(doc.id,query),text:`Open ${section.title}`},icon('arrow-up-right','icon icon-sm')),fetchButton(`Refresh ${section.title}`,section.group,day,refresh,{existing:true}),h('span',{class:'small muted',text:doc.sections?`${doc.sections} sections · saved research`:'Saved research'}))):
      h('div',{class:'research-source-body'},h('p',{class:'muted',text:explanation[section.key]}),h('p',{class:'source-missing-note',text:`No ${section.title.toLowerCase()} saved for ${dateLabel(day)}.`}),fetchButton(`Fetch ${section.title}`,section.group,day,refresh)),
    h('p',{class:'research-source-path',text:section.path}));
}
function compactLink(item,query,label){
  return h('a',{class:'document-item research-row',href:href(item.id,query)},avatar(item.category==='Resume research'?43:25,'research-row-art'),h('div',{class:'research-row-copy'},h('strong',{text:label||item.title}),h('small',{text:'.research/'+item.path})),item.read?h('span',{class:'pill pill-ok',text:'Complete'}):null,icon('arrow-up-right','icon icon-sm'));
}
function runningNotice(){
  return S.status?.run?.running?h('div',{class:'inline-notice',role:'status'},h('strong',{text:S.status.run.label+' is running.'}),' Follow the output in Activity. Saved content remains readable; new results appear when the run finishes.'):null;
}
export function renderResearchDesk(data,{view,query,refresh,completed,stats,saved}){
  const b=data.briefing||{date:data.date,sections:[],available_dates:[],references:[],additional:[]};
  query.set('date',b.date);
  const get=key=>b.sections.find(section=>section.key===key);
  if(view==='today'){
    const digest=get('digest')||{group:'brief'},doc=digest.document;
    const topics=['papers','tech','companies'].map(get).filter(Boolean);
    const ready=[digest,...topics].filter(s=>s.document).length;
    const hero=h('section',{class:'daily-digest'},avatar(29,'digest-art'),h('div',{class:'digest-copy'},h('p',{class:'eyebrow',text:`DAILY DIGEST · ${dateLabel(b.date)}`}),h('h2',{text:doc?'Your day, all in one place.':'Your next briefing is waiting to be made.'}),h('p',{text:doc?'Open the daily README for your research, stage summaries and saved charts.':`No daily README is saved for ${dateLabel(b.date)}. Fetch this date’s research to build it.`}),h('div',{class:'digest-actions'},doc?h('a',{class:'btn btn-primary',href:href(doc.id,query),text:'Open daily README'},icon('arrow-up-right','icon icon-sm')):null,fetchButton(doc?'Refresh daily research':'Fetch daily research','brief',b.date,refresh,{existing:!!doc}))),h('div',{class:'digest-count'},h('strong',{text:`${ready}/4`}),h('span',{text:'daily briefs ready'})));
    const previous=b.latest&&b.latest!==b.date?h('a',{class:'saved-day-link',href:viewLink('today',b.latest)},icon('calendar','icon icon-sm'),`Latest saved research: ${dateLabel(b.latest)}`,icon('arrow-up-right','icon icon-sm')):null;
    const learningLink=h('a',{class:'studio-crosslink',href:viewLink('learning',b.date)},avatar(30,'source-section-art'),h('div',{},h('strong',{text:'Your learning has its own space.'}),h('p',{text:'90-day plan, daily goal, system-design brief and course progress.'})),h('span',{text:'Open Learning'}),icon('arrow-up-right','icon icon-sm'));
    const refs=[...(b.additional||[]),...(b.references||[])];
    return [dayToolbar(b,view),runningNotice(),hero,previous,h('nav',{class:'research-jump-links','aria-label':'Daily research sections'},topics.map(section=>h('button',{type:'button',class:'filter-chip',text:section.title,onclick:()=>{const target=document.querySelector(`[data-research-section="${section.key}"]`);target?.focus({preventScroll:true});target?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth',block:'start'});}}))),
      ...topics.map(section=>sourceSection(section,b.date,query,refresh)),learningLink,
      refs.length?panel('More from your research',{sub:'Saved daily notes and ongoing reference documents.'},refs.map(item=>compactLink(item,query,item.path==='TODAY.md'?'Latest briefing pointer · TODAY.md':undefined))):null,
      completed,saved].filter(Boolean);
  }
  if(view==='learning'){
    const focus=data.focus;
    const hero=journeyBanner({image:30,eyebrow:focus?`YOUR NEXT READ · DAY ${focus.day}`:'YOUR LEARNING PLAN',title:focus?.title||(data.plan_complete?'All 90 days. Look how far you’ve come.':'Your next chapter starts here.'),body:focus?'Pick up at your first unfinished day. Your pace, your progress.':data.missing||'Explore your saved research or revisit a course lesson.',action:focus?h('a',{class:'btn btn-primary',href:href(focus.id,query),text:'Start reading'},icon('arrow-up-right','icon icon-sm')):h('a',{class:'btn btn-primary',href:viewLink('library',b.date),text:'Explore saved research'}),progress:progressRing(data.plan_done,90,'days complete')});hero.classList.add('daily-focus');
    return [hero,stats,h('div',{class:'research-learning-tools'},h('a',{class:'btn',href:'#/study',text:'Open course lessons'}),fetchButton('Prepare learning day','learn',b.date,refresh)),dayToolbar(b,view),runningNotice(),...['goal','design'].map(get).filter(Boolean).map(section=>sourceSection(section,b.date,query,refresh)),
      panel('Saved weekly plans',{sub:'Your complete learning material, organised by week.'},data.weeks?.length?h('div',{class:'weekly-plan-list'},data.weeks.map(item=>compactLink(item,query))):empty('No weekly plans are saved yet. Prepare a learning day to generate the next material.')),completed,saved].filter(Boolean);
  }
  const resume=data.resume||{topics:[],index:null},read=resume.topics.filter(item=>item.read).length;
  return [h('section',{class:'resume-lab-intro'},avatar(43,'digest-art'),h('div',{},h('p',{class:'eyebrow',text:'FROM YOUR EXPERIENCE. FOR YOUR NEXT INTERVIEW.'}),h('h2',{text:'Know your resume inside out.'}),h('p',{text:'A separate learning library for the systems, tools and projects in your saved resume.'})),progressRing(read,resume.topics.length,'topics read')),
    statStrip([[resume.topics.length,'saved topics'],[read,'completed'],[resume.topics.length-read,'left to explore']]),
    h('div',{class:'research-learning-tools'},resume.index?h('a',{class:'btn',href:href(resume.index.id,query),text:'Open resume README'}):null,fetchButton('Update resume library','research:resume',b.date,refresh)),runningNotice(),
    panel('Your resume topics',{sub:'Read, practice and mark each topic complete. Your progress stays in .memory.'},resume.topics.length?resume.topics.map(item=>compactLink(item,query)):empty('No resume learning topics are saved yet. Update the resume library to generate them from your saved resume.')),saved].filter(Boolean);
}
