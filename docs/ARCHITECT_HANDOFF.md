# ARCHITECT_HANDOFF.md

**To:** Claude — Lead Programmer  
**From:** ChatGPT — LotRadar Chief Architect  
**Task:** Finish photo-gallery QA, integrate approved logo baseline, and deliver verifiable Windows/browser evidence  
**Repository:** https://github.com/iDarknesskiller/LotRadar  
**Active feature branch:** `feat/photo-gallery-auto-fetch-ordered-selection`  
**Draft pull request:** https://github.com/iDarknesskiller/LotRadar/pull/3  
**Audited feature HEAD:** `60490cd480c45d36152ef919a0035374930d5f04`  
**Latest approved `main`:** `763fb8bad8a86172837db5600f04f1b40f1812be` (merged radar-branding PR #4)  
**Source/version note:** Git documentation reports no single canonical app version; existing `R62` in scanner README and Chrome Reader version `1.9.7` are distinct from package provenance. Record complete SHA and build manifest version in evidence.

## Request

Finish the Project Owner's photo-gallery improvements: automatically fetch missing dealer photos when opening a vehicle, automatically sort after fetching, show a single truthful progress indicator and the sequence `Found → Unique → Downloaded → Usable` with expandable failure detail, remove redundant photo picker controls and category dropdowns, select/deselect by clicking the photo or checkbox, and retain the exact sequence of selection clicks in selected preview, persisted selection, downloaded ZIP, and local exported folder. The Project Owner's explicit order example is `01, 02, 03, 11, 14, 18, 20, 25, 04`.

Gemini's audit of feature HEAD `60490cd` reports **67 Python tests passed; 9 Node VM tests passed**, but says actual Windows 10 launch, browser DOM behavior, live photo-download loop, and Facebook text-editor stability have **not** been verified. Those tests are the blocking scope, not a mandate to redesign the system.

## Current behavior (verified source)

- `app.js` owns `photoSelection.keys` as an ordered array, `togglePhotoKey()`, `selectionChanged()`, `persistPhotoSelection()`, the thumbnail/checkbox handlers, one `<progress>` display, and `startPhotoAutoFetch()` / `watchPhotoProgress()`.
- `photo_selection.py` `PhotoSelections.get()` and `.save()` maintain key order rather than gallery order. A missing photo is recorded separately; default choice is cover + dedication. Limit defaults to 20.
- `photo_cache.py` `select_export_frames()` names selected files sequentially in input key order and no longer sorts by gallery/category.
- `server.py` includes authenticated `GET /api/photos/progress?vin=&source=` and `POST /api/photos/open`; the latter enqueues `force=False, explicit=True` with existing per-(VIN,source) dedup and failed-host cooldown.
- `photo_cache.py` still holds the real download queue and calls the existing auto-sort hook at completion. The source progress funnel reports **saved candidate links**, not a verified external-gallery discovery provenance count; do not label `found` as independently captured gallery counts.
- `app.js` progress polling currently calls `renderPhotoControls()` on an unchanged stage, which itself calls `renderDetail()`. Actual DOM preservation of focus, scroll, input composition, and text selection is *not established* by the isolated VM tests. Treat this as a specific regression risk to test, not a pre-proven failure.
- PR #3 is currently `open`, `draft`, head `60490cd`, and GitHub describes it as mergeable but **diverged** from newly approved `main` `763fb8b`. The logo integration in `main` modifies `server.py`, `styles.css`, and packaging; PR #3 modifies `server.py` and `app.js`/photo selection files. Automatic mergeability does not substitute for integration tests.

## Required behavior

1. On opening the photo picker, the chosen vehicle/source is examined and missing *known* photo links are automatically queued exactly once, without repeated downloads, bypassing global suspension only for the explicit open but respecting safety and failed-host cooldown. If the dealer has not supplied all links, show an honest discovery shortfall instead of inventing URLs/photos.
2. One coherent status component must reflect the true current vehicle/source: `Found → Unique → Downloaded → Usable` plus selected count, phase, progress, and expandable failures. Never combine totals from Toyota/Mitsubishi, alternate vehicles, originals, and generated dedication/cover assets in one misleading count.
3. Auto-sort should run after new photos are downloaded, without modifying source photos or shuffling already selected user order. Sorting can affect display categories, **not** selected export sequence.
4. Clicking an actual photo tile **or** its checkbox toggles the same key exactly once. Clicking a selected photo removes it; reselecting appends to the end. The separate selected-preview strip can remain preview-only where explicitly marked.
5. The selected strip, saved `photo_selection.json`, ZIP `photos/01…N`, `selection.json`, README mapping, and written local folder must reproduce the exact user click order. Cover/dedication are the default selection only for vehicles without a previously saved selection; user modifications override defaults.
6. Progress polling and preview reloading must not corrupt a Facebook draft in progress, switch another vehicle's source, reset scroll/focus during photo operations, or disable normal navigation.
7. Public repository code and production installer must retain the officially merged **190px radar brand** without committing private logo images or changing the verified `LotRadar.ico` use.

## Relevant architecture / affected files

| File | Responsibility / expected action |
| --- | --- |
| `app.js` | DOM events, ordered selection, progress polling, preview rebuild, focus/scroll preservation. **Modify only if actual test identifies a reproducible defect.** |
| `photo-selection.css` | Photo picker and single progress indicator. Check desktop/high-DPI/short-view height; modify only on confirmed UI defect. |
| `server.py` | Photo APIs, validation, source scoped progress. Merge reviewed branding/static-route changes from current `main`; ensure both behaviors coexist. |
| `photo_selection.py` | Ordered persistence and ZIP/folder path. Keep stable keys, limit and source isolation. |
| `photo_cache.py` | Queue dedup, cooldown, downloaded/usable counts, export order, original-photo integrity. |
| `photo_classify.py` | Post-download auto-sort integration; avoid changes unless an actual sorting failure is demonstrated. |
| `tests/js/picker_logic.test.js` | Existing Node VM tests; supplement with **real DOM interaction test** using a browser if feasible. |
| `tests/test_photo_selection_order.py`, `tests/test_photo_progress_api.py`, `tests/test_photo_cache_enqueue_policy.py` | Extend only for confirmed missing edge cases. |
| `scripts/build_installer.py`, `docs/INSTALL.md` | Current `main` branding/private-assets rules must survive integration; rebuild a **private** DEV/PROD package using published guidance. |
| `tests/windows/Get-LotRadarEvidence.ps1` | Read-only before/after SHA-256 photo preservation audit. |
| `Marketplace Bootstrap.ps1`, `Launch Marketplace Scanner.cmd`, `installer/Install-LotRadar.ps1` | **Do not redesign or alter**. Preserve launcher, installer locks, rollback and data separation. |

## Implementation / validation plan (ordered)

1. **Freeze facts.** Verify local working tree, remote branch and `main` SHA. Back up any live profile data before touching the installed application. Record installed package identity and Chrome Reader version. Use a *separate test VIN*, no public disclosure of customer data.
2. **Integrate newly approved `main`.** On `feat/photo-gallery-auto-fetch-ordered-selection`, merge the approved `origin/main` `763fb8b` (or use a carefully controlled equivalent workflow) without discarding either the 190px logo, secure `/branding/...` routes, or the photo APIs. Do not merge PR #3 into `main`. Record the resulting feature HEAD and changed-file comparison. If HEAD changes, all subsequent evidence and Gemini review must refer to that new SHA, not stale `60490cd`.
3. **Run all source tests** after integration: `python -m unittest discover -s tests -v`, `node --check app.js`, `node tests/js/picker_logic.test.js`, and installer/package verification appropriate to the build. Do not infer Windows or DOM success from these tests.
4. **Add/run real DOM tests** using an actual browser against the local LotRadar UI with synthetic/test vehicle data. Capture a test transcript, screenshots, console errors and unexpected network calls. Exercise clicking photo vs checkbox, double-trigger prevention, reselect-to-end, ordering, keyboard activation, rapid clicking, 20-photo limit, source switch, close/reopen, page scroll, long thumbnail strips, and missing photo behavior. Verify all controls removed by the Owner are actually absent, and the single progress bar remains.
5. **Run Windows 10 standard-user end-to-end check** against one intentionally partially cached *used* Toyota vehicle with a backup Mitsubishi source when available. Open the vehicle picker and observe requests to `POST /api/photos/open`, `GET /api/photos/progress`, one real download queue job, successful/failed paths, honest `Found/Unique/Downloaded/Usable`, completion/auto-sort, and gallery refresh without manual intervention. Use application logs and source-scoped API results as evidence; never substitute a mocked download for the only live check.
6. **Verify exact export order:** reset to `01+02`, select `03, 11, 14, 18, 20, 25, 04` by alternating photo clicks and checkbox clicks. Confirm the preview and saved selection order `01, 02, 03, 11, 14, 18, 20, 25, 04`. Close/reopen and verify persistence. Download and examine ZIP file ordering, metadata and local export folder. Deselect `11`, then reselect and verify it becomes the last item, including after restart.
7. **Check Facebook draft typing under polling.** With a deliberately unsaved description and cursor in the middle, let the photo queue progress through queued, downloading, sorting, terminal states; verify typed text, focus, selection range and editor state remain unchanged. Test switching to another vehicle during a request and back; no stale response should overwrite current UI.
8. **Verify originals unchanged.** Snapshot original dealer photos for the chosen VIN with `Get-LotRadarEvidence.ps1 -Mode PhotoSnapshot` to a CSV **outside** LotRadar data before export; run `-Mode PhotoCompare` afterward. Require zero changes and zero deletions to original image bytes, record additions separately, and explain any simultaneous background fetches. Export cover + dedication and verify the radar logo was **not** inserted into vehicle photos.
9. **Re-run Windows launch/installer smoke and branding regression** (sidebar 190px, dark/light, browser favicon and shortcut use). In production packaging, logo/business-card/dedication/ICO remain private assets. Keep Windows 11, OneDrive, R3 file-symlink waivers visible and do not claim those tests passed.
10. **Evidence and re-audit.** Send `CLAUDE_IMPLEMENTATION_HANDOFF.md` with exact HEAD SHA, executed command lines, outputs, Windows build/PowerShell, browser/version, screenshot references or sanitized descriptions, export-order proof, before/after SHA counts and residual issues. Gemini must independently audit the *post-integration* HEAD; then return to Chief Architect and Project Owner. No merge before explicit owner approval.

## Protected functionality

- `%LOCALAPPDATA%\MarketplaceScanner\data`, SQLite, inventories, saved Facebook drafts, VIN/source mappings, original dealership photos and manifests; preserve one-time migration, installer backups and rollback.
- Existing pre-approved 190px radar logo, browser favicon, Start-menu/Desktop icon, private asset restrictions, and installer manifest provenance.
- Chrome Reader pairing, read-only dealer retrieval, Toyota default / Mitsubishi fallback, existing used-only inventory behavior; do not publish Facebook listings or create duplicate Chrome tabs.
- Dealer-photo original byte integrity, business-card cover and dedication photo ordering, Facebook privacy and local-only token/host restrictions.
- Installer and bootstrap concurrency interlock, download queue cooldown, error handling and in-progress job dedup.
- PR #5 startup window work and PR #2 contributors-doc task are **outside scope**.

## Acceptance criteria

1. Current `main` logo changes and PR #3 photo changes coexist at a single identifiable feature HEAD. A diff shows no accidental branding regression.
2. At least one real Windows 10 normal-user vehicle fetch and completion is captured with accurate request/status evidence; source-level unit tests alone do not pass this gate.
3. A real browser DOM test proves photo click and checkbox click toggles produce the same ordered result; neither generates duplicate event toggles. 20-photo limit is respected.
4. Owner example order `01,02,03,11,14,18,20,25,04` is identical in selected preview, persisted configuration, exported ZIP/README/selection.json and local export folder. Removal then re-adding moves an item to the end.
5. One coherent status/progress indicator; honest per-source counts; failed-host/cooldown and missing links are explained without impossible percentages or indefinite "done" claims.
6. Auto-sort after actual fetching does not reorder saved selection or corrupt originals.
7. Switching vehicles or editing a Facebook draft while background progress updates occur does not reset text, caret, focus, scroll or live vehicle identity.
8. Before/after SHA evidence reports 0 changed and 0 deleted original image files; data/SQLite/drafts remain preserved.
9. Latest Python, Node, DOM, Windows and production-package tests actually run and pass, with any skips/waivers explicit.
10. No unauthorized changes to main, public private-image exposure, runtime installer, extension or unrelated scanner functionality.

## Required tests (must actually be executed)

- `python -m unittest discover -s tests -v` (Linux/Windows environments as available)
- `node --check app.js` and `node tests/js/picker_logic.test.js`
- Browser DOM integration tests, preferably in real Chromium/Chrome; report browser version, actual click/focus events, screenshots and console logs
- Windows 10 non-admin launch and photo open/auto-fetch/live download/auto-sort/selection/ZIP smoke tests
- Windows photo hashes: `tests/windows/Get-LotRadarEvidence.ps1 -Mode PhotoSnapshot -Vin <TEST_VIN> -OutFile <PRIVATE_CSV_OUTSIDE_DATA>`, one real export, then `-Mode PhotoCompare -Vin <TEST_VIN> -BeforeFile <SAME_CSV>`
- Test no duplicate queue on repeated picker open; cooldown behavior on failed host; source switch / stale response rejection
- Browser draft typing/focus/scroll regression while progress polling
- Installed branding, local-only API token guards, output package provenance and private asset checks

## Risk areas

- Stale PR #3 branch relative to approved `main`; `server.py` branding + photo endpoint integration conflict or untested combined behavior.
- `renderDetail()` on recurring progress polling replacing active DOM, destroying Facebook input focus, caret, composition or scroll despite stage-change-only preview rebuilding.
- Race between auto-fetch stage completion and preview revision changes; false 409/stale URL; losing dirty selection during asynchronous save.
- Duplicate job scheduling, cooldown bypass, failed hosts, downloading incomplete albums, reporting "found" as a discovery count when it is only cached candidate link count.
- Selecting duplicate or missing frame keys; source fallback switching Toyota/Mitsubishi while the selection belongs to the original source.
- Photo export order silently reordered in a less-traveled path (ZIP vs local folder vs `selection.json`).
- Installer production build with newly mandatory logo/ICO assets; no private artifacts in public GitHub.

## Git instructions

Continue **only** `feat/photo-gallery-auto-fetch-ordered-selection` / Draft PR #3. Integrate approved `main` SHA `763fb8bad8a86172837db5600f04f1b40f1812be`, preserve the exact branch HEAD transition and rerun all tests. Do not edit or merge directly to `main`; **the Project Owner must explicitly authorize a merge after Gemini QA and Chief Architect approval**. Do not touch PR #5 or publish private packages/assets. No automatic release or user data migrations.