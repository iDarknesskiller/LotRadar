# LotRadar AI README

This is the central reference for human-led, AI-assisted LotRadar development. It consolidates the contribution record from PR #2 and the working rules from PR #9. Its repository-wide adoption requires the Owner's approval; explicit Owner instructions for an assigned task apply within that task immediately.

## Roles and authority

| Role | Responsibility |
| --- | --- |
| Project Owner | Sets priorities; approves implementation scope, risk waivers, merges and releases. Merge and release are separate decisions. |
| ChatGPT, Chief Architect | Inspects source, validates and deduplicates findings, designs safe solutions, prepares work orders and coordinates QA. |
| GitHub Copilot, Issue Scout | Proposes bugs, security/performance/data risks and test gaps. Findings start unverified. |
| Claude, Lead Programmer and Test Designer | Implements authorized work, designs tests, reviews every Codex finding and decides HOLD or READY FOR GEMINI. |
| Codex, Independent Test Engineer | Challenges coverage, tests frozen code and adds useful isolated test-only cases; reports to Claude. |
| Gemini, Final Independent QA | Audits exact source and complete evidence after Claude's readiness gate; reports verdict and risks. |

Codex may implement only under explicit reassignment; its own tests cannot independently certify its authored changes. One active implementation writer per branch. No AI can authorize merging or release.

## Source of truth

Use https://github.com/iDarknesskiller/LotRadar and latest Owner-approved main, or the explicitly assigned PR. Recheck main/candidate/harness SHAs, relevant source, tests, commits, conflicts and package manifests before new engineering decisions. Memory and old handoffs are context, not proof of current behavior. If GitHub is inaccessible, state it.

Label facts VERIFIED, HYPOTHESIS or NOT VERIFIED. An old-SHA PASS does not certify new code. Identify package source_commit, package_version, build_type and hashes; a historical exported FILE_MANIFEST.json is not a new installer manifest.

## Finding intake

Read the scout finding and evidence at its stated SHA. Inspect exact source or safely reproduce, check existing issues/PRs, then classify VERIFIED, INVESTIGATE, DUPLICATE, FALSE POSITIVE, STALE or OUT OF SCOPE. Record P0-P3 priority, confidence, impact and data/security risk. Create one scoped work item per verified cause or an investigation if uncertain. Owner prioritizes and authorizes implementation.

A scout report, issue, comment or filename does not start another AI or authorize fixes. Scouting schedules and platform/plan capabilities must be checked before claiming automation exists.

## Required workflow

1. Chief prepares ARCHITECT_HANDOFF.md: Owner request; verified current and required behavior; root cause or hypothesis; exact architecture/files; ordered plan; edit/exclusion scope; protected behavior; measurable AC IDs; required tests; risks; baseline, branch and writer; no implicit merge permission.
2. Claude implements within authorization and authors CLAUDE_TEST_PLAN.md. Freeze candidate and harness SHAs. Map each AC to test IDs, commands, prerequisites, expected results, negative/edge cases, fixtures, cleanup and evidence.
3. Codex independently challenges and executes the authorized plan against frozen code. Add meaningful CX tests on an isolated test-only branch/workspace with traceable harness identity. Do not change production under test.
4. Codex returns CODEX_TEST_REPORT.md and all sanitized raw individual artifacts to Claude, including failures and omissions.
5. Claude dispositions EVERY finding, test addition and coverage gap in CLAUDE_QA_READINESS.md: HOLD or READY FOR GEMINI, exact identities and reasons. Code changes require a new candidate and affected retests. If Claude is unavailable, frozen testing may continue within authorization, but its readiness gate cannot be invented; Owner may appoint an acting lead.
6. Gemini receives the complete unfiltered reports, exact source, raw evidence and Claude triage, then issues GEMINI_FINAL_AUDIT.md. Defects return through Claude, Codex retest and Gemini re-audit.
7. Chief recommends readiness and reports risks; Owner separately decides merge and release.

READY FOR GEMINI authorizes referral, not merge. P0/P1 defects, unsafe cleanup/data changes, source/manifest mismatch, missing critical proof or unapproved critical waivers mean HOLD.

## Evidence contract

Each report records test IDs, source/harness SHAs, package/kit identity, OS/build, privilege and relevant tool versions, exact commands, exit codes, expected versus actual outcomes, evidence names/hashes, findings and limitations. Use PASS, FAIL, SKIP, NOT RUN, BLOCKED and INCONCLUSIVE accurately. Preserve failed runs and authentic provenance.

Synthetic keyboard messages are not physical-key/manual tests. Preview is not real startup. Static source checks are not Windows runtime certification. A deferred test is not a PASS or waiver.

Keep originals private; share sanitized individual source/evidence files with Gemini in batches within verified attachment limits (Owner reports ten per prompt). Do not rely on ZIP-only delivery or fabricate missing evidence.

## Protected behavior and Git

Preserve used Toyota/Mitsubishi inventory, VIN/stock identity, SQLite records, original photos, selection/export order, Facebook drafts, verified equipment, Chrome Reader/pairing, browser sessions, offline operation, reconnect and single-server locks; installer guards, backups/rollback, shortcuts and settings.

Protect %LOCALAPPDATA%\\MarketplaceScanner\\data and local-only storage, OneDrive cloud tagging and reparse/symlink guards. Use safe synthetic fixtures; avoid unintended migrations/deletion, customer uploads, Facebook posting, persistent installs, sync-setting changes and killing unrelated processes. Never publish private assets, tokens, user/customer data or unsanitized evidence.

Use scoped feature branches and confirm sole writer. No unapproved force-push, reset, branch deletion, deployment, merge or release. Recheck candidate and remote before authorized publication. Record explicit Owner consent boundaries; do not silently extend consent between candidates or tiers.

## Contribution record

AI role acknowledgements do not create GitHub identities or prove commit authorship. Record work only when actually used and supported by evidence.

PR #2 proposed historical attribution for installer/bootstrap PR #1: ChatGPT architecture/coordination, Claude implementation/test tooling, Gemini independent review and Owner requirements/manual acceptance/approval. PR #1 merged as b9e843111ce1ed39f7d4003dd39c06eb75724325. Its historical tests and waivers remain tied to that cycle, not current certification.

Closed PRs #2 and #9 retain the detailed historical proposals. This README replaces their proposed documentation structure, without changing application behavior or authorizing any outstanding feature.
