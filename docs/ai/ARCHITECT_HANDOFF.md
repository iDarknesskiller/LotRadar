# ARCHITECT_HANDOFF.md — Rebuild LotRadar's AI Test and Approval Workflow

**To:** Claude — Lead Programmer and Test Designer; Codex — Independent Test Engineer; Gemini — Final Independent QA  
**From:** ChatGPT — Chief Architect  
**Owner request (2026-11-17):** "Codex as independent tester and give results back to Claude for him to decide whether it's good to send to Gemini. Claude designs the tests. Codex can add more tests if suited. Rebuild the workflow."  
**Status:** Architecture proposal in draft PR #9, not approval to merge or alter production.  
**Source of truth:** https://github.com/iDarknesskiller/LotRadar  
**Approved `main` SHA at inspection:** `bf61207a21999c8ff256b08c0d17650193e3835f`  
**Current version:** No unified app version; build manifest and exact `source_commit` identify packages.  
**Existing governance branch reviewed:** `docs/codex-senior-developer-role`, prior HEAD `5b2fed196f05111b439c27ffb87dae5e713afc5a`, draft PR #9.  
**Current feature reference:** PR #5 `feat/windows-startup-status-window`, observed HEAD `2894b2c50a1347946425254deedb7be5449a16de` at planning, still DRAFT; no merge.  
**Other active branches:** PR #7 uninstaller, PR #8 compiled packaging, PR #10 display QA follow-up, all separate.

## Request

Replace the previous AI team operating procedure. Claude remains the engineering lead and **designs tests**. Codex acts as the **default independent test engineer**, not the author of the change being certified. Codex executes Claude's tests and can identify/add further meaningful test cases. Codex sends the unfiltered report and actual evidence **back to Claude**. Claude reviews/corrects and decides whether the candidate is sufficiently ready to **submit to Gemini for final independent audit**. Project Owner alone approves merge/release. Codex may act as temporary Senior Developer **only when explicitly reassigned**, with no self-certification of its own code.

"Whole rebuild" here means the **coordination and QA procedure**, **not** rewriting LotRadar or its installer.

## Current behavior (source inspected)

1. Proposed `AGENTS.md` and `docs/ai/CODEX_SENIOR_DEVELOPER.md` in draft PR #9 previously made Codex primarily an implementation backup and peer reviewer; no Claude-designed-test → Codex → Claude → Gemini evidence gate.
2. PR #5 contains a native Windows Forms startup window, guarded batch/PowerShell bootstrap and installer, independent local/OneDrive QA kit and test scripts. Latest evidence summary in `docs/startup/CODEX_IMPLEMENTATION_HANDOFF.md` reports Windows 11 full-launch 69 PASS/0 FAIL/0 SKIP and Python 116 OK on **local** candidate `6ebafe26f915568b2c8094f2392a01e66631c33d`; its reported Git tree equals **published** `7194e6c7575835eedd5f7f91ebef5644e929ec4f`. The latest PR #5 HEAD is additional documentation only. These are developer/tester **reported claims**, NOT Gemini approval.
3. Gemini previously requested individual source patches and private sanitized logs/screenshots; the code comparison and acceptance file links have been posted, but raw private evidence is not in public Git. Current PR #5 is **DRAFT** and has no final submitted Gemini audit.
4. PR #10 tracks actual missing 1366×768/1920×1080/3440×1440 resolution/DPI combinations, physical-key/expanded-control and Windows 10 coverage. Deferral does not equal PASS or waiver.

## Required behavior

The authoritative sequence is **Architect → Claude implement + design test plan → Codex independent execute + extend tests → Claude triage + READY/HOLD decision → Gemini final independent audit → Owner merge/release authority**. If Codex finds a defect, Claude fixes or documents it, Codex retests the exact corrected source tree, then Claude may refer to Gemini. A Gemini finding cycles back to Claude/Codex.

