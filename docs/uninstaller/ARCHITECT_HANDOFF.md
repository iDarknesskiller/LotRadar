# ARCHITECT_HANDOFF.md — Safe Windows Uninstaller

**To:** Claude — Lead Programmer  
**From:** ChatGPT — Chief Architect  
**Owner:** Project Owner, final merge/release authority  
**Repository:** https://github.com/iDarknesskiller/LotRadar  
**Feature branch:** feat/safe-windows-uninstaller  
**Approved main (inspected Nov 17, 2026):** bf61207a21999c8ff256b08c0d17650193e3835f  
**Version:** Source has no canonical app version. Scanner README R62 and Chrome Reader 1.9.7 are separate. Installer manifest package_version and source_commit identify builds.  
**Status:** Planning only; no uninstaller currently exists. Keep draft PR separate from PR #5.

## Request

Build a safe, user-friendly **per-user Windows uninstaller**, accessible through **Settings > Apps > Installed apps** and optionally from the Start menu. It must remove LotRadar application code and only verified LotRadar shortcuts/registration, while preserving **all user data by default**. No administrator account, Python, Git or internet required for removal.

The Project Owner is validating Windows 11, R3 symlinks and OneDrive on PR #5; this uninstaller is a **separate feature**. GitHub issue #6 is the Copilot read-only performance audit, **not** an uninstaller PR.

**Policy:** First version is **“Uninstall app, keep my data” only**. Do not add an irreversible data purge or a “delete everything” toggle in this release. A separate user-authorized future task may address intentional data deletion with its own backups, confirmation, and audit.

## Current behavior (verified from approved main)

