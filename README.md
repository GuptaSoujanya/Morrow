<div align="center">

# Morrow

### **Autonomous Learning-First Career Workspace & Multi-Platform Application Engine**
**Local-First Architecture · Playwright Multi-Board Automation · LaTeX Resume Tailoring · Interview Prep**

[Features](#what-morrow-does) &nbsp;•&nbsp; [Quick Start](#quick-start) &nbsp;•&nbsp; [Dashboard](#the-dashboard) &nbsp;•&nbsp; [Architecture](#how-each-feature-works) &nbsp;•&nbsp; [SoujanyaLab](https://www.soujanyalab.in/)

<br/>

[![Version](https://img.shields.io/badge/Release-v1.0.0-00F2FE?style=flat-square&logo=github)](https://github.com/GuptaSoujanya/Morrow/releases/tag/v1.0.0)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Linux-blueviolet?style=flat-square&logo=apple)](https://github.com/GuptaSoujanya/Morrow)
[![Tests](https://img.shields.io/badge/Tests-1641%20passing-39D353?style=flat-square&logo=pytest)](https://github.com/GuptaSoujanya/Morrow)
[![Local-First](https://img.shields.io/badge/Architecture-Local--First%20%26%20Private-FFD700?style=flat-square)](https://github.com/GuptaSoujanya/Morrow)
[![Supported Boards](https://img.shields.io/badge/Boards-Naukri%20%7C%20Wellfound%20%7C%20Instahyre%20%7C%20Cutshort-orange?style=flat-square)](https://github.com/GuptaSoujanya/Morrow)

</div>

<br/>

**A learning-first career workspace that runs on your own computer.** Morrow studies with you every
morning, keeps your job-board profiles the way a recruiter should see them, tailors your resume per
posting, applies to the jobs that actually match you on Naukri, Hirist, Instahyre, Cutshort, Wellfound
and employers' own career sites, drafts recruiter emails and a daily LinkedIn post, and writes one
report a day of everything it did and everything it left for you.

Built by Soujanya Gupta at [SoujanyaLab](https://www.soujanyalab.in/). **Free beta:** every tool runs
locally with no account, subscription or payment. Your data never leaves your machine except through
the browsers you sign in to and the AI CLI you already use.

- **Nothing is reported as done unless it was verified on the page.** Login, apply, questionnaire
  submission, profile saves, resume uploads and LinkedIn posts each have an explicit read-back step.
- **Nothing about you is invented.** Screening answers, profile text, cover letters and emails come
  only from your resume, your facts file and your own answers. A question none of them answer is
  written to a file for you instead of guessed.
- **Every run leaves a record**: an SQLite ledger, a per-day report with links, the full log of each
  run, and a folder per tailored resume holding exactly what a recruiter received.

> Status on 27 Oct 2026: `pytest tests` runs 1641 tests (1637 passed, 3 skipped, 1 failing on a
> half-written briefing day on this machine, not on code). Every command below answers `--help`.
> See [Verifying the install](#verifying-the-install) and [Known limits](#known-limits).

---

## Contents

1. [What Morrow does](#what-morrow-does)
2. [Requirements](#requirements)
3. [Quick start](#quick-start)
4. [The dashboard](#the-dashboard)
5. [Command reference](#command-reference)
6. [How each feature works](#how-each-feature-works)
   - Getting set up: [Onboarding](#onboarding), [LLM backend](#llm-backend)
   - Applying: [Naukri](#applying-on-naukri), [Scoring and ranking](#job-scoring-and-ranking),
     [Early Access](#early-access-on-naukri), [The application ledger](#the-application-ledger),
     [Company websites](#company-websites-apply-on-company-site), [Browser agent](#browser-agent-claude-code-takes-over-a-stuck-site),
     [Other job boards](#other-job-boards-hirist-instahyre-cutshort-wellfound)
   - Your profile and resume: [Profile updater and review](#keeping-the-naukri-profile-recently-updated-and-reviewing-it-everywhere),
     [Resume and tailoring](#your-resume-edit-the-latex-the-bot-does-the-rest), [Your data folder and answers](#your-data-folder-the-files-you-edit)
   - Outreach: [Cold emails](#cold-emails-to-recruiters-drafts-only), [LinkedIn](#linkedin-one-post-a-day)
   - Learning: [The 90-day study plan](#the-90-day-study-plan), [Daily briefings](#daily-briefings),
     [Resume study notes](#resume-study-notes), [The course](#the-course-prepforge), [DSA practice and the code runner](#dsa-practice-and-the-code-runner),
     [AI practice papers and weekly exams](#ai-practice-papers-and-weekly-exams), [Progress, streaks, XP and badges](#progress-streaks-xp-and-badges),
     [Saved research library](#saved-research-library)
   - Running and watching: [Daily report](#daily-report), [The morning pipeline](#the-morning-pipeline),
     [Action inbox](#action-inbox), [Connections and browser sessions](#connections-and-browser-sessions),
     [Activity dock](#activity-dock-live-logs-browser-previews-and-stop), [Launchpad, Insights, Reports, Data hub, Preferences](#launchpad-insights-reports-data-hub-and-preferences),
     [Alerts and run logs](#telegram-alerts-and-run-logs)
   - Platform: [Accounts mode and the account API](#accounts-mode-and-the-account-api), [HOUND security audit](#hound-the-security-audit-harness)
7. [Configuration: every `.env` key](#configuration-every-env-key)
8. [Your data: repos and folders](#your-data-repos-and-folders)
9. [Documents in this repo](#documents-in-this-repo)
10. [Verifying the install](#verifying-the-install)
11. [Troubleshooting](#troubleshooting)
12. [Known limits](#known-limits)
13. [Legacy scripts](#legacy-scripts)
14. [Disclaimer](#disclaimer)

---

## What Morrow does

| Area | Feature | Where |
|---|---|---|
| **Learn** | A 90-day study plan cut from the PrepForge interview course (DSA, system design, full stack, ML/GenAI, behavioural), one day at a time, with the day's course sections quoted in full | `python3 -m pipeline learn`, dashboard **Learning** |
| | Daily briefings researched on the web by the `claude` and `kiro` CLIs: today's goal, a system-design deep dive, 5 papers, tech news, companies hiring | `python3 -m pipeline`, `user/research/daily/<date>/` |
| | Resume-topic notes: what your own resume says you know, turned into study material | `research:resume` stage |
| | DSA practice: 22 topics, a 72-problem sheet, an in-browser code runner (Python, JavaScript, C++) in an OS sandbox, AI-generated daily papers and weekly exams | dashboard **Learning** |
| | Progress that survives restarts: course chapters read, documents read, DSA days, plan days; streaks, XP, a year heatmap and badges | `user/memory/learning.json`, dashboard **Learning > Progress** |
| | A saved research library: every briefing, paper list, news brief, company note and study file, searchable, with a reader that marks what you read | dashboard **Learning > Library** |
| | The PrepForge interview course (5 tracks, 43 chapters) as a docsify site with search, served by the dashboard or on its own | `database/course/`, `python3 database/course/serve.py` |
| **Profile** | One profile plan made from your resume and held to a recruiter's rubric; written to Naukri, LinkedIn, Hirist, Instahyre, Cutshort and Wellfound; every planned value verified on the reloaded page and repaired when it did not land | `naukri_bot.update_profile --review`, `<board>_bot.update_profile`, `common.profile_plan`, `common.profile_record` |
| | Keep the Naukri profile "recently updated" three times a day; re-upload the resume when it changes | `naukri_bot.update_profile --if-due`, launchd |
| **Resume** | LaTeX resume compiled to PDF; tailored per application (skills reordered, bullets reordered, summary rewritten, nothing added); uploaded to the profile and restored after the run | `common.resume`, `TAILOR_RESUME=true` |
| **Apply** | Naukri: resume-derived keyword searches plus the recommended feed, scored by an LLM against your resume and posting age, applied in that order until the 50/day quota is spent; Early Access interest for free | `python3 -m naukri_bot` |
| | Hirist, Instahyre, Cutshort, Wellfound: the same loop on each board's feed and search | `python3 -m <board>_bot`, `sites_bot.platforms` |
| | Employer career sites (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Workday, iCIMS, Taleo, ...): sign in or sign up, fill the form page by page, submit only when complete and confirmed | `sites_bot.external`, `EXTERNAL_APPLY=true` |
| | A browser agent (Claude Code over Playwright MCP) that takes over a stuck site in the same Chrome window | `sites_bot.browser_agent`, `BROWSER_AGENT=true` |
| **Answer** | Screening questions answered from your `answers.txt`, then your profile, then the model with quotes; the AI fills blanks in your own files from quoted lines; honest judgements (0 years, N/A, Other) with the reason written next to them | `common.assist`, `JUDGE_ANSWERS` |
| **Outreach** | Cold emails to recruiters whose address a posting published, written from your resume, saved as `.eml` drafts and Gmail drafts, never sent | `sites_bot.cold_email` |
| | One LinkedIn post a day about a fresh article on your topics, in your voice, with an image card and a PDF carousel, verified at every step | `python3 -m linkedin_bot` |
| **Report** | `user/reports/<date>/report.md`: applied, tried, left for you, profile slots, resumes tailored, LinkedIn, AI edits with quotes, every run's log | `common.report` |
| **Run it all** | One resumable morning pipeline: learn, profiles, applications, briefings; every site in its own process and Chrome profile, or in its own Docker container with its screen in your browser | `python3 -m pipeline`, `docker compose` |
| **Dashboard** | All of the above as buttons on http://127.0.0.1:8100, with live logs, browser previews, an action inbox, applications ledger, insights, data hub and the course reader | `scripts/morrow start` |
| | Connections: one card per site (Naukri, LinkedIn, the four boards, Google) to open a sign-in window, check it, switch account or disconnect, without ever typing a password | dashboard **Connections** |
| | Every bot's screen while it runs, with the option to type into it; a stop button; every run's log kept | **Activity dock** |
| **Alerts** | A Telegram message when a scheduled run fails or a LinkedIn draft is ready for approval | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| **Accounts** (optional) | Sign-in, email verification, Free / Plus / Pro plans with Razorpay or Stripe, an admin screen with an audit log, workspace import and export | [Manual developer setup](froned-dashbord/README.md#optional-accounts-mode), `morrow-api/` |
| **Audit** | HOUND, an adversarial security audit harness: SAST, secrets, supply chain, container and test instruments with pinned databases, writing a gated verdict to `QUARRY.md` | `uv run --project hunt hound run` |

---

## Requirements

| | Needed for |
|---|---|
| **macOS** | Everything is tested on macOS. Linux works for the bots and Docker; the launchd schedules are macOS only. |
| **Python 3.11+** (3.12 tested) | all bots |
| **zsh** | the `morrow` launcher |
| **Google Chrome** | all bots (ChromeDriver is fetched by `webdriver-manager`; Edge also works) |
| **Node 22.19+** | the dashboard (`npm start`) and the browser agent (`npx @playwright/mcp`) |
| **`claude` CLI** signed in | the default LLM backend (no API key needed); briefings, profile agent, browser agent, LinkedIn writer. `kiro-cli` is optional and used alongside it. |
| **GitHub CLI (`gh`)** signed in | `scripts/setup_user.sh` creates your private data repo |
| **tectonic** (`brew install tectonic`) | compiling the LaTeX resume (`pdflatex` or `xelatex` also work) |
| **Docker Desktop** | optional: one container per site, and the accounts mode API |
| **sqlite3**, **pdftotext** (Poppler) | `scripts/sync_data.sh` checkpoints the ledger; the dashboard reads PDF resumes |

---

## Quick start

```bash
git clone --recurse-submodules https://github.com/GuptaSoujanya/Morrow.git
cd Morrow
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.lock          # exact, hashed versions (or requirements.txt)

./scripts/setup_user.sh                   # 1. your private data repo -> user/, the shared course -> database/,
                                          #    .env created from .env.example with both paths written in
python3 -m pipeline onboard               # 2. your resume (PDF, .tex or .txt) + the facts a resume cannot hold
                                          #    -> user/inputs/profile.yaml, persona.yaml, answers.txt, resume/base.tex, .env

python3 -m naukri_bot --dry-run           # 3. rank the jobs it would apply to; clicks nothing, spends no quota
scripts/morrow install                    # 4. install the command in ~/.local/bin
morrow start                              # 5. start the dashboard at http://127.0.0.1:8100
```

The first real run of each bot opens a visible Chrome window so you can finish the site's OTP or
verification code; the session is then saved under `user/browser/` and later runs skip the login.
From here, either press buttons in the dashboard or run the commands below. `python3 -m pipeline`
runs the whole morning (study material, profiles, applications, briefings) and can be re-run any
time to continue where it stopped.

---

## The dashboard

Run `scripts/morrow install` once from the repo root to create `~/.local/bin/morrow`, a symlink to this
checkout's launcher. With `~/.local/bin` on your `PATH`, run `morrow start` from any directory.
If the command is not found, add `export PATH="$HOME/.local/bin:$PATH"` to your shell configuration.
You can also use `scripts/morrow start` directly from the repo root without installing the command.

`morrow start` builds the frontend and starts the Python backend together in the background on
**http://127.0.0.1:8100**, bound to localhost only. It waits for `/api/session` to confirm the free beta
is ready before reporting success. You can close the terminal afterward. The launcher always uses
beta mode, even when `MORROW_MODE=accounts` or old account settings are present in the environment.

The dashboard (`froned-dashbord/`, built on the `web/` bot engine) launches the same `python3 -m ...`
commands documented below, shows a command preview before each run, streams every run's log live
and keeps run history.

| Command | Does |
|---|---|
| `scripts/morrow install` | create the `~/.local/bin/morrow` symlink |
| `morrow start` | build and start the free beta on :8100; reuse this launcher's running dashboard |
| `morrow start --port 8116` | start the free beta on a different local port |
| `morrow stop` | stop only the dashboard process group owned by this launcher |
| `morrow restart` | stop the owned dashboard, rebuild the frontend and start again |
| `morrow status` | check this launcher's dashboard and whether it is ready |
| `morrow logs` | follow `reports/morrow/dashboard.log` in this checkout |

All commands also work as `scripts/morrow <command>` from the repo root. An unrelated process on
port 8100 is reported as a conflict; the launcher does not take it over or stop it. It does not start
or stop Docker, PostgreSQL, or the account API. `morrow start accounts` is rejected; accounts mode
uses the [manual developer setup](froned-dashbord/README.md#optional-accounts-mode).

For a foreground development server: `cd froned-dashbord && npm install && npm start -- --mode beta --port 8100`
(it runs `venv/bin/python server.py`; set `DASHBOARD_PYTHON` to use another interpreter). Stop this
manually started server with Ctrl+C in its terminal; the launcher manages only its own process group.

### Pages

| Page | What it does |
|---|---|
| **Launchpad** (`#/overview`) | 7/14/30-day and all-time metrics, activity graph, recent attempts, shortcuts to every agent, follow-ups, saved flow progress, CSV export |
| **Bot Crew** (`#/bots`) | 18 agents with search and filters: applications (naukri, hirist, instahyre, cutshort, wellfound, company sites), profile updates (naukri, linkedin, hirist, instahyre, cutshort, wellfound), writers (linkedin post, cold email, resume), research (learn, brief, resume notes). Run one, or select up to 8 and **Run selected**. **Run in background** hides the Chrome windows. |
| **Flows** (`#/pipeline`) | Today's pipeline checkpoint refreshed every 5 s, **Resume workflow**, **Retry this stage**, full run or one group or stage, CLI choice, agent concurrency, date |
| **Action inbox** (`#/todo`) | Every question the bots could not answer and every blank fact in your profile, answered in place |
| **Applications** (`#/records`) | The ledger: search, discovered jobs vs attempts, filter by board, outcome and date, sort by score |
| **Learning** (`#/learning`) | Today's checklist, DSA practice (22 topics, code editor with run and submit), the 72-problem DSA sheet, AI practice papers and weekly exams (needs `claude` or `kiro`), resume topics, the full course with chapter completion, saved research library, progress with heatmap, streaks, XP and badges |
| **Data hub** (`#/data`) | Every file the bots wrote, searchable, with inline PDF preview and download |
| **Insights** (`#/analytics`) | Funnel, outcomes, score and platform comparisons, CSV export |
| **Reports** (`#/reports`) | Any day's report, generated or refreshed on demand |
| **My profile & files** (`#/files`) | Structured editor for `profile.yaml`, source editor for every input file, the agent answer sheet, Preferences with masked secrets. Saves are revision-checked and backed up to `user/inputs/backups/`. |
| **Connections** (`#/connections`) | Per site (Naukri, LinkedIn, Hirist, Instahyre, Cutshort, Wellfound, Google): Open sign-in, Check sign-in, Close, Change account, Disconnect. Also **Your private data repo → Connect repo**, which runs `scripts/setup_user.sh` with your `gh` login. |
| **Bot controls** (`#/naukri`, `#/boards`, `#/sites`, `#/profile`, `#/linkedin`, `#/linkedin-profile`, `#/outreach`, `#/resume`) | The options form for each agent |
| **Schedules** (on Bot Crew, Naukri and LinkedIn pages) | Enable or disable the two launchd jobs (profile refresh, LinkedIn post). macOS only. |
| **Preferences** (`#/setup`) | The `.env` editor with search and masked secrets; your private data repo's status and sync; **Run checks** (the test suite) and **Install requirements**; a link to the raw settings file |
| **Setup checklist** (`#/onboarding`) | Profile details, resume (a saved PDF or an upload of up to 20 pages with selectable text), the accounts you use, the sign-in check and the private data repo |
| **Plans & billing, My account, Administration** (`#/plans`, `#/account`, `#/admin`) | Accounts mode only, see [Accounts mode and the account API](#accounts-mode-and-the-account-api) |
| **Activity dock** (bottom right) | Progress, Agents and Browsers tabs: live logs, Copy, Stop, a preview of each run's Chrome, sign-in windows, **Answer sheet updated** notifications (desktop alerts opt-in) |

Keyboard: the digits **1** to **9** jump to the first nine sidebar items, **Cmd+K** (Ctrl+K) opens
workspace search, Left and Right switch Activity dock tabs and Escape collapses it, and the charts
answer the arrow keys, Home and End. Launchpad and Insights export the daily series as
`job-hunt-<start>-<end>.csv`. The dashboard is light-themed only; there is no dark mode. Learning
sidebar state and the 32 workspace avatars live in your browser's local storage, nowhere else.

**Free beta vs accounts mode.** The beta has no login and every page is open; account, plan and admin
links are disabled. Accounts mode is a separate [manual developer setup](froned-dashbord/README.md#optional-accounts-mode):
start the `morrow-api/` backend (FastAPI, PostgreSQL), then use `npm start -- --mode accounts` inside
`froned-dashbord/`. It provides local accounts with Argon2 passwords, email verification, Stripe and Razorpay plans (Free,
Plus ₹499, Pro ₹999), an admin **People & access** screen with an audit log, and a setup wizard whose
**Finish setup** copies the profile and resume from the account into `user/`. Only the account named in
`MORROW_WORKSPACE_OWNER_EMAIL` can run the bots; other accounts get read-only, plan-gated views.
Per-user bot execution is not implemented. See [froned-dashbord/README.md](froned-dashbord/README.md)
and [morrow-api/README.md](morrow-api/README.md).

---

## Command reference

Every command runs from the repo root with the venv active (or as `venv/bin/python -m ...`). Every
module accepts `--env PATH` to read another `.env` and `-v` / `--verbose` for debug logging unless
noted. Exit codes everywhere: **0** ok, **1** configuration or profile problem, **2** a login needs you
at the keyboard (run again with a visible window), **3** the run failed.

### Setup and data

| Command | Does |
|---|---|
| `./scripts/setup_user.sh` | Creates `<you>/Morrow-user-<you>` (private) on GitHub from the Morrow-user template and clones it to `user/`; clones Morrow-database to `database/`; copies `.env.example` to `.env` if missing and writes `MORROW_USER_DIR` and `MORROW_DATABASE_DIR` into it. `./scripts/setup_user.sh owner/repo` uses a user repo that already exists. Needs `gh auth login`. |
| `./scripts/sync_data.sh` | Checkpoints `user/db/naukri_bot.db` (WAL folded in), commits everything in `user/` as "Record the bots' work as of <stamp>", pulls with rebase and pushes to your private repo. No flags. |
| `python3 -m pipeline onboard` | Interactive onboarding (below). Forwards only `--env`. |
| `python3 -m common.onboard` | The same, with flags: `--resume PATH` (.pdf, .tex, .txt or .md; asked for when omitted), `--answers FILE` (a JSON object of answers keyed by field name), `--yes` (no prompts; the model's reading and the defaults stand), `--user-dir DIR` (default `MORROW_USER_DIR` or `user/`), `--env PATH` (the `.env` to **write**, default the repo's). No `-v`. |

### The morning pipeline

```
python3 -m pipeline [run|continue|status|learn|check|onboard] [options]
```

| Command | Does |
|---|---|
| `run` (default) | Run today's stages, skipping the ones already done; failed ones are retried |
| `continue` | Same as `run` |
| `status` | Print today's checkpoint (stages, attempts, board profiles, applications) |
| `learn` | Only the study-day stage; with `--done`, mark today's study day finished |
| `check` | Check the day's study material (90-day plan, course links, resume notes, briefing files, links); exits 3 when something is missing or broken |
| `onboard` | First-run onboarding |

| Option | Effect |
|---|---|
| `--fresh` | start today over instead of continuing |
| `--only STAGE` | run only this stage or group; repeatable (`--only learn --only brief`) |
| `--skip STAGE` | leave this stage or group out; repeatable |
| `--redo` | run the `--only` stages again even when done today |
| `--dry-run` | pass `--dry-run` to every bot and record nothing |
| `--cli both\|claude\|kiro` | which AI CLI the briefing agents use (default both: both draft, claude merges; `PIPELINE_AI_CLI`) |
| `--agents N` | briefing agents at the same time (default 6, all of them) |
| `--bots N` | sites at the same time, each in its own process and Chrome profile (default: every site at once; `1`: one after another; `PIPELINE_BOTS`) |
| `--containers` | every site in its own Docker container (`PIPELINE_CONTAINERS=1`) |
| `--no-watch` | with `--containers`, do not open the page showing the bots' screens |
| `--date YYYY-MM-DD` | the day to run, check or show |
| `--done` | with `learn`: mark the day finished |

Stage names: `learn`, `profile:naukri`, `profile:linkedin`, `profile:<board>`, `apply:naukri`,
`apply:<board>` (one per board in `PLATFORMS`), `research:resume`, `brief:goal`, `brief:system-design`,
`brief:papers`, `brief:tech-news`, `brief:companies`. Group names for `--only` / `--skip`: `profile`,
`apply`, `research`, `brief`, `learn`.

### Naukri

```
python3 -m naukri_bot [options]
```

| Flag | Effect |
|---|---|
| `--dry-run` | rank and report, never click Apply; zero quota |
| `--limit N` | apply to at most N jobs this run (never more than the remaining quota) |
| `--min-score S` | relevance floor 0-100 (default 55) |
| `--max-days-old D` | ignore postings older than D days (default 7; unknown age is kept) |
| `--keywords K1,K2` | override the resume-derived search keywords |
| `--location LOCATION` | override the search location |
| `--headless` | no window (login is more likely to be challenged) |
| `--answer-mode auto\|propose\|ask` | auto: submit grounded answers; propose: log what it would answer, then skip; ask: pause for a human |
| `--llm-backend claude-cli\|kiro-cli\|anthropic\|none` | which LLM scores jobs and answers questions |
| `--early-access` | share interest on Naukri's Early Access roles before applying (saved recruiter searches; costs no apply quota) |
| `--early-access-limit N` | Early Access roles per run (default 20) |
| `--early-access-only` | share Early Access interest and stop; no search, no applications |

```
python3 -m naukri_bot.update_profile [options]
```

| Flag | Effect |
|---|---|
| (none) | toggle the trailing dot on the resume headline once, now; Naukri counts it as an update |
| `--dry-run` | log in, open the headline editor, read it, change nothing (ignores `DRY_RUN` in `.env`) |
| `--if-due` | only act when one of the daily slots (09:00, 13:30, 18:30) is due and not yet done; what launchd runs |
| `--review` | after the headline, the Playwright browser agent compares the whole profile with your facts, fixes what is missing or out of date, saves, and verifies every planned value on the reloaded page |
| `--score` | read the live profile and report how much of the plan is on it, plus Naukri's completeness figure and the resume's ATS score; changes nothing, spends no agent budget, records the score in the index |
| `--headless` | no window |

### Other job boards

```
python3 -m hirist_bot | instahyre_bot | cutshort_bot | wellfound_bot [options]
python3 -m sites_bot.platforms --site hirist [--site instahyre ...] | --site all [options]
```

| Flag | Effect |
|---|---|
| `--site NAME` | (`sites_bot.platforms` only) board to work on; repeat for several; `all` is every board; default `PLATFORMS` in `.env` |
| `--limit N` | applications per board this run (default `PLATFORM_LIMIT`, 10) |
| `--dry-run` | collect, rank and open each job, click nothing |
| `--update-profile` | refresh the board profile through the browser agent, then apply |
| `--profile-only` | refresh the board profile and apply nowhere |
| `--create-profile` | when the board shows no session, sign in or create the account and the profile first |

`python3 -m <board>_bot.update_profile` is `<board>_bot --profile-only` and accepts the same flags.

### Employer career sites, browser agent, cold email

```
python3 -m sites_bot.external [options]
```

| Flag | Effect |
|---|---|
| `--url URL` | the application page to work on (a `company_sites.md` Site link) |
| `--retry-pending` | try every entry in `user/inputs/company_sites.md` again, skipping those that wait on your answers or a code from your inbox |
| `--title`, `--company` | for the tailored resume and the records |
| `--dry-run` | fill the form and find Submit, never click it; the window stays open |
| `--no-tailor` | attach the base resume instead of a tailored one |
| `--google-login` | sign the bot's browser in to `GOOGLE_EMAIL` (types `GOOGLE_PASSWORD` when set, waits 10 minutes for a passkey, phone prompt or code); nothing else happens |
| `--headless` | no window |

```
python3 -m sites_bot.browser_agent --url URL [options]
```

| Flag | Effect |
|---|---|
| `--url URL` | (required) the page to start on |
| `--title`, `--company` | for the records and the tailored resume |
| `--task TEXT` | a specific job for the agent instead of finishing the application; prints a JSON report |
| `--dry-run` | fill the application, never click its final Submit |
| `--no-resume` | do not hand the agent a resume PDF |

Needs Node (`npx @playwright/mcp`) and the `claude` command on `PATH`.

```
python3 -m sites_bot.cold_email [options]
```

| Flag | Effect |
|---|---|
| (none) | draft emails to every published address found in today's records |
| `--scan-naukri` | also open recent well-scored Naukri job pages and read any address they show |
| `--days N` | how far back `--scan-naukri` looks (default 7) |
| `--pages N` | most Naukri pages `--scan-naukri` opens (default 30) |
| `--limit N` | drafts this run (default `COLD_EMAIL_LIMIT`, 10) |
| `--to ADDRESS --company C --title T --url U` | one draft to one address about one posting |
| `--dry-run` | print the emails, save nothing |

### Resume, answers, report, profile plan

| Command | Does |
|---|---|
| `python3 -m common.resume` | compile `user/resume/base.tex` to `user/resume/out/base/<Name>_Resume.pdf` |
| `python3 -m common.resume --upload [--headless]` | compile, put the PDF on the Naukri profile, verify the resume card shows the new file with today's date |
| `python3 -m common.resume --tailor posting.txt --title "AI Engineer" --company "Acme"` | tailor the resume to a pasted posting; result in `user/resume/out/tailored/<Company - Role>/` |
| `python3 -m common.assist [--dry-run]` | the AI fills blank `A:` lines in `answers.txt` and `null` facts in `profile.yaml` from quoted lines in your own files; `--dry-run` shows what it would fill |
| `python3 -m common.report [--date YYYY-MM-DD] [--print]` | rebuild `user/reports/<date>/report.md`; `--print` also prints it |
| `python3 -m common.profile_plan [--fresh] [--json]` | print the ATS score and the profile planned from the resume; `--fresh` asks the LLM again even if the facts did not change (no `-v`) |
| `python3 -m common.profile_record [--board NAME] [--history] [--json] [--dir PATH]` | what the last profile update changed on each board; `--board` gives a line per section; `--history` every recorded run; default index `user/reports/profile` (no `-v`) |

### LinkedIn

```
python3 -m linkedin_bot (--dry-run | --propose | --post [PATH] | --if-due) [--headless]
```

| Mode | Effect |
|---|---|
| `--dry-run` | find an article, write the post and the card, print the draft; no browser; the post folder `user/linkedin_post/<topic>/<date>/` gets `post.txt`, `article.txt`, `card.png` and `carousel.pdf` |
| `--propose` | like `--dry-run`, and also save `user/linkedin/drafts/<date>.md` and send it on Telegram |
| `--post [PATH]` | publish the given draft, else today's saved draft, else a new one; refuses a draft whose article was already posted |
| `--if-due` | once a day after `LINKEDIN_POST_TIME`: propose a draft, or post it when `LINKEDIN_AUTO_POST=true`; what launchd runs |

Running with no mode prints the help and exits 1. `python3 -m linkedin_bot.update_profile [--dry-run]`
brings the LinkedIn profile (headline, About, Experience, Skills) in step with the resume through the
browser agent; `--dry-run` signs in, opens the profile and stops. It has no `--headless`.

### Schedules and sign-in helpers (macOS)

| Command | Does |
|---|---|
| `./scripts/install_profile_updater.sh` | launchd agent `com.naukri-bot.profile-update`, every 15 min, runs `naukri_bot.update_profile --if-due` (slots 09:00, 13:30, 18:30; a review every `PROFILE_REVIEW_DAYS`) |
| `./scripts/profile_update_status.sh` | is it loaded, which slots ran today, last log lines, and whether macOS is blocking it |
| `./scripts/install_linkedin_poster.sh` | launchd agent `com.naukri-bot.linkedin-post`, every 30 min, runs `linkedin_bot --if-due` |
| `./scripts/linkedin_status.sh` | agent state, today's entry, last log lines |
| `launchctl bootout gui/$(id -u)/com.naukri-bot.profile-update` | uninstall (same with `linkedin-post`) |
| `scripts/run_profile_update.sh`, `scripts/run_linkedin_post.sh` | what the agents run; they set `PATH`, `HEADLESS=false`, `BACKGROUND=false` and a random start delay (`MAX_START_DELAY_SECONDS`, 600) |
| `scripts/google_login.sh [URL ...]` | opens ordinary Chrome on the bot's profile at accounts.google.com, plus any URLs given, so you can sign in by hand; quit with Cmd+Q when done |

### Docker

| Command | Does |
|---|---|
| `docker compose build` | the one image every container uses (Chromium, Xvfb, noVNC, claude CLI, Playwright MCP) |
| `python3 -m pipeline run --containers` | every site at once, each in its own container, screens side by side in `user/docker/watch.html` |
| `docker compose run --rm --service-ports hirist docker/login.sh` | sign in to one site inside its container, watched at http://localhost:6083/vnc.html |
| `docker compose run --rm --service-ports hirist python3 -m hirist_bot --dry-run` | one bot in its container |
| `docker compose run --rm --service-ports bots python3 -m pipeline run --bots 4` | the older all-in-one container (screen on :6080) |

Watch ports: naukri 6081, linkedin 6082, hirist 6083, instahyre 6084, cutshort 6085, wellfound 6086,
all at `http://localhost:<port>/vnc.html`.

### Account API (accounts mode only)

Inside `morrow-api/` (`uv sync --locked` first): `uv run morrow <command>`.

| Command | Does |
|---|---|
| `init-local` | write a private `.env` with generated secrets (errors if one exists) |
| `migrate` | run migrations and runtime grants |
| `create-user --email E [--name N] [--admin]` | create a verified user (prompts for a 12-128 char password) |
| `set-password --email E` | reset a local password and revoke sessions |
| `link-firebase-user --email E --firebase-uid U --reason R [--new-email E2]` | link an account to a Firebase identity (audited) |
| `send-mail` | flush queued mail with retries |
| `reconcile-billing` | recover missed Razorpay notifications |
| `import-workspace --source user --owner-email E [--apply]` | snapshot a user repo (ledger, profile, resumes, research, reports) into the account; dry run without `--apply` |
| `export-workspace --target user --owner-email E [--apply]` | write the account back out in the user-repo layout; the mirror of `import-workspace` |
| `purge-artifacts` | delete storage objects for tombstoned artifacts |

---

## How each feature works

### Onboarding

`python3 -m pipeline onboard` asks for your resume (PDF, .tex or .txt) and the facts a resume cannot
supply, then writes everything the bots read: `.env` (credentials, platforms, LLM backend),
`user/inputs/profile.yaml`, `user/inputs/persona.yaml` (name, pronouns, voice, topics and study areas
for the LinkedIn writer and the learning plan), `user/inputs/answers.txt`, the worklists and the memory
skeleton under `user/memory/`. A PDF resume is converted to LaTeX (`user/resume/base.tex`) so tailoring
can work; if the conversion fails, the PDF is used as-is with `TAILOR_RESUME=false`. Any
`python3 -m pipeline` run without a profile starts onboarding on its own. Rerun it any time; existing
values are the defaults.

Everything is also editable by hand (`common/profile.example.yaml` and `common/persona.example.yaml`
document every field) or in the dashboard's **My profile & files**. Fields you leave blank are facts
the bot **does not know**: it skips a job rather than invent a notice period or a salary expectation.
The fields that matter most are the ones a resume cannot supply: current CTC, expected CTC, notice
period, relocation willingness.

### LLM backend

Job scoring, screening answers, profile text and tailoring use an LLM. By default it shells out to the
`claude` CLI, so **no API key is required**. `LLM_BACKEND=kiro-cli` uses the kiro CLI instead,
`LLM_BACKEND=anthropic` (with `ANTHROPIC_API_KEY`) the SDK, and `LLM_BACKEND=none` runs on lexical
scoring alone, in which case any screening question not already in the answer cache makes the bot skip
that job.

### Applying on Naukri

`python3 -m naukri_bot` collects a large candidate pool from freshness-sorted keyword searches (keywords
derived from **your** resume unless `KEYWORDS` is set) plus the recommended feed, scores every job
against your resume and its posting age, drops anything already applied to in a previous run and
anything below `MIN_SCORE` or older than `MAX_DAYS_OLD`, and applies to the best ones until the daily
quota is spent. Always do one `--dry-run` after changing your profile or keywords.

The rules it will not break:

- **Nothing is reported as applied unless it is verified.** Login, apply and questionnaire submission
  each have an explicit verification step.
- **Quota is debited only for confirmed Naukri-native applications.** "Apply on company site" leaves
  Naukri and consumes none; it is recorded as skipped (or handed to the company-site flow, below).
- **Screening questions are answered only from facts you supplied.** A question that needs a fact not
  in your files abandons that application rather than guessing. There is no fuzzy matching.
- **Ranking is ours, not Naukri's.**
- Naukri's "There was an error while processing your request" after Apply is its other way of saying
  the day is over; the run stops after two in a row and those jobs are tried again next run.

`user/db/naukri_bot.db` holds the applied history and the rolling 24-hour quota ledger. Deleting it
makes the bot forget what it applied to and how much quota it spent today. Back it up, don't clear it.

Two more Naukri rules: a random pause of `APPLY_DELAY_MIN_S` to `APPLY_DELAY_MAX_S` seconds (10 to 30)
follows every successful application, and a scheduled run can start up to `MAX_START_DELAY_SECONDS`
late so runs do not land at the same second every day. The chatbot drawer fails closed: every question
goes through the answer engine below, and one it cannot answer ends that application as `abstained`.

### Job scoring and ranking

The same scoring runs for Naukri and for the four boards (`naukri_bot/ranking.py`, `common/llm.py`).

1. **Collect.** Keyword searches sorted by freshness (`KEYWORDS`, or keywords derived from your
   resume's titles and skills when empty), `PAGES_PER_KEYWORD` pages each, up to `MAX_CANDIDATES`
   jobs, plus the recommended feed. `SEARCH_EXPERIENCE_YEARS` asks Naukri for jobs whose range covers
   that many years (only on keyword landing pages). `MAX_EMPTY_SEARCHES` consecutive empty searches
   abandon that search endpoint.
2. **Drop stale jobs.** Anything older than `MAX_DAYS_OLD` is removed before the model sees it. A
   posting whose age cannot be read is kept.
3. **Lexical score**, 0 to 100, no network:

   | Component | Points |
   |---|---|
   | Base | 20 |
   | Skill overlap with your resume | up to 40 |
   | Title matches one of your preferred titles | +15 |
   | Experience range fits yours | +10 |
   | Location fits (remote, WFH and work-from-home count) | +5 |
   | Freshness, 10 at 0 to 1 day old, falling to 0 at `MAX_DAYS_OLD` (unknown age: 5) | up to 10 |
   | Wrong kind of job (sales, BPO, recruiter, HR, manual testing, field, telecaller, insurance, BDE) | -35 |
   | Experience mismatch | -10 |
   | A location you did not ask for | -3 |

4. **LLM score.** The top `LLM_RANK_TOP_N` by lexical score go to the model in batches of
   `LLM_RANK_BATCH_SIZE` (20) across `LLM_RANK_WORKERS` (3) threads. It returns 0 to 100, a verdict
   and reasons, told to penalise 8+ year requirements, the wrong domain and non-preferred locations and
   to reward LLM, AI, ML, agent, evaluation and RAG roles. The blended score is **0.4 lexical + 0.6
   LLM**; verdicts are **strong** at 75 and above, **possible** at `MIN_SCORE` and above, otherwise
   **weak**; ties go to the newer posting.
5. **Coverage guard.** If fewer than `MIN_LLM_RANK_COVERAGE` (0.5) of the ranked jobs carry an LLM score
   (the CLI was down, say), a live run sends nothing rather than apply on lexical scores alone. Set it
   to 0 to allow a lexical-only run, or `LLM_BACKEND=none` to always rank that way.
6. **Select.** Jobs not already applied to, scoring at least `MIN_SCORE`, no older than `MAX_DAYS_OLD`,
   at most `MAX_PER_COMPANY` (3) per employer (names are normalised: "Soul AI" and "Soul Ai Pvt Ltd"
   are one company; 0 disables the cap). The whole sorted queue is kept because company-site redirects
   and unanswerable questions only show up with the page open; the run stops after
   `TARGET_APPLICATIONS` confirmed applications. Near misses (up to 20 jobs within 10 points of the bar)
   are logged with their reasons so you can see what a lower `MIN_SCORE` would have added.

### Early Access on Naukri

`python3 -m naukri_bot --early-access` (or `--early-access-only` to do nothing else) handles Naukri's
Early Access page, `/mnjuser/recommended-earjobs`. Those cards are recruiters' saved searches, not
postings: pressing **Share interest** flags your profile against the recruiter's query. It creates no
application, so none of the 50-a-day quota is spent. The page is a client-side route that redirects
to the homepage unless reached through the homepage's **View all** link, so the bot clicks that link.
Cards carry no job id; a role is keyed by a hash of its visible title, company, experience and location
and remembered in the `early_access_shares` table so it is shared once. The bot shares up to
`--early-access-limit` roles (20) with 1.5 to 4 second pauses and stops at the first anomaly: a button
that does not flip, or a redirect that is not Naukri's confirmation. `--dry-run` only counts.

### The application ledger

`user/db/naukri_bot.db` is SQLite in WAL mode (`-wal` and `-shm` siblings; `DB_PATH` moves it;
`LEDGER_JOURNAL_MODE=DELETE` for Docker). Parallel bots share it through a lock and a busy timeout.

| Table | What it holds |
|---|---|
| `jobs_seen` | every job the bots ever saw: id, url, title, company, source, first and last seen, latest score |
| `applications` | one row per attempt, including skips and failures: status, detail, whether quota was consumed, questions answered and abstained, the facts fingerprint at the time |
| `answers` | the screening-answer cache: normalised question, answer, field type, what it was grounded in, source, confidence, times used, profile fingerprint |
| `runs` | start and finish of every run with its counts and summary |
| `early_access_shares` | Early Access roles already shared |

Statuses: `applied`, `applied_platform` (a board), `applied_external` (a company site),
`already_applied`, `external_skipped`, `external_manual` (left in `company_sites.md`), `abstained`,
`no_apply_button`, `quota_expired`, `session_expired`, `chatbot_timeout`, `naukri_refused`, `error`.
Only `applied` debits the Naukri quota, counted over a **rolling 24 hours**, not a calendar day.

What the ledger protects you from:

- **Applying twice.** `has_applied` is true for the four applied statuses, and the pipeline's
  checkpoint reads the day's companies back from here.
- **Resending while you are still needed.** A job whose last attempt stopped for you (an abstained
  question, a company site that "needs you for" something) is held back until `answers.txt` or
  `profile.yaml` changes, which changes the facts fingerprint.
- **Sending unconfirmed twice.** A company-site job where Submit was clicked but no confirmation was
  read is held back for good.
- **The same company-site role forever.** Roles go to `user/worklists/external_jobs.md`, newest first,
  and move to `external_archive.md` after 3 opens or 10 days of Naukri no longer listing them.

The dashboard's **Applications** page is a view on `jobs_seen` and `applications`; **Insights** and
**Launchpad** count submissions from the three applied statuses only, so a retried attempt is never
shown as a second role.

### Keeping the Naukri profile recently updated, and reviewing it everywhere

Recruiter searches on Naukri rank profiles by how recently they were modified. The updater toggles a
trailing `.` on your resume headline, which Naukri counts as an update, using the same verified login
and saved browser session as the apply run, and spends none of the apply quota. The new headline is
read back from the editor before Save and from the profile page after it; nothing is reported as
updated unless both checks pass.

`--review` (and every board's `update_profile`) hands the whole profile to the Playwright browser agent.
What the agent writes comes from **one plan**, made by the LLM from the whole resume first and the facts
and answers after it (`python3 -m common.profile_plan` prints it, `--fresh` writes it again): the
headline, designation, profile summary, a short summary for one-paragraph fields, the LinkedIn About, key
skills in search order, a job profile and the skills used for every employment, every project with its
description, IT skills with years, certifications, links and preferred roles. The draft is read the way
a recruiter would: it has to open with what you build and a figure instead of "I am a", carry at least
two figures from the resume, name the stack, say what you want next, stay inside each board's length
limits and use no filler ("passionate", "results-driven", "leverage"...). A draft with notes goes back
to the model once, the better of the two is kept. Nothing in it can be a new claim: employers,
projects, skills, links, certifications and every number are dropped when the resume and facts do not
contain them. The plan is cached in `user/memory/profile-plan.json` until the facts change.

After the agent is done, the bot reloads the profile and looks for each planned value where that
section is on the page (unfolding every "Read More", allowing the board's own spelling such as
"Fast API" or "2 Years 6 Months"). Whatever the page does not show, a whole section or one skill of
several, is sent back to the agent on its own and checked again (`PROFILE_REPAIR_PASSES`, default 1).
A planned section the agent never reported (out of budget, out of turns, crashed) goes into the same
repair pass, so a run that stops short is finished rather than lost. Some Naukri forms need facts the
resume does not carry (salary breakdown, a client and start month per project, language proficiency);
fill `salary_breakdown`, `projects_detail` and `language_proficiency` in `profile.yaml` and the next
review saves those sections; until then they are reported as failed with the field named.

`--score` is the verifier on its own: reads the live profile, checks every planned value, prints
Naukri's completeness figure and the resume's ATS score, names what is missing, changes nothing.

Every run and score writes one flat record to an index shared by every board, which is the place to
look rather than the run folders:

```bash
python3 -m common.profile_record                 # every board: when, saved, sections confirmed, ATS
python3 -m common.profile_record --board naukri   # one board, a line per section
python3 -m common.profile_record --history --json # every run, for a script or the dashboard
```

```
BOARD     WHEN              RESULT     SECTIONS  COMPLETE    ATS  NOT ON PAGE
Naukri    2026-10-26 23:29  NOT SAVED  3/3       93% -> 93%  86   EC2, Git LFS, Whisper, ...
Hirist    2026-10-26 23:04  NOT SAVED  0/2       ? -> ?      90   About / profile summary, Resume
```

Details land in `user/reports/profile/latest.json` and `history.jsonl`. A failed run leaves a screenshot
in `user/screenshots/` and, with `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` set, a Telegram message after
the third failed attempt.

**The first run from a fresh browser profile is the only one that needs you at the keyboard**: Naukri
sends an OTP and the run keeps the Chrome window open for up to 5 minutes while you type it. The session
is saved in `user/browser/naukri/`; every later run, scheduled ones included, skips the login form. A
headless run cannot wait for you and exits 2 instead.

**On a schedule** (`./scripts/install_profile_updater.sh`): the agent polls every 15 minutes and runs
`--if-due`, which acts once per slot (09:00, 13:30, 18:30 local), so a laptop asleep through two slots
catches up once when it wakes. Once every `PROFILE_REVIEW_DAYS` days (default 1) a scheduled run also does
what `--review` does; a failed review is retried at the next slot, at most twice a day; `0` keeps the
schedule to the headline toggle. Slot memory lives in `user/logs/profile_update.json`, output in
`user/logs/profile_update.log`. Two things to know:

- **Keep the checkout outside `~/Desktop`, `~/Documents` and `~/Downloads`**, or grant the Python binary
  that `venv/bin/python` points at access to the folder under System Settings → Privacy & Security →
  Files and Folders. macOS blocks background launchd jobs from reading those folders; the failure is a
  silent "Operation not permitted" in `user/logs/launchd-profile-update.err`. The install and status
  scripts say when this applies.
- A scheduled run that overlaps your morning apply run cannot share the browser profile, so it falls
  back to a fresh session and logs in with `NAUKRI_EMAIL` / `NAUKRI_PASSWORD`. Start the apply run well
  before 09:00 or after that slot has run.

### Your resume: edit the LaTeX, the bot does the rest

Keep your resume as LaTeX in `user/resume/base.tex` and point `RESUME_PATH` at it. The bot compiles it
with [tectonic](https://tectonic-typesetting.github.io/) (`pdflatex` and `xelatex` also work, see
`TEX_COMPILER`) and names the PDF after the name in the header, for example `Soujanya_Gupta_Resume.pdf`,
or whatever `RESUME_FILE_NAME` says. `python3 -m common.resume --upload` reads the profile's resume card
before and after, reloads the page, and only reports success when the card shows the new file name with
today's date. With `UPLOAD_RESUME_DAILY=true` the profile updater does the same on its own: once a day at
the first slot, and again whenever you edit `base.tex` and the compiled PDF changes.

**Tailoring per application** (`TAILOR_RESUME=true`, never on a dry run): each real application first
gets its own copy of the resume. The LLM may do exactly four things: reorder the items in each
**Skills** line so the ones the posting asks for come first (an item added, dropped or renamed is
rejected); reorder the **bullet points** under each role (the words never change); reword the one-line
**subtitle** under your name; rewrite the **Summary** so the most relevant experience comes first.
Every tool, employer, number and capitalised name in the rewritten text is checked against the base
resume; a proposal that mentions anything the resume does not already say is rejected, as is anything
with buzzwords, em dashes or exclamation marks. The result must fit in the same number of pages,
otherwise the base summary is restored. The tailored PDF is uploaded to your profile in a second tab, the
application is made with it, and the base PDF is put back at the end of the run, even on error. Each job
gets `user/resume/out/tailored/<Company - Role>/` holding the PDF that was sent, `posting.txt`,
`tailored.tex` and a `tailoring.json` listing what changed and what was refused.

### Your data folder: the files you edit

| File | What it holds | What you do |
|---|---|---|
| `user/inputs/profile.yaml` | Your facts: contact details, experience, CTC, notice period, education, links. | Fill the fields left `null`; the daily report and the Action inbox list them. |
| `user/inputs/persona.yaml` | Name, pronouns, voice, topics, study areas. | Edit when your interests change. |
| `user/inputs/answers.txt` | Your own answers to application questions, as `Q:` / `A:` blocks. | Write the answer after `A:` for every question the bot added. |
| `user/inputs/company_sites.md` | Company-site applications that stopped short of submitting, with the link, the resume to send and what is missing. | Finish them by hand, or answer the missing questions and run `sites_bot.external --retry-pending`. |
| `user/inputs/accounts.md` | Career sites the bot signed in to or made an account on, and with which email. | Nothing; read it to know where you have accounts. |
| `user/resume/base.tex` | Your resume. | Edit it; the bots compile, tailor and upload. |

`answers.txt` is read before anything else, so your own words always win over the cache, the profile
and the model. Several `Q:` lines can share one `A:`. Exact matches come first; common wording
variations then use local intent rules and TF-IDF cosine similarity with no model call ("How soon can
you join?" can reuse "What is your notice period?"); skills, countries, current versus expected salary,
units and numeric thresholds stay distinct. For a dropdown the answer must name one of its options. When
a question cannot be answered from these files, the bot makes one honest judgement (below) and otherwise
adds the question to the end of `answers.txt` with an empty `A:`, the job and the date. The file is
re-read whenever it changes, even during a run. In auto mode, accepted reusable model answers are saved
to the sheet with a source comment; editing an `A:` makes your value authoritative. Parallel agents
asking the same question share a lock and re-check the sheet before calling the model. While the
dashboard is open, each save shows as **Answer sheet updated** in the Activity dock.

**The AI fills what your own files already answer** (`python3 -m common.assist`, and automatically
before and after every Naukri run). For each empty `A:` and each `null` fact it looks at three sources
only: your resume, your profile and the answers you already wrote. It must quote, word for word, the
line that supports the answer; the quote is checked against the files; a number in the answer must
appear in the quote. It never answers "why do you want to join us", never claims years in a tool none of
your files name, never copies identity numbers. Each filled line gets a `# AI filled this on <date> from
your <file>: "<quote>"` comment, the old file is kept in `user/inputs/backups/` (last 10), and the day's
report lists every change. It also reports where `answers.txt` and `profile.yaml` disagree (expected CTC,
notice period, passport, relocation, total experience, an impossible date of birth). It does not pick a
side; you fix it.

**When nothing answers a question, the AI judges it** (`JUDGE_ANSWERS=true`, auto mode). The model gets
a second look with your resume, profile, answers and the posting, and may answer only with one of these
honest inferences: a skill none of your files name: **0** years or "No"; a skill your resume shows: the
years of that role, never more than your total experience, with the line quoted; a follow-up whose
premise your files make false: **N/A**; a list without your value: the range that contains your number,
or "Other"; a question your files answer in other words, quoted. Anything else stays blank for you.
Gender, race, disability, visa, sponsorship, citizenship, right to work, identity numbers and "why us"
are never judged. A typed judgement is written into `answers.txt` with `# AI judged this on <date> while
applying to <role> at <company>: <reason>. Change it if it is wrong.` above it, so your edit replaces it.

### Company websites ("Apply on company site")

With `EXTERNAL_APPLY=true` the bot follows Naukri's (or a board's) company-site button for up to
`EXTERNAL_APPLY_LIMIT` jobs a run (never on a dry run) and works the employer's form:

1. **Opens the site** in a new tab and recognises the system behind it (Greenhouse, Lever, Ashby,
   Workable, SmartRecruiters, ...), clicking through an "Apply" button when the form is behind one. A
   job-search box is not taken for an application form. A removed posting is recorded as gone. When the
   page shows no form and no sign-in, the **page brain** takes a screenshot (kept in `user/screenshots/`),
   shows it with the page's text and a numbered list of its controls to the local `claude` CLI, and acts
   on the answer: click one control that leads to this job's form (up to twice), call the posting gone,
   or stop. A captcha or "verify you are human" page is never sent to the model; the job goes to your
   list.
2. **Signs in or signs up** when the site wants an account (Workday, iCIMS, Taleo, SuccessFactors,
   portals, any email-and-password form). It first tries **Sign in with Google** with `GOOGLE_EMAIL`
   (each run makes sure the bot's browser is signed in to it first: it types the email, then
   `GOOGLE_PASSWORD` if set, and leaves a passkey, phone prompt or code to you for 2 minutes). Otherwise
   it signs in with `COMPANY_SITE_EMAIL` (default `GOOGLE_EMAIL`, then `NAUKRI_EMAIL`) and
   `COMPANY_SITE_PASSWORD`, and when that fails or no password exists yet, creates the account. The first
   time a password is needed, a strong one is generated and written to `.env` as
   `COMPANY_SITE_PASSWORD`, so every site shares it. Every site it signs in to or registers on is listed
   in `user/inputs/accounts.md` (never the password). A dry run never creates an account. A site that
   wants its email verified first, shows a captcha, or already has an account under your email with
   another password stops here and says which.
3. **Fills the form** page by page (Next, Continue, Save and Continue; up to 8 pages), skipping hidden
   honeypot fields. Name, email, phone, links, location and current role come from `profile.yaml`; every
   other question from `answers.txt`, then the profile, then the model, exactly as on Naukri; attaches
   the resume tailored for that job (or the base one); declines optional diversity questions; ticks the
   privacy consent and leaves other optional boxes alone. A **required** long answer ("Why this role?", a
   cover-letter box) takes your answer from `answers.txt` if there is one; otherwise, with
   `JUDGE_ANSWERS=true`, one is written for that job from your resume and the posting only, first person,
   2 to 4 sentences, checked for new claims and filler, kept in
   `user/resume/out/tailored/<Company - Role>/answers.md`.
4. **Clicks Submit only** when every required field is filled, and counts the application only when the
   site confirms it. A site that answers with an error is recorded as an error, never as applied.
5. **Anything short of that** (a question it cannot answer, a captcha, an email to verify, a page it
   cannot leave) goes to `user/inputs/company_sites.md`, the questions to `answers.txt`, the tab is closed
   and the run carries on. LinkedIn and Indeed postings always go to the file.

Sign in to Google once, while no bot is running: `python3 -m sites_bot.external --google-login` (the
bot types your email, you finish the passkey or prompt) or `scripts/google_login.sh` (plain Chrome on
the bot's profile). Work one page by hand with `--url ... --title ... --company ... --dry-run`.
Company-site applications use no Naukri quota and never count toward `TARGET_APPLICATIONS`.

### Browser agent: Claude Code takes over a stuck site

When a site beats the scripted filler (an odd dropdown, a Workday step with no visible resume upload, a
"Save and Continue" that does not move on), `BROWSER_AGENT=true` hands that open page to **Claude
Code**, signed in with your local `claude` login, as a browser agent:

- `claude -p` starts with one MCP server, Playwright, attached over CDP to the bot's own Chrome, so the
  sign-ins, cookies and the half-filled form carry over and you can watch it in the window. Its only
  tools are the browser tools: no shell, no file edits, no web fetch.
- Its task holds your facts, answers, resume text, the posting, the tailored PDF to attach, and the same
  rules as the scripted filler: never invent an answer, decline optional diversity questions, write a
  required "Why us?" from the resume and posting only, click Submit at most once.
- It stops, and the job goes to `company_sites.md`, at any captcha, a code sent to your email or phone,
  two-factor, payment, or an identity number you have not given.
- For the career-site password it types the word `COMPANY_SITE_PASSWORD`; the Playwright server swaps in
  the real one and blanks it out of everything the model reads back.
- Its JSON report's "Submitted" counts as applied only when the confirmation it quotes is on the page
  when the bot reads it afterwards; otherwise the job is recorded as "Submit was clicked ..." and never
  tried again automatically.
- Each task gets `user/reports/<date>/agent/<time> <Company - Role>/` with `task.md`, `steps.txt`,
  `transcript.jsonl`, page snapshots and `report.json`. Files it may upload (the resume) are copied into
  that folder, the only place the browser tool may upload from.

It is used at most `BROWSER_AGENT_LIMIT` times a run, for up to `BROWSER_AGENT_TIMEOUT_S` seconds and
`BROWSER_AGENT_BUDGET_USD` each, and never on a page that stopped at a captcha or after a Submit click.
`python3 -m sites_bot.browser_agent --url ... --task "..."` gives it any page and any task by hand.

### Other job boards: Hirist, Instahyre, Cutshort, Wellfound

The four board bots share one loop (`sites_bot/platforms.py`) with the same facts, answers, ranking
(`MIN_SCORE`, `MAX_DAYS_OLD`) and records as Naukri. Each reads the board's own job feed for your
profile, then one search page per keyword, ranks the cards, opens each chosen job and clicks Apply. A
one-click apply, or the board's own question form, counts as applied only when the job page shows
**Applied** after a reload; such applications use no Naukri quota and carry the board's name in the
daily report. A board that sends the job to the employer's site hands it to the company-site flow; a form
the script cannot finish goes to the browser agent when `BROWSER_AGENT=true`, otherwise to
`company_sites.md`. A job where Apply was clicked but the board never showed Applied is never clicked
again automatically.

Sign in to each board once in the bot's browser (the run stops with this hint when a board is signed
out): `scripts/google_login.sh https://www.hirist.tech/ https://www.instahyre.com/login/`, or the
dashboard's **Connections** page, or let `--create-profile` sign in or sign up and build the profile.
What is board-specific lives in that bot's `board.py`: one `Board` record with its feed and search
addresses, profile page, job-link pattern and the words on its Apply and Applied buttons. A new board is
a new `<name>_bot/` package with the same files and one line in `BOARDS` in `sites_bot/platforms.py`.

### Cold emails to recruiters (drafts only)

- **Who gets one:** only an address a company published for applications: a posting's text, a career
  page the bot or the browser agent read, a Naukri job page (`--scan-naukri`). Support, no-reply and
  privacy mailboxes, and addresses with no hiring words around them, are left out. Nothing is looked up
  elsewhere.
- **What it says:** written from your resume and that posting by the local `claude`, 70 to 190 words,
  first person, checked like the tailored summary (no tool, employer or number your resume does not
  name, no filler, no em dashes), signed with your name, phone, LinkedIn and portfolio, with the resume
  tailored for that job attached.
- **Never sent:** each email is saved as `user/reports/<date>/emails/<Company - Role> (<address>).eml`;
  double-click to open it in Mail as a draft. With `GMAIL_APP_PASSWORD` set for `COLD_EMAIL_FROM`
  (default `GOOGLE_EMAIL`), it is also put in that Gmail account's **Drafts**.
- **Once per address:** `user/inputs/cold_emails.jsonl` records every draft; the same address is not
  written to again for 30 days. At most `COLD_EMAIL_LIMIT` drafts a run.

### Daily report

Every run rewrites `user/reports/<YYYY-MM-DD>/report.md`: jobs applied to today on Naukri, the boards
and company sites, with links; jobs tried but not applied, with the reason; each run's numbers;
**left for you** (company-site applications to finish, questions waiting in `answers.txt`, blank facts
in `profile.yaml`); the three profile-refresh slots, the resume on the profile, resumes tailored today;
LinkedIn's post or waiting draft; where `answers.txt` and `profile.yaml` disagree and what the AI filled
in today, with its quotes; every judgement and cover letter; cold-email drafts; browser-agent tasks;
**logs**, since every run saves its full log to `user/reports/<date>/logs/<tool>-<HHMMSS>.log`; and
**learning**: today's module from the course. The report is not written by a model; everything in it
comes from the database and the files under `user/`. Read it in the dashboard's **Reports** page or with
`python3 -m common.report --print`.

### LinkedIn: one post a day

`linkedin_bot` finds a fresh article on your topics (`LINKEDIN_TOPICS`, else the topics in
`persona.yaml`; sources are `LINKEDIN_FEEDS` or Hacker News per topic plus TechCrunch AI, The Verge AI,
Ars Technica AI, MIT Technology Review AI, the Hugging Face blog and Simon Willison), has `LINKEDIN_RESEARCH`
read it on the web and hand the writer notes, has `LINKEDIN_WRITER` write a short reaction in your voice
(the facts in `persona.yaml`; it may claim nothing else), has `LINKEDIN_CRITIC` review it once, draws a
1200x627 image card (designed as HTML by `LINKEDIN_IMAGE` and drawn by headless Chrome, or the plain
Pillow card) and a swipeable PDF carousel (1080x1350; a cover, 4 to 7 slides, a closing "Your turn"
slide; `LINKEDIN_CAROUSEL=false` turns it off), and publishes through a logged-in Chrome session. One
post a day, never two; at most 2 attempts a day.

Every draft is linted before it is accepted: no emojis, em dashes, exclamation marks or bullet lists; none
of "excited to share", "game-changer", "delve", "leverage" and the rest; no "it's not X, it's Y"; no
restating the headline; 450 to 1300 characters; the article URL alone on the last line; a one-line hook
first and a question to readers at the end. Findings go back to the model three times, then it gives up
for the day rather than post something weak.

First login: run `python3 -m linkedin_bot --post` once with `LINKEDIN_EMAIL` and `LINKEDIN_PASSWORD` in
`.env`; finish LinkedIn's verification code in the Chrome window (up to five minutes). The session is kept
in `user/browser/linkedin/`, separate from the Naukri profile. Publishing is verified at every step: the
typed text is read back from the editor and must match the draft before the media is attached; the media
must show in the composer before Post is clicked; Post is clicked once; then the bot waits for the "Post
successful" toast or the post at the top of the feed. If neither appears it reports "unconfirmed", marks
the day done so it cannot post twice, exits 3 and sends a Telegram alert. If the carousel upload fails
before Post is clicked, the image card goes out instead.

Start with `LINKEDIN_AUTO_POST=false`: for a few days `--if-due` only saves `user/linkedin/drafts/<date>.md`
with its card next to it and sends the text on Telegram. When you are happy with the voice, set
`LINKEDIN_AUTO_POST=true`. A draft you edited by hand goes out with `--post user/linkedin/drafts/<date>.md`.
Files: drafts in `user/linkedin/drafts/`, each post's folder in `user/linkedin_post/<topic>/<date>/`, the
posted-URL list and per-day record in `user/linkedin/state.json`, logs in `user/logs/linkedin.log`.

Two honest notes. LinkedIn's User Agreement forbids automated access, and an account that posts through
a bot can be restricted; the compliant route is a LinkedIn developer app with "Share on LinkedIn", which
this project does not implement. And LinkedIn changes its markup often: every selector the publisher uses
lives in the tuples at the top of `linkedin_bot/publisher.py`, in the order they are tried.

### The morning pipeline

`python3 -m pipeline` runs the day in this order: `learn` (today's study day) first, then every site as
its own **lane** (its profile stage, then its apply stage) with all lanes running at the same time by
default (`--bots N` caps it; `--bots 1` is one after another), while the AI agents run next to them
(`--agents N` at a time): `research:resume` and the five briefing agents. Each stage runs as its own
`python3 -m <bot>` process with its own Chrome profile: Naukri and LinkedIn keep theirs, each board gets
`<BROWSER_PROFILE_DIR>/../lanes/<board>`, copied from the Naukri profile the first time. Each line of a
lane's output is prefixed with the site.

The writing stages are described in [The 90-day study plan](#the-90-day-study-plan),
[Daily briefings](#daily-briefings) and [Resume study notes](#resume-study-notes). A stage that exits
0 but whose output file is missing is marked failed ("exited 0 but wrote no ..."), and a stage whose
file later disappears runs again. One crashed stage never stops the rest of the day. Failure details
written to the checkpoint are redacted (passwords, tokens, keys, cookies) and capped at 1200
characters.

`python3 -m pipeline check` (also run at the end of every pipeline run that wrote study material)
checks the material for the day: the study notes have their four parts, every briefing file is there
with its graphs and links, no emojis or contact details crept in, every link and anchor in the
90-day plan and in every course page resolves, and every course page is in the sidebar. It prints
every problem and exits 1, or "The study material is complete for <date>".

`user/memory/` is the checkpoint: `progress.json` (readable copy `user/memory/<date>.md`) records every
stage's status, attempts and files, and the companies applied to that day; `profiles.json` tracks every
board profile the bots created or updated. A stage is done only while its files still exist; when every
stage is done the day is marked **DONE** and another run that day only prints the checkpoint.

**In Docker** (`--containers`): every site runs at the same time in its own container
(`docker-compose.yml` has one service per site). Each container has its own Chromium, virtual screen and
Chrome profile in `user/docker/browser/`, and its screen is shown at `http://localhost:<port>/vnc.html`;
the pipeline opens `user/docker/watch.html` with every screen side by side. The pipeline itself stays on
your Mac, so the briefing agents still use claude and kiro and only one process writes `user/memory/`. The
containers share the ledger through the mounted repo (`LEDGER_JOURNAL_MODE=DELETE`). A macOS Chrome
profile does not open in Linux Chromium, so sign in once per site in its container with
`docker/login.sh`. The claude CLI in the containers needs `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`
on your Mac) or `ANTHROPIC_API_KEY`; kiro-cli is not in the image.

### The 90-day study plan

The `learn` stage (`python3 -m pipeline learn`, the **Prepare learning day** button on Learning > Today,
or the **Learning assistant** agent on Bot Crew) writes today's study day. Everything lives in
`user/research/learning/`:

| File | What it is |
|---|---|
| `README.md` | the plan: two hours a day for 90 days, the week-by-week syllabus (system design in one column, ML / GenAI in the other), how to use it |
| `weeks/week-NN.md` | one file per week (13 weeks), written by the AI CLI the first time that week comes up, with exactly one `## Day N` section per day |
| `today.md` and `daily/<date>.md` | today's day, cut from its week file, with the links rewritten for the new location |
| `progress.json` | the plan's start date (kept for older checkouts; the live progress is in `user/memory/learning.json`) |

Every regular day has the same four parts: **System Design** (55 minutes: notes, a mermaid diagram, a
back-of-envelope estimate), **ML / GenAI** (55 minutes: notes and a small Python exercise), **Recall**
(10 minutes: three to five self-check questions) and **Go deeper** (two to four links). Day 7 of a week
is revision plus a mini project; the last day is a mock interview. Each day then ends with **From the
course**: the `database/course/` sections the week links, quoted in full (up to 400 lines) so the
reading is in one file, plus one optional chapter the plan never links, so every chapter comes up once
over the 90 days.

The plan is about you. The week prompts are built from `user/inputs/persona.yaml`: its `goal` (default:
senior interview level in high-level system design and ML / generative AI), your headline and
experience. The day number is the first day not marked done, so skipping a calendar day does not skip
a study day. Mark a day finished with `python3 -m pipeline learn --done` (or the Flows page's mark-done
control); a second `--done` the same day is ignored. The briefing agents are told today's two topics,
which is why they wait for `learn`.

The dashboard's **Learning > Today** page shows the day as a checklist (course lesson, DSA topic,
research reading, each "N / M complete"), a streak counter, the week strip, a stepped lesson (concept,
worked example, practice questions with **Reveal approach & Python solution**) and the DSA roadmap.
`--cli claude|kiro` or `PIPELINE_AI_CLI` picks the CLI that writes the week; `PIPELINE_AI_TIMEOUT_S`
(1800) bounds one answer. A week the CLI writes short of a day is rejected and nothing is saved.

### Daily briefings

Five agents (`pipeline/briefing.py`, the **Daily briefing** entry on Bot Crew, the `brief` group on
Flows) research the day on the web and write `user/research/daily/<date>/`:

| File | Must contain | What is in it |
| --- | --- | --- |
| `01-goal.md` | 2 graphs, 3 links | today's goal in one paragraph, a mindmap of the concepts, a gantt chart of the 55 / 55 / 10 minute blocks, 6 to 10 key ideas, 5 interview questions with model answers, where this leads |
| `02-system-design.md` | 2 graphs, 4 links | the problem, an architecture flowchart, a request-flow sequence diagram, a numbers table (QPS, storage, bandwidth), trade-offs, how two or three real companies do it, 5 interview questions |
| `03-papers.md` | 2 graphs, 5 links | 5 papers from the last 2 years, 2 on today's topics and 3 the industry talks about, each with problem, idea, how it works, results, who builds on it, why it matters for your focus and what to read; an industry mindmap and a reading-order flowchart |
| `04-tech-news.md` | 1 graph, 6 links | the last 7 days: models and labs, tools, research, infrastructure, jobs (India and remote); a pie chart; one thing to try this week |
| `05-companies.md` | 1 graph, 5 links | 6 to 8 companies hiring for your focus in your location or remote: what they build, the stack, the role that fits, a recent post, the careers link; a mindmap and talking points |
| `README.md` | | every agent's status and file, a 90-day progress pie, a stages chart, an applications-per-day chart; rewritten after every agent finishes |

Each agent is a claude + kiro bridge: both CLIs get the same brief at once and search the web on their
own, each draft is checked (the graphs and links above, real URLs, papers no older than the window,
markdown only, no emojis), and claude merges the good drafts into one file, keeping the strongest and
newest items and dropping duplicates and unconfirmed links. If one CLI fails the other's draft is used;
`--cli claude` or `--cli kiro` uses one. A draft that fails its checks is not written, so the stage
stays failed and is retried on the next run. `{focus}` and `{location}` in the briefs come from
`persona.yaml`. `user/research/TODAY.md` always links the newest day. The files also show up in the
**Saved library** and on the Today page ("Saved briefings & research tools").

### Resume study notes

The `research:resume` stage (the **Resume researcher** agent) writes one study file per area of your
own resume to `user/research/resume-learning/NN-<slug>.md`, plus an index `README.md`. The areas come
from `study_areas` in `persona.yaml` (onboarding derives them from the resume; the fallback is the
Skills section of `base.tex`). Only missing files are written, so the stage is cheap after the first
day and runs again when you add an area. Each file has the same sections: what it is, how you used it
(only what the resume says, never invented numbers), core concepts, 8 to 12 interview questions with
answers, a hands-on exercise, what to read next. No contact details and no emojis; a file without its
questions section is rejected. The dashboard's **Learning > Resume topics** page lists them with a
"topics complete" counter and lets you mark each done.

### The course (PrepForge)

`database/course/` (the public Morrow-database repo, `COURSE_DIR`) is a complete senior-engineer
interview course in Markdown with mermaid diagrams and runnable code:

| Track | Chapters | Covers |
|---|---|---|
| `01-system-design` | 8 | fundamentals, storage, caching and queues, distributed systems, scalability, observability, 10 case studies, the interview framework with 30 questions |
| `02-dsa` | 12 | arrays and hashing, two pointers and sliding window, stack / queue / linked list, binary search, trees, heaps, graphs, backtracking, DP, greedy and intervals, tries and bits, mock interview sets; 70+ solved problems with Python test drivers |
| `03-fullstack-mern-kubernetes` | 9 | Node and Express, MongoDB, advanced React, auth and API security, project architecture, Docker and CI/CD, Kubernetes, production operations, 60+ Q&A |
| `04-ml-genai-agents` | 11 | ML and deep learning fundamentals, transformers and LLMs, prompting, RAG, agents and tool use, evaluation harnesses, fine-tuning and LLMOps, ML system design, 60+ Q&A, 2025-26 trends |
| `05-behavioral-leadership` | 3 | STAR stories, company round guides, senior and staff questions, negotiation |

Read it three ways: in the dashboard at **Learning > Courses** (pick a track, tick chapters read, open
a chapter in the reader at `http://127.0.0.1:8100/course/`), as its own site with
`python3 database/course/serve.py 8000` (sidebar, full-text search, rendered diagrams, copy buttons;
any port works), or as plain Markdown on GitHub. The site's `news.md` pulls today's AI headlines from
Hacker News and dev.to. Enabling GitHub Pages on the Morrow-database repo publishes it. Chapter
completion is written to your user repo, never to the course repo. The pipeline quotes course sections
into each study day (above) and `pipeline check` verifies every page is in `_sidebar.md` and every
link resolves. The daily report's **Learning today** names the day's module; `COURSE_START_DATE` sets
where that count starts.

### DSA practice and the code runner

**Learning > DSA practice** (`#/learning/dsa`) assigns one topic a day from 22 topics mapped onto the
11 DSA chapters: hash sets and frequency maps; grouping and array patterns; two pointers; sliding
windows; stacks and queues; linked lists; binary search foundations; search boundaries and answers;
walking through trees; binary search trees; heaps and priority queues; scheduling and streaming with
heaps; exploring graphs and grids; graph dependencies and paths; backtracking foundations; searching
with constraints; 1-D dynamic programming; dynamic programming on sequences; greedy choices; intervals;
bit manipulation; tries and prefix search. Each topic is a 30-minute lesson: concept, a worked example,
then problems.

**The problem sheet** (`#/learning/dsa/sheet`) is the 72-problem list with search, a status filter
(Not started, Attempted, Solved) and a notes box per problem (up to 20,000 characters). Status and notes
are saved on the spot.

**The code runner** is a CodeMirror editor on every problem with **Python 3**, **JavaScript** and
**C++17** (a language whose runtime is not installed shows as unavailable). Python and JavaScript
implement `solve(input)`; C++ reads JSON on stdin and prints JSON (a vendored `nlohmann/json.hpp` is on
the include path). Three actions: run the **samples**, run on your own **stdin**, or **submit** against
the full test set (up to 24 tests). Drafts autosave per problem and language; submissions and scores go
to `user/memory/code-practice.json`. Every run happens inside an operating-system sandbox, macOS
`sandbox-exec` or Linux `bwrap`, with no unsandboxed fallback: no network, a private workspace, 3
seconds wall time, 15 seconds to compile, 384 MB of memory, 100,000 characters of code, 64 KB of output.
If the sandbox is missing the runner refuses rather than run your code openly.

### AI practice papers and weekly exams

**Learning > Practice & exams** (`#/learning/practice`) generates question papers with the `claude` or
`kiro` CLI from what you have actually studied. Three kinds: **DSA practice** (from the daily topics),
**Daily learning** (from the study days) and **Research review** (from the briefings' paper lists). Two
modes: **Daily practice** with 3 questions and a **Weekly exam** with 5, which tests only the sources
completed in its review window. Each paper shows **Why this paper** (the sources, reviewed or still to
review), lets you save an answer per question, offers hints, and after submission shows a reference
answer with review criteria; coding questions open the inline editor. Written answers are not graded
automatically. **Prepare daily practice automatically** makes a paper appear each day. Papers and
answers live in `user/memory/practice.json`. Without an AI CLI the page says **Set up AI connection**.

### Progress, streaks, XP and badges

Everything you finish in the Learning section goes to one file, `user/memory/learning.json`, shared by
the dashboard, the course reader and the pipeline: chapters read, documents read, DSA days, plan days
marked done, and a history of every completion and reopening. Writes take a lock, validate, write a
temporary file and replace it, so two pages cannot overwrite each other, and bad data raises "Your
progress has not been reset" instead of wiping the file. The older `user/reports/studied.json` and
`learning/progress.json` are imported once and left as they are.

**Learning > Progress** (`#/learning/progress`) computes from that history:

| | |
|---|---|
| XP | 20 per course chapter, 10 per research document, 50 per DSA day; level = XP / 100 + 1 |
| Streaks | current and best, by local date |
| Heatmap | the last 365 days, 5 shades |
| Badges | First spark (1 completion), Finding rhythm (3-day streak), Week of learning (7), A lasting habit (30), Pattern finder (5 DSA topics), Curious mind (100 completions) |

The same streak and week strip are on the Today page and the Launchpad's learning widget.

### Saved research library

**Learning > Library** (`#/learning/library`) is every Markdown file the pipeline wrote under
`user/research/`, plus the cold-email drafts: briefings, papers, tech news, company notes, study days,
resume topics, and the two standing notes `tech-radar.md` (adopt / trial / assess / hold for your stack)
and `companies-to-watch.md`. Category tabs, search, a date filter and pagination; a full-width reader
(`#/learning/read/<id>`) renders sanitised Markdown and marks the document read or reopened, which
counts towards XP. Document ids are allow-listed under the research and email folders, so the reader
cannot be pointed at any other file. **Data hub** shows the same files as files.

### Action inbox

`#/todo` is where the bots leave what only you can answer: every `Q:` in `answers.txt` with an empty
`A:` (with the job, the date and the options it offered) and every `null` fact in `profile.yaml`.
Answer in place and **Save**; the file is updated, backed up and re-read by any run in progress. The
sidebar badge is the count of both. **Preview suggested answers** runs `common.assist --dry-run` so you
can see what the AI would fill from your own files before letting it. Links lead to the full answer
sheet, the profile editor and the company-site worklist.

### Connections and browser sessions

Every bot drives a Chrome profile Morrow owns, never your personal browser: `user/browser/naukri`
(the main session, also used for Google and company sites), `user/browser/linkedin`, and one permanent
lane per board under `user/browser/lanes/<board>`, which may inherit a closed Morrow session once and
is never merged again. Nothing under `user/browser/` is ever committed.

**Connections** (`#/connections`) shows one card per account (Naukri, LinkedIn, Hirist, Instahyre,
Cutshort, Wellfound, Google) with **Open sign-in** (a visible window on that site's login page: you type
the password, Morrow never does), **Check sign-in** (a read-only check of the saved session; cookie
values never leave the module), **Close**, **Change account** and **Disconnect** (deletes the session).
A scope selector switches between the main browser and each board lane. From the command line the
same windows are `scripts/google_login.sh [URL...]` and `docker/login.sh` for containers. A live run
needs the profile it uses to be free: "The bot's browser profile is in use" means a sign-in window or
another run holds it.

### Activity dock, live logs, browser previews and stop

The dock at the bottom right of every page follows every run the dashboard started. **Progress** is
the log, streamed over Server-Sent Events (`/api/events`, with polling as a fallback), with follow
latest, earlier updates, copy and expand. **Agents** is the roster with each agent's progress and
result. **Browsers** is a live picture of each run's Chrome (Chrome DevTools Protocol screenshots) and
you can type into it, which is how an OTP or a captcha gets answered without leaving the dashboard.
**Stop** asks the process to finish gracefully, then offers a confirmed force stop; only runs the
dashboard launched can be stopped. When a bot saves a learned answer it prints one structured line on
its own output (enabled by `MORROW_ANSWER_EVENT_TOKEN`, which the dashboard sets on every run), and the
dock shows **Answer sheet updated** with a link to review it. Every run's log is also kept on disk
under `user/reports/<date>/logs/`.

Several agents run at the same time. The runner reserves named resources per job (a board, a browser
profile, the ledger), so unrelated agents run together while two jobs on the same board queue.
**Run selected** on Bot Crew previews the batch and reports the conflicts before starting.

### Launchpad, Insights, Reports, Data hub and Preferences

- **Launchpad** (`#/overview`): 7 / 14 / 30 days or all time; the sent chart; your latest moves
  (linking into Applications); platform performance; the Bot Crew shortcuts; **Needs your attention**;
  the day's flow; saved research counts and learning days; **Export** the series as CSV. A failed
  refresh keeps the last data with a stale notice.
- **Insights** (`#/analytics`): the funnel (**Where the jobs went**, filterable to apply or profile
  runs, with drop reasons and "tried but not sent"), outcomes per attempt, match-score distribution
  with a range slider, job boards, which searches find matches, recent runs, CSV export.
- **Reports** (`#/reports/<date>`): any day's `report.md`, rendered in a sandboxed frame; **Build
  report** regenerates it (`python3 -m common.report --date`).
- **Data hub** (`#/data`): every file the bots wrote (research, reports, profile inputs, resumes,
  automation records, drafts) with counts per source, search, pagination, inline PDF preview and
  download. Credentials and browser sessions are excluded. In accounts mode you can upload files up
  to 10 MB.
- **My profile & files** (`#/files`): a form for `profile.yaml` (identity, preferences, career,
  background) or its source; `answers.txt`; the live agent answer sheet with **Recent agent changes**;
  `company_sites.md`; and `.env` behind a reveal guard. Saves are revision-checked (a 409 if the file
  changed since you opened it), confirmed, backed up to `user/inputs/backups/` and written atomically.
- **Preferences** (`#/setup`): the `.env` editor with search and masked secrets, the private repo's
  status and **Sync** (runs `scripts/sync_data.sh`), **Run checks** (pytest) and **Install
  requirements**.

### Telegram alerts and run logs

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` and every scheduled run reports a failure to you, the
LinkedIn writer sends each `--propose` draft for approval, and nothing else. With either unset the
alert is a no-op and the real error is still logged. Every command writes its full log to
`user/reports/<date>/logs/<tool>-<HHMMSS>.log` as well as the terminal; `-v` adds debug lines.

### Accounts mode and the account API

The free beta needs no account, and `morrow start` always opens that beta. For accounts development,
start PostgreSQL and the FastAPI service on :8200 using the Docker instructions in
[morrow-api/README.md](morrow-api/README.md), then run `npm start -- --mode accounts` inside
`froned-dashbord/`. The dashboard proxies `/api/v1/*` to the account API. See the full
[manual setup](froned-dashbord/README.md#optional-accounts-mode) for configuration.
`MORROW_API_URL` and `MORROW_WORKSPACE_OWNER_EMAIL` must be set; only that owner's account gets the bots
and the runner, every other account gets read-only, plan-gated pages backed by the API.

| Group | Endpoints under `/api/v1` |
|---|---|
| Auth | `auth/options`, `register`, `login`, `logout`, `forgot-password`, `resend-verification`, `verify`, `reset-password`, Google OIDC (`google/start`, `google/callback`, with state, nonce and PKCE); Firebase token exchange when `AUTH_PROVIDER=firebase` |
| Profile and onboarding | `me`, `profile` (versioned), `onboarding` (version conflict returns 409) |
| Applications and records | `applications` (idempotent writes), `records/<collection>/<key>` for research, learning, runs, outreach, resumes, analytics |
| Artifacts | upload, list, download, delete; local files or private S3 with AES256 |
| Billing | `plans`, `account/settings`, `modules/<module>`, Stripe `billing/checkout`, `portal`, `webhook`; Razorpay `billing/status`, `refresh`, `razorpay/verify`, `cancel`, `razorpay/webhook` |
| Admin | users and their profile, applications, records and artifacts; `admin/audit-events`; `admin/users/<id>/access` (role and plan, reason required); `admin/plans` |
| Health | `/health/live`, `/health/ready`; interactive docs at `/docs` |

| Plan | Price per month | Modules |
|---|---|---|
| Free | 0 | My profile, Applications, Private files |
| Plus | 499 INR | Free plus Resume studio, Research, Learning path |
| Pro | 999 INR | Plus plus Automations, Outreach, Insights |

Each person brings their own claude or kiro subscription; no AI credits are bundled. Admins get every
module, an admin-assigned plan overrides a subscription, expired paid access falls back to Free, and
private files survive a downgrade. Security: Argon2 passwords, HttpOnly session cookies with a CSRF
token, persistent sign-in throttling, PostgreSQL row-level security under a non-owner runtime role,
and an append-only audit log. The dashboard's account pages: sign in / create account / forgot /
verify / resend, **Plans & billing** (plan cards, checkout, cancel renewal or the Stripe portal), **My
account** (name and the claude / kiro preference), and **Administration** (user search, inspection,
access changes with a reason, plan editing). Setup: `morrow-api/README.md`,
`morrow-api/PAYMENTS_SETUP.md` (Razorpay UPI AutoPay and cards, or Stripe, chosen by
`BILLING_PROVIDER`) and `morrow-api/FIREBASE_SETUP.md`. See [Known limits](#known-limits) for what is
not built.

### HOUND: the security audit harness

`hunt/` (the Morrow-hunt submodule) is an adversarial audit of this repository that writes only under
`hunt/` and to `QUARRY.md`. It strips credentials from the environment before any child runs, pins
every scanner database, proves each instrument can both fire and stay quiet against fixture trees,
records every result in `hunt/evidence.yaml` with a provenance digest, and confirms a finding only when
a no-network sandbox test reproduces it.

| Category | Instruments |
|---|---|
| Static analysis | semgrep (custom rules), bandit |
| Lint and types | ruff, shellcheck, oxlint, tsc |
| Secrets | gitleaks over the tree and over the whole git history, a custom history check |
| Supply chain | trivy over the Python freeze and the Node lockfile, an import inventory |
| Containers | trivy over the Dockerfiles |
| Tests | this repo's pytest suite and the dashboard's node tests |
| Reproduction | probes and a sandboxed `pytest --disable-socket` that try to reproduce suspected defects |

```bash
uv sync --project hunt
uv run --project hunt hound provision
uv run --project hunt hound run
uv run --project hunt hound verify --findings hunt/findings.yaml --context hunt/evidence.yaml
uv run --project hunt pytest hunt/test              # HOUND's own tests
```

Outputs: `hunt/scope.yaml`, `evidence.yaml`, `findings.yaml`, `provenance.yaml`, `review.md`,
`progress.yaml`, the regenerated `hunt/RUNBOOK.md` (the exact command of every instrument) and raw
results under `hunt/results/`. The verdict goes to `QUARRY.md`: BLOCK, HOLD or pass, a findings table
with issue ids, what was validated and what could not be. The last run's verdict is in
[Known limits](#known-limits).

---

## Configuration: every `.env` key

`.env` is created by `scripts/setup_user.sh` from `.env.example` and filled by `pipeline onboard`.
Relative paths that start with `user/` or `database/` follow `MORROW_USER_DIR` and
`MORROW_DATABASE_DIR`. A variable already set in your shell wins over `.env`. Defaults below are the
values in `.env.example`; where the code's own default differs it is noted.

**Where things live**

| Key | Default | Meaning |
|---|---|---|
| `MORROW_USER_DIR` | `user` | your private data repo |
| `MORROW_DATABASE_DIR` | `database` | the shared course repo |
| `PROFILE_PATH` | `user/inputs/profile.yaml` | your facts |
| `RESUME_PATH` | `user/resume/base.tex` | your resume (LaTeX; .txt and .md work for ranking only) |
| `DB_PATH` | `user/db/naukri_bot.db` | applied history and quota ledger |
| `DATA_DIR` | `user/inputs` | `answers.txt`, `company_sites.md`, `accounts.md` |
| `REPORT_DIR` | `user/reports` | daily reports and logs |
| `COURSE_DIR` | `database/course` | the study course |
| `COURSE_START_DATE` | empty | the day the plan started (empty: first report) |
| `RESUME_OUT_DIR` | `user/resume/out` | compiled and tailored PDFs |
| `SCREENSHOT_DIR` | `user/screenshots` | page captures of failed runs |
| `PROFILE_UPDATE_STATE_PATH` | `user/logs/profile_update.json` | slot memory |
| `BROWSER_PROFILE_DIR` | `user/browser/naukri` | the saved Chrome session (not in `.env.example`; set per container) |

**Credentials**

| Key | Meaning |
|---|---|
| `NAUKRI_EMAIL`, `NAUKRI_PASSWORD` | Naukri login, used when no saved session exists |
| `LINKEDIN_EMAIL`, `LINKEDIN_PASSWORD` | only for `--post` and `--if-due` with auto-post |
| `GOOGLE_EMAIL`, `GOOGLE_PASSWORD` | "Sign in with Google" on career sites (password optional) |
| `COMPANY_SITE_EMAIL`, `COMPANY_SITE_PASSWORD` | career-site accounts; a strong password is generated and written here the first time |
| `COLD_EMAIL_FROM`, `GMAIL_APP_PASSWORD` | Gmail drafts for cold emails |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | failure alerts and LinkedIn drafts |
| `ANTHROPIC_API_KEY` | only with `LLM_BACKEND=anthropic`; also accepted by the Docker image's claude CLI |
| `CLAUDE_CODE_OAUTH_TOKEN` | the claude CLI inside Docker (`claude setup-token`) |

**Naukri search, ranking, quota**

| Key | Default | Meaning |
|---|---|---|
| `DAILY_QUOTA` | 50 | Naukri's hard cap |
| `TARGET_APPLICATIONS` | 50 | how many to use this morning, minus what the last 24 h already spent |
| `MAX_CANDIDATES` | 400 | candidate pool before ranking |
| `LLM_RANK_TOP_N` | 400 (code default 150) | how many top lexical candidates the LLM scores |
| `LLM_RANK_WORKERS` | 3 | ranking calls side by side |
| `MIN_SCORE` | 55 | relevance floor |
| `MAX_DAYS_OLD` | 7 | ignore older postings |
| `KEYWORDS` | empty | empty derives them from the resume |
| `LOCATION` | empty | all locations |
| `PAGES_PER_KEYWORD` | 3 | search pages per keyword |
| `SEARCH_EXPERIENCE_YEARS` | 0 | ask Naukri for jobs whose range covers this many years (0 off) |
| `MAX_PER_COMPANY` | (code) 3 | applications per company per run |

**Browser and run mode**

| Key | Default | Meaning |
|---|---|---|
| `HEADLESS` | false | no window; sites challenge headless sessions more |
| `BACKGROUND` | false | also runs without a desktop window; the dashboard's **Run in background** sets it |
| `DRY_RUN` | false | applications only; the updaters use their own `--dry-run` |
| `MAX_START_DELAY_SECONDS` | 0 | random wait before a scheduled run (launchd scripts set 600) |
| `CHROME_BINARY`, `CHROMEDRIVER`, `CHROME_WINDOW_SIZE`, `USER_AGENT` | auto | override the browser (set in the Docker image) |
| `LEDGER_JOURNAL_MODE` | WAL | `DELETE` when the ledger is shared with Docker containers |

**LLM and answers**

| Key | Default | Meaning |
|---|---|---|
| `LLM_BACKEND` | claude-cli | `claude-cli`, `kiro-cli`, `anthropic`, `none` |
| `LLM_MODEL` | empty | the backend's default model |
| `LLM_TIMEOUT_S` | 90 | per call |
| `ANSWER_MODE` | auto | `auto`, `propose`, `ask` |
| `JUDGE_ANSWERS` | true | honest inferences for unanswered questions; long answers on company forms |

**Profile updater and profile agent**

| Key | Default | Meaning |
|---|---|---|
| `PROFILE_REVIEW_DAYS` | 1 | a scheduled run also reviews the whole profile every N days (0 off) |
| `PROFILE_AGENT_TIMEOUT_S` | 2400 | seconds one profile-agent pass may use |
| `PROFILE_AGENT_BUDGET_USD` | 10 | dollars one pass may use |
| `PROFILE_REPAIR_PASSES` | 1 | extra passes that redo only what the page did not show (0 off) |
| `UPLOAD_RESUME_DAILY` | false | re-upload the base PDF daily and when it changes |

**Resume**

| Key | Default | Meaning |
|---|---|---|
| `RESUME_FILE_NAME` | empty | the file name recruiters see (empty: `First_Last_Resume.pdf`) |
| `TEX_COMPILER` | empty | `tectonic`, `pdflatex` or `xelatex` (empty: first found) |
| `TAILOR_RESUME` | false | tailor per application |
| `MORROW_RESUME_LIBRARY_DIR` | `RESUME_OUT_DIR` | set by the pipeline for each lane: the shared folder of compiled PDFs every lane reads, while each lane writes its own under `RESUME_OUT_DIR/lanes/<site>` |

**Company sites and browser agent**

| Key | Default | Meaning |
|---|---|---|
| `EXTERNAL_APPLY` | false | follow "Apply on company site" |
| `EXTERNAL_APPLY_LIMIT` | 15 (code default 5) | company sites per run |
| `BROWSER_AGENT` | false | hand stuck sites to Claude Code |
| `BROWSER_AGENT_LIMIT` | 5 | tasks per run |
| `BROWSER_AGENT_TIMEOUT_S` | 900 | seconds per task |
| `BROWSER_AGENT_BUDGET_USD` | 5 | dollars per task |
| `BROWSER_AGENT_MODEL` | empty | claude model alias |
| `BROWSER_AGENT_MCP` | `npx -y @playwright/mcp@0.0.83` | the MCP server command (pinned) |

**Other boards, cold email, pipeline**

| Key | Default | Meaning |
|---|---|---|
| `PLATFORMS` | hirist,instahyre | boards for `sites_bot.platforms` and the pipeline (`cutshort`, `wellfound` too) |
| `PLATFORM_LIMIT` | 10 | applications per board per run |
| `COLD_EMAIL_LIMIT` | 10 | drafts per run |
| `PIPELINE_AI_CLI` | both | `both`, `claude`, `kiro` |
| `PIPELINE_AI_TIMEOUT_S` | 1800 | per agent call |
| `PIPELINE_AI_MODEL` | empty | model for the pipeline's CLI calls |
| `PIPELINE_BOTS` | all | lanes at once |
| `PIPELINE_CONTAINERS` | 0 | `1` runs every site in Docker |

**LinkedIn**

| Key | Default | Meaning |
|---|---|---|
| `LINKEDIN_TOPICS` | empty | comma-separated; empty uses `persona.yaml` |
| `LINKEDIN_FEEDS` | empty | comma-separated RSS/Atom URLs; empty uses the built-in list |
| `LINKEDIN_POST_TIME` | 09:30 | local time after which the daily run is due |
| `LINKEDIN_AUTO_POST` | false | `--if-due` posts instead of proposing |
| `LINKEDIN_CAROUSEL` | true | PDF carousel with each post |
| `LINKEDIN_WRITER` | claude | `claude`, `kiro`, `backend` |
| `LINKEDIN_RESEARCH` | claude | `claude`, `kiro`, `none` |
| `LINKEDIN_CRITIC` | kiro | `claude`, `kiro`, `none` |
| `LINKEDIN_IMAGE` | claude | `claude`, `kiro`, `card` (plain Pillow card) |
| `LINKEDIN_AI_TIMEOUT_S` | 600 | per call |
| `LINKEDIN_CHROME` | auto | Chrome binary for the designed card |
| `LINKEDIN_MAX_AGE_DAYS` | 3 | ignore older articles |
| `LINKEDIN_STATE_PATH` | `user/linkedin/state.json` | posted URLs and per-day record |
| `LINKEDIN_DRAFT_DIR` | `user/linkedin/drafts` | drafts and cards |
| `LINKEDIN_POST_DIR` | `user/linkedin_post` | one folder per post |
| `LINKEDIN_BROWSER_PROFILE_DIR` | `user/browser/linkedin` | the LinkedIn Chrome session (never the Naukri one) |

**Dashboard**

| Key | Default | Meaning |
|---|---|---|
| `MORROW_MODE` | beta | mode for manual `npm start`: `beta` or `accounts`; the `morrow` launcher always uses beta |
| `MORROW_API_URL` | `http://127.0.0.1:8200` | the account API (accounts mode) |
| `MORROW_WORKSPACE_OWNER_EMAIL` | empty | the one account allowed to run the bots (accounts mode) |
| `DASHBOARD_PYTHON` | `venv/bin/python` | interpreter for `npm start` |
| `MORROW_ANSWER_EVENT_TOKEN`, `MORROW_BROWSER_INTERACTIVE` | internal | set by the dashboard for its runs |

**Legacy only** (`legacy/` scripts; ignored by everything else): `FIRSTNAME`, `LASTNAME`,
`MAX_APPLICATIONS`, `EDGE_DRIVER_PATH`, `FIREFOX_PROFILE_PATH`.

---

## Your data: repos and folders

[Morrow](https://github.com/GuptaSoujanya/Morrow) (this repo) holds the code and nothing personal. What
the bots read and write lives in two plain clones next to it, both ignored by this repo's `.gitignore`:

| Folder | Repo | Who sees it | What it holds |
|---|---|---|---|
| `user/` | your copy of the [Morrow-user](https://github.com/GuptaSoujanya/Morrow-user) template | **private, yours** | profile, resume, answers, the application database, reports, LinkedIn drafts, the pipeline's `memory/` and your `research/` notes |
| `database/` | [Morrow-database](https://github.com/GuptaSoujanya/Morrow-database) | public, shared | the PrepForge course (`database/course/`; `cd database/course && python3 serve.py 8000` reads it on its own) |

Submodules (code only): `froned-dashbord/` ([Morrow-frontend](https://github.com/GuptaSoujanya/Morrow-frontend),
the dashboard), `morrow-api/` ([Morrow-api](https://github.com/GuptaSoujanya/Morrow-api), accounts and
billing) and `hunt/` ([Morrow-hunt](https://github.com/GuptaSoujanya/Morrow-hunt), the security audit
harness whose last verdict is in `QUARRY.md`). Commit and push inside a submodule's folder; its "Bump
Morrow" workflow asks this repo's "Bump submodules" workflow to point `main` at the new commit (it also
catches up every hour); then `git pull` here. Every code repo needs `MORROW_BUMP_TOKEN`, a fine-grained
token with Contents read/write.

```
Morrow/
├── .env.example          # every key above, commented; copied to .env by setup_user.sh
├── requirements.txt / requirements.lock
├── docker-compose.yml, docker/   # one container per site: image, virtual screen, noVNC, login
├── scripts/              # morrow, setup_user.sh, sync_data.sh, launchd install/run/status, google_login.sh
├── common/               # shared: models, config, paths, profile, persona, onboard, browser, llm, ai_cli,
│                         #   answers, answer_learning, assist, ledger, resume, report, profile_plan,
│                         #   profile_record, learning_memory, memory, connections, browser_preview, run
├── naukri_bot/           # auth, sources, ranking, apply, chatbot, early_access, update_profile, cli
├── sites_bot/            # external, accounts, page_brain, browser_agent, profile_agent, board, platforms,
│                         #   cold_email, skills/profile-update/ (the agent's per-board instructions)
├── hirist_bot/ instahyre_bot/ cutshort_bot/ wellfound_bot/   # board.py, cli.py, update_profile.py each
├── linkedin_bot/         # config, news, research, writer, design, card, publisher, session, update_profile, cli
├── pipeline/             # run, lanes, briefing, learning, content, course, links
├── web/                  # the bot engine the dashboard runs on: runner, state, server, run_isolation,
│                         #   browser_preview, answer_notifications
├── froned-dashbord/      # submodule: the dashboard
├── morrow-api/           # submodule: accounts, billing, import/export
├── hunt/                 # submodule: HOUND audit harness
├── tests/                # pytest: common/, naukri/, sites/, linkedin/, pipeline/, research/, web/
├── legacy/               # the original Naukri-Edge.py and Naukri-Recommended.py scripts
├── database/             # clone of Morrow-database (gitignored)
└── user/                 # clone of YOUR private repo (gitignored)
    ├── inputs/           #   profile.yaml, persona.yaml, answers.txt, company_sites.md, accounts.md,
    │                     #   cold_emails.jsonl, backups/
    ├── resume/           #   base.tex, out/base/, out/tailored/<Company - Role>/
    ├── db/               #   naukri_bot.db
    ├── browser/          #   naukri/, linkedin/, lanes/<board>/ (never committed)
    ├── worklists/        #   external_jobs.md, external_archive.md, unanswered_questions.md
    ├── reports/          #   <date>/report.md, logs/, emails/, agent/; profile/latest.json, history.jsonl
    ├── linkedin/, linkedin_post/
    ├── logs/, screenshots/
    ├── memory/           #   progress.json, <date>.md, profiles.json, profile-plan.json, learning.json,
    │                     #   practice.json, code-practice.json
    └── research/         #   TODAY.md, daily/<date>/, learning/ (90-day plan), resume-learning/, tech-radar.md
```

`./scripts/sync_data.sh` saves what the bots wrote to your private repo. After a fresh clone the browser
sessions are gone: sign in again with the bots' login commands or the Connections page.

---

## Documents in this repo

| File | What it is |
|---|---|
| `user/README.md` | the layout of your private data repo and how to sync it |
| `database/README.md`, `database/course/README.md` | the shared course repo and how to read the course on its own |
| `froned-dashbord/README.md`, `froned-dashbord/CAPABILITIES.md` | the dashboard: start, modes, every page's controls and the accuracy rules behind its numbers |
| `morrow-api/README.md`, `PAYMENTS_SETUP.md`, `FIREBASE_SETUP.md` | the account API, payments and Firebase setup |
| `hunt/RUNBOOK.md`, `QUARRY.md` | the audit harness's exact commands and its last verdict |
| `microservices-architecture-plan.md` | the plan for splitting the bots into per-user services (not built) |
| `common/profile.example.yaml`, `common/persona.example.yaml` | every field of your two input files, documented |
| `.env.example` | every setting with its default |

---

## Verifying the install

```bash
venv/bin/python -m pytest -q tests          # ~2 minutes; 1641 tests
python3 -m naukri_bot --help                 # every module prints its flags
python3 -m pipeline status                   # today's checkpoint (read-only)
python3 -m pipeline check                    # the study material for today
python3 -m common.profile_record             # the profile index (read-only)
scripts/morrow status                        # launcher-owned dashboard readiness
uv run --project hunt hound run              # the full security audit (optional, slow)
```

Result on this machine, 27 Oct 2026: **1637 passed, 3 skipped, 1 failed**. The failure is
`tests/research/test_research_content.py::test_every_briefing_day_on_disk_is_complete`, which reads the
real `user/research/daily/` folder and found 2026-10-23 with three briefing files missing; it passes on a
fresh checkout or once that day's briefings are rerun (`python3 -m pipeline --date 2026-10-23 --only brief --redo`).
The dashboard's own suites run inside `froned-dashbord/` (`npm test`, `npm run test:beta`) and the API's
inside `morrow-api/`. The security audit harness in `hunt/` wrote its last disposition to `QUARRY.md`.

---

## Troubleshooting

| Issue | What to do |
|---|---|
| `ModuleNotFoundError` | `pip install -r requirements.lock` inside the venv |
| Exit code 2, "needs a human" | run again with a visible window (`HEADLESS=false`, `BACKGROUND=false`, no `--headless`) and finish the OTP or code in Chrome |
| "The bot's browser profile is in use" | another bot run or a `google_login.sh` window holds `user/browser/naukri/chrome`; wait or quit it |
| Login failed with a saved session gone | check `NAUKRI_EMAIL` / `NAUKRI_PASSWORD`; sign in via the dashboard's Connections page |
| A board run stops with "signed out" | `scripts/google_login.sh <board URL>` or `--create-profile` |
| No jobs found | broader keywords, no location filter, lower `MIN_SCORE`, larger `MAX_DAYS_OLD` |
| "Daily quota expired" or "There was an error while processing your request" | Naukri's day is over; the run stops and those jobs are retried next run |
| launchd job never runs | the checkout is under Desktop/Documents/Downloads; move it or grant access (see `scripts/profile_update_status.sh`) |
| Tailoring fails | needs a `.tex` resume and a LaTeX compiler on `PATH` (`brew install tectonic`) |
| Browser agent or briefings fail at once | `claude` (and optionally `kiro-cli`) must be on `PATH` and signed in; Node for `npx` |
| A profile section is reported "not on page" | read `python3 -m common.profile_record --board <name>`; fill the named field in `profile.yaml` |
| Dashboard port busy | `morrow start` reports the occupied port. Use `morrow start --port 8116` for another port, stop this launcher's dashboard with `morrow stop`, or stop an unrelated server through its own terminal or service manager. |
| Docker containers cannot sign in | a macOS Chrome profile does not open in Linux; `docker/login.sh` once per site |

---

## Known limits

- **One person per machine.** The dashboard's accounts mode stores profiles per account, but only the
  workspace owner can run the bots. There is no hosted or per-user runner.
- **macOS first.** Schedules (launchd), `google_login.sh` and the code sandbox for
  DSA practice (`sandbox-exec`) are macOS; the Linux sandbox (`bubblewrap`) is untested.
- **Sites change.** Naukri, LinkedIn and the boards change their markup; selectors live at the top of
  each bot's module and in `board.py` files so a breakage is a one-line fix.
- **Accounts mode is not production.** Firebase is not connected, payments should stay in test mode,
  MFA and usage quotas are not implemented.
- **The audit harness's last verdict is BLOCK** (`QUARRY.md`, 23 Oct): eight findings, seven of them
  local defects reproduced by failing tests (whole-file saves that lose a concurrent edit, board-profile
  history lost across processes, a dry run that still writes the learning day, a bad PNG that skips the
  LinkedIn card fallback) and one on floating CDN scripts in the course reader, none exploitable from
  outside the machine. The gate is BLOCK because scanner databases were missing at closure, and six
  redacted secret matches in git history are still unresolved. Live sites, the LLM CLI, Telegram,
  SMTP, launchd and LaTeX are not exercised by tests.
- **Platform terms.** LinkedIn's User Agreement forbids automated access; Naukri and the boards may
  restrict accounts that automate. Use the dry runs, keep the limits low, read the daily report.

---

## Legacy scripts

`legacy/Naukri-Edge.py` and `legacy/Naukri-Recommended.py` are the original scripts this project grew
from ([lordzohar/Naukri-autoapply-bot](https://github.com/lordzohar/Naukri-autoapply-bot)). They open
every keyword search in its own Edge tab, click Apply without verifying, and write `naukriapplied.csv`
with `passed` and `failed` columns. They read `NAUKRI_EMAIL`, `NAUKRI_PASSWORD`, `FIRSTNAME`,
`LASTNAME`, `KEYWORDS`, `LOCATION`, `PAGES_PER_KEYWORD`, `MAX_APPLICATIONS` and `EDGE_DRIVER_PATH`
from `.env` and are kept as-is; nothing above depends on them.

```bash
python legacy/Naukri-Edge.py
```

---

## Disclaimer

Use Morrow responsibly and within each site's Terms of Service. The bots mimic a person at a keyboard,
verify every step and never guess facts about you, but any automation can lead to account restrictions.
Every application, profile edit, email draft and post is recorded under `user/` so you can always see
what was done in your name. This project is provided for educational use.
