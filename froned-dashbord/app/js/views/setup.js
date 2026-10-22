import { journeyBanner } from '../components/journey.js';
import { richIcon } from '../components/identity.js';
import { h } from '../dom.js';
import { panel } from '../components/panel.js';
import { quickButton } from '../forms.js';
import { fileEditor } from './files.js';

export function renderSetup() {
  return h('div', { class: 'page' }, h('header', { class: 'page-head' }, h('div', {}, h('p', { class: 'eyebrow', text: 'Make it yours' }), h('h1', { text: 'Preferences' }), h('p', { class: 'lead', text: 'Search preferences, account details and the tools behind your workspace.' }))),
    journeyBanner({image:31,eyebrow:'TUNED TO YOU',title:'Make Orbit work your way.',body:'Fine-tune matching, manage account details and choose the tools your crew uses. Changes apply on the next run.'}),
    h('div', { class: 'dash preferences-grid' },
      panel('Configuration', { cls: 'span-8', sub: 'Saved locally in .env · passwords and keys are masked' }, fileEditor('env', true)),
      h('div', { class: 'span-4 stack' },
        panel('Google sign-in', {tools:richIcon('person')}, h('p', { class: 'muted', text: 'Open the bot’s browser to connect your Google account for company-site applications.' }), h('div', { class: 'panel-foot' }, quickButton('google', 'Open sign-in'))),
        panel('Workspace health', {tools:richIcon('bot')}, h('p', { class: 'muted', text: 'Check your installation or update the Python packages used by the bots.' }), h('div', { class: 'panel-foot' }, quickButton('tests', 'Run checks'), quickButton('install', 'Install requirements'))),
        panel('Advanced settings', {tools:richIcon('sliders')}, h('p', { class: 'muted', text: 'Add new settings or edit comments in the original configuration file.' }), h('div', { class: 'panel-foot' }, h('a', { class: 'btn', href: '#/files/env', text: 'Open settings file' }))))));
}
