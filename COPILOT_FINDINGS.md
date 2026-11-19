# Scan improvements and stability

Source: `main` at `a5d1754bec01a5bf11d492bbc8f7c585237404dc`

Audit date: 2026-11-19

Scope: scan controls, scan admission, dealer and photo queues, verification, listing-link checks, and related performance.

## Audit verdict

| Finding | Audit verdict |
| --- | --- |
| Historical scan Stop | **Reproduced synthetically:** the worker continued after Stop reported it inactive. The test did not use a real browser. |
| Concurrent scan starts | **Reproduced with the actual route logic**, mocked dependencies, and controlled thread timing. Sequential starts are normally blocked; this is a race, not unrestricted overlap. |
| Quick Scan cross-dealer skip | **Reproduced synthetically** when both dealers use the same URL path. Whether that path collision occurs in current live inventory is unverified. |
| Rescan Everything cooldown | **Reproduced synthetically.** The button's wording promises more than the cooldown policy does. Whether an explicit rescan should override cooldown needs a product decision. |
| Missing-photo source selection | **Reproduced synthetically:** a complete first dealer can exclude an incomplete second dealer. |
| Verification timeout | **Reproduced with an accelerated mock:** Facebook checking can start afterward, and the final result is marked **partial**, not an unqualified success. Whether to stop or deliberately continue needs a product decision. |
| Unreadable-page early abort | **Reproduced synthetically:** queued pages remained after four timeouts. The separate headless 403 safeguard is not affected by this finding. |
| Photo worker persistence failure | **Reproduced with an injected disk error:** one worker exited. Real-world frequency and recovery impact are unmeasured. |

These are investigation findings, not implemented fixes. Priorities are proposed, not final; no data corruption has been demonstrated.

## Findings

### LR-SCAN-01: Concurrent historical and Chrome scan admission

**Proposed priority:** P1, subject to triage. **Evidence:** synthetic route-level interleaving.

The historical route calls `chrome_bridge.verify_status()` and later sets `scan_info.running` under `scan_lock`. `ChromeBridge.start()` checks that flag under its own lock, then later acquires `scan_lock` to update it. If the historical request has completed its verification check before the Chrome request enters `start()`, the historical request can set its running state after Chrome has checked the flag but before Chrome sets its own state. Both requests returned `started` in the controlled test, and the Chrome mode replaced the historical mode while the historical worker was active.

Sequential starts are normally rejected. The earlier report's claim of generally separate running-state checks was overstated; the observed defect is a race between the check and state update.

- Source: `server.py:1282-1307`, `chrome_bridge.py:143-149,176-185`; UI entry points `app.js:1461-1474,1815-1825`.
- Impact: overlapping work and misleading shared status; the historical worker's finalization can change shared running state. Data corruption was not demonstrated.
- Direction: coordinate admission and state changes atomically without weakening existing lifecycle protections.
- Required tests: simultaneous basic/Quick, basic/Rescan, basic/verification, and duplicate requests; sequential rejection; partial results and state after either worker finishes.

### LR-SCAN-02: Missing-photo eligibility uses only the first dealer source

**Proposed priority:** P2. **Evidence:** synthetic cache responses.

`missing_photo_targets()` selects the first used source for each VIN. In the test, Toyota had 10 usable photos and Mitsubishi had 2; the VIN was omitted. The downstream VIN-based job builder queues all valid used dealer links for a selected VIN, rather than only the deficient source.

- Source: `server.py:89-98,1534-1544`; `chrome_bridge.py:305-318`.
- Impact: a second dealer gallery may remain incomplete, while an already complete source may also be revisited.
- Direction: consider source-specific eligibility and jobs, preserving exact VIN/source checks, originals, cache integrity, and the ten-photo eligibility threshold.
- Required tests: both source orders, one/both incomplete, one/both complete, invalid links, cached photos, and single-source vehicles.

### LR-SCAN-03: Historical scan Stop reports inactive while work continues

**Proposed priority:** P1, subject to triage. **Evidence:** synthetic blocked historical worker and actual bridge control.

