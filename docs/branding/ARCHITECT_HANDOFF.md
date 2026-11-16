# ARCHITECT_HANDOFF.md

**To:** Claude — Lead Programmer  
**From:** ChatGPT — Chief Architect, LotRadar  
**Date:** 2026-11-16  
**Task:** Official LotRadar radar-logo integration (SEPARATE from photo gallery QA)  
**Repository:** https://github.com/iDarknesskiller/LotRadar  
**Approved baseline:** `main` at `b9e843111ce1ed39f7d4003dd39c06eb75724325`  
**Proposed branch:** `feat/lotradar-radar-branding`  
**Release authority:** Project Owner only. **No merge authorized.**

## Request
The Project Owner supplied a new official LotRadar radar image. Integrate this *unchanged* image as the application branding, first for the app sidebar/header, browser tab/favicon, and Windows shortcut. Treat this as a separate visual change: **do not combine it with the currently blocked photo-gallery feature PR #3**.

The source image is provided privately in `LOTRADAR_NEW_LOGO_PRIVATE_ASSETS.zip`, not in the public GitHub repository. It is a **256 × 256 transparent RGBA PNG**, file name `lotradar_logo.png`, SHA-256 `b598d23ba243d30274d59ba78abc1571348b46eefbccd494a9dd3e0af2820e7d`. The ZIP also contains a Windows `LotRadar.ico`, created by standard resizing from that exact source (SHA-256 `a0bf137e9b9901a57b668835bb351f26d099ea7a1ea29cc3d43567af605dc4b5`). The supplied original PNG must remain byte-identical; do not redraw, crop, watermark, recolor, stylize, remove transparency, or change text.

## Current behavior
- `index.html` lines 14–15 show `.brand-mark` containing text `L` and `R` and an adjacent `LOT RADAR` title; it does not load a logo image.
- `styles.css` defines a 45 × 45 px `.brand-mark` and hides the sidebar brand below 760 px.
- `server.py` uses an explicit `STATIC` path map for `/`, `/index.html`, `/app.js`, `/styles.css`, `/photo-selection.css` and MIME map for HTML/JS/CSS only; it does not serve any logo PNG/favicon.
- `scripts/build_installer.py` injects private `business_card.png`, `dedication.jpg`, and an optional `LotRadar.ico` from `--asset-dir`; binary private branding is not tracked in Git.
- `installer/Install-LotRadar.ps1` points desktop/Start Menu shortcut icons to `LotRadar.ico` if present.
- Chrome Reader `chrome-extension/manifest.json` has its own version and no dedicated icon mapping. That extension is **not** a required logo-integration target in this cycle.
- Source-of-truth `main` does not contain tracked PNG/JPG/ICO images; the repository is **public**.

## Required behavior
1. Display the exact supplied radar PNG in the application's brand mark at useful accessible sizes. Preserve the product name as readable text/alt text. The icon must fit dark and light themes and not obscure navigation.
2. Serve the image locally under an exact allowlisted static route, with `image/png`, same-origin usage, and no paths resolved from caller-controlled user input. Add a local favicon using appropriate generated icon derivative(s) only; never download external logo URLs at runtime.
3. Production installer includes the radar PNG and replaces the Windows shortcut icon with the supplied `LotRadar.ico`. Keep branding assets supplied through the private `--asset-dir` workflow. In dev/test builds lacking those assets, provide a graceful fallback to the current `LR` text branding and never break page load, installer, or launcher.
4. Keep all dealer photo exports unchanged: `business_card.png`, `dedication.jpg`, original dealer photos, classified photo order, VIN/cache, and Facebook draft data are entirely separate. The new radar logo must **never** be inserted into dealer galleries or uploaded as a vehicle image.
5. The new branding appears consistently on Windows 10 verified builds. Treat Windows 11 as untested under existing release waiver; do not claim it passes.

## Relevant architecture / affected files
- `index.html`: replace/augment `.brand-mark` using an image with a text fallback and accessible label, add favicon reference.
- `styles.css`: size/containment/alignment for logo; dark/light theme and narrow screens; do not alter photo-gallery styles.
- `server.py`: exact allowlisted static PNG/ICO mapping and MIME coverage; keep existing local-host and session protections.
- `scripts/build_installer.py`: private asset registry and production build verification; optional generated derivatives if approved; keep deterministic ZIP behavior and no private assets tracked in Git.
- `installer/Install-LotRadar.ps1`: validate existing optional icon behavior and shortcut path; change only if real Windows testing reveals a defect.
- `tests/test_installer_build.py`: add synthetic image/icon fixtures and assert private packaging, stable hashes, missing-assets behavior, and path safety.
- Add focused tests for static asset serving, fallback, HTML presence, and content type; use synthetic fixtures in tests, not owner branding.
- `docs/INSTALL.md`: note the new private files, packaging command, and fallback behavior.

**Do not modify** `app.js`, `photo_cache.py`, `photo_selection.py`, `photo_classify.py`, `dealer_site_scraper.py`, `core.py`, `chrome_bridge.py`, `chrome-extension/*`, Facebook implementation modules, database schema, or any runtime data unless an observed and separately approved integration defect requires it.

