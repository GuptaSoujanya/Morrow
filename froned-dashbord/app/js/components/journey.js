import {h,svg} from '../dom.js';
import {avatar} from './identity.js';

export function progressRing(done,total,label='complete') {
  const ratio=total?Math.max(0,Math.min(1,done/total)):0;
  return h('div',{class:'progress-ring',role:'img','aria-label':`${done} of ${total} ${label}`},
    svg('svg',{viewBox:'0 0 100 100','aria-hidden':true},svg('circle',{cx:50,cy:50,r:42,class:'ring-track'}),svg('circle',{cx:50,cy:50,r:42,class:'ring-fill','stroke-dasharray':`${ratio*264} 264`,transform:'rotate(-90 50 50)'})),
    h('div',{},h('strong',{text:`${Math.round(ratio*100)}%`}),h('span',{text:label})));
}
export function journeyBanner({image=11,eyebrow,title,body,action,progress}) {
  return h('section',{class:'journey-banner'},avatar(image,'journey-avatar'),h('div',{class:'journey-copy'},h('p',{class:'eyebrow',text:eyebrow}),h('h2',{text:title}),h('p',{text:body}),action?h('div',{class:'journey-actions'},action):null),progress||null);
}
export function statStrip(items) {
  return h('div',{class:'experience-stats'},items.map(([value,label,href])=>h(href?'a':'div',{class:'experience-stat',href},h('strong',{text:String(value)}),h('span',{text:label}))));
}
