import { h } from '../dom.js';
import { api } from '../api.js';
import { S, hooks } from '../state.js';
import { panel, empty } from '../components/panel.js';
import { toast } from '../components/toast.js';
import { quickButton } from '../forms.js';
import { journeyBanner, statStrip } from '../components/journey.js';
import { richIcon } from '../components/identity.js';

function task(kind, item, index = 0) {
  const key = `${kind}:${item.line}`;
  const label = kind === 'answer' ? item.questions.join(' / ') : item.key.replaceAll('_', ' ');
  const control = h(kind === 'answer' ? 'textarea' : 'input', {
    class: 'input textarea-short', 'aria-label': label, value: S.drafts[key] || '',
    placeholder: kind === 'answer' ? 'Write your answer…' : 'Add this detail…',
    oninput: e => { S.drafts[key] = e.target.value; if(control.value.trim()){feedback.hidden=true;control.setAttribute('aria-invalid','false');} },
    onkeydown: e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); save(); } },
  });
  const feedback = h('p',{class:'field-error',role:'status',id:`task-${kind}-${item.line}`,hidden:true});
  control.setAttribute('aria-describedby',feedback.id);
  const button = h('button', { class: 'btn btn-primary', type: 'button', text: 'Save', onclick: save });
  async function save() {
    if (!control.value.trim()) { feedback.textContent='Add this detail before saving.';feedback.hidden=false;control.setAttribute('aria-invalid','true');control.focus();return; }
    if(button.disabled)return;button.disabled = true;button.textContent='Saving…';feedback.hidden=true;
    try {
      await api(`/api/${kind}`, { line: item.line, [kind === 'answer' ? 'answer' : 'value']: control.value });
      delete S.drafts[key];
      await hooks.refreshStatus();
      hooks.requestRender();
      toast('Saved. Your next run will use it.', 'ok');
    } catch (error) { feedback.textContent=`Could not save. ${error.message} Your draft is still here.`;feedback.hidden=false; }
    finally { button.disabled = false;button.textContent='Save'; }
  }
  return h('li', { class: 'todo' }, h('details',{class:'inbox-task',open:index===0||!!S.drafts[key]},h('summary',{class:'task-heading'},richIcon(kind==='answer'?'check':'person'),h('span', { class: 'todo-label', text: label }),h('span',{class:'task-expand','aria-hidden':'true'})),h('div',{class:'task-editor'},h('div', { class: 'todo-input' }, control, button),feedback)));
}

export function renderTodo() {
  return h('div', { class: 'page' },
    h('header', { class: 'page-head' }, h('div', {}, h('p', { class: 'eyebrow', text: 'Keep things moving' }), h('h1', { text: 'Action inbox' }), h('p', { class: 'lead', text: 'A few details from you can unlock the next application.' }))),
    journeyBanner({image:27,eyebrow:'A LITTLE INPUT. MORE MOMENTUM.',title:S.status.questions.length+S.status.facts.length?'Clear the way for your next move.':'Your details are up to date.',body:'Save reusable answers once. Your crew will use them on the next run.'}),
    statStrip([[S.status.questions.length,'Employer questions',null],[S.status.facts.length,'Profile details',null],[S.status.sites.length,'Company follow-ups','#/sites']]),
    h('div', { class: 'dash inbox-grid' },
      panel('Questions from employers', { cls: 'span-7', sub: 'Cmd / Ctrl + Enter to save · answers stay here until saved' },
        S.status.questions.length ? h('ul', { class: 'plain-list' }, S.status.questions.map((item,i) => task('answer', item,i))) : empty('You’re all caught up. No unanswered questions.'),
        h('a', { class: 'btn btn-sm', href: '#/files/answers', text: 'Manage all answers' })),
      panel('Complete your profile', { cls: 'span-5', sub: 'These facts are still blank in your profile.' },
        S.status.facts.length ? h('ul', { class: 'plain-list' }, S.status.facts.map((item,i) => task('fact', item,i))) : empty('Your profile has no missing facts.'),
        h('a', { class: 'btn btn-sm', href: '#/files/profile', text: 'Edit profile' })),
      panel('Application follow-ups', { cls: 'span-12' }, h('p', { text: `${S.status.sites.length} company-site applications are waiting for a final step.` }),
        h('div', { class: 'panel-foot' }, h('a', { class: 'btn', href: '#/sites', text: 'Review company sites' }), quickButton('assist', 'Preview suggested answers', { dry_run: true })))));
}
