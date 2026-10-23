# Apply — glass control center

## 0. Research and change of direction
The user rejected the paper/serif design and requested Apple-inspired glass, polished motion, visible bots and complete controls. This contract supersedes the earlier visual direction. This is a redesign of an existing component system.

- Apple Human Interface Guidelines, Materials: https://developer.apple.com/design/human-interface-guidelines/materials. Use translucent navigation and controls to establish hierarchy; keep data readable. This is a web interpretation, not an exact native Liquid Glass reproduction.
- Loaded UI/UX Pro Max SKILL.md: sufficiently opaque light glass, readable text, visible focus, touch targets and reduced motion. Its search CLI is missing from the installation.
- The supplied frontend router is available, but its design/perfection/interaction/visual-qa/designpowers reference files remain unavailable locally. No claim that those external gates ran.
- Audit: bots hidden in dropdowns, excessively long overview, dominant dark console, generic inspirational copy. Resolve with bot-first controls, separate analytics, compact activity dock and task-specific language.

## 1. Purpose and content hierarchy
Primary user: a job seeker operating local automation. Opening tasks: identify bots, inspect latest recorded activity, choose a run, resolve blocked applications. Secondary: conversion, scores, searches, files, schedules and learning.

Content jobs: greeting/execution state (orient); four concise metrics (prove); six application bot cards (control); chart and follow-up queue (explain/act); pipeline shortcut (coordinate). Analytics retains all funnel, outcome, score, board, search and history data. Bot center includes application and career/research assistants. Existing features remain reachable.

## 2. Tokens
Cool luminous desktop, pale blue/lilac background wash, translucent floating sidebar, white frosted cards, small glass activity dock. No decorative floating objects or continuously animated backgrounds.

- Canvas #edf2f9. Text #172338, secondary #526078, muted #5d6b80. Accent #2563eb, pressed #174dc4, subtle #e5edff. Success #14764f, warning #855612, error #b52e40.
- Glass white78–88%, sidebar65%, dialogs94%. Blur22px/saturation1.35. Dense data uses higher opacity. Border rgba(98,121,156,.16), white inner highlight. Ambient shadow0 10px 32px rgba(55,78,117,.07), contact0 1px 3px rgba(55,78,117,.06).
- System typography: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif. Display34/1.12 weight650, headings18/22 weight650, body14/21, secondary12/18, micro11/16. Tabular data. SFMono-Regular/Consolas for code. No serif headings.
- Spacing4,8,12,16,20,24,32,48,64px. Padding24 cards/20 bot cards. Radius12 controls,22 cards,24 sidebar,28 dialogs,999 pills.
- Sidebar224px desktop/72px tablet, main max1280, gap20. Bot identity tiles44px; status dots6px. Original letter marks/shared stroke icons, never fabricated brand logos. Blue/teal/orange/plum/charcoal distinguish application bots; violet/blue for career tools.

## 3. Primitives
Glass panel = white edge highlight, subtle shadow, frosted fill. Avoid nested glass. Metric = label, tabular value, short context, optional trend. Bot card = identity, name, capability, recorded status, activity/metrics, control and settings. Cards static; actionable controls respond to hover.

Controls: blue primary, white glass secondary, segmented filters, labeled search, switch, outlined icon button. Empty states name missing data and offer action. Errors retain retry. Native dialogs trap/restore focus. Console supports expand/collapse/copy/graceful stop/force stop.

## 4. Bot/data contract
Application bots: Naukri, Hirist, Instahyre, Cutshort, Wellfound, Company sites. Career: Naukri profile, LinkedIn, Resume, Learning, Briefing, Resume research. Individual board controls preselect that board; pipeline assistants preselect their group.

Live means owned by this dashboard runner. An unended ledger record is unfinished history, not proof of a live process. Checkpoints are historical. No invented connected/login state, queue, pause or percentage. External processes cannot be stopped here. Counts and graphs use SQLite/local files. Practice default; live actions confirmed; revisions/backups preserved; one owned run at a time.

