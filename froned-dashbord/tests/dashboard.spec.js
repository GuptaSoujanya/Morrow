import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import { mkdir } from 'node:fs/promises';

async function choose(page,label,value){
  await page.getByRole('combobox',{name:label,exact:true}).click();
  await page.locator('[role=listbox]:popover-open').locator(`[role=option][data-value="${value}"]`).click();
}

const pages = ['overview', 'bots', 'analytics', 'pipeline', 'naukri', 'boards', 'sites', 'profile', 'linkedin', 'resume', 'reports', 'study', 'todo', 'setup', 'files', 'records', 'research', 'outreach', 'linkedin-profile', 'data'];
const sampleFiles = {
  env: 'NAUKRI_EMAIL=demo@example.com\nNAUKRI_PASSWORD=sample-secret\nMIN_SCORE=45\nKEYWORDS=AI Engineer\n',
  profile: 'first_name: Demo\nlocation: Bengaluru\n', answers: 'Q: Notice period?\nA: 30 days\n', company_sites: '# Company follow-ups\n',
};

test.beforeEach(async ({ page }) => {
  // No browser test may start a real bot, send a message, open an app, or edit personal files.
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/file' && route.request().method() === 'GET') {
      const name = url.searchParams.get('name');
      return route.fulfill({ json: { name, path: name === 'env' ? '.env' : `data/inputs/${name}`, exists: true, text: sampleFiles[name], revision: 'fixture-v1' } });
    }
    if (route.request().method() === 'POST' && url.pathname !== '/api/preview') return route.fulfill({ status: 409, json: { error: 'Test safety guard: action was not executed.' } });
    return route.continue();
  });
});

for (const width of [375, 768, 1280]) {
  test(`all screens render and fit at ${width}px`, async ({ page }) => {
    test.setTimeout(120000);
    await page.setViewportSize({ width, height: 900 });
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await mkdir(`artifacts/${width}`, { recursive: true });
    for (const name of pages) {
      await page.goto(`/#/${name}`);
      await expect(page.locator('main h1')).toBeVisible();
      if (name === 'overview') await expect(page.getByText('Application activity', { exact: true })).toBeVisible();
      if (name === 'files') await expect(page.getByRole('textbox', { name: 'Your profile', exact: true })).toBeVisible();
      if (name === 'setup') await expect(page.getByRole('searchbox')).toBeVisible();
      if (name === 'data') await expect(page.locator('.data-source')).toHaveCount(7);
      if (name === 'reports') await expect(page.getByText('Reading the report…')).toHaveCount(0);
      if (['naukri', 'boards', 'profile', 'linkedin', 'resume', 'sites', 'pipeline', 'outreach', 'linkedin-profile'].includes(name)) await expect(page.locator('.preview')).not.toContainText('Checking…');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), name).toBe(true);
      await page.locator('main').evaluate(async el => { await Promise.all(el.getAnimations({subtree:true}).filter(a => a.effect?.getTiming().iterations !== Infinity).map(a => a.finished.catch(() => {}))); });
      await page.screenshot({ animations: 'disabled', path: `artifacts/${width}/${name}.png`, fullPage: true });
      if (width === 1280) {
        // Reports intentionally use an opaque sandbox; audit the dashboard shell separately.
        const result = await new AxeBuilder({ page }).exclude('iframe').withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze();
        expect(result.violations.map(v => ({ id: v.id, targets: v.nodes.map(n => n.target) })), name).toEqual([]);
      }
    }
    expect(errors).toEqual([]);
  });
}

