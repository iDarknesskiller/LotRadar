# CLAUDE_QA_READINESS.md — Lead Programmer's Independent-Test Triage

**To:** Gemini — Final Independent QA (only after Claude's explicit READY decision)  
**From:** Claude — Lead Programmer / Test Designer  
**Status:** `HOLD` or `READY FOR GEMINI`. Do not substitute this for Owner release approval.

## Candidate identity

- PR and task:
- Approved `main` SHA:
- Current frozen feature SHA / tree:
- Package `source_commit` and hash:
- Claude test plan SHA and link:
- Codex independent test report SHA/link, unchanged original report:
- Codex test-harness SHA and `CX-` additions:
- Sanitary raw JSON/log/screenshots manifest and private delivery:
- Any source SHA changes after the reported test run:

## Claude review of all results

| Test/finding | Codex result | Evidence verified? | Claude disposition | Rationale and link | Fix commit or Owner waiver | Retest ID/status |
| --- | --- | --- | --- | --- | --- | --- |
| G10 | PASS/FAIL/... | Yes/No | FIX/RETEST/ACCEPT/HOLD | ... | ... | ... |
| E3 | PASS/NOT RUN/... | Yes/No | ... | ... | ... | ... |

**Must include every FAIL, SKIP, NOT RUN, BLOCKED, INCONCLUSIVE and every independently added test, not just high-severity findings.**

## Readiness checks

- [ ] Required acceptance criteria trace to executed cases and raw evidence.
- [ ] No unexplained P0/P1 or data-integrity/security failures; any such finding means HOLD.
- [ ] All Codex added tests have accepted/rejected/deferred rationale, never deleted from report.
- [ ] Source-tree/test-harness/installer ZIP checksums are reconciled; no old SHA PASS relabeled as current.
- [ ] If fixes changed application or accepted harness tests, Codex retested new candidate as specified.
- [ ] Physical GUI checks distinguished from simulation, private production build from DEV, Windows-only from Linux-only.
- [ ] Remaining hardware/OneDrive/Windows10/display/asset gaps are explicit; Owner-approved scope decisions attached where necessary.
- [ ] Sanitized original raw evidence is available to Gemini, including failures and aborted runs.
- [ ] Safe cleanup and user data/shortcut hashes accounted for.

## Decision

**Claude decision:** `HOLD` / `READY FOR GEMINI`

**Why:** 

**Gaps remaining:**

**Exact implementation SHA for any Gemini audit:**

**Required accompanying files:** `ARCHITECT_HANDOFF.md`, `CLAUDE_TEST_PLAN.md`, `CODEX_TEST_REPORT.md`, added test diffs, raw sanitized evidence and this readiness review. Do not publish private customer/logo/desktop data. If HOLD, return issues to Claude implementation and Codex retesting; do not call Gemini's audit completed.

**Owner-only gate:** Gemini may audit readiness independently. Neither Claude nor Gemini authorizes merge, release, installer deployment or waiver without explicit Owner consent.
