# Manual acceptance checklist (cannot be automated)

Run each item on **Windows 10 and Windows 11**, as a standard user, using a package built from the commit under
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

## D. Production package + photo export
1. Build from a clean commit with the owner's branding supplied privately: `python scripts/build_installer.py build --mode production --asset-dir <private folder outside the repo>`.
2. `python scripts/build_installer.py verify <zip> --require-production`; compare the ZIP SHA-256 with the manifest note.
3. Install it. Export photos for one vehicle (read-only): business-card cover first, dedication image, exterior before
   interior, originals unchanged.
4. A DEV-NOBRANDING package must report `branding_assets_missing`.

## Result table
| Item | Windows 10 | Windows 11 |
|------|-----------|-----------|
| A1-A6 | | |
| B1-B2 | | |
| C | | |
| D | | |
