🟡 HOLD

# QUARRY: HOUND audit of apply (Naukri auto-apply bot and companions), update run after fixes

Target `/Users/apple/Desktop/apply`, HEAD `53b21e191b772c4e1ecd14c30cc14e57f6ae9a6e` on `main`, working tree dirty (243 entries at evidence time). Evidence is `hunt/evidence.yaml` (13 records, all status ok, 254 unique issues, 19 coverage gaps). Findings are `hunt/findings.yaml`: 35 findings (0 CRITICAL, 0 HIGH, 8 MEDIUM, 26 LOW, 1 INFO), 41 triage entries, 49 must-triage issues, 0 omitted. The gate `uv run --project hunt hound verify --findings hunt/findings.yaml --context hunt/evidence.yaml` exits 0, with computed and declared disposition both HOLD.

## Why HOLD and not SHIP

- ⚠️ The working tree is dirty: the fixes below are uncommitted, and other sessions are adding `pipeline/`, the four board bots, `froned-dashbord/` and `.research/` content in parallel. SHIP needs a clean recorded tree.
- ⚠️ There are 19 coverage gaps that no automated instrument exercises: Selenium against live sites, the external AI CLI, LaTeX, SMTP and IMAP, Telegram, launchd, `.kiro/`, the dashboard's Playwright suite, and the dirty tree itself.
- ✅ No critical-capable finding remains. The previous run's CRITICAL and HIGH items (certifi, lxml, Pillow, the `course/news.md` XSS, the agent's `secrets.env`, and the shared career-site password) are fixed, and the scanners and probe no longer report them.

Nothing reached BLOCK. Every instrument ran with status ok. Every liveness proof fired on its planted positive fixture and stayed clean on its clean fixture. The scanner databases are pinned: semgrep uses 459 frozen rules with a lock digest, trivy is pinned by its DB metadata digest, and gitleaks by its binary digest. Every negative control passes.

## What changed since the last QUARRY

| Flag | Area | Before | Now |
|---|---|---|---|
| ✅ | Dependencies | certifi CRITICAL, lxml HIGH, Pillow 45 advisories, RSS parsed with `xml.etree`, no lockfile | certifi 2026.10.19, lxml 6.1.3, Pillow 13.0.0, `defusedxml` for feeds, hashed `requirements.lock`; trivy-python EV-1bbaa7116166 reports 0 advisories |
| ✅ | Sandbox | 25 of 29 reproductions failing on their defect | 29 of 29 pass (sandbox record EV-6a31bebd5af4) |
| ✅ | Target tests | 632 of 633 | 759 of 759 (pytest-target EV-4601541ae38f) |
| ✅ | Must-triage | 158 | 49, all covered |

The bugs fixed in the working tree are grouped by lane below. Each one fixed by a passing reproduction is triaged in `hunt/findings.yaml` with the sandbox record it rests on.

- **core**: exact-only answer lookup; success and quota XPaths matched on own text; passport number and dates abstain; "total experience in X" is no longer answered with career years; an empty `DB_PATH` keeps the default database; an unrecognised `DRY_RUN` stays dry; `ALREADY_APPLIED` counts as applied; LLM text is flattened to one line before it reaches `answers.txt`.
- **linkedin**: a bad item URL is skipped; undated items are not fresh; a corrupt `state.json` is an error; the article URL replaces the model's link and stays on the last line, below the hashtags; front matter is single-line; malformed HN payloads are skipped; article fetches need a public http(s) host and stop at 2 MB; a browser error after Post ends the day as unconfirmed.
- **pipeline**: a settings failure surfaces; `--fresh --dry-run` keeps the checkpoint; corrupt progress files are refused, not reset; an empty study file no longer breaks the index; a missing resume is an error; contact lines are filtered more widely; `learn --done` is idempotent per day; `Memory` re-reads under `flock` before every write.
- **sites**: IMAP uses a verified TLS context and a timeout; a URL word alone is not a confirmation; hiring mailboxes match whole name parts; long addresses no longer crash file naming; an IMAP OSError is reported; the agent prompt forbids account creation when no password is saved; a Submit-click error is held back as "Submit was clicked"; Ctrl-C stops the agent process group; the shared password is typed only on recorded hosts; `secrets.env` lives outside the upload root.
- **web**: Runner notices a command that exited while a child kept the pipe open; bad JSON shapes answer 400; `days` is bounded; report paths are percent-decoded; Content-Length is checked; answer, fact and studied edits are serialised and atomic; SIGTERM and SIGHUP stop the running bot.
- **edge**: `esc()` escapes quotes and hrefs must be http(s); the launchd wrappers export a usable PATH; the status scripts read the real `data/` paths.

## Remaining findings (anchor-verified, static, not reproduced)

