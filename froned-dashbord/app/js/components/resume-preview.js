import {h} from '../dom.js';
import {icon} from '../icons.js';

export function previewResume(file){
  const previous=document.activeElement;
  const url=new URL(file.href,window.location.origin);
  if(url.origin!==window.location.origin||url.pathname!=='/api/resume-file')return;
  url.searchParams.set('preview','1');
  const src=url.pathname+url.search;
  const status=h('span',{class:'small muted',role:'status',text:'Opening preview…'});
  const dialog=h('dialog',{class:'resume-dialog','aria-labelledby':'resume-preview-title'});
  const frame=h('iframe',{class:'resume-preview-frame',title:`Resume preview: ${file.title}`,src,referrerpolicy:'no-referrer',onload:()=>{status.textContent='PDF preview';},onerror:()=>{status.textContent='Preview unavailable. Open the PDF in a new tab below.';}});
  dialog.append(h('header',{class:'preview-head'},h('div',{},h('p',{class:'eyebrow',text:'RESUME REVIEW'}),h('h2',{id:'resume-preview-title',text:file.title})),h('button',{class:'icon-btn',type:'button','aria-label':'Close resume preview',onclick:()=>dialog.close()},icon('x'))),
    frame,h('footer',{class:'preview-foot'},h('div',{},status,h('p',{class:'small muted',text:'Preview not displaying? Open it in a new tab.'})),h('div',{class:'row'},h('a',{class:'btn',href:src,target:'_blank',rel:'noopener',text:'Open PDF'}),h('a',{class:'btn btn-primary',href:file.href,download:'',text:'Download'},icon('download','icon icon-sm')))));
  dialog.addEventListener('close',()=>{dialog.remove();if(previous?.isConnected)previous.focus();});
  document.body.append(dialog);dialog.showModal();
}
