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
      if (name === 'files') await expect(page.getByRole('textbox', { name: 'First name', exact: true })).toBeVisible();
      if (name === 'setup') await expect(page.getByRole('searchbox')).toBeVisible();
      if (name === 'data') await expect(page.locator('.source-tile')).toHaveCount(7);
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
  await page.getByRole('textbox', { name:'First name',exact:true }).fill('Updated');
  await page.locator('.file-tabs a[href="#/files/answers"]').click();
  await page.locator('.file-tabs a[href="#/files/profile"]').click();
  await expect(page.getByRole('textbox',{name:'First name',exact:true})).toHaveValue('Updated');
  await page.getByRole('button',{name:'Save changes',exact:true}).click();
  await page.getByRole('dialog').getByRole('button',{name:'Save changes'}).click();
  await expect(page.getByRole('alert').filter({hasText:'This file changed since you opened it.'})).toBeVisible();
  expect(saved).toMatchObject({name:'profile',revision:'fixture-v1'});
  expect(saved.text).toContain('first_name: Updated');
  expect(saved.text).toContain('location: Bengaluru');
  await expect(page.getByRole('textbox',{name:'First name',exact:true})).toHaveValue('Updated');
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
  await expect(page.locator('.pagination [aria-current=page]')).toHaveText('2');
  await expect(page).toHaveURL(/page=2/);
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
  await page.goto('/#/research?view=library');
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
  await expect(page).toHaveURL(/#\/records\?/);
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
  await page.getByRole('link',{name:'Library',exact:true}).click();
  await expect(page.getByText(/notes from \.research/)).toBeVisible();
  await page.getByRole('button',{name:'Resume research',exact:true}).click();
  await expect(page.getByRole('button',{name:'Resume research',exact:true})).toHaveAttribute('aria-pressed','true');
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
  await page.getByRole('link',{name:'Library',exact:true}).click();
  await expect(page.getByText(/notes from \.research/)).toBeVisible();
  await page.locator('#nav a[href="#/data"]').click();
  await expect(page.locator('.source-tile')).toHaveCount(7);
  for(const source of sources.sources){
    const card=page.locator('.source-tile').filter({hasText:source.title});
    await expect(card.locator('strong')).toHaveText(source.count===null?'—':new Intl.NumberFormat().format(source.count));
  }
  await page.locator('.source-tile').filter({hasText:'Application attempts'}).click();
  await expect(page.getByRole('combobox',{name:'Record period',exact:true})).toHaveAttribute('data-value','0');
  await page.goto('/#/data/resumes');
  await expect(page.getByRole('combobox',{name:'File category',exact:true})).toHaveAttribute('data-value','Resumes');
  await expect(page.locator('.data-file').first()).toContainText('Resumes');
  expect(await page.locator('.data-file').count()).toBeLessThanOrEqual(24);
  await page.locator('.data-file').first().getByRole('button',{name:/Preview/}).click();
  await expect(page.getByRole('dialog',{name:/resume|pdf|resume review/i})).toBeVisible().catch(async()=>{await expect(page.locator('.resume-dialog')).toBeVisible();});
  await page.getByRole('button',{name:'Close resume preview'}).click();
  const download=page.waitForEvent('download');await page.locator('.data-file').first().getByRole('link',{name:/Download/}).click();
  expect((await download).suggestedFilename()).toMatch(/\.pdf$/);
  await page.getByRole('searchbox',{name:'Search workspace data'}).fill('no-such-file-999');
  await expect(page.getByText('No saved files match.')).toBeVisible();
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
  const dialog=page.getByRole('dialog',{name:'Find your Morrow alter ego'});
  await expect(dialog.locator('.avatar-choice')).toHaveCount(32);
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

test('records pagination is bounded for 100,000 rows and survives refresh and history',async({page})=>{
  await page.route('**/api/records?*',route=>{
    const q=new URL(route.request().url()).searchParams,size=Number(q.get('size')||20),pageNumber=Math.min(Number(q.get('page')||1),Math.ceil(100000/size));
    return route.fulfill({json:{page:pageNumber,pages:Math.ceil(100000/size),size,total:100000,statuses:['applied'],updated_at:new Date().toISOString(),rows:Array.from({length:size},(_,i)=>({job_id:String((pageNumber-1)*size+i+1),title:`Fixture role ${(pageNumber-1)*size+i+1}`,company:'Example',board:'hirist',kind:'sent',label:'Submitted',score:85,at:'2026-10-23T08:00:00',url:''}))}});
  });
  await page.goto('/#/records?kind=jobs&days=0&page=2&size=20&board=hirist');
  await expect(page.locator('tbody tr')).toHaveCount(20);
  await expect(page.locator('tbody tr').first()).toContainText('Fixture role 21');
  await page.getByRole('button',{name:'Next',exact:true}).click();
  await expect(page).toHaveURL(/page=3/);
  await expect(page.locator('tbody tr').first()).toContainText('Fixture role 41');
  await page.goBack();
  await expect(page.locator('tbody tr').first()).toContainText('Fixture role 21');
  await page.goForward();await page.reload();
  await expect(page.locator('tbody tr').first()).toContainText('Fixture role 41');
  await expect(page.getByRole('combobox',{name:'Board',exact:true})).toHaveAttribute('data-value','hirist');
  await choose(page,'Rows per page','50');
  await expect(page).toHaveURL(/page=1.*size=50/);
  await expect(page.locator('tbody tr')).toHaveCount(50);
  expect(await page.locator('.page-number').count()).toBeLessThanOrEqual(5);
});

test('Data hub restores filters and previews without triggering a download',async({page})=>{
  await page.goto('/#/data?category=Resumes&page=2&size=12');
  await expect(page.locator('.data-file')).toHaveCount(12);
  const title=await page.locator('.data-file-name strong').first().textContent();
  await page.reload();await expect(page.locator('.data-file-name strong').first()).toHaveText(title);
  const downloads=[];page.on('download',d=>downloads.push(d));
  const trigger=page.locator('.data-file').first().getByRole('button',{name:/Preview/});
  await trigger.click();
  const dialog=page.locator('.resume-dialog');await expect(dialog).toBeVisible();
  const src=await dialog.locator('iframe').getAttribute('src');expect(src).toContain('preview=1');
  const response=await page.request.get(src);expect(response.headers()['content-disposition']).toMatch(/^inline/);
  const audit=await new AxeBuilder({page}).exclude('iframe').withTags(['wcag2a','wcag2aa']).analyze();expect(audit.violations.map(v=>v.id)).toEqual([]);
  await page.screenshot({path:'artifacts/resume-preview-laptop.png',animations:'disabled'});
  await page.keyboard.press('Escape');await expect(trigger).toBeFocused();expect(downloads).toHaveLength(0);
  await choose(page,'File category','Research');await expect(page).toHaveURL(/category=Research.*page=1/);
  await page.goBack();await expect(page.getByRole('combobox',{name:'File category',exact:true})).toHaveAttribute('data-value','Resumes');
  await expect(page.locator('.pagination [aria-current=page]')).toHaveText('2');
});

test('query cache reuses reads, explicit refresh refetches, mutation invalidates',async({page})=>{
  let reads=0;
  await page.route('**/api/data?*',route=>{reads++;return route.fallback();});
  await page.route('**/api/course/read',route=>route.fulfill({json:{ok:true}}));
  await page.goto('/#/data');await expect(page.locator('.data-file').first()).toBeVisible();expect(reads).toBe(1);
  await page.locator('#nav a[href="#/reports"]').click();await expect(page.locator('main h1')).toHaveText('Reports');
  await page.locator('#nav a[href="#/data"]').click();await expect(page.locator('.data-file').first()).toBeVisible();expect(reads).toBe(1);
  await page.getByRole('button',{name:'Refresh data',exact:true}).click();await expect.poll(()=>reads).toBe(2);
  await page.locator('#nav a[href="#/study"]').click();await page.locator('.lesson-row input').first().click();await expect(page.locator('.lesson-row input').first()).toBeEnabled();
  await page.locator('#nav a[href="#/data"]').click();await expect(page.locator('.data-file').first()).toBeVisible();expect(reads).toBe(3);
});

test('late filter responses cannot overwrite the current search',async({page})=>{
  await page.route('**/api/data?*',async route=>{
    const q=new URL(route.request().url()).searchParams.get('q');
    if(q==='slow')await new Promise(resolve=>setTimeout(resolve,700));
    if(q)return route.fulfill({json:{sources:[],files:[],total:0,page:1,pages:1,size:12}});
    return route.fallback();
  });
  await page.goto('/#/data');await expect(page.locator('.data-file').first()).toBeVisible();
  const search=page.getByRole('searchbox',{name:'Search workspace data'});
  const slow=page.waitForRequest(r=>r.url().includes('q=slow'));await search.fill('slow');await slow;
  await search.fill('latest');await expect(page).toHaveURL(/q=latest/);await expect(page.getByText('No saved files match.',{exact:true})).toBeVisible();
  await page.waitForResponse(r=>r.url().includes('q=slow'));await expect(page).toHaveURL(/q=latest/);await expect(search).toHaveValue('latest');await expect(search).toBeFocused();
});

test('lazy route loading is visible and failed chunks preserve navigation',async({page})=>{
  await page.goto('/#/overview');await expect(page.locator('main h1')).toBeVisible();
  let release;const held=new Promise(resolve=>{release=resolve;});
  await page.route('**/assets/chunks/data-*.js',async route=>{await held;return route.continue();});
  await page.locator('#nav a[href="#/data"]').click();
  await expect(page.locator('main .state-loading')).toBeVisible();
  await page.screenshot({path:'artifacts/lazy-loading.png',animations:'disabled'});release();
  await expect(page.locator('main h1')).toHaveText('Data hub');
  await page.route('**/assets/chunks/research-*.js',route=>route.abort());
  await page.locator('#nav a[href="#/research"]').click();
  await expect(page.getByRole('alert')).toContainText('This page could not open');
  await expect(page.getByRole('button',{name:'Reload workspace',exact:true})).toBeVisible();
  await page.locator('.nav-group a[href="#/overview"]').click();await expect(page.getByText('Application activity',{exact:true})).toBeVisible();
});

test('profile fields preserve YAML types, lists, comments and unrelated facts',async({page})=>{
  const source='# keep this comment\nfirst_name: Demo\ntotal_experience_years: 3\nskills:\n  - Python\n  - SQL\nwilling_to_relocate: true\nextra_facts:\n  portfolio_url: https://example.com\n  custom_fact: Keep me\n';
  let saved;
  await page.route('**/api/file?name=profile',route=>route.fulfill({json:{name:'profile',path:'profile.yaml',text:source,revision:'fixture-types'}}));
  await page.route('**/api/file',route=>{saved=route.request().postDataJSON();return route.fulfill({json:{ok:true,revision:'fixture-saved'}});});
  await page.goto('/#/files/profile');await page.getByRole('textbox',{name:'First name',exact:true}).fill('Taylor: Jo');
  await page.getByRole('button',{name:'Career',exact:true}).click();await page.getByLabel('Experience in years',{exact:true}).fill('4.5');
  await page.getByLabel('Skills',{exact:true}).fill('Python\nTypeScript');
  await page.locator('.profile-form').getByRole('button',{name:'Preferences',exact:true}).click();await choose(page,'Willing to relocate','false');
  await page.getByRole('button',{name:'Save changes',exact:true}).click();await page.getByRole('dialog').getByRole('button',{name:'Save changes',exact:true}).click();
  await expect.poll(()=>saved?.revision).toBe('fixture-types');
  expect(saved.text).toContain('# keep this comment');expect(saved.text).toContain('total_experience_years: 4.5');expect(saved.text).toContain('willing_to_relocate: false');expect(saved.text).toContain('custom_fact: Keep me');expect(saved.text).toContain('TypeScript');expect(saved.text).toContain('"Taylor: Jo"');
  await expect(page.getByText('All changes saved',{exact:true})).toBeVisible();
});

for(const [width,height] of [[1280,720],[1366,768],[1440,900]])test(`laptop workspace at ${width}×${height}`,async({page})=>{
  test.setTimeout(90000);await page.setViewportSize({width,height});await mkdir(`artifacts/laptop-${width}`,{recursive:true});
  for(const route of ['overview','research','reports','study','files','setup','data','records']){
    await page.goto('/#/'+route);await expect(page.locator('main h1')).toBeVisible();
    if(route==='files'){await expect(page.getByRole('textbox',{name:'First name',exact:true})).toBeVisible();await expect(page.getByRole('textbox',{name:'First name',exact:true})).toBeInViewport();}
    if(route==='data')await expect(page.locator('.data-file').first()).toBeVisible();
    if(route==='research')await expect(page.locator('.daily-digest')).toBeVisible();
    if(route==='reports')await expect(page.getByText('Reading the report…')).toHaveCount(0);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),route).toBe(true);
    await page.screenshot({path:`artifacts/laptop-${width}/${route}.png`,animations:'disabled'});
  }
});

