# Morrow UX verification — October 23, 2026

Local production dashboard: http://127.0.0.1:8100. This report supersedes the earlier Orbit scores and screen counts.

## Scope

Morrow retains the approved charcoal/lavender direction, dimensional crew and glass shell. The latest Research Studio separates Today, Learning, Resume lab, Library and Progress. Today exposes the selected date’s README, Papers, Tech radar and Company radar, with real heading previews and direct fetch/refresh controls. Learning contains the next unfinished day, saved weekly plans, daily goal and system-design material. Resume lab has its own index and all numbered topics. Readers use the available width and preserve their return URL.

Earlier refinements in this delivery include URL pagination, inline resume PDF preview, 32 selectable workspace avatars, a folded-M logo, local Space Grotesk headings, structured profile editing, grouped preferences, a centered loader and an independently scrolling sidebar. React owns lazy route boundaries and Suspense; TanStack Query caches and deduplicates read requests.

## Verification

| Check | Result |
| --- | --- |
| Production build | Passed; 17 lazy route modules; no react-grab, react-scan or react-doctor in production inputs |
| Browser regression suite | 52 passed; final Research loading-copy cleanup additionally passed 4 targeted checks |
| Python backend, web and pipeline suite | 124 passed |
| Main routes | All 20 at 375, 768 and 1280px, without page overflow or JavaScript exceptions |
| Short laptop layouts | 1280×720, 1366×768 and 1440×900 |
| Research views | All five at 375, 768 and 1280px, including saved and missing dates |
| Accessibility | Zero axe WCAG 2 A/AA, 2.1 A/AA and 2.2 AA violations across desktop routes and all five Research views |
| React Doctor | No issues in the React route adapter |
| Diff whitespace | Passed |

Browser write requests were intercepted; editable-file screenshots use fixtures. Tests did not run bots, change personal profile/settings files, operate schedules or change real course/research completion. Python checks use temporary workspaces and mocks. The requested resume-index repair was performed separately: the old index was backed up under `.memory/backups/`, then README was rebuilt from the 12 existing topic files without AI calls or topic changes.

## Research and progress evidence

- The saved October 22 date exposes all six daily documents, the additional dated note and root research references. Missing October 23 content remains explicitly missing, with a link to the latest saved date.
- Papers, Tech radar and Company radar preview commands target their exact `brief:*` stage and selected date. Cancel sends no run request; failed runs produce an inline error. The existing runner handles confirmed execution and Activity. Actual AI generation was not exercised.
- Daily README and the repaired resume README open in the full-width reader. Resume README contains all 12 topics; Learning and Resume lab remain separate from news.
- Completion is explicit and reversible. Opening a document does not mark it complete. Failed saves retain the prior state and show an error. Today’s completions and paginated completion/reopen history use stored timestamps.
- `.memory/learning.json` is the canonical course/research/plan store. Tests cover legacy migration, reopening without reimporting old completion, module reload, CLI/dashboard coherence, alias deduplication, 16 concurrent process updates, malformed storage and interrupted atomic replacement. Failed writes preserve the last committed JSON.
- The legacy `/course/01-system-design/` URL opens the actual Docsify lesson. Dashboard and course reader share progress controls and storage.
- Date selection, reader return URLs, separate Learning/Resume navigation, source previews and all Research view widths were verified in Chrome.

## Other interaction evidence

- Pagination: Applications and Data hub preserve page, filters and search across reload/Back/Forward. A 100,000-row fixture renders only the selected page; it is a frontend rendering check, not a concurrent-user load test.
- PDF preview: inline contained PDF endpoint, explicit download and fallback link; no automatic download. Backend rejects traversal and escaping symlinks.
- Query cache: repeat reads are reused, manual refresh refetches, successful mutations invalidate, and stale filter responses cannot overwrite the current search. Personal/credential responses are not persisted in browser storage.
- Route resilience: delayed chunks show Suspense loading; failed chunks preserve navigation and recovery. Sidebar scroll remains stable through background polling. Loader centering and reduced motion are checked.
- Profile/preferences: structured YAML preserves types, lists, comments and unrelated keys; revision conflicts preserve drafts; credentials remain masked. Avatar selection persists and restores keyboard focus.
- Controls: dropdown arrows/typeahead/Home/End/Enter/Escape, focus return, invalid dates, month boundaries, phone calendar bounds, inline field errors and multiline inbox drafts.
- Charts: daily values agree with the data table; trend/bar modes, channel filters, keyboard/touch exploration, score buckets and proportional outcomes work. Resize keeps the graph’s interaction target stable. Reduced motion removes animation without removing information.
- Runner: exact command previews, cancel, confirmed actions, competing-run disable, stop confirmation, 18 bots including six profile agents, and Activity idle/live/failure states.

## Performance

The final production measurements use Playwright-controlled installed Chrome and the Lighthouse library, with three desktop and three mobile runs. Values below are medians from `artifacts/lighthouse/summary.json`.

| Preset | Performance | Accessibility | Best practices | SEO | LCP | FCP |
| --- | --- | --- | --- | --- | --- | --- |
| Desktop | 100 | 100 | 100 | 100 | 0.661s | 0.394s |
| Mobile | 94 | 100 | 100 | 100 | 3.024s | 1.432s |

All six runs recorded zero layout shift and 0ms total blocking time. Mobile performance is below the frontend skill’s 100 target; that gate is **not claimed as passed**. The mobile heading LCP remains about 3 seconds in Lighthouse’s simulated network/CPU preset. The critical React/runtime and shared module payload remains performance debt. Fonts are local and preloaded, the initial route and API reads start together, and other routes remain lazy. Content, graphics, controls and motion remain intact. These are local lab results, not field Core Web Vitals or production load tests.

## Visual evidence and limits

Fresh route screenshots: `artifacts/{375,768,1280}/`. Research screenshots: `artifacts/research-{today,learning,resume,library,progress}-{375,768,1280}.png`. Additional evidence includes laptop screens, avatar picker, custom controls, chart touch states, Activity and document readers. The Research laptop and mobile surfaces were visually inspected after the final layout corrections. Full-page screenshots capture fixed navigation/Activity at their viewport position. Artifacts remain gitignored because real views can contain personal data.

The frontend reference pack, formal visual-qa/review-work orchestrators and in-app browser target were unavailable. Existing Playwright with installed Chrome provided browser evidence; no formal dual-oracle pass or other-browser support is claimed. Opaque sandboxed document frames are excluded from axe injection; their surrounding dashboard shell is checked and document rendering is visually reviewed.

This remains a local single-user Python/SQLite workspace, not an authenticated multi-user deployment. Client caching and bounded lists do not prove 100,000 simultaneous users. Live research/bot success still depends on configured agents, sessions and credentials. The hosted course reader retains its existing CDN dependencies. Existing generated research content is displayed as saved, not independently verified by this UI work.
