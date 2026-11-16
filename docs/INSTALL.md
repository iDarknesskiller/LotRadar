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

## Private branding assets

Photo export requires `business_card.png` and `dedication.jpg` (and the shortcut icon `LotRadar.ico`, optional).
Keep them in a folder **outside** this repository (or under the git-ignored `branding/`), e.g.
`C:\LotRadarPrivate\assets\`. The builder checks type headers and size and refuses an in-repo, non-ignored folder.

## Build commands

```
# Release candidate: requires both branding images and a clean working tree
python scripts/build_installer.py build --mode production --asset-dir C:\LotRadarPrivate\assets

# Development/test package without private images (named *-DEV-NOBRANDING.zip; photo export will report
# "branding_assets_missing")
python scripts/build_installer.py build --mode development

# Verify any package (re-hashes everything, scans for private data / secrets)
python scripts/build_installer.py verify dist\LotRadar-Installer-<...>.zip --require-production
```

The build fails (and writes nothing) on: a missing mandatory file, a tracked file that is neither packaged nor
explicitly excluded, a forbidden path (`data`, `runtime`, databases, keys, logs, `.exe`, ...), a secret-looking
string, a missing/invalid required asset (production), or a dirty tree (production). Output is deterministic:
the same commit and assets give the same ZIP byte for byte. Share the ZIP's SHA-256 (printed by the build) when
handing it over. Publish it only as a release artifact, with the Project Owner's approval.

## Install / upgrade (user, no admin rights)

1. Extract the ZIP to a normal folder (not inside the ZIP preview).
2. Close LotRadar completely. The installer refuses to run while port 8765 is active or another installer holds
   `runtime\lotradar-install.lock`.
3. Double-click `Installer.cmd`. It verifies every file's SHA-256 **before** changing anything, stages the new
   program next to the old one, moves the old program to `ProgramBackups`, swaps the folders, and restores the old
   program if the swap fails. Shortcuts are created on the Desktop and Start menu.
4. Start LotRadar from the shortcut. First run installs Python 3.10+ (via WinGet), the packages in
   `requirements.txt` and Playwright Chromium; offline it stops with a message and can simply be launched again
   after connecting.

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
and restored. Interactive checks (Explorer double-click, offline first run, Chrome Reader pairing) are manual.

### Launcher pause

On a non-zero exit the launcher pauses so the message can be read after a double-click. Scripts and CI set
`LOTRADAR_NO_PAUSE=1` to disable the pause.
