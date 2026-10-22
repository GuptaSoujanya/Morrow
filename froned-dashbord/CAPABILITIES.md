# Orbit control and data coverage

The dashboard lives in `froned-dashbord`. Display names changed; existing route hashes,
backend modules and stored data remain compatible. This inventory describes implemented
controls, not a claim that remote platform operations have succeeded.

| Workspace area | Existing backend / data | Controls available |
| --- | --- | --- |
| Launchpad | `web.state.overview`, SQLite ledger, worklists, `.memory/progress.json` | 7/14/30/all-time scope, refresh, CSV, source-record drill-down, platform shortcuts, saved flow progress, current follow-ups |
| Data hub | `/api/data`, existing ledger, `.research`, reports, profile inputs, resume PDFs, saved checkpoint | All-time source counts, searchable/paginated file inventory, source paths, safe resume downloads and links into existing editors/readers |
| Applications | `jobs_seen`, `applications` | Unique discovered jobs or individual attempts; search; board/outcome/period filters; score/date sorting; pagination; detail disclosure; original job links |
| Bot Crew | 18 bot/assistant entries; runner and recorded runs | Search/category filters, individual practice actions, specific board/group configuration, six profile agents, profile-only deep links, owned live status and run history |
| Naukri | `naukri_bot` | Keywords, location, limit, answer mode, dry run, headless, Early Access/only/limit, score threshold, job age, scoring provider |
| Job boards | `sites_bot.platforms` | Hirist/Instahyre/Cutshort/Wellfound/all, application or profile mode, profile-before-apply, practice and per-board limit |
| Company sites | `sites_bot.external` | Search/select worklist rows, preview, apply using existing browser/answer options |
| Naukri profile | `naukri_bot.update_profile` | Preview/live, full review, due-only, headless, schedule status/on/off |
| LinkedIn profile | `linkedin_bot.update_profile` | Preview or save profile updates from saved facts |
| LinkedIn writer | `linkedin_bot` | Draft, propose, publish, due-only, draft file, headless, schedule status/on/off |
| Recruiter drafts | `sites_bot.cold_email` | Naukri scan, lookback/pages/limit, explicit recipient/company/title/URL, preview or save drafts. Backend never sends mail; may sync Gmail Drafts if configured |
| Resume tailor | Existing resume action | Job description, generated resume destination, preview and execution |
| Flows | `pipeline` | Full workflow, groups or exact stage; continue; redo selected work; fresh live checkpoint; skip group; date; CLI; research concurrency; status and content check |
| Research Studio | `.research/**/*.md`, `data/reports/*/emails/*.eml` | Search, category filter, document reader, local links, refresh, learning-day completion |
| Action inbox | Existing question/fact APIs | Reusable answers, missing profile facts and existing save controls |
| Learning path | Existing course API/site | Course list, reading links and read status |
| Reports | Existing report builder/read API | Date selection, generate, refresh and sandboxed report reader |
| My profile & files | Existing profile/answers/worklist file allowlist | Edit, unsaved draft retention, revision conflict checks, private backups; 24 workspace avatars stored only in browser local storage |
| Preferences | Existing settings API | Search, secret masking/reveal, configuration updates |
| Activity | Existing dashboard-owned runner | Illustrated launcher, elapsed/result summary, logs with follow-latest, copy, expand/collapse, graceful stop and confirmed force stop |

## Accuracy rules

- Submission totals count only `applied`, `applied_platform`, `applied_external` events.
  Repeated attempts are not presented as unique roles or interviews.
- Discovery totals count unique job IDs first seen in the period; scores are the latest stored
  values. Records use the same local calendar boundaries and score threshold as overview.
- Missing application role/company/URL can fall back to that job's discovery record. If both
  omit metadata, the actual job ID and “Company not recorded” are shown; no data is invented.
- Rolling 24-hour Naukri quota and current follow-up worklists are independent of date filters.
  Company worklist entries are not assumed to be confirmed submissions or reconciled events.
- Failed refresh preserves prior overview data with an explicit stale notice and retry.
- Saved pipeline checkpoints and unfinished run records are not proof of live activity.
  Only processes launched by this dashboard are controllable in its Activity dock.
- Markdown HTML is disabled, external images omitted and source links constrained. Documents
  must be allowlisted under the research/email roots; traversal and escaping symlinks fail.

## Product boundary

Orbit is a commercial visual direction for this existing personal local tool. It does not add
public hosting, accounts, multi-user isolation, billing or distributed workers. Platform sessions
are checked by the actual bots when launched. CLI-only environment-path/verbose switches are
not arbitrary-command inputs in the UI. The two supported schedule controls use macOS launchd.

Profile-only board commands use `--profile-only --create-profile`, and are distinct from application commands in crew status. Application history is never shown as profile history. Data hub excludes credentials and browser sessions; PDF downloads are constrained to the configured resume directory and reject traversal/escaping symlinks. Generated art is documented in ASSETS.md.
