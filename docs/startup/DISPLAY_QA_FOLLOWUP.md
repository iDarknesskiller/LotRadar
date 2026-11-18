# Deferred startup display QA follow-up

Requested by the Project Owner on November 17, 2026: track the remaining display coverage separately for a later session. This is a documentation-only follow-up to draft PR #5, not a claim that the remaining tests passed.

## Source and ownership

- Canonical repository: iDarknesskiller/LotRadar.
- Main baseline at creation: bf61207a21999c8ff256b08c0d17650193e3835f.
- Feature under test: PR #5, feat/windows-startup-status-window.
- Last executed implementation candidate in this Codex session: 6ebafe26f915568b2c8094f2392a01e66631c33d.
- Local report-only follow-up HEAD: 0121564. These local Codex commits have not been pushed as part of this follow-up PR.
- Before any future run, fetch and record current approved main, actual PR #5 HEAD and package source_commit. Confirm the active writer with the Owner/Architect; Claude remains Lead Programmer, Codex Senior Developer, Gemini Independent QA.
- This follow-up does not authorize a merge, release, deployment, platform waiver or automatic future execution. Owner approval is required for each push and for merging into main.

## Evidence already available

| Check | Recorded result and boundary |
| --- | --- |
| Python suite at 6ebafe2 | 116 tests OK |
| Windows 11 PS5.1 full launch at 6ebafe2 | 69 PASS / 0 FAIL / 0 SKIP, including G7 and targeted-message G10 |
| 100% and 150% preview, physical keyboard/manual checks | Prior Owner/Claude evidence at 7998f70; do not relabel as newly executed on 6ebafe2 |
| Original-logo 150% preview | Loaded unchanged; no clipped labels/buttons or timer errors; visually inspected |
| Original-logo 125% preview | Measured scale 1.25; collapsed layout PASS; no clipped labels/buttons or timer errors; exit 0; captures inspected |
| Original-logo 200% preview | Measured scale 2.0; collapsed layout PASS; no clipped labels/buttons or timer errors; exit 0; captures inspected |

The later 125% and 200% runs used the same startup UI source as the tested candidate; no product code was changed for those runs. Their screen resolution was not recorded, so they do not certify any particular resolution/DPI combination below. Preview uses synthetic failure events and starts no real server. Targeted-message G10 does not prove physical keyboard focus.

Evidence is retained privately as individual files. Never add private logo bytes, personal paths, full-desktop captures or production packages to this public repository.

## Remaining display matrix

All entries are NOT RUN for the specified resolution/DPI combination. Use actual supported Windows display modes and record the monitor/work area, physical resolution, DPI and Windows build. Do not simulate scaling by resizing a screenshot or changing browser zoom.

| Physical display mode | 100% | 125% | 150% | 200% |
| --- | --- | --- | --- | --- |
| 1366 x 768 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| 1920 x 1080 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| 3440 x 1440 ultrawide | NOT RUN | NOT RUN | NOT RUN | NOT RUN |

Run available combinations on Windows 11 as a standard user in Windows PowerShell 5.1. If the hardware does not expose a mode, mark BLOCKED / UNSUPPORTED with the exact reason and request an Owner scope decision. Do not invent an ultrawide pass from a smaller display. Full Windows 10 display coverage remains NOT RUN: no Windows 10 test machine was available. Obtain a suitable machine or an explicit Owner platform decision.

At high scaling on a low-height display, specifically check whether the whole window and expanded controls fit inside the taskbar-adjusted work area. A text-only clipping assertion does not establish that the whole window is reachable.

## Checklist for each available combination

- [ ] Save work before any sign-out; coordinate display changes with the Owner and record the original settings so they can be restored.
- [ ] Start the actual unmodified startup UI in isolated preview with the original private logo, then test DEV fallback separately.
- [ ] Inspect running, failure and retry-to-success states; verify the live blue bar and four live stage headings.
- [ ] Expand details and inspect every label/button, the details box, window placement and taskbar overlap. No off-screen Close/Retry controls.
- [ ] Physically test Tab order, Show details, Show console, Retry, Close/Escape and the documented Alt accelerators. Preview cannot certify a real console; use an independently consented synthetic sandbox for real-console checks.
- [ ] Check high-contrast behavior and readability when feasible; record unavailable configurations honestly.
- [ ] Save window-only screenshots and per-case PASS / FAIL / SKIP / BLOCKED / NOT RUN, with exact source/package identity. Sanitize names, machine identifiers, paths and vehicle/customer information.
- [ ] Close every test app window individually; never terminate Chrome/Edge by process name or localhost URL alone. Do not close unrelated user windows.
- [ ] Restore the original display settings with the Owner, and confirm no test server or owned test process remains.

## Safety and completion

Do not alter live inventory, photos, drafts, SQLite, OneDrive settings or real user files; do not install Python/WinGet globally. Keep private assets outside Git. Any live sandbox/installation run needs its established consent and data/shortcut restoration safeguards.

This PR contains only this checklist. Do not implement product changes here without a new scoped assignment; report any discovered defect with the failing configuration and a minimal reproduction for the Architect.

Completion requires the agreed matrix to be executed (or each unavailable case explicitly dispositioned by the Owner), individual sanitized evidence, Gemini review at an exact candidate SHA, and a clear handback to Claude. Deferral alone is not a passing result or a release approval.
