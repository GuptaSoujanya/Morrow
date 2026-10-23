import {h} from '../dom.js';
import {panel} from '../components/panel.js';
import {quickButton} from '../forms.js';
import {fileEditor} from './files.js';
import {avatar} from '../components/identity.js';
import {readQuery,withQuery} from '../url-state.js';

export function renderSetup(){
  const maintenance=readQuery().get('tab')==='maintenance';
  return h('div',{class:'page preferences-page'},h('header',{class:'page-head'},h('div',{},h('p',{class:'eyebrow',text:'MAKE ROOM FOR YOUR WAY'}),h('h1',{text:'Preferences'}),h('p',{class:'lead',text:'Tune your search, connect your accounts and keep your crew ready.'}))),
    h('nav',{class:'workspace-tabs','aria-label':'Preferences sections'},h('a',{href:'#/setup','aria-current':!maintenance?'page':null,text:'Your preferences'}),h('a',{href:withQuery('setup',{tab:'maintenance'}),'aria-current':maintenance?'page':null,text:'Connections & maintenance'})),
    maintenance?h('div',{class:'maintenance-list'},
      panel('Google sign-in',{tools:avatar(20,'utility-art')},h('p',{class:'muted',text:'Connect Google in the bot’s browser for company-site applications.'}),h('div',{class:'panel-foot'},quickButton('google','Open sign-in'))),
      panel('Workspace health',{tools:avatar(46,'utility-art')},h('p',{class:'muted',text:'Check your installation or update the packages your bots use.'}),h('div',{class:'panel-foot'},quickButton('tests','Run checks'),quickButton('install','Install requirements'))),
      panel('Advanced configuration',{tools:avatar(31,'utility-art')},h('p',{class:'muted',text:'Add settings and comments directly in your original local configuration.'}),h('div',{class:'panel-foot'},h('a',{class:'btn',href:'#/files/env',text:'Open settings file'})))):
    panel('Fine-tune your workspace',{cls:'preferences-panel',sub:'Saved locally · credentials stay masked · changes apply to your next run',tools:avatar(31,'utility-art')},fileEditor('env',true)));
}
