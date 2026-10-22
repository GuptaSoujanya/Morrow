# Orbit UX verification — October 23, 2026

Local production dashboard: http://127.0.0.1:8100/#/overview.
This report supersedes earlier paper/glass redesign scores and screen counts.

Latest extension: explicit Research Studio and Data hub navigation/Launchpad shortcuts; 18 bots including six profile agents; 24 selectable workspace avatars; eight new section emblems; and a redesigned compact Activity sheet. Data hub enumerates actual records and supported files, including contained resume PDF downloads.

## Scope

Retained the approved Orbit dark visual direction; extended its original avatar atlas with matching portraits and section graphics. Added shared
custom selects and calendars, inline field validation, persistent save errors, useful loading
and empty states, interactive activity and score charts, and a proportional outcome ring.
Refined Flows, Action inbox, Research Studio, Reports, Learning path, My profile & files and
Preferences. `.research` is explicit in the library and its document paths.

Flow checkpoints are grouped and labeled as saved state. Inbox answers expand individually;
Enter inserts a line and Cmd/Ctrl+Enter saves. Learning tracks preserve expansion, restore
checkboxes after failed writes and distinguish a failed refresh from a failed save. Settings
have readable names and purpose filters; credentials remain masked. Files retain revision
checks, backups and drafts after conflicts. Report calendars mark actual saved dates.

## Verification

| Check | Result |
| --- | --- |
| Production esbuild | Passed; local fonts and graphics; no React runtime or chart library |
| Browser regression suite | 36 passed; final Activity label correction additionally passed all 20 desktop route audits and idle/live/failure tests |
| Backend + existing web tests | 79 passed |
| Responsive routes | All 20 at 375, 768 and 1280px; no page overflow or JS exceptions |
| Accessibility | Zero axe WCAG 2 A/AA, 2.1 A/AA and 2.2 AA violations across all desktop routes |
| Complete Launchpad axe scan | Zero violations |
| Open select and mobile calendar | Zero axe A/AA violations |
| Final control refinements | Targeted dropdown, calendar and learning rollback reruns passed |

Browser writes were intercepted. No tests submitted applications, sent messages, published
posts, changed personal files or operated real schedules. Python checks use temporary data
and mocks. Profile/settings screenshots use fixtures.

## Interaction evidence

- Selects: arrows, Home/End, typeahead, Enter, Escape, outside dismissal, selected state,
  active descendant and focus retention. Async checkpoint updates defer while a popover is
  open, and field focus/caret survive background redraws.
- Calendar: invalid dates, typed entry, arrows, month navigation (including January 31 → February 28), selected date, clearing,
  focus return and phone sheet bounds. Saved report dates receive a marker.
- Charts: trend/bar switching, visible-channel filtering, exact readout/table parity, keyboard
  date selection, touch/pointer hit areas, zero-count score buckets and threshold marker.
  Straight lines connect daily observations; no synthetic smoothing or invented values.
  Unsent outcomes remain available for each selected day.
- Motion: bar/line reveal and route/dialog transitions settle; pointer exploration does not
  replay the entrance. Reduced motion disables the animations. Only loading/live state has
  continuing informational motion.
- Failure states: bounded fields block invalid commands; inbox errors retain multiline drafts;
  learning failures restore prior state; file conflicts retain edits; offline/retry and stale
  overview states remain explicit.
- Existing controls: exact command previews, practice/live confirmation, cancel without a run,
  competing-run disable, confirmed stop, all 18 bots, deep links, supported schedules, CSV,
  record filters/pagination and sandboxed document reading.

## New feature evidence

- Research Studio is explicit in desktop navigation and appears first in mobile More with Data hub. Launchpad links directly to both. Research collections use generated emblems.
- Data hub source counts checked against `/api/data`; all-time record drill-down, category/search filtering, 24-file pagination and real PDF downloads verified. Python fixtures cover source errors, traversal and symlink containment.
- Six profile agents; four new board agents preview `--profile-only --create-profile --dry-run`. Returning to application controls restores apply mode. Backend status tests distinguish profile-only from application runs. No application history is assigned to a profile agent.
- Avatar picker offers 24 identities, persists locally after reload, restores focus and leaves platform photos untouched.
- Activity idle/live/failure states, output visibility, keyboard collapse/focus restoration, stop confirmation and mobile bounds verified. Zero axe violations with the failed-run sheet open on a phone viewport.
- The live data inventory at verification contained 2,315 jobs, 289 attempts, 39 research notes, 5 reports, 3 profile files, 388 resume PDFs and 1 saved checkpoint day. Counts are dynamic.

## Performance

Production audit uses Playwright-controlled installed Chromium with the Lighthouse library,
not the Lighthouse CLI. Three desktop and three mobile runs use standard presets.

| Preset | Performance | Accessibility | Best practices | SEO | Median LCP | Median FCP |
| --- | --- | --- | --- | --- | --- | --- |
| Desktop | 100 | 100 | 100 | 100 | 0.496s | 0.248s |
| Mobile | 99 | 100 | 100 | 100 | 2.146s | 0.908s |

All six final runs had CLS 0. Median TBT: desktop 0ms, mobile 27ms (mobile range 0–46ms).
Mobile performance remains one point below the supplied frontend skill’s 100 target; that
target is **not claimed as passed**. Accessibility, best practices and SEO scored 100 in every
run. These are local lab measurements, not field Core Web Vitals.

The full graphics, data, interactions and motion remain. AVIF delivery at the original atlas
dimensions reduces combined artwork transfer by 43%, with WebP fallback. The local font is
preloaded before API discovery. The audit follows those delivery changes and the complete browser
regression run. A subsequent Activity accessible-name correction changes no layout or loading
behavior and is covered by the final full axe scan and targeted browser reruns.

## Visual evidence and limits

Final route screenshots: artifacts/375/, artifacts/768/, artifacts/1280/.
New states: artifacts/avatar-picker-{375,768,1280}.png, activity-idle-desktop.png, activity-failed-mobile.png and mobile-navigation.png.
The final atlas variants and picker were visually inspected at their actual rendered sizes.
Open controls: artifacts/custom-dropdown.png and artifacts/custom-calendar-mobile.png.
Touch graph: artifacts/chart-touch-mobile.png.
Other states: artifacts/research-reader.png and artifacts/bot-dialog-settled.png.
Lighthouse reports: artifacts/lighthouse/. Full axe scan: artifacts/accessibility-initial.json.

Reviewed the requested screens, custom controls, data/readout consistency and narrow layouts.
Screenshots are captured after motion settles. Full-page images show fixed navigation/docks
at their viewport position. Artifacts remain gitignored because live dashboard views can
contain personal data.

The external frontend reference packs and formal visual-qa/review-work orchestrators are
unavailable; no formal dual-oracle pass is claimed. Chrome is verified; other engines are not.
Opaque sandboxed report/research documents are visually reviewed and excluded from axe
injection; their dashboard shell is checked. This remains a local personal workspace, with
live controls limited to processes owned by its runner. Remote bot success still depends on
platform sessions and credentials and was not exercised by these tests. Profile source
editing retains the existing file format rather than converting its schema.