## 5. Motion
Fast180ms, normal260ms, entrance320ms; cubic-bezier(.22,.8,.25,1). Animate only transform/opacity. Press scale.97. Routes enter4px/fade once, never replay on polling. Dialog enters8px/scale.98. Console content fades on expansion. Only actual running indicators pulse. No idle breathing, fake progress, sweeps or mouse-following effects.
Keyboard equals pointer. Search/filter preserve focus. Deep links select bots. Async refresh must not discard edited forms.

## 6. Responsive
1280+: full sidebar/four metrics/three bot columns/chart+attention. 768–1100: labeled icon rail/two bot columns. 375–767: five-item glass bottom navigation, two-column compact metrics, stacked bot cards, full-width controls, scrollable More sheet. Bottom content clears dock. Tables scroll locally. Mobile inputs16px. No page horizontal overflow.

## 7. Accessibility
Text contrast>=4.5:1 on actual composite backgrounds; visible focus/borders. Mobile targets44px. Reduced motion removes transitions. Reduced transparency increases opacity/removes blur. Charts provide names, keyboard tooltips and data tables. Status has text and dots. Native modal/Escape/focus restoration.

## 8. Verification/debt
Every route375/768/1280; overview/bots1440 visual critique. Test bot selection, practice/live commands, filters/deep links, busy/failed/empty states, console stop, revisions, keyboard. Production Playwright/axe/Python checks and real Chromium performance audit.

Accepted limits: CSS glass approximates native material; no optical refraction. Profile and LinkedIn schedule controls enable/disable their explicit launchd jobs; status uses the existing scripts. Other externally started jobs remain outside runner control. Sessions verified only when bots open platforms. Unavailable reference gates listed above. Record fresh checks in QA.md; earlier scores do not validate the redesign.

## 9. Overview revision — data and control coverage

The user again rejected the pastel palette, typography, sparse data and missing backend controls. They explicitly selected **Dark — charcoal surfaces, bright text, restrained accents**. This section supersedes all conflicting visual/content rules above.

Palette: charcoal canvas #141719; content #1c2022; navigation #181c1e at94% opacity; bright text #edf1ef, secondary #b1bab5, muted #99a69f; sage accent #8acba8 with subtle #263b31; primary controls use dark text #14241b. Chart green #78b99a, secondary #8da8bb, warning #dfb878, error #f1979c. Border #343c38; hover surface #282e30; dark native color-scheme. Remove the blue/lilac backdrop and colored identity gradients. Subtle glass belongs to navigation/dock/dialogs; data surfaces stay legible. Card radius14, control8, dialog20; shadow0 1px 3px rgba(0,0,0,.12) with restrained edge highlights. No pastel tiles or floating decorative metrics. Report and research document readers inherit this palette; inputs, date pickers, menus, empty/error states and dialogs must be checked in dark mode.

Typography: locally hosted Source Sans3, weights400–700; headings30/36 weight650, section18/24 weight600, body15/22, labels13/18, captions12/18; tabular numeric data34/40. No critical data in10px text. Maintain visible hierarchy through weight, spacing and rules, not color proliferation.

Overview decision order: operational header with freshness/date scope; clickable KPI strip (confirmed submission records, discovered jobs, matching jobs, rolling Naukri quota); activity chart + current follow-up queue; recent application records + saved daily pipeline; compact platform rows with real counts and configuration; shortcuts to research/output and full controls. Full bot catalog belongs in Bot center. Current quota and follow-ups explicitly ignore period filters. Failed refresh preserves last data with stale/error label and Retry, never silent old data. Records and charts must use identical local-day boundaries.

Add Application/Opportunity records with search, board/status/period filters, pagination, safe source links and expanded outcome detail. Show each recorded attempt as an attempt, not a unique job; only verified applied/applied_platform/applied_external count as submitted. Jobs are unique ledger IDs; score is latest recorded score. No invented salaries, locations, connection states, interviews or conversion percentages.

Close concrete control gaps: Naukri score/age/LLM/Early Access limit; full profile review; LinkedIn profile updater; recruiter email drafts (never sends mail); all individual pipeline stages, rerun completed selection, skip, date, concurrency and CLI selection; research/learning output reader and marking a learning day done. Expose saved research Markdown through a constrained read-only renderer with raw HTML disabled. Keep default practice mode and explicit confirmation on live effects. Test command allowlists, bounds, exact options and file containment.

