# LotRadar Startup Splash — Approved Visual Reference

**To:** Claude — Lead Programmer  
**Approval:** Project Owner selected the final image in the ChatGPT LotRadar design discussion on 2026-11-17. **Visual direction is approved; code/build/merge are not approved.**  
**Correct implementation PR:** [PR #5 — Windows startup status window](https://github.com/iDarknesskiller/LotRadar/pull/5), branch `feat/windows-startup-status-window`.  
**Approved baseline `main`:** `bf61207a21999c8ff256b08c0d17650193e3835f`  
**Feature HEAD inspected before this approval:** `2604a6161ff57a32ff0b2c91c58fb4b4246dc4be`  
**Candidate app version:** no unified application version; the extension independently has a version, but the packaged candidate must retain `source_commit` and manifest version.

## Request / approved image identity

The Project Owner wants the **actual startup screen** to look like the *last approved supplied screenshot*, **not** the earlier red-themed variant, text-heavy logo variant, or the version with the progress bar removed.

Approved visual master (uploaded in ChatGPT):
- Source filename: `c7ab77cd-909b-49b2-9092-bb019f7e3bce.png`.
- PNG, RGBA, **1670 × 941 pixels** (approximately 16:9), **3.3 MB**.
- **SHA-256:** `4024522afe01a8d35953e28d2e6ec4611267ecb1eccc9c72655279576d2fe763`.
- The exact image is the visual acceptance authority. Preserve its subject placement, palette, pocket-radar shape, loading area, and hierarchy; do not re-generate it as a different-looking image.

**Asset access/security:** This image was supplied through the private ChatGPT conversation; its bytes are **not** in the public GitHub repository or retrievable through this GitHub handoff. The user should provide the PNG to Claude via an authorized private asset-delivery channel. Do not claim that the PNG has been uploaded to PR #5 and **do not commit** this image or the original private logo/branding to the public GitHub repository. The source SHA above lets Claude verify the exact received file. If the binary is not accessible, implement/test the asset contract and mark **final visual comparison BLOCKED (asset not received)**. Do not substitute a guessed public image.

## Required appearance, with reference composition

- Overall look: dramatic **electric blue / indigo / violet** cinematic fantasy lighting, silver steel, vivid green radar center, blue moon at upper right, atmospheric armored silhouette with glowing energy, cool-colored lightning and flags. **No dominant red background**.
- **One main logo in center:** the supplied **metal pocket radar / stopwatch**, round gunmetal/silver body, screws and top loop, **red arched `LOT RADAR` on the upper metal rim**, **green `LOT RADAR` inside the screen**, green grid and sweep, and rows of miniature colored cars. Preserve its exact face/lettering and style from the supplied original emblem. The earlier failed versions replaced or dropped its lettering; never do that again.
- **No enormous separate `LOTRADAR` wordmark** beneath the stopwatch. The logo itself is the brand.
- Lower center: elegant small **`INITIALIZING LOTRADAR`** line, blue metallic horizontal loading meter underneath, and visible startup stages across the bottom. The mocked image's aesthetic is the target, not a fixed 72%-complete runtime state.
- Preserve four short prominent statuses **SYSTEM CHECK / LOADING MODULES / STARTING SERVER / LAUNCHING LOTRADAR**, with clear complete/active/pending indicators. Under `LOADING MODULES` disclose Python/dependencies and browser runtime (both are real distinct bootstrap stages) in details or a small substatus, so no stage is falsely skipped. If changes to stage grouping are necessary, explain and test exact mapping.
- Keep the actual working controls available: **Show details**, **Show console**, **Retry** on failure, and **Close** with the established safely-continue-startup semantics. They may be visually subdued/contextual in the cinematic interface, never clipped or removed.
- Center the artwork within a 16:9 launch window; adapt to narrow laptop displays, high DPI, and ultrawide desktop without stretching the stopwatch/cars. Avoid covering logo/sweep with controls.

## Current architecture / behavior

At the inspected PR #5 HEAD:
- `startup/Show-LotRadarStartup.ps1` (WinForms/PowerShell 5.1) constructs a fixed 480×330 logical-pixel, manually DPI-scaled window with standard labels/buttons and an indeterminate progress bar. This is functional infrastructure but **not** the approved cinematic artwork.
- `Launch Marketplace Scanner.cmd` invokes the startup GUI where available, with console fallback.
- `Marketplace Bootstrap.ps1` alone owns the local server and launch locks, emits nonce-bound real startup stages, and opens the browser once.
- The GUI verifies real `open:complete` **plus** localhost `/api/health` before indicating ready.
- Installer builder `scripts/build_installer.py` currently obtains private branding via `--asset-dir`, never public Git. The new splash needs a **separate private asset** production-path contract; its existence/format/hash must be checked, and its absence in DEV builds must not silently misrepresent an approved production splash.
- PR #8 plans compiled distribution later; this visual addition must remain compatible with its final resource embedding without editing PR #8 as part of PR #5.

## Implementation plan for Claude

1. On `feat/windows-startup-status-window`, verify the latest feature SHA, current `main` and UI/installer/QA files. Do not alter installed Owner data. Confirm private approved image bytes by SHA-256 when they are made available.
2. **Separate static art from live controls.** The reference PNG **contains baked-in** `72%` and a fully drawn progress meter/checkmarks. Those **must not be used as a static progress display**. Make a clean visual-background derivative by removing/reconstructing the lower mock UI region, while preserving the approved high-detail artwork and main logo. Then build actual progress and status indicators as live, accessible controls over that region. Do not fake percentage values: use an indeterminate blue animation if no objectively measurable progress fraction exists; phase completion must come from real bootstrap events. Do not fabricate countdowns or ETAs.
3. Introduce a secure resource loader for `branding/startup_splash.png` or a clearly named private build resource. In production, **require and verify** the approved splash asset along with existing private production branding, without placing it in public Git. For DEV/test kit, have a clearly labeled nonbranded fallback with unchanged startup behavior and tests. Resource-loading failures must show meaningful fallback/status, not strand launcher/server.
4. Preserve and animate real stage changes only: install => SYSTEM CHECK; python + browser checks => LOADING MODULES (accurate subdetails); server => STARTING SERVER; open/health => LAUNCHING LOTRADAR and terminal complete. On failure, show the actual short error and Show console/Retry/Close. Preserve existing nonce, health, no-double-launch and return-code semantics.
5. Implement professional resizing/scaling: default centered window sized reasonably within available work area, 16:9 safe composition, 100/125/150/200% DPI, 1366×768 and 1920×1080 and 3440×1440 displays, no stretched logo, no cropped progress/status/buttons, no stealing game/fullscreen focus. No forced fullscreen. UI remains responsive under slow downloads and errors; close-while-starting makes server console visible without killing the owned startup job.
6. Ensure all UI artwork is bundled into **private production installer payload**, SHA-256 manifest recorded, rollback-safe, and no runtime network image loading. Dev/test QA kits do not include the owner's private artwork unless explicitly authorized through a private delivery mechanism. Never send user-specific imagery/logs to public Git.
7. Write visual acceptance tests and safe manual QA instructions: compare screenshot against approved master at matching aspect ratio, inspect exact `LOT RADAR` bezel + center lettering, presence of moon and cool palette, absence of giant independent wordmark, correct lower UI state, control visibility, accessibility/keyboard navigation, high DPI, success/failure/retry, second-launch and close-mid-start flows.
8. Rerun the already established `G1–G10`, `E1–E6`, R1–R8, OneDrive, installer/launcher and full-launch tests from a fresh feature-head package, with proper result flags for tests not executed. Have Gemini independently audit the actual rebuilt private package at an exact SHA. Return `CLAUDE_PR5_CINEMATIC_SPLASH_HANDOFF.md` detailing image hash, file changes, screenshots, build artifacts, test results, remaining blocked gates and regressions.

## Protected functionality and files

**Allowed to change for this task:** `startup/Show-LotRadarStartup.ps1`, narrow static-resource/private-asset paths in `scripts/build_installer.py`, `tests/test_installer_build.py`, `tests/test_startup_window.py`, `tests/windows/*`, QA-kit build logic and relevant `docs/*`. Any `Marketplace Bootstrap.ps1` or `Launch Marketplace Scanner.cmd` semantic changes must be justified and separately reviewed.

**Do NOT change:** `server.py`, `core.py`, SQLite/drafts, imported vehicle records, photo export/picker/classification, Chrome Reader pairing and permissions, Facebook posting/prep, SalesmanHub connector, runtime lock/port behavior, local-only data/photo directory, original private business card/dedication/logo, source-only cloud reparse guard, strict destination guard, rollback checks or PR #7/#8 scope.

## Acceptance criteria

| Gate | Measurable pass condition |
| --- | --- |
| VIS-01 | Exact approved PNG received privately, width/height and SHA-256 match; not committed to public Git. |
| VIS-02 | New production GUI visually follows the approved blue/purple cinematic composition and full-size correct radar watch face, with both `LOT RADAR` labels but **no separate oversized wordmark**. |
| VIS-03 | Animated progress/stage UI is independently rendered, real data-driven and never stuck/falsely displaying baked-in 72%; four visible stage headings have correct complete/active/pending states. |
| VIS-04 | Real `open:complete` + healthy localhost service required for terminal success; failure/retry/console semantics intact, one server only and no duplicate browser launch. |
| VIS-05 | 100/125/150/200% DPI and 1366×768 / 1920×1080 / 3440×1440 manual and screenshot checks show readable, accessible, uncropped artwork and controls. |
| VIS-06 | Private production package manifest includes validated splash, original 4 branding assets and exact source SHA; no private asset, compiled program, sensitive data or passwords committed to public branch. |
| VIS-07 | Synthetic DEV package still testable with clear nonproduction fallback; real install, OneDrive, symlink, startup and cleanup regression suites pass on the final change SHA. |
| VIS-08 | Owner visually signs off on a private packaged screenshot/sample and Gemini audits before PR #5 can be considered ready. |

**Git:** Continue existing **draft PR #5**. No separate competing startup PR, no merge into `main`, no publishing the raw approved picture or binary installer in public Git. Only Project Owner may authorize final merge/release.