The controls call `ChromeBridge.control()`, but `website_scan_worker()` has no corresponding cancellation signal. With the bridge in scan mode, Stop set `scan_info.running` false while the synthetic historical worker remained alive; after release it wrote its catalog. Depending on the bridge's previous mode, control behavior can differ, but neither path gives the worker a cancellation signal.

- Source: `app.js:1404-1455,1815-1825`; `server.py:597-688,1270-1281`; `chrome_bridge.py:425-468`.
- Impact: Stop can be misleading and may allow another scan to start while historical work continues. No real browser or dealer request was used in the test.
- Direction: add truthful cancellation and status for historical work, checking safe boundaries without losing completed results.
- Required tests: pause/stop during discovery and between sources, reload, repeated Stop, concurrent start after Stop, and preservation of completed catalog entries.

### LR-SCAN-04: Multi-stage coordinator state after restart

**Proposed priority:** P1 pending lifecycle reproduction. **Evidence:** source trace only; restart NOT RUN.

Dealer jobs may restore paused from `pending_dealer_scan.json`, while `full_job` and its phase are initialized in memory. An interruption may therefore leave a restored dealer queue without its associated Full Scan or listing-check coordinator.

- Source: `server.py:357-445`; `chrome_bridge.py:99-130,1134-1141`.
- Impact: possible lost phase and incomplete subsequent stages; exact user-visible behavior needs a disposable restart test.
- Direction: investigate durable interrupted-state reporting and explicit recovery; never automatically advance later stages without an approved policy.
- Required tests: restart during discovery, verification, Facebook checking, and after Stop; verify partial work, controls, and no implicit subsequent stage.
- Duplicate: overlaps [issue #6](https://github.com/iDarknesskiller/LotRadar/issues/6), instability item INST-02.

### LR-SCAN-05: Verification timeout advances to Facebook checking

**Proposed priority:** P2. **Evidence:** extracted coordinator with an accelerated synthetic clock and mocked dependencies.

When verification times out, the worker records `verify.error` and `partial=True`, then can enter Facebook checking and finish with phase `completed`. The UI displays “Some checks incomplete”; this is not an unqualified success. The test confirmed the Facebook stage was invoked without waiting two real hours and did not contact Facebook.

- Source: `server.py:364-445,1545-1590`; `app.js:1374-1400`.
- Impact: the later stage can run despite incomplete dealer verification, and the timeout is not necessarily the main final error.
- Decision needed: stop on failed verification or continue with an explicit, prominent partial-result policy.
- Required tests: timeout, reader disconnect, stop, no saved links, partial coverage, later-stage failure, and accurate final status.

### LR-SCAN-06: Quick Scan skips another dealer's matching URL path

**Proposed priority:** P2. **Evidence:** synthetic saved Toyota URL and Mitsubishi discovery URL with identical paths.

Quick Scan stores existing paths without their source and tests discovered paths against that shared set. The test skipped the Mitsubishi candidate even though only Toyota was saved.

- Source: `chrome_bridge.py:150-160,678-685`.
- Impact: a source-specific inventory record may not be discovered; real-world path-collision frequency is NOT MEASURED.
- Direction: match an existing record by dealer source and normalized path, preserving distinct source records for shared VINs.
- Required tests: same path across different dealers, same dealer duplicate, shared VIN, changed URLs, and new vehicles.

### LR-SCAN-07: Rescan Everything obeys refresh cooldown

**Proposed priority:** P2. **Evidence:** synthetic recent successful refresh.

The Rescan Everything UI requests a full discovery with `skip_existing=False`, but vehicle jobs pass through `RefreshPolicy.skip()`. A synthetic recent success was skipped for 24 hours; failures are subject to a 30-minute cooldown.

- Source: `index.html:60`; `app.js:1461-1474,1899`; `chrome_bridge.py:568-576,686-689`; `refresh_policy.py:10-16`.
- Impact: the button's promise to rescan existing vehicles can differ from actual behavior. No live scan was run.
- Decision needed: retain cooldown with clear disclosure, or define a safe explicit-rescan override. Preserve cooldown and rate safeguards where applicable.
- Required tests: recent success, recent failure, cooldown expiry, Quick versus Rescan, and clear skipped counts.

### LR-SCAN-08: Early abort waits until the source queue is empty

**Proposed priority:** P2. **Evidence:** synthetic timeouts and mocked store.

The unreadable-section branch checks `not self._source_pending(source)` before removing queued jobs for that source. After four synthetic page timeouts, four jobs were still queued and the scan remained active. Headless mode separately stops after three consecutive access-denied outcomes; this test concerned page timeouts.

- Source: `chrome_bridge.py:869-878`; `headless_dealer.py:146-154`.
- Impact: a largely unreadable section can continue opening and timing out pages before it is flagged.
- Direction: evaluate an early-abort policy that handles queued and inflight work safely, distinguishes transient failures, and preserves completed imports and dealer access protections.
- Required tests: repeated timeouts, access denials, transient recovery, inflight work, other source continuing, and truthful partial status.

### LR-SCAN-09: Photo worker exits on persistence failure

**Proposed priority:** P2. **Evidence:** synthetic `_persist_queue()` failure.

An exception in the worker's `finally` block can escape before `task_done()` and terminate that worker. The injected `OSError` left one unfinished queue task. The displayed worker count derives from the worker list, not a liveness check.

- Source: `photo_cache.py:459-463,775-784,833-855`.
- Impact: repeated disk or persistence failures can reduce worker capacity; actual frequency and recovery impact are NOT MEASURED.
- Direction: surface the failure, preserve recoverable queue state, and explicitly handle worker liveness without claiming successful persistence.
- Required tests: write and replace failures, queue-full during reschedule, unfinished task accounting, worker liveness, restart recovery, and user-visible errors.

## Performance investigation

### PERF-01: Queue dispatch and checkpoints

`ChromeBridge.next()` scans the remaining queue for refresh eligibility; durable wrappers checkpoint queue state under the bridge lock. A no-network synthetic dispatcher benchmark with mocked completion gave:

| Synthetic jobs | Eligibility checks | Checkpoint bytes written | Median of 3 runs |
| ---: | ---: | ---: | ---: |
| 50 | 1,275 | 317,673 | 0.130 s |
| 200 | 20,100 | 4,181,953 | 0.524 s |
| 500 | 125,250 | 25,035,521 | 1.633 s |

Source: `chrome_bridge.py:99-108,551-606,1134-1141`. These numbers describe the artificial dispatcher and its simulated completions only. Checkpoint-write counts and elapsed time are **not production scan measurements** and must not be extrapolated to user throughput. Profile realistic synthetic workloads before changing durability or synchronization.

### Further hypotheses: NOT MEASURED

- Verification writes its growing report after results (`chrome_bridge.py:894-901,1108-1122`); measure write size and lock time.
- Console/status polling copies state, and inventory refresh compares complete state (`server.py:804-827`, `app.js:1559-1575,1578-1637`); measure API latency, payload size, and UI long tasks.
- Headless jobs create browser contexts and perform page and lag checks (`headless_dealer.py:88-128`); measure setup separately from remote network waits before changing isolation or worker counts.

Suggested benchmark: disposable 50/200/500-vehicle synthetic fixtures, at least three runs per workload; record wall time, queue operations, bytes written, CPU/RSS, API latency, and UI long tasks. Report distributions and environment, retain failed runs, and compare before/after without real dealer or Facebook requests.

## Scope, safety, and follow-up

- No live dealer scans, Facebook actions, browser profiles, private data, or external network requests were used. Tests used synthetic data, mocks, controlled timing, and disposable temporary directories; no product changes were made.
- The race reproduction executed the extracted actual route body, not an end-to-end HTTP/browser test. Other reproduced findings are similarly bounded synthetic checks, not production incident measurements.
- Preserve VIN/source identity, truthful availability and partial status, original photos, draft text, queue recovery, browser ownership, existing safeguards, and completed partial results.
- The report supersedes the earlier `bf61207` findings wording; the current audit used `a5d1754`. Issue/PR check on 2026-11-19 found related [issue #6](https://github.com/iDarknesskiller/LotRadar/issues/6) and this report PR #11.
- Suggested order: historical Stop and atomic admission; source-specific Quick Scan and photo targeting; timeout/early-abort/worker reliability; then profile and optimize. Implement only after Owner prioritization and scoped authorization; independent QA and separate Owner merge/release decisions remain required.
