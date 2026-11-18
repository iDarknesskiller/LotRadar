# CODEX_TEST_REPORT.md — Independent Test Engineer → Claude

**Do not fill this from remembered pass counts. Use executed, individually sanitized raw results.**

## Header and integrity

- **To:** Claude — Lead Programmer and Test Designer.
- **From:** Codex — Independent Test Engineer.
- PR/task and linked Claude test plan:
- Approved main SHA at run time:
- Frozen implementation SHA and **Git tree**:
- Test harness SHA/branch, list of Codex test-only additions:
- App version / packaged manifest `source_commit`, package SHA256, QA kit SHA256:
- OS build, user privilege, PowerShell/Python/Browser versions:
- Test environment: native/sandbox/cloud runner; display mode/DPI, network/OneDrive when relevant:
- Time window and command invocations:
- Data/shortcut snapshot location and **sanitized** hash manifest:
- Previous test history consulted (SHA; not current passes):

## Executive result

- **Disposition for Claude:** `NO CRITICAL FINDINGS / FAILURES FOUND / BLOCKED BY ENVIRONMENT / INCONCLUSIVE`
- Tests: **PASS __ / FAIL __ / SKIP __ / NOT RUN __ / BLOCKED __ / INCONCLUSIVE __**.
- Critical/high findings:
- Evidence gaps (missing actual log/image/manifest):
- Side effects / cleanup outcome:
- Recommendation: **fix / rerun / investigate / candidate may be considered by Claude** (this is **not** Gemini or Owner approval).

## Full case matrix

| ID | From | Exact command or manual method | Expected | Actual | State | Exit code | Evidence filename + SHA256 | Defect |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| G10 | Claude | Windows owned-window targeted mnemonic | Owned console shown; exit semantics | Record observed result | PASS/FAIL/... | 0/91/... | sanitized-G10.json, SHA | URL |
| E3 | Claude | Actual physical Tab/Alt keys | Documented focus/accelerators | Record observed result | PASS/FAIL/BLOCKED | n/a | screenshot/video/report | URL |
| CX-001 | Codex addition | New independent test and pre-declared expected value | ... | ... | ... | ... | ... | ... |

Include **all** case IDs from Claude's plan, even those that never ran, and all additional Codex IDs. Do not collapse multiple failures into one all-green summary.

## Independent additional tests proposed and actually executed

For each `CX-###`:
- Reason Claude's original plan missed a likely defect:
- Test code path, own branch, commit SHA and diff:
- New predeclared expected result and isolated fixture:
- Exact command, observed outcome, raw evidence and side effects:
- Whether Claude should incorporate the regression test (yes/no and reason):
- **No production code edits** made by Codex during independent testing; if any occurred, declare role conflict and suspend independent certification.

## Defect reports and recommendations

| Finding | Severity P0–P3 | File:line | Reproduction | Consequence | Fix direction for Claude | Retest cases |
| --- | --- | --- | --- | --- | --- | --- |
| CX-F-001 | P1 | path:line | command/fixture | impact | recommendation not production patch | ID list |

Never hide failures in a summary. Explicitly describe **test-harness defects** separately from **product defects**; do not excuse a failing test without reproducible proof.

## Safety and cleanup record

- Was real local inventory/SQLite/photos/selections/Facebook data untouched? before/after hash proof:
- Was the user's Desktop/Start-menu shortcut restored byte-identical?
- Was the localhost 8765 listener foreign? Did we leave its ownership intact?
- Are install/launch locks and temporary directories clean?
- Did testing touch OneDrive? Which synthetic files (never customer data)?
- Were unrelated Chrome/Edge tabs/processes untouched?
- Did any persistent Python/Chromium/WinGet dependency get installed with consent?
- List any leftovers/blocked cleanup; never delete unknown assets to make results green.

## Raw individual evidence manifest

| File | Format | SHA256 | Captured at candidate/harness SHA | Sanitized? | Where privately shared |
| --- | --- | --- | --- | --- | --- |
| Full-launch result | JSON | ... | ... | yes | ... |
| Full-launch console | TXT/LOG | ... | ... | yes | ... |
| Python unit output | TXT/LOG | ... | ... | yes | ... |
| UI window capture | PNG | ... | ... | yes | ... |

No forged evidence, no public posting of private brand/customer data, and no ZIP-only delivery.

## Exact handoff back to Claude

- **Implementation SHA evaluated:** ...
- **New independent tests introduced:** ...
- **Failures / blocks / environment gaps:** ...
- **Recommended Claude actions:** ...
- **Test rerun scope if implementation changes:** ...
- **Next owner:** Claude for G3 triage. Gemini final audit is not yet requested unless Claude issues `CLAUDE_QA_READINESS.md` as READY FOR GEMINI.

## Claude's response (not filled by Codex)

Claude must separately create `CLAUDE_QA_READINESS.md`, disposition EVERY Codex finding/test and clearly state **HOLD** or **READY FOR GEMINI** on an exact implementation SHA. A clean report by Codex is **not** final independent QA.