Claude's READY means **"ready for Gemini to independently audit," never "ready to merge."** All Codex failures, test deviations and raw evidence must travel with the referral to Gemini. Claude cannot hide unfavorable results, approve a regression unilaterally, declare a SKIP as passed, or overrule the Owner's release authority. Codex can keep executing an already-issued plan while Claude has no usage; the readiness gate waits for Claude or a formal Owner-appointed alternate. No automatic background testing is implied.

## Relevant architecture and files

**Governance documentation owned by PR #9:**
- `AGENTS.md` — repository-wide role and safety instruction to assistants.
- `docs/ai/QA_WORKFLOW.md` — authoritative pipeline, test independence, gates, defect cycle and artifact identity.
- `docs/ai/CODEX_INDEPENDENT_TESTER.md` — independent tester rules and code contribution constraints.
- `docs/ai/CODEX_SENIOR_DEVELOPER.md` — legacy redirect; implementer mode is exceptional.
- `docs/ai/CLAUDE_TEST_PLAN_TEMPLATE.md` — required design inputs and acceptance for execution.
- `docs/ai/CODEX_TEST_REPORT_TEMPLATE.md` — actual commands, evidence, gap analysis and triage.
- `docs/ai/ARCHITECT_HANDOFF.md` — this implementation plan.

**Existing product/test interfaces, for PR #5 pilot only:**
`startup/Show-LotRadarStartup.ps1`, `Marketplace Bootstrap.ps1`, `Launch Marketplace Scanner.cmd`, `installer/Install-LotRadar.ps1`, `scripts/build_installer.py`, `scripts/build_qa_kit.py`, `tests/test_startup_window.py`, `tests/test_qa_kit.py`, `tests/test_windows_process_cleanup.py`, `tests/windows/Test-LotRadarInstaller.ps1`, `tests/windows/qa-kit/Run-QAKit.ps1`, `docs/MANUAL_ACCEPTANCE.md`, `docs/startup/VISUAL_DESIGN_APPROVAL.md`, `docs/startup/CODEX_IMPLEMENTATION_HANDOFF.md`.

## Implementation plan

1. In **existing draft PR #9** replace the previous primary Codex development mandate with a **tester-first** operating contract, without deleting commit history or introducing a conflicting governance branch.
2. Write the canonical `QA_WORKFLOW.md` with named G0–G5 gates and clear candidate/harness/package provenance, mandatory neutral treatment of failures, and strict single-writer/independence separation.
3. Add a Claude test-plan template with test IDs, setup/cleanup, expected assertions, negative and integrity cases, environment feasibility and evidence obligations; **Claude authors the instantiated plan for each real feature**.
4. Add Codex independent test engineer charter and test report template. Allow Codex to add tests on isolated `test/<feature>` branches, recording additional test commits; prohibit unsanctioned edits to production code under test.
5. Add a Claude readiness report requirement. Claude responds to all failures/recommendations, requests new evidence where required, and chooses **HOLD** or **READY FOR GEMINI** on exact verified SHA. Gemini receives complete prior report and raw evidence.
6. Notify PR #5 of the newly requested pilot procedure. Its already-produced Codex results and earlier Gemini findings remain valid **as historical evidence tied to their source SHAs**, not as a new current independent certification. Claude must produce a test plan and disposition, and Codex rerun any necessary frozen tests before new Gemini final audit.
7. Validate GitHub docs and cross-links; publish documentation-only changes to draft PR #9, keep PR #5/7/8/10 source code unchanged. Ask for Owner governance review before merging PR #9 into main.

## Protected functionality (must not break)

- All approved `main` app modules and API/server ownership, bootstrap locks, install/rollback safeguards, OneDrive source-cloud-tag vs destination link controls, Chrome Reader pairing, scanner behavior, Facebook drafts, VIN/stock and SQLite identity, photo originals and order.
- Private `%LOCALAPPDATA%\MarketplaceScanner\data` inventory/photos/drafts, personal browser sessions, Desktop/Start-menu shortcuts, configuration, tokens, original brand assets and secrets.
- Existing historical signed-off test evidence and prior architecture decisions, clearly dated and tied to commit. Do not mislabel older evidence as current.
- PR #5's minimal logo + blue live bar + four truthful stages, not fantasy wallpaper.
- User's sole final authority for merges/releases and any explicit platform/safety waiver.

