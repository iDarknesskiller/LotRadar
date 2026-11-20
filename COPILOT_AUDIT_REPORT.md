# COPILOT AUDIT REPORT — Non-Scanning Button Stability, Responsiveness & Performance

Status: **Audit only. No production code changed.** For review by the Chief Architect (ChatGPT). Claude must not implement until `ARCHITECT_HANDOFF.md` is approved.

## 1. Source of truth

| Item | Value |
|---|---|
| Branch audited | `main` (= `origin/main`) |
| Full SHA | `dd3b80cda20ded45d0e10f2fc20904bbf65648e4` (merge of PR #20) |
| App version | No single version constant. Server banner `LotRadar R62` (`server.py` main); Reader `READER_REVISION='R59'` (`chrome_bridge.py:25`); extension manifest `1.9.7`. |
| Main files | `app.js` (2020 lines), `index.html`, `server.py` (1728), `core.py` (1375), `facebook_auto.py`, `chrome_bridge.py`, `chrome-extension/*` |
| Open PRs | #6, #7, #8, #10, #11, #16, #19, #21. All touch docs/installer/startup/photo-sort handoffs; none touch `app.js`, `server.py` or `core.py` Facebook-link code, except #19 (Offline Picture Sorting, only `ARCHITECT_HANDOFF.md` in its file list). Conflict risk with Findings below: low, but re-check #19 when it gains code. |

Existing automated coverage: pytest suite has **no tests for Facebook link, `confirm_published`, `track_existing`, or any button handler**. Only `tests/js/picker_logic.test.js` and `tests/browser/picker_dom.mjs` exercise UI logic (photo picker).

## 2. Test evidence

### Executed
Environment: Linux container, Python 3.12, Chrome headless via Playwright, synthetic data in `/tmp` (not committed). No real Facebook, dealer sites, Reader extension or Windows.

| Test | Result |
|---|---|
| `pytest tests` | 90 passed, 1 skipped, 43 failed, 22 errors. All failures are `test_installer_build.py` / `test_qa_kit.py` (git-tree/provenance assumptions in this worktree, Windows scripts). All 40 photo/branding tests pass. Unrelated to buttons. `node --test tests/js` passes. |
| `/api/state` latency, 100 vehicles | median 39 ms, 0.30 MB |
| `/api/state` latency, 1000 vehicles | median 366 ms, 2.52 MB |
| `confirm_published` API, 100 / 1000 vehicles | median 45 ms / 376 ms |
| In-process breakdown, 1000 vehicles | `store.state()` 17 ms; `store.backup()` 14 ms; `json.dumps(state)` 10 ms; **`decorated_state()` ≈ 312 ms (≈85% of request)** |
| `decorated_state` profile | 60,000 `photo_cache.clean_url` calls (each does `urlsplit`) from `status()` + `cover_choice()` per vehicle; 1000 `safe_photo_status`; `trade_ready.status` 148 ms/1000 |
| 5 concurrent identical `confirm_published` API calls | Server is safe: 1 succeeds, 4 rejected with `editable_listing_draft_required` (store lock + status check). Data not duplicated. |
| **UI: 3 rapid clicks on Link Facebook (browser, 1000 vehicles)** | **3 `POST /api/action` requests sent** (no in-flight guard) |
| UI: single click, 100 vehicles | 1 request; drawer re-rendered at 109 ms; success toast shown only after full response |
| UI: idle 14 s with drawer open | 0 polling requests in that window (pollers are gated; fine) |
| UI: initial load, 100 vehicles | 213 ms |

### Not executed (could not be)
Real Chrome Reader extension flow; real Facebook pages; Windows installer/updater; slow-network and timeout injection; application-restart persistence under UI; heavy concurrent scan load; true main-thread long-task tracing on user hardware; real-world photo cache (disk) latency. Findings that depend on these are labeled **Hypothesis**.

## 3. Findings (prioritized)

### BTN-001 — Link Facebook has no in-flight guard; repeated clicks send duplicate operations
- Severity: **High**
- Workflow: Link Facebook (`confirm-published`, `track-existing`)
- Location: `app.js` `onDetailAction` (lines ~1241 and 1329) → `linkAndCheckFacebook` (~839)
- Observed: Button is not disabled, no "Linking…" text, no feedback until the whole response arrives and the drawer re-renders. Each click sends a new `POST /api/action`, then `watchFacebookAuto` and `signalFacebookAutoCheck` run each time.
- Expected: Immediate acknowledgment, exactly one operation, visible progress/success/failure.
- Evidence: **Measured.** 3 programmatic rapid clicks → 3 requests (1000-vehicle data). Contrast with `create-draft` (~1213) and `open-facebook` (~1290), which do disable the button and set a busy flag.
- Root cause: **Confirmed.** Missing busy state/ in-flight guard in `linkAndCheckFacebook`.
- Fix: Per-VIN in-flight set; on valid click immediately disable button, set `aria-busy`, text "Linking…"; re-enable in `finally`. Also disable the URL input. Add idempotency: server returns existing state with `ok` when VIN already linked to the same listing id (instead of `editable_listing_draft_required` error, which shows users a misleading "failed" toast on the 2nd click even though it succeeded).
- Regression risk: Low. Must not touch scan buttons. Idempotent server path must still reject different URL/different VIN.
- Tests: JS DOM test: N clicks → 1 fetch; button disabled during, restored on failure. pytest: `confirm_published` twice with same URL returns success, different URL rejected, URL assigned to other VIN rejected.
- Benefit: Duplicate requests 3 → 1; removes error toasts after double-click.

### BTN-002 — Link Facebook latency is dominated by `decorated_state` recomputation on every action
- Severity: **High** (scales with inventory)
- Workflow: Every `/api/action` button (link, save draft, create draft, relink, trash, restore, confirm updated/removed) and `/api/state` reload
- Location: `server.py` `decorated_state` (~701), `_json` (~752), `photo_cache.status` (~675), `cover_choice` (~591), `clean_url` (~332), `trade_ready.status`
- Observed: ~45 ms at 100 vehicles, **~376 ms at 1000** per click, plus a 2.5 MB response. A user perceives this as lag, and with no feedback (BTN-001) as "click not registered".
- Expected: Action latency independent of inventory size.
- Evidence: Measured in §2. 85% of time is `decorated_state`, which re-screens photo status for every vehicle for a single-VIN change.
- Root cause: **Confirmed** for server time. Real-world cost on user hardware with a disk photo cache is a **Hypothesis** (synthetic data had no downloaded photos; real `status()` does file checks and may be slower).
- Fix (targeted, no rewrite): (a) memoize `clean_url`/`photo_url_reason` (pure functions, `functools.lru_cache`); (b) cache per-(vin,source) photo status keyed by image list + cache version, invalidated by photo cache writes; (c) optional: `/api/action` returns only the changed vehicle (`vehicle` delta) and client merges it.
- Regression risk: **Medium.** Shared photo-cache code is used by Fetch Missing Photos and export. Stale-cache bugs could hide freshly downloaded photos. Scan queues write to the same cache; invalidation must be tied to those writes. Do (a) first; it is pure and safe.
- Tests: Unit equality of memoized vs. original output; test that status refreshes after `photo_cache` save; benchmark guard at 1000 vehicles.
- Benefit: Expected to remove most of the ~310 ms at 1000 vehicles (estimate; to be re-measured).

### BTN-003 — Full-state re-render after each action
- Severity: Medium
- Location: `app.js` `setState` (338) → `render()` (347); `JSON.stringify` of per-vehicle images in `setState`; `renderDetail` rebuilds the entire drawer (innerHTML) including photo grid
- Observed: Drawer fully re-rendered at 109 ms (100 vehicles). Large inventories not measured in-browser for long tasks.
- Root cause: **Hypothesis** (design: any state change rebuilds grid and detail). `renderGrid` is capped at 60 cards, which limits cost.
- Fix: Measure first with Performance long-task trace on real data; only then consider skipping `renderGrid` when the changed vehicle is not visible. No broad rewrite recommended.
- Risk: Medium (stale UI). Tests: DOM snapshot after link.

### BTN-004 — Delayed/absent feedback and misleading success wording
- Severity: Medium
- Location: `app.js` `linkAndCheckFacebook`
- Observed: The toast "Facebook listing linked. Chrome Reader will check it…" appears only after the full round trip. On a failed Reader check there is no further error here. The toast auto-hides after 4.2 s (`notify`), which can be missed.
- Fix: Immediate "Linking…" state (BTN-001); keep error toasts longer or sticky.
- Risk: Low. Tests: toast text and duration.

### BTN-005 — Backup written synchronously under the store lock for every action
- Severity: Low (measured)
- Location: `core.py` `backup()` (362), called from `confirm_published`, `track_existing`, `relink_facebook`, `approve_draft`, `rebuild_draft` etc.
- Observed: 14 ms at 2.4 MB DB; grows with DB size, and blocks all other store users because it holds `self.lock`. Keeps 8 backups.
- Root cause: Confirmed design; not a cause of the user-reported delay at current size.
- Fix: Leave as is for now; consider backup only before destructive actions, or throttle (e.g. once per minute). Do **not** remove without Chief approval (data safety).
- Risk: High if changed carelessly (data integrity). Tests: backup exists before destructive action.

### BTN-006 — Single click depends on checkbox state captured at click time; silent failure paths
- Severity: Low
- Location: `app.js` ~1241 (`track-existing`) and `confirm-published` (1329)
- Observed: `confirm-published` sends `$('published-url').value` unvalidated; invalid URL or unchecked box produces a server error toast (`explicit_manual_publication_confirmation_required`) in raw code form. `track-existing` validates client side.
- Expected: Same client-side validation and readable messages for both.
- Fix: Share validator; map error codes to text. Risk: Low.

### BTN-007 — Personally Verified controls are redundant (removal requested)
- Severity: Low (UX redundancy; no heavy processing)
- Affected: "I personally published this listing" (`app.js:642`, id `published-confirm`) and "This is my existing listing" (`app.js:640`, id `existing-confirm`), next to Link Facebook.
- Frontend: Checkbox read at `app.js:1241` (blocks with message "Confirm that you personally verified…") and `app.js:1329` (`explicit_confirmation:$('published-confirm').checked`).
- Backend: **No dedicated endpoint, DB column or background task.** The checkbox only supplies `explicit_confirmation` to `store.confirm_published` / `track_existing` (`core.py:925`, `1008`), which raise if not `True`; `server.py` `/api/action` passes it through. Nothing is persisted from the checkbox itself; audit events are `user_confirmed_facebook_publication` and `existing_facebook_listing_manually_linked`.
- Other dependencies: Separate verification concepts exist and are **unrelated** (dealer availability confirm `confirm_used_availability`, `explicit_user_confirmation`; `#updated-confirm`, `#removed-confirm` checkboxes; Verify Inventory scan). They must stay.
- Unnecessary processing: none found. Removal gives no measurable performance gain.
- Recommendation: Remove the two checkbox labels and their client-side checks. The click on Link Facebook itself is the explicit user action; the client sends `explicit_confirmation:true` constant (as `track-existing` already does after its check). **Keep** the server-side `explicit is not True` guard and API contract (so other callers and tests stay valid). Do not delete any DB data or events. Existing links remain unchanged.
- Decision needed (Chief/Owner): removing the checkbox removes a deliberate mis-click safeguard (the UI otherwise cannot ever create a link without a valid URL, which is itself a strong guard).
- Tests: Link with valid URL and no checkbox works; invalid URL rejected; server still rejects `explicit_confirmation` missing; existing linked records unchanged.
- Scanning impact: none.

### BTN-008 — `watchFacebookAuto` polling and event dispatch after every link
- Severity: Low
- Location: `app.js` `watchFacebookAuto` (807): up to 35 polls at 1.2 s (≈42 s) per link; new call supersedes older via serial counter. `signalFacebookAutoCheck` dispatches a window event to the extension.
- Observed: Bounded, cancelable; not a cause of click lag. Repeated clicks (BTN-001) multiply these.
- Fix: Resolved by BTN-001. Risk: Low. This touches the Facebook auto-check queue (a protected scanning workflow, "Check Facebook"); do not alter queue code.

### BTN-009 — Many unthrottled pollers (hypothesis)
- Severity: Low
- Location: `app.js` ~2003–2009 (6.5 s photo status, 3 s dealer console/reader setup/cleanup status), scan timers (1.7 s, 2.8 s, 1.8 s, 2.5 s)
- Observed: Gated by `document.hidden`; 0 requests in 14 s idle with drawer open on the test dataset (conditions not met). With a scan running, 3 s pollers contend with the single threaded-per-request server and with `decorated_state`.
- Status: **Hypothesis**, not measured under scan load. Scan-related timers are out of scope; do not modify.

### Positive observations
- Server rejects duplicate link attempts safely (data integrity OK).
- `create-draft`, `open-facebook`, photo status poll have in-flight guards.
- Global `document` click delegation is registered once (`installHandlers`); no duplicate-listener evidence found for `[data-act]` buttons.

## 4. Protected functionality impact summary
| Proposed change | Scans | Photos/export | DB | Installer/updater |
|---|---|---|---|---|
| BTN-001/004/006/007 (frontend + idempotent link) | None | None | None | None |
| BTN-002(a) memoize pure URL helpers | Reads only | Pure, low | None | None |
| BTN-002(b/c) status cache / delta response | Must invalidate on scan photo writes | Medium | None | None |
| BTN-005 backup policy | None | None | **Data-safety risk** | None |

## 5. Button inventory

Legend: **T** = tested in this audit, **R** = code-reviewed only / needs further investigation, **X** = excluded (scanning).

| Control (location) | Status |
|---|---|
| Link Facebook (`confirm-published`, `track-existing`) | **T** (BTN-001/002) |
| Personally verified checkboxes | **T** (BTN-007) |
| Create listing draft | R (has guard) |
| Prepare Facebook form (`open-facebook`) | R (has guard, 3 s fetch timeout, 20 s poll) |
| Save description / Rebuild draft / AI draft | R |
| Confirm availability, confirm listing updated/removed | R |
| Padlock edit/save Facebook URL (`toggle-fb-url`, `relink_facebook`) | R |
| Trash listing / restore / cleanup trash | R |
| Copy buttons (model, mileage, stock, title, price, description, full post, compare) | R |
| Refresh vehicle (`refresh-vehicle`, card refresh) | R |
| Check Facebook (single, `check-facebook-auto`) | R — protected workflow |
| Photos: gallery prev/next, thumbnails, select/toggle, set cover, download photos, ZIP, open folder, retry preview, toggle grid, photo settings | R (photo logic has existing tests) |
| Business-card refresh/report, photo queue pause/resume/clear, trade-ready | R |
| Filters, search, sort up/down, reset, tabs, show more | R (search debounced 110 ms) |
| Import (file / external), Export, Sync feeds, theme toggle, dealer console toggle, listing trash button, dialogs close/dismiss, toast close | R |
| Reader setup / copy key | R |
| Quick Scan, Chrome Scan, Full Scan, Verify Inventory, Verify report/export/pause/stop, Check Facebook (all), Facebook cancel/retry, Fetch Missing Photos, Recheck Out of Stock, Site scan start, Scan Console, Scan dock | **X — excluded, not modified** |

## 6. Recommended implementation order
1. BTN-001 + BTN-004 + BTN-006 (frontend only, lowest risk, fixes the reported symptom).
2. BTN-007 (remove checkboxes; keep server guard) after Owner confirms.
3. BTN-002(a) memoization; re-measure; then decide on (b)/(c).
4. Measure BTN-003/009 on real data before any work.

## 7. Reproduction (synthetic)
Seed N vehicles with `MarketplaceStore.import_feed` + `create_draft`, run `server.py --no-browser`, `POST /api/action` `confirm_published`; browser test clicks `[data-act="confirm-published"]` three times and counts `/api/action` requests. Scripts were temporary and not committed.
