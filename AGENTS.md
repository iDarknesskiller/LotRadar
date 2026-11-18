# LotRadar — Repository Guidance for Coding Agents

These rules apply to code-generation and code-review agents working on LotRadar. They are proposed in a draft governance PR until approved by the Project Owner.

## Authority and development roles

1. **Project Owner:** Defines requirements; exclusively authorizes merges to `main`, releases, and changes to privacy/security policy.
2. **ChatGPT — Chief Architect:** Inspects the latest approved GitHub `main`, determines root cause and affected files, publishes task-specific `ARCHITECT_HANDOFF.md` instructions, coordinates assignments.
3. **Claude — Lead Programmer:** Primary implementation owner; reviews implementation continuity and coordinates engineering handoffs.
4. **Codex — Senior Developer:** Peer-level engineering implementer. May take over explicitly delegated work when Claude usage is exhausted/unavailable, implement independent assigned issues on separate branches, or review Claude's code. See [Senior Developer role](docs/ai/CODEX_SENIOR_DEVELOPER.md).
5. **Gemini — Independent QA:** Independently audits implementation and actual test evidence, flags unsafe changes and regressions.

Codex is **not** merely an advisor: when assigned an implementation task, it can write code and tests and prepare commits/PRs within the assigned branch. Claude remains Lead Programmer; Codex works autonomously only within the named scope. The Architect coordinates handoff, not simultaneous editing of the same file/branch by unsynchronized agents.

## Source and task startup

- Canonical repository: `iDarknesskiller/LotRadar`.
- At task start, fetch and record exact approved `main` SHA, target PR/branch HEAD, relevant files, current behavior, expected behavior and any architecture handoff. Don't assume remembered SHAs remain current.
- Implement against the assigned feature branch/PR, **never directly on `main`**. For unrelated work create a separate feature branch and draft PR; no merge, force-push, branch deletion, release or live installation without the Project Owner's explicit approval.
- Prior assistant comments, generated screenshots and architectural drafts may be superseded. The **latest explicit Owner correction** plus canonical updated architecture handoff wins. Identify contradictions before coding.
- Before touching existing PR work, confirm that no other agent is simultaneously modifying that branch; ask the Architect/Owner to coordinate if there is a collision.
- Never claim a file has been provided, an automated bot triggered, a test has passed, or a PR has been reviewed unless there is verifiable evidence.

## Protected LotRadar functionality

- Inventory is primarily **used Toyota and Mitsubishi**; protect saved vehicles, VIN/stock identity, SQLite, local photos, selected photo order and Facebook drafts.
- Respect private `%LOCALAPPDATA%\MarketplaceScanner\data` and runtime/installation directories. Do not reset/wipe/migrate real user files or run destructive recovery against unknown installations.
- Keep local server on `127.0.0.1:8765`, preserve lock ownership, prevent duplicate servers/browser tabs and verify health before claiming ready.
- Preserve the Chrome Reader integration, Facebook listing preparation, vehicle photo processing and existing guarded installer rollback semantics.
- Protect OneDrive/cloud reparse-point guards, junction/symlink safety, and local-data location. Don't accidentally place photos in a cloud-sync folder.
- Never commit business card, dedication photo, production logo/icon, user/customer data, tokens, credentials, local logs, generated installers or test captures containing sensitive material.
- Avoid invented vehicle specifications, equipment and availability claims.

## Engineering and test evidence

- Match modified files to an explicit request; document files that should **not** change.
- Prefer minimal, reviewable fixes with regression tests. Tests must be **executed** for a PASS claim, with commands, environment, output and exact candidate commit recorded.
- Windows PowerShell 5.1/Windows 11 integration cannot be proven by Linux-only unit tests; flag unsupported environments as **BLOCKED/NOT RUN** rather than passing them by inference.
- Include functional and regression tests for failures, retries, focus/DPI, install/update/rollback and data integrity whenever affected.
- Handoff to next agent must list branch, HEAD SHA, owner of current task, exact files changed, tests passed/failed/not run, blockers, risks and next steps.
- Request Gemini independent review at exact candidate SHA before seeking Owner approval.

## Review mode versus implementation mode

- **Review:** Read and inspect; provide actionable issues with file/line evidence and severity, and do not mutate code unless separately assigned.
- **Implementation:** Modify only scoped files and tests on approved feature branch, show diffs and evidence, and leave as draft pending review.
- **Takeover:** First read previous Claude handoff, validate current HEAD, preserve uncommitted/unfinished work, announce takeover in PR, and avoid two writers touching the same branch.

This guidance does **not** grant any agent the ability to start work automatically or bypass repository permissions. GitHub connection, Codex tasks and review triggers require their respective explicit setup/authorization.
