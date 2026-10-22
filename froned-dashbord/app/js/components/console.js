/** Persistent, nonmodal Activity sheet. Only the dashboard-owned runner is controllable. */
import {h} from '../dom.js';
import {icon} from '../icons.js';
import {api} from '../api.js';
import {toast} from './toast.js';
import {confirmDialog} from './dialog.js';
import {avatar} from './identity.js';
import {S} from '../state.js';
import {duration} from '../format.js';
let parts=null,wasRunning=false;

export function setConsoleSize(size){
  S.consoleSize=size;
  if(!parts)return;
  const collapsed=size==='collapsed';
  if(collapsed && parts.body.contains(document.activeElement))parts.toggleButton.focus();
  parts.root.dataset.size=size;
  parts.body.hidden=collapsed;
  parts.toggleButton.setAttribute('aria-expanded',String(!collapsed));
  parts.toggleButton.title=collapsed?'Open Activity':'Collapse Activity';
  parts.toggleIcon.replaceChildren(icon(collapsed?'chevron-up':'chevron-down','icon icon-sm'));
  parts.resize.textContent=size==='expanded'?'Compact view':'Expand output';
  if(!collapsed)requestAnimationFrame(()=>{if(parts.follow)parts.lines.scrollTop=parts.lines.scrollHeight;});
}
async function stopRun(){
  const stopping=S.status?.run.stopping;
  if(!await confirmDialog(stopping?{title:'Force stop the run?',body:'This ends it immediately; it may leave a browser window open.',ok:'Force stop',tone:'danger'}:{title:'Stop the run?',body:'It gets a chance to close its browser cleanly. Press Stop again to force it.',ok:'Stop',tone:'danger'}))return;
  try{const reply=await api('/api/stop',{});toast(reply.message,reply.ok?'info':'warn');}
  catch(error){toast(error.message,'error');}
}
async function copyConsole(){
  const text=[...parts.lines.children].map(line=>line.textContent).join('\n');
  try{await navigator.clipboard.writeText(text);toast('Output copied.','info',2000);}
  catch{toast('The browser didn’t allow copying.','warn');}
}
export function initConsole(){
  const label=h('span',{class:'activity-caption',text:'Ready when you are'});
  const dot=h('span',{class:'console-dot'});
  const toggleIcon=h('span',{class:'activity-chevron'},icon('chevron-up','icon icon-sm'));
  const toggleButton=h('button',{class:'activity-launch',type:'button',title:'Open Activity','aria-expanded':'false','aria-controls':'activity-content',onclick:()=>setConsoleSize(S.consoleSize==='collapsed'?'normal':'collapsed')},
    avatar(22,'activity-avatar'),h('span',{class:'activity-launch-copy'},h('strong',{},'Activity',dot),label),toggleIcon);
  const summaryTitle=h('strong',{text:'Your crew is ready'});
  const summaryText=h('span',{text:'Run a bot to follow its progress here.'});
  const status=h('span',{class:'activity-state',text:'Standby',role:'status'});
  const lines=h('div',{class:'console-lines',role:'log','aria-label':'Run output','aria-live':'polite',tabindex:'0'});
  const empty=h('div',{class:'activity-empty'},avatar(23,'activity-empty-art'),h('h3',{text:'A little quiet. A lot of possibility.'}),h('p',{text:'Start a bot or flow. Its live output and final result will appear here.'}),h('a',{class:'btn',href:'#/bots',onclick:()=>setConsoleSize('collapsed'),text:'Find your next bot'}));
  const stopBtn=h('button',{class:'btn btn-sm btn-danger',type:'button',onclick:stopRun,hidden:true},icon('stop','icon icon-sm'),'Stop');
  const copy=h('button',{class:'btn btn-sm',type:'button','aria-label':'Copy output',onclick:copyConsole,disabled:true},icon('copy','icon icon-sm'),'Copy');
  const resize=h('button',{class:'text-link',type:'button',text:'Expand output',onclick:()=>setConsoleSize(S.consoleSize==='expanded'?'normal':'expanded')});
  const jump=h('button',{class:'activity-jump',type:'button',text:'Latest output ↓',hidden:true,onclick:()=>{parts.follow=true;lines.scrollTop=lines.scrollHeight;jump.hidden=true;}});
  const body=h('div',{id:'activity-content',class:'console-body',hidden:true},
    h('div',{class:'activity-summary'},h('div',{},summaryTitle,summaryText),status),
    h('div',{class:'activity-log-wrap'},empty,lines,jump),
    h('div',{class:'activity-footer'},resize,h('div',{class:'row'},copy,stopBtn)));
  const root=h('section',{class:'console','aria-label':'Activity',dataset:{size:'collapsed'},onkeydown:event=>{if(event.key==='Escape'&&!document.querySelector('dialog[open]')){event.preventDefault();setConsoleSize('collapsed');}}},toggleButton,body);
  document.getElementById('console-dock').append(root);
  parts={root,body,label,dot,lines,empty,stopBtn,copy,resize,jump,toggleIcon,toggleButton,summaryTitle,summaryText,status,follow:true};
  lines.addEventListener('scroll',()=>{parts.follow=lines.scrollTop+lines.clientHeight>=lines.scrollHeight-24;jump.hidden=parts.follow;});
  lines.hidden=true;
  return parts;
}
export function appendRunLines(entries){
  if(!parts||!entries.length)return;
  for(const [,text] of entries)parts.lines.append(h('span',{class:'console-line',text}));
  while(parts.lines.children.length>5000)parts.lines.firstChild.remove();
  parts.lines.hidden=false;parts.empty.hidden=true;parts.copy.disabled=false;
  if(parts.follow)parts.lines.scrollTop=parts.lines.scrollHeight;
  else parts.jump.hidden=false;
}
export function clearConsoleLines(){
  if(!parts)return;parts.lines.replaceChildren();parts.lines.hidden=true;parts.empty.hidden=false;parts.copy.disabled=true;parts.jump.hidden=true;parts.follow=true;
}
export function updateConsoleStatus(run){
  if(!parts||!run)return;
  const live=run.running,last=run.last;
  const state=live?(run.stopping?'Stopping':'Running'):last?(last.stopped?'Stopped':last.exit===0?'Completed':'Needs attention'):'Standby';
  parts.root.dataset.state=live?'live':last&&!last.stopped&&last.exit!==0?'error':'idle';
  parts.dot.className=`console-dot ${live?'live':''}`;
  parts.label.textContent=live?`${run.label} · ${duration(run.seconds)}`:last?`${last.label} · ${state.toLowerCase()}`:'Ready when you are';
  parts.summaryTitle.textContent=live?run.label:last?last.label:'Your crew is ready';
  parts.summaryText.textContent=live?`Elapsed ${duration(run.seconds)} · ${run.stopping?'Closing the run…':'Started from this workspace'}`:last?`${state} · ${duration(last.seconds)}${last.finished?' · '+new Date(last.finished).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'}):''}`:'Run a bot to follow its progress here.';
  if(parts.status.textContent!==state)parts.status.textContent=state;
  parts.stopBtn.hidden=!live;
  parts.stopBtn.replaceChildren(icon('stop','icon icon-sm'),run.stopping?'Force stop':'Stop');
  if(live&&!wasRunning&&S.consoleSize==='collapsed')setConsoleSize('normal');
  wasRunning=live;
}
