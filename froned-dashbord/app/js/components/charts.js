/** Hand-built inline SVG chart primitives, driven entirely by design tokens (see charts.css).
 * Charts expose actual observations through pointer, touch, keyboard and text readouts.
 * All labels are real DOM nodes, never interpolated HTML. */

import { h, svg } from "../dom.js";
import { num, share } from "../format.js";


/** Recompute SVG geometry at the container width; keep labels at readable CSS sizes. */
function observeChart(root, resize) {
  if (!window.ResizeObserver) return;
  let previous=0;
  const observer=new ResizeObserver(entries=>{
    if(!root.isConnected){observer.disconnect();return;}
    const width=Math.round(entries[0].contentRect.width);
    if(width>0&&width!==previous){previous=width;const focused=root.contains(document.activeElement)&&document.activeElement.getAttribute('role')==='slider';resize(width);if(focused)root.querySelector('[role=slider]')?.focus({preventScroll:true});}
  });
  observer.observe(root);
}

/** Tiny single-series line, used in the "Sent" KPI card. */
export function sparkline(values, width = 120, height = 32) {
  const max = Math.max(1, ...values);
  const step = values.length > 1 ? width / (values.length - 1) : 0;
  const points = values.map((v, i) => [i * step, height - (v / max) * (height - 4) - 2]);
  const d = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const last = points[points.length - 1] || [0, height];
  return svg(
    "svg",
    { class: "sparkline", viewBox: `0 0 ${width} ${height}`, width, height, "aria-hidden": "true" },
    svg("path", { d }),
    svg("circle", { cx: last[0], cy: last[1], r: 2.2 }),
  );
}