Coverage inventory is recorded in CAPABILITIES.md. File/status API failures are visible; do not claim authenticated accounts or successful bot effects without evidence. Styling must be applied to all existing views, report documents and new records/research screens, with mobile usability and keyboard focus preserved.

## 10. Orbit — iBanko reference adaptation

User-supplied visual reference: https://dribbble.com/shots/19411888-iBanko-Finance-Dashboard-UI-Concept by Anik Deb. Viewed the actual 1824×1368 tablet composition, saved locally as artifacts/ibanko-reference.jpg for QA only. The image contains light and dark product views. This is a project-specific dark adaptation: preserve the reference's profile-led left rail, compact greeting and utility header, dominant balance-style summary, small colored metrics, chart below, right activity column and avatar shortcuts. Never reuse its finance figures, logo, card numbers or people. Its angled tablet presentation is not part of the website.

Brand: **Orbit**, a career workspace for younger job seekers. Descriptor “Your next move.” Product language stays clear rather than slangy. Routes keep stable hashes; display labels become Launchpad (overview), Applications (records), Bot Crew (bots), Flows (pipeline), Insights (analytics), Action inbox (todo), Growth library (research), Reports, Learning path (study), My profile (files), Preferences (setup). Existing backend actions retain their exact API identifiers. No fabricated plan, billing, social connections or multiplayer status.

Visual tokens: near-black navy-charcoal canvas #121318, raised #1b1d24, nav #191b22, fine border #30333d; text #f2f3f7, secondary #b7bac7, muted #a0a5b6. Lavender accent #b9a5ff (dark foreground #241b3a); success mint #95d6b5; peach #e6b69c; slate blue #9eb8d5. Main career card satin charcoal with a dimensional violet orbital graphic, readable real submission total and clear Review applications / Open Flows actions. Three compact metrics may use muted tinted surfaces, avoiding full-page neon. Rounded20 cards,12 controls,24 summary; 24px inner spacing,24px section gaps. Local Source Sans3 body15px; bold heading32px; total44px; tabular data.

Graphics: original generated 3D vinyl bot avatar atlas, locally stored. One fictional mascot also represents the user's workspace; never imply it is their photo. Bot identities retain readable platform names and descriptions. Replace thin generic navigation line icons with a reusable custom filled/duotone SVG set. Small arrows, close, check and utility icons remain familiar. No emoji icons. Brand mark is an original orbital monogram. Overview avatar shortcuts directly open bot configuration.

Overview composition: header greeting + search Applications + date/export; two columns (main flexible, right340px at wide desktop); main hero, three metrics, activity chart, recent record table; right interactive Bot Crew avatar strip, current Action inbox, saved Flow progress, Growth card. Collapse to one column below1000px, move key controls before long records. Avoid duplicated giant headings and generic KPI grids. Other routes reuse the same materials, brand, typography and avatars.

Motion: retain180ms control/320ms route entries; meaningful hover lift2px for clickable hero/crew controls, press scale.97, stagger newly entered panels by35ms (max140ms), sidebar active indicator settles without replay on polling. No endless decorative orbiting or auto-moving avatars. Reduced motion removes all transforms/transitions. Active-run pulse stays informational. Accessible labels and tests follow display taxonomy; underlying records and actions stay unchanged.

Assets/references and limitations must be logged in CAPABILITIES.md/QA.md. This is a commercial visual direction, not a claim of public SaaS readiness: local hosting and ownership boundary are unchanged.

## 11. Orbit experience refinement

The user approves the current visual direction. Retain §10; improve the control layer and the remaining task screens. No new branding or decorative motion system.

Controls: 44px minimum touch targets; custom select with top-layer dark frosted menu, selected check, keyboard arrows/Home/End/typeahead/Enter/Escape, outside dismissal, restored focus and announced expanded state. Date entry accepts ISO dates and has a custom month calendar with today/clear, weekday labels, roving arrow navigation, month navigation and a selected-day marker. Surface #242730, border #444855, shadow 0 16px 48px #0006, radius16; focus ring2px lavender with3px offset. Error text #ffb4ba, error surface #35232a; errors stay next to the responsible field and are linked with aria-describedby. Preserve drafts on failure. Loading and empty states explain what is happening and offer the relevant next action.

