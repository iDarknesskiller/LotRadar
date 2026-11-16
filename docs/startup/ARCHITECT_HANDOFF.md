# ARCHITECT_HANDOFF.md

**To:** Claude — Lead Programmer  
**From:** ChatGPT — LotRadar Chief Architect  
**Task:** Windows startup status window, separate from logo PR #4/photo-gallery PR #3  
**Repository:** https://github.com/iDarknesskiller/LotRadar  
**Approved `main` (at inspection):** `b9e843111ce1ed39f7d4003dd39c06eb75724325`  
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
- Keyboard navigation, high-DPI scaling and closing/minimizing window during setup; no UI deadlock. Repeat Windows 11 only if waiver is lifted (currently unverified).

## Risks
GUI/main-thread deadlocks; `Start-Process -NoNewWindow` and redirected stream lifetime; early bootstrap exit releasing launch lock; zombie child server; duplicated Chrome windows; race between health, event files, and actual server readiness; failed download retries; orphaned status/log files; WinForms availability and execution policy; auth/path/log leakage; first-run long stalls; missing installer file allowlist; launch while installer swaps program directories.

## Git instructions
Work on `feat/windows-startup-status-window` based on approved `main` `b9e843111ce1ed39f7d4003dd39c06eb75724325`. Create/continue the draft PR for *startup only*. The official logo-size changes belong to PR #4, photo-gallery work belongs to PR #3. **No merge to `main` and no release without explicit Project Owner authorization after Gemini and Architect review.**