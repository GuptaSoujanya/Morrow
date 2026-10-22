import {h,svg} from '../dom.js';
let serial=0;
export function avatar(index=15,className=''){
  const cell=index%16;
  const position=n=>index>=16?((n+.5)*112.5-50)/3.5:n*100/3;
  return h('span',{class:`crew-avatar ${index>=16?'orbit-world':''} ${className}`,'aria-hidden':'true',dataset:{avatar:index},style:{backgroundPosition:`${position(cell%4)}% ${position(Math.floor(cell/4))}%`}});
}
export function workspaceAvatar(){
  try {const raw=localStorage.getItem('orbit-avatar');const value=Number(raw);return raw!==null&&Number.isInteger(value)&&value>=0&&value<24?value:15;}catch{return 15;}
}
export function orbitMark(className='orbit-mark'){
  const id='orbit-'+(++serial);
  return svg('svg',{class:className,viewBox:'0 0 48 48','aria-hidden':'true'},
    svg('defs',{},svg('linearGradient',{id,x1:'0',y1:'0',x2:'1',y2:'1'},svg('stop',{offset:'0%','stop-color':'#dfd4ff'}),svg('stop',{offset:'100%','stop-color':'#8c72dc'}))),
    svg('circle',{cx:24,cy:24,r:12,fill:`url(#${id})`}),
    svg('ellipse',{cx:24,cy:24,rx:23,ry:9,transform:'rotate(-35 24 24)',fill:'none',stroke:'#e2d9ff','stroke-width':2.5}),
    svg('circle',{cx:8,cy:35,r:3,fill:'#e2d9ff'}));
}
const glyphs={
  grid:['M3 7a4 4 0 014-4h3v8H3zM14 3h3a4 4 0 014 4v4h-7zM3 15h7v6H7a4 4 0 01-4-4z','M14 15h7v2a4 4 0 01-4 4h-3z'],
  file:['M5 6a3 3 0 013-3h7l4 4v11a3 3 0 01-3 3H8a3 3 0 01-3-3z','M9 11h6v2H9zM9 15h6v2H9z'],
  bot:['M4 8a4 4 0 014-4h8a4 4 0 014 4v9a4 4 0 01-4 4H8a4 4 0 01-4-4z','M8 10h3v4H8zM14 10h3v4h-3zM9 17h6v1H9z'],
  refresh:['M4 3h7v7H4zM13 14h7v7h-7z','M13 5h5v6h-2V7h-3zM6 13h2v4h3v2H6z'],
  chart:['M3 13h5v8H3zM10 3h5v18h-5zM17 8h5v13h-5z','M3 13h5v3H3zM10 3h5v4h-5zM17 8h5v3h-5z'],
  check:['M4 4a3 3 0 013-3h10a3 3 0 013 3v16H4z','M7 10l3 3 7-7 1.5 1.5L10 16 5.5 11.5z'],
  book:['M3 4c4-2 7-1 9 1 3-2 6-3 9-1v16c-4-2-7-1-9 1-3-2-6-3-9-1z','M11 5h2v15h-2z'],
  folder:['M3 7V5a2 2 0 012-2h5l3 3h6a2 2 0 012 2v2H3z','M3 9h19l-2 12H2z'],
  sliders:['M4 3h4v18H4zM10 3h4v18h-4zM16 3h4v18h-4z','M2 7h8v4H2zM8 14h8v4H8zM14 5h8v4h-8z'],
  person:['M12 2a5 5 0 110 10 5 5 0 010-10','M3 22v-3a7 7 0 017-6h4a7 7 0 017 6v3z'],
};
export function richIcon(name){
  const paths=glyphs[name] || glyphs.grid;
  return svg('svg',{class:'rich-icon',viewBox:'0 0 24 24','aria-hidden':'true'},svg('path',{d:paths[0],fill:'currentColor',opacity:.38}),svg('path',{d:paths[1],fill:'currentColor'}));
}