Charts recompute SVG geometry at the actual container width so axes remain readable on phones; reserve chart height to avoid layout shifts. Default continuous daily trend, optional stacked daily bars; straight interpolation between actual daily observations (no invented smoothing). Three readable channel colors, subtle area fill, selectable legend, crosshair and selected-date readout for pointer/touch/keyboard. Arrow/Home/End moves one date; data table exposes every value. Recompute scale from visible series, explicitly label visible total. Bars grow via transform scaleY, trend fades/slides4px on data/view changes, 420ms ease-out; no animation on hover or polling, no invented intermediate counts. Respect reduced motion. Score histogram includes bucket labels, a target marker, meaningful zero-value hit targets and keyboard/touch inspection with equivalent accessible values. Outcomes use a proportional ring plus exact totals and a text legend.

Screen composition: Flows has a saved-checkpoint progress summary and grouped numbered stages beside setup; Action inbox has priority counts, question/profile categories and persistent inline save feedback; Growth library explicitly names .research, surfaces real document categories and recent reading cards, and retains full search/reader; Reports has a custom calendar and saved-date rail beside the document; Learning path has actual completion progress, today's lesson and compact expandable tracks; profile uses illustrated file tiles and a durable save/error bar above the editor; preferences groups actual configuration keys by purpose with filtering and readable labels. No fabricated progress, streaks, authenticated state or activity.

Reusable section banner combines one existing atlas avatar with a purposeful metric and explanation. Spacing remains4/8/12/16/20/24/32; headings20/24, values32/40. Cards use existing satin material; menus/dialogs receive glass. Mobile collapses secondary rails and keeps actions reachable. Error/saving states never depend only on a toast. Textarea Enter inserts a line; Cmd/Ctrl+Enter saves inbox answers. Failed learning saves restore the original checkbox state.

Verification: all19routes at375/768/1280, custom controls by keyboard and touch, invalid fields, chart data parity/mode/legend/keyboard, failed inbox/course/file writes with intercepted requests, .research discovery, responsive screenshots, axe and production Chromium performance. External /visual-qa and beui reference packs remain unavailable as recorded in §0; use direct Playwright evidence without claiming those external gates.

Loading architecture: the production build includes the compressed JavaScript/CSS shell in
the initial document, with local external font and avatar assets. Read-only startup requests
begin in the head; later refreshes remain normal API calls. This removes a module-download
round trip without removing motion or content. Target the stated performance bar, and report
measured values honestly if the local mobile simulation remains below100.

## 12. Discoverability, profile crew and Activity

The user approves the original bot atlas and requests more matching graphics, explicit research/data navigation, per-platform profile agents and a better Activity dock. Preserve Orbit's charcoal/lavender system. Research becomes **Research Studio**, retaining #/research; add **Data hub** at #/data. Both are first-class desktop navigation items in a “Knowledge & data” group and visible in mobile More. Launchpad gets direct illustrated Research Studio and Data hub shortcuts. Research Studio keeps real .research paths, categories, search and the existing reader.

Data hub is an inventory of actual saved workspace data: all-time application attempts, discovered jobs, research notes, reports, editable profile inputs, saved flow checkpoint and resume PDF outputs. Each collection has a measured count, source path, clear destination and missing/error state. A searchable file list shows real modification dates, sizes and open actions; only supported safe sources are listed. Browser sessions, credentials and arbitrary filesystem contents are not exposed. Never imply an absent file exists. Records link with days=0; research IDs and report dates retain stable deep links. Resume downloads use a contained PDF-only endpoint.

Bot Crew grows to18 specialists: six application bots, six profile bots (Naukri, LinkedIn, Hirist, Instahyre, Cutshort, Wellfound), and six career/research assistants. Profile cards have their own identities and filter. Board profile links encode board and mode and always select profile-only; application links explicitly select apply. Practice confirmations remain; live profile actions state their effects. Status distinguishes profile-only commands from application commands. Do not reuse application run history as profile history. Pipeline checkpoints are saved history, never evidence that a standalone bot is running.

