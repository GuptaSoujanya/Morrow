import { chromium } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import AxeBuilder from '@axe-core/playwright';
const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
await mkdir('artifacts', { recursive: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } });
const page = await context.newPage();
const errors = [];
page.on('pageerror', error => errors.push(error.message));
await page.goto('http://127.0.0.1:8100');
await page.waitForTimeout(1500);
console.log('title', await page.title(), 'errors', errors);
await page.screenshot({ path: 'artifacts/overview-desktop.png', fullPage: true });
const a11y = await new AxeBuilder({ page }).analyze();
console.log('accessibility', a11y.violations.map(v => ({ id: v.id, impact: v.impact, nodes: v.nodes.map(n => ({ target: n.target, summary: n.failureSummary })) })));
await writeFile('artifacts/accessibility-initial.json', JSON.stringify(a11y.violations, null, 2));
for (const [width,height,name] of [[375,900,'mobile'],[768,1000,'tablet'],[1280,900,'desktop-viewport']]) {
  await page.setViewportSize({width,height});
  await page.goto('http://127.0.0.1:8100/#/overview');
  await page.getByText('Application activity',{exact:true}).waitFor();
  await page.locator('main').evaluate(async el=>{await Promise.all(el.getAnimations({subtree:true}).filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{})));});
  await page.screenshot({path:`artifacts/orbit-${name}.png`,animations:'disabled'});
}
await browser.close();
