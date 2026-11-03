"""Offline profile-reader browser contract; opt in with RUN_BROWSER_CONTRACTS=1."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from sites_bot.profile_agent import _TEXT_JS


@pytest.mark.skipif(os.getenv('RUN_BROWSER_CONTRACTS') != '1', reason='offline browser contract is opt-in')
def test_selected_current_visible_values_are_the_only_profile_evidence():
    root = Path(__file__).resolve().parents[2]
    if not shutil.which('node') or not (root / 'froned-dashbord/node_modules/playwright').exists():
        pytest.skip('local Playwright is unavailable')
    script = r"""
const {chromium} = require('./froned-dashbord/node_modules/playwright');
const assert = require('node:assert/strict');
let raw=''; process.stdin.on('data', chunk => raw += chunk);
process.stdin.on('end', async () => {
  const browser=await chromium.launch({headless:true,
    executablePath:process.env.CHROMIUM_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try {
    const page=await browser.newPage();
    await page.route('**/*', route => route.abort());
    await page.setContent(`<label for="city">Current location</label>
      <select id="city"><option>UnsavedCity</option><option selected>SavedCity</option></select>
      <label><input type="radio" name="role" checked>SavedRadio</label>
      <label><input type="radio" name="role">UnsavedRadio</label>
      <div role="checkbox" aria-checked="true">SavedCheckbox</div>
      <div role="checkbox" aria-checked="false">UnsavedCheckbox</div>
      <label for="about">About</label><textarea id="about">Old default summary</textarea>
      <div style="visibility:hidden"><textarea>Invisible summary</textarea></div>
      <div aria-hidden="true"><textarea>Aria hidden summary</textarea></div>
      <div hidden><textarea>Hidden summary</textarea></div>`);
    await page.locator('#about').evaluate(el => { el.value='Current saved summary'; });
    const text=await page.evaluate(code => new Function(code)(), JSON.parse(raw));
    for (const value of ['SavedCity','SavedRadio','SavedCheckbox','Current saved summary']) assert.ok(text.includes(value), value);
    for (const value of ['UnsavedCity','UnsavedRadio','UnsavedCheckbox','Old default summary','Invisible summary','Aria hidden summary','Hidden summary']) assert.ok(!text.includes(value), value);
    console.log('Profile reader DOM contract passed');
  } finally { await browser.close(); }
});
"""
    result = subprocess.run(['node', '-e', script], cwd=root, input=json.dumps(_TEXT_JS),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'Profile reader DOM contract passed' in result.stdout