Art: extend the approved 4×4 vinyl atlas with8 new avatar portraits and8 dimensional section emblems, rendered in the same restrained lavender, mint, peach, cream and slate. Use new profile portraits for the four added agents; section emblems for Research, Data, Flows, Reports, Learning, Inbox and Preferences. Existing bot identities remain stable. Sidebar graphics28px; section graphics64–104px. Decorative assets are aria-hidden and always paired with readable labels. A local avatar picker offers all24 portraits, persists the selected index on this device, and updates the workspace profile in navigation. It does not edit a platform photo.

Activity is a compact68px desktop /60px mobile glass capsule at bottom right, with one avatar, two-line status and explicit expand control. Expanded panel is a480px-wide nonmodal activity sheet, with avatar/title, status/elapsed summary, output log, copy and stop controls; empty state guides to Bot Crew. Logs scroll within280px (expanded480px), bounded by viewport height, auto-follow only when already at the bottom, with a “Latest output” affordance when scrolled away. Escape collapses and returns focus. Collapsed content is hidden from keyboard/accessibility trees. A live run may reveal the panel without stealing focus. Mobile uses available width above bottom navigation and bounded viewport height. Layered glass belongs to the shell; log surface remains opaque and readable. Open uses opacity/translateY8px over180ms; no animated layout or idle movement. Reduced-motion/transparency preferences remain supported.

Verification: actual inventory/source parity, missing/corrupt source handling, download containment, exact profile-only command previews, persisted avatar selection, Activity idle/live/failure/keyboard states, all routes at375/768/1280 and production browser audits. No live bot or personal file changes during QA.

Asset delivery retains full1024px atlas dimensions with AVIF/WebP format negotiation; each image has a single network-selected source. Preload the local font before startup API discovery to preserve typography on cold connections. These delivery changes do not remove content or alter motion. Save screenshots of all three picker sizes and audit the final production build.

## 13. Morrow — laptop-first workspace refinement

Scope: rename the workspace, expand its mascot family, replace cramped reading layouts, paginate large collections, add preview and resilient loading. Morrow is the working product name (no trademark clearance claimed); a folded M / rising path mark replaces the planet as the primary logo. Existing crew remains the illustration system.

### Tokens and primitives
- Preserve §12 charcoal, lavender, mint and light text tokens. Glass belongs on navigation, dialogs and Activity; reading surfaces remain opaque for contrast.
- Display: locally hosted Space Grotesk variable 500–700; body Source Sans 3. H1 32/38 desktop, 28/34 mobile; section titles 20/26; body 15/24. Wordmark 26/30, weight 650, tracking −1px.
- Laptop targets 1280×720, 1366×768 and 1440×900: sidebar 216px, content padding 28px, page max 1400px; compact headers, no duplicated oversized banners. Full-width reader, max text width 880px, no archive side column. Tablet rail and mobile bottom navigation remain.
- Pagination: bounded numbered pages, previous/next, range/total and page size. Query parameters inside hash routes encode filters, page and search. Back/forward/refresh restore state. Filters reset page 1; empty results stay page 1.
- Collections: compact visual summary, horizontal categories, one searchable list/table and pagination. Dedicated full-width document reader returns to the exact collection URL.
- PDF preview: native dialog with title, inline PDF viewer, explicit download and open-tab fallback; Escape closes and restores trigger focus. Only allowlisted PDFs served.
- Profile: identity summary, avatar picker, horizontal file tabs; structured scalar fields plus source editor for complex YAML, revision-safe saving and preserved comments/unknown fields. Preferences: full-width categories, friendly labels, masked secrets, inline errors, sticky save controls. Maintenance gets its own tab.
- Motion: 180ms press/popover, 260ms filter result, 320ms route reveal, transform/opacity only. Skeleton opacity pulse only during actual loading; retain content on refresh. Reduced motion removes travel/pulse.
- New atlas: eight portraits plus eight dimensional symbols. Existing avatar selections persist. Primary logo is reusable SVG.

### Runtime contract
React owns the route boundary while existing imperative components retain their interiors. Lazy route imports use a DOM adapter inside Suspense and a retryable ErrorBoundary. Navigation/Activity survive route failures. TanStack Query v5 deduplicates GETs with bounded memory freshness; run/status and editable or credential files always read fresh and never persist in browser storage. Successful mutations invalidate server caches; failed mutations never retry. Explicit refresh bypasses freshness. Bound rendered lists and load route chunks on demand.

