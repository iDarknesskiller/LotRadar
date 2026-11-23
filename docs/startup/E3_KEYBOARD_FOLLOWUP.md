# LR-010-02 (LR-010, following LR-010-01): E3 physical-keyboard acceptance

To: Claude, Lead Programmer and Test Designer
From: LotRadar Chief Architect
Owner priority: November 19, 2026 — move E3 to its own PR and complete it before the next implementation work.

## Scope and identity

Follow-up to PR #5 audited candidate abfa580a288ffd026488958c88a73e0564e14cd0 (tree 3f51d537f39a2c3fc68c46317e5dcf2b71fb20bc). Recheck Owner-approved main and freeze candidate, harness and package before execution. This PR adds a documentation/test work order only. No product code change or test execution is performed by creating it.

Current E3 status: INCONCLUSIVE in Codex evidence; Owner attestation D-4 accepted PR5 risk. Preserve that historical distinction. Targeted-message G10 is not physical-key testing. FullLaunch CLN1 cleanup remains a separate waived FAIL (D-5), tracked in issue #14, not PASS.

## Required behavior and architecture

Physical keys must route to the focused startup form and controls reliably: Tab navigation, Shift+Tab, Alt+S for Show details, contextual Alt+D for Hide details, Alt+C for Show console, plain F5 for Retry (Alt+R ignored by LotRadar), Alt+L for Close and Escape. Confirm actual accelerators in startup/Show-LotRadarStartup.ps1; test only those present and record context/enabled state. UI is display-only: launch/bootstrap retain server and lock ownership.

## Ordered assignment

1. Claude verifies exact source, focus/tab/control handlers, current QA kit and safe preflight. Author an E3-specific CLAUDE_TEST_PLAN.md and freeze identities. Confirm sole writer before any test-only edit.
2. Coordinate a standard-user Windows PowerShell 5.1 session with the Owner. This work order sets priority; obtain explicit execution consent for its concrete preview and separately disclosed real-console sandbox steps before running. No display changes, downloads, OneDrive writes or global installations are authorized here.
3. Owner physically presses each key while Codex records one result per action, actual focused window/control, state before/after and evidence. Use isolated actual UI preview for harmless controls; a preview cannot prove a real console or server/lock lifecycle. Use owned synthetic failure/retry/console fixture only after consent, preserving original program/data/shortcut.
4. Test forward/reverse focus order; expand/collapse details; Show console; Retry after an owned failure; Close/Alt+L/Escape during running/failure states. Verify no lost focus, inaccessible enabled control, duplicate bootstrap/server, unrelated window closure or stuck owned console. Return focus deliberately after console activation before testing the next key.
5. Record startup continuation on close where applicable, expected exits and before/after shortcut/data/lock integrity. Close owned app windows individually. Do not kill personal browser processes or delete unknown residue; preserve ownership records if cleanup fails.
6. Codex reports all outcomes and sanitized individual evidence to Claude. Claude dispositions every result; Gemini audits after READY FOR GEMINI. Owner authorizes any merge. Do not start another implementation workstream until this follow-up is resolved or the Owner explicitly changes priority.

## Allowed and excluded edits

LR-010-02 authorizes Codex to change only startup/Show-LotRadarStartup.ps1 in production and update the tests and guides. Owner consents P and R separately at execution. Original scope before LR-010-02: E3 test plan, report, evidence manifests and narrowly scoped test-only cases in an isolated test workspace. Do not change startup UI, launcher/bootstrap, installer, server/core, photo modules, drafts, SQLite, Chrome Reader, private assets or user settings. A discovered product defect requires a separate source-grounded proposal and Owner implementation approval.

## Acceptance criteria

- E3-AC-01: Each physical key/action above has a distinct observed PASS/FAIL/INCONCLUSIVE/NOT RUN result with exact source/harness/package, Windows build/DPI, focused-control context and operator action. No aggregate Y/N replaces per-key observations.
- E3-AC-02: Correct forward/reverse navigation and contextual controls, including physical Escape and real console/Retry when safely exercised; G10 injection is recorded separately.
- E3-AC-03: All protected state/shortcut hashes, lock/server ownership and owned fixture cleanup are accounted for; existing waivers remain explicit.
- E3-AC-04: Unfiltered Codex report, Claude readiness/dispositions and Gemini audit delivered; private data and full-desktop captures stay outside Git. No invented evidence.
- E3-AC-05: This draft is not closed as completed merely because the checklist exists; execution gaps remain open until resolved or explicitly dispositioned by Owner.

## Risk and related work

Risks: foreground routing, console focus changes, delayed child exit, shell/global hotkeys, wrong monitor work area, testing a different package, live-data access and browser-profile locks. Use known-owned synthetic fixtures and window-only captures. No keyboard automation may be called a physical/manual PASS.

Related: PR #10 display/GEM-001; issue #13 Windows 10; issue #14 A3 and test-kit cleanup; issue #15 installer/resource polish. No merge/release permission is conveyed by these links.
