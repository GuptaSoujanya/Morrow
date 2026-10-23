import React,{Component,Suspense,lazy,useLayoutEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {QueryClientProvider} from '@tanstack/react-query';
import {queryClient} from './query-client.js';
import {h} from './dom.js';
import {loadingState,errorState} from './components/panel.js';

const R=React.createElement;
// The adapter isolates existing, tested DOM controls while React owns loading,
// route scheduling and recoverable rendering boundaries. No duplicated React roots.
function DomView({render,arg,revision,onCommit}){
  const host=useRef(null),[error,setError]=useState(null);
  useLayoutEffect(()=>{
    try{host.current.replaceChildren(render(arg));onCommit?.();}
    catch(error){setError(error);}
  },[render,arg,revision,onCommit]);
  if(error)throw error;
  return R('div',{ref:host,className:'route-host'});
}
const imports={
  overview:()=>import('./views/overview.js').then(m=>m.renderOverview),analytics:()=>import('./views/overview.js').then(m=>m.renderAnalytics),
  bots:()=>import('./views/bots.js').then(m=>m.renderBots),records:()=>import('./views/records.js').then(m=>m.renderRecords),
  research:()=>import('./views/research.js').then(m=>m.renderResearch),data:()=>import('./views/data.js').then(m=>m.renderData),
  reports:()=>import('./views/reports.js').then(m=>m.renderReports),study:()=>import('./views/study.js').then(m=>m.renderStudy),
  files:()=>import('./views/files.js').then(m=>m.renderFiles),setup:()=>import('./views/setup.js').then(m=>m.renderSetup),
  naukri:()=>import('./views/naukri.js').then(m=>m.renderNaukri),sites:()=>import('./views/sites.js').then(m=>m.renderSites),
  profile:()=>import('./views/profile.js').then(m=>m.renderProfile),linkedin:()=>import('./views/linkedin.js').then(m=>m.renderLinkedin),
  resume:()=>import('./views/resume.js').then(m=>m.renderResume),todo:()=>import('./views/todo.js').then(m=>m.renderTodo),
  boards:()=>import('./views/automations.js').then(m=>m.renderBoards),pipeline:()=>import('./views/automations.js').then(m=>m.renderPipeline),
  outreach:()=>import('./views/outreach.js').then(m=>m.renderOutreach),'linkedin-profile':()=>import('./views/outreach.js').then(m=>m.renderLinkedinProfile),
};
const ready=new Map();
const makeRoute=name=>lazy(()=>imports[name]().then(render=>{ready.set(name,render);return {default:props=>R(DomView,{...props,render})};}));
const routes=Object.fromEntries(Object.keys(imports).map(name=>[name,makeRoute(name)]));
class RouteBoundary extends Component{
  state={error:null};
  static getDerivedStateFromError(error){return {error};}
  componentDidCatch(error){console.error('Route failed',error);}
  render(){return this.state.error?R(DomView,{render:()=>h('div',{},errorState('This page could not open. Your workspace and saved data are still available.',()=>{
    routes[this.props.name]=makeRoute(this.props.name);this.setState({error:null});this.props.retry();
  }),h('button',{class:'btn',type:'button',text:'Reload workspace',onclick:()=>window.location.reload()}))}):this.props.children;}
}
export function createRouteShell(content){
  const root=createRoot(content);let revision=0;
  return {
    preload:name=>imports[name]().then(render=>{ready.set(name,render);}),
    state:node=>root.render(R(DomView,{render:()=>node,revision:++revision})),
    route:(route,onCommit,retry)=>root.render(R(QueryClientProvider,{client:queryClient},
      R(RouteBoundary,{key:route.name,name:route.name,retry},
        R(Suspense,{fallback:R(DomView,{render:()=>loadingState('Opening your workspace…')})},
          ready.has(route.name)?R(DomView,{key:route.name,render:ready.get(route.name),arg:route.arg,revision:++revision,onCommit}):R(routes[route.name],{key:route.name,arg:route.arg,revision:++revision,onCommit}))))),
  };
}