## Acceptance criteria

| ID | Measurable condition |
| --- | --- |
| GOV-01 | Repo guidance assigns Claude Lead Programmer **and test designer**, Codex **default independent tester**, Gemini **final independent QA**, Owner **merge authority**. |
| GOV-02 | A written G0–G5 flow requires Codex to send results to Claude **before** Gemini submission. |
| GOV-03 | Claude's READY/HOLD includes exact implementation/test harness/manifest SHAs and evidence disposition; READY is explicitly not release approval. |
| GOV-04 | Codex can add test-only cases independently with IDs and branch SHA without changing production code; if assigned development duty, it cannot independently approve its own code. |
| GOV-05 | All PASS/FAIL/SKIP/NOT RUN/BLOCKED are visible; no suppressing unfavorable results or carrying old-SHA PASS to changed code. |
| GOV-06 | Tests on Windows GUI, OneDrive, private production branding and source/package validation demand actual evidence; missing items remain outstanding. |
| GOV-07 | No PR #5, #7, #8, #10 product implementation, installer, user data or private branding is changed by governance PR #9. |
| GOV-08 | PR #9 remains draft; no unapproved merge, force push, release or deployment. |
| GOV-09 | Test-plan and execution-report templates are concrete enough that Claude/Codex can run the PR #5 pilot without guessing what PASS means. |
| GOV-10 | PR #5 is notified of new evaluation order; Gemini may still report urgent safety findings immediately, but no final ready claim bypasses Claude's readiness review. |

## Required tests and verification for *this docs-only change*

1. GitHub readback: fetch each new/updated file at PR #9 HEAD; ensure all relative links resolve and references do not point to deleted docs.
2. Compare PR #9 changed-file list to `main`: documentation files only (`AGENTS.md`, `docs/ai/*`); any production code difference FAIL.
3. Audit authority consistency: find no surviving text describing Codex as **default** production implementer or Gemini as the tester who receives results before Claude. Historic PR comments remain historical, explicitly superseded.
4. Pilot **planning check** against PR #5: verify existing `G1–G10`, E1–E6 and OneDrive/risk test families can be represented without lying about previous 69/116 counts, current Gemini evidence or unrun display checks. Do not execute a live Windows test by merely checking docs.
5. Where execution is impossible, mark **NOT RUN**; do not record the new workflow as technically validated until a real feature passes through Claude → Codex → Claude → Gemini.

## Risk areas

- **Loss of independence:** Codex fixes the production code then certifies that same change. Mitigation: distinct assignment and tester, clear change provenance and Gemini audit.
- **Lead bottleneck / usage exhaustion:** Claude unavailable after Codex tests. Mitigation: safe HOLD with report preserved; Owner can formally nominate temporary lead; never claim an unattended handoff.
- **Suppressed failures:** Lead could cherry-pick passing evidence. Mitigation: Codex publishes a complete immutable report; Gemini receives it without curation.
- **Test harness itself changes:** Codex-added tests shift branch HEAD. Mitigation: record frozen app SHA and separately versioned harness SHA; rerun after adoption.
- **Unsafe Windows live test:** Powershell/OneDrive operations may alter shortcuts, leave servers or install dependencies. Mitigation: explicit consent, synthetic/isolated fixtures, non-admin guards, saved hashes and cleanup verification.
- **Cloud/CI confusion:** GitHub comments and Codex subscription do not guarantee self-executing tests, Windows runners or private artifact access.
- **Fragmentation:** Separate PR #5 and governance PR #9 may diverge. Mitigation: immediate PR #5 coordination comment + later Owner-approved governance merge.

## Git instructions