test('Research Learning shows the next read, saves explicitly and explains earlier progress',async({page})=>{
  let completed=false,fail=false;const date=new Date().toLocaleDateString('en-CA'),at=new Date().toISOString();
  await page.route('**/api/research/learning?*',route=>route.fulfill({json:{date,focus:{id:completed?'plan/day-2':'plan/day-1',day:completed?2:1,title:completed?'Caching foundations':'Client and server'},queue:[{id:completed?'plan/day-2':'plan/day-1',title:completed?'Caching foundations':'Client and server',category:'Learning',caption:'Your next unfinished day'}],plan_done:completed?1:0,plan_total:90,course_done:3,course_total:49,completed_today:completed?[{id:'plan/day-1',kind:'research',title:'Client and server',completed_at:at}]:[],history:{items:completed?[{id:'plan/day-1',kind:'research',title:'Client and server',at,action:'completed'}]:[],page:1,pages:1,size:15,total:completed?1:0},imported:[{id:'intro.md',kind:'course',title:'Imported introduction',done:true}],legacy_plan_days:[],storage:'.memory/learning.json'}}));
  await page.route('**/api/document?id=plan%2Fday-1',route=>route.fulfill({json:{id:'plan/day-1',title:'Client and server',day:1,read:completed,html:'<h1>Client and server</h1><p>A saved lesson.</p>'}}));
  await page.route('**/api/research/read',route=>{if(fail)return route.fulfill({status:500,json:{error:'Disk is unavailable.'}});completed=route.request().postDataJSON().read;return route.fulfill({json:{ok:true,read:completed}});});
  await page.goto('/#/research?view=learning');await expect(page.locator('.daily-focus')).toContainText('Client and server');
  await page.getByRole('link',{name:'Start reading',exact:true}).click();await expect(page.getByRole('button',{name:'Mark complete',exact:true})).toBeVisible();expect(completed).toBe(false);
  fail=true;await page.getByRole('button',{name:'Mark complete',exact:true}).click();await expect(page.locator('.reading-save-status')).toContainText('Could not save');expect(completed).toBe(false);
  fail=false;await page.getByRole('button',{name:'Mark complete',exact:true}).click();await expect(page.getByRole('button',{name:'Reopen reading',exact:true})).toBeEnabled();
  await page.reload();await expect(page.getByRole('button',{name:'Reopen reading',exact:true})).toBeVisible();
  await page.getByRole('link',{name:'← Back to Research Studio',exact:true}).click();await expect(page.locator('.daily-focus')).toContainText('Caching foundations');
  await expect(page.locator('.panel').filter({has:page.getByRole('heading',{name:'Completed today',exact:true})})).toContainText('Client and server');
  await page.getByRole('link',{name:'Progress',exact:true}).click();await expect(page).toHaveURL(/view=progress/);
  await expect(page.getByRole('heading',{name:'Your learning history'})).toBeVisible();await page.getByText('1 imported completions',{exact:true}).click();await expect(page.getByText('Imported introduction',{exact:true})).toBeVisible();
  for(const width of [375,768,1280]){await page.setViewportSize({width,height:900});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);await page.screenshot({path:`artifacts/research-progress-${width}.png`,animations:'disabled',fullPage:true});}
  const result=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();expect(result.violations.map(v=>v.id)).toEqual([]);
  await page.goto('/#/research/plan%2Fday-1?view=today');await page.getByRole('button',{name:'Reopen reading',exact:true}).click();await expect(page.getByRole('button',{name:'Mark complete',exact:true})).toBeEnabled();expect(completed).toBe(false);
});

