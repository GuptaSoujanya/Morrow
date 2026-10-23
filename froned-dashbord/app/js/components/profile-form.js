import {parseDocument,isMap,isSeq,isScalar} from 'yaml';
import {h} from '../dom.js';
import {selectControl} from './controls.js';

const names={full_name:'Full name',first_name:'First name',last_name:'Last name',email:'Email address',phone:'Phone number',current_location:'Current location',preferred_locations:'Preferred locations',total_experience_years:'Experience in years',current_ctc_lpa:'Current CTC · LPA',expected_ctc_lpa:'Expected CTC · LPA',notice_period_days:'Notice period · days',titles:'Target roles',skills:'Skills',highest_qualification:'Highest qualification',extra_facts:'Additional facts'};
const label=key=>names[key]||key.replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
const groupFor=path=>path[0]==='extra_facts'?'Background':/name|email|phone|current_location/.test(path[0])?'Identity':/preferred|willing|serving|passport|authorization/.test(path[0])?'Preferences':'Career';
export function profileForm(file,onChange){
  let doc;try{doc=parseDocument(file.draft,{keepSourceTokens:true});}catch{return null;}
  if(doc.errors.length||!isMap(doc.contents))return null;
  const root=h('div',{class:'profile-form'}),fields=[];
  function walk(node,path=[]){
    if(isMap(node))for(const pair of node.items){if(isScalar(pair.key))walk(pair.value,[...path,String(pair.key.value)]);}
    else if(isScalar(node)||node===null||(isSeq(node)&&node.items.every(isScalar)))fields.push({path,node});
  }
  walk(doc.contents);
  const search=h('input',{class:'input',type:'search','aria-label':'Find a profile field',placeholder:'Find a fact, skill or preference…'});
  const tabs=h('div',{class:'settings-tabs',role:'group','aria-label':'Profile categories'}),rows=h('div',{class:'profile-field-grid'});
  let group='Identity';
  const filter=()=>{for(const row of rows.children)row.hidden=(search.value? !row.dataset.search.includes(search.value.toLowerCase()):row.dataset.group!==group);for(const tab of tabs.children)tab.setAttribute('aria-pressed',String(tab.dataset.group===group));};
  ['Identity','Career','Preferences','Background'].forEach(name=>tabs.append(h('button',{class:'filter-chip',type:'button',text:name,dataset:{group:name},onclick:()=>{group=name;search.value='';filter();}})));
  fields.forEach(({path,node},i)=>{
    const key=path.at(-1),title=label(key),isList=isSeq(node),value=isList?node.items.map(n=>n.value??'').join('\n'):node?.value??'';
    const update=value=>{if(isScalar(node))node.value=value;else doc.setIn(path,value);file.draft=doc.toString({lineWidth:0});onChange();};
    let input;
    if(typeof value==='boolean'){
      input=selectControl({label:title,value:String(value),options:[{value:'true',label:'Yes'},{value:'false',label:'No'}],onChange:value=>update(value==='true')});
    }else{
      const multiline=isList||String(value).length>100||/history|reason|certification/.test(key);
      input=h(multiline?'textarea':'input',{id:`profile-field-${i}`,class:multiline?'textarea profile-answer':'input',...(multiline?{rows:isList?4:3}:{type:typeof value==='number'?'number':key==='email'?'email':'text',...(typeof value==='number'?{step:'any'}:{})}),value:String(value),spellcheck:'false',oninput:e=>{
        if(!e.target.checkValidity())return;
        update(isList?e.target.value.split('\n').map(v=>v.trim()).filter(Boolean):typeof value==='number'?(e.target.value===''?null:Number(e.target.value)):e.target.value);
      }});
    }
    rows.append(h('div',{class:`profile-field${isList?' profile-field-wide':''}`,dataset:{group:groupFor(path),search:(title+' '+path.join(' ')).toLowerCase()}},h('label',{class:'field-label',for:input.id||null,text:title}),input,h('span',{class:'field-hint',text:isList?'One item per line':path[0]==='extra_facts'?'Additional fact used by your crew':/ctc/.test(key)?'Lakhs per annum · keep this accurate':'Saved in your source profile'})));
  });
  search.addEventListener('input',filter);filter();
  root.append(h('div',{class:'profile-form-head'},tabs,search),rows);
  root.validate=()=>{const invalid=[...root.querySelectorAll('input,textarea')].find(input=>!input.checkValidity());invalid?.reportValidity();return !invalid;};
  return root;
}
