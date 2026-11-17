# Manual acceptance checklist (cannot be automated)

**Scope for the approved `main` release (`bf61207`; Project Owner waivers, recorded 2026-11-16):** Windows 10 is the
verified platform. **Windows 11, OneDrive-redirected extraction/installation and the R3 file-symlink refusal test are
WAIVED - NOT VERIFIED** for that release (not passed). Its link/reparse-point guard (`Test-UnsafeLink`), path containment
and checksums stay enabled. Release label: **"Windows 10 verified; Windows 11 untested."** Extract that release into an
ordinary local folder (for example `C:\LotRadarInstall`), not into OneDrive.

**PR #5 candidate (unmerged; automated evidence at `673fe9d`, 2026-11-17):** Windows 11 Home build 26200, standard
user, Developer Mode on: installer suite 48 PASS / 0 FAIL / 1 SKIP, **R3 PASS**; extraction inside a hydrated
**Personal OneDrive** Files On-Demand folder 51 PASS / 0 FAIL / 1 SKIP (cloud placeholders accepted for the package
source only; links inside the package and cloud/linked install destinations still refused). **Still open for the
candidate:** F1 full launch (skipped, not passed), this manual checklist on Windows 11, Windows 10 re-run, online-only
placeholders, OneDrive for Business and other cloud providers. These results are automated only; they do not fill in
the Windows 11 column below.

Run each item on **Windows 10** (and on Windows 11 for the PR #5 candidate), as a standard user, using a package built from the commit under
test. Record OS build, package version and PASS/FAIL. Do not use real customer data; do not post to Facebook.
Use a test profile or a machine where overwriting `%LOCALAPPDATA%\Programs\MarketplaceScanner` is acceptable
(data in `%LOCALAPPDATA%\MarketplaceScanner\data` is preserved, but back it up first).

## A. Explorer double-click
1. Extract the ZIP to a normal folder. Double-click `Installer.cmd`. Expect "INSTALL COMPLETE" and the window to stay open.
2. Temporarily rename `Install-Manifest.json` in the extracted package folder, then double-click `Installer.cmd` again.
   Expect a clear error, a pause, and no change to the installed program. Restore the file.
3. Double-click the Desktop `LotRadar` shortcut and the Start-menu `LotRadar` shortcut. Expect LotRadar to open once
   (second click: "already running", no second server).
4. Rename the installed `Marketplace Bootstrap.ps1`, double-click the shortcut: expect "error code 2" message and a pause.
   Restore it.
5. Temporarily make PowerShell unavailable is not safe on a real machine; instead rely on the harness-only static
   check for exit code 3 and record this item as NOT RUN unless a disposable VM is used.
6. Force an error (e.g. hold `marketplace-launch.lock` open from another PowerShell). Expect a readable message and pause.

## B. Offline
1. Fresh user profile (or after deleting the *venv* only, never the data): disconnect the network, launch. Expect a clear
   failure message, no server. Reconnect, launch again: provisioning resumes and the app starts.
2. With everything installed, disconnect and launch: the app must still start.
Health must show `ok=true, local_only=true, service="Marketplace Scanner"`; one server process tree.

## C. Chrome Reader
1. `chrome://extensions` > Developer mode > Load unpacked > `%LOCALAPPDATA%\Programs\MarketplaceScanner\chrome-extension`.
2. Pair with LotRadar. Open one dealership vehicle page and read it (read-only). Confirm no Facebook page is touched.
3. **Version evidence:** compare name/version in the source `chrome-extension/manifest.json`, the package ZIP, the installed
   `%LOCALAPPDATA%\Programs\MarketplaceScanner\chrome-extension\manifest.json` and the extension card in
   `chrome://extensions` (expected `LotRadar Browser Reader` 1.9.7; the card's Details > "Loaded from" must be the installed
   folder; remove any older unpacked copy). `tests\windows\Get-LotRadarEvidence.ps1 -Mode Version -PackageZip <zip>` prints
   the first three with SHA-256.
4. **VDP read-only evidence:** with `/api/health` healthy, open one legitimate dealership used-vehicle page, trigger the
   Reader, and confirm VIN/stock, make/model, mileage and price in LotRadar match the page (only fields present on the
   page). Nothing may be published to Facebook.

## D. Production package + photo export
1. Build from a clean commit with the owner's branding supplied privately: `python scripts/build_installer.py build --mode production --asset-dir <private folder outside the repo>`.
2. `python scripts/build_installer.py verify <zip> --require-production`; compare the ZIP SHA-256 with the manifest note.
3. Install it. Export photos for one vehicle (read-only): business-card cover first, dedication image, exterior before
   interior, originals unchanged. Hash evidence: `Get-LotRadarEvidence.ps1 -Mode PhotoSnapshot -Vin <VIN> -OutFile <file outside data>`
   before the export and `-Mode PhotoCompare -Vin <VIN> -BeforeFile <file>` after it (read-only; changed/deleted originals must be 0).
4. A DEV-NOBRANDING package must report `branding_assets_missing`.

## E. Startup window (PR #5 candidate; Windows 11 and Windows 10)
Automated: G1-G5 every run, G6-G8 with `-FullLaunch` (window over the real bootstrap). Still manual:
1. Explorer double-click of the Desktop shortcut: one LotRadar startup window, steps change from Waiting to In progress
   to Done, LotRadar opens once, the startup window closes by itself, "LotRadar Server" stays in the taskbar.
2. Double-click again while LotRadar runs: LotRadar opens again; still one "LotRadar Server" window.
3. Keyboard only: Tab moves between the buttons, Alt+S / Alt+C / Alt+R / Alt+L work, Esc closes.
4. Display scaling 150% (Settings > Display): text and buttons are not cut off.
5. Close the startup window while it shows "In progress": the "LotRadar Server" window comes up and LotRadar still
   opens; nothing is stopped.
6. Failure: with LotRadar running from a DIFFERENT folder or another program on port 8765, the window shows the port
   message; Show console shows the output; Retry after closing the other program works; Close leaves no console behind.

## Result table
| Item | Windows 10 | Windows 11 |
|------|-----------|-----------|
| A1-A6 | | |
| B1-B2 | | |
| C | | |
| D | | |
| E1-E6 | | |
