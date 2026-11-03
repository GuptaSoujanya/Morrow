"""Offline DOM contract from Cutshort's saved Nov 3 job/inbox snapshots.

Run separately with RUN_BROWSER_CONTRACTS=1; no account or network is used.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from cutshort_bot import questionnaires as q


@pytest.mark.skipif(os.getenv("RUN_BROWSER_CONTRACTS") != "1", reason="offline browser contract is opt-in")
def test_actual_dom_excludes_other_jobs_inbox_previews_and_chat_messages():
    root = Path(__file__).resolve().parents[2]
    if not shutil.which("node") or not (root / "froned-dashbord/node_modules/playwright").exists():
        pytest.skip("local Playwright is unavailable")
    script = r"""
const {chromium} = require('./froned-dashbord/node_modules/playwright');
const assert = require('node:assert/strict');
let raw=''; process.stdin.on('data', d => raw += d);
process.stdin.on('end', async () => {
  const data=JSON.parse(raw);
  const browser=await chromium.launch({headless:true, executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  try {
    const page=await browser.newPage();
    await page.route('**/*', route => route.abort());
    const href='https://cutshort.io/profile/conversations/candidate?i=all&thread=6ae9cf1356433e8e3f5febcc&stage=awaiting';
    await page.setContent('<h2>Showing 1 recently active jobs</h2><article><a href="https://cutshort.io/job/Senior-Fullstack-Engineer-encbzjFp">Senior Fullstack Engineer</a><a href="'+href+'">View conversation</a></article>');
    assert.deepEqual(await page.evaluate(code => new Function(code)(), data.conversation), [href]);
    await page.locator('h2').evaluate(el => el.textContent='Showing 2 recently active jobs');
    assert.deepEqual(await page.evaluate(code => new Function(code)(), data.conversation), []);
    await page.setContent('<aside role="tabpanel"><button>Acme For job Engineer [Questionnaire]</button><div role="status">Questionnaire answers submitted</div></aside><section id="selected"><header>Acme <span>For job Engineer</span></header><a href="https://cutshort.io/job/Engineer-12345678">View full job description</a><div role="log"><div role="status">Questionnaire answers submitted</div></div><p>Questionnaire answers submitted</p><textarea placeholder="Type your message..."></textarea></section>');
    assert.deepEqual(await page.evaluate(code => new Function(code)(), data.proof), []);
    await page.locator('#selected').evaluate(el => {const s=document.createElement('div');s.role='status';s.textContent='Questionnaire answers submitted';el.append(s);});
    assert.deepEqual(await page.evaluate(code => new Function(code)(), data.proof), ['Questionnaire answers submitted']);
    console.log('Cutshort DOM contract passed');
  } finally { await browser.close(); }
});
"""
    result = subprocess.run(["node", "-e", script], cwd=root, input=json.dumps({"conversation": q._CONVERSATION_SCRIPT,
                            "proof": q._PROOF_SCRIPT}), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "Cutshort DOM contract passed" in result.stdout
