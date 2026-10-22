import {h} from '../dom.js';
import {api} from '../api.js';
import {S,hooks} from '../state.js';
import {panel,errorState,empty,loadingState} from '../components/panel.js';
import {quickButton} from '../forms.js';
import {selectControl} from '../components/controls.js';
import {journeyBanner} from '../components/journey.js';
import {avatar} from '../components/identity.js';
import {routeHref} from '../router.js';

export const READER_STYLE=`<style>html{color-scheme:dark}body{margin:0;padding:24px;color:#f2f3f7;background:#1b1d24;font:15px/1.75 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}h1,h2,h3{line-height:1.3;letter-spacing:-.02em}h1{font-size:26px}h2{font-size:21px;margin-top:32px}a{color:#b9a5ff}table{display:block;max-width:100%;overflow:auto;border-collapse:collapse;font-size:13px}td,th{border-bottom:1px solid #30333d;padding:10px;text-align:left}th{background:#242730}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#242730;padding:16px;border-radius:8px;font-size:13px}code{overflow-wrap:anywhere}img{max-width:100%}:focus-visible{outline:2px solid #b9a5ff}@media(max-width:450px){body{padding:12px}h1{font-size:23px}}</style>`;
let loading=false;
async function loadLibrary(){
  if(loading)return;loading=true;
  try{S.library={data:await api('/api/library'),at:Date.now()};}catch(error){S.library={error:error.message,at:Date.now()};}finally{loading=false;}
  if(S.route.name==='research')hooks.requestRender();
}
async function loadDoc(id){
  S.document={id,loading:true};
  try{const data=await api('/api/document?id='+encodeURIComponent(id));if(S.document.id===id)S.document={id,data};}catch(error){if(S.document.id===id)S.document={id,error:error.message};}
  if(S.route.name==='research' && S.route.arg===id)hooks.requestRender();
}
export function renderResearch(id){
  if(!S.library)loadLibrary();
  if(id && S.document?.id!==id)loadDoc(id);
  const items=S.library?.data?.items || [];
  const list=h('div',{class:'document-list'});
  const draw=()=>{
    const shown=items.filter(item=>(!S.libraryCategory || item.category===S.libraryCategory) && `${item.title} ${item.path}`.toLowerCase().includes((S.libraryQuery||'').toLowerCase()));
    list.replaceChildren(...(shown.length ? shown.map(item=>h('a',{class:'document-item',href:routeHref('research',item.id),'aria-current':id===item.id?'page':null},h('span',{class:'document-category',text:item.category}),h('strong',{text:item.title}),h('small',{text:item.id.startsWith('research/')?'.research/'+item.path:item.path}))) : [empty('No documents match your search.')]));
  };
  const search=h('input',{class:'input',type:'search',placeholder:'Find a document…','aria-label':'Find a document',value:S.libraryQuery||'',oninput:e=>{S.libraryQuery=e.target.value;draw();}});
  const categories=['Briefing','Learning','Resume research','Email drafts'];
  const category=selectControl({label:'Document category',options:[{value:'',label:'All documents'},...categories.map(value=>({value,label:value}))],value:S.libraryCategory||'',onChange:value=>{S.libraryCategory=value;draw();}});draw();

  let reader;
  if(!id)reader=h('div',{class:'stack'},
    journeyBanner({image:25,eyebrow:'YOUR RESEARCH, READY TO READ',title:`${items.filter(i=>i.id.startsWith('research/')).length} notes in .research`,body:'Daily briefings, learning plans and deeper research, collected from your workspace.',action:h('a',{class:'btn btn-primary',href:'#/pipeline/brief',text:'Configure research agents'})}),
    h('div',{class:'library-collections'},categories.map((name,i)=>h('button',{class:'collection-card',type:'button',onclick:()=>{S.libraryCategory=name;category.value=name;draw();search.focus();}},avatar([25,30,23,27][i],'collection-art'),h('strong',{text:name}),h('span',{text:`${items.filter(item=>item.category===name).length} documents` })))),
    panel('Start reading',{sub:'Latest saved documents from your workspace'},items.length?h('div',{class:'reading-grid'},items.slice(0,6).map(item=>h('a',{class:'reading-card',href:routeHref('research',item.id)},h('span',{class:'document-category',text:item.category}),h('strong',{text:item.title}),h('small',{text:item.id.startsWith('research/')?'.research/'+item.path:item.path})))):empty('Your library is ready for its first document. Run a research flow to create one.')),
    panel('Keep your learning moving',{},h('p',{class:'muted',text:'Finished today’s research learning plan? Save your progress here.'}),quickButton('pipeline','Mark learning day done',{command:'learn',done:true},{confirm:{title:'Mark today’s learning done?',body:'This records the current learning day as completed. Repeating this on the same date does not skip another day.'}})));
  else if(S.document?.error)reader=errorState(S.document.error,()=>loadDoc(id));
  else if(!S.document?.data)reader=empty('Opening document…');
  else {
    const frame=h('iframe',{class:'document-reader',title:items.find(item=>item.id===id)?.title || 'Generated document',sandbox:'allow-popups allow-top-navigation-by-user-activation'});
    frame.srcdoc=READER_STYLE+S.document.data.html;
    reader=panel(items.find(item=>item.id===id)?.title || 'Generated document',{sub:items.find(item=>item.id===id)?.path,tools:h('a',{class:'btn btn-sm',href:'#/research',text:'All documents'})},frame);
  }
  return h('div',{class:`page research-page${id?' has-document':''}`},h('header',{class:'page-head'},h('div',{},h('p',{class:'eyebrow',text:'LEVEL UP, AT YOUR PACE'}),h('h1',{text:'Research Studio'}),h('p',{class:'lead',text:'Your .research folder, learning plans and saved drafts — all in one library.'})),h('button',{class:'btn',type:'button',text:'Refresh library',onclick:()=>{if(id)loadDoc(id);loadLibrary();}})),
    S.library?.error ? errorState(S.library.error,loadLibrary) : !S.library?.data ? loadingState('Reading your research library…') : h('div',{class:'library-layout'},panel('Documents',{cls:'library-sidebar'},search,category,list),h('div',{class:'library-content'},reader)));
}
