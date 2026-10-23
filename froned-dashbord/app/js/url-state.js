export function readQuery(){return new URLSearchParams(window.location.hash.split('?')[1]||'');}
export function pageNumber(value,fallback=1,max=1_000_000){const n=Number(value);return Number.isInteger(n)&&n>=1&&n<=max?n:fallback;}
export function choice(value,values,fallback){return values.includes(value)?value:fallback;}
export function withQuery(route,values){
  const query=new URLSearchParams();
  for(const [key,value] of Object.entries(values))if(value!==''&&value!==null&&value!==undefined)query.set(key,String(value));
  return `#/${route}${query.size?'?'+query:''}`;
}
// Change URL without rebuilding a focused search field. Browser back/forward
// emits hashchange, and the route renderer reads the URL again from scratch.
export function writeQuery(route,values,{replace=false}={}){
  const current=window.location.hash.replace(/^#\/?/,'').split(/[/?]/)[0];
  if(current!==route)return;
  const href=withQuery(route,values);
  if(window.location.hash!==href)history[replace?'replaceState':'pushState'](null,'',href);
}
