import {h} from '../dom.js';
import {api} from '../api.js';
import {panel,errorState,empty,loadingState} from '../components/panel.js';
import {avatar} from '../components/identity.js';
import {icon} from '../icons.js';
import {routeHref} from '../router.js';
import {readQuery,writeQuery,pageNumber,choice,withQuery} from '../url-state.js';
import {pagination} from '../components/pagination.js';
import {READER_STYLE} from '../components/reader.js';
import {statStrip} from '../components/journey.js';
import {renderResearchDesk} from './research-desk.js';
import {updateRunButtons} from '../forms.js';

const categories=['Briefing','Learning','Resume research','Email drafts'];
const arts={'Briefing':25,'Learning':30,'Resume research':43,'Email drafts':27};
function studioTabs(view){
  return h('nav',{class:'workspace-tabs studio-tabs','aria-label':'Research views'},[['today','Today'],['learning','Learning'],['resume','Resume lab'],['library','Library'],['progress','Progress']].map(([key,title])=>h('a',{href:withQuery('research',{view:key,date:readQuery().get('date')||''}),'aria-current':view===key?'page':null,text:title})));
}
function documentHref(id,query){return routeHref('research',id)+(query.toString()?'?'+query:'');}
function historyRow(item){
  const href=item.kind==='course'?'/course/#/'+item.id.replace(/README\.md$/,'').replace(/\.md$/,''):documentHref(item.id,new URLSearchParams({view:'progress'}));
  const date=item.at||item.completed_at;
  return h('li',{class:'history-row'},h('span',{class:'history-dot','data-state':item.action||'completed','aria-hidden':'true'}),
    h('div',{},h('a',{href,text:item.title||item.id}),h('span',{class:'small muted',text:`${item.kind==='course'?'Course lesson':'Research'} · ${item.action==='reopened'?'Reopened':'Completed'}`})),
    date?h('time',{dateTime:date,text:new Date(date).toLocaleString(undefined,{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})}):h('span',{class:'small muted',text:'Imported · date unavailable'}));
}
function dailyView(view){
  const content=h('div',{},loadingState(({today:'Opening your daily research…',learning:'Finding your next learning day…',resume:'Opening your resume topics…',progress:'Opening your learning history…'})[view]));
  const query=readQuery();query.set('view',view);let ticket=0;
  async function load(fresh=false){
    const request=++ticket;
    try{
      const data=await api('/api/research/learning?'+new URLSearchParams({page:pageNumber(query.get('page')),date:query.get('date')||''}),undefined,{fresh});if(request!==ticket)return;
      const stats=statStrip([[data.completed_today.length,'completed today'],[`${data.plan_done} / 90`,'learning days complete'],[`${data.course_done} / ${data.course_total}`,'course lessons read','#/study']]);
      const saved=h('p',{class:'memory-note'},icon('check','icon icon-sm'),'Progress saved on this device in ',h('code',{text:data.storage}),'. It stays when you restart the server.');
      const completedItems=view==='today'?(data.completed_selected_date||data.completed_today):data.completed_today;
      const completed=panel(view==='today'&&data.selected_date!==data.date?'Completed on this date':'Completed today',{sub:view==='today'?data.selected_date:data.date},completedItems.length?h('ul',{class:'plain-list learning-history'},completedItems.map(historyRow)):empty('Your first finish is ahead. Open a document, then mark it complete.'));
      if(view!=='progress'){
        content.replaceChildren(...renderResearchDesk(data,{view,query,refresh:()=>load(true),completed,stats,saved}));updateRunButtons();
      }else{
        const history=data.history;query.set('view','progress');query.set('page',history.page);writeQuery('research',Object.fromEntries(query),{replace:true});
        const paging=pagination({...history,label:'Learning history',onPage:page=>{query.set('page',page);writeQuery('research',Object.fromEntries(query));return load();}});
        const imported=[...data.imported,...data.legacy_plan_days.map(day=>({id:`plan/day-${day}`,title:`Learning day ${day}`,kind:'research'}))];
        content.replaceChildren(stats,panel('Your learning history',{sub:'Every completion and reopen, across research and courses.',tools:h('button',{class:'btn btn-sm',type:'button',text:'Refresh progress',onclick:()=>load(true)})},history.items.length?h('ul',{class:'plain-list learning-history'},history.items.map(historyRow)):empty('No new completions yet. Choose a document in Today or Learning to begin.'),history.pages>1?paging:null),imported.length?panel('Earlier progress',{sub:'Preserved from your previous progress files. Original completion dates were not recorded.'},h('details',{},h('summary',{text:`${imported.length} imported completions`}),h('ul',{class:'plain-list learning-history'},imported.map(historyRow)))):null,saved);
      }
    }catch(error){content.replaceChildren(errorState(error.message,()=>load(true)));}
  }
  content.refresh=()=>load(true);load();return content;
}
function reader(id,query){
  const body=h('div',{},loadingState('Opening your document…'));
  const load=async(fresh=false)=>{
    try{
      const data=await api('/api/document?id='+encodeURIComponent(id),undefined,{fresh});
      const frame=h('iframe',{class:'document-reader',title:data.title||'Research document',sandbox:'allow-popups allow-top-navigation-by-user-activation'});frame.srcdoc=READER_STYLE+data.html;
      const feedback=h('p',{class:'reading-save-status small muted',role:'status',text:data.read?'Completed · saved in .memory':'Mark complete when you finish. Your progress is saved on this device.'});
      const toggle=h('button',{class:'btn '+(data.read?'':'btn-primary'),type:'button',text:data.read?'Reopen reading':'Mark complete',onclick:async()=>{
        const wanted=!data.read;toggle.disabled=true;toggle.textContent='Saving…';feedback.textContent='Saving your progress…';feedback.classList.remove('field-error');
        try{await api('/api/research/read',{id,read:wanted});data.read=wanted;feedback.textContent=wanted?'Completed · saved in .memory. Your saved progress is ready in Learning and Progress.':'Reopened · saved in .memory.';}
        catch(error){feedback.classList.add('field-error');feedback.textContent=`Could not save. ${error.message} Please try again.`;}
        finally{toggle.disabled=false;toggle.textContent=data.read?'Reopen reading':'Mark complete';toggle.classList.toggle('btn-primary',!data.read);}
      }});
      body.replaceChildren(panel(data.title||'Research document',{cls:'focus-reader',sub:data.day?`Learning day ${data.day} of 90`:id.replace(/^research\//,'.research/'),tools:toggle},feedback,frame));
    }catch(error){body.replaceChildren(errorState(error.message,()=>load(true)));}
  };load();
  return h('div',{class:'page research-page has-document'},h('header',{class:'page-head'},h('div',{},h('a',{class:'back-link',href:withQuery('research',Object.fromEntries(query)),text:'← Back to Research Studio'}),h('h1',{text:'Reading room'}))),body);
}
export function renderResearch(id=''){
  const q=readQuery(),view=choice(q.get('view'),['today','learning','resume','library','progress'],q.has('category')||q.has('q')?'library':'today');q.set('view',view);
  if(id)return reader(id,q);
  if(view==='library')return library(q);
  const body=dailyView(view);
  return h('div',{class:'page research-page'},h('header',{class:'page-head'},h('div',{},h('p',{class:'eyebrow',text:'A LITTLE CURIOSITY. REAL PROGRESS.'}),h('h1',{text:'Research Studio'}),h('p',{class:'lead',text:'Know what’s next. See how far you’ve come.'})),view!=='progress'?h('button',{class:'btn',type:'button',text:'Refresh view',onclick:()=>body.refresh()}):null),studioTabs(view),body);
}
function library(q){
  const filters={view:'library',date:q.get('date')||'',category:choice(q.get('category'),['',...categories],''),q:q.get('q')||'',page:pageNumber(q.get('page')),size:choice(Number(q.get('size')),[12,24,48],12)};
  const returnURL=()=>withQuery('research',filters);
  writeQuery('research',filters,{replace:true});let ticket=0,timer;
  const list=h('div',{class:'research-results'},loadingState('Opening your research collection…')),paging=h('div'),feedback=h('div');
  const total=h('span',{class:'muted small',role:'status'});
  const tabs=h('div',{class:'collection-tabs',role:'group','aria-label':'Document categories'});
  const search=h('input',{class:'input',type:'search',placeholder:'Search your notes and research…','aria-label':'Find a document',value:filters.q,dataset:{focusKey:'research-search'},oninput:e=>{filters.q=e.target.value;filters.page=1;clearTimeout(timer);timer=setTimeout(()=>{if(search.isConnected)load();},250);}});
  const refresh=h('button',{class:'btn',type:'button',text:'Refresh library',onclick:()=>load(true)});
  async function load(fresh=false){
    writeQuery('research',filters);const request=++ticket;list.setAttribute('aria-busy','true');refresh.disabled=true;
    [...tabs.children].forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.category===filters.category)));
    try{
      const data=await api('/api/library?'+new URLSearchParams(filters),undefined,{fresh});if(request!==ticket)return;
      filters.page=data.page;writeQuery('research',filters,{replace:true});feedback.replaceChildren();
      total.textContent=`${data.total} documents · ${data.research_count} notes from .research`;
      list.replaceChildren(...(data.items.length?data.items.map(item=>h('a',{class:'document-item research-row',href:routeHref('research',item.id)+returnURL().slice(returnURL().indexOf('?'))},
        avatar(arts[item.category]||25,'research-row-art'),h('div',{class:'research-row-copy'},h('span',{class:'document-category',text:item.category}),h('strong',{text:item.title}),h('small',{text:item.id.startsWith('research/')?'.research/'+item.path:item.path})),item.read?h('span',{class:'pill pill-ok',text:'Complete'}):null,h('time',{dateTime:item.updated_at,text:new Date(item.updated_at).toLocaleDateString(undefined,{day:'numeric',month:'short'})}),icon('arrow-up-right','icon icon-sm'))):[empty('No notes match your search.',h('button',{class:'btn',type:'button',text:'Clear filters',onclick:()=>{filters.q='';search.value='';filters.category='';filters.page=1;load();}}))]));
      paging.replaceChildren(pagination({...data,label:'Research',onPage:page=>{filters.page=page;return load();},onSize:size=>{filters.size=size;filters.page=1;return load();}}));
    }catch(error){if(request===ticket){feedback.replaceChildren(errorState(error.message,()=>load(true)));if(list.querySelector('.state-loading'))list.replaceChildren();}}
    finally{if(request===ticket){list.setAttribute('aria-busy','false');refresh.disabled=false;}}
  }
  ['',...categories].forEach(category=>tabs.append(h('button',{class:'collection-tab',type:'button',dataset:{category},'aria-pressed':String(category===filters.category),onclick:()=>{filters.category=category;filters.page=1;load();}},category?avatar(arts[category],'tab-art'):icon('grid','icon icon-sm'),category||'All notes')));
  load();
  return h('div',{class:'page research-page'},h('header',{class:'page-head'},h('div',{},h('p',{class:'eyebrow',text:'GOOD IDEAS START HERE'}),h('h1',{text:'Research Studio'}),h('p',{class:'lead',text:'A little curiosity. A clearer next move.'})),refresh),
    studioTabs('library'),h('section',{class:'research-intro'},avatar(25,'research-intro-art'),h('div',{},h('h2',{text:'Your knowledge, connected.'}),h('p',{text:'Briefings, career research and learning notes from your .research folder.'})),h('a',{class:'btn',href:'#/pipeline/brief',text:'Research agents'},icon('arrow-up-right','icon icon-sm'))),
    panel('Your collection',{tools:total},tabs,h('div',{class:'research-search'},icon('search'),search),feedback,list,paging));
}