/** Actual daily observations with shared pointer, touch and keyboard inspection. */
let chartId = 0;
export function columnsChart({ rows, series, label, xLabel, detailFor }, width = 720, height = 240) {
  if (!rows.length) return h('p', {class:'panel-empty',text:'No activity recorded in this period.'});
  const id = `activity-${++chartId}`, visible = new Set(series.map(s => s.key));
  let mode = 'trend', index = rows.length - 1, interaction, guide;
  const root = h('div', {class:'activity-explorer'});
  const plot = h('div', {class:'chart-canvas'});
  const readout = h('div', {class:'chart-readout'});
  const detail = h('p',{class:'chart-instruction',hidden:true});
  const modes = h('div', {class:'chart-modes',role:'group','aria-label':'Chart presentation'});
  const legend = h('div', {class:'chart-controls',role:'group','aria-label':'Visible application channels'});
  const left = 36, right = 16, top = 16, bottom = height - 30;
  const inset = () => mode === 'bars' ? Math.min(19,(width-left-right)/rows.length*.325) : 0;
  const x = i => left + (rows.length === 1 ? (width-left-right)/2 : inset()+i*(width-left-right-2*inset())/(rows.length-1));
  const longDay = day => new Date(day+'T12:00:00').toLocaleDateString(undefined,{weekday:'short',day:'numeric',month:'short',year:'numeric'});
  function inspect(next) {
    index = Math.max(0, Math.min(rows.length-1, next));
    const row=rows[index], total=series.filter(s=>visible.has(s.key)).reduce((n,s)=>n+(row[s.key]||0),0);
    readout.replaceChildren(h('div',{class:'chart-day'},h('span',{text:longDay(row.day)}),h('strong',{text:num(total)},h('small',{text:visible.size===series.length?' confirmed submissions':' in visible channels'}))),
      h('div',{class:'chart-values'},series.filter(s=>visible.has(s.key)).map(s=>h('span',{},h('i',{class:`swatch ${s.cls}`}),s.label,h('b',{text:num(row[s.key]||0)})))));
    const note=detailFor?.(row);detail.hidden=!note;detail.textContent=note?`Not sent: ${note}.`:'';
    interaction?.setAttribute('aria-valuenow', index+1);
    interaction?.setAttribute('aria-valuetext', `${longDay(row.day)}: ${series.filter(s=>visible.has(s.key)).map(s=>`${row[s.key]||0} ${s.label}`).join(', ')}`);
    if (guide) { guide.setAttribute('x1', x(index)); guide.setAttribute('x2', x(index)); }
    plot.querySelectorAll('.chart-point').forEach(p=>{
      const max=Number(p.dataset.max); p.setAttribute('cx',x(index));p.setAttribute('cy',bottom-(row[p.dataset.key]||0)/max*(bottom-top));
    });
  }
  function draw() {
    const shown=series.filter(s=>visible.has(s.key));
    const highest=Math.max(1,...rows.map(r=>mode==='bars'?shown.reduce((n,s)=>n+(r[s.key]||0),0):Math.max(...shown.map(s=>r[s.key]||0))));
    const magnitude = 10**Math.floor(Math.log10(highest));
    const max=Math.ceil(highest/magnitude)*magnitude;
    const y=v=>bottom-v/max*(bottom-top);
    const chart=svg('svg',{class:'chart interactive-chart',viewBox:`0 0 ${width} ${height}`,role:'group','aria-label':label});
    for(let n=0;n<=4;n++){
      const value=max*n/4;
      chart.append(svg('line',{class:'chart-grid',x1:left,y1:y(value),x2:width-right,y2:y(value)}));
      if(Number.isInteger(value))chart.append(svg('text',{class:'chart-y-label',x:left-10,y:y(value)+4,'text-anchor':'end'},num(value)));
    }
    rows.forEach((r,i)=>{
      if(i===0||i===rows.length-1||(i%Math.max(1,Math.ceil(rows.length/(width<420?4:6)))===0 && i<rows.length-2))
        chart.append(svg('text',{class:'chart-x-label',x:x(i),y:height-7,'text-anchor':i===0?'start':i===rows.length-1?'end':'middle'},xLabel(r)));
    });
    if(mode==='trend')shown.forEach((s,j)=>{
      const points=rows.map((r,i)=>`${i?'L':'M'}${x(i)},${y(r[s.key]||0)}`).join(' ');
      const gradient=`${id}-${s.key}`;
      chart.append(svg('g',{class:`chart-series chart-motion ${s.cls}`},
        svg('defs',{},svg('linearGradient',{id:gradient,x1:0,y1:0,x2:0,y2:1},svg('stop',{offset:'0%','stop-color':'currentColor','stop-opacity':'.18'}),svg('stop',{offset:'100%','stop-color':'currentColor','stop-opacity':'0'}))),
        svg('path',{d:`${points} L${x(rows.length-1)},${bottom} L${x(0)},${bottom} Z`,fill:`url(#${gradient})`}),
        svg('path',{class:'chart-line',d:points}),svg('circle',{class:'chart-point',r:4,'data-key':s.key,'data-max':max})));
    });
    else rows.forEach((row,i)=>{
      let total=0;
      const barWidth=Math.min(38,(width-left-right)/rows.length*.65);
      const group=svg('g',{class:'chart-bars-motion'});
      shown.forEach(s=>{const v=row[s.key]||0;total+=v;if(v)group.append(svg('rect',{class:`chart-col ${s.cls}`,x:x(i)-barWidth/2,y:y(total),width:barWidth,height:v/max*(bottom-top),rx:3}));});
      chart.append(group);
    });
    guide=svg('line',{class:'chart-crosshair',x1:x(index),x2:x(index),y1:top,y2:bottom}); chart.append(guide);
    interaction=svg('rect',{x:left,y:0,width:width-left,height:bottom,fill:'transparent',tabindex:0,role:'slider',
      'aria-label':'Inspect application date','aria-orientation':'horizontal','aria-valuemin':1,'aria-valuemax':rows.length,
      onkeydown:e=>{const delta={ArrowLeft:-1,ArrowDown:-1,ArrowRight:1,ArrowUp:1}[e.key];if(delta||['Home','End'].includes(e.key)){e.preventDefault();inspect(e.key==='Home'?0:e.key==='End'?rows.length-1:index+delta);}},
      onpointermove:e=>{if(e.pointerType!=='touch'||e.buttons)locate(e);},onpointerdown:e=>locate(e)});
    function locate(e){const r=chart.getBoundingClientRect();inspect(Math.round(((e.clientX-r.left)/r.width*width-left-inset())/(width-left-right-2*inset())*(rows.length-1)));}
    chart.append(interaction);plot.replaceChildren(chart);
    [...modes.children].forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===mode)));
    [...legend.children].forEach(b=>{b.setAttribute('aria-pressed',String(visible.has(b.dataset.key)));b.disabled=visible.size===1&&visible.has(b.dataset.key);});
    inspect(index);
  }
  for(const [key,text] of [['trend','Trend'],['bars','Bars']])modes.append(h('button',{class:'chart-mode',type:'button',dataset:{mode:key},text,onclick:()=>{mode=key;draw();}}));
  series.forEach(s=>legend.append(h('button',{class:'chart-legend',type:'button',dataset:{key:s.key},onclick:()=>{visible.has(s.key)?visible.delete(s.key):visible.add(s.key);draw();}},h('span',{class:`swatch ${s.cls}`}),s.label)));
  root.append(h('div',{class:'chart-toolbar'},legend,modes),readout,plot,detail,h('p',{class:'chart-instruction',text:'Hover or tap to explore · Arrow keys move between dates'}));
  draw();observeChart(root,next=>{if(next!==width){width=next;draw();}});return root;
}

/** Score histogram: 20 buckets of 5 points. Buckets at/above `minScore` read emerald, the
 * bucket the threshold falls inside reads amber ("mixed"), the rest read neutral. */
export function scoreKind(bucket, minScore) {
  if (minScore <= bucket.from) return "over";
  if (minScore >= bucket.to) return "under";
  return "mixed";
}

