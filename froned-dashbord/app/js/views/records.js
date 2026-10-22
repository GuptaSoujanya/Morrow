import { h } from '../dom.js';
import { icon } from '../icons.js';
import { api } from '../api.js';
import { S } from '../state.js';
import { panel, dataTable, empty, errorState } from '../components/panel.js';
import { num } from '../format.js';
import { selectControl } from '../components/controls.js';

const boardNames={naukri:'Naukri',hirist:'Hirist',instahyre:'Instahyre',cutshort:'Cutshort',wellfound:'Wellfound',external:'Company site'};
export function outcomePill(row) {return h('span',{class:`result-pill result-${row.kind}`,text:row.label});}
export function recordTable(rows, compact=false) {
  return dataTable(compact ? [['Role / company'],['Platform'],['Outcome'],['When']] : [['Role / company'],['Platform'],['Outcome'],['Match score','num'],['When']],
    rows.map(row=>h('tr',{},
      h('td',{},h('div',{class:'record-role'},row.url ? h('a',{href:row.url,target:'_blank',rel:'noopener noreferrer',text:row.title || `Job ${row.job_id}`},icon('arrow-up-right','icon icon-sm')) : h('strong',{text:row.title || `Job ${row.job_id}`})),
        h('span',{class:'record-company',text:row.company || 'Company not recorded'}),row.detail ? h('details',{class:'record-detail'},h('summary',{text:'Outcome details'}),h('p',{text:row.detail})) : null),
      h('td',{text:boardNames[row.board] || row.board}),h('td',{},outcomePill(row)),
      compact ? null : h('td',{class:'num tabular',text:row.score==null ? 'Not scored' : `${Math.round(row.score)}/100`}),
      h('td',{class:'record-date'},h('time',{dateTime:row.at,text:new Date(row.at).toLocaleDateString(undefined,{day:'numeric',month:'short'})}),h('small',{text:new Date(row.at).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'})})))));
}
function select(label, options, value, change) {
  return selectControl({label,options:options.map(([value,label])=>({value,label})),value,onChange:change});
}
export function renderRecords(arg='') {
  if(S.recordsArg!==arg || !S.recordFilters){
    const [kind='applications',outcome='all',days]=arg.split('/');
    S.recordFilters={kind:kind==='jobs'?'jobs':'applications',outcome,days:days==='0'?'0':String(S.overviewDays),board:'all',q:'',sort:'recent',page:1};S.recordsArg=arg;
  }
  const f=S.recordFilters;
  if(S.pendingRecordQuery!==undefined){f.q=S.pendingRecordQuery;f.page=1;delete S.pendingRecordQuery;}
  let request=0,timer;
  const body=h('div',{class:'records-body','aria-live':'polite'});
  const count=h('p',{class:'records-count'});
  const status=select('Outcome',[['all','All outcomes'],['submitted','Confirmed submissions'],['matched','Above match threshold'],['not_attempted','Not attempted']],f.outcome,value=>{f.outcome=value;f.page=1;load();});
  const refresh=h('button',{class:'btn',type:'button',onclick:()=>load()},icon('refresh','icon icon-sm'),'Refresh');
  const draw= data=>{
    const current=f.outcome;
    const options=[['all','All outcomes'],[f.kind==='jobs'?'matched':'submitted',f.kind==='jobs'?'Above match threshold':'Confirmed submissions'],...data.statuses.map(s=>[s,s.replaceAll('_',' ')])];
    if(!options.some(([key])=>key===current)) options.push([current,current.replaceAll('_',' ')]);
    status.setOptions(options.map(([value,label])=>({value,label})));status.value=current;
    count.textContent=`${num(data.total)} ${f.kind==='jobs'?'jobs':'application attempts'} · ${f.days==='0'?'all recorded dates':`last ${f.days} days`} · refreshed ${new Date(data.updated_at).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'})}`;
    body.replaceChildren(data.rows.length ? recordTable(data.rows) : empty('No records match these filters.',h('button',{class:'btn',type:'button',text:'Clear search & outcome',onclick:()=>{f.q='';search.value='';f.outcome='all';f.page=1;load();}})),
      h('div',{class:'records-pagination'},h('span',{text:`Page ${data.page} of ${data.pages}`}),h('div',{class:'row'},h('button',{class:'btn btn-sm',type:'button',text:'Previous',disabled:data.page===1,onclick:()=>{f.page=data.page-1;load();}}),h('button',{class:'btn btn-sm',type:'button',text:'Next',disabled:data.page===data.pages,onclick:()=>{f.page=data.page+1;load();}}))));
  };
  async function load(){
    const ticket=++request;refresh.disabled=true;body.setAttribute('aria-busy','true');count.textContent='Loading records…';
    try {const data=await api('/api/records?'+new URLSearchParams(f));if(ticket===request)draw(data);}
    catch(error){if(ticket===request){count.textContent='Records could not be loaded';body.replaceChildren(errorState(error.message,load));}}
    finally{if(ticket===request){refresh.disabled=false;body.setAttribute('aria-busy','false');}}
  }
  const search=h('input',{type:'search',class:'input',placeholder:'Search role, company or outcome…','aria-label':'Search records',value:f.q,oninput:e=>{f.q=e.target.value;f.page=1;clearTimeout(timer);timer=setTimeout(load,250);}});
  const toolbar=h('div',{class:'records-filters'},search,
    select('Record type',[['applications','Application attempts'],['jobs','Discovered jobs']],f.kind,value=>{f.kind=value;f.outcome='all';f.page=1;load();}),
    select('Board',[['all','All platforms'],...Object.entries(boardNames)],f.board,value=>{f.board=value;f.page=1;load();}),status,
    select('Record period',[['7','Last 7 days'],['14','Last 14 days'],['30','Last 30 days'],['0','All time']],f.days,value=>{f.days=value;f.page=1;load();}),
    select('Sort records',[['recent','Most recent'],['score','Highest score']],f.sort,value=>{f.sort=value;f.page=1;load();}));
  load();
  return h('div',{class:'page records-page'},h('header',{class:'page-head'},h('div',{},h('p',{class:'eyebrow',text:'EVERY MOVE, IN ONE PLACE'}),h('h1',{text:'Applications'}),h('p',{class:'lead',text:'Find a role. Check the outcome. Know what happens next.'})),refresh),
    panel('Explore your ledger',{sub:'Applications are recorded attempts; discovered jobs are unique job IDs. Scores show the latest recorded match. Missing role titles are shown by job ID.'},toolbar,count,body));
}
