import {h} from '../dom.js';
import {avatar,workspaceAvatar} from './identity.js';
import {S,hooks} from '../state.js';
import {icon} from '../icons.js';

const names=['Lavender headphones','Mint antenna','Peach explorer','Blue astronaut','Cream robot','Sage companion','Rose antenna','Slate glasses','Midnight headphones','Violet antenna','Pearl blush','Mint visor','Lavender star','Peach glasses','Chrome astronaut','Morrow planet','Mint sprout','Peach studio','Lavender spark','Blue scholar','Cream bowtie','Lilac cat','Silver orbit','Sage explorer'];
const extras=['Lavender bunny','Mint mushroom','Peach pilot','Pearl professor','Slate bear','Violet beanie','Mint stargazer','Cream earmuffs'];
const choices=[...names.map((name,index)=>({name,index})),...extras.map((name,i)=>({name,index:i+32}))];
export function openAvatarPicker(){
  const previous=document.activeElement;
  let selected=workspaceAvatar();
  const dialog=h('dialog',{class:'confirm-dialog avatar-dialog','aria-labelledby':'avatar-title'});
  const preview=avatar(selected,'avatar-preview');
  const grid=h('div',{class:'avatar-grid',role:'group','aria-label':'Workspace avatars'});
  const feedback=h('p',{class:'field-error',role:'alert',hidden:true});
  choices.forEach(({name,index})=>grid.append(h('button',{type:'button',class:'avatar-choice','aria-label':name,'aria-pressed':String(index===selected),onclick:()=>{
    selected=index;const next=avatar(index,'avatar-preview');preview.className=next.className;preview.style.cssText=next.style.cssText;preview.dataset.avatar=index;
    [...grid.children].forEach((b,i)=>b.setAttribute('aria-pressed',String(choices[i].index===index)));
  }},avatar(index))));
  dialog.append(h('div',{class:'confirm-body'},h('div',{class:'avatar-picker-heading'},preview,h('div',{},h('h2',{id:'avatar-title',text:'Find your Morrow alter ego'}),h('p',{class:'muted',text:'Your workspace, a little more you.'}))),
    grid,h('p',{class:'small muted',text:'Only changes your avatar in Morrow on this browser. Your platform profile photos stay as they are.'}),feedback,
    h('div',{class:'row end'},h('button',{class:'btn',type:'button',text:'Cancel',onclick:()=>dialog.close()}),h('button',{class:'btn btn-primary',type:'button',text:'Use this avatar',onclick:()=>{
      try{localStorage.setItem('orbit-avatar',String(selected));}catch{feedback.hidden=false;feedback.textContent='Browser storage is unavailable. Allow local storage, then try again.';return;}
      S.pendingFocusKey='change-avatar';dialog.close();hooks.requestRender();
    }}))));
  dialog.addEventListener('close',()=>{dialog.remove();requestAnimationFrame(()=>{(previous?.isConnected?previous:document.getElementById('change-avatar'))?.focus();});});
  document.body.append(dialog);dialog.showModal();grid.children[choices.findIndex(c=>c.index===selected)].focus();
}
export function avatarPickerButton(){return h('button',{id:'change-avatar',dataset:{focusKey:'change-avatar'},class:'btn',type:'button',onclick:openAvatarPicker},icon('person','icon icon-sm'),'Change avatar');}
