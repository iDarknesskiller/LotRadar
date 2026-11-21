# ARCHITECT_HANDOFF.md — Source Layout and Compiled Windows Distribution

**To:** Claude — Lead Programmer (sole implementation owner)  
**From:** ChatGPT — LotRadar Chief Architect  
**Project Owner:** Final approval for release, repository visibility changes and merging  
**Repo:** https://github.com/iDarknesskiller/LotRadar  
**Feature branch:** `feat/source-layout-compiled-distribution`  
**Approved `main` at inspection, 2026-11-17:** `bf61207a21999c8ff256b08c0d17650193e3835f`  
**Current version:** No canonical app version; scanner UI/README mentions `R62`, Chrome Reader `manifest.json` reports `1.9.7`, and installer identity is `package_version` plus full `source_commit` in `Install-Manifest.json`. Do not equate those version strings.  
**Stage:** Architecture only. No source files or installer logic have yet been modified for this request. Keep a dedicated DRAFT PR. Never merge to `main` without Owner authorization.

## Request

The Project Owner reports that the approved `main` GitHub root has too many top-level app files, that downloading `main` and trying to install LotRadar did not work ("missing something"; no precise console/error log supplied), and wants a **proper standalone compiled Windows installer** so recipients do not receive easily readable Python application source. The Owner wants clean, meaningful source folders, a double-clickable working installer for a fresh Windows 11 machine, and code protection beyond simply shipping plain `.py` files.

**Important constraints / candid security boundaries:**
- A GitHub **Source code ZIP** is NOT an installer; `main` currently has no generated installer artifact and no `LotRadar.exe`. Do not advertise "Download ZIP" from the code page as an install method.
- The repository is currently **PUBLIC**. Compiling a download does not make existing GitHub source private. Do **not** change repository visibility, purge history, rotate secrets or force-push automatically. Recommend to the Owner a deliberate separate decision to make source private and restrict artifact publication. Previously downloaded/forked copies cannot be recalled.
- No locally executable application is impossible to inspect or reverse-engineer. Compiled native backend improves resistance to casual source reading; **HTML/JS served to a local browser remains inspectable**, and the unpacked Manifest V3 Chrome extension remains inspectable by Chrome users. Minification/obfuscation may reduce casual readability but is NOT security or secrecy. Secret keys/credentials must never be embedded in a binary or delivered JS. If a business algorithm must be truly secret, propose a separately approved server-side design.
- The immediate goal is **a verified compiled, source-minimized Windows distribution**, not an unsupported promise that absolutely no user can ever recover any implementation.

## Current behavior and confirmed root architectural limitations