test('short laptop navigation scrolls independently and remains stable during polling',async({page})=>{
  await page.setViewportSize({width:1280,height:720});await page.goto('/#/research?view=learning');await expect(page.locator('.daily-focus')).toBeVisible();
  const scroll=page.locator('.sidebar-scroll');expect(await scroll.evaluate(el=>el.scrollHeight>el.clientHeight)).toBe(true);
  await scroll.evaluate(el=>{el.scrollTop=el.scrollHeight;});await expect(page.locator('.nav-group a[href="#/setup"]')).toBeInViewport();
  const before=await scroll.evaluate(el=>el.scrollTop);await page.waitForResponse(r=>r.url().includes('/api/status'));expect(await scroll.evaluate(el=>el.scrollTop)).toBe(before);
  await page.locator('.nav-group a[href="#/setup"]').click();await expect(page.locator('main h1')).toBeVisible();await expect(page.locator('.sidebar-foot')).toBeInViewport();
  expect(await page.evaluate(()=>scrollY)).toBe(0);await page.screenshot({path:'artifacts/sidebar-short-laptop.png',animations:'disabled'});
});

test('loading indicator is centered and respects reduced motion',async({page})=>{
  await page.setViewportSize({width:1366,height:768});await page.emulateMedia({reducedMotion:'reduce'});
  await page.goto('/#/overview');await expect(page.locator('main h1')).toBeVisible();
  let release;const held=new Promise(resolve=>{release=resolve;});await page.route('**/assets/chunks/data-*.js',async route=>{await held;return route.continue();});
  await page.locator('.nav-group a[href="#/data"]').click();const state=page.locator('main .state-loading');await expect(state).toBeVisible();
  const box=await state.boundingBox(),emblem=await state.locator('.loading-emblem').boundingBox();expect(Math.abs(emblem.x+emblem.width/2-box.x-box.width/2)).toBeLessThan(2);expect(emblem.y).toBeGreaterThan(200);
  expect(await page.locator('.loading-orbit').evaluate(el=>getComputedStyle(el).animationName)).toBe('none');await page.screenshot({path:'artifacts/centered-loading-laptop.png',animations:'disabled'});release();await expect(page.locator('main h1')).toHaveText('Data hub');
});

