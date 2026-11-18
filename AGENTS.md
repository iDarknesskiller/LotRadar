# LotRadar — Agent Collaboration Rules

**Status:** Proposed in draft PR #9; do not treat this as approved `main` policy until the Project Owner merges it. The Owner's explicit latest instruction for individual PRs applies immediately when recorded on that PR.

## Authority and roles

| Role | Owner | Responsibility |
| --- | --- | --- |
| Project Owner | Human Owner | Set priorities, accept scope/waivers, authorize merges and releases |
| Chief Architect | ChatGPT | Inspect latest approved main, diagnose affected systems, issue precise architecture handoff, coordinate work and risks |
| Lead Programmer and Test Designer | Claude | Implement the change; design and approve the test plan; review Codex's full independent report; decide if the candidate is ready to be submitted to Gemini |
| Independent Test Engineer | Codex (default) | Test the frozen candidate independently; challenge Claude's tests, add missing tests in isolated test-only changes, run tests and send a complete report **back to Claude first** |
| Final Independent QA Auditor | Gemini | Independently review candidate source and complete evidence after Claude's readiness gate; identify defects and provide a QA verdict. Gemini does not merge |
| Stand-in Senior Developer | Codex (explicit reassignment only) | If Claude is unavailable, may implement an assigned change on a scoped branch; **must not represent its own tests as independent certification of the code it authored** |

**Canonical workflow:** [`docs/ai/QA_WORKFLOW.md`](docs/ai/QA_WORKFLOW.md).  
**Codex role:** [`docs/ai/CODEX_INDEPENDENT_TESTER.md`](docs/ai/CODEX_INDEPENDENT_TESTER.md).  
**Architect role change:** [`docs/ai/ARCHITECT_HANDOFF.md`](docs/ai/ARCHITECT_HANDOFF.md).

## Required sequence for every substantive code PR

1. ChatGPT records approved `main` SHA, relevant branch HEAD, actual behavior, desired behavior, affected and protected files, acceptance and risks in an architecture handoff.
2. Claude implements on a feature branch and authors **`CLAUDE_TEST_PLAN.md`**, with IDs, objective setup, expected results, negative cases, data-integrity assertions and environment requirements, before requesting independent testing.
3. Claude freezes and identifies **one exact candidate SHA** and package/manifest identity. Codex is given an explicit testing assignment and runs against that frozen candidate, not a moving branch alias.
4. Codex examines the tests critically, executes what is possible, independently adds missing test cases when useful, and returns **`CODEX_TEST_REPORT.md` plus individually sanitized raw evidence to Claude**. Unrun tests are **NOT RUN**, not passed. Tests added by Codex are clearly identified.
5. Claude triages **every failure, skip and risk**. Claude may fix issues, propose extra tests or record Owner-required scope decisions; changed code means a new candidate SHA and rerun of affected tests. Claude records a **`CLAUDE_QA_READINESS.md`** decision: READY FOR GEMINI or HOLD, with reasons. Neither a clean Codex report nor Claude's decision is final QA.
6. Gemini receives the **unaltered complete** Claude plan, Codex report, raw sanitized evidence, Claude triage, changed source and exact candidate SHA. Gemini independently audits; failures cycle back to Claude and Codex. Do not filter or hide failed tests when submitting.
7. The Project Owner alone approves any merge to `main`, release, deployment or risk waiver. Merging and issuing a release are distinct decisions.

If Claude is at a usage limit, Codex can **continue independent testing against an already frozen plan/candidate**. The gate to Gemini remains HOLD until Claude returns or the Owner formally delegates the gate to another named lead. No agent may forge Claude's acceptance.

## Version and provenance

Every plan/report must identify: repo, PR, approved `main` SHA, feature candidate SHA, test harness SHA (if different), package manifest `source_commit`, OS/build/PowerShell version, executed command, exit code and PASS/FAIL/SKIP/NOT RUN/BLOCKED. A report at an old SHA cannot certify a new one. If a test-only patch lands on the feature branch, identify both tested code tree and harness tree; revalidate any dependency affected by that patch. Do not claim Windows GUI passes from Linux-only tests.

## Test independence and branch ownership

- Codex as independent tester **must not modify production code under test**. Codex may add or strengthen tests on a separate `test/<task>` branch / draft PR or isolated workspace, with traceable test commits and a clear chain from candidate to test-harness SHA. Claude reviews incorporation of those tests.
- If Codex becomes stand-in implementer, its own testing becomes developer self-test; a distinct tester/independent Gemini audit is required for that work.
- One active writer per implementation branch. Confirm ownership before changing it; no concurrent unsynchronized writes, resets or force-pushes.
- A GitHub comment alone does not trigger Codex/Gemini execution unless the actual connector or automation has been configured and started.

## LotRadar protections (all roles)

- Protect used Toyota/Mitsubishi vehicle records, VIN/stock and SQLite integrity, vehicle photo originals and selection order, Facebook drafts, inventory caches, Chrome Reader pairing and local-only operation.
- Protect `%LOCALAPPDATA%\MarketplaceScanner\data` and `runtime`; server health/locks at `127.0.0.1:8765`; installer rollback; OneDrive cloud-tagging and reparse/symlink guards; Desktop shortcut ownership and restoration.
- No unapproved real-system installs, persistent dependency downloads, destructive cleanup, photo moves, OneDrive setting changes, credential exposure, Facebook posting or killing unrelated browser processes.
- Private logos, business card and dedication assets, tokens, customer information, user-specific folders, unsanitized logs and screenshot content must remain outside public Git.
- Preserve test reproducibility, safety preflight, synthetic fixtures, nonadmin Windows PowerShell 5.1 checks and rollback evidence for affected systems.

## Stop rules and escalation

P0/P1 findings, unproven data/shortcut preservation, manifest/source mismatch, hazardous cleanup or missing critical evidence mean **HOLD**. Claude may recommend a scope waiver for noncritical coverage, but only the Owner can grant it, and Gemini must see the disposition. Do not translate a SKIP/BLOCKED into PASS. No agent may merge or release without explicit Owner approval.