1. **Root layout:** Almost all Python app code is directly at repo root: `server.py`, `core.py`, `photo_cache.py`, `photo_selection.py`, `dealer_site_scraper.py`, `chrome_bridge.py`, `facebook_auto.py`, `feed_sync.py`, `ai_copy.py`, etc. Browser assets `app.js`, `index.html`, `styles.css`, `photo-selection.css` are also root. Chrome Reader files live under `chrome-extension/`. Installer, scripts, docs and tests already have their own folders.
2. **Launcher:** `Launch Marketplace Scanner.cmd` invokes `Marketplace Bootstrap.ps1`, which directly expects adjacent `server.py` and `requirements.txt`, creates/finds private `%LOCALAPPDATA%\MarketplaceScanner\runtime\setup-venv`, and may use WinGet to install Python 3.13, pip-install `requirements.txt`, and `playwright install chromium` on first launch. The server then binds **127.0.0.1:8765**. A user with no build tools/Internet/dependencies can encounter setup failures after installing source files.
3. **Current "installer":** `scripts/build_installer.py` builds a deterministic **ZIP containing plaintext source** from a strict `SOURCE_ALLOWLIST` and optional private asset directory, plus package-root `Installer.cmd`, `Install-LotRadar.ps1` and README. `installer/Install-LotRadar.ps1` hashes all packaged files, stages, replaces only `%LOCALAPPDATA%\Programs\MarketplaceScanner`, backs up previous code and creates shortcuts. Current tests expressly **forbid .exe files** in the payload; manifest/allowlist/test contracts must be redesigned for compiled artifacts.
4. **Private production assets:** `business_card.png`, `dedication.jpg`, `lotradar_logo.png` and `LotRadar.ico` are required by `build_installer.py build --mode production --asset-dir ...`. They are intentionally **absent from public source** and must remain outside public Git. A generated DEV-NOBRANDING installer is not a production-ready package and may fail branding-dependent exports.
5. **Import/static paths:** `server.py` imports unqualified sibling modules (`from core import MarketplaceStore`, `from photo_cache import PhotoCache`, etc.). It defines `BASE=Path(__file__).resolve().parent`, serves `index.html`, `app.js`, CSS and logo/icon relative to BASE, and exposes `--data-dir` for an external persisted data root. `photo_cache.py` similarly locates `branding/` from `__file__`. Scripts such as `Export Inventory for SalesmanHub.cmd` assume a private `python.exe` plus adjacent `connector_export.py`. Relocation/binary freezing without explicit resource/import mapping will break serving, photo overlays, exports and first launch.
6. **Browser extension:** `chrome-extension/manifest.json` is Manifest V3, extension version 1.9.7, and refers to `background.js`, `marketplace_signal.js` and `popup.html`. The browser requires an accessible manifest and extension JavaScript. Never place pairing tokens or secrets into frontend or extension artifacts.
7. **Current installer failure:** The Owner's exact failing action/error is **not yet evidenced**. Possible confusion between GitHub source ZIP and built ZIP is established by the build architecture, but the precise failure (missing branding, bootstrap, runtime/Chromium, missing packaged files, incorrect extraction, OneDrive tags, etc.) **must be reproduced and logged**, not guessed.
8. **Concurrent development:** Approved main does not yet contain **draft PR #5** (Windows startup GUI and tested hydrated OneDrive/source-reparse protection) or **draft PR #7** (safe Windows uninstaller plan). Do NOT silently cherry-pick unapproved code, and do NOT regress those features when later integrating.

## Required behavior

### A. Clean source layout, not a cosmetic mass-move

Proposed layout for Claude to refine after dependency/import audit:

```text
LotRadar/
  README.md
  pyproject.toml                     # if selected, declared source package/build metadata
  src/lotradar/
    __init__.py
    __main__.py
    backend/                        # HTTP API, auth, storage and common domain core
    scanner/                        # dealer readers, feed sync, headless/Chrome bridge
    photos/                         # cache, detection, overlays, selection/export
    facebook/                       # draft/form preparation, listing transfer
    integrations/                   # SalesmanHub connector, specialized adapters
    resources/web/                  # index.html, app.js, styles.css, photo-selection.css
  extensions/chrome-reader/          # complete original Manifest V3 Chrome Reader source
  packaging/windows/                # packaging specs, launcher, install/upgrade assets
  scripts/                          # developer-only build/verification tools
  tests/                            # unit, browser, Windows installer/security and smoke
  docs/                             # install, compatibility, architecture and QA
```

This is a **target map, not permission to blindly rename every file**. Create an actual dependency/path inventory for every moved module; use a commit-by-commit relocation map with old→new paths and explicit changes to Python imports, test imports, static routes, resources, startup, build allowlists and docs. Keep root restricted to standard repo metadata and human-facing README/build entrypoints; remove obsolete duplicate top-level files only after tests. Do not relocate runtime customer data inside source tree.

### B. Working compiled Windows distribution

