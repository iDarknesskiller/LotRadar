# CLAUDE_TEST_PLAN.md — Lead Programmer's Test Design

**Copy and instantiate for each implementation PR. Remove placeholders; don't present a template as an executed plan.**

## Identity and scope

- PR / feature / purpose:
- **Claude — Lead Programmer/test plan author:**
- Owner approval and Architect handoff URL:
- Approved `main` SHA:
- Frozen implementation branch / commit SHA / Git tree:
- App/package manifest `source_commit`, package SHA256 and build type:
- Test-harness base SHA:
- Current behavior:
- Required behavior:
- Protected systems (unchanged):
- Known defects and past test evidence (SHAs; mark historical):
- Explicit Owner-approved waivers (if any, with approval link):

## Test strategy and execution environment

- Units: code-focused, deterministic.
- Integration: real services/sandbox with test data.
- Security and data integrity: hashes, canonical path/OneDrive/symlink/malicious paths, rollback, permissions.
- GUI/manual: Windows-specific accessible interactions, real keyboard vs simulated messages, actual DPI/resolution.
- Packaging and install: production branding / DEV fallback, manifest, install/update/revert.
- Environmental prerequisites: Windows version/build, PowerShell, Python/browser, network, offline mode, developer privileges, test-only folders.
- Safety preflight: exact paths/processes, system current state, opt-in for installing/downloads, no customer data.
- Abort rules (P0/P1, real-data mutation, unknown symlink ownership, unverified shortcut backup).

## Case-by-case definitions

Write a separate row **for each independent assertion**, not one generic "startup works" row. Use stable existing IDs plus new `CL-###` IDs. Codex may add `CX-###` without altering Claude's originals.

| ID | Category | Preconditions and fixture | Exact executable steps/command | Observable expected result | Evidence needed | Risk level |
| --- | --- | --- | --- | --- | --- | --- |
| CL-001 | Example | Synthetic preflight | Exact command | Explicit success/failure criteria | JSON, logs, screenshots if UI | P1/P2 |
| CL-002 | Example negative case | Inject failure in owned sandbox | Exact command | Preserves live data and aborts safely | exit code, hashes, server/lock checks | P1 |

Add as many cases as needed. For every test requiring separate hardware, a private image or real-world UI, mark REQUIRED vs OPTIONAL and how to record BLOCKED.

## Additional cases Codex should seek

List likely untested boundaries and explicitly invite Codex to add tests; possible topics: second simultaneous launch, process cleanup path-prefix collisions, wildcard chars, browser-tab ownership, offline retry, skipped module, partial corrupt payload, cloud-tagged source vs destination, high DPI controls, persistence and data-migration integrity. Do not dictate the exact answers to Codex's exploratory tests.

## Test artifacts contract

- Logs and per-case JSON contain case IDs, test result and exit code.
- Capture actual candidate SHA + tree SHA + manifest `source_commit` + kit hashes; do not guess.
- Mask personal names, customer VINs, file paths, tokens and account identities.
- Record screenshot-only of the app window (not desktop) and permission to share private logo.
- Record before/after hashes for data/shortcut/artifacts when touched by sandbox.
- Report failing/aborted test runs too. No ZIP-only evidence.
- Output location (private channel) and SHA256 manifest for each sanitized file:

## Handoff instructions to Codex

- **Test candidate:** SHA ...
- **Test harness:** SHA ...
- **May add tests:** yes, test-only branch; report each with original expected result.
- **Do not modify production source under test.**
- Required commands to execute:
- Manual steps requiring Owner assistance/approval:
- Safety stops / cleanup:
- Deliver `CODEX_TEST_REPORT.md` plus individual raw evidence **to Claude**.

## Claude gate G1: READY FOR INDEPENDENT TEST? 

- [ ] All requested code changes committed; implementation SHA recorded.
- [ ] Plan covers acceptance, regression, negative, data-integrity and error cases.
- [ ] Windows-only requirements explicitly distinguish actual vs simulated tests.
- [ ] Sandbox/production safety and evidence requirements defined.
- [ ] No unsafe uncontrolled real-system change implied.
- Decision: **READY FOR CODEX / HOLD** (with reason).
