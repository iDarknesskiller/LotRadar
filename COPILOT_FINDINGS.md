COPILOT_FINDINGS.md

Source: approved main SHA bf61207a21999c8ff256b08c0d17650193e3835f
Inspected scope: all LotRadar scan buttons, server scan routes, Chrome bridge state, Full Scan coordinator, and existing GitHub issues/PRs
Date: 2026-11-18

Candidate LR-SCAN-01: Basic and Chrome scans do not mutually exclude each other
Category: scanner reliability
Proposed severity: P1
Confidence: HIGH
Verification status: VERIFIED FROM SOURCE
Exact path and function:
- server.py:1282-1305, /api/start-site-scan
- app.js:1461-1470, beginInventoryScan()
- app.js:1815-1824, beginSiteScan()

Current behavior:
Chrome inventory scans check chrome_bridge state, while basic historical scans check only scan_info.running. The basic scan route can start separately from Quick/Rescan, verification, Full Scan, or Facebook/link workflows.

Expected behavior:
LotRadar should allow only one mutually exclusive dealer discovery or verification workflow at a time and return a clear conflicting-scan response.

Reproduction or NOT RUN:
NOT RUN. Source trace indicates that the basic and Chrome scan paths use separate state checks.

Impact:
Overlapping catalog reads/writes, duplicate browser activity, misleading progress, and potentially inconsistent import state.

Affected files:
- app.js
- server.py

Protected files or behavior:
Do not alter inventory records, Chrome Reader pairing, VIN/stock provenance, or scan stop semantics outside the implementation task.

Required tests:
- Basic historical scan plus Quick Scan
- Basic historical scan plus Rescan Everything
- Basic historical scan plus live verification
- Basic historical scan plus Full Scan
- Duplicate scan-button clicks
- Start, reload, and page-refresh state recovery

Existing issue/PR duplicate check:
No matching existing issue or PR found.

Recommended investigation or fix direction:
Introduce one server-owned active-operation state or a shared eligibility guard covering basic, Chrome, verification, Full Scan, photo-fetch, and Facebook batch operations. Mirror that state accurately in the UI.

Candidate LR-SCAN-02: Fetch Missing Photos ignores the second dealer source
Category: photo/scanner reliability
Proposed severity: P2
Confidence: HIGH
Verification status: VERIFIED FROM SOURCE
Exact path and function:
- server.py:89-96, missing_photo_targets()
- server.py:1534-1544, /api/fetch-missing-photos
- chrome_bridge.py:302-318, start_missing_photos()

Current behavior:
Eligibility selects only the first used source present on a vehicle. start_missing_photos then processes eligible VIN/source pairs, but a shared VIN may be excluded if the first dealer source already has ten usable photos even when the second source has fewer.

Expected behavior:
Fetch targets should include each eligible vehicle/source pair with fewer than ten usable photos.

Reproduction or NOT RUN:
NOT RUN. Safe synthetic reproduction would use a shared VIN with Toyota at ten photos and Mitsubishi below ten.

Impact:
The Fetch Missing Photos button can report completion while one dealer gallery remains incomplete.

Affected files:
- server.py
- chrome_bridge.py

Protected files or behavior:
Preserve original photos, source isolation, the ten-photo threshold, VIN/source matching, and existing cache safeguards.

Required tests:
- Shared VIN with Toyota complete and Mitsubishi incomplete
- Shared VIN with Mitsubishi complete and Toyota incomplete
- Both sources complete
- No valid dealer link
- Toyota-only and Mitsubishi-only vehicles
- Cached, partial, failed, and unavailable gallery cases

Existing issue/PR duplicate check:
No matching existing issue or PR found.

Recommended investigation or fix direction:
Return source-specific photo targets instead of VIN-only targets, while retaining existing source and VIN validation.

Candidate LR-SCAN-03: Basic historical scans have no pause or stop control
Category: startup/scanner process safety
Proposed severity: P2
Confidence: HIGH
Verification status: VERIFIED FROM SOURCE
Exact path and function:
- server.py:597-688, website_scan_worker()
- server.py:1282-1308, /api/start-site-scan
- app.js:1404-1455, installDealerScanControls()
- app.js:1815-1824, beginSiteScan()

