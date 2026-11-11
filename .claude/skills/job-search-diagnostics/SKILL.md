---
name: job-search-diagnostics
description: Use when a job seeker running Morrow asks why applications get no calls, shortlists or replies, or asks to audit the application funnel, the mailbox, or a job board's applied/inbox pages. Runs the read-only `python3 -m diagnose` audit, reads its report, and turns each ranked cause into a concrete change (env value, code, saved answer, resume line, skill). Never applies, sends or edits accounts.
---

# Job-search funnel diagnostics

## When to use

The person says some form of "I applied to N jobs and nobody called", "no shortlist", "is something broken",
or asks what to fix in the bot, resume or skills. Do not guess from the ledger alone: the answer is in
four places at once (ledger, mailbox, each board's own pages, the resume against the postings) and the
audit reads all four.

## Run

```bash
python3 -m diagnose                      # everything: local files, Gmail (IMAP), five boards (saved profiles)
python3 -m diagnose --skip-browser       # when the dashboard or a bot holds the browser profiles
python3 -m diagnose --skip-mail          # when GMAIL_APP_PASSWORD is not set
python3 -m diagnose --sites hirist,wellfound --days 60 --no-llm
```

Output: `user/reports/<date>/diagnostics.md` (read this), `diagnostics.json` (numbers), and
`diagnostics/<site>-<page>.txt` (the visible text of each board page, the evidence).

Preconditions and their fixes:
- `locked` for a site: that browser profile is open elsewhere (dashboard, running bot). Stop it or skip the site.
- `needs_sign_in`: sign in once via the dashboard Connections page, re-run.
- Mail not read: either sign in to Google once in a browser profile the audit can open (Naukri, startups or
  LinkedIn profile; it then reads Gmail's list pages without a password), or set `GMAIL_APP_PASSWORD` /
  `REPLY_INBOXES=address:app-password` for IMAP.
- "Model did not answer": `LLM_BACKEND=claude-cli` shells out to `claude -p`, which can hang; the audit
  drops the model after two silent calls and says so in "How each step was checked". Run with `--no-llm`
  or set `LLM_BACKEND=anthropic` with a key. The dashboard tab **Why no replies** shows the same report.

## What the model does, and how each step is checked

Every model step is recorded as research → verify → check → execute (report section "How each step was
checked", JSON key `trail`). A step whose check fails keeps the rules' result.
- Targeted Gmail searches: rule-made (positive subject words, Cutshort replies, Naukri non-alerts, the
  companies applied to) plus up to 6 model-proposed; each is lint-checked (operator allow-list, balanced
  quotes, `newer_than` capped, `in:anywhere`), dropped when it returns over 300 rows.
- Verification of the rules' verdicts: batches of 25 (search hits and rule positives first); a batch is
  trusted only when it agrees with the rules on positive-or-not at 60%+; a verdict changes only above 70%
  confidence. Numbers: `mail.verification` (agreement_kind, agreement_positive, changed, promoted, demoted).
- Review of the causes: the model reads a digest of the numbers; agreement moves confidence ±; an added
  cause is kept only when its evidence quotes a number present in the digest, capped at medium severity.

## Read the report in this order

1. **Verdict** — did positive mail or board messages exist? If yes, the first job is answering them, not
   changing code.
2. **Root causes** — ranked critical > high > medium. Each has Evidence (numbers you can re-query) and
   Fix (kind: env / code / answers / profile / resume / skill / manual) and Where (files).
3. **Platform account pages** — the board's own statuses. Hirist shows views/applicants/recruiter actions
   per job; Cutshort and Wellfound show pending/shortlisted/rejected; Instahyre shows who viewed and the
   inbox. A questionnaire or assessment request sitting there is a live lead.
4. **Resume vs the postings** — terms the applied postings ask for and whether the resume says them.

## Turning a cause into a change

| Cause id | Change |
|---|---|
| `unanswered-messages` | Open each board inbox listed, finish the questionnaire/assessment today. Then add a read-only inbox stage per board (pattern: `diagnose/platforms.py`, `cutshort_bot/questionnaires.py`). |
| `low-fit` | `.env` `MIN_SCORE=65`; make every `<board>_bot` honour `settings.min_score` like `naukri_bot/cli.py`. |
| `title-mismatch` | `.env` `EXCLUDE_TITLES=` add Senior, Sr, Manager, Director, Data Scientist, React Native, DevOps, SRE, Test, III; run `ranking.excluded_title` in every lane. |
| `experience-filter` | `MAX_YEARS_OVER=0`; keep years+months identical on every board and in `profile.yaml`. |
| `bad-answers` | Fix location answers in `user/inputs/answers.txt`; make `common/answers.py` refuse Others/Remote/Any for location questions. |
| `volume` | `TARGET_APPLICATIONS=20`, `DAILY_QUOTA=25`; enable per-application resume tailoring. |
| `resume` / `skills-to-add` | Headline = job title + stack + years; delete mock/simulated/prototype/beta wording; one metric per bullet; add the missing in-demand terms you truly have. |
| `profile-inconsistent` | Same notice period, experience and city on every board. |
| `spam` / `naukri-mail-missing` | Gmail filters; Naukri Settings > Communication address and toggles. |

## Applying the fixes automatically

`python3 -m diagnose.autofix` (pipeline stage `autofix`, dashboard button **Fix it now**) reads the latest
`diagnostics.json` and acts on it; `autofix.md` records every step as research → verify → check → execute.

| Fix kind | Who applies it | Guard |
|---|---|---|
| `env` / `profile` settings the causes spell as `KEY=value` | Morrow itself, in `.env` | only to the stricter value; old value kept in a comment; copy under `autofix/` |
| `answers` (location answers saying Others/Remote/Any) | Morrow itself, from `profile.yaml` | refuses when the profile has no city; cached rows deleted so the bot re-learns |
| `code` causes and the plan's code lines | a coding CLI: opencode → claude → kiro (`AUTOFIX_CLI`, `--cli`) | may edit bot packages and tests only; tests must not get worse; no test deleted; otherwise every change reverted; never committed |

Dry run with `--dry-run` (or `AUTOFIX=false` in `.env`); it reads neither the tree nor the test baseline and writes `autofix.dry-run.md`, never `autofix.md`. A CLI that hangs usually has a stale proxy in its
environment; the report lists `ANTHROPIC_BASE_URL`-style variables that were set.

## Benchmarks to quote

Cold applications → interview 2–3% (meta-analysis of 27 studies); Ashby Q1 2026 technical 3.6%;
Naukri shortlist 2.78% vs LinkedIn 15.2%, Indeed 4.7% (IJCOPE 2(10), doi 10.55041/ijcope.v2i10.143);
keyword match <50% → 0.9% callback, ≥85% → 11.4% (Jobloo). Expected from N submissions: 0.02N–0.03N
interviews. Zero at N>200 is a broken funnel, not variance.

## Job-fit rubric (adapted from art2url/career-agent-skills `job-fit-analyzer`, MIT)

Score a posting before applying: required-skill coverage ≥70% (the posting's own words appear in the
resume), experience within the stated band (never more than MAX_YEARS_OVER under), title level matches
(no Senior/Lead for <3 years), location or remote policy matches a real city on the profile, applicant
count on the board < 300 where shown. Fewer than four of five → do not apply; spend the slot on a closer
posting or a direct mail to a named recruiter from `user/inputs/job_contacts.jsonl`.

## Guardrails

Read-only. The audit never clicks Apply, never sends mail, never edits a board profile. Do not change
`.env`, answers or the resume from inside this skill without the person's explicit go-ahead; present the
Fix list and let them choose.
