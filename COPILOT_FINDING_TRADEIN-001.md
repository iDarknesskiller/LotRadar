# COPILOT_FINDING_TRADEIN-001 — Trade-in priority and automatic discovery/photo downloads

## A. Finding identity
- Finding ID: TRADEIN-001 (work order LR-009, PR #11)
- Title: Trade-in priority photos have no automatic starting point; automatic discovery, download scheduling and renewal tracking are absent
- Date: 2026-11-19
- Repository: iDarknesskiller/LotRadar
- Approved main SHA inspected: `a52bf1d8bcc88a740267bfa5c0226beb4587e67a` (`origin/main`). The existing scan report in this PR audited `a5d1754`; the two are not claimed identical.
- Affected PR/SHA: none; relates to PR #11 findings LR-SCAN-02, -05, -07, -09.
- Category: Photo processing, scanning, UI, Facebook listing preparation
- Proposed severity: P2 (essential workflow gap, no data loss demonstrated)
- Confidence: MEDIUM — source-level mechanisms verified; nothing reproduced at runtime
- Investigation status: VERIFIED SOURCE DEFECT / design gap, plus HYPOTHESES where stated

## B. Executive summary
Trade-in photos (stock number ending in a letter) are not ready when clicked. Nothing downloads them automatically, and their download order has no defined starting point. The Owner wants automatic discovery, trade-in-first background downloads that fall back to regular stock, a single Repair/Fix button next to Quick Scan, and a separate Facebook renewal check.

## C. Current behavior (source, `main` a52bf1d)
- Trade-in downloads start only from the "Get trade-in priority ready" button (`app.js:1192` -> `/api/trade-ready`, `trade_ready.py TradeReady.start/run`), a scan import (`server.py imported_photos`) or opening the picker (`/api/photos/open`). The 60 s UI poll uses `prepare:false` (`app.js:1645`), which only checks readiness.
- `is_trade_in` (`trade_ready.py:4`): `toyota_used`/`mitsubishi_used` record with a stock number ending in a letter. Owner confirms this is the definition.
- Order: `TradeReady.run` iterates trade-ins in store order and sets level-1 priority for each; `VehiclePriorityQueue.rank` (`photo_cache.py:394-399`) prefers the latest deadline, so the effective start is arbitrary (reverse store order). The grid "priority" sort (`app.js:446-456`) is display-only; the sort arrows only flip to price low/high.
- Priority expiry: level 1 lasts 24 h, level 2 lasts 30 min (`photo_cache.py prioritize`).
- `clear_queue()` sets persisted `automatic_suspended`; `enqueue` then drops non-explicit requests (`photo_cache.py` ~792).
- Failure cooldown: non-forced enqueue skips vehicles with a failed photo for 2 h. Dealer refresh uses `refresh_policy.py` (24 h success, 30 min failure).
- Preemption already exists: `_download` yields when a higher-ranked job is queued (`photo_cache.py` ~870), and the queue falls back to lower ranks when no higher work exists.
- Photo workers: fixed at 3 (`photo_cache.py` ~436). No adjustable photo-speed control was found in `main`.
- No startup auto-scan, no scheduler, no random midnight-4 AM Central window, no keep-awake handling. Fresh install shows an empty inventory until the user clicks Quick Scan (`app.js:1912`). `system_load.py` samples Windows CPU/memory but throttles nothing.
- "Age in LotRadar" is available: `vehicle_first_seen` (`core.py` ~304, written once by `INSERT OR IGNORE` ~485, exposed as `first_seen` ~679). It is independent of last refresh. Caveat: a VIN that disappears and returns keeps its original date (NOT TESTED).
- Facebook: `record_link_check` (`core.py:1227`) stores only `reachable|unavailable|check_failed`. No posted date or renewal state exists; `drafts.updated_at` changes with edits. Out-of-stock is inferred from unavailable links (`core.py:1265`).

## D. Expected behavior (Owner requirements, not independently verified)
1. Trade-ins always rank first and are processed in a defined order; when none are pending, regular stock is processed; trade-ins preempt again when they appear.
2. Scans collect quick info; photo downloads run in the background; fresh installs start discovery automatically; one nightly scan at a random time 00:00-04:00 Central; up to ~80% CPU as an upper target; no artificial resource use.
3. Failures never mark vehicles out of stock; Toyota and Mitsubishi fail independently; unfinished jobs resume.
4. Visible controls reduce to Quick Scan and one Repair/Fix; Facebook checks remain separate.
5. Facebook listings need renewal about every 7 days; existing listings' ages must be discovered.

## E. Proposed trade-in score (Owner-specified shape; weights are unvalidated guesses)
Applies to unposted, not-ready trade-ins only; highest first.
- Model year relative to current year: 2-4 years back +40; 5-8 back +25; all others +10.
- Age = days since `first_seen`: points rise with age, capped (placeholder +0.5/day to +40 at 80 days; cap threshold is an open Owner decision).
- Ties: oldest `first_seen`, then VIN. Missing data scores 0 for that factor. Posted or ready vehicles are skipped.
- Queue deadlines must ascend with rank so the top-ranked VIN downloads first. Same order should drive the Trade-in tab.
- Two tiers: tier 1 trade-ins (decided by `is_trade_in` at enqueue, not by a 24 h timer); tier 2 regular stock only when tier 1 is empty.

## F. Reproduction
NOT RUN. Source-level only. Suggested synthetic reproduction: temp store with trade-in and regular VINs, fake downloader; assert (a) nothing queues without `/api/trade-ready`, (b) order of downloads, (c) priority after 24 h, (d) behaviour when `automatic_suspended` is set.

## G. Root cause (verified facts vs hypotheses)
Verified: no code path calls `trade_ready.start(prepare=True)` or an explicit enqueue for the trade-in set except the manual button; ranking is timer-based and unordered within level 1.
Hypotheses: Facebook exposes a listed date/renewal state on the Owner's listings page; Windows keep-awake/locked-screen operation works with the existing launcher; overnight capacity can reach ~80% CPU safely.

## H. Impact
Trade-in photos missing or "pending" when clicked; stale priority after 24 h; manual-only workflow; redundant overlapping buttons and code paths. No data-loss risk shown.

## I. Proposed solutions (advisory only)
1. Minimal: a `TradeReady.auto_loop` background thread (60 s check; start prepare when the trade-in/URL signature changes or every 10 min while not ready; no dealer-page refresh; respects pause and cleared queue). A prototype was written and compile-checked on a scratch branch earlier, never executed; it is not part of this PR.
2. Tiered queue: rank = (tier, score) computed at enqueue; replace 24 h expiry with "trade-in and not ready"; ascending deadlines within tier.
3. Optional import hook: queue trade-ins immediately after each scan import.
4. Full automation (separate work): first-run scan, randomized nightly scheduler, CPU governor using `system_load.py`, catch-up/maintenance modes, console fields (next scan, pending, failures).
Recommended: 1+2 first (smallest, reversible); defer 4. Tradeoffs: option 3 touches the scan import path (higher regression risk); option 4 uses live dealer sites and needs authorization.

## J. Redundancy cleanup (once the downloader exists)
- Keep: Quick Scan, one Repair/Fix, Photo settings, scan console/dock, Pause/Stop/Cancel controls.
- Remove or merge into Repair/Fix: Fetch Missing Photos, Get trade-in priority ready, Rescan Everything, Refresh & Verify, Recheck Out of Stock, Full Scan (already hidden), Historical link discovery. Import working scan is a data tool, not a scan.
- Overlapping code paths to consolidate: scan-import auto-enqueue, 60 s readiness poll, `missing_photo_targets`, the 2 h and refresh-policy cooldowns, `_fix_trade_scope` (one-time).
- Facebook checks stay a separate scan.

## K. Facebook renewal (separate finding candidate, TRADEIN-002)
Missing: a stable posted date and renewal state. Candidate sources: Facebook listing page (best, unverified, needs Owner authorization and read-only testing), `facebook_listing_captures.captured_at` (lower bound), `drafts.updated_at` (weak). Fallback: "age unknown" list oldest-capture first, then store a posted date at user confirmation. Flag renewal at about 7 days; never post, edit or change out-of-stock status.

## L. Dependencies on PR #11 findings
- LR-SCAN-09: a photo worker can die on a persistence error and is not replaced -> auto-download must add worker liveness or follow this fix.
- LR-SCAN-05: restored queue can be paused -> the loop skips paused queues.
- LR-SCAN-02: first-source-only photo eligibility -> trade-ins with two dealer sources need source-specific completeness.
- LR-SCAN-07: cooldown vs "Rescan" wording -> reconcile cooldowns.

## M. Protected files and functionality
Original dealership photos, manifests, cover preferences, queue persistence, VIN/source identity, SQLite records and backups, Facebook drafts, Chrome Browser Reader sessions, installer safeguards, `%LOCALAPPDATA%\MarketplaceScanner\data`.

## N. Regression risks
Extra startup CPU/network; contention with scan photo work; forced retries every 10 minutes against a blocked image host; interaction with pause, `automatic_suspended` and queue restore; score changes reordering the Trade-in tab; removal of buttons users rely on.

## O. Recommended tests (not yet written)
- T1 trade-in with URLs is queued automatically; non-trade-in is not.
- T2 paused or suspended queue: nothing queued.
- T3 unchanged signature and all ready: no repeated start.
- T4 failed host: retry no more than once per window.
- T5 automatic run never calls `refresh_gallery`; manual run still does.
- T6 score ordering: 2-4 yr > 5-8 yr > others; age rises then caps; ties by `first_seen` then VIN; ascending deadlines give the top VIN first.
- T7 two tiers: a new trade-in preempts a running regular download; regular stock resumes when tier 1 is empty; no 24 h expiry.
- T8 dying photo worker is detected and replaced (with SCAN-09).
- T9 re-listed VIN `first_seen` behaviour (documents the caveat).

## P. Actual test results
- Environment: Linux 6.12.115, Python 3.12.3. Not Windows; no Windows UI or locked-screen verification.
- Command: `python -m unittest discover -s tests` at a52bf1d, clean tree. Result: FAIL as baseline — 106 run, 7 failures, 41 errors, 1 skipped, about 7 s. Observed causes include missing `bs4` and `PIL` and installer-build guard tests; not further investigated. The same counts appeared with the earlier prototype applied, which proves nothing about the prototype.
- Prototype `py_compile`: passed. Prototype never executed. No new tests written. No live scans, Facebook actions or private data used. No performance measurements; all performance statements are hypotheses.

## Q. Duplicate check
Open issue #6 (read-only performance audit) and PR #11 findings above; no existing issue or PR covers trade-in auto-download, tiering, renewal or the button cleanup. Open PRs #6/#7/#8/#10/#16 are installer/startup work and not related.

## R. Open questions
Age cap (placeholder 80 days); where the adjustable photo-speed control lives (not in `main`); whether Facebook exposes listing age/renewal and where; renewal interval (Owner: about 7 days) and renew-vs-relist action; whether regular-stock order stays as today; re-listed VIN handling.

## S. Final recommendation
Architect to verify and decide scope. Suggested order: SCAN-09 and queue liveness; source-specific eligibility; tiered score queue plus automatic trade-in loop; button consolidation; then scheduler/first-run automation; Facebook renewal as its own finding after discovery.

## T. Approval status
PENDING CHIEF ARCHITECT VALIDATION.
PENDING PROJECT OWNER IMPLEMENTATION AUTHORIZATION.
NOT ASSIGNED TO CLAUDE.
Delivery to the Chief Architect: not sent; Owner-mediated handoff.
