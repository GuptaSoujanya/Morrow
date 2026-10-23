import { h } from '../dom.js';
import { icon } from '../icons.js';
import { SECTIONS, routeHref } from '../router.js';
import { S } from '../state.js';
import {avatar,workspaceAvatar,richIcon,brandMark} from './identity.js';
const groups = [['WORKSPACE', ['overview','bots','pipeline','todo','records']], ['KNOWLEDGE & DATA', ['research','data','analytics','reports','study']], ['PERSONAL', ['files','setup']]];
const sectionArt={research:25,data:26,pipeline:28,todo:27,reports:29,study:30,setup:31};
const allGroups = [groups[1],groups[0],groups[2],['Bot controls',['naukri','boards','sites','profile','linkedin','linkedin-profile','outreach','resume']]];
const primary = ['overview', 'bots', 'todo', 'analytics'];
function navLink(key, mobile = false) {
  const [, title, name] = SECTIONS.find(([id]) => id === key);
  const count = key === 'todo' ? (S.status?.questions.length || 0) + (S.status?.facts.length || 0) : 0;
  const active = S.route.name === key || (key==='bots' && ['naukri','boards','sites','profile','linkedin','resume','outreach','linkedin-profile'].includes(S.route.name));
  return h('a', { class:`nav-item ${active ? 'active' : ''}`, href:routeHref(key), title,
    'aria-current':S.route.name===key ? 'page' : null,
    onclick:() => { if(mobile) document.getElementById('mobile-nav').close(); } }, sectionArt[key]!==undefined?avatar(sectionArt[key],'nav-art'):richIcon(name),h('span',{class:'nav-title',text:title}),count ? h('span',{class:'badge','aria-hidden':'true',text:count}):null);
}
function openMore() {
  const dialog=document.getElementById('mobile-nav');
  dialog.replaceChildren(h('div',{class:'mobile-menu'},h('div',{class:'editor-toolbar'},h('h2',{text:'Your workspace'}),h('button',{class:'icon-btn',type:'button','aria-label':'Close navigation',onclick:()=>dialog.close()},icon('x'))),
    ...allGroups.map(([title,keys])=>h('div',{},h('p',{class:'eyebrow',text:title}),...keys.map(key=>navLink(key,true))))));
  dialog.showModal();
}
export function renderNav() {
  const root=document.getElementById('nav'),previous=root.querySelector('.sidebar-scroll');
  const scrollTop=previous?.scrollTop||0,changed=root.dataset.route!==S.route.name;
  const focused=document.activeElement?.closest('#nav a')?.getAttribute('href');
  const sections=h('div',{class:'sidebar-scroll',tabIndex:0,'aria-label':'Navigation sections'},...groups.map(([title,keys])=>h('div',{class:'nav-group'},h('p',{class:'nav-group-label',text:title}),...keys.map(key=>navLink(key)))));
  root.replaceChildren(
    h('a',{class:'sidebar-brand',href:'#/overview',title:'Morrow home'},brandMark(),h('span',{},h('strong',{text:'morrow'}),h('small',{text:'YOUR NEXT MOVE.'}))),
    h('a',{class:'workspace-profile',href:'#/files/profile',title:'Open my profile'},avatar(workspaceAvatar(),'profile-avatar'),h('div',{},h('strong',{text:S.status?.name || 'Your workspace'}),h('span',{text:'Personal workspace'})),icon('chevron-down','icon icon-sm')),
    sections,
    h('div',{class:'sidebar-foot'},h('span',{class:`status-pin ${S.online ? 'connected' : ''}`}),h('div',{},h('strong',{text:S.online ? 'Workspace connected' : 'Reconnecting…'}),h('p',{text:'Private · on this device'}))),
    h('div',{class:'mobile-primary'},...primary.map(key=>navLink(key)),h('button',{class:`nav-item ${primary.includes(S.route.name)?'':'active'}`,type:'button','aria-label':'More sections',onclick:openMore},icon('sliders'),h('span',{class:'nav-title',text:'More'}))));
  sections.scrollTop=scrollTop;root.dataset.route=S.route.name;
  if(focused&&!changed)[...root.querySelectorAll('a')].find(a=>a.getAttribute('href')===focused)?.focus({preventScroll:true});
  if(changed&&matchMedia('(min-width:768px)').matches){
    const active=sections.querySelector('[aria-current=page]');
    if(active){const a=active.getBoundingClientRect(),s=sections.getBoundingClientRect();if(a.bottom>s.bottom)sections.scrollTop+=a.bottom-s.bottom+8;else if(a.top<s.top)sections.scrollTop-=s.top-a.top+8;}
  }
}