test('period filters update data, chart detail and CSV export', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Application activity', { exact: true })).toBeVisible();
  const changed = page.waitForResponse(r => r.url().endsWith('/api/overview?days=7'));
  await page.getByRole('button', { name: '7 days', exact: true }).click();
  await changed;
  await expect(page.getByRole('button', { name: '7 days', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', { name: '7 days', exact: true })).toBeFocused();
  await page.getByText('View daily breakdown', { exact: true }).click();
  await expect(page.locator('.chart-table tbody tr')).toHaveCount(7);
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export data' }).click();
  expect((await download).suggestedFilename()).toMatch(/^job-hunt-.*\.csv$/);
});

test('run preview follows inputs; cancel never executes; confirmed run is sent once', async ({ page }) => {
  let runs = [];
  await page.route('**/api/run', async route => {
    if (route.request().method() === 'POST') { runs.push(route.request().postDataJSON()); return route.fulfill({ json: { label: 'Test practice run', ok: true } }); }
    return route.fallback();
  });
  await page.goto('/#/naukri');
  await page.getByLabel('Keywords', { exact: true }).fill('Platform Engineer');
  await page.getByLabel('Limit', { exact: true }).fill('5');
  await expect(page.locator('.preview')).toContainText('Platform Engineer');
  await expect(page.locator('.preview')).toContainText('--dry-run');
  await page.getByRole('button', { name: 'Run', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Run this?' })).toBeVisible();
  await page.screenshot({ animations: 'disabled', path: 'artifacts/run-confirmation.png' });
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  expect(runs).toEqual([]);
  await page.getByRole('button', { name: 'Run', exact: true }).click();
  await page.getByRole('button', { name: 'Run it', exact: true }).click();
  await expect.poll(() => runs.length).toBe(1);
  expect(runs[0]).toMatchObject({ action: 'naukri', options: { keywords: 'Platform Engineer', limit: '5', dry_run: true } });
  await expect(page.locator('.console')).toHaveAttribute('data-size', 'normal');
});

test('file edits survive navigation; save uses revision; conflicts keep draft', async ({ page }) => {
  let saved;
  await page.route('**/api/file', async route => {
    if (route.request().method() === 'POST') { saved = route.request().postDataJSON(); return route.fulfill({ status: 409, json: { error: 'This file changed since you opened it.' } }); }
    return route.fallback();
  });
  await page.goto('/#/files/profile');
  await page.getByRole('textbox', { name: 'Your profile', exact: true }).fill('first_name: Updated');
  await page.locator('.file-tabs a[href="#/files/answers"]').click();
  await page.locator('.file-tabs a[href="#/files/profile"]').click();
  await expect(page.getByRole('textbox', { name: 'Your profile', exact: true })).toHaveValue('first_name: Updated');
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByRole('alert').filter({hasText:'This file changed since you opened it.'})).toBeVisible();
  expect(saved).toMatchObject({ name: 'profile', text: 'first_name: Updated', revision: 'fixture-v1' });
  await expect(page.getByRole('textbox', { name: 'Your profile', exact: true })).toHaveValue('first_name: Updated');
});

test('settings filter and secret reveal are operable', async ({ page }) => {
  await page.goto('/#/setup');
  await expect(page.getByRole('textbox',{name:'Search keywords (KEYWORDS)',exact:true})).toHaveAttribute('type', 'text');
  await page.getByRole('searchbox').fill('password');
  await expect(page.locator('.setting-row:visible')).toHaveCount(1);
  await expect(page.getByLabel('Naukri password (NAUKRI_PASSWORD)', {exact:true})).toHaveAttribute('type', 'password');
  await page.getByRole('button', { name: 'Show NAUKRI_PASSWORD' }).click();
  await expect(page.getByLabel('Naukri password (NAUKRI_PASSWORD)', {exact:true})).toHaveAttribute('type', 'text');
  await page.getByRole('button', { name: 'Hide NAUKRI_PASSWORD' }).click();
  await expect(page.getByLabel('Naukri password (NAUKRI_PASSWORD)', {exact:true})).toHaveAttribute('type', 'password');
});

test('mobile More sheet exposes every route and closes on navigation', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto('/');
  await page.getByRole('button', { name: 'More sections' }).click();
  await page.screenshot({ animations: 'disabled', path: 'artifacts/mobile-navigation.png' });
  await page.getByRole('dialog', { name: 'All sections' }).getByRole('link', { name: 'Job boards', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Job boards');
  await expect(page.getByRole('dialog', { name: 'All sections' })).not.toBeVisible();
});

test('initial outage shows retry and recovers without reloading', async ({ page }) => {
  let failing = true;
  await page.route('**/api/status', route => failing ? route.abort() : route.fallback());
  await page.goto('/');
  await expect(page.getByText('Your workspace is unavailable.', { exact: false })).toBeVisible();
  await page.screenshot({ animations: 'disabled', path: 'artifacts/offline-state.png' });
  failing = false;
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByText('Application activity', { exact: true })).toBeVisible();
});

test('invalid limits block running and live actions require clear confirmation', async ({ page }) => {
  await page.goto('/#/boards');
  await page.getByLabel('Application limit per board', { exact: true }).fill('-1');
  await expect(page.locator('.preview')).toContainText('between 1 and 500');
  await expect(page.getByRole('button', { name: 'Start run' })).toBeDisabled();
  await page.getByLabel('Application limit per board', { exact: true }).fill('5');
  await page.getByLabel('Practice run', { exact: false }).uncheck();
  await expect(page.locator('.preview')).not.toContainText('--dry-run');
  await page.getByRole('button', { name: 'Start run' }).click();
  await expect(page.getByRole('dialog', { name: 'Run for real?' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).not.toBeVisible();
});

test('company-site search filters records and selected record updates the preview', async ({ page }) => {
  await page.goto('/#/sites');
  await page.getByRole('searchbox', { name: 'Find an application' }).fill('no-such-company-qa-xyz');
  await expect(page.getByText('No applications match your search.')).toBeVisible();
  await page.getByRole('searchbox', { name: 'Find an application' }).fill('');
  await page.getByRole('button', { name: 'Fill in this form' }).first().click();
  await expect(page.getByLabel('Job URL', { exact: true })).not.toHaveValue('');
  await expect(page.locator('.preview')).toContainText('--url');
});

test('empty history is honest and reduced-motion disables transitions', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.route('**/api/overview?*', async route => {
    const response = await route.fetch();
    const data = await response.json();
    await route.fulfill({ json: { ...data, first: null, sent: { ...data.sent, total: 0 }, daily: [] } });
  });
  await page.goto('/');
  await expect(page.getByText('Nothing to chart yet')).toBeVisible();
  await expect(page.locator('.kpi')).toHaveCount(0);
  await page.screenshot({ animations: 'disabled', path: 'artifacts/empty-state.png' });
  expect(await page.locator('.btn').first().evaluate(el => getComputedStyle(el).transitionDuration)).toBe('0s');
});

test('bot inventory is visible, searchable and opens the selected board', async ({ page }) => {
  await page.goto('/#/bots');
  await expect(page.locator('.bot-card')).toHaveCount(18);
  await expect(page.locator('.bot-status').first()).toContainText('Idle');
  await page.getByRole('searchbox', {name:'Find a bot'}).fill('hirist');
  await expect(page.locator('.bot-card')).toHaveCount(2);
  await page.getByRole('button', {name:'Configure Hirist',exact:true}).click();
  await expect(page).toHaveURL(/#\/boards\/hirist$/);
  await expect(page.getByRole('combobox',{name:'Job board',exact:true})).toHaveAttribute('data-value','hirist');
  await expect(page.locator('.preview')).toContainText('--site hirist');
  await page.getByRole('link', {name:'← Bot Crew'}).click();
  await page.getByRole('searchbox', {name:'Find a bot'}).fill('');
  await page.getByRole('button', {name:'Career & research',exact:true}).click();
  await expect(page.locator('.bot-card')).toHaveCount(6);
  await page.getByRole('button', {name:'Configure Learning assistant',exact:true}).click();
  await expect(page.getByRole('combobox',{name:'Stages to run',exact:true})).toHaveAttribute('data-value','learn');
  await expect(page.locator('.preview')).toContainText('--only learn');
});

test('individual bot practice run previews and submits exactly that board', async ({ page }) => {
  const runs=[];
  await page.route('**/api/run', route => {
    if(route.request().method()==='POST') { runs.push(route.request().postDataJSON()); return route.fulfill({json:{label:'Hirist · practice',ok:true}}); }
    return route.fallback();
  });
  await page.goto('/#/bots');
  await page.getByRole('button', {name:'Practice run — Hirist',exact:true}).click();
  await expect(page.getByRole('dialog', {name:'Preview Hirist?'})).toBeVisible();
  await expect(page.locator('.confirm-code')).toContainText('--site hirist --dry-run');
  await page.getByRole('button',{name:'Cancel',exact:true}).click();
  expect(runs).toHaveLength(0);
  await page.getByRole('button', {name:'Practice run — Hirist',exact:true}).click();
  await page.getByRole('button',{name:'Run it',exact:true}).click();
  await expect.poll(()=>runs.length).toBe(1);
  expect(runs[0]).toEqual({action:'boards',options:{board:'hirist',dry_run:true}});
});

test('active bot disables competing runs and exposes confirmed stop', async ({ page }) => {
  const active={running:true,action:'boards',label:'Hirist · practice',shown:'python -m sites_bot.platforms --site hirist --dry-run',seconds:24,stopping:false,last:null,next:0,lines:[]};
  await page.route('**/api/status',async route=>{const r=await route.fetch(); await route.fulfill({json:{...await r.json(),run:active}});});
  await page.route('**/api/bots',async route=>{const r=await route.fetch();const d=await r.json();await route.fulfill({json:{...d,run:active,bots:d.bots.map(b=>({...b,running:b.id==='hirist'}))}});});
  await page.route('**/api/run?*',route=>route.fulfill({json:active}));
  let stops=0;
  await page.route('**/api/stop',route=>{stops++;return route.fulfill({json:{ok:true,message:'Stopping fixture'}});});
  await page.goto('/#/bots');
  await expect(page.locator('[data-bot="hirist"] .bot-status')).toHaveText('In current run');
  await expect(page.getByRole('button',{name:'Practice run — Naukri',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'View live run',exact:true}).click();
  await expect(page.locator('.console')).toHaveAttribute('data-size','normal');
  await page.getByRole('button',{name:'Stop',exact:true}).click();
  await expect(page.getByRole('dialog',{name:'Stop the run?'})).toBeVisible();
  await page.getByRole('dialog').getByRole('button',{name:'Stop',exact:true}).click();
  await expect.poll(()=>stops).toBe(1);
});

test('bot status failure is explicit and can be retried', async ({ page }) => {
  let failed=true;
  await page.route('**/api/bots',route=>failed ? route.fulfill({status:503,json:{error:'Status temporarily unavailable'}}) : route.fallback());
  await page.goto('/#/bots');
  await expect(page.locator('.inline-notice')).toContainText('Bot status is unavailable');
  await expect(page.locator('.bot-status').first()).toHaveText('Status unavailable');
  failed=false;
  await page.getByRole('button',{name:'Try again',exact:true}).click();
  await expect(page.locator('.inline-notice')).toHaveCount(0);
  await expect(page.locator('.bot-status').first()).toHaveText('Idle');
});

test('schedule disable is explicit and uses the registered action', async ({ page }) => {
  const runs=[];
  await page.route('**/api/run',route=>{
    if(route.request().method()==='POST'){runs.push(route.request().postDataJSON());return route.fulfill({json:{ok:true,label:'Profile schedule · disable'}});}
    return route.fallback();
  });
  await page.goto('/#/profile');
  await page.getByRole('button',{name:'Turn off the schedule',exact:true}).click();
  await expect(page.getByRole('dialog',{name:'Turn off the schedule?'})).toBeVisible();
  await expect(page.locator('.confirm-code')).toContainText('schedule.py profile disable');
  await page.getByRole('button',{name:'Turn off',exact:true}).click();
  await expect.poll(()=>runs.length).toBe(1);
  expect(runs[0].action).toBe('profile_disable');
});

test('route and dialog motion settles and Escape restores the triggering control', async ({ page }) => {
  await page.goto('/');
  await page.locator('.nav-group a[href="#/bots"]').click();
  await expect(page.getByRole('heading',{name:'Meet your Bot Crew',exact:true})).toBeVisible();
  await page.locator('main').evaluate(async el=>{await Promise.all(el.getAnimations({subtree:true}).filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{})));});
  const trigger=page.getByRole('button',{name:'Practice run — Hirist',exact:true});
  await trigger.click();
  const dialog=page.getByRole('dialog',{name:'Preview Hirist?'});
  await expect(dialog).toBeVisible();
  expect(await dialog.evaluate(el=>getComputedStyle(el).animationName)).toBe('dialog-in');
  await dialog.evaluate(async el=>{await Promise.all(el.getAnimations().map(a=>a.finished));});
  expect(await dialog.evaluate(el=>getComputedStyle(el).opacity)).toBe('1');
  await page.screenshot({animations:'disabled',path:'artifacts/bot-dialog-settled.png'});
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
});

test('records explorer filters real data, preserves search focus and drills down from metrics',async({page})=>{
  await page.goto('/#/overview');
  await page.locator('a.kpi[href="#/records/jobs/matched"]').click();
  await expect(page.getByRole('combobox',{name:'Record type',exact:true})).toHaveAttribute('data-value','jobs');
  await expect(page.getByRole('combobox',{name:'Outcome',exact:true})).toHaveAttribute('data-value','matched');
  await expect(page.locator('.records-count')).not.toContainText('Loading');
  const search=page.getByRole('searchbox',{name:'Search records'});
  await search.fill('no-such-job-fixture-xyz');
  await expect(page.getByText('No records match these filters.',{exact:true})).toBeVisible();
  await expect(search).toBeFocused();
  await page.getByRole('button',{name:'Clear search & outcome'}).click();
  await choose(page,'Record type','applications');
  await choose(page,'Board','hirist');
  await expect(page.locator('.records-count')).not.toContainText('Loading');
  await expect(page.locator('.records-body tbody tr').first()).toContainText('Hirist');
  await choose(page,'Board','all');
  await expect(page.locator('.records-count')).not.toContainText('Loading');
  await page.getByRole('button',{name:'Next',exact:true}).click();
  await expect(page.locator('.records-pagination')).toContainText('Page 2');
});

test('new controls preview exact CLI options without running bots',async({page})=>{
  await page.goto('/#/naukri');
  await page.getByLabel('Minimum match score').fill('66');
  await page.getByLabel('Maximum job age (days)').fill('5');
  await choose(page,'Scoring provider','none');
  await expect(page.locator('.preview')).toContainText('--min-score 66.0');
  await expect(page.locator('.preview')).toContainText('--max-days-old 5 --llm-backend none');
  await page.goto('/#/profile');
  await page.getByLabel('Review the full profile').check();
  await expect(page.locator('.preview')).toContainText('--review');
  await page.goto('/#/linkedin-profile');
  await expect(page.locator('.preview')).toContainText('linkedin_bot.update_profile --dry-run');
  await page.goto('/#/outreach');
  await page.getByLabel('Recipient email').fill('reader@example.com');
  await page.getByLabel('Company',{exact:true}).fill('Sample Company');
  await page.getByLabel('Maximum drafts').fill('2');
  await expect(page.locator('.preview')).toContainText('--to reader@example.com');
  await expect(page.locator('.preview')).toContainText('--dry-run');
  await page.getByLabel('Preview only').uncheck();
  await page.getByRole('button',{name:'Prepare drafts',exact:true}).click();
  await expect(page.getByRole('dialog')).toContainText('It does not send email.');
  await page.getByRole('button',{name:'Cancel',exact:true}).click();
  await page.goto('/#/pipeline/brief%3Apapers');
  await expect(page.getByRole('combobox',{name:'Stages to run',exact:true})).toHaveAttribute('data-value','brief:papers');
  await page.getByLabel('Rerun selected stages').check();
  await page.getByLabel('Research agents').fill('3');
  await choose(page,'AI CLI','kiro');
  await expect(page.locator('.preview')).toContainText('--only brief:papers --dry-run --redo --cli kiro --agents 3');
  await choose(page,'Stages to run','');
  await expect(page.locator('.preview')).toContainText('Select a stage or group');
  await expect(page.getByRole('button',{name:'Continue pipeline'})).toBeDisabled();
});

test('research documents can be searched, opened and read in their dark sandbox',async({page})=>{
  await page.goto('/#/research');
  await expect(page.locator('.document-item').first()).toBeVisible();
  await page.getByRole('searchbox',{name:'Find a document'}).fill('today');
  await expect(page.locator('.document-item').first()).toBeVisible();
  await page.locator('.document-item').first().click();
  await expect(page.locator('.document-reader')).toBeVisible();
  await expect(page.frameLocator('.document-reader').locator('h1').first()).toBeVisible();
  await expect(page.frameLocator('.document-reader').locator('body')).toHaveCSS('background-color','rgb(27, 29, 36)');
  await page.screenshot({animations:'disabled',path:'artifacts/research-reader.png',fullPage:true});
});

test('failed overview refresh retains records with an explicit stale state',async({page})=>{
  await page.goto('/#/overview');
  await expect(page.getByText('Application activity',{exact:true})).toBeVisible();
  await page.route('**/api/overview?*',route=>route.fulfill({status:503,json:{error:'Temporarily unavailable'}}));
  await page.getByRole('button',{name:'Refresh overview'}).click();
  await expect(page.getByRole('alert')).toContainText('Showing the last loaded records');
  await expect(page.locator('.recent-panel tbody tr')).toHaveCount(6);
  await expect(page.getByRole('button',{name:'Try again',exact:true})).toBeVisible();
});

test('launchpad search and avatar shortcuts open the right workspace controls',async({page})=>{
  await page.goto('/#/overview');
  await page.getByRole('searchbox',{name:'Search applications',exact:true}).fill('no-such-orbit-fixture');
  await page.getByRole('searchbox',{name:'Search applications',exact:true}).press('Enter');
  await expect(page).toHaveURL(/#\/records$/);
  await expect(page.getByRole('searchbox',{name:'Search records'})).toHaveValue('no-such-orbit-fixture');
  await expect(page.getByText('No records match these filters.',{exact:true})).toBeVisible();
  await page.goto('/#/overview');
  await page.getByRole('button',{name:'Configure Hirist',exact:true}).click();
  await expect(page.getByRole('combobox',{name:'Job board',exact:true})).toHaveAttribute('data-value','hirist');
  await expect(page.locator('.preview')).toContainText('--site hirist');
});

test('custom dropdown supports keyboard selection, typeahead, dismissal and accessible states',async({page})=>{
  await page.goto('/#/pipeline');
  const control=page.getByRole('combobox',{name:'AI CLI',exact:true});
  await control.focus();await page.keyboard.press('ArrowDown');
  await expect(control).toHaveAttribute('aria-expanded','true');
  await page.keyboard.press('End');await page.keyboard.press('Enter');
  await expect(control).toHaveAttribute('data-value','kiro');
  await expect(control).toBeFocused();
  await control.click();await page.keyboard.type('claude');await page.keyboard.press('Enter');
  await expect(control).toHaveAttribute('data-value','claude');
  await control.click();
  const audit=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa']).analyze();
  expect(audit.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))).toEqual([]);
  await page.screenshot({animations:'disabled',path:'artifacts/custom-dropdown.png'});
  await page.keyboard.press('Escape');await expect(control).toHaveAttribute('aria-expanded','false');
  await control.click();await page.getByRole('heading',{name:'Flows',exact:true}).click();
  await expect(control).toHaveAttribute('aria-expanded','false');
});

test('calendar supports typed errors, keyboard dates, months, clearing and mobile fit',async({page})=>{
  await page.setViewportSize({width:375,height:812});
  await page.goto('/#/pipeline');
  const date=page.getByLabel('Pipeline date',{exact:true});
  await date.fill('2026-02-30');await date.press('Tab');
  await expect(date).toHaveAttribute('aria-invalid','true');
  await expect(page.getByText('Enter a real date as YYYY-MM-DD, or choose one from the calendar.')).toBeVisible();
  await date.fill('2026-10-22');await page.getByRole('button',{name:'Choose date',exact:true}).click();
  const calendar=page.getByRole('dialog',{name:'Choose a date',exact:true});
  await expect(calendar).toBeVisible();
  await expect(calendar.getByRole('grid')).toBeVisible();
  await page.keyboard.press('ArrowRight');await page.keyboard.press('Enter');
  await expect(date).toHaveValue('2026-10-23');
  await expect(page.locator('.preview')).toContainText('--date 2026-10-23');
  await expect(page.getByRole('button',{name:'Choose date',exact:true})).toBeFocused();
  await page.getByRole('button',{name:'Choose date',exact:true}).click();
  await calendar.getByRole('button',{name:'Next month',exact:true}).click();
  await expect(calendar.getByRole('grid')).toHaveAttribute('aria-label','November 2026');
  const bounds=await calendar.boundingBox();expect(bounds.x).toBeGreaterThanOrEqual(0);expect(bounds.x+bounds.width).toBeLessThanOrEqual(375);
  const audit=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa']).analyze();
  expect(audit.violations.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))).toEqual([]);
  await page.screenshot({animations:'disabled',path:'artifacts/custom-calendar-mobile.png'});
  await calendar.getByRole('button',{name:'Clear date',exact:true}).click();await expect(date).toHaveValue('');
  await expect(date).toHaveAttribute('aria-invalid','false');
  await date.fill('2026-01-31');await page.getByRole('button',{name:'Choose date',exact:true}).click();
  await page.keyboard.press('PageDown');await page.keyboard.press('Enter');
  await expect(date).toHaveValue('2026-02-28');
});

test('bounded fields show persistent inline guidance and recover on correction',async({page})=>{
  await page.goto('/#/naukri');
  const score=page.getByLabel('Minimum match score');
  await score.fill('150');await score.press('Tab');
  await expect(score).toHaveAttribute('aria-invalid','true');
  await expect(page.getByText('Use 100 or less.',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Run',exact:true})).toBeDisabled();
  await score.fill('70');await expect(score).toHaveAttribute('aria-invalid','false');
  await expect(page.getByRole('button',{name:'Run',exact:true})).toBeEnabled();
});

test('interactive graph preserves real daily values across modes and channel filters',async({page})=>{
  await page.goto('/#/overview');
  const slider=page.getByRole('slider',{name:'Inspect application date'});
  await slider.focus();await page.keyboard.press('Home');
  await expect(slider).toHaveAttribute('aria-valuenow','1');
  const first=await slider.getAttribute('aria-valuetext');
  await page.keyboard.press('ArrowRight');await expect(slider).toHaveAttribute('aria-valuenow','2');
  await page.getByRole('button',{name:'Bars',exact:true}).click();
  await expect(page.locator('.chart-bars-motion')).not.toHaveCount(0);
  await slider.focus();await page.keyboard.press('Home');await expect(slider).toHaveAttribute('aria-valuetext',first);
  await page.getByRole('button',{name:'Job boards',exact:true}).click();
  await expect(page.getByRole('button',{name:'Job boards',exact:true})).toHaveAttribute('aria-pressed','false');
  await expect(slider).not.toHaveAttribute('aria-valuetext',/Job boards/);
  await page.getByRole('button',{name:'Trend',exact:true}).click();
  await expect(page.locator('.chart-line')).toHaveCount(2);
  await page.getByRole('button',{name:'Job boards',exact:true}).click();
  await expect(slider).toHaveAttribute('aria-valuetext',first);
  await page.getByText('View daily breakdown',{exact:true}).click();
  const cells=await page.locator('.chart-table tbody tr').first().locator('td').allTextContents();
  const values=await page.locator('.chart-values b').allTextContents();expect(values).toEqual(cells);
  await page.emulateMedia({reducedMotion:'reduce'});await page.getByRole('button',{name:'Bars',exact:true}).click();
  expect(await page.locator('.chart-bars-motion').first().evaluate(el=>getComputedStyle(el).animationName)).toBe('none');
});

test('inbox preserves multiline drafts and shows inline validation and save failures',async({page})=>{
  await page.route('**/api/status',async route=>{const response=await route.fetch();const data=await response.json();await route.fulfill({json:{...data,questions:[{line:7,questions:['Test employer question']}],facts:[]}});});
  await page.goto('/#/todo');
  const task=page.locator('.todo').first(),answer=task.getByRole('textbox');
  await task.getByRole('button',{name:'Save',exact:true}).click();
  await expect(answer).toHaveAttribute('aria-invalid','true');
  await answer.fill('First line');await answer.press('End');await answer.press('Enter');await answer.press('L');
  await expect(answer).toHaveValue('First line\nL');
  await task.getByRole('button',{name:'Save',exact:true}).click();
  await expect(task.getByRole('status')).toContainText('Your draft is still here');
  await expect(answer).toHaveValue('First line\nL');
});

test('failed learning save rolls back the checkbox with visible feedback',async({page})=>{
  await page.goto('/#/study');
  const check=page.locator('.lesson-row input').first();const before=await check.isChecked();
  await check.click();await expect(check).toBeEnabled();
  expect(await check.isChecked()).toBe(before);
  await expect(page.locator('.lesson-row').first().getByRole('status')).toContainText('Could not update progress');
});

test('research collections expose the real folder and preferences filter by purpose',async({page})=>{
  await page.goto('/#/research');
  await expect(page.getByRole('heading',{name:/notes in \.research/})).toBeVisible();
  await page.locator('.collection-card').filter({hasText:'Resume research'}).click();
  await expect(page.getByRole('combobox',{name:'Document category'})).toHaveAttribute('data-value','Resume research');
  await expect(page.locator('.document-item').first()).toContainText('.research/resume-learning/');
  await page.goto('/#/setup');
  await page.getByRole('button',{name:'Search & matching',exact:true}).click();
  await expect(page.locator('.setting-row:visible')).toHaveCount(2);
  await page.getByRole('button',{name:'Accounts',exact:true}).click();
  await expect(page.locator('.setting-row:visible')).toHaveCount(2);
  await expect(page.getByLabel('Naukri password (NAUKRI_PASSWORD)',{exact:true})).toHaveAttribute('type','password');
});

test('score ranges include zero buckets and graph transitions settle without idle motion',async({page})=>{
  await page.goto('/#/analytics');
  const score=page.getByRole('slider',{name:'Inspect score range'});
  await score.focus();await score.press('Home');await expect(score).toHaveAttribute('aria-valuenow','1');
  await expect(page.locator('.score-readout')).toContainText('0–5');
  await score.press('End');await expect(score).toHaveAttribute('aria-valuenow','20');
  await expect(page.locator('.score-readout')).toContainText('95–100');
  await page.getByRole('button',{name:'Bars',exact:true}).click();
  const bars=page.locator('.activity-explorer .chart-bars-motion').first();
  expect(await bars.evaluate(el=>getComputedStyle(el).animationName)).toBe('bar-reveal');
  await page.locator('.activity-explorer').evaluate(async el=>{await Promise.all(el.getAnimations({subtree:true}).map(a=>a.finished.catch(()=>{})));});
  await page.getByRole('slider',{name:'Inspect application date'}).hover();
  expect(await page.locator('.activity-explorer').evaluate(el=>el.getAnimations({subtree:true}).filter(a=>a.playState==='running').length)).toBe(0);
});

test.describe('Touch exploration',()=>{
  test.use({hasTouch:true,isMobile:true,viewport:{width:375,height:812}});
  test('mobile graph responds to taps and keeps controls reachable',async({page})=>{
    await page.goto('/#/overview');
    const slider=page.getByRole('slider',{name:'Inspect application date'});
    await slider.scrollIntoViewIfNeeded();
    const chart=page.locator('.interactive-chart');
    const bounds=await slider.boundingBox();
    await page.touchscreen.tap(bounds.x+4,bounds.y+bounds.height*.45);
    await expect(slider).toHaveAttribute('aria-valuenow','1');
    await page.touchscreen.tap(bounds.x+bounds.width-4,bounds.y+bounds.height*.45);
    const max=await slider.getAttribute('aria-valuemax');await expect(slider).toHaveAttribute('aria-valuenow',max);
    await page.getByRole('button',{name:'Bars',exact:true}).tap();
    await expect(page.getByRole('button',{name:'Bars',exact:true})).toHaveAttribute('aria-pressed','true');
    await page.getByRole('button',{name:'Naukri',exact:true}).tap();
    await expect(page.getByRole('button',{name:'Naukri',exact:true})).toHaveAttribute('aria-pressed','false');
    await expect(slider).not.toHaveAttribute('aria-valuetext',/Naukri/);
    await page.screenshot({animations:'disabled',path:'artifacts/chart-touch-mobile.png'});
  });
});

test('Research Studio and Data hub expose real sources and all-time records',async({page})=>{
  const sources=await (await page.request.get('/api/data')).json();
  await page.goto('/#/overview');
  await page.locator('.workspace-portal[href="#/research"]').click();
  await expect(page.getByRole('heading',{name:'Research Studio',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:/notes in \.research/})).toBeVisible();
  await page.locator('#nav a[href="#/data"]').click();
  await expect(page.locator('.data-source')).toHaveCount(7);
  for(const source of sources.sources){
    const card=page.locator('.data-source').filter({has:page.getByRole('heading',{name:source.title,exact:true})});
    await expect(card.locator('.data-source-count')).toHaveText(source.count===null?'—':new Intl.NumberFormat().format(source.count));
  }
  await page.locator('.data-source').filter({has:page.getByRole('heading',{name:'Application attempts',exact:true})}).click();
  await expect(page.getByRole('combobox',{name:'Record period',exact:true})).toHaveAttribute('data-value','0');
  await page.goto('/#/data/resumes');
  await expect(page.getByRole('combobox',{name:'File category',exact:true})).toHaveAttribute('data-value','Resumes');
  await expect(page.locator('.data-file').first()).toContainText('Resumes');
  expect(await page.locator('.data-file').count()).toBeLessThanOrEqual(24);
  const download=page.waitForEvent('download');await page.locator('.data-file').first().click();
  expect((await download).suggestedFilename()).toMatch(/\.pdf$/);
  await page.getByRole('searchbox',{name:'Search workspace data'}).fill('no-such-file-999');
  await expect(page.getByText('No saved files match. Try another category or search.')).toBeVisible();
});

test('profile crew selects profile-only previews for all four new platforms',async({page})=>{
  for(const name of ['Hirist','Instahyre','Cutshort','Wellfound']){
    await page.goto('/#/bots');
    await page.getByRole('button',{name:'Profile crew',exact:true}).click();
    await expect(page.locator('.bot-card')).toHaveCount(6);
    await page.getByRole('button',{name:`Configure ${name} profile`,exact:true}).click();
    await expect(page.getByRole('combobox',{name:'Job board',exact:true})).toHaveAttribute('data-value',name.toLowerCase());
    await expect(page.getByRole('combobox',{name:'Action',exact:true})).toHaveAttribute('data-value','profile');
    await expect(page.locator('.preview')).toContainText(`--site ${name.toLowerCase()} --profile-only --create-profile --dry-run`);
  }
  await page.goto('/#/boards/wellfound');
  await expect(page.getByRole('combobox',{name:'Action',exact:true})).toHaveAttribute('data-value','apply');
  await expect(page.locator('.preview')).not.toContainText('--profile-only');
});

test('workspace avatar picker persists choice without changing platform profiles',async({page})=>{
  await page.goto('/#/files/profile');
  await page.getByRole('button',{name:'Change avatar',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'Find your Orbit alter ego'});
  await expect(dialog.locator('.avatar-choice')).toHaveCount(24);
  await dialog.getByRole('button',{name:'Lilac cat',exact:true}).click();
  for(const width of [375,768,1280]){
    await page.setViewportSize({width,height:900});
    await expect(dialog).toBeInViewport();
    await page.screenshot({path:`artifacts/avatar-picker-${width}.png`,animations:'disabled'});
  }
  await dialog.getByRole('button',{name:'Use this avatar',exact:true}).click();
  await expect(page.locator('.workspace-profile [data-avatar="21"]')).toBeVisible();
  await expect(page.getByRole('button',{name:'Change avatar',exact:true})).toBeFocused();
  await page.reload();
  await expect(page.locator('.journey-banner [data-avatar="21"]')).toBeVisible();
  await page.getByRole('button',{name:'Change avatar',exact:true}).click();
  await page.getByRole('dialog').getByRole('button',{name:'Mint sprout',exact:true}).click();
  await page.keyboard.press('Escape');
  await expect(page.locator('.journey-banner [data-avatar="21"]')).toBeVisible();
});

test('Activity is compact, keyboard accessible and explains idle and failed runs',async({page})=>{
  await page.goto('/#/overview');
  await expect(page.getByRole('button',{name:'Copy output',exact:true})).not.toBeVisible();
  await page.getByRole('button',{name:/^Activity/}).click();
  await expect(page.getByText('A little quiet. A lot of possibility.',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Copy output',exact:true})).toBeDisabled();
  await page.screenshot({path:'artifacts/activity-idle-desktop.png',animations:'disabled'});
  await page.getByRole('button',{name:'Expand output',exact:true}).focus();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button',{name:/^Activity/})).toBeFocused();
  const failed={running:false,seconds:0,last:{label:'Wellfound profile · practice',exit:1,stopped:false,seconds:12,finished:'2026-10-23T00:00:00'},next:2,lines:[[0,'Opening the profile preview…'],[1,'Sign-in required. Review your platform session and try again.']]};
  await page.route('**/api/status',async route=>{const r=await route.fetch();await route.fulfill({json:{...await r.json(),run:failed}});});
  await page.route('**/api/run?*',route=>route.fulfill({json:failed}));
  await page.reload();await page.getByRole('button',{name:/^Activity/}).click();
  await expect(page.locator('.activity-state')).toHaveText('Needs attention');
  await expect(page.getByRole('log',{name:'Run output'})).toContainText('Sign-in required.',{timeout:10000});
  await expect(page.getByRole('button',{name:'Stop',exact:true})).not.toBeVisible();
  await page.setViewportSize({width:375,height:812});
  await expect(page.locator('.console')).toBeInViewport();
  await page.screenshot({path:'artifacts/activity-failed-mobile.png',animations:'disabled'});
  const result=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21a', 'wcag21aa','wcag22aa']).analyze();
  expect(result.violations.map(v=>v.id)).toEqual([]);
});
