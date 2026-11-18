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

## Final executed verification (implementation candidate 6ebafe26f915568b2c8094f2392a01e66631c33d)

- Windows 11 Home build 26200, Windows PowerShell 5.1.26100.9818, non-admin.
- `python -m unittest discover -s tests`: 116 tests OK, exit 0, 90.995 seconds. Includes executed cleanup selector regression against mocked processes; no real processes killed by that test.
- `Run-QAKit.ps1 -FullLaunch -Yes`: 69 PASS / 0 FAIL / 0 SKIP, exit 0. Includes G1-G10, OFF1, F0-F5, R1-R8. G7 second launch and G10 targeted mnemonic/console/Escape PASS. Desktop shortcut restored byte-identical. Synthetic data checks and server/lock cleanup pass.
- Kit SHA256: 205604bc7f4f11d1028240ed96fd19a710d8f1302ef57f28cc08677b08101747.
- Development package SHA256: 026910f089ec3c47250838c19fc0fd89d3c741c97ae77a1d00dac1eee5e2aca9.
- Original Owner-supplied radar logo copied unchanged into an isolated preview: PASS at 150%, logo=true, clipped empty, tick_error empty. Progress capture visually inspected. This is NOT a full production installer test; production packaging still requires its complete private asset set.
- Safe invocation note: kit guard initially mistook its parent's literal script filename for a second run (exit 5, no tests). Reinvocation avoided that parent-command false match without changing or disabling guard logic.
- The early root-level handoff failed installer allowlisting; moving it under docs/startup resolved that without weakening packaging validation. Earlier failed runs are superseded by the passing committed candidate results above.
- Report-only follow-up does not change the implementation or test harness tested at 6ebafe2.

## Remaining verification / next owner

1. Owner: actual 125% and 200% sign-out/relogin tests, 1366x768 and ultrawide. NOT RUN; no display-setting changes made by Codex.
2. Windows 10: NOT RUN, no machine available. Owner must provide an environment or explicitly decide platform scope; no implied waiver.
3. Full production package with all original private assets: NOT RUN. Real-logo UI preview passed; private images remain outside Git.
4. Gemini: independent review of exact implementation candidate 6ebafe2 and individual sanitized evidence. Prior real-key/manual and OneDrive evidence is explicitly at 7998f70, not falsely recertified on the new candidate. OneDrive extraction was not repeated by Codex.
5. Owner: approve each push separately. No push, merge, release or deployment performed. Claude handback starts at actual local branch HEAD with this report and the tested implementation SHA recorded above.