test('legacy course URL opens the real lesson and provides a safe progress control',async({page})=>{
  test.setTimeout(60000);
  await page.goto('/course/01-system-design/');await expect(page).toHaveURL('/course/#/01-system-design/');
  await expect(page.locator('.markdown-section h1').first()).toBeVisible({timeout:30000});
  await expect(page.locator('.morrow-progress button')).toBeVisible();await page.locator('.morrow-progress button').click();
  await expect(page.locator('.morrow-progress [role=status]')).toContainText('Could not save');await expect(page.locator('.morrow-progress button')).toBeEnabled();
  await page.screenshot({path:'artifacts/course-reader-progress.png',animations:'disabled'});
});

test('daily research exposes Papers, Tech, Companies, README and distinct learning spaces',async({page})=>{
  await page.goto('/#/research?view=today&date=2026-10-22');
  await expect(page.getByRole('link',{name:'Open daily README',exact:true})).toBeVisible();
  for(const [key,title] of [['papers','Papers'],['tech','Tech radar'],['companies','Company radar']]){
    const section=page.locator(`[data-research-section="${key}"]`);await expect(section.getByRole('heading',{name:title,exact:true})).toBeVisible();await expect(section.getByRole('link',{name:'Open '+title,exact:true})).toBeVisible();await expect(section.locator('.research-headlines li').first()).toBeVisible();
  }
  await page.getByRole('link',{name:'Open Papers',exact:true}).click();await expect(page.frameLocator('.document-reader').locator('h1')).toContainText('Papers');
  await page.getByRole('link',{name:'← Back to Research Studio',exact:true}).click();await expect(page).toHaveURL(/view=today.*date=2026-10-22/);
  await page.getByRole('link',{name:'Learning',exact:true}).click();await expect(page).toHaveURL(/view=learning.*date=2026-10-22/);
  await expect(page.getByRole('heading',{name:'Daily learning goal',exact:true})).toBeVisible();await expect(page.getByRole('heading',{name:'System design deep dive',exact:true})).toBeVisible();await expect(page.locator('.daily-digest')).toHaveCount(0);
  await page.getByRole('link',{name:'Resume lab',exact:true}).click();await expect(page.getByRole('heading',{name:'Your resume topics',exact:true})).toBeVisible();await expect(page.locator('.research-row')).toHaveCount(12);
  await page.getByRole('link',{name:'Open resume README',exact:true}).click();await expect(page.frameLocator('.document-reader').locator('h1')).toHaveText('Resume learning');await expect(page.frameLocator('.document-reader').locator('li')).toHaveCount(12);
});

