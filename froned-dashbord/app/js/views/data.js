import {h} from '../dom.js';
import {api} from '../api.js';
import {avatar} from '../components/identity.js';
import {icon} from '../icons.js';
import {panel,errorState,loadingState,empty} from '../components/panel.js';
import {selectControl} from '../components/controls.js';
import {pagination} from '../components/pagination.js';
import {previewResume} from '../components/resume-preview.js';
import {readQuery,writeQuery,pageNumber,choice} from '../url-state.js';
import {num} from '../format.js';

const bytes=n=>n<1024?`${n} B`:n<1048576?`${(n/1024).toFixed(1)} KB`:`${(n/1048576).toFixed(1)} MB`;
const categoryArt={Research:25,Reports:29,Profile:20,Resumes:43,Automation:28,Drafts:27};
export function renderData(arg=''){
  const q=readQuery();
  const filters={category:choice(q.get('category')||(arg==='resumes'?'Resumes':''),['',...Object.keys(categoryArt)],''),q:q.get('q')||'',page:pageNumber(q.get('page')),size:choice(Number(q.get('size')),[12,24,48],12)};
  writeQuery('data',filters,{replace:true});
  let ticket=0,timer;
  const sources=h('div',{class:'source-strip'}),list=h('div',{class:'data-file-list'},loadingState('Finding your saved files…'));
  const paging=h('div'),feedback=h('div'),count=h('span',{class:'muted small',role:'status'});
  const refresh=h('button',{class:'btn',type:'button',onclick:()=>load(true)},icon('refresh','icon icon-sm'),'Refresh data');
  async function load(fresh=false){
    writeQuery('data',filters);const id=++ticket;refresh.disabled=true;list.setAttribute('aria-busy','true');
    try{
      const data=await api('/api/data?'+new URLSearchParams(filters),undefined,{fresh});
      if(id!==ticket)return;
      feedback.replaceChildren();filters.page=data.page;writeQuery('data',filters,{replace:true});
      count.textContent=`${num(data.total)} saved files`;
      sources.replaceChildren(...data.sources.map(source=>h('a',{class:'source-tile',href:source.href},avatar(source.art,'source-art'),h('div',{},h('strong',{text:source.count===null?'—':num(source.count)}),h('span',{text:source.title})),source.error?h('small',{class:'field-error',text:source.error}):null)));
      list.replaceChildren(...(data.files.length?data.files.map(file=>h('div',{class:'data-file'},avatar(categoryArt[file.category]||29,'file-art'),
        h('div',{class:'data-file-name'},h('strong',{text:file.title}),h('small',{text:file.path})),
        h('span',{class:'data-file-meta'},h('span',{text:file.category}),h('small',{text:bytes(file.bytes)+' · '+new Date(file.updated_at).toLocaleDateString(undefined,{month:'short',day:'numeric'})})),
        file.category==='Resumes'?h('div',{class:'file-actions'},h('button',{class:'btn btn-sm',type:'button',onclick:()=>previewResume(file),'aria-label':`Preview ${file.title}`},icon('eye','icon icon-sm'),'Preview'),h('a',{class:'icon-btn',href:file.href,download:'','aria-label':`Download ${file.title}`},icon('download','icon icon-sm'))):h('a',{class:'btn btn-sm',href:file.href,'aria-label':`Open ${file.title}`,text:'Open'},icon('arrow-up-right','icon icon-sm')))):[empty('No saved files match.',h('button',{class:'btn',type:'button',text:'Clear filters',onclick:()=>{filters.q='';search.value='';filters.category='';category.value='';filters.page=1;load();}}))]));
      paging.replaceChildren(pagination({...data,label:'Workspace files',onPage:page=>{filters.page=page;return load();},onSize:size=>{filters.size=size;filters.page=1;return load();}}));
    }catch(error){if(id===ticket){feedback.replaceChildren(errorState(error.message,()=>load(true)));if(list.querySelector('.state-loading'))list.replaceChildren();}}
    finally{if(id===ticket){refresh.disabled=false;list.setAttribute('aria-busy','false');}}
  }
  const category=selectControl({label:'File category',value:filters.category,options:[{value:'',label:'All saved files'},...Object.keys(categoryArt).map(value=>({value,label:value}))],onChange:value=>{filters.category=value;filters.page=1;load();}});
  const search=h('input',{type:'search','aria-label':'Search workspace data',placeholder:'Find a resume, note or file…',value:filters.q,dataset:{focusKey:'data-search'},oninput:e=>{filters.q=e.target.value;filters.page=1;clearTimeout(timer);timer=setTimeout(()=>{if(search.isConnected)load();},250);}});
  load();
  return h('div',{class:'page data-page'},h('header',{class:'page-head'},h('div',{},h('p',{class:'eyebrow',text:'EVERYTHING YOU’VE BUILT'}),h('h1',{text:'Data hub'}),h('p',{class:'lead',text:'Browse your work. Preview a resume. Find the details that matter.'})),refresh),
    sources,panel('Your files',{sub:'Saved on this device · select a collection above to explore its records',tools:count},h('div',{class:'data-toolbar'},h('label',{class:'search-control'},icon('search'),search),category),feedback,list,paging));
}