- Deliver a **double-clickable `Setup-LotRadar.exe` or equivalently named signed-ready per-user setup executable** built on Windows from a pinned, exact approved/tested source SHA. The installed app launches via `LotRadar.exe` (or a documented compiled equivalent), with correct icon/branding, no visible plain `server.py` or other proprietary Python source in installed payload, no need to install Python/Node/Git to use it, and no first-run pip/WinGet requirement. Avoid supplying a launcher that still depends on executing `server.py` from adjacent source.
- Prefer a **one-directory compiled backend/runtime** initially rather than a self-extracting onefile with slow cold start, temporary executable extraction and antivirus complications. Conduct a **feasibility spike** comparing **Nuitka standalone/native compilation** versus PyInstaller onedir (PyInstaller commonly bundles inspectable bytecode); select based on tested support for `beautifulsoup4`, `Pillow`, `playwright`, Windows Forms startup window, packaging license/compliance, size, runtime import hooks and malware false positives. If neither passes the tests, report the blocker; do not falsely call a wrapper script or zipped `.pyc` "protected compiled source." Document what reverse engineering remains possible.
- Bundle a verified compatible **Playwright Chromium** runtime or implement an explicitly approved, hash-verified optional first-run download that does **not** silently require a global Python installation. The owner wants a working clean-machine installer: the **offline installation and opening of the local UI** should succeed without external downloads. Live dealer scanning naturally needs internet, but offline cached inventory browsing must still work.
- Deliver frontend assets in appropriate **resource bundles** or minified static files; preserve exact browser routes, branding, accessibility, DOM IDs and JS behavior. State clearly that local-browser assets remain inspectable through browser developer tools and extension scripts must remain usable.
- Preserve the local-only bind `127.0.0.1:8765`, pairing/authentication semantics, installer/launch single-instance lock and correct subprocess shutdown. No external network listener or unsolicited cloud dependencies.
- Set up **repeatable, deterministic-source** build orchestration with manifest `source_commit`, `package_version`, build/toolchain versions, target OS/architecture, hashes of EXE/resources/installer, build type and included private assets. Signed release is a separate Owner decision requiring a certificate; unsigned binaries are not "verified/signed". Release binaries must never be committed into the public source repo as source.
- Installer must fail with **clear actionable error** on missing/corrupted files, locked app, unsupported CPU/OS, inaccessible resource, incompatible Playwright runtime, or unknown OneDrive/cloud state; preserve older installed program and user data, and provide recovery/rollback. Do not hide errors behind "Installation complete" followed by failing startup.
- Keep **%LOCALAPPDATA%\Programs\MarketplaceScanner** as the default program target and **%LOCALAPPDATA%\MarketplaceScanner\data** as persistent data. Keep photos (`data\vehicle_photos`), Facebook exports (`data\facebook_photos`), SQLite and drafts local-only. Do not migrate or delete existing data on upgrades. A cleanly wiped PC must work; an old installed PC must upgrade safely; a hostile junction/symlink must fail closed.
- Chrome Reader must be distributed and installed/loaded in a supported manner. Test the actual MV3 extension manifest, paths and pairing after compiled packaging. An unpacked extension remains visible to the browser and should not embed privileged business secrets.

## Relevant architecture: files to inspect/change

**Core relocation/build integration expected:**
- `server.py`, `core.py`, `photo_cache.py`, `photo_selection.py`, `photo_classify.py`, `dealer_site_scraper.py`, `dealer_features.py`, `feed_sync.py`, `chrome_bridge.py`, `headless_dealer.py`, `refresh_policy.py`, `facebook_auto.py`, `listing_transfer.py`, `ai_copy.py`, `trade_ready.py`, `vin_decode.py`, `system_load.py`, `connector_export.py`, `migrate_legacy.py`, `browser_trials.py`, `ai_copy.py` and other root Python files (map each only once).
- `app.js`, `index.html`, `styles.css`, `photo-selection.css` and `chrome-extension/*`: resource/layout mapping, **no unrelated UI redesign**.
- `scripts/build_installer.py` and `tests/test_installer_build.py`: source map, compiled EXE allowlist, reproducible build provenance, manifest schema and security verification. Add dedicated builder (e.g. `scripts/build_windows_release.py`) and a Windows build matrix.
- `Launch Marketplace Scanner.cmd`, `Marketplace Bootstrap.ps1`, `Export Inventory for SalesmanHub.cmd`: replace reliance on adjacent `server.py` and venv ONLY when compiled launch path is proven, maintaining compatibility fallback only for development workflows; never ship leaked plaintext backend source as fallback.
- `installer/Install-LotRadar.ps1`, `installer/Installer.cmd`, `installer/README - INSTALL.txt`: new compiled program payload, integrity + rollback + shortcut + packaged-resource installation, no first-run Python setup, and **integrate PR #5's source-only Cloud Files reparse guard only after approval**.
- `docs/INSTALL.md`, `docs/MANUAL_ACCEPTANCE.md`, `README.md`, tests under `tests/`: exact user instructions, regression matrix and visible source/release distinction.