Current behavior:
The page Pause/Stop controls call chrome_scan_control and chrome_bridge.control. Basic historical scans run in a separate server thread and do not update chrome_bridge scan or verification state, so the controls do not stop them.

Expected behavior:
Every scan mode should support pause/stop, or the UI should explicitly prevent it from being described as pausable/stoppable and provide a supported cancellation status.

Reproduction or NOT RUN:
NOT RUN. UI and route tracing show that a basic scan does not activate the Chrome bridge controls.

Impact:
Users cannot cancel unwanted public-site discovery work after it starts.

Affected files:
- app.js
- server.py

Protected files or behavior:
Preserve historical-link-only semantics, no-Facebook behavior, partial catalog results, and existing Chrome stop behavior.

Required tests:
- Start and stop basic scan
- Pause and stop basic scan from the dock and console
- Close/reopen the console
- Reload during basic scan
- Stop near source handoff
- Verify completed partial catalog candidates remain intact

Existing issue/PR duplicate check:
No matching existing issue or PR found.

Recommended investigation or fix direction:
Add a basic-scan cancellation signal checked between sources and pages, plus truthful UI state.

Candidate LR-SCAN-04: Full Scan state is not restored after restart
Category: scanner lifecycle/recovery
Proposed severity: P1
Confidence: HIGH
Verification status: VERIFIED FROM SOURCE
Exact path and function:
- server.py:361-445, full_scan_worker()
- chrome_bridge.py:99-128,1133-1141, scan restoration and checkpointing

Current behavior:
Dealer and verification checkpoint state can be restored, but the in-memory full_job coordinator is not persisted or reconstructed. Restart can leave the dealer queue paused while no active Full Scan state is exposed.

Expected behavior:
Restart should restore the Full Scan coordinator or mark every interrupted stage incomplete and prevent subsequent stages from starting implicitly.

Reproduction or NOT RUN:
NOT RUN. This is a restart lifecycle hypothesis supported by source. It was not service-restart reproduced.

Impact:
Missed verification or Facebook stages, stale progress, false idle state, or no usable stop/resume control.

Affected files:
- server.py
- chrome_bridge.py

Protected files or behavior:
Preserve paused restored work, partial results, dealer inventory, saved Facebook drafts, and the rule that availability is never invented.

Required tests:
- Restart during dealer discovery
- Restart during dealer verification
- Restart during Facebook checking
- Restart after user stop
- Reload while no scan is active
- Verify no implicit subsequent stage starts

Existing issue/PR duplicate check:
Matches issue #6 instability item INST-02; no separate issue or PR for this scan-specific finding.

Recommended investigation or fix direction:
Persist a minimal durable Full Scan phase/status snapshot and restore it explicitly as interrupted until the user chooses resume or stop.

Candidate LR-SCAN-05: Verification timeout can advance to Facebook checking
Category: scanner state integrity
Proposed severity: P2
Confidence: HIGH
Verification status: VERIFIED FROM SOURCE
Exact path and function:
- server.py:364-421, full_scan_worker(), wait_stage()
- server.py:422-445, stage finalization

Current behavior:
If verification times out, full_scan_worker records verify.error, but the subsequent Facebook stage is not guarded by a verification-success check. The timeout can remain secondary to a later Facebook phase or final completed state.

Expected behavior:
A verification timeout should stop the workflow or preserve a clearly reported partial verification stage and must not be silently advanced as a successful verification.

Reproduction or NOT RUN:
NOT RUN. Source trace indicates the timeout path, but no live two-hour timeout was run.

Impact:
Facebook checking can begin after incomplete verification, while final status does not make the timeout the primary result.

Affected files:
- server.py

Protected files or behavior:
Preserve partial verification records, truthful Facebook status, and explicit availability verification rules.

Required tests:
- Verification timeout
- Verification reader disconnect
- Verification stop/cancel
- Verification limit/partial coverage
- Restart during verification timeout handling
- Full Scan final status for timeout, partial coverage, stop, and success

Existing issue/PR duplicate check:
No matching existing issue or PR found.

Recommended investigation or fix direction:
Guard the Facebook transition on verification completion state and surface timeout/partial-coverage in full_job.error and phase.

Global limitations and missing access:
- No live scans, browser actions, Facebook actions, private user data, or external network requests were used.
- No benchmarks or performance measurements are claimed.
- Verification of restart and timeout behavior requires synthetic or disposable local test execution.
