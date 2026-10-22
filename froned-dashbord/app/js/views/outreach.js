import {h} from '../dom.js';
import {S} from '../state.js';
import {panel} from '../components/panel.js';
import {field,textInput,toggle,previewBox,runButton,liveRunConfirm} from '../forms.js';

export function renderLinkedinProfile(){
  return h('div',{class:'page'},h('header',{class:'page-head'},h('div',{},h('h1',{text:'LinkedIn profile'}),h('p',{class:'lead',text:'Keep your profile aligned with your experience and saved facts.'}))),
    h('div',{class:'dash'},panel('Review & update',{cls:'span-7'},
      toggle('linkedin_profile','dry_run','Preview changes','Review proposed edits without saving profile changes.'),
      previewBox('linkedin_profile'),runButton('linkedin_profile','Review profile',{confirm:()=>S.forms.linkedin_profile.dry_run?null:liveRunConfirm('This reviews and saves changes to your LinkedIn profile using your saved facts.')})),
    panel('Before you begin',{cls:'span-5'},h('p',{text:'The profile assistant uses your saved professional facts and an existing LinkedIn browser session.'}),h('p',{class:'muted',text:'It updates profile sections; posting is controlled separately in LinkedIn writer.'}),h('div',{class:'panel-foot'},h('a',{class:'btn',href:'#/files/profile',text:'Review saved facts'}),h('a',{class:'text-link',href:'#/linkedin',text:'Open LinkedIn writer'})))));
}

export function renderOutreach(){
  return h('div',{class:'page'},h('header',{class:'page-head'},h('div',{},h('h1',{text:'Recruiter email drafts'}),h('p',{class:'lead',text:'Prepare a relevant introduction, then review the draft before sending it yourself.'})),h('a',{class:'btn',href:'#/research',text:'Open saved drafts'})),
    h('div',{class:'dash'},panel('Prepare drafts',{cls:'span-7',sub:'Leave the recipient blank to use recruiter contacts discovered in your job data.'},
      h('div',{class:'form-grid'},
        field('Recipient email',textInput('cold_email','to',{type:'email',placeholder:'recruiter@company.com'})),
        field('Company',textInput('cold_email','company',{placeholder:'Company name'})),
        field('Role title',textInput('cold_email','title',{placeholder:'Role you are interested in'})),
        field('Job URL',textInput('cold_email','url',{type:'url',placeholder:'https://…'})),
        field('Look back (days)',textInput('cold_email','days',{type:'number',min:1,max:365,placeholder:'7'})),
        field('Maximum drafts',textInput('cold_email','limit',{type:'number',min:1,max:100,placeholder:'Use configured limit'})),
        field('Pages to scan',textInput('cold_email','pages',{type:'number',min:1,max:100,placeholder:'30'}))),
      toggle('cold_email','scan_naukri','Scan Naukri descriptions','Look for recruiter email addresses in recent job descriptions.'),
      toggle('cold_email','dry_run','Preview only','Show draft candidates without saving email drafts.'),
      previewBox('cold_email'),runButton('cold_email','Prepare drafts',{confirm:()=>S.forms.cold_email.dry_run?null:{title:'Save recruiter drafts?',body:'This creates email draft files and may sync them to Gmail Drafts if configured. It does not send email.',ok:'Save drafts'}})),
      panel('Drafts stay in your hands',{cls:'span-5'},h('p',{text:'Saved drafts appear in the Research library under Email drafts. Review the recipient, role and message before sending.'}),h('p',{class:'muted',text:'Gmail draft sync uses your existing backend configuration. This assistant never sends the emails.'}),h('div',{class:'panel-foot'},h('a',{class:'btn',href:'#/research',text:'Browse your library'})))));
}
