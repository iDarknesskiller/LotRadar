# ARCHITECT_HANDOFF.md — LotRadar Auto-Updater (planning only)

**To:** Claude — Lead Programmer
**From:** Chief Architect
**Date:** 2026-11-20
**Status:** DRAFT WORK ORDER. No implementation, deployment, release, or merge authorized.
**Approved source baseline at creation:** GitHub `main` `dd3b80cda20ded45d0e10f2fc20904bbf65648e4`. Reverify main SHA, version, packaging architecture and code before implementation.
**Feature branch:** `docs/auto-updater-architecture` (planning); create/continue a separate implementation feature branch after Owner approval.

## Request
Design a reliable Windows auto-updater for the future compiled LotRadar installation. The Project Owner alone approves and publishes official releases. An update must never be triggered solely by a push or merge to `main`.

## Current behavior
No dedicated auto-updater PR or implemented updater was found in the reviewed open PR list as of this handoff. PR #8 LR-007 is a **draft compiled-installer plan**, not a finished installer. The current source checkout/installer and bootstrap are not evidence of an approved, compiled update channel. The exact current version must be established from current source before coding.

## Required behavior
- Installed LotRadar checks a configured, Owner-controlled **published release channel**, initially proposed GitHub Releases (subject to access/security review), not branch commits or source ZIPs.
- Compare versions using explicit stable version metadata and supported upgrade rules; never auto-install merely because a newer commit exists.
- Inform user of version, changes, size and publisher; **ask user to approve installation** by default; no silent upgrades.
- Verify signed update metadata and package authenticity using a pinned public verification key; validate file digest and reject tampered, wrong-platform, unsupported, downgraded, or incomplete payloads. Keep signing private keys out of repo and binaries.
- Separate updater/helper coordinates a safe application stop and single-instance lock ownership, atomically installs verified binaries, preserves local database/photos/drafts/configuration and Chrome Reader pairing, and supports recovery/rollback on failure.
- Offline behavior: continue running installed version; no blocking startup if GitHub is unreachable. Do not require GitHub credentials in a public client. No telemetry or customer-data upload without separate approval.
- Coordinate installer/uninstaller/updater package IDs, paths, data ownership and upgrade schema. Avoid data-destructive rollback after irreversible schema migrations.

## Relevant architecture to inspect and verify
- `scripts/build_installer.py`, `installer/Install-LotRadar.ps1`, `Marketplace Bootstrap.ps1`, `startup/Show-LotRadarStartup.ps1`, `server.py`, `docs/INSTALL.md`.
- `tests/test_installer_build.py`, `tests/windows/Test-LotRadarInstaller.ps1`, relevant lock/process cleanup tests.
- PR #8 compiled distribution, PR #7 safe uninstaller, PR #16 keyboard acceptance, PR #11 scanner stability. Inspect all current paths, actual file identities and version before assigning edits.
- **Do not change** scanner worker logic, photo classification, listing text, Chrome Reader internals, customer database schemas, or unrelated UI to implement update checks.

## Implementation plan (proposed, not authorized)
1. Rebase architecture on latest Owner-approved `main`; document exact SHA/version, actual installer artifacts, existing lock/server/data paths, and which files would change. Confirm PR #8 packaging choices first.
2. Specify threat model, signed manifest schema (version, platform, minimum compatible version, artifact digest, signature, release notes), trusted-key rotation and release publication procedure under Owner authority.
3. Prototype update check and version comparison as an isolated component; network timeout, offline mode, caching and error states must not block LotRadar.
4. Implement user-approved update download to a staging directory, verify signature/digest **before** executing, and protect against path traversal and untrusted redirects.
5. Implement an external update helper with owned-process shutdown, lock release, backup where appropriate, transactional binary swap, health validation, failure recovery, and restart. Define precise database migration/rollback policy.
6. Integrate UI prompt, progress/error states, release notes, manual check and safe defer. Keep update helper and installer ownership boundaries clear.
7. Validate integration with compiled installer and safe uninstaller; complete Claude implementation review, Codex independent adversarial tests, Claude disposition, Gemini independent audit, Owner final approval. Publish nothing automatically.

## Protected functionality
Existing local-first/offline use; startup/bootstrap single-server behavior; localhost service; scanner jobs and cancellation; data under user-local paths; SQLite/photos/drafts; Chrome Reader; installer rollback and OneDrive/reparse safety; private branding assets; user settings. Never delete customer data as part of a binary update.

## Acceptance criteria
- Only an explicitly Owner-published and cryptographically valid release can be offered/installed; a merged PR or unpublished draft is ignored.
- No update installs without the user's confirmation (unless Owner separately approves an explicit managed policy).
- Offline/unreachable/invalid metadata cannot prevent normal startup; tampered artifacts never execute.
- Interrupted downloads, locked files, crashes, and failed health checks leave a runnable previous app or a clearly recoverable state, without lost user data.
- Existing local data and version records survive successful update; no duplicate server or orphan helper.
- Installer/uninstaller integration is tested on exact candidate artifacts with documented hashes and evidence.
- No merge to `main`, release or deployment without explicit Project Owner authorization.

## Required tests (must execute before approval)
Unit: version ordering, compatibility, signed manifest valid/invalid/expired/key rotation, SHA-256 mismatch, path sanitization, release channel filtering.
Integration: no-network, timeout, 404, partial download/resume, interrupted install, insufficient permissions/disk space, locked files, concurrent update requests, update helper crash, old version recovery.
Windows 11 standard-user clean install and upgrade from prior approved release; full app startup and localhost health, scanner idle/active handling, Chrome Reader and private asset availability, SQLite/photos/drafts/config hashes and migrations; uninstaller coexistence; OneDrive/reparse safeguards.
Manual: update notification, defer, explicit consent, progress, error/retry and restart. Record exact build SHA, package/manifest signature, machine/OS, pass/fail evidence. Windows 10 support remains unverified unless explicitly tested.

## Risk areas
Unsigned or spoofed GitHub releases, signing-key compromise, version rollback, TOCTOU and partial installs, server/process races, updater self-replacement, locked browser profile, schema migration incompatibility, data deletion, private assets in package, network outage, CDN caching, release rollout/rollback semantics. Public GitHub releases may be unsuitable for private distribution or licensing.

## Git instructions
This PR is documentation only. Claude must create or continue an implementation **feature branch** from the then-current approved `main`, not edit `main` directly. Keep implementation scoped and traceable to this work order. Do not merge or publish any release without explicit Owner approval.
