import { chromium } from '@playwright/test';
import { playAudit } from 'playwright-lighthouse';
import desktopConfig from 'lighthouse/core/config/desktop-config.js';
import { mkdir, writeFile } from 'node:fs/promises';
const root = process.env.DASHBOARD_URL || 'http://127.0.0.1:8100';
await mkdir('artifacts/lighthouse', { recursive: true });
const results = [];
const args=process.argv.slice(2);
const requested=args.includes('--preset')?args[args.indexOf('--preset')+1]:null;
const presets=requested?[requested]:['desktop','mobile'];
const count=args.includes('--runs')?Number(args[args.indexOf('--runs')+1]):3;
if(presets.some(p=>!['desktop','mobile'].includes(p))||!Number.isInteger(count)||count<1||count>5)throw new Error('Use --preset desktop|mobile and --runs 1..5.');
for (const preset of presets) {
  for (let run = 1; run <= count; run++) {
    const port = 9340 + run + (preset === 'mobile' ? 10 : 0);
    const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true, args: [`--remote-debugging-port=${port}`] });
    try {
      const context = await browser.newContext();
      const page = await context.newPage();
      await page.goto(root);
      await page.getByText('Application activity', { exact: true }).waitFor();
      const result = await playAudit({ page, port, ignoreError: true,
        thresholds: { performance: 100, accessibility: 100, 'best-practices': 100, seo: 100 },
        opts: { disableStorageReset: false },
        config: preset === 'desktop' ? desktopConfig : undefined,
        reports: { formats: { json: true, html: true }, name: `${preset}-${run}`, directory: 'artifacts/lighthouse' } });
      const lhr = result.lhr;
      const scores = Object.fromEntries(Object.entries(lhr.categories).map(([k,v]) => [k, Math.round(v.score * 100)]));
      const metrics = Object.fromEntries(['first-contentful-paint', 'largest-contentful-paint', 'cumulative-layout-shift', 'total-blocking-time'].map(key => [key, lhr.audits[key].numericValue]));
      results.push({ preset, run, scores, metrics });
      console.log(JSON.stringify(results.at(-1)));
    } finally { await browser.close(); }
  }
}
await writeFile('artifacts/lighthouse/summary.json', JSON.stringify(results, null, 2));
for (const preset of presets) {
  const group = results.filter(r => r.preset === preset);
  const median = key => group.map(r => r.scores[key]).sort((a,b) => a-b)[Math.floor(group.length/2)];
  console.log(preset, Object.fromEntries(Object.keys(group[0].scores).map(key => [key, median(key)])));
}