export function scoresChart(buckets, minScore, overCount, width = 640, height = 220) {
  let selected=Math.min(buckets.length-1,Math.floor(minScore/5));
  const container=h('div',{class:'score-responsive'});
  const draw=()=>{
  const left=32,bottom=height-28,top=22,total=buckets.reduce((n,b)=>n+b.count,0);
  const max=Math.max(1,...buckets.map(b=>b.count)),step=(width-left-8)/buckets.length;
  const readout=h('div',{class:'score-readout'});
  const chart=svg('svg',{class:'chart score-chart',viewBox:`0 0 ${width} ${height}`,role:'group','aria-label':`Score distribution: ${overCount} of ${total} jobs scored ${minScore} or more`});
  [0,.5,1].forEach(r=>{const y=bottom-r*(bottom-top);chart.append(svg('line',{class:'chart-grid',x1:left,y1:y,x2:width-8,y2:y}),svg('text',{class:'chart-y-label',x:left-8,y:y+4,'text-anchor':'end'},num(Math.round(max*r))));});
  const bars=svg('g',{class:'chart-bars-motion'});
  buckets.forEach((b,i)=>bars.append(svg('rect',{class:`hist-bar score-${scoreKind(b,minScore)}`,x:left+i*step+2,y:bottom-b.count/max*(bottom-top),width:Math.max(1,step-4),height:b.count/max*(bottom-top),rx:3})));
  chart.append(bars);
  [0,25,50,75,100].forEach(v=>chart.append(svg('text',{class:'chart-x-label',x:left+v/100*(width-left-8),y:height-6,'text-anchor':v===0?'start':v===100?'end':'middle'},String(v))));
  const threshold=left+minScore/100*(width-left-8);
  chart.append(svg('line',{class:'score-threshold',x1:threshold,x2:threshold,y1:top,y2:bottom}),svg('text',{class:'chart-x-label',x:Math.min(width-8,threshold+6),y:12,'text-anchor':threshold>width-100?'end':'start'},`Target ${minScore}+`));
  const marker=svg('rect',{class:'score-selection',x:left+selected*step,y:top,width:step,height:bottom-top,rx:4});chart.append(marker);
  function inspect(i){selected=Math.max(0,Math.min(buckets.length-1,i));const b=buckets[selected];
    readout.replaceChildren(h('span',{},h('strong',{text:`${b.from}–${b.to}`}),h('span',{text:' score range'})),h('span',{},h('b',{text:num(b.count)}),` jobs · ${share(b.count,total)}`));
    hit.setAttribute('aria-valuenow',selected+1);hit.setAttribute('aria-valuetext',`Scores ${b.from} to ${b.to}: ${b.count} jobs, ${share(b.count,total)}`);marker.setAttribute('x',left+selected*step);
  }
  function locate(e){const r=chart.getBoundingClientRect();inspect(Math.floor(((e.clientX-r.left)/r.width*width-left)/step));}
  const hit=svg('rect',{x:left,y:top,width:width-left,height:bottom-top,fill:'transparent',role:'slider',tabindex:0,'aria-label':'Inspect score range','aria-valuemin':1,'aria-valuemax':buckets.length,'aria-orientation':'horizontal',onpointermove:e=>{if(e.pointerType!=='touch'||e.buttons)locate(e);},onpointerdown:locate,onkeydown:e=>{const n={ArrowRight:1,ArrowUp:1,ArrowLeft:-1,ArrowDown:-1}[e.key];if(n||['Home','End'].includes(e.key)){e.preventDefault();inspect(e.key==='Home'?0:e.key==='End'?buckets.length-1:selected+n);}}});
  chart.append(hit);inspect(selected);
  return h('div',{class:'score-explorer'},readout,chart,h('p',{class:'chart-instruction',text:'Hover or tap a range · Arrow keys move between ranges'}));
  };
  container.replaceChildren(draw());observeChart(container,next=>{if(next!==width){width=next;container.replaceChildren(draw());}});return container;
}

export function donutChart(items,total) {
  const circle=2*Math.PI*48;let offset=0;
  const chart=svg('svg',{viewBox:'0 0 120 120','aria-hidden':true},svg('circle',{cx:60,cy:60,r:48,class:'donut-track'}));
  items.forEach(({key,value})=>{const length=value/total*circle;chart.append(svg('circle',{cx:60,cy:60,r:48,class:`donut-segment kind-${key}`,'stroke-dasharray':`${Math.max(0,length-2)} ${circle}`,'stroke-dashoffset':-offset,transform:'rotate(-90 60 60)'}));offset+=length;});
  return h('div',{class:'outcome-donut',role:'img','aria-label':items.map(i=>`${i.label}: ${i.value}`).join(', ')},chart,h('div',{},h('strong',{text:num(total)}),h('span',{text:'attempts'})));
}

export function meter(ratio, cls = "") {
  const pct = Math.max(0, Math.min(1, ratio || 0)) * 100;
  return h("div", { class: `meter ${cls}` }, h("span", { style: { width: `${pct}%` } }));
}
