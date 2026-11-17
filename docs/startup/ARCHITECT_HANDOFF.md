# ARCHITECT_HANDOFF.md

**To:** Claude — Lead Programmer  
**From:** ChatGPT — LotRadar Chief Architect  
**Task:** Windows startup status window, separate from logo PR #4/photo-gallery PR #3  
**Repository:** https://github.com/iDarknesskiller/LotRadar  
**Latest approved `main` (reverified 2026-11-17):** `bf61207a21999c8ff256b08c0d17650193e3835f` (PR #3 and PR #4 merged; PR #5 must integrate this baseline)  
**Branch:** `feat/windows-startup-status-window`  
**PR:** new draft PR, no merge authorized

## Request
The Project Owner wants a custom LotRadar-branded Windows window when launching the app, showing *real* progress while the server checks its environment, resolves dependencies, starts and opens LotRadar. They suggested optionally running the server inside the window. Architect selects a **transient native startup/status window** for this cycle; persistent WebView2/Tauri container is a separate future feature and NOT authorized by this handoff. The app must continue running even after the startup/status window closes on success.

## Current behavior and root cause
- `Launch Marketplace Scanner.cmd` validates that `Marketplace Bootstrap.ps1` and PowerShell exist, then runs the bootstrap in an ordinary console and pauses on errors (unless `LOTRADAR_NO_PAUSE=1`).
- `Marketplace Bootstrap.ps1` finds Python 3.10+, may use WinGet to install Python, creates a private venv, installs Python requirements and Playwright Chromium, performs guarded one-time migration, launches `server.py --no-browser` on `127.0.0.1:8765`, probes `/api/health`, then opens Chrome/Edge app-mode or the default browser.
- It holds the exclusive `runtime/marketplace-launch.lock` until the server terminates. This lifetime prevents installation-over-launch races. Repeated launcher clicks reuse the existing healthy server.
- The current `Start-Process -NoNewWindow -PassThru` + `WaitForExit()` ties the background server and bootstrap to the original console lifetime. A simple `Start-Process -WindowStyle Hidden` followed by closing the console is **not** a safe implementation without designing process lifetime and output ownership.
- Installer `installer/Install-LotRadar.ps1` refuses concurrent execution by claiming installer and launch locks, and checks port 8765. Existing Windows harness tests L1–L6, C1–C2, F0–F4 protect these behaviors.

## Required behavior
1. Normal user **Explorer double-click of the LotRadar shortcut** presents one compact, accessible, native-looking LotRadar startup window with optional **private radar logo** only when packaged; safely fall back to a text mark in DEV/no-logo packages. Keep private image binaries outside public Git.
2. Display actual lifecycle stages: **Checking installation**, **Checking Python/dependencies**, **Checking browser runtime**, **Starting local server**, **Opening LotRadar**. Indicate checked, active or error states based on real bootstrap events. If a stage has no measurable fraction, show an indeterminate bar; **never invent progress percentages, ETA, or success**.
3. When a healthy local LotRadar server is confirmed, open the existing Chrome/Edge app-mode window **exactly once** and close/hide the startup window without terminating the server, losing the exclusive lock, or suspending existing background work.
4. On second shortcut click, detect the healthy server and open the UI without starting another Python process or getting stuck behind the launch lock. If installation holds the lock or port 8765 is occupied by an unrelated process, show accurate user-facing messages and refuse unsafe work.
5. Failed Python/pip/Chromium/offline first-run attempt must display an actionable failure in the native UI with **Show details** (sanitized output) and **Retry** or **Close**. No silent disappearance, no infinite spinner, no duplicate install attempts; user data remains untouched. Full detail logs must not contain tokens, browser pairing keys, dealer/customer data, or credentials.
6. Existing scripted/automation/CI execution must retain the original console bootstrap path and exit codes, e.g. via **documented explicit opt-out** `LOTRADAR_STARTUP_GUI=0` and legacy `LOTRADAR_NO_PAUSE=1` behavior. GUI unavailable/noninteractive/unsupported PowerShell should fail over safely to the old console path.
7. Progress window must remain responsive during potentially long dependency downloads. UI close during setup must not create an orphan/stranded lock, kill an already-healthy server unexpectedly, or corrupt partially downloaded runtime. Define explicit close behavior and test it.
8. No public remote service, external telemetry, authentication bypass, automatic inventory scan or Facebook post may be introduced by this feature.

## Recommended architecture
- Prefer **Windows PowerShell 5.1 Windows Forms** (built into supported Windows) for a lightweight startup UI; no new Python, Node, Tauri, WebView2 or elevated installer requirement.
- The existing bootstrap remains the **single authority** for prerequisites, interlocks, migration and server startup. Do not duplicate these operations in the UI controller.
- Add a narrow, optional, sanitized machine-readable stage signaling contract from the bootstrap to the UI (e.g. launch-scoped atomic JSON/status file under `%LOCALAPPDATA%/MarketplaceScanner/runtime` with a fresh per-attempt ID and controlled schema). The bootstrap also retains useful console status for scripts. Do not parse arbitrary untrusted text as control flow and do not print secrets.
- The native UI controller can supervise a bootstrap child process while displaying stage updates and failure summaries, but **must not make the server's lifetime depend on the splash window**. Preserve the bootstrap/server ownership and launch-lock lifetime, including when the startup window closes. Design and test explicit process/handle/redirected-output behavior on real Windows before committing to one approach.
- Avoid GUI/PowerShell UI-thread blocking: poll status asynchronously or use a background worker; marshal updates to the UI thread.
- Preserve `Open-LotRadarWindow` exactly-once semantics: establish which component owns browser launch; do not let both the GUI and the bootstrap open it.
- Stage-file writes, if chosen, must be atomic, launched inside the user-owned runtime directory, and either cleaned up safely after the run or bounded so they cannot accumulate indefinitely. Validate the per-launch nonce; do not allow another process to forge a ready state based solely on a file. Actual `/api/health` must confirm readiness.

## Relevant architecture / files
**Expected to modify:**
- `Launch Marketplace Scanner.cmd`: interactive GUI default and documented noninteractive fallback, exact exit propagation.
- `Marketplace Bootstrap.ps1`: optional structured stage reporting, process/lock/health reporting without altering underlying operations.
- `scripts/` or a new `startup/` PowerShell helper (e.g. `startup/Show-LotRadarStartup.ps1`): native status UI; no duplicate server logic.
- `scripts/build_installer.py`: package allowlist for any new GUI helper (must be included in production ZIP deterministically).
- `docs/INSTALL.md` and `docs/MANUAL_ACCEPTANCE.md`: startup behavior, error recovery and test instructions.
- `tests/windows/Test-LotRadarInstaller.ps1`: scripted/noninteractive bypass, GUI smoke test and process/lock protections.

**Do NOT modify:** `core.py`, `server.py`, `photo_cache.py`, `photo_selection.py`, `photo_classify.py`, `chrome_bridge.py`, `facebook_auto.py`, `chrome-extension/*`, SQLite schema, database/photo/draft files, installer rollback algorithms, branding PNG/ICO assets or logo-size work on PR #4. 

## Ordered implementation plan
1. Confirm reviewed `main` SHA and work exclusively on the new feature branch. Build a process-lifecycle diagram for normal launch, already-running, dependency first-run, failure, installer-active and user-close paths; document exact parent/child ownership before editing code.
2. Implement a small optional bootstrap event/status contract with stage ID, message, event time, state (`started`, `complete`, `failed`) and attempt identifier. Sanitize messages and never serialize secrets or machine-private paths needlessly. Keep bootstrapping operations intact.
3. Add the responsive native startup UI controller with honest status, an indeterminate progress indicator, error details and non-blocking loop. Show the branding fallback when no private logo exists.
4. Add the interactive launcher path and explicit noninteractive opt-out. Preserve console commands, existing legacy exit codes and no-extra-process single-instance behavior.
5. Update deterministic packaging and docs; ensure new script is packaged, all signed-off binary private assets remain external, and untracked/missing GUI helper is detected by the builder.
6. Run existing Python and Windows installer tests; expand with lifecycle and abort/retry cases. First-run offline behavior must still recover without deleting data. Test actual Windows Explorer double-click, not only `cmd /c`.
7. Give Gemini independent review with code diff, executed test logs, and sanitized screenshots. Do not merge.

## Protected functionality
- `%LOCALAPPDATA%/MarketplaceScanner/data`: SQLite, original photos, selection files, Facebook drafts, audit events; never modified by startup UI.
- `%LOCALAPPDATA%/MarketplaceScanner/runtime`: private venv and launch/install locks, preserved across restarts; no early release or deadlock.
- ProgramBackups and installer rollback; install/launch mutual exclusion.
- Chrome Reader pairing, API security/local-only health identity, used-only inventory, manual Facebook approval, scanner behavior.
- Production logo and business-card/dedication assets remain private, unmodified, not included in public Git.

## Acceptance criteria (all must pass)
- On Windows 10 normal standard-user Explorer launch, one visible LotRadar startup window appears and shows every actual stage without fictitious progress values.
- Healthy server opens exactly one browser app-mode window, startup UI exits cleanly, and there remains exactly one listening server on 127.0.0.1:8765 with the launch lock held for the server's lifetime.
- A second click opens an additional UI window for the *same* server and never starts a duplicate server.
- Offline dependency failure and missing Python/Chromium show clear actionable errors; retry after restoring internet or repairing a dependency succeeds without touching existing data.
- Lock held by installer or foreign port listener is refused, with no unintended server or UI launch.
- Closing/canceling the startup window during setup has explicitly tested, documented behavior that does not leave stale exclusive locks or terminate an already-running healthy server.
- In opt-out (`LOTRADAR_STARTUP_GUI=0`) and test mode (`LOTRADAR_NO_PAUSE=1`), existing console launch/test harness exit codes and messages remain valid; no unrequested UI appears.
- No modified/deleted original photo files, database rows or Facebook draft records as a result of using startup UI; system functions normally when the GUI controller is absent/unavailable.
- Production build verifies required file inventory and deterministic archives; no private assets, logs, status files or tokens are in Git.

## Required tests (execute, record OS/build/exit status)
- `python -m unittest discover -s tests -v` and package build/verify repeatability.
- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/windows/Test-LotRadarInstaller.ps1 -PackageZip <DEV ZIP> -FullLaunch` on Windows 10 standard user (sandboxed as designed), including existing L, C, F and installer rollback tests.
- Real Windows Explorer double-click of production shortcut: fast existing-runtime path, first-run dependency setup, offline failure, retry and second launch. Confirm UI responsiveness, correct error descriptions and exactly one listener on port 8765.
- Explicit GUI opt-out scripted launch, environment with PowerShell WinForms unavailable, lock contention and unexpected server termination.
- Snapshot original data hashes before and after UI-only startup, including a previously healthy installation; test with paths containing spaces.
- Keyboard navigation, high-DPI scaling and closing/minimizing window during setup; no UI deadlock. Repeat these startup-window GUI and lifecycle checks on **Windows 11** under the expanded Owner-approved test scope; report Windows version/build and do not mark Windows 11 as verified until actual execution succeeds.

## Risks
GUI/main-thread deadlocks; `Start-Process -NoNewWindow` and redirected stream lifetime; early bootstrap exit releasing launch lock; zombie child server; duplicated Chrome windows; race between health, event files, and actual server readiness; failed download retries; orphaned status/log files; WinForms availability and execution policy; auth/path/log leakage; first-run long stalls; missing installer file allowlist; launch while installer swaps program directories.

## Git instructions
Continue `feat/windows-startup-status-window`, first integrating the latest approved `main` `bf61207a21999c8ff256b08c0d17650193e3835f` (PR #4 branding and PR #3 photo gallery are already merged). Record both the pre-integration HEAD and new implementation HEAD. Keep PR #5 draft. **Do not merge to `main` and do not release without explicit Project Owner authorization after Gemini and Chief Architect review.**

## Owner-requested expanded QA: Windows 11 and R3 file symlink (2026-11-17)

### Request and baseline
The Project Owner can now test on a home Windows PC and has authorized **adding Windows 11 and R3 symlink-refusal testing** to PR #5's acceptance program. This changes **test scope only**, not the planned startup UI architecture. Do **not** infer Windows 11 is installed; verify it with the test harness and record the reported OS name/build. Previous waivers for Windows 11 and R3 are **not automatically removed** by requesting tests. OneDrive-redirected extraction remains a separate waiver until actually tested.

At the time of this instruction, PR #5 HEAD `db1c82b6959a7f7f1baf79060bc264d784c7d545` contained **only this architecture document**, not production startup-window code. The approved `main` is `bf61207a21999c8ff256b08c0d17650193e3835f`. Perform R3 and baseline installer testing first, then retest the actual GUI implementation once Claude has built it. A test on an old installer package is not proof of the newer PR #5 build.

### Relevant source and protected functionality
- `tests/windows/Test-LotRadarInstaller.ps1` implements PowerShell 5.1 normal-user, synthetic-data, redirected `LOCALAPPDATA` and `APPDATA` installer tests. Its **R3** block (lines 513–525 in approved main) substitutes a symlinked `requirements.txt` in a *disposable package copy* and expects the installer to refuse. The harness emits **SKIP**, not PASS, if `mklink` cannot create a file symlink (Windows Developer Mode or permissions may be required).
- `installer/Install-LotRadar.ps1` rejects symlink/reparse-point payload folders/files through `Test-UnsafeLink`; never weaken this validation, follow symlinks into external folders, or edit/delete the actual installed program/data to create a test fixture.
- Preserve `%LOCALAPPDATA%\\MarketplaceScanner\\data` (original dealer photos, photo selection, inventory, drafts), the 190px radar branding, photo-gallery export order, local-only server and launch/installer locks. The test harness may temporarily replace the **real Desktop LotRadar.lnk** but backs up/restores an existing shortcut. Check its restoration afterward.

### Ordered implementation and testing instructions to Claude
1. **Preflight the machine and files:** record `(Get-CimInstance Win32_OperatingSystem).Caption` and `BuildNumber`; verify `$PSVersionTable.PSVersion` is 5.1, session is non-elevated, test ZIP manifest `source_commit` matches the intended baseline/PR head, and package SHA-256. Make a verified backup of any existing Desktop `LotRadar.lnk`. Close LotRadar completely and ensure nothing is listening on `127.0.0.1:8765` before the test.
2. **Now, baseline Windows 11 + R3:** use an actual installer ZIP whose manifest identifies approved `main` `bf61207...` (or clearly document any older baseline). From the repo root in a normal Windows PowerShell 5.1 session run:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\tests\\windows\\Test-LotRadarInstaller.ps1 -PackageZip "C:\\Private\\LotRadar-Test\\LotRadar-Installer-<version>.zip"
   ```

   Read the emitted `LotRadar-WindowsTest-*.json` and `.log` **beside the ZIP**. Confirm `T00` identifies Windows 11 and `R3` reports **PASS** with an installer refusal, external target/sentinel intact, no data mutation, and `FAIL=0`. `R3 SKIP` does not satisfy the R3 acceptance gate. If symlinks are disallowed, enable Windows **Developer Mode only if permitted and desired**, rerun as a **normal user**, and preserve the SKIP/blocked status if Windows policy still forbids it; do not escalate to administrator to manufacture a pass.
3. After the baseline passes, optionally rerun with `-FullLaunch` for the real sandbox bootstrap. This can install Python/Chromium packages and open an app window. Capture health response and single-listener evidence; ensure installer/launcher interlock and Desktop shortcut restoration. Do not run while the real server is in use.
4. **After PR #5 implementation:** integrate approved `main`, build a deterministic **private** test package from the feature HEAD, confirm manifest commit, and rerun the entire Windows 11 harness with `-FullLaunch` plus R3. Manual Explorer double-click checks must verify the custom startup UI, real progress phases, offline dependency error and recovery, noninteractive opt-out, busy installer/foreign listener, launch twice without duplicate server, GUI close during setup, focus/keyboard/high-DPI (100%, 125%, 150%) and no orphaned locks/processes. Verify Windows 10 remains supported through its own evidence; Windows 11 results do not replace the Windows 10 gate.
5. **Data-integrity proof:** where appropriate, use `tests/windows/Get-LotRadarEvidence.ps1` to snapshot/check original photo SHA-256 before/after the *actual* startup/installation test without overwriting source photos. Also confirm inventory/drafts survive and no private asset appears in public Git or logs. Do not use the live data directory for the adversarial R3 fixture.
6. Deliver `CLAUDE_WINDOWS11_R3_HANDOFF.md` with exact tested source/installer SHA, Windows build, PowerShell version, non-admin status, command transcript, JSON result summary (especially R3), normal and failure modes, redacted screenshots, ZIP SHA-256 and safety notes. Request Gemini independently audit the same feature SHA and real evidence before asking the Architect to lift the relevant test waivers.

### Acceptance criteria and risk areas
- Windows 11: real test environment confirmed, **zero installer/launcher failures**, stage-window and lifecycle checks pass on the implemented PR #5 candidate, shortcut restored, one healthy local server, zero orphaned server or installer lock.
- R3: **PASS** only when the symlink was actually created *inside sandbox*, installer rejected it, external sentinel unchanged and the production data/installed program untouched. `SKIP` remains an explicitly unverified security test; never relabel as PASS.
- Do not confuse a baseline installer test on approved main with post-implementation PR #5 GUI acceptance. Any package whose manifest does not match tested HEAD must be identified as a different build.
- Risks: Windows 11 PowerShell/Developer Mode differences, symlink privilege restrictions, reparse-point traversal, shortcut restoration, port conflict, first-run downloads, sandbox cleanup, GUI focus/high-DPI, launcher lock lifetime and inadvertent live-data modification. Treat private data and branding as protected.
- Do not alter unrelated source or merge PR #5 into `main`. Owner authority remains required.


## Addendum: Owner has no installer or development environment at home (2026-11-17)

### Request
The Project Owner says **nothing is installed on the home Windows PC** and wants Claude to deliver everything necessary for Windows 11 and R3 testing. The Owner must **not** be asked to clone the repository, manually build a ZIP, install Python/Node/Git/Chrome, copy PowerShell scripts, enable symlinks, or guess file paths. This supersedes the previous instruction that assumed an installer ZIP and a checked-out repo were already present. Windows 11 is **not yet verified** until the generated test report confirms the OS/build.

### Current behavior and gap
- PR #5 remains **documentation-only** at baseline commit `4a15f9a238e6282f1b6ffe15d4df3e75df109f1e`. It does not yet contain a built custom Windows startup UI.
- Approved `main`: `bf61207a21999c8ff256b08c0d17650193e3835f`.
- `scripts/build_installer.py build --mode development` can produce an installer ZIP without private branding, marking it DEV / DEV-NOBRANDING; **this can validate installer security but is not a production branding or startup-window acceptance build**.
- `tests/windows/Test-LotRadarInstaller.ps1` expects a valid `-PackageZip`, uses Windows PowerShell 5.1, and protects the real profile with redirected temporary `LOCALAPPDATA` and `APPDATA`. It also temporarily manipulates the **real Desktop LotRadar.lnk** and restores it at finish.
- R3 creates a temporary file symlink and tests that installation rejects it. On machines where Windows policy blocks `mklink`, R3 reports **SKIP**; **SKIP cannot be called PASS**. Current R3 only checks a nonzero installer result; improve test assertion to require an explicit `link` or `reparse` refusal reason so a coincidental checksum failure is not mistaken for a security PASS.
- `-FullLaunch` provisions Python/Chromium under temporary test paths; this is not a requirement that the Owner first install them. It needs internet on first run, and any temporary downloads/runtime must be disclosed to the Owner.

### Implementation plan — Claude owns preparation end to end
1. Verify the active branch, approved main and current tree, and **integrate approved `main` before building or changing startup code**. Do not merge PR #5 into main.
2. Prepare a **private, owner-facing Windows 11 QA test kit** from an exact known commit. Suggested delivery: a ZIP named `LotRadar-Win11-R3-QA-<shortsha>.zip` containing:
   - a tested **development** LotRadar installer ZIP and manifest, with `build_type=development`, `source_commit` and SHA-256 clearly labeled; no claims that missing private assets constitute a final production release;
   - a tested copy of `tests/windows/Test-LotRadarInstaller.ps1` and any explicitly required test-only helpers;
   - one easy `RUN_WINDOWS11_TESTS.cmd` launcher (or an equivalently simple bundled launcher) that uses built-in `powershell.exe`, resolves package paths **relative to its own folder**, runs the harness, preserves exit codes, and clearly reports where logs are saved;
   - a plain-language `START_HERE.txt` explaining actions, temporary Desktop shortcut handling, internet needs, Developer Mode requirement for R3 if applicable, expected result, and how to send **only** sanitized log/JSON evidence.
   - checksum manifest for the kit and embedded installer ZIP so file integrity and exact source provenance can be checked before running.
3. **Do not send an installer alone** and then tell the Owner to locate source scripts. The test kit must be self-contained for the **baseline installer/security test**, with **no Git, Python, Node, repo checkout, build tools, or administrator installation required on the Owner PC**. First-phase test must run with built-in Windows PowerShell 5.1. If the test machine lacks required Windows features, explain the blocker clearly rather than silently installing system components.
4. Keep this kit **outside public Git history**: do not upload private branding, customer data, credentials, logs, absolute home paths, or binary installer archives to the repository. Deliver the kit through a private channel with SHA-256. A link or file only counts as delivered once uploaded and verified. Do not claim a generated artifact exists until it does.
5. Ensure launcher **preflight safety**: detect OS name/build and privilege level; refuse elevation; reject unexpected package manifest hash/source SHA, missing files, occupied 127.0.0.1:8765, or a desktop shortcut that cannot be safely backed up/restored. Use only test sandbox paths. State upfront that Desktop `LotRadar.lnk` may be temporarily replaced (not silently); provide instructions to close LotRadar even if none installed. Do not launch a real Facebook session or touch installed data.
6. **R3 hardening**: in the **feature branch test harness only**, require evidence that symlink was actually created; installer error explicitly identifies a link/reparse refusal; outside target file and sentinel remain byte-identical; program/data unaffected. If file-symlink creation is blocked by Windows permissions, report `R3 SKIP`, not PASS, and offer the Owner a choice to enable Windows Developer Mode (not administrator mode). Do not attempt privilege escalation or weaken installer protection.
7. First-pass on home PC: run the easy launcher without `-FullLaunch`, collect OS/build, PASS/FAIL/SKIP and R3 details. **Only after baseline safety passes** offer a separate, explicitly labeled `RUN_FULL_LAUNCH_TESTS.cmd` which may download temporary Python/Chromium, exercise launcher/server lifecycle and then clean up. Do not silently turn on `-FullLaunch`.
8. After Claude actually implements the startup window for PR #5, build a **new** manifest-verified test kit and rerun Windows 11 and R3 plus actual native startup window, quick relaunch, retry/offline behavior, installer lock/contention, keyboard/high DPI/close behavior, and exact one-server lifetime. **Baseline installer evidence cannot certify PR #5's not-yet-written GUI.**
9. Claude returns `CLAUDE_WINDOWS11_R3_HANDOFF.md` listing package and kit SHA-256, manifest build type/source SHA, actual Windows 11 OS/build, privileges/PS 5.1, the exact command and exit code, R3 error/sentinel evidence, full PASS/FAIL/SKIP summary, shortcut restoration confirmation, temporary downloads, screenshot evidence where appropriate, and remaining limits. Send those to Gemini for independent review, then the Chief Architect.

### Acceptance criteria and protected systems
- The Owner's initial task is **only** download private kit, extract to a normal local folder, review `START_HERE.txt`, double-click `RUN_WINDOWS11_TESTS.cmd`, and return the resulting sanitized log/JSON. No coding or separate dependency installs.
- The kit itself builds/verifies on Claude's development environment, and launches test harness correctly on a **clean Windows 11 standard-user** system using only OS-bundled features.
- `R3 PASS` requires successful symlink creation and refusal **specifically because it is a reparse point**, not simply a nonzero exit code; unchanged outside target and zero production-data impact. Otherwise retain the proper FAIL/SKIP result.
- Startup UI acceptance remains **blocked until actual PR #5 production code exists and Windows 11 GUI tests run on a candidate package that names that exact commit**.
- Protect user inventory, photos, SQLite, selection JSON, Facebook drafts, 190px logo, existing installer rollback and launch locks. Changes to unrelated application files are prohibited.
- Risks: absolute paths in scripts, ambiguous kit provenance, package tampering, Windows symlink privileges, Desktop shortcut restore failure, port conflict, transient downloads, temporary workspace cleanup, and false confidence from testing an older baseline.
- Git: continue `feat/windows-startup-status-window`, update the existing draft PR #5; no merge to `main` without explicit Project Owner approval.



## Owner-approved OneDrive / redirected-folder QA addendum (2026-11-17)

**To: Claude — Lead Programmer.** **Phase:** Windows 11 OneDrive compatibility verification, independent of pending PR #5 startup GUI implementation. **Source basis:** approved main `bf61207a21999c8ff256b08c0d17650193e3835f`; current PR #5 pre-addendum HEAD `61181f9ddb1415d4a4e8c4a8df4dad88ec5b42dc`, which contains the self-contained QA kit but no startup GUI source. Gemini's current pasted audit reports Windows 11 Home build 26200 non-admin baseline installer tests **47 PASS / 0 FAIL / 1 SKIP** (F1 skipped) and R3 file-symlink refusal **PASS** with Developer Mode ON. These are **Gemini-reported**, not tests executed by ChatGPT.

### Request
The Project Owner is home on a Windows 11 PC and wants to close the longstanding **OneDrive-synced extraction and redirected Desktop / Known Folder Move** waiver while preserving all installer reparse-point and data-safety guards. Do not assume OneDrive is installed, signed in, enabled or redirecting Desktop: detect and ask for the Owner's consent before writing any disposable test files to a synchronized location. Never require moving the user's existing Desktop/Documents or enabling OneDrive backup.

### Current behavior and architectural boundaries (verified source)
- `installer/Install-LotRadar.ps1` defines `Test-UnsafeLink`: it refuses directory reparse points and actual file `SymbolicLink`/`Junction`, **but allows other verified reparse-point FILE types**, including ordinary OneDrive cloud placeholders subject to successful content hydration and SHA-256 validation. It verifies every manifest payload file before staging and again after staging; this guard must not be relaxed.
- `tests/windows/qa-kit/Run-QAKit.ps1` currently detects whether the extracted kit appears under `$env:OneDrive` and prints a note. **This is not a real OneDrive compatibility test**: it neither proves sync identity or hydration state, nor verifies installing from a OneDrive-synced *extracted installer payload*. It writes `RESULTS` under the kit folder, which may itself be cloud-synced.
- `tests/windows/Test-LotRadarInstaller.ps1` redirects `LOCALAPPDATA` and `APPDATA` to a disposable local sandbox but briefly creates/replaces a Desktop shortcut. The kit backs up and verifies that shortcut. On a OneDrive Known Folder Move Desktop, this shortcut is in a synchronized location even though the installed program and database are not.
- `docs/INSTALL.md` and `docs/MANUAL_ACCEPTANCE.md` still explicitly mark OneDrive extraction/installation unverified. A successful Windows 11 R3 test **does not** close the separate OneDrive compatibility waiver.
- Product installation must remain local under `%LOCALAPPDATA%\Programs\MarketplaceScanner`, with database/photos/drafts under `%LOCALAPPDATA%\MarketplaceScanner\data`. Do not place executable runtime or live data inside OneDrive.

### Implementation plan for Claude (in order)
1. **Preflight only / no account or sync changes.** Report actual Windows build, PS 5.1 version, non-admin status, `$env:OneDrive` / `OneDriveConsumer` / `OneDriveCommercial` presence, OneDrive sync-client state if ascertainable, the current Desktop known-folder path from `[Environment]::GetFolderPath('Desktop')`, and source/package full SHA. Record whether Desktop is a OneDrive KFM path **without revealing the real username or tenant**. Do not assume the environment variable alone proves active synchronization. If no usable OneDrive folder is present or the Owner declines writes, record **NOT TESTED / BLOCKED**, not PASS. Never launch OneDrive account setup or enable backup automatically.
2. **Prepare a disposable OneDrive test folder** only after explicit Owner permission, e.g. `<verified OneDrive root>\LotRadar QA TEST ONLY <random suffix>`, with exclusively synthetic test ZIP, extracted installer and sentinel files. No real customer data, production logo or credentials. Explain that these synthetic bytes may sync to OneDrive cloud; keep all verbose logs and shortcut backups in an **unsynced local folder** under `%LOCALAPPDATA%` rather than `RESULTS` inside OneDrive. Do not upload these artifacts to public Git.
3. **Local control:** first rerun the existing known-good non-elevated kit from an unsynced local folder and record PASS/FAIL/SKIP and package identity. Then **actual OneDrive source:** place a copy of the verified kit / installer ZIP in the approved OneDrive test folder, extract there, and run the installer/security harness **with sandboxed LOCALAPPDATA/APPDATA as before**. Verify real OneDrive extraction, manifest verification, clean install into a local test program directory, rollback, checksum checks, and R1–R5/R3 behavior. Do not treat a kit merely *stored* in OneDrive while payload is extracted only to local Temp as proof of OneDrive extraction.
4. **Files On-Demand / hydration:** when available, separately test fully local/hydrated files versus a safe synthetic online-only placeholder. Validate the expected behavior: either successful hydration with identical hashes and safe installation, or a clean actionable refusal with zero data mutation. Do not force dehydration or reconfigure sync globally. Do not classify an offline placeholder's inability to hydrate as an installer integrity bypass. Never bypass `Test-UnsafeLink` to make this test pass.
5. **Known Folder Move Desktop:** if the Desktop is already OneDrive redirected, test only with the Owner's consent to create a temporary **LotRadar.lnk**. Preserve the preexisting shortcut's SHA-256 and original bytes in unsynced local backup, restore or remove the test shortcut, and confirm final shortcut identity with before/after hash. Do not move the actual Desktop, change OneDrive settings, or overwrite unrelated shortcuts. If shortcut protection fails, stop further tests and report failure.
6. **Negative security tests within the disposable fixture only:** create a directory junction and R3 file symlink to a **throwaway external sentinel**, verify the installer rejects actual path escapes/reparse-point links, does not follow links or change outside files, and does not weaken existing R3 guarantees. Distinguish ordinary OneDrive FILE placeholders from actual symlinks/junctions by properties/target, not just a generic `ReparsePoint` attribute.
7. **OneDrive sync / race handling:** test path with spaces and non-ASCII name if supported. Check checksum correctness after sync/hydration, file-lock/incomplete-sync error handling, retry behavior, and clean rollback if files are unavailable or altered during install. Use deterministic synthetic fixtures. If safe controlled reproduction is unavailable, classify these as unverified, not passing.
8. **QA kit usability:** make the Owner's task a straightforward private download, extract, read `START_HERE.txt`, double-click a **separately labeled OneDrive QA launcher** only after affirmative disclosure, and return sanitized `SUMMARY.txt`, JSON and log files. The existing default Windows 11/R3 launcher must remain unchanged for ordinary local users. No manual Git/Python/Node installs; no admin elevation. Put the OneDrive mode behind explicit opt-in and keep it **outside** the silent default test flow.
9. **Verification/release:** use the same tested full HEAD/package manifest and do not infer success from an older baseline ZIP. After PR #5's startup GUI is implemented, rerun the OneDrive tests on a newly built candidate with the exact feature HEAD and confirm a launch originating from OneDrive-synced extraction (while installed server stays local), one server instance, accurate startup status and no orphan locks. The previously skipped **F1 -FullLaunch** is still a separate prerequisite for PR #5 overall acceptance.
10. **Handoff to Gemini:** return `CLAUDE_ONEDRIVE_QA_HANDOFF.md` with OS/build, verified OneDrive root / KFM status (sanitized), consent, exact SHA and package identity, local-control results, OneDrive-extraction evidence, R3 and reparse classification, hydration state, local data/shortcut before-and-after hashes, cleanup of synthetic test folder, expected vs actual errors, outstanding waivers and command/exit-code evidence. Gemini performs a new independent audit; Chief Architect reviews; Owner alone can authorize merging PR #5.

### Files Claude may and may not modify
- **May change (tests/tools/docs only if needed):** `tests/windows/Test-LotRadarInstaller.ps1`, `tests/windows/qa-kit/Run-QAKit.ps1`, new narrowly scoped `tests/windows/qa-kit/RUN_ONEDRIVE_TESTS.cmd`, `tests/windows/qa-kit/START_HERE.txt`, `scripts/build_qa_kit.py`, `tests/test_qa_kit.py`, and this handoff. Changes must remain compatible with the existing normal Windows 11/R3 test kit and deterministic packaging.
- **Do not modify for OneDrive testing:** `installer/Install-LotRadar.ps1`, `Marketplace Bootstrap.ps1`, `Launch Marketplace Scanner.cmd`, `server.py`, `core.py`, `app.js`, photo modules, database schema, original photos, current installer rollback algorithm, the 190px radar brand, Chrome Reader, or Facebook drafts. Only raise a separate proven-bug proposal to the Architect if source changes become genuinely necessary.

### Acceptance criteria / risks
- **OneDrive source verified:** actual extracted installer payload is within a verified, Owner-approved OneDrive sync folder (not just a spoofed environment variable) and successful safe install occurs inside the **local test sandbox**, or a legitimate unsupported reparse state is explicitly documented as a safe refusal instead of falsely claiming broad OneDrive compatibility.
- **Integrity:** deterministic package manifest and SHA hashes verified before/after, zero changes to installed real program/database/photos/drafts; no external sentinel altered; original Desktop shortcut restored byte-for-byte and no stray test shortcuts.
- **Security:** real symlinks/junctions remain rejected; OneDrive placeholder files are only accepted when fully readable, content-verified and safe; no target path escapes, credentials, raw local paths or personal filenames in public reports.
- **Correct interpretation:** report each combination as PASS/FAIL/SKIP/BLOCKED; a passing hydrated scenario does not prove offline-only placeholders or all corporate OneDrive configurations work. Do not lift the OneDrive waiver beyond actually tested modes.
- **Risks:** sync-client race, Files On-Demand hydration, reparse-point false positives, OneDrive KFM Desktop double-sync/shortcut restore, protected offline files, unsupported auth state, cloud upload of temporary files, path length and Unicode, and cleanup of disposable cloud files.
- **Git:** continue on `feat/windows-startup-status-window` and keep PR #5 DRAFT. No merge to `main`, no source refactor for speed, and no new production install unless approved separately.


## Owner requirement: vehicle photos must never be placed in a OneDrive sync folder by default (2026-11-17)

**To:** Claude — Lead Programmer. This extends the OneDrive QA scope for PR #5; it does **not** authorize a new photo-storage migration or application refactor.

### Request
The Project Owner wants dealership vehicle photos to remain **local-only** when using LotRadar with OneDrive. Do not upload/synchronize vehicle image caches, generated listing photo exports, or photo selection metadata simply because the installer ZIP, the Desktop or the Documents folder is synchronized. The owner's normal OneDrive sync behavior must not be modified.

### Current behavior (verified against approved main bf61207a...)
- On Windows, `server.py:default_data_dir()` returns `%LOCALAPPDATA%\MarketplaceScanner\data` by default. `server.py` accepts a `--data-dir` override, so the effective path must actually be verified at runtime.
- `photo_cache.py:PhotoCache.__init__` stores downloaded vehicle originals under `<data-dir>\vehicle_photos` and its `_branding_cache` beneath that local photo tree. It keeps per-VIN/source manifests and queue state in the data tree.
- `photo_selection.py:PhotoSelections` stores `<data-dir>\photo_selection.json` and writes prepared local Facebook photo exports under `<data-dir>\facebook_photos\<stock>`.
- `core.py:MarketplaceStore` keeps `marketplace.sqlite3` beneath the same data root. The installer installs *program code* under `%LOCALAPPDATA%\Programs\MarketplaceScanner` and deliberately does not copy or replace the user data directory.
- Therefore the **default application already keeps these files outside ordinary OneDrive Known Folder Move locations** (Desktop, Documents, Pictures). **No code change is needed to disable OneDrive sync in a standard installation.** However, a custom `--data-dir`, an unusual environment/profile redirection, or a junction/symlink targeting a synchronized directory can change the real storage destination. Do not claim the data is local-only without checking the resolved paths.

### Required behavior and engineering plan
1. **Preserve default paths unchanged.** Vehicle originals: `%LOCALAPPDATA%\MarketplaceScanner\data\vehicle_photos`; generated Facebook photos: `%LOCALAPPDATA%\MarketplaceScanner\data\facebook_photos`; selection metadata: `%LOCALAPPDATA%\MarketplaceScanner\data\photo_selection.json`. Keep the existing database and other draft data in the protected data folder. Do **not** create another `LotRadar Photos` directory in OneDrive, Documents, Pictures, or the Desktop.
2. **Audit the actual path, not its name.** In OneDrive QA preflight, inspect the effective `--data-dir` / actual running server data root; canonical/physical resolved paths for vehicle photos and Facebook exports; Windows reparse/junction attributes of each ancestor; and known OneDrive sync roots (consumer/business when present). Report only sanitized local-vs-synced classification. Do not mistake a OneDrive environment variable alone for proof that a path is actively synced.
3. **Verify OneDrive extraction is not photo synchronization.** The installer package may be extracted in a disposable OneDrive QA folder to test compatibility, but the sandbox's *installed app*, *vehicle photos*, *exports*, *selection JSON* and *database* must remain under the isolated local test `LOCALAPPDATA` tree. The test's synthetic OneDrive files can sync only after informed Owner consent; no real vehicle photo, private branding, database, Facebook draft or customer record may enter OneDrive.
4. **Use synthetic path-containment tests**: OneDrive-enabled and OneDrive-disabled/local-only fixture; hydrated and unavailable placeholders if offered by the machine; default data root; custom `--data-dir` pointing inside a disposable OneDrive test subtree; junction from a simulated local data root into the OneDrive test subtree. The last two cases must be identified as **NOT LOCAL-ONLY**; never silently claim they're excluded from sync. Do not use a real user's files and do not automatically alter the real runtime data path.
5. **No OneDrive selective-sync API or settings change.** The robust method is storing images outside synchronized folders. OneDrive does not provide a general application-owned guarantee to selectively omit arbitrary nested folders while keeping them locally usable. Do not set cloud-placeholder, offline, hidden or exclude flags on user files in an attempt to block sync; do not programmatically disconnect OneDrive or change backup settings.
6. **If the existing real data root resolves inside OneDrive** (exceptional/custom configuration), stop any proposed automatic relocation. Produce a separate migration plan for Owner authorization: verified complete backups, existing image/manifest and export inventory, hash before/after, pause jobs, migration and atomic cutover, rollback and no data loss. Never move, delete, duplicate or silently re-download the real cache in this OneDrive QA phase.
7. **If tests show a product-level unsafe default**, report an exact reproducible defect to the Chief Architect with affected files, source and Windows-build evidence. Do not modify `server.py`, `photo_cache.py`, `photo_selection.py`, `core.py`, installed photos or SQLite in PR #5 solely to pass a OneDrive test. Any newly proposed storage guard or configurable local photo path must be separately approved and independently regression tested by Gemini.
8. Ensure `START_HERE.txt` and `RUN_ONEDRIVE_TESTS.cmd` explicitly say: **“LotRadar vehicle photos and Facebook photo exports stay local; only the disposable installer-compatibility test fixture is placed in OneDrive.”** Include a `LOCAL_PHOTO_STORAGE` classification in sanitized results and an explicit warning if any effective photo/export path resolves within a OneDrive sync root.

### Acceptance criteria / risks / protected functionality
- For the default Windows path: photo originals, generated exports and selection JSON resolve to the local `%LOCALAPPDATA%\MarketplaceScanner\data` subtree, never to the OneDrive test tree; test fixture remains fully synthetic.
- Check paths via real canonical resolution/reparse awareness, not substring-only matching; distinguish `LOCAL_ONLY`, `IN_ONEDRIVE`, `UNKNOWN` correctly. If a path cannot be verified, do not claim PASS for local-only containment.
- Test ZIP extraction under OneDrive and Windows Desktop KFM separately from the storage assertions; successful installation from a synced folder must **not** imply syncing runtime photos or database.
- Preserve cached original SHA-256 bytes, VIN/source mapping, ordered export selection, cover/dedication copies, background photo jobs, Facebook drafts, SQLite consistency and existing backups. No changes to actual Owner data or OneDrive configuration.
- Risks: custom `--data-dir`, profile-folder redirection, junctions, reparse points, path prefixes, cloud hydration, accidentally uploading synthetic logs or private real files, interrupted cache jobs and photo database/manifest divergence.
- Git: update only Phase 1/OneDrive QA test tooling and documentation as necessary; continue draft PR #5, do not merge to main without explicit Owner approval. Claude returns the path-containment proof in `CLAUDE_ONEDRIVE_QA_HANDOFF.md` for Gemini audit.