- installer/Install-LotRadar.ps1 installs the *program* into %LOCALAPPDATA%\Programs\MarketplaceScanner as a normal user. It checks manifest SHA-256, rejects link/reparse directory traversal, stages files, backs up the old program, atomically swaps the program directory, and rolls back on errors.
- The installer takes %LOCALAPPDATA%\MarketplaceScanner\runtime\lotradar-install.lock and then marketplace-launch.lock, probes port 127.0.0.1:8765, and refuses concurrent install/launch activity. It writes LotRadar.lnk on Desktop and in the user's Start-menu Programs directory.
- Marketplace Bootstrap.ps1 launches server.py on 127.0.0.1:8765 while holding the launch lock. It may provision Python/Chromium. The active PR #5 will change the startup UI, so do not make assumptions about its future lifecycle.
- %LOCALAPPDATA%\MarketplaceScanner\data holds marketplace.sqlite3, vehicle_photos, facebook_photos, photo_selection.json, and Facebook drafts. %LOCALAPPDATA%\MarketplaceScanner\runtime holds a local Python environment and lock files. %LOCALAPPDATA%\MarketplaceScanner\ProgramBackups holds prior program installs. **All these locations MUST be preserved**.
- installer/Installer.cmd invokes the PowerShell installer. scripts/build_installer.py uses explicit allowlists; installer/* is package-root material, not automatically included in the installed payload. docs/INSTALL.md documents installation/rollback, not uninstall.
- The current program install does not contain an authoritative persistent install receipt with complete managed file ownership. Claude must design this; the package-root Install-Manifest.json cannot be assumed to remain in the installed program.
- Public GitHub repo: never commit customer data, original photos, SQLite files, pairing keys, local profiles, logs or private branding assets.

## Required behavior

1. Register a Windows Installed Apps entry for the current Windows user under HKCU/Software/Microsoft/Windows/CurrentVersion/Uninstall/LotRadar (stable app key, no HKLM). DisplayName LotRadar; correct publisher, install location, icon and source-derived version, with a valid UninstallString that invokes a **bundled, standalone PowerShell 5.1** uninstaller.
2. User must see confirmation before anything is removed: **“Remove the LotRadar application? Your saved vehicle photos, inventory database, Facebook drafts, settings, and backups will be kept.”** Cancel changes nothing. Test-only unattended mode needs an explicit affirmative flag.
3. Refuse uninstall when LotRadar is running/starting, another installer/uninstaller owns the lock, or port 8765 is occupied. Acquire locks in **install lock then launch lock** order, as the installer does. Do not forcibly kill python.exe, Chrome, Edge, an unrelated port listener, or the startup-window process.
4. Determine exact managed program directory from trusted app identity and expected user-level path. Create a persistent, tamper-resistant-in-scope **receipt/installation identity** in the installer workflow recording product ID, installed source_commit/package_version, canonical program path, owned files and owned shortcuts. The receipt is not permission to delete arbitrary paths: enforce an immutable exact expected target and prohibit path escape, junctions, symlinks and reparse traversal. Define how a failed install/upgrade rolls back receipt/registry changes.
5. **Legacy installations without a receipt:** either a narrowly bounded, independently verified detection path or **fail closed** with explicit “upgrade to a supported installer first” instructions. Never guess ownership or use unrestricted recursive removal.
6. Delete only verified app-owned files within the program folder; remove it only if empty and safe. **Preserve unknown/custom files**, warn of incomplete removal and offer safe next steps. Verify a shortcut's real target points to this specific LotRadar install before removing. A different user's shortcut, a renamed shortcut targeting a different app, or OneDrive-redirected unrelated Desktop files must never be deleted.
7. Preserve the installed user's *data*, *runtime*, and *ProgramBackups* byte-identical by default. Do NOT uninstall globally installed Python/WinGet Python, Playwright/Chromium caches used by others, browser extensions/profiles, Windows app dependencies, or SalesmanHub data. Tell user how to remove the **unpacked Chrome Reader** manually from chrome://extensions afterward.
8. Uninstall through Windows Settings must still work if the original installation ZIP has been deleted or the Python runtime fails. An uninstaller stored inside the program directory cannot assume it can delete itself while in use: use a safe out-of-program temporary runner or equivalent, with proper exit code and cleanup; no extra dependencies.
9. Make interrupted runs, held file handles, permission failures and repeated invocation safe: use a reversible transition where practical, report partial cleanup accurately, leave data untouched, avoid arbitrary delete fallback, and permit retry without corrupting a preserved installation. Delete app-owned registry registration **only when the app itself was successfully removed**; define cleanup behavior if only a shortcut/registration remains.
10. Support Windows 10/11 normal non-admin usage, paths with spaces/Unicode, Windows Defender file locks and OneDrive Known Folder Move Desktop. Do not alter OneDrive settings or sync files, or migrate data.

## Relevant architecture and allowed files

**Likely changes (finalize exact ownership contract before coding):**
- installer/Install-LotRadar.ps1: install receipt and HKCU registry registration integrated with existing rollback and locks.
- installer/Installer.cmd and installer/README - INSTALL.txt: install/uninstall documentation, invocation behavior.
- NEW installer/Uninstall-LotRadar.ps1, optionally installer/Uninstall.cmd; place an installed copy where the registered UninstallString is valid and can execute without the original ZIP.
- scripts/build_installer.py: explicitly package new files and provenance, maintain deterministic ZIP and private-asset checks.
- tests/windows/Test-LotRadarInstaller.ps1: synthetic install/uninstall test matrix. **Isolate HKCU registry writes to disposable fixture keys or a disposable Windows user/VM with restoration**, not real production Installed Apps.
- tests/test_installer_build.py, new tests if needed, docs/INSTALL.md, docs/MANUAL_ACCEPTANCE.md and docs/uninstaller/ as required.

**Do not modify for this feature:** server.py, core.py, app.js, photo_cache.py, photo_selection.py, photo_classify.py, Facebook automation, chrome_bridge.py, chrome-extension/*, SQLite schema, photo bytes, original logo, private assets, SalesmanHub, or active PR #5 files. If PR #5 introduces conflicting bootstrap/installer changes, report an integration plan to Architect before reconciling.

## Implementation plan (ordered)

1. Verify latest approved main SHA; compare PR #5 state; record behavior, path ownership, startup and installer lock ordering. Continue this dedicated branch, not PR #5.
2. Design and document install receipt structure, stable per-user app registration, safe ownership proof for legacy installs, and what is **not** owned. Treat receipt as untrusted input and validate exact paths independently.
3. Implement standalone PowerShell 5.1 uninstaller: user confirmation, explicit noninteractive test mode, lock/port refusals, exact app ownership validation, link/reparse and TOCTOU defenses, safe unknown-file handling, owned shortcut checks, rollback/retry/status summary.
4. Implement installed uninstaller location and Windows Installed Apps registration. Make it work without original package or Python. Add correct installer-side rollback when registration/receipt creation fails and when upgrading an existing install.
5. Include uninstaller files in build allowlists and deterministic package, maintain production branding and package source_commit identity; avoid private data in the public repo.
6. Add Windows 10/11 synthetic end-to-end install→uninstall→reinstall acceptance tests and fault injection. Preserve data SHA-256, runtime and ProgramBackups. Avoid any destructive testing on the actual Owner profile.
7. Confirm app launch after reinstall, legacy receipt behavior, Chrome Reader manual removal notice, OneDrive-synced Desktop shortcut safety, restart/repeat uninstall behavior.
8. Deliver CLAUDE_UNINSTALLER_HANDOFF.md with exact changed paths, commits, tests executed and exit codes, SHA and before/after data hashes, rollback proof, blocked cases and Gemini independent audit request.

## Protected functionality

- Vehicle photo originals and exported images, VIN mapping, 20-photo ordered selections, custom cover/dedication exports, draft metadata, SQLite WAL integrity.
- Chrome Reader pairing, used-only inventory, scanner queues, accurate dealer information, Facebook draft state, trade-in priority.
- Installer manifest SHA checks, R1–R5 (especially R3 file symlink) containment, safe program backup/rollback and installed shortcuts.
- Windows 11 and OneDrive compatibility checks and native startup work in PR #5; server lifetime and port 8765 single-server behavior.
- Private 190px radar logo, secrets, API tokens, global Python and browser installations.

## Acceptance criteria (all applicable)

| ID | Requirement |
|---|---|
| U01 | Windows 10 and Windows 11 standard users can invoke Installed Apps uninstall without elevation, network, Git or Python. |
| U02 | Cancel leaves **program, data, runtime, backups, shortcuts and registry** unchanged. |
| U03 | Confirm removes only verified program/owned shortcuts/owned HKCU registry entry and retains data, runtime and backups **byte-identical**. |
| U04 | Active server, active installer, active launcher or foreign port-8765 listener prevents uninstall with nonzero status and no changes. |
| U05 | Symlink/junction/reparse points, malicious receipt, wrong paths and outside sentinel targets are refused without following/deleting through links. |
| U06 | A same-named shortcut targeting an unrelated program is preserved, including a OneDrive KFM Desktop. |
| U07 | Locked file/permission denial/forced failure reports accurate nonzero status; defined rollback or safe retry succeeds without data loss. |
| U08 | Reinstall recovers unchanged synthetic database, photos, draft status and photo selection after uninstall. |
| U09 | Installer upgrade correctly updates receipt/registration and rolls back if failure; no duplicate or orphaned Installed Apps entry. |
| U10 | Deterministic verified installer ZIP includes uninstaller; manifest matches feature HEAD; private data/assets never committed. |
| U11 | Unknown files beneath program folder are not deleted, and incomplete removal is explicitly reported. |
| U12 | No regression in Windows 11 R3 suite, installer rollback or PR #5 startup behavior after future integration. |

## Required tests (actually execute, not just propose)

- python -m unittest discover -s tests -v; python scripts/build_installer.py build --mode development; python scripts/build_installer.py verify <DEV ZIP>; repeat to compare SHA-256.
- PowerShell 5.1 parser all installed scripts; normal-user Windows 10/11 sandboxed install/uninstall roundtrips; real Settings uninstaller flow inside a **disposable Windows profile/VM or explicitly owner-approved isolated test installation**.
- Synthetic SHA-256 snapshots before/after app data, saved photos, drafts, photo selections, managed Python runtime and program backups; compare byte-identical after uninstall/reinstall.
- Cancel, missing uninstaller script, corrupted/stale/missing receipt, altered registry UninstallString, unrelated shortcut collision, Desktop KFM, path with spaces/Unicode, drive/reparse spoofing, target folder injected unknown file, sentinel folder escape attempts.
- Held installer lock, held launcher lock, running real sandbox server, foreign listener 8765, simultaneous uninstall launches, Windows file lock, intentional failure mid-uninstall, cleanup after retry.
- Existing installer hardening R1–R5/R3, L1–L6, C1–C2, P1–P2, Windows 11 baseline and F1 FullLaunch when appropriate; record each PASS/FAIL/SKIP/BLOCKED separately.
- Gemini must independently audit real test logs/source diffs and data-integrity evidence; unsupported platforms are BLOCKED, never fictional PASS.

## Risk areas

Catastrophic accidental photo/database deletion; fake install receipt pointing outside intended program; OneDrive KFM shortcuts; link/reparse traversal and TOCTOU; mistaken cleanup of global Python; lock-order deadlocks; active server deleted mid-execution; stale per-user registry entries; self-removal file handles; partial filesystem failures; data migration collision on reinstall; accidental modification of PR #5 or Copilot performance work.

## Git instructions and handoff destination

Claude alone implements this feature on **feat/safe-windows-uninstaller** and updates its separate **draft PR**. Do not write to approved main. Do not merge or publish a production release without **explicit Project Owner authorization** after Gemini and Chief Architect review. PR #5 remains reserved for startup GUI/OneDrive testing. GitHub issue #6 remains Copilot read-only performance investigation. Claude returns CLAUDE_UNINSTALLER_HANDOFF.md to ChatGPT Chief Architect and Gemini.
