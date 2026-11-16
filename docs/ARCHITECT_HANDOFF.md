# ARCHITECT_HANDOFF.md

**To:** Claude — Lead Programmer  
**From:** ChatGPT — Chief Architect, LotRadar  
**Project:** [iDarknesskiller/LotRadar](https://github.com/iDarknesskiller/LotRadar)  
**Work item:** Photo picker: automatic missing-photo fetch, one progress bar, truthful counts, simplified controls, and exact click-order exports  
**Status:** IMPLEMENTATION REQUEST; no changes to `main` authorized  
**Source of truth inspected:** GitHub `main` at `b9e843111ce1ed39f7d4003dd39c06eb75724325` (2026-11-16); prior installer PR #1 is merged.  
**Version note:** The source contains the R62 photo-audit UI label and 1.9.13 auto-sort comments, but no reliable unified release version is established. Do not invent a version number. Record the Git SHA in implementation evidence.

## Request

The Project Owner supplied three photo-gallery screenshots and requests:

1. Opening a vehicle's photo picker must **automatically fetch all missing saved dealer-photo links**; no manual refresh/fetch action is required in the photo picker.
2. Automatic exterior/interior sorting must run when the automatic fetch completes, without an additional manual trigger.
3. Replace overlapping download, preview, and audit indicators with **one visible, truthful photo-job progress bar**, with one factual status line ordered **Found → Unique → Downloaded → Usable**. Keep failure reasons and counts in an expandable details section.
4. Remove the category-filter buttons (`All`, `Exterior`, `Interior`, `Unclassified`), `Select all shown`, `Unselect all shown`, per-photo `Exterior/Interior/Unclassified` dropdowns, and `auto` badges. Remove redundant **manual** `Refresh vehicle`, `Fetch missing photos`, and `Refresh photo preview` controls from the photo-picker area. Do not remove essential scanning functionality elsewhere in the application.
5. Make **either clicking a photo thumbnail or its checkbox** toggle that photo's selection.
6. Preserve selections in **chronological selection order**, not category, gallery index, or frame-preparation order. For a fresh selection in which the user clicks `1, 2, 3, 11, 14, 18, 20, 25, 4`, the selected strip and ZIP order must be exactly `01, 02, 03, 11, 14, 18, 20, 25, 04`, with ZIP files sequentially named `01` through `09`.
7. Keep existing behavior: without a saved selection, only the business-card cover and dedication image are selected (`01 + 02`), and an explicit reset-to-default action remains available. Do not reinterpret category sorting as permission to reorder the user's selected ZIP.

**Scope interpretation:** The crossed-out screenshot targets controls *inside the vehicle photo picker*. Preserve `Download selected photos (ZIP)`, the selected-order preview, a compact expand/collapse gallery control, and necessary source-dealer links. Keep global inventory scanner and dealer-verification controls outside this picker unless separately requested. If a group has no relevant action, do not render an empty toolbar.

## Current behavior (verified source, not an inferred runtime test)

- `app.js:583` `openDetail()` currently opens the drawer, starts an export preview, then fetches photo status. **It does not enqueue missing-photo downloads on open.** `requestPhotoDownloads()` at `app.js:969` is an explicit button action with `force:true`.
- `app.js:920` `refreshPhotoStatus()` polls photo status; a global interval at `app.js:1967` refreshes only in selected/pending situations. It may reset and rebuild the preview when cached photo status changes.
- `app.js:23–32` `photoDisplayOrder()` groups the grid by category; crucially, **`orderedPhotoKeys()` sorts the selected set by category rank** rather than click chronology.
- `app.js:54–70` generates the redundant filter/bulk controls, category dropdowns, sort toggle, `auto` tags, and separate audit/preview text.
- `app.js:659` builds thumbnail buttons and checkboxes separately. A gallery-thumbnail click at `app.js:1928` (approx.; find `[data-gallery-index]`) changes the preview only; the checkbox `change` handler near `app.js:130` changes selection.
- `app.js:979` `downloadPhotoZip()` submits `selection` but suppresses exports while automatic classification is running; it also supports a separate legacy prepare/export path. Ensure both paths cannot silently reorder an explicitly selected list.
- **Three independent server-side reorder points:** `photo_selection.py:get()` restores keys in frame-availability order; `PhotoSelections.save()` stores keys in frame-availability order; `photo_cache.py:select_export_frames()` rebuilds `wanted` in gallery order and optionally sorts it by photo category. Thus changing only frontend behavior is insufficient.
- `server.py:829–853` `/api/photos/export-preview` computes `photo_counts` from the cached snapshot but derives `excluded` using exported frame count, and the frontend presents `Math.max(0, pictures.length-1)` as “usable.” These are not a consistent count of current dealer-photo candidates. The screenshot shows conflicting figures (dealer gallery 39, 44 shown including cover/dedication, 78 links found, 65 downloaded, 13 failed, 43 labeled usable).
- `photo_cache.py:675–753` `PhotoCache.status()` reports accepted current-source links, downloaded, usable, excluded, and photo states; `analyze=False` omits expensive duplicate screening, so the fast and full views do **not** automatically have equivalent usable totals.
- `photo_cache.py:788–858` `enqueue()` already deduplicates a `(VIN, source)` job, reuses cache, honors failed-refresh cooldown (2 hours without force), retains a persistent queue, and calls `on_finished`. `server.py:459` wires `on_finished` to `AutoSorter.request()`. Extend/reuse these facilities; do not build a second download system.
- `server.py:1379–1391` `/api/photos/download` accepts VIN/source and invokes the cache queue. `/api/photos/selection` GET/POST and `/api/photos/export` already provide selection and ZIP paths.
- `photo_classify.py` supplies the existing automatic exterior/interior classification; it relies on the available AI listing API key and may pause/fail. User order must not depend on its success.

## Required behavior

### A. Opening a vehicle starts one bounded automatic fetch

1. When a vehicle photo drawer opens, identify the preferred *used* dealer source (Toyota primary, Mitsubishi backup only under the established rules). Read the current saved image URLs, cache state, and current queue state.
2. If saved dealer links have missing photos, enqueue exactly **one logical** `(VIN, source)` job using the existing photo queue, with cache reuse and **without `force:true`**. Treat opening the picker as explicit user intent for queue scheduling if the global automatic-suspension flag would otherwise block it, but **do not bypass the existing failed-host cooldown** or create a retry storm.
3. Reopening the drawer, rerendering, double-clicking, switching sources, or reopening after a failure must not spawn duplicate work. Keep a per-session keyed request guard plus backend queue deduplication. Queue activity may outlive closing the drawer; closing must cancel UI polling/listeners, not corrupt persistent work.
4. The automatic fetch must include **all valid known gallery links** within existing MAX_PHOTOS and rate limits, not stop when 10 images are downloaded. Already cached originals must not be redownloaded unnecessarily.
5. If the dealership *reports* more photos than captured unique links, distinguish **discovery shortfall** from **download failures**. Reuse only an existing authorized Chrome Reader/dealer discovery flow if safe and already supported. Do not invent links, launch stealth/browser bypasses, silently open duplicate tabs, or claim missing URLs were downloaded. If link discovery needs a separate architectural change, mark this as an explicit limitation with the correct next action.
6. When downloads finish, invoke the existing automatic sorting workflow exactly once per relevant completed revision where possible. Handle no-key, paused, and API-failure cases gracefully: retain the photos and selected order, show `Sorting unavailable`/`Unclassified` rather than claiming success or blocking download forever.
7. Automatically rebuild the export preview upon actual photo/cache revision changes and update one on-screen progress indicator; **do not require** the user to click Refresh photo preview. Preserve the current VIN/source, selected keys, selection order, gallery scroll, focus, and typed Facebook draft fields throughout asynchronous updates.

### B. One canonical photo progress and audit model

Use one source-scoped status payload, preferably extend `GET /api/photo-status` or introduce one narrowly scoped `GET /api/photos/progress?vin=...&source=...`; reuse existing photo queue/classifier state. It must be authorized by the existing local token and validate VIN and used source.

Define each stage and its provenance before calculating UI text:

- **Found:** total raw image link candidates actually captured from the current dealer gallery/Reader, with provenance; if only a stored link set is available, label that honestly and don't invent a raw count.
- **Unique:** currently valid candidate URLs after URL/identity deduplication and legitimate hidden/graphic filtering, for the **same vehicle and same source**.
- **Downloaded:** unique candidate URLs in that same current set whose cached original file exists and passes required identity/basic validation. Do not count stale cached URLs from earlier gallery revisions or duplicates twice.
- **Usable:** downloaded current-source vehicle images that pass export eligibility/screening (excluding graphic, hidden, exact-byte duplicates, or corrupt files); do not include the generated dedication frame or double-count the business-card cover.
- **Failed:** current-source download failures, available as expandable per-reason diagnostics with no secrets or sensitive URLs. Distinguish queued/pending, excluded, and failed. Do not conflate reported dealer gallery size, cache totals across scans, generated preview frames, or rendered thumbnail count.

The stage counts should form a traceable funnel when they share a denominator: `Found >= Unique >= Downloaded >= Usable`. If sources/stages truly cannot be reconciled, label them independently with an honest reason rather than massage numbers to match. Keep `photo_gallery_expected` (e.g., 39 on the screenshot) as a separately labeled **dealer-reported gallery count**, never the denominator for downloaded cache unless actually comparable. The selected count and rendered frame count are separate, clearly labeled concepts.

UI specification:

- Exactly **one** photo-job progress bar in the picker. It represents real queue/download/classify stages, not a fabricated 0–100 timer. Show stage text (`Queued`, `Downloading n/N`, `Sorting n/N`, `Ready`, `Partial`, `Unavailable`) and measured progress. Use an indeterminate bar when no factual denominator is known. Do not show a second “preview images ready” progress counter as a competing progress bar.
- One compact line: `Found N → Unique N → Downloaded N → Usable N`, using actual same-source audited counts and a precise separate `Selected M` label.
- Expandable `Failures (N)` detail with failed/skipped/excluded breakdown and actionable errors, not one unconditional refresh button. Avoid repeated toasts from polling.
- On completion, auto-refresh the gallery once per revision; on partial failures show honest usable selections. Explicit `Retry failed` may be shown **inside expanded failures only** if needed; no permanent manual fetch/refresh buttons in the main photo picker.

### C. Selection order is the user's click history

1. Store `selectedKeys` as an **ordered array** of stable `frame_key` identities, NOT only an unordered membership set or a category-sorted projection. A set may be used separately for O(1) membership lookup.
2. Clicking an unselected thumbnail OR its checkbox appends that key to the **end**. Clicking a selected thumbnail OR unchecking removes it. Re-selecting an earlier photo appends it at the end. A click on a checkbox must not double-toggle from event bubbling. Keyboard selection must work as well.
3. The click also previews the thumbnail; selected-strip thumbnails can remain preview-only (do not accidentally toggle/remove an item when inspecting the top strip). Show the user the ordered selection number on each grid tile and in the strip.
4. On first use with no persisted selection, default order `[cover, dedication]` (`01`, `02`). `Reset to 01 + 02` restores exactly that order. Keep the existing maximum selection constraint (current default 20) enforced consistently, with accessible feedback when exceeded; do not reintroduce a visible photo-limit control unless user expressly requests it.
5. Persist the exact ordered array **as supplied** in `photo_selection.json` using existing atomic writes and VIN+source isolation. `PhotoSelections.get()` and `save()` must not reorder by availability. Maintain a separate explicit list of missing keys after gallery revisions without mapping a missing selection to a different photo.
6. `select_export_frames()` and `PhotoSelections.export()` must iterate the validated ordered key list **without sorting by category or gallery index**. ZIP numbered filenames, `selection.json`, README order mapping, copied `facebook_photos/` folder, top selected strip, and response selected count must all agree. Category classification changes only **grid grouping**, not the selection/ZIP sequence.
7. End-to-end example: start with no saved selection, clear if needed, click `1, 2, 3, 11, 14, 18, 20, 25, 4`: the top strip and ZIP must maintain that precise chronological order. Verify again after closing/reopening, a download completion, an auto-sort result, and app restart. When photos 01/02 are preselected, the test harness must reset/deselect before re-clicking them; otherwise the semantics differ by design.
8. Prevent debounce/API races: the newest selection version wins across background preview changes, selection saves, and an immediate ZIP click. A failed save must be surfaced and must never lead to a ZIP that falsely claims the preview order was saved. Do not mutate or overwrite old selections merely because a background fetch finished.

### D. Simplify the photo picker only

Remove the crossed-out photo category filters, the select-all/unselect-all controls, per-photo classification dropdowns, `auto` captions, the visible auto-sort toggle, and the redundant manual fetch/refresh buttons **from this drawer**. Sorting should remain automatic where configured and available. Retain compact necessities: selected count/strip, `Reset to 01 + 02`, gallery expand/collapse, download-selected ZIP, open exported folder where applicable, and Toyota/Mitsubishi dealer source links. Do not remove or change the unrelated global scanner/verify/queue controls, menu actions, or existing selected-photo cover/dedication branding.

## Relevant architecture and exact files

**Primary files Claude will likely modify**

| File | Responsibility |
| --- | --- |
| `app.js` | `openDetail`, `toggleExportPreview`, `refreshPhotoStatus`, selected-order array and input events, gallery rendering, one progress display, ZIP request, stale-request/race guards |
| `photo_selection.py` | ordered-selection storage/retrieval and ZIP/folder report order; atomic persistence and validation |
| `photo_cache.py` | `select_export_frames()` ordered output; existing `enqueue/status/progress` for truthful scoped counts and automatic fetch |
| `server.py` | photo download/status/preview/export/selection endpoints; narrow progress aggregation and automatic-sort handoff |
| `photo-selection.css` and narrow photo styles in `styles.css` | simplified picker, selected sequence badges, one accessible progress bar and failure disclosure |
| `photo_classify.py` | only if needed to reliably trigger classification after automatic fetch; do not rewrite the classifier |

**Modify only if a confirmed dependency exists:** `dealer_site_scraper.py` or `chrome_bridge.py` if trace proves known gallery links are not being captured by the approved Reader flow; provide a separate finding before expanding scraper permissions.

**Do not modify:** `core.py` database schema/inventory lifecycle, Facebook posting/approval logic, Chrome extension permissions, installed data/photos/drafts, installer/bootstrap files, `migrate_legacy.py`, branding image binaries, or `main`. Do not enable Facebook posting automation.

## Implementation plan (ordered)

1. Create/continue `feat/photo-gallery-auto-fetch-ordered-selection` **from** `main` SHA `b9e8431`; keep the `docs/record-ai-development-contributions` draft PR independent.
2. Add regression tests first for ordered `PhotoSelections.get/save`, `select_export_frames`, `PhotoSelections.export`, ZIP numbering, missing keys, and category-sort independence. Confirm existing tests fail specifically on the intended old behavior.
3. Define a canonical source-scoped photo-count model using `PhotoCache.status()` and actual Reader/gallery provenance; audit fast/full analysis differences. Expose truthful counters and progress, preserving existing token checks.
4. Add automatic enqueue-on-open with `force=False`, existing duplicate suppression and failure cooldown, all valid known gallery links, and clean UI lifecycle cancellation. Do not trigger full inventory scans just to open the picker.
5. Ensure downloaded/changed photo revisions schedule the existing auto-sorter and regenerate the prepared preview automatically. Prevent stale asynchronous responses from resetting ordered selections.
6. Refactor frontend selection handling to a single toggle helper used by thumbnail and checkbox; persist exact chronological order and update render, labels, and selected strip.
7. Remove the specified redundant picker controls and wire one progress bar plus expandable failures. Maintain working links and essential ZIP/export actions.
8. Apply ordering to **all** output paths: API selection response, ZIP, manifest mapping, README, and exported local folder. Ensure a category sort never changes a manually selected sequence.
9. Run unit, integration, UI, and real Windows 10 smoke tests; capture exact command outputs and screenshots showing the requested sequence, one status/progress display, and source gallery counts. Rebuild/install using normal private asset packaging only when owner approves a release candidate.
10. Return `CLAUDE_IMPLEMENTATION_HANDOFF.md` and executed test logs to ChatGPT/Gemini for review. Do not merge or release.

## Protected functionality

- Toyota preferred / Mitsubishi fallback only under existing same-VIN rules; never mix photos from both sources in one export.
- Dealer URLs, VIN identity, source isolation, exact-byte duplicate detection, photo quality screening, and original cache immutability.
- Photo 1 business-card cover; photo 2 dedication graphic; production-only private branding assets. Export works as a copy; originals remain byte-identical.
- Existing bounded worker queue, persistent pending jobs, failed-host cooldown, priority, rate limiting, safe photo hosts, and Chrome Reader pairing/permissions.
- Saved selections keyed to VIN+source and existing client draft edits.
- Trade-in priority rules, inventory verification, Facebook state/draft lifecycle, and installer rollback/data protections.

## Acceptance criteria (must be demonstrated)

1. Opening a picker with missing known links queues automatic missing-photo downloads; reopening it five times does not increase distinct job count; no manual refresh/fetch action required.
2. Opening a fully cached vehicle starts **zero** new network downloads. A failed-host cooldown prevents infinite retrials, and invalid/unavailable links display a truthful partial state.
3. When automatic downloads finish, classification is requested automatically; if no classification key is available, no false classification occurs and manual selection/ZIP remain usable.
4. One and only one visible job progress bar; one status line in the requested stage order; failures in a disclosure. For same-scope stage counts: `Found >= Unique >= Downloaded >= Usable`; no fabricated counts. The screenshot's 39/44/65 discrepancy is explained by provenance and corrected, not silently rounded.
5. Crossed-out filter/bulk buttons, per-thumbnail dropdowns, `auto` tags, and three redundant refresh/fetch buttons are absent from the picker. Existing essential controls still operate.
6. Thumbnail and checkbox clicks select/deselect the **same** key exactly once. Re-select appends to the end. Keyboard interaction also works.
7. In a new/reset selection, clicking `01, 02, 03, 11, 14, 18, 20, 25, 04` in that order produces that exact ordered strip, saved keys, ZIP file-to-image correspondence, and folder contents. Export filenames remain `01`–`09`; category sort never changes selection order.
8. After picker close/reopen, app restart, fetch completion, and category update, selected photo order and any typed draft fields remain intact. Missing gallery entries are reported, not replaced.
9. No original dealer photo is overwritten, deleted, or changed (SHA-256 before/after); exports do not post to Facebook.
10. No changes to unrelated scanner, extension permission, or installer behavior; no private database, images, tokens, or customer data committed.

## Required tests — actually execute, do not merely describe

- Python tests for ordered keys on GET/save/export, defaults, max selection, duplicate/missing identities, restored order across reopen, source separation, and exact ZIP `selection.json`/README/filename order.
- Backend HTTP/API tests for token rejection, VIN/source validation, scoped counts, queue deduplication, 2-hour cooldown, empty/no-link states, all-known-link fetching, auto-sort scheduling, and truthful partial failures.
- JS DOM/event tests for thumbnail + checkbox event semantics (including keyboard and no double toggle), selected-strip ordering, debounce/race behavior, pending preview updates, single progress bar, and removal of old controls.
- Test the sequence `01, 02, 03, 11, 14, 18, 20, 25, 04` exactly, including after reorder from exterior/interior classification and ZIP download. Test deselect/reselect: it moves to the end.
- Real Windows 10 standard-user smoke test with a disposable/synthetic vehicle or approved non-sensitive dealer vehicle: open, auto-fetch, watch download then auto-sort, verify counts, export ZIP, compare original-photo SHA-256 before/after, verify no duplicate browser tabs or unexpected Facebook actions.
- Run existing `python -m unittest discover -s tests -v` and every newly added test. Provide commands, OS, PASS/FAIL/SKIP, and exact evidence. Windows 11, OneDrive installation, and R3 symlink test remain the owner's **waived release-platform tests**, not blanket waivers for new photo functionality.

## Risk areas

- **Data integrity:** `PhotoSelections.get/save` currently discards the supplied order. Atomic write must remain intact; no automatic reset of existing VIN+source selections.
- **Race conditions:** picker-open enqueue vs repeated requests; async preview invalidation vs persistence; stale VIN/source callbacks; auto-sort finishing while user is selecting; click then immediately download.
- **Incorrect counts:** raw gallery count vs stored-link set vs current cache vs generated dedication/export frames; exclusions may change after full image screening. Do not compute usable as `preview.length - 1`.
- **Queue overload:** opening many vehicles must not overwhelm dealer/CDN requests or bypass request caps, backoff, global worker controls, or suspension policies.
- **Export correctness:** ZIP order, saved folder, selection metadata, README and UI must agree; an automatic category grouping cannot reorder explicit user clicks.
- **Availability:** missing/dead dealer links or no AI key should produce honest partial status, not endless spinner or false completion.
- **UI:** modal scroll and focus preservation, disabled states, accessibility, rerender flicker, narrow viewport, and zero extra refresh buttons.
- **Security/privacy:** tokenized loopback APIs, source URL allowlisting, cache path containment, no sensitive URLs or tokens in diagnostics, and no Facebook publication.

## Git instructions

- Start from approved GitHub `main` at `b9e843111ce1ed39f7d4003dd39c06eb75724325`, unless a **new** approved main commit appears before implementation (then record new SHA and rebase safely).
- Create or continue feature branch **`feat/photo-gallery-auto-fetch-ordered-selection`**. Commit focused code/test changes there. If this handoff appears in `docs/ARCHITECT_HANDOFF.md`, retain it as the project's review artifact; runtime packaging excludes `docs/`.
- Do not touch unrelated draft PR #2. Do not push private assets or runtime data.
- Open or update a **draft** pull request and provide the exact head SHA, changed files, executed test evidence, and open risks to Gemini and ChatGPT.
- **Do not merge into `main`; only the Project Owner can authorize a merge after independent QA.**

## Handoff destination

**Claude — Lead Programmer.** Implement the specified engineering objectives on the feature branch, return a tested implementation and `CLAUDE_IMPLEMENTATION_HANDOFF.md` for Gemini's independent QA. This is not authorization to change production installations.