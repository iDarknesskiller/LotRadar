# LotRadar: build, install, upgrade and roll back (Windows)

This repository is **public**. It holds source code and installer *tooling* only. A working installer package is a
**generated artifact** (a ZIP) built from a commit, and it is **never committed to Git**. Private branding images
are supplied locally at build time and must never be committed.

## Terms

| Thing | What it is |
|---|---|
| Source checkout | This repo. `Launch Marketplace Scanner.cmd` runs `Marketplace Bootstrap.ps1` from it (needs Windows, internet for first-run Python/Chromium). |
| Installer package | `LotRadar-Installer-<date>-<sha>.zip`, produced by `scripts/build_installer.py`. |
| Program folder | `%LOCALAPPDATA%\Programs\MarketplaceScanner` (replaced on upgrade) |
| Data folder | `%LOCALAPPDATA%\MarketplaceScanner\data` (**never touched** by the installer) |
| Runtime folder | `%LOCALAPPDATA%\MarketplaceScanner\runtime` (Python venv, lock files; never touched) |
| Program backups | `%LOCALAPPDATA%\MarketplaceScanner\ProgramBackups` (never deleted automatically) |

## Versioning and provenance

There is no single canonical application release number in the source. `README - SCANNER.txt` says `R62`; the
Chrome extension manifest has its own version (`1.9.7`). They are separate and **not** the installer version.
A package is identified by `package_version` = `<commit date UTC>-<short commit>` plus the full `source_commit`
and `build_type` in `Install-Manifest.json`.

## Build requirements

* Python 3.9+ and Git (standard library only; works on Windows, macOS or Linux).
* The commit to package must be committed. Packages are built from **committed blobs at HEAD**, never from
  uncommitted working-tree files.

## Branding assets (committed, Owner-approved public files)

Photo export requires `business_card.png` and `dedication.jpg`. Branding uses `lotradar_logo.png` (transparent RGBA
PNG, shown unchanged in the sidebar and startup window) and `LotRadar.ico` (made from that PNG; used for the shortcuts
and the browser tab icon). The logo is never added to vehicle photos or exports.

Since 2026-11-19 these four files are **committed** at the paths the program reads, with the Project Owner's
explicit approval to publish them (including the business card's photo and contact details):

| Path in the repository and installed program | SHA-256 |
| --- | --- |
| `branding/business_card.png` | `be82e63c6035cf337cdc9a7bb038f670393324fa9e1f9aa3c710607bdfa701bd` |
| `branding/dedication.jpg` | `f1f86eef4f8d69d9f797e69767e8c1058afeb156d5af2d1ea369a538715db0e5` |
| `branding/lotradar_logo.png` | `b598d23ba243d30274d59ba78abc1571348b46eefbccd494a9dd3e0af2820e7d` |
| `LotRadar.ico` | `e97981648825570899b7a208fcd7aa82f2a66238fc791a87e18cf24b680d7629` |

So a **GitHub "Download ZIP" of `main` works as is**: export previews and the logo need no extra private folder and
no Git. Only these four exact paths are tracked; any other file in `branding/` stays git-ignored, and the builder
refuses to package an unknown tracked file. The builder also refuses a committed asset whose bytes differ from the
table above (`APPROVED_ASSET_SHA256` in `scripts/build_installer.py`); changing an asset needs a new Owner approval.

`--asset-dir` is now an optional **per-file override** for a single build (a file found there replaces the committed
copy; files not found there keep the committed copy). The override folder must be outside the repository or
git-ignored (e.g. `private-assets/`); the tracked `branding/` folder itself is refused. `--no-branding`
(development only) packages no branding at all, to test the text "LR" fallback; the Windows QA kit uses it.

## Build commands

```
# Release candidate: committed branding, clean working tree required
python scripts/build_installer.py build --mode production

# Same, overriding one or more branding files for this build only
python scripts/build_installer.py build --mode production --asset-dir C:\LotRadarPrivate\assets

# Development/test package (committed branding, named *-DEV.zip)
python scripts/build_installer.py build --mode development

# Development package WITHOUT branding (named *-DEV-NOBRANDING.zip; photo export reports
# "branding_assets_missing: business_card.png, dedication.jpg")
python scripts/build_installer.py build --mode development --no-branding

# Verify any package (re-hashes everything, scans for private data / secrets)
python scripts/build_installer.py verify dist\LotRadar-Installer-<...>.zip --require-production
```

The build fails (and writes nothing) on: a missing mandatory file, a tracked file that is neither packaged nor
explicitly excluded, a forbidden path (`data`, `runtime`, databases, keys, logs, `.exe`, ...), a secret-looking
string, a missing/invalid required asset (production), a committed asset that does not match its approved
SHA-256, or a dirty tree (production). The manifest records where each branding file came from
(`branding_asset_sources`: `committed` or `asset-dir`). Output is deterministic:
the same commit and assets give the same ZIP byte for byte. Share the ZIP's SHA-256 (printed by the build) when
handing it over. Publish it only as a release artifact, with the Project Owner's approval.

## Supported platforms

Two versions are described here. Do not mix them up.

**Approved `main` (`bf61207`, the current release):** Windows 10 is the verified platform ("Windows 10 verified;
Windows 11 untested"). Windows 11, installation/extraction from OneDrive folders, and the file-symlink refusal test
(R3) were waived by the Project Owner and are **not verified** for that release. Its link/reparse-point guard refuses
OneDrive folders, so extract that release to an ordinary local folder such as `C:\LotRadarInstall`.

**PR #5 candidate (not merged, not released; tested at `673fe9d`):** on 2026-11-17 the automated installer suite
passed on **Windows 11 Home build 26200**, PowerShell 5.1, standard user, with Developer Mode on so R3 could run
(48 PASS / 0 FAIL / 1 SKIP; the skip is the full-launch test F1, which has **not** passed). Extracting this candidate's
installer inside a **Personal OneDrive folder with Files On-Demand, files hydrated (available on this device)** also
passed (51 PASS / 0 FAIL / 1 SKIP): the installer accepts cloud-file placeholders **only** for the read-only package it
installs from, still refuses junctions and symlinks inside the package, and still refuses to install the program into
a cloud or linked folder. **Not tested for the candidate:** online-only (not downloaded) files, OneDrive for Business,
other cloud providers (Dropbox, Google Drive, iCloud), non-ASCII folder names, OneDrive sync conflicts during
install, and Windows 10. If the installer refuses a cloud folder, copy the extracted package to an ordinary local
folder and run it again.

## Install / upgrade (user, no admin rights)

1. Extract the ZIP to a normal folder (not inside the ZIP preview).
2. Close LotRadar completely. The installer refuses to run while port 8765 is active, another installer holds
   `runtime\lotradar-install.lock`, or LotRadar holds `runtime\marketplace-launch.lock` (starting/running). The
   installer takes both locks without waiting and keeps them until it finishes, so a launch started during an install
   fails safely ("already starting in another window") instead of racing it. Close it and launch again afterwards.
3. Double-click `Installer.cmd`. It verifies every file's SHA-256 **before** changing anything, stages the new
   program next to the old one, moves the old program to `ProgramBackups`, swaps the folders, and restores the old
   program if the swap fails. Shortcuts are created on the Desktop and Start menu.
   The installer refuses (nothing is changed) if the package payload, `Programs\MarketplaceScanner` or
   `ProgramBackups` is a junction, symlink or other reparse-point folder, or if any payload path resolves outside the
   package folder. In the PR #5 candidate this check also covers `Programs`, `%LOCALAPPDATA%\MarketplaceScanner` and
   its `runtime` folder, and runs before the runtime folder and lock files are created, so nothing is written through
   a link. (`%LOCALAPPDATA%` itself is not checked.) If the package sits in a OneDrive or other cloud/redirected folder and is refused, copy the extracted package to a
   normal local folder (for example `C:\LotRadarInstall`) and run it again.
   If anything fails after the swap, the previous program folder is restored (the failed copy is kept as
   `ProgramBackups\Failed-install-*`); on a first install with no previous program, the failed copy is moved there
   and no program is installed. Data is never touched.
4. Start LotRadar from the shortcut (in the PR #5 candidate a startup window shows the steps; see below). First run installs Python 3.10+ (via WinGet), the packages in
   `requirements.txt` and Playwright Chromium; offline it stops with a message and can simply be launched again
   after connecting.

## Startup window (PR #5 candidate, not in the approved `main` release)

Double-clicking the LotRadar shortcut shows a small LotRadar window listing the real startup steps: checking the
installation, Python and packages, the browser runtime, starting the local server, opening LotRadar. A step is marked
done only when the startup script reports it; a moving bar is shown because no step reports a measurable fraction (no
percentages or time estimates are shown). LotRadar is reported as open only after the script reports that it opened the
window AND the window's own check of `http://127.0.0.1:8765/api/health` succeeds.

- The window only displays progress. `Marketplace Bootstrap.ps1` still does all the work, in its own minimized
  "LotRadar Server" console window (taskbar), and stays the only owner of the launch lock, the server and the browser
  window. LotRadar keeps running after the startup window closes; closing the "LotRadar Server" window stops LotRadar.
- Closing the startup window while LotRadar is still starting does not stop anything: the console window is brought up
  and startup continues there.
- If startup fails, the window shows the reason, **Show details**, **Show console** (the full output of that attempt),
  **Retry** and **Close**. Retry/Close close the failed attempt's console only after its script has exited.
- A second double-click while LotRadar runs opens LotRadar again without starting a second server.
- Scripts and automation keep the original console start and exit codes: set `LOTRADAR_STARTUP_GUI=0` (or
  `LOTRADAR_NO_PAUSE=1`, used by the test harness). If the window cannot be shown (no desktop session, Windows Forms
  unavailable, or the per-user LotRadar or runtime folder is a link), the launcher falls back to the console start.
- Progress is passed through `%LOCALAPPDATA%\MarketplaceScanner\runtime\startup-status-<random>.jsonl` (step names and
  short messages only, with user/computer names and profile paths removed). The window deletes its file when it
  closes; files older than one day are removed at the next start.

## Stale staging folders

A crashed or killed install can leave `%LOCALAPPDATA%\Programs\.MarketplaceScanner-stage-<id>`. The installer does
**not** delete folders it did not create in the current run (they may belong to a concurrent or crashed run). They are
harmless and do not block installs. With LotRadar closed, they can be deleted by hand.

## Roll back manually

Close LotRadar, rename `%LOCALAPPDATA%\Programs\MarketplaceScanner` aside, and move the wanted folder from
`%LOCALAPPDATA%\MarketplaceScanner\ProgramBackups\Before-HomeTransfer-...` to
`%LOCALAPPDATA%\Programs\MarketplaceScanner`. Data is unaffected either way.

## Chrome Reader

`chrome://extensions` > Developer mode > Load unpacked > `%LOCALAPPDATA%\Programs\MarketplaceScanner\chrome-extension`.
Disable any older LotRadar/SalesmanHub scanner extension before pairing.

## Executable policy

The package contains no `LotRadar.exe`. The launcher runs the Python bootstrap directly. A compiled launcher, if ever
wanted, is a separate task with reproducible source.

## Tests

```
python -m unittest discover -s tests -v
```

These cover the builder, verifier and static launcher checks and run on any OS. They do **not** execute the
PowerShell installer or the launcher.

### Windows acceptance script

`tests/windows/Test-LotRadarInstaller.ps1` runs the installer and launcher for real, in a sandbox (LOCALAPPDATA and
APPDATA are redirected to a temp folder with spaces in its name; fixture data is synthetic). Run it in Windows
PowerShell 5.1 as a normal user:

```
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests\windows\Test-LotRadarInstaller.ps1 -PackageZip C:\path\LotRadar-Installer-<...>.zip
```

It covers: PowerShell parser check, manifest re-verification, clean install via `Installer.cmd`, upgrade with a
byte-for-byte data comparison, tampered/missing/adversarial manifests (traversal, UNC, reserved names, case
collisions, ADS, bad hashes), held installer lock, foreign listener on port 8765, locked program file, missing
`LOCALAPPDATA`, and the launcher (missing bootstrap, exit-code propagation, working directory, EXE absent/present,
pause behavior). `-FullLaunch` additionally starts the real bootstrap in the sandbox and checks `/api/health`
and the single-server guarantee. The only shared location is the real Desktop `LotRadar.lnk`, which is backed up
and restored. Hardening tests: R1-R5 (junction/symlink inside payload, payload root, install target, backup root; outside
sentinel folders must stay untouched; R3 reports SKIP if the account cannot create symlinks), C1/C2 (launch-lock
interlock, including a real bootstrap launched mid-install), P1/P2 (post-swap rollback with and without a prior
install, via a test-only injected *copy* of the installer; the shipped script is not edited) and S1 (stale stage
folder). With `-FullLaunch`: OFF1 (offline first run fails clearly, data untouched) followed by F0 (retry proceeds)
and F4 (provisioned + outage still starts). Interactive checks are listed in `docs/MANUAL_ACCEPTANCE.md`.

### Launcher pause

On a non-zero exit the launcher pauses so the message can be read after a double-click. Scripts and CI set
`LOTRADAR_NO_PAUSE=1` to disable the pause.