## Ordered implementation plan
1. Checkout **approved `main` `b9e8431`** and continue `feat/lotradar-radar-branding`; check no uncommitted source changes. Avoid basing on the unmerged photo-gallery branch.
2. Review the uploaded PNG and ICO under a private asset directory outside tracked files. Verify PNG dimensions, alpha and SHA-256; verify ICO header and multi-size frames. Never commit the ZIP or images to the public repo.
3. Define an exact stable local asset URL (e.g. `/branding/lotradar_logo.png`) and add its explicit `STATIC` handler and `image/png` MIME. Ensure a missing file returns a controlled fallback/404 instead of a server exception; no path traversal and no server-side discovery of arbitrary filenames.
4. Adapt `index.html`/`styles.css` to render the radar mark at a legible size inside its existing brand area, respecting layout width, keyboard navigation, text labels, dark/light themes, and mobile breakpoints. Fallback to the legacy LR mark in development/no-logo installations. Add a favicon route as appropriate (a private ICO is available). Use cache-busting based on a stable build/revision, not a stale browser cache.
5. Register the private PNG as a production package asset and ensure the `LotRadar.ico` used in production matches the new image. Decide explicitly whether missing radar PNG/ICO should fail **production** builds (recommended) with clear instructions; development builds should continue to work without private assets. Do not silently substitute an older icon in production. Update the build manifest/test expectations accordingly.
6. Maintain the existing `business_card.png` and `dedication.jpg` paths and their current roles unchanged. Keep original image data outside source and ensure the public tree, commits, Git diffs and logs contain no private branding bytes.
7. Run the required tests, capture screenshots and Windows shortcut behavior, and submit only this branding diff for independent Gemini review. Any unrelated failure belongs to its existing PR or a new task, not this branch.

## Protected functionality
- Inventory scans, used-only feeds, Toyota primary/Mitsubishi fallback, Chrome Reader pairing, Facebook preparation, vehicle records, drafts, VINs, photo classifications, vehicle-image downloads, caching and exports.
- `%LOCALAPPDATA%\MarketplaceScanner\data`, `runtime`, `ProgramBackups`, and all private business-card/dedication assets.
- Localhost-only API constraints, safe static path allowlist, token checks, lock interlocks, rollback and deterministic package hashes.
- PR #3's photo-gallery work must remain separate and unmerged until its Windows/browser smoke tests pass.

## Acceptance criteria
1. The installed Windows 10 app displays the original logo recognizably at the branding location, without distortion, clipping, blur from artificial upscaling, or layout overflow, in both dark and light themes.
2. The original PNG in the production payload has SHA-256 `b598d23ba243d30274d59ba78abc1571348b46eefbccd494a9dd3e0af2820e7d` and remains unchanged. Shortcut icon is visually the same radar image and uses the packaged icon.
3. Local logo resource returns HTTP 200 with `image/png` and identical bytes; any other unapproved arbitrary path returns a safe denial/404.
4. No logo installed in a development package -> app still starts and text fallback remains visible; no browser console crash.
5. Production ZIP verification passes with required assets and fails clearly when the required logo/icon is absent or corrupted. Repeated builds from identical source/assets have identical ZIP SHA-256.
6. No original photo or export/overlay changes, database writes, network logins, or Facebook publishing; no binary private assets committed to public GitHub.
7. Logo is visible in a Windows Explorer desktop/Start Menu shortcut after installer setup (allowing for Windows icon cache refresh) and in the browser tab where supported.
8. QA confirms the file diff is limited to branding/UI/static path, package configuration, docs and tests; there are no changes to scanning or photo selection semantics.

## Required tests to actually execute
- `python -m unittest discover -s tests -v` and existing installer packaging tests, plus new synthetic-private-asset and static-route tests.
- Build DEV package without logo assets and smoke-test browser fallback.
- Build PROD package with new logo, business card, dedication, and ICO; verify manifest exactly once, SHA-256, deterministic repeat build, and no private binary paths tracked by Git.
- On Windows 10 with a standard user, use the built production ZIP to install/upgrade with backup, then double-click Desktop and Start Menu shortcuts; inspect correct icon and app page.
- Browser layout checks at desktop and narrow viewport in **both light and dark themes**, including reload/cache refresh and missing image fallback. Confirm browser tab icon and console has no 404 loop or uncaught errors.
- Regression check: one existing branded vehicle photo ZIP retains business-card cover and dedication image with unchanged original dealership-photo hashes. Do not upload or post photos to Facebook.
- Gemini reviews actual diff and logs and reports PASS/PARTIAL/FAIL with evidence and omissions. Never treat a test not run as PASS.

## Risk areas
- 256 px source may be unsuitable for oversized display; do not invent resolution; show conservatively.
- Installer private-asset allowlist and public repository privacy policy; logo cannot be accidentally published.
- Cache staleness, alpha transparency/light-theme legibility, tiny favicon readability, icon caching in Explorer, fallback on DEV packages, and fixed-route path traversal.
- Photo-gallery PR #3 remains blocked by Windows 10 browser/network validation and should not be mixed into this release.

## Git instructions and handoff destination
1. This document is an architecture-only handoff addressed to **Claude — Lead Programmer**.
2. Continue/create `feat/lotradar-radar-branding` from approved `main` commit `b9e843111ce1ed39f7d4003dd39c06eb75724325`. Use a **draft** PR; do not merge into `main`.
3. Commit only source, documentation, and tests. Do not commit the logo PNG, ICO, production ZIP, databases, photos, customer records, pairing keys or secrets to the **public** repository.
4. Return changed-file list, hashes/provenance, full automated test output, Windows screenshots and limitations to **Gemini — Independent QA**, then to ChatGPT for architecture review.
5. Only the Project Owner may explicitly authorize merge/release after QA and the required tests.