# Morrow — your career workspace

A complete local workspace for the existing job-hunt project: application analytics,
bot controls, pipeline progress, screening answers, profile/settings editors, reports,
resume tailoring and study progress.

## Start

Use Node.js 22.19 or newer. From this folder:

```sh
npm install
npm start
```

Open **http://127.0.0.1:8100**. `npm start` builds the frontend and starts one Python server
for both the UI and API. It uses `../venv/bin/python` when available; otherwise `python3`.
The parent project's Python requirements must already be installed. Override the interpreter
with `DASHBOARD_PYTHON`, or choose a port with `npm start -- --port 8200`.

## What is included

- **Launchpad:** reference-inspired dark summary, real activity graph, compact metrics,
  recent attempts, Bot Crew shortcuts, follow-ups, saved flow progress and research output.
- **Data hub:** all-time record counts, source paths and searchable research/report/profile/resume files; inline PDF preview, explicit downloads, URL-backed pagination and clear missing/error states.
- **Applications:** search the actual ledger, switch between discovered jobs and attempts,
  filter by platform/outcome/date, sort by score and open the underlying records.
- **Bot Crew:** 18 application, profile and career assistants with original 3D avatars, practice
  controls, configuration links, busy states and recorded history.
- **Flows:** select groups or exact stages, continue or rerun completed work, skip groups,
  choose date/CLI/concurrency, inspect grouped checkpoints and validate material.
- **Insights:** conversion funnel, outcomes, match scores, platform/search comparisons,
  recent runs and 7/14/30/all-time CSV exports.
- **Research Studio:** search and read generated briefings, study plans, resume research and
  saved recruiter drafts. Today presents the selected date’s daily README, Papers, Tech radar and Company radar, with direct fetch/refresh controls. Learning and Resume lab have separate material and progress. Library contains the searchable `.research` collection; Progress records completion history.
- **Automation controls:** Naukri and four other job boards, company sites, Naukri/LinkedIn
  profiles plus dedicated Hirist/Instahyre/Cutshort/Wellfound profile agents, LinkedIn posts, recruiter email drafts and resume tailoring.
- **Action inbox, Learning path and Reports:** answer questions, complete facts, read course
  modules in expandable tracks and review or generate reports from the date archive.
- **My profile & files / Preferences:** configuration editing, masked credentials, revision
  checks, unsaved drafts, private backups, preferences grouped by purpose and a 32-character workspace avatar picker.
- **Activity:** compact illustrated launcher, run summary, expandable output, copy, follow-latest, graceful stop and force stop for owned runs.
- **Schedules:** enable, inspect and disable the supported Naukri-profile/LinkedIn macOS jobs.
- **Custom controls:** keyboard-accessible dropdowns, calendar date entry, persistent field errors,
  clear loading/retry states and draft-preserving saves.
- **Interactive charts:** trend/bars toggle, channel filters, crosshairs, touch/keyboard date
  inspection, score-range exploration and outcome rings, all driven by the actual records.
- **Morrow design:** dark glass navigation/dock, layered charcoal cards, original avatar art,
  duotone navigation, local typography, restrained motion and reduced-motion support.

See [CAPABILITIES.md](CAPABILITIES.md) for the backend-to-UI inventory and data semantics.

Runs show an exact command preview and ask for confirmation. Practice mode is selected by
default wherever supported. Pipeline practice mode still permits its learning/research stages
to invoke the configured AI CLI. Only one command can run through this server at a time.
Commands started separately in a terminal are outside this console's process control.

## Data

The dashboard reads the project's existing SQLite database, `data/`, `.memory/`, `.research/`, `course/`
and `.env`. It does not duplicate personal records in this folder or invent chart values.
Shared course endpoints in `web/` use the same durable progress store. Most dashboard files are contained here; `common/learning_memory.py` is shared with the learning CLI.

File saves require the revision that was opened; external changes cause a conflict instead
of an overwrite. Prior versions are saved under `data/inputs/backups/dashboard-*.bak` with
private permissions. Unsaved editor drafts survive in-app navigation; they are held only
in memory. Reloading the whole page discards them after the browser's warning.

The server binds only to `127.0.0.1` and keeps the original API's Host/Origin checks. This is
a local personal tool, not an authenticated internet-facing service.

## Development and verification

```sh
npm run build                  # rebuild app/ into dist/, then reload the page
npm test                       # Playwright UI, accessibility and responsive checks
npm run audit                  # 3 desktop + 3 mobile Lighthouse runs in Chromium
../venv/bin/python -m pytest tests ../tests/web -q
```

Browser checks default to installed Google Chrome on macOS; set `CHROMIUM_PATH` to another
Playwright-compatible Chromium executable. `DASHBOARD_URL` changes the target for audits.
The UI tests replace write requests with fixtures; they never run bots or edit your personal
files. Backend tests use temporary data. Reports are deliberately sandboxed: the automated
accessibility scan checks the dashboard shell separately from report documents.

Source: `app/js/` (ES modules), `app/styles/` (design tokens and primitives), `server.py`
(dashboard server using the existing web API). React 19 owns lazy route boundaries and Suspense; existing DOM components render inside a route adapter. TanStack Query v5 caches and deduplicates read requests. Typography uses locally hosted Space Grotesk and Source Sans 3. Original avatar graphics are bundled from
`app/assets/`; generation details are in `ASSETS.md`. Design decisions are in `DESIGN.md`; verification
evidence and limitations are in `QA.md`. Generated screenshots/reports in `artifacts/` are
gitignored because real dashboard views can contain personal information.

## Durable learning and navigation

Course lessons, research notes and 90-day learning completions save to **`.memory/learning.json`** in the project root. The server imports prior `data/reports/studied.json` and `.research/learning/progress.json` once, preserving the originals. Writes use a process lock, fsync and atomic replacement. Invalid storage is reported rather than silently reset. Back up `.memory/` with the rest of your workspace.

- Research Studio → **Today**: choose a date, open its daily README, and read Papers, Tech radar and Company radar. Missing dates remain explicitly empty, with a link to the latest saved date. Fetch a whole briefing or one section directly, after reviewing its exact command.
- **Learning**: your first unfinished learning day, 90-day progress, daily goal, system-design brief and saved weekly plans. **Resume lab**: a separate topic library based on your resume, with its own overview and completion count.
- Fetch actions use your configured AI agents and persist their output in `.research/`; they are not simulated feeds. The Activity panel shows the run, and the view refreshes when it finishes. Only one dashboard run can execute at a time.
- Open a read → **Mark complete**. **Reopen reading** reverses it. Opening alone never completes an item.
- **Progress**: dated course/research completions and reopens, plus imported work whose original dates were not recorded.
- Learning path and the hosted course reader share the same progress. `/course/01-system-design/` redirects to `/course/#/01-system-design/`. The course reader still uses its existing CDN scripts.
- Applications, Data hub and the Research library keep page/filter/search state in the URL. Browser Back, Forward and reload restore it.

TanStack Query keeps ordinary GETs fresh for 30 seconds and evicts unused entries after five minutes. Status/run/editable files bypass the cache. Mutations do not retry and invalidate cached reads after success. No credential or personal-data cache is persisted to browser storage. React Suspense and a route error boundary keep navigation available while pages load or fail. The initial route loads alongside its data to avoid an extra waterfall.

`npm run dev` includes development-only react-grab and react-scan; `npm run doctor` checks the React route adapter. Production builds exclude those tools. Client caching and bounded rendering do **not** establish 100,000-user capacity: this server remains a local single-user tool.