test('missing daily research can be fetched by exact section and selected date with inline errors',async({page})=>{
  await page.goto('/#/research?view=today&date=2026-10-23');
  await expect(page.getByRole('button',{name:'Fetch daily research',exact:true})).toBeVisible();await expect(page.getByRole('link',{name:/Latest saved research:/})).toBeVisible();
  const calls=[];page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/api/run'))calls.push(r.postDataJSON());});
  for(const [title,group] of [['Papers','brief:papers'],['Tech radar','brief:tech-news'],['Company radar','brief:companies']]){
    await page.getByRole('button',{name:'Fetch '+title,exact:true}).click();const dialog=page.getByRole('dialog',{name:`Fetch ${title}?`});await expect(dialog.locator('code')).toContainText('--only '+group);await expect(dialog.locator('code')).toContainText('--date 2026-10-23');await expect(dialog.locator('code')).not.toContainText('--only apply');await dialog.getByRole('button',{name:'Cancel',exact:true}).click();
  }
  expect(calls).toHaveLength(0);
  await page.getByRole('button',{name:'Fetch Papers',exact:true}).click();await page.getByRole('dialog').getByRole('button',{name:'Fetch research',exact:true}).click();
  await expect(page.locator('[data-research-section=papers] [role=alert]')).toContainText('Could not fetch this research');expect(calls).toEqual([{action:'pipeline',options:{group:'brief:papers',date:'2026-10-23',redo:true}}]);
  const date=page.getByRole('textbox',{name:'Research date',exact:true});await date.fill('2026-10-22');await date.press('Enter');await expect(page).toHaveURL(/date=2026-10-22/);await expect(page.getByRole('link',{name:'Open daily README',exact:true})).toBeVisible();
});