**DO NOT MODIFY beyond minimal relocation/import adjustment:** inventory schema/meaning, VIN identity/business rules, scanner scheduling/priority, Facebook approval and autofill behavior, UI design/DOM semantics, photo processing/sorting/branding visuals or image pixel output, Chrome extension permissions, credential/pairing protocols, data migration semantics. Never alter real installed user records/photos/drafts, Git history or third-party private secrets for this work.

## Implementation plan — ordered engineering steps

1. **Verify source and scope.** Record latest approved main SHA, current feature HEAD, PR #5/#7 status, current distribution behavior, and exact failed-install scenario. Collect a reproducible failure log from a disposable Windows 11 standard-user VM/profile. Run the **current intended** builder from source with DEV assets and verify generated ZIP, then try its installer and first launch in isolated sandbox; distinguish "GitHub source ZIP not an installer" from a true packaged installer defect. If exact failure cannot be reproduced, classify UNKNOWN and preserve evidence; do not claim a fix without a failing test.
2. **Dependency and path graph.** Inventory every root module, imports, `__file__` references, relative static/branding paths, browser/extension asset paths, subprocess/script entrypoints, command-line flags and environment variables. Write `docs/packaging/MOVE_MAP.md` with old→new paths and compatibility shims. Identify import cycles and side effects, path redirection risks and any Test-UnsafeLink assumptions.
3. **Phase 1: organize source only.** Commit bounded logical moves to `src/lotradar`, `resources/web`, `extensions/chrome-reader`, and `packaging/windows`, adjusting import/resource paths and developer tools. Preserve a developer run command and tests. Keep runtime/data paths EXACTLY as before and verify no existing behavior changes. Do not combine mass moves with performance refactors or new features. Demonstrate expected and moved trees. If a module cannot safely be moved, document why and leave a narrow compatibility entrypoint, not an unexplained duplicate.
4. **Phase 2: compilation feasibility.** On actual Windows 11 x64, produce small compiled proof-of-concept including server + HTML/CSS/JS resources, Pillow/bs4/Playwright, local HTTP health, photo processing and Chrome Reader link. Record compiler version, Python build version, size, cold/warm startup CPU/RAM, AV/Defender result, import trace and private-data leakage scan. Compare candidate tools with source-readability reality; select one explicitly.
5. **Implement compiled app packaging.** Create executable entrypoint with reliable resource lookup (frozen/bundled vs development), reliable writable data root, local-only port binding, single-instance locks and clean teardown. Include web assets, extension resources, icon, business-card/dedication assets privately at build time, optional runtime browser in reliable path. Ensure older direct script paths still function for developer tests if retained; production package must not silently execute plaintext backend source.
6. **Installer rebuild.** Replace or carefully adapt manifest and staging to compiled payloads, explicit EXE and dynamic library allowlist, path/tag checks, checksum validation, install/upgrade rollback and correct Desktop/Start-menu shortcuts to compiled launcher. Provide `Setup-LotRadar.exe` (or a verified setup executable) and an easy README that says **this** is the user installer, not the GitHub code ZIP. Do not assert release signing until actually done.
7. **Offline bootstrap acceptance.** From a genuinely clean standard-user Windows 11 profile (no Python, Node or Git), install and launch LotRadar, verify localhost UI, existing features and extension setup without automatic global dependencies. Disconnected internet must still allow installer and local UI; scanning may report network unavailable clearly. First-run bundling must be validated, not assumed.
8. **Data integrity / upgrades.** In sandbox, install source-based approved-main build, seed SQLite/WAL/photos/drafts/settings and export selection, take SHA-256 snapshots, upgrade to compiled candidate, verify data and unchanged photo bytes, safe launch/stop, rollback after injected failure, and explicit no data-loss on abort. New install after full cleanup also tested; no use of actual Owner profile for destructive QA. Test staged and recovered backups.
9. **Security / release provenance.** Verify the installed compiled package contains **zero proprietary application `.py` and `.pyc` source/bytecode files exposed as plain loose files** (stdlib/vendor resources may require documented exclusions), no `.env` or tokens, no embedded secret, no hidden debug endpoints, no exposed source maps, no world-accessible server port. Check compiled EXE strings/archive disclosure and document reverse engineering limits, not impossible security promises. Evaluate changing repo from public to private as a separate Owner-approved step.
10. **PR #5 and PR #7 integration planning.** Startup GUI, Cloud Files tag guard and QA harness from PR #5, and future HKCU Windows Installed Apps uninstaller from PR #7, must integrate to the new executable path. PR #5 tests cannot be considered passed for the compiled product without retesting actual combined code. Avoid duplicating installer/lock/shortcut/uninstall logic. Merge order only after Owner decision. Maintain branch isolation until approved.
11. **Deliverable:** `CLAUDE_COMPILED_DISTRIBUTION_HANDOFF.md` with exact branch/HEAD, move map, reproducible build commands and toolchain pin versions, checksum and manifest, compiled bundle file inventory, build proof, fresh/offline/upgrade Windows 11 tests and outcomes, photos/database snapshot evidence, installer error reproduction, residual security limits, possible Windows 10 gate, and links to privately delivered setup artifact (only after upload+SHA-256 verification). Send to Gemini for independent security/installer audit and Chief Architect for approval review.

