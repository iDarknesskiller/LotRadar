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