test('research desk views remain readable and accessible across laptop, tablet and phone',async({page})=>{
  test.setTimeout(90000);
  for(const width of [375,768,1280]){
    await page.setViewportSize({width,height:width===1280?720:900});
    for(const view of ['today','learning','resume','library','progress']){
      await page.goto(`/#/research?view=${view}&date=2026-10-22`);await expect(page.locator('main h1')).toBeVisible();
      if(view==='today')await expect(page.locator('[data-research-section=papers]')).toBeVisible();
      if(view==='learning')await expect(page.locator('.daily-focus')).toBeVisible();
      if(view==='resume')await expect(page.locator('.research-row')).toHaveCount(12);
      if(view==='library')await expect(page.getByRole('searchbox',{name:'Find a document'})).toBeVisible();
      if(view==='progress')await expect(page.getByRole('heading',{name:'Your learning history',exact:true})).toBeVisible();
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),view).toBe(true);
      await page.screenshot({path:`artifacts/research-${view}-${width}.png`,animations:'disabled',fullPage:true});
      if(width===1280){const result=await new AxeBuilder({page}).exclude('iframe').withTags(['wcag2a','wcag2aa','wcag21aa','wcag22aa']).analyze();expect(result.violations.map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)})),view).toEqual([]);}
    }
  }
});
