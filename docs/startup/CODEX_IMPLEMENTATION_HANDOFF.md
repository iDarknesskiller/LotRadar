# Codex PR #5 takeover handoff

Owner assigned takeover after confirming Claude is unavailable. Claude remains Lead Programmer; Gemini remains independent QA. Keep PR #5 draft, no merge or push without Owner approval.

Baseline main: bf61207a21999c8ff256b08c0d17650193e3835f.
Starting branch: feat/windows-startup-status-window at 1d67ad8be6aeb1e391e853133000d39a61fb4549.
Claude completed the visual correction at 7998f70 and G7 expectation at 1d67ad8. Those changes are preserved.

## Changes
- tests/windows/Test-LotRadarInstaller.ps1: G10 uses messages posted to the owned window's queue (PID checked) instead of foreground stealing and global SendKeys. It checks mnemonic/dialog processing, not physical keyboard delivery; E3 remains the real-key acceptance test. Removed unproven URL-only Chrome/Edge tree termination from Stop-SandboxProcesses; browser windows require manual close. Only sandbox server processes are selected.
- tests/test_qa_kit.py: updated packaged-harness contracts for G10's explicit scope.
- tests/test_windows_process_cleanup.py: executes the actual cleanup selector against synthetic process records and mocked taskkill; personal browsers and outside servers must survive, including prefix-collision and wildcard-containing fixture paths.
- docs/MANUAL_ACCEPTANCE.md: documents targeted keyboard coverage and browser-cleanup limitation.
- No production code, launch/bootstrap semantics, installer, private branding or user data changed.

## Evidence and current gates
- Focused G10 on Windows PowerShell 5.1 PASS: failed stub, console click/shown, exit 91 via targeted Escape. Private window-only capture and JSON retained locally.
- Initial sandbox Python run failed due blocked Git MSYS/socket access. Not a product PASS.
- Unsandboxed preliminary Python run: 115 tests, 2 failures because package tests build committed HEAD while the updated assertions were uncommitted. Rerun on the committed candidate is required.
- New cleanup regression and final candidate full suite: pending at preparation; see follow-up evidence.
- Owner/Claude prior 7998f70 evidence: Python 115 OK; main Windows 58/1/1 (G10); OneDrive 62/0; full launch 67/2 (G7 expectation and G10). Manual E1/E2/E5/E6/B3/B9/B10 PASS; preview 100% and 150% PASS as listed in CODEX_HANDOFF_PR5.md. These are prior-reported results, not new candidate certification.
- Production private-logo check, 125%/200%, 1366x768/ultrawide, Windows 10: NOT RUN. No Windows 10 PC available; Owner scope decision remains required.
- Final full launch must verify G7 on the new candidate. No PASS by inference.
- Gemini review at exact final candidate remains pending; send individual sanitized evidence files, never ZIPs.

## Handback
Claude should resume from actual committed branch HEAD and inspect this change before using an old working tree. Next: verify committed unit/Windows results, finish available visual gates, obtain Gemini review, then Owner approval. No release is authorized.
