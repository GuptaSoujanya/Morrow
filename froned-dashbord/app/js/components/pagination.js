import {h} from '../dom.js';
import {selectControl} from './controls.js';
import {num} from '../format.js';

export function pagination({page,pages,size,total,onPage,onSize,sizes=[12,24,48],label='Results'}){
  let root;
  async function change(value,isSize=false){
    const panel=root.closest('.panel');
    await (isSize?onSize(value):onPage(value));
    if(!panel?.isConnected)return;
    panel.querySelector(isSize?'.pagination [role=combobox]':'.pagination [aria-current=page]')?.focus({preventScroll:true});
    panel.querySelector('table,.data-file-list,.research-results')?.scrollIntoView({block:'start',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
  }
  const numbers=[...new Set([1,...[page-1,page,page+1].filter(n=>n>1&&n<pages),pages])].sort((a,b)=>a-b);
  const links=[];
  numbers.forEach((number,i)=>{
    if(i&&number-numbers[i-1]>1)links.push(h('span',{class:'pagination-gap','aria-hidden':'true',text:'…'}));
    links.push(h('button',{type:'button',class:'page-number','aria-label':`Page ${number}`,'aria-current':number===page?'page':null,text:number,dataset:{edge:String(number===1||number===pages)},onclick:()=>{if(number!==page)change(number);}}));
  });
  root=h('nav',{class:'pagination','aria-label':`${label} pagination`},
    h('div',{class:'pagination-meta'},h('span',{role:'status',text:total?`${num((page-1)*size+1)}–${num(Math.min(page*size,total))} of ${num(total)}`:'0 results'}),
      onSize?selectControl({label:'Rows per page',value:String(size),options:sizes.map(n=>({value:String(n),label:`${n} per page`})),onChange:value=>change(Number(value),true)}):null),
    h('div',{class:'pagination-pages'},h('button',{type:'button',class:'btn btn-sm',text:'Previous',disabled:page<=1,onclick:()=>change(page-1)}),...links,h('button',{type:'button',class:'btn btn-sm',text:'Next',disabled:page>=pages,onclick:()=>change(page+1)})));
  return root;
}