## Protected functionality

- Used-only Toyota/Mitsubishi inventory; Quick Scan, Verify Inventory, Check Listing Links, fetch missing photos, reader queue prioritization and connection behavior.
- VIN/stock/miles/price authority; source identity and validation; no invented equipment; no automatic Facebook posting.
- Data store SQLite WAL and migration safety, snapshots, drafts and photo selection metadata, original dealership image bytes, VIN/source photo cache, cover then dedication then exterior/interior order, 20-photo picker and exact export ZIP order.
- Chrome Reader MV3 manifest/permissions and pairing; browser polling without losing draft focus or caret; dark/light UI, 190px radar logo/icon; SalesmanHub export bridge.
- Windows 10/11 single-server at 127.0.0.1:8765, startup health and launch/install lock, PR #5 GUI behavior once approved, symlink/junction/cloud-tag guard, rollback, SHA-256 package verification, OneDrive KFM Desktop shortcut protection.
- Runtime/user data under LocalAppData, not public Git, synced OneDrive, or compiled executable directory. PR #7 uninstaller retains user data by default.

## Acceptance criteria

| ID | Measurable acceptance gate |
| --- | --- |
| PKG-01 | Approved `main` SHA and exact source-archive-vs-generated-installer behavior logged. No unsupported claim about actual prior failure. |
| PKG-02 | Root contains only standard repository metadata/entrypoints; application code, frontend and extension organized in logical folders, all imports/routes/path references corrected; move map complete. |
| PKG-03 | Development test suite and HTTP/UI/browser/synthetic scanner/photo tests pass after relocation, with no semantic behavior change. |
| PKG-04 | Windows 11 standalone **compiled** `LotRadar.exe` starts from installed path with no Python/Git/Node preinstalled and no first-run pip/WinGet; source files not distributed in readable backend form. |
| PKG-05 | A standard-user double-clickable compiled installer succeeds on a clean offline Windows 11 machine, leaves zero misleading hidden dependency requirements, and shows correct errors for missing/corrupt components. |
| PKG-06 | Correct private branding in production candidate; loss of any of four required assets makes **production build fail**, not silently produce an unbranded release. |
| PKG-07 | A nonempty old SQLite/photos/drafts dataset upgrades without modification, validates clean health, and rolls back safely after an injected stage/copy/launch failure; photo original SHA-256 unchanged. |
| PKG-08 | Chrome Reader MV3 remains loadable and pairs to installed compiled backend; UI static routes, logo/favicon, gallery and Facebook draft/editor behavior intact. |
| PKG-09 | Manifest lists exact source SHA, compiled outputs, licenses and SHA-256; package verifier rejects tampering, unknown files, unsafe links, code/secret leaks and wrong build type. |
| PKG-10 | Compiled app never binds outside `127.0.0.1`, does not embed private credentials, preserves locks/one server and cleans up on stop. |
| PKG-11 | Existing PR #5 and #7 functionality are either explicitly integrated with fresh tests or identified as **BLOCKED** pending separate Owner approval; neither PR is modified silently. |
| PKG-12 | No claim of irremovable code or signed EXE without evidence; all owner-facing install links refer to a **generated verified installer**, not the source ZIP. |