### Accessibility and review
Keyboard pagination/category controls, current-page announcements, status/error feedback, preserved focus during filters, PDF fallback, 44px targets, readable line length, visible focus. No page overflow at 375/768/1280/1366/1440px. Verify short laptop heights as well as width.

### Limits
Python/SQLite remains a single-user local workspace. Client caching/lazy loading cannot prove 100,000 concurrent-user server capacity; that requires tenant isolation, authentication, production database/queue architecture and measured load tests. External frontend reference pack and formal dual-oracle tools remain unavailable as documented earlier; verify with existing Chromium tests, screenshots, axe and production audits.

## 14. Daily direction and durable learning

Research Studio opens Today, with Library and Progress as URL-addressable tabs. Today answers what to read next, what is already complete today, and how far the learner has progressed. A single full-width focus card uses the existing learning mascot, real day title, day/90 progress, and an explicit reading action. Below it, a numbered reading queue shows the next saved plan day, latest dated briefing, and next unread resume topic. Never relabel an older briefing as today's. Completion is an explicit action in the reader, with saving/saved/error feedback and a reversible Reopen action. Opening a document does not mark it complete. Library retains search, bounded pagination, filters and exact return URLs. Progress shows actual dated completions/reopens, including course work; imported legacy work is labelled without invented timestamps.

Durability: course, research-document and 90-day-plan progress share `.memory/learning.json`. Import existing studied.json and research progress once, preserve originals, commit changes atomically under a process-safe lock, and surface corrupt storage errors without resetting data. CLI learning and the dashboard use the same plan. Successful mutations invalidate frontend queries. History is paginated; no per-browser completion authority. Course links use the existing hash reader and old extensionless links redirect safely.

Shell: navigation has a dedicated scroll region between the identity area and connection footer; preserve its scroll position during status updates. Visible scrollbar, keyboard focus, active item and restrained glass remain. Loader is centered within the available route/panel, with the folded M mark, a lavender progress ring and explanatory status. Rotate the ring with transform only; reduced motion uses a static mark. Compact profile summary and remove duplicate padding so the first editable field is visible on a 1280×720 laptop.

Validation: temporary-root migration/restart/concurrent updates/corruption tests; browser Today→reader→complete→history, failed-save recovery, deep links, sidebar scrolling at short laptop height, centered loading, reduced motion and accessibility. Never modify the user's real learning completion during QA.

## 15. Research Studio as a daily desk

Latest user correction: Today must expose Papers, Tech, Companies and the daily README directly. Learning and resume learning are separate destinations, not mixed into the daily briefing queue. Tabs are Today, Learning, Resume lab, Library, Progress; retain selected date in their URLs. Today uses a custom calendar, a compact daily-digest header, three full-width source sections with real saved headline previews, and clear per-section Open/Fetch/Refresh actions. No two-column reading layout. The daily README is labelled “Daily digest · README”; other dated files and long-lived research references remain reachable. If today has no files, show that honestly and offer the latest saved day without silently substituting its content.

Learning contains the 90-day next unfinished lesson, that date's goal/design briefs, saved weekly plans and course links. Resume lab lists every numbered resume topic, completion and its README overview, independently of the daily news. Progress remains shared and durable. Fetch actions carry the selected date and exact existing research-only stage to the runner, with the existing command preview and confirmation; they never run application/profile stages. Show pending, failed and saved-file states; refresh after generation completes. Existing saved content remains readable during refetch. Empty sections always explain the missing source and give the appropriate fetch action.

Use the established tokens, typography and atlas. Source section anatomy: 48px dimensional emblem, title/date/read state, 2–3 actual headline previews, explicit Open and Fetch/Refresh controls. Single-column source sections and compact digest preserve laptop readability. Tabs wrap on mobile, 44px controls and calendar focus behavior remain. Verification must cover a complete saved date and a missing date, all six daily files, separate learning/resume views, exact dated stage previews, cancellation/failure, and preservation of progress.
