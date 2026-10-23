import { h } from '../dom.js';
import { api } from '../api.js';
import { S, hooks } from '../state.js';
import { panel } from '../components/panel.js';
import { journeyBanner, progressRing } from '../components/journey.js';
import { richIcon } from '../components/identity.js';
import {readQuery,withQuery} from '../url-state.js';
import { icon } from '../icons.js';

function readerHref(route) { return `${S.meta?.course || '/course/'}#/${route}`; }
function moduleRow(m, i) {
  const feedback=h('p',{class:'field-error',role:'status',hidden:true});
  const check=h('input',{type:'checkbox',class:'switch',checked:m.read,dataset:{focusKey:`lesson:${m.path}`},'aria-label':`Mark ${m.title} as read`,onchange:async()=>{
    const wanted=check.checked;check.disabled=true;feedback.hidden=true;
    try{await api('/api/course/read',{path:m.path,read:wanted});m.read=wanted;
      try{await hooks.refreshCourse();}catch(error){feedback.textContent=`Progress saved. The summary could not refresh: ${error.message}`;feedback.hidden=false;}
    }
    catch(error){check.checked=m.read;feedback.textContent=`Could not update progress. ${error.message}`;feedback.hidden=false;}
    finally{check.disabled=false;}
  }});
  return h('li',{class:`lesson-row${m.today?' lesson-today':''}`},h('span',{class:'lesson-number',text:String(i+1).padStart(2,'0')}),
    h('div',{class:'lesson-copy'},h('a',{href:readerHref(m.route),target:'_blank',rel:'noopener noreferrer',text:m.title},icon('arrow-up-right','icon icon-sm')),m.today?h('span',{class:'pill pill-accent',text:'Today’s lesson'}):null,feedback),check);
}
export function renderStudy() {
  const c=S.course,today=c.today;
  const trackName=readQuery().get('track');
  const active=c.tracks.find(t=>t.name===trackName)||c.tracks.find(t=>t.modules.some(m=>m.today))||c.tracks[0];
  return h('div',{class:'page study-page'},h('header',{class:'page-head'},h('div',{},h('p',{class:'eyebrow',text:'BUILD SKILLS. BUILD MOMENTUM.'}),h('h1',{text:'Learning path'}),h('p',{class:'lead',text:`${c.read} of ${c.total} modules read · your progress, at your pace`}))),
    journeyBanner({image:30,eyebrow:today?`TODAY · DAY ${today.number} OF ${today.total}${today.revising?' · REVISION':''}`:'YOUR LEARNING JOURNEY',title:today?.title||'One lesson closer to your next chapter.',body:today?.tomorrow?`Up next: ${today.tomorrow.title}`:'Explore your learning tracks below.',action:today?h('a',{class:'btn btn-primary',href:readerHref(today.route),target:'_blank',rel:'noopener noreferrer',text:'Open today’s lesson'},icon('arrow-up-right','icon icon-sm')):null,progress:progressRing(c.read,c.total,'read')}),
    h('nav',{class:'learning-nav','aria-label':'Learning tracks'},c.tracks.map(track=>h('a',{class:'learning-tab',href:withQuery('study',{track:track.name}),'aria-current':track===active?'page':null},h('strong',{text:track.name}),h('span',{text:`${track.modules.filter(m=>m.read).length} / ${track.modules.length} read` })))),
    h('div',{class:'learning-tracks focused-tracks'},(active?[active]:[]).map((track,i)=>{
      const read=track.modules.filter(m=>m.read).length;
      S.studyOpen ||= {};
      const details=h('details',{class:'track-lessons',open:S.studyOpen[track.name]??(i===0||track.modules.some(m=>m.today))},h('summary',{},h('span',{text:'Explore lessons'}),h('span',{class:'muted',text:`${track.modules.length-read} unread`})),h('ol',{class:'plain-list lesson-list'},track.modules.map(moduleRow)));
      details.addEventListener('toggle',()=>{S.studyOpen[track.name]=details.open;});
      return panel(track.name,{cls:'learning-track',sub:`${read} of ${track.modules.length} modules read`,tools:h('span',{class:'track-symbol'},richIcon(i?'chart':'book'))},h('div',{class:'track-progress'},h('span',{style:{transform:`scaleX(${track.modules.length?read/track.modules.length:0})`}})),details);
    })));
}
