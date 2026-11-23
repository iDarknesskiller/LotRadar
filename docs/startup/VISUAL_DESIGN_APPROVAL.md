# ARCHITECT_HANDOFF — FINAL Owner Startup Visual Direction (PR #5)

**To:** Claude — Lead Programmer  
**From:** ChatGPT — LotRadar Chief Architect  
**Owner's latest decision:** The Project Owner explicitly **REVOKED** the earlier full-scene/cinematic fantasy splash and confirmed that the startup must show **only the original radar logo, the progress bar, and the startup steps**. This file **replaces the prior visual proposal** even where that proposal was described as previously approved. Do not implement any superseded illustration requirements from older PR comments.  
**PR:** [#5 — Windows startup window](https://github.com/iDarknesskiller/LotRadar/pull/5), `feat/windows-startup-status-window` (DRAFT).  
**Approved baseline `main` at decision:** `bf61207a21999c8ff256b08c0d17650193e3835f`.  
**PR HEAD at decision:** `87499ef1346a729772ec8545344a0063fd0024cd`.  
**App version:** No unified app version; the install manifest `source_commit` + `package_version` remain authoritative for the built artifact.

## Request

Replace the previous fantasy/cinematic startup concept with a **small, clean, dark, polished LotRadar-native startup window**. The original LotRadar watch-shaped radar logo is the main visual, followed by **a functioning blue progress bar and four functioning startup-step indicators**. No additional scene, poster, title treatment or other background illustration.

## Current behavior / root cause

- `startup/Show-LotRadarStartup.ps1` is the existing native Windows Forms/PowerShell 5.1 progress window. Its current approx. 480×330 logical-pixel layout includes the packaged private logo if available, multiple literal backend stages, an indeterminate `ProgressBar`, details, console, retry and close.
- `Marketplace Bootstrap.ps1` remains the only owner of real startup, lock, server and browser launch. It emits nonce-bound `install`, `python`, `browser`, `server`, `open` events; the UI requires both `open:complete` and live `127.0.0.1:8765/api/health` to report ready.
- `scripts/build_installer.py` already privately packages `branding/lotradar_logo.png` for production via `--asset-dir`. Development packages may fall back to an unbranded/text version. No new private image asset is required for this redesign.
- The prior `VISUAL_DESIGN_APPROVAL.md` wrongly demanded a huge blue/purple fantasy image, moon, warrior, banners, 16:9 artwork, a `startup_splash.png` and baked 72% fake progress. **Those instructions are revoked.** The earlier screenshot is **not a production artwork dependency** and its hash is NOT an acceptance criterion.
- This is a UI refinement only; it must not change launch/installer permissions or data.

## Required behavior / visual specification (single source of truth)

1. **Original radar logo as the main focal point.** Center the existing circular silver stopwatch/radar icon, preserving its exact shape, green radar face and the red outer and green inner **`LOT RADAR` lettering** from the Owner's supplied logo. Use the existing private `branding/lotradar_logo.png` and retain its existing private build contract. Do **not** substitute a regenerated logo, and do **not** add a giant external `LOTRADAR` wordmark.
2. **Minimal supporting backdrop.** Use a dark near-black/charcoal solid or subtle gradient panel, restrained steel-blue trim and a subtle blue glow around the logo if feasible with existing WinForms drawing. **NO** armored warrior, Diablo character, moon, lightning, banners, dramatic scene, poster/landscape illustration, red background, giant title, or full-screen splash art.
3. **Live status and bar.** Small `Initializing LotRadar` line below logo; **real blue animated progress bar** beneath. When an objectively measured fraction is unavailable, use honest indeterminate animation (no invented percentages, fixed 72%, ETA or countdown). Optionally show a real fraction only for a truly measured sub-operation with tested semantics.
4. **Four visible stages below the bar**, labeled exactly: `SYSTEM CHECK`, `LOADING MODULES`, `STARTING SERVER`, `LAUNCHING LOTRADAR`. Show clear live **pending / active / complete / failed** states; not image-baked checks. Stage map: `install` → SYSTEM CHECK; `python` and `browser` → LOADING MODULES (surface the current Python vs browser substage in details/status; do not incorrectly mark complete before both finish); `server` → STARTING SERVER; `open` + verified health → LAUNCHING LOTRADAR complete. Event changes must be driven by the existing nonce-bound startup messages.
5. **Existing practical controls preserved:** `Show details` (or equivalent), `Show console`, `Retry` on failed startup, `Close`/Esc. If controls are contextual, they still need to be discoverable, keyboard-accessible, and visible without clipping. Do not convert Close into Kill Server; existing close-while-starting must allow console takeover.
6. **Window proportions:** compact centered application window with enough padding for logo, bar, four stages and controls. Respect 1366×768, 1920×1080 and 3440×1440, plus 100/125/150/200% DPI. Do not force fullscreen or hijack focus from games. Single radar image, no background image dependency.

## Relevant architecture / files to modify

**Primary:** `startup/Show-LotRadarStartup.ps1` for visual layout, logo dimensions, WinForms progress appearance and state mapping; `tests/test_startup_window.py`, `tests/windows/Test-LotRadarInstaller.ps1` and existing QA kit/manual UI preview tests; `docs/MANUAL_ACCEPTANCE.md` for visible appearance checks; this architecture file and the canonical `docs/startup/ARCHITECT_HANDOFF.md` for design precedence.

**Expected NOT to modify:** `Marketplace Bootstrap.ps1` stage semantics or `Launch Marketplace Scanner.cmd` launch logic; installer private asset allowlist or manifest (there is **no new splash image**); `server.py`, `core.py`, photo modules, Facebook modules, Chrome extension, scanner, inventory database, draft/photo data, packaging PR #8 or uninstaller PR #7. Any deviation requires a specific demonstrated blocker and Architect review.

## Ordered implementation plan for Claude

1. Reconfirm current approved `main` SHA and draft PR #5 HEAD; examine actual WinForms form layout, logo loader, stage-event handling, previews and manual QA state. Record the before behavior/screenshots without altering user data.
2. Remove the obsolete requirement for `startup_splash.png` and fantasy art. Do **not** add a new image file to public or private packaging. Reuse the private logo as already supported.
3. Adjust the WinForms form so logo is large and centered, with `Initializing LotRadar`, blue indeterminate progress bar, four concise status badges/rows, and accessible details/console/retry/close actions. Use native controls or simple code-drawn shapes rather than embedding fixed stage artwork. Preserve text equivalents for screen readers and no fake percentages.
4. Map actual `install/python/browser/server/open` events into the four visible stages without losing detail or declaring browser readiness early. Ensure failed state and retry reset each indicator correctly; only declare all complete after real health.
5. Update safe `-Preview` synthetic tests to display the correct visual without starting a server. Keep preview unmistakably nonproduction; real sandbox E1–E6 remain separate and may not be marked PASS just because preview works.
6. Test Windows 11 PowerShell 5.1 behavior at 100/125/150/200% scaling, including 1366×768 and ultrawide, expanded details, mouse/keyboard/Alt accelerators, real logo/no-asset fallback, dark colors, no clipping, normal / existing server / failure / retry / close-while-starting / console behavior.
7. Run the existing Python unit tests, Windows full-launch G1–G10, real E1–E6 manual checks, OneDrive installer/security R1–R8, app lifecycle and shortcut/lock safeguards on the exact new SHA. Record PASS/FAIL/SKIP/BLOCKED honestly. Gemini audits executed tests and screenshots. Do not claim that this docs-only change executes any tests.
8. Deliver `CLAUDE_PR5_STARTUP_VISUAL_CORRECTION_HANDOFF.md` with exact commit, modified paths, before/after screen captures, source of private logo, test results and waivers. Owner reviews the visual result; no merge authorized.

## Protected functionality and risk areas

- **Never regress** bootstrap real stages, nonce validation, local health check, exactly one server/browser, port 8765, launch/install locks, existing failed attempt cleanup and safe close/console takeover.
- **Never touch** private photo/cache/database/draft state, vehicle records, OneDrive, production icon/logo pixels, user Desktop shortcut except in already-guarded sandbox QA, or SalesmanHub integration.
- Risks: oversimplifying five backend stages into four hides browser setup; status marked done before server is healthy; hardcoded blue Windows Forms ProgressBar renders OS-themed green; UI freezes during dependency downloads; too-large logo clips actions at high DPI; private logo missing in dev; automatic checkmarks appear falsely from image; public branding leak.
- If the native Windows ProgressBar cannot render reliable blue across themes without harming accessibility, use a small custom WinForms-painted indeterminate indicator with real animation/timer and high-contrast fallback. Test it; no fake completion.

## Acceptance criteria

| ID | Required measurable result |
| --- | --- |
| UI-01 | Only existing watch-shaped LotRadar logo, minimal dark window, actual bar and four live stages dominate the screen; no fantasy character, moon or full-scene backdrop. |
| UI-02 | Original private radar logo is unchanged, with outer and inner `LOT RADAR` lettering; no giant separate wordmark. |
| UI-03 | Progress bar is visible, styled blue, animated from actual running state and never fixed to an invented percentage. |
| UI-04 | Four stage headings exactly match Owner request, mapped faithfully to all five real bootstrap stages, with pending/active/done/failed states. |
| UI-05 | UI reports success only after real `open:complete` and healthy `/api/health`; does not double-launch or break install/launch locks. |
| UI-06 | Show details, Show console, Retry, Close and keyboard controls remain operational with real errors. |
| UI-07 | UI clean and readable at 100/125/150/200% DPI and 1366×768/1920×1080/3440×1440, with no clipped controls. |
| UI-08 | DEV without logo uses a clear safe fallback; production uses the **existing** private logo without introducing any new mandatory splash asset. |
| UI-09 | Windows unit/full-launch/security/OneDrive/manual E1–E6 tests run and pass or honestly report unresolved failures; Gemini and Owner can review screenshot proof. |
| UI-10 | New splash-only private asset requirement, cinematic background and fake 72% requirement are absent from current design contract; no code or private assets added by this architect-docs revision. |

## Git / handoff

Continue existing **draft PR #5** only. This document supersedes the earlier cinematic visual approval and any conflicting PR comment. Do not merge to `main`, do not make PR #5 ready, and do not modify PR #7/#8 as part of this task. Owner alone decides final release/merge.