| Flag | Id | Severity | Class | Hypothesis | What |
|---|---|---|---|---|---|
| ⚠️ | HND-1273415786 | MEDIUM | secret | history | Personal application data (`Naukri autoapply jobs.ipynb` outputs, `application_answers.csv`, `naukriapplied.csv`) is still recoverable from git history |
| ⚠️ | HND-9cfa31bd81 | MEDIUM | injection | core-07 | Text-only claude CLI calls pass no tool restriction, and Kiro gets unscoped `fs_read`, while untrusted page text is in the prompt |
| ⚠️ | HND-2bdc3e03c7 | MEDIUM | supply | edge-02 (+web-02) | Course page loads floating-version jsdelivr scripts with no SRI and no CSP, on the control site's origin |
| ⚠️ | HND-53750a05b7 | MEDIUM | concurrency | core-06 | No lock between apply runs, the launchd profile updater and the control site |
| ⚠️ | HND-a48ef77827 | MEDIUM | lifecycle | core-04 | A tailored resume can stay on the Naukri profile when the upload errors after the file landed |
| ⚠️ | HND-ba78dc3aff | MEDIUM | logic | linkedin-05 | `--post` ignores the day's done flag, and the unconfirmed branch never records the URL |
| ⚠️ | HND-6a458e208d | MEDIUM | logic | sites-10 | A manual `--url` run records nothing in the ledger and never clears its `company_sites.md` entry |
| ⚠️ | HND-a9a78c75cb | MEDIUM | logic | boards-01 | Cutshort `second_apply` can click a related job's "Apply now" before navigation completes |

There are also 26 LOW findings and 1 INFO finding: installer and launchd robustness, board regex edges, `pipeline/links.py` link handling, dashboard UTC dates and caching, and similar items. All are listed with remediation in `hunt/findings.yaml`. The boards and dashboard items sit on code another session is actively writing.

## Instruments and liveness

| Flag | Instrument | Record | Issues | Liveness |
|---|---|---|---|---|
| ✅ | semgrep (frozen packs + custom) | EV-738e6d0a54d1 | 32 | clean and positive |
| ✅ | bandit | EV-a87b52f3522c | 88 | clean and positive |
| ✅ | ruff | EV-1a44e20a0120 | 28 | clean and positive |
| ✅ | shellcheck | EV-d5751e0800c6 | 2 | clean and positive |
| ✅ | gitleaks git history | EV-b6a2c46eb407 | 3 (course placeholders, false positive) | clean and positive |
| ✅ | gitleaks working tree | EV-6f1802198250 | 3 (same placeholders) | clean and positive |
| ✅ | trivy python environment | EV-1bbaa7116166 | 0 | clean and positive |
| ✅ | trivy node lockfile | EV-10a199273395 | 0 | clean and positive |
| ✅ | pytest target suite | EV-4601541ae38f | 0 (759 passed) | clean and positive |
| ✅ | history | EV-adb6019ab02d | 3 | clean and positive |
| ✅ | inventory | EV-d40e3a51e624 | 46 | clean and positive |
| ✅ | probe (8 lanes) | EV-80bab45a9df7 | 52 (49 verified, 36 rejected, 3 lane failures) | clean and positive |
| ✅ | sandbox reproductions | EV-6a31bebd5af4 | 0 (29 passed) | clean and positive |

## Caveats

- ⚠️ "Fixed" for the 29 reproduced hypotheses means the reproduction now passes. For the static ones it means the code changed as described and the anchor review was redone by hand, not that a test proves it. The triage reasons in `hunt/findings.yaml` say which is which.
- ⚠️ One reproduction was changed. pipeline-04 used to demand that a corrupt `.memory/progress.json` be read back with its history. The fix refuses the damaged file and leaves it untouched on disk, so the test now accepts either outcome. That is a deliberate fail-closed choice, and `python3 -m pipeline` exits with a config error naming the file.
- ⚠️ Two existing LinkedIn tests asserted hashtags after the URL. That contradicts the README and the writer's own lint, so they now assert hashtags above the URL.
- ⚠️ Harness changes in this run:
  - a `node-test` instrument for `node --test` scripts;
  - `tsc` and `oxlint` are owed only to projects that have a tsconfig or oxlint config;
  - a Playwright test script is a named gap;
  - `requirements.lock` counts as a lockfile;
  - instruments start with default SIGINT handling. Without that, `test_stop_interrupts_the_run` failed only when hound ran as a background job.
- ⚠️ Three dashboard hypotheses (dashboard-01 to 03) were pruned as superseded, because the dashboard was rebuilt mid-run. The core, sites and web lanes failed their first attempt, and that is recorded as lane-failure issues. The five fix lanes timed out without landing changes, so the fixes were made directly.
- ⚠️ Earlier caveats still apply: integrity is self-consistency plus digests of the raw artifacts, `hunt/results/` is volatile and sensitive, and the sandbox runs Python 3.13.9 against a 3.12.13 target venv.

## Next steps

1. Review and commit the working tree (`git diff`), then rerun `uv run --project hunt hound run` and `hound verify`. With a clean tree, the remaining ceiling is the coverage gaps.
2. Fix the 8 MEDIUM findings above. The cheapest are SRI-pinned course scripts (edge-02), a `--disallowedTools` list for text-only CLI calls (core-07), and an flock shared by apply and the updater (core-06).
3. Purge the personal CSVs and notebook outputs from history with `git filter-repo`, if the remote is shared. This is destructive, so coordinate first.

The backlog is regenerated in `hunt/TODO.md`, and the runbook is `hunt/RUNBOOK.md`.
