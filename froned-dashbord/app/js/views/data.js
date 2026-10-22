import {h} from '../dom.js';
import {api} from '../api.js';
import {S,hooks} from '../state.js';
import {avatar} from '../components/identity.js';
import {icon} from '../icons.js';
import {panel,errorState,loadingState,empty} from '../components/panel.js';
import {selectControl} from '../components/controls.js';
import {num} from '../format.js';

let loading=false;
async function load(){
  if(loading)return;loading=true;
  try {S.dataHub={data:await api('/api/data'),at:Date.now()};}
  catch(error){S.dataHub={...S.dataHub,error:error.message};}
  finally{loading=false;}
  if(S.route.name==='data')hooks.requestRender();
}
const bytes=n=>n<1024?`${n} B`:n<1048576?`${(n/1024).toFixed(1)} KB`:`${(n/1048576).toFixed(1)} MB`;
const categoryArt={Research:25,Reports:29,Profile:20,Resumes:21,Automation:28,Drafts:27};
export function renderData(arg=''){
  if(!S.dataHub)load();
  if(S.dataHubArg!==arg){S.dataCategory=arg==='resumes'?'Resumes':'';S.dataQuery='';S.dataHubArg=arg;}
  const data=S.dataHub?.data;
  const list=h('div',{class:'data-file-list'}),count=h('span',{class:'muted small',role:'status'});
  let limit=24;
  function draw(){
    const matches=(data?.files||[]).filter(f=>(!S.dataCategory||f.category===S.dataCategory)&&`${f.title} ${f.path}`.toLowerCase().includes((S.dataQuery||'').toLowerCase()));
    count.textContent=`${matches.length} saved files`;
    list.replaceChildren(...(matches.length?matches.slice(0,limit).map(file=>h('a',{class:'data-file',href:file.href,...(file.category==='Resumes'?{download:''}:{})},
      avatar(categoryArt[file.category]||29,'file-art'),h('div',{class:'data-file-name'},h('strong',{text:file.title}),h('small',{text:file.path})),
      h('span',{class:'data-file-meta'},h('span',{text:file.category}),h('small',{text:bytes(file.bytes)+' · '+new Date(file.updated_at).toLocaleDateString(undefined,{month:'short',day:'numeric'})})),
      icon(file.category==='Resumes'?'download':'arrow-up-right','icon icon-sm'))):[empty('No saved files match. Try another category or search.')]));
    if(matches.length>limit)list.append(h('button',{class:'btn data-load-more',type:'button',text:`Show more files (${matches.length-limit} remaining)`,onclick:()=>{limit+=24;draw();list.querySelectorAll('.data-file')[limit-24]?.focus();}}));
  }
  const category=selectControl({label:'File category',value:S.dataCategory||'',options:[{value:'',label:'All saved files'},...Object.keys(categoryArt).map(value=>({value,label:value}))],onChange:value=>{S.dataCategory=value;limit=24;draw();}});
  const search=h('label',{class:'search-control'},icon('search'),h('input',{type:'search','aria-label':'Search workspace data',placeholder:'Search names or source paths…',value:S.dataQuery||'',oninput:e=>{S.dataQuery=e.target.value;limit=24;draw();}}));
  draw();
  return h('div',{class:'page data-page'},
    h('header',{class:'page-head'},h('div',{},h('p',{class:'eyebrow',text:'YOUR WORKSPACE, IN ONE PLACE'}),h('h1',{text:'Data hub'}),h('p',{class:'lead',text:'Every opportunity, note and saved file. Connected to the data on this device.'})),h('button',{class:'btn',type:'button',onclick:load},icon('refresh','icon icon-sm'),'Refresh data')),
    S.dataHub?.error?errorState(S.dataHub.error,load):null,
    !data?(S.dataHub?.error?null:loadingState('Reading your workspace data…')):h('div',{class:'stack'},
      h('div',{class:'data-intro'},avatar(26,'data-hero-art'),h('div',{},h('span',{class:'eyebrow',text:'LOCAL SOURCES · ALL TIME'}),h('h2',{text:'The details behind your next move.'}),h('p',{text:'Open a collection to explore its records, or find a saved file below.'})),h('div',{class:'data-freshness'},h('span',{class:'status-pin connected'}),h('span',{text:'Read '+new Date(data.updated_at).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'})}))),
      h('div',{class:'data-source-grid'},data.sources.map(source=>h('a',{class:'data-source',href:source.href},
        h('div',{class:'data-source-top'},avatar(source.art,'source-art'),icon('arrow-up-right','icon icon-sm')),
        h('strong',{class:'data-source-count',text:source.count===null?'—':num(source.count)}),h('h2',{text:source.title}),h('p',{text:source.description}),
        h('div',{class:'data-source-origin'},h('code',{text:source.path}),h('span',{class:source.error?'source-error':'',text:source.error||(!source.exists?'Not created yet':source.id==='flows'?'Saved days':source.id==='applications'?'Attempts, including retries':source.id==='jobs'?'Unique job IDs':'Saved locally')}))))),
      panel('Workspace files',{sub:'Research, reports, profile inputs, resumes and your saved checkpoint.',tools:count},h('div',{class:'data-toolbar'},search,category),list),
      h('p',{class:'small muted',text:'Counts cover all saved history. Open Applications to filter by date, board or outcome. Account credentials and browser session files stay in their dedicated settings.'})));
}