Continue documentation branch `docs/codex-senior-developer-role` in **existing DRAFT PR #9**, based on latest approved `main`; do not amend, force-push, rebase unrelated branches or merge `main`. Architecture-only edits, no production code. Owner must explicitly authorize merge after review. Do not use a Gemini audit or Claude readiness result as permission to merge or release.


## Owner-approved addendum — Copilot automated discovery and Chief-created new work

**New request:** The Owner already has GitHub Copilot working on its own automated issue-finding task. Copilot should independently surface suspected problems, and the **Chief Architect creates new engineering work** from validated findings.

**Current behavior:** The draft workflow documented Claude/Codex/Gemini handoffs, but did not define Copilot as a formal intake stage or require source verification, duplicate checking and scoped issue creation.

**Required behavior:** Copilot generates **candidate reports**; the Chief inspects current approved main, relevant PR HEAD, source references and evidence, checks open issues/PRs for duplicates, then rejects false positives or creates **one scoped backlog issue per verified root cause** (or an investigation-only item if unproven). Architecture work orders use `docs/ai/ARCHITECT_WORK_ORDER_TEMPLATE.md`; Copilot candidate contract is `docs/ai/COPILOT_AUTOMATED_DISCOVERY.md`. Owner controls priority and authorizes implementation. Keep G0–G5 testing and final QA unchanged.

**Relevant files:** `AGENTS.md`, `docs/ai/QA_WORKFLOW.md`, `docs/ai/COPILOT_AUTOMATED_DISCOVERY.md`, `docs/ai/ARCHITECT_WORK_ORDER_TEMPLATE.md`, this document. **Do not touch:** `core.py`, `server.py`, photos, database, Chrome Reader, Facebook modules, `startup/`, `installer/`, `tests/` or other feature PRs.

**Implementation steps:** (1) Update team roles; (2) state existing Copilot automation as a distinct source of candidate findings (no claimed new scheduler); (3) require exact-SHA validation and deduplication; (4) define verified/investigation/duplicate/false-positive disposition and Architect work-order fields; (5) require Owner approval before Claude begins new implementation; (6) preserve Codex independent test, Claude readiness, Gemini QA and Owner-only merge decision.

**Acceptance criteria:** All documents link correctly; Copilot reports are explicitly untrusted until verified; Chief is authorized to create new backlog work but not to order unapproved production changes; duplicates cannot create parallel writers; issue creation is not falsely described as triggering code work; no private logs/data publicly exposed; every actual code change still flows through Claude -> Codex -> Claude -> Gemini -> Owner.

**Required tests for this docs-only addendum:** Fetch all modified docs from PR #9 and verify exact Git blobs, check links, compare changed paths to approved main and confirm *no product/test files modified*, confirm no invented GitHub automation has been enabled. No executable test pass is claimed.

**Risks:** Copilot false positives, issue spam, old-SHA claims, concurrent edits to same feature, accidental public disclosure, and treating issue creation as implementation permission. Mitigate with evidence, dedup, investigation-only statuses, sandbox/privacy rules and Owner approval.

**Git:** Continue draft PR #9 `docs/codex-senior-developer-role`. Do not merge to `main`, release, or change another branch.


## Setup clarification — Copilot Free and repository visibility

GitHub was checked during Copilot setup: `iDarknesskiller/LotRadar` is **public**, and GitHub's Copilot cloud automations require a paid Copilot plan plus a **private/internal** repository. The Owner's prior description of an automated Copilot task is an unverified statement about a possibly different workflow, not confirmation that native Copilot cloud automation is active. Do not configure, activate or promise it on Copilot Free. A read-only manual Copilot Chat scout prompt is available in `docs/ai/COPILOT_FREE_SCOUT_PROMPT.txt`; its repository instructions are in `.github/copilot-instructions.md`. GitHub's CodeQL/Dependabot security scanning may be activated separately as a free public-repository alternative, only with Owner choice and appropriate settings access. No production files, schedules or actions workflows were changed as part of this clarification. Preserve Owner-only work assignment and merge authority.