## Required tests Claude must execute

**Cross-platform and build:** `python -m unittest discover -s tests -v`; `node --check` on moved JS (where Node is available to developer); picker DOM integration; existing installer unit tests or adapted compiled-package equivalents; deterministic resource/hashes and strict source allowlist; verify wrong/missing private branding; syntax and import path tests; `python scripts/build_installer.py verify <generated package>` or upgraded verifier contract. Test compiler's reproducible provenance even if bit-for-bit compiler output isn't guaranteed.

**Windows 11 clean-machine (non-admin):** install/uninstall-reinstall as appropriate in disposable profile; Windows Defender/SmartScreen response recorded; PATH no python/node/git; disconnected network install+local launch; bundled browser runtime; local health and exactly one server process; double-click repeated launch; port 8765 contention; exact package SHA; icon/shortcuts; display and browser.

**Security:** File/directory symlink, junction, mount point, unknown and Cloud Files tagged source and destination; unsafe manifest paths, tampering, duplicate files, unknown payload, locked file rollback, interrupted install/upgrade, OneDrive hydrated extraction, no source/secret/exposed map files, no unauthorized runtime downloads or global dependency writes.

**Functional regressions:** imported synthetic used inventory+verified VIN/prices/mileage; Quick/Verify/Reader photo queue; downloadable original photo integrity and ordered selection/ZIP; cover/dedication assets; saved Facebook draft focus/caret; browser extension pairing and local API authentication; synthetic SalesmanHub export; SQLite schema compatibility and WAL close; local-only photo storage.

**Platform:** Windows 10 is **NOT** automatically covered by Windows 11 results. Either execute a separate compiled startup/installer test on Windows 10 or ask Owner to explicitly narrow supported platform. All missing tests remain BLOCKED/NOT TESTED rather than PASS.

## Risk areas / mitigations

- Massive Python import/path relocation and circular imports; packaged-resource lookup changes and unreadable CSS/JS/branding; Chrome extension absolute path and permissions.
- Native compilation conflicts with Playwright child processes, Chromium distribution, antivirus warnings, LGPL/MIT/BSD/Chromium distribution notices, architecture/compiler toolchains, DLL loading and frozen process lifecycle.
- Build-time private asset leakage, source maps, credential exposure, secret-in-binary misconceptions, public repo visibility; external downloads and malicious installer spoofing.
- Installer manifest schema changes may break proven R1–R8 safety, OneDrive source-only cloud allowance, rollback/backup and PR #7 safe uninstaller/receipt design.
- Existing old installations must not lose photos/database when code moves; avoid data in program directory or OneDrive, backup and verify before first real upgrade.
- Large browser/runtime package size, cold-start delay, Windows Defender false positives, lost error visibility, failure to restore shortcut after interrupted QA; never claim success without clean OS proof.
- Untracked/unpackaged files from public source ZIP, hidden four private assets, incomplete frozen dependencies and no reliable reproduction of Owner-reported installer failure.

## Git instructions and handoff

Claude develops only on `feat/source-layout-compiled-distribution`. Commit Phase 1 **source-layout-only** and Phase 2 **compiled packaging** separately for review. PR must remain **DRAFT**. Keep PR #5 (Windows startup GUI / OneDrive QA) and PR #7 (safe uninstaller) as independent feature branches; Copilot performance issue #6 is read-only. No merge to `main`, no public release of binaries or branding, and no change of repository visibility or secrets without explicit Project Owner authorization. Return `CLAUDE_COMPILED_DISTRIBUTION_HANDOFF.md` to ChatGPT Chief Architect and request independent Gemini audit.
