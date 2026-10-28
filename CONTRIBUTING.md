# Contributing to Morrow

Run `bash setup.sh --no-start` from the repository root. Keep personal profiles,
resumes, answer banks, browser sessions, `.env`, and logs out of commits and issue
attachments. Use synthetic details in tests and screenshots.

The dashboard is a separate Git submodule in `froned-dashbord/`. Changes there
must be committed in its repository and published before the parent repository
can point to that commit. Do not initialize or share personal data repositories;
the public project treats those paths as ignored local storage.

## Validate a change

```bash
venv/bin/python -m pip install pytest
venv/bin/python -m pytest tests/common/test_local_setup.py tests/common/test_resume_onboarding.py tests/common/test_answers_file.py
venv/bin/python -m pytest froned-dashbord/tests/test_local_onboarding.py froned-dashbord/tests/test_server.py
bash -n setup.sh scripts/morrow
bash setup.sh --check
cd froned-dashbord
npm run build
node --test tests/access-policy.test.mjs
npx playwright install chromium
DASHBOARD_PYTHON=../venv/bin/python npx playwright test --config playwright.local-setup.config.js
```

Onboarding tests use real local persistence and PDF extraction with a synthetic
AI response. Add coverage for validation, interrupted work, retry, and preservation
of saved data when changing setup. Do not start real job applications in tests.

Provider install commands follow the official [Claude Code setup guide](https://code.claude.com/docs/en/setup)
and [Kiro CLI guide](https://kiro.dev/docs/cli/). Review these when updating the installer.

Contributions to this project are provided under the MIT license. Third-party
dependencies and separately maintained components retain their own licenses.
