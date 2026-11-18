# LotRadar QA Workflow — Claude → Codex → Claude → Gemini → Owner

**Team process proposal | Draft PR #9 | 2026-11-17**

## The core rule

**Claude designs the tests. Codex independently tests and may add more. Codex sends the full results to Claude. Claude decides whether the candidate is ready for Gemini's independent audit. Gemini audits the code and evidence. The Owner decides whether to merge/release.**

A release must not depend on one AI accepting its own claims. Preserve Codex's findings, including every FAIL, as first-class evidence. "Ready for Gemini" is not "approved for production."

## Independent Copilot discovery (before G0)

**GitHub Copilot** can investigate potential issues in parallel when invoked. The Owner previously described an automated task, but its availability has not been verified; GitHub Copilot Free cloud automations are unavailable for this public repository. Separate GitHub security scanning may be automatic without being Copilot agent automation. It can flag suspected bugs, performance bottlenecks, security/data risks and test coverage gaps, but findings are only **candidates**, not verified facts. See [`COPILOT_AUTOMATED_DISCOVERY.md`](COPILOT_AUTOMATED_DISCOVERY.md).

**ChatGPT Chief Architect** owns validation, de-duplication against open issues/draft PRs, severity/impact and creation of **new scoped backlog work** via [`ARCHITECT_WORK_ORDER_TEMPLATE.md`](ARCHITECT_WORK_ORDER_TEMPLATE.md). For substantiated claims create a verified issue; for uncertain findings create an investigation task; reject false positives. Owner decides which work is prioritized and authorized for Claude to start. Do not automatically interrupt an active branch.

After intake, the existing G0–G5 gates are unchanged: **Claude implements and designs tests -> Codex independently executes/extends -> Claude reviews and gates -> Gemini final independent audit -> Owner merge/release authority**. Copilot may inspect/follow up on fixes but does not replace Codex or Gemini. A GitHub issue or comment is not an automatic ChatGPT trigger without specifically configured automation.

## Gate-by-gate process

| Gate | Owner | Inputs | Required output | Promotion rule |
| --- | --- | --- | --- | --- |
| **G0: Scope** | ChatGPT Architect / Project Owner | approved main, request, current files/behavior | `ARCHITECT_HANDOFF.md` with exact SHA, acceptance/protected functions | Owner authorizes task and boundaries |
| **G1: Implementation & test design** | **Claude** | G0 handoff | feature commit(s), `CLAUDE_TEST_PLAN.md`, frozen candidate SHA + source/package manifest | no critical unaddressed developer findings; ready for independent test |
| **G2: Independent execution** | **Codex** | frozen code, Claude test plan, secure environment | `CODEX_TEST_REPORT.md` + individual raw sanitized JSON/TXT/screenshots; optionally test-only PR with new cases | complete independent report delivered to Claude, **including failures** |
| **G3: Lead triage** | **Claude** | entire Codex report, evidence, test additions and source changes | `CLAUDE_QA_READINESS.md` with **HOLD** or **READY FOR GEMINI**, exact candidate SHA, per-finding disposition | only READY goes to final Gemini audit; no automatic code merge |
| **G4: Independent final audit** | **Gemini** | frozen source, entire Claude plan, Codex evidence + report, Claude triage | `GEMINI_FINAL_AUDIT.md`: PASS/CONDITIONAL/HOLD/REJECT with findings and provenance | Gemini assesses risks independently; findings cycle back to Claude |
| **G5: Product approval** | **Project Owner** | all prior outcomes, risks and waivers | explicit merge/release decision | Owner alone authorizes merge to `main`; release separately authorized |

If Gemini finds a new issue, return to Claude for fixes and update candidate SHA. Codex independently retests affected test groups; Claude updates readiness; Gemini re-audits the new exact candidate. **Never reuse an old verdict by changing only the link.**

## Separation of duties

- Claude is the **Lead Programmer and Test Designer**, not the final QA auditor. Claude can add developer/unit tests, but must provide a complete test plan for Codex to execute and challenge.
- Codex is the **Independent Test Engineer by default**, not the author of the production change being certified. Codex may inspect source, execute Claude's tests, test manual UI with qualified environment access, add tests, harden fixtures/harness *on a test-only branch*, and file defects. Do not alter production implementation while claiming independence.
- **Codex-written tests are allowed:** codified independent checks, negative/security cases, boundary data, concurrency, race/cleanup, UI, caching and regression tests. Each must identify its origin, exact test harness SHA, safety setup, expected results and rationale. Claude decides whether to incorporate them; rejecting a test must be explained rather than silently dropped.
- **Codex as backup programmer:** explicit Owner/Architect switch to a separate task and single-writer branch. Codex-authored production code needs an independent party to certify; Codex may report self-tests but cannot label them independent.
- **Gemini is the separate final QA auditor**, not a rubber stamp. It can identify previously untested risks and request more tests. No Gemini review is auto-initiated by posting a GitHub comment unless the integration is actually configured.
- **The Owner is release authority**, including any explicit decision about untested Windows 10 or hardware configurations. No AI may independently waive a critical data-integrity or security requirement.

## Canonical version and evidence record

Each run must publish:
- repository and PR number, **approved `main` SHA**, exact frozen implementation SHA, **Git tree SHA** where useful, test-harness SHA if additional tests, `source_commit` from build manifest, package ZIP SHA256 and kit SHA256;
- OS/build, account privilege, Windows PowerShell/Python version, display resolution/DPI if applicable, development vs private-branded production build, network/OneDrive conditions and synthetic fixture IDs;
- test ID, actual command and arguments, expected and observed values, exit code, PASS/FAIL/SKIP/NOT RUN/BLOCKED, cleanup and before/after data/shortcut/lock hashes;
- raw **sanitized individual** logs, structured JSON and **window-only** screenshots with filenames/hashes and private sharing location. No reconstructed logs, cropped-out failures or raw customer details.

**PASS** = executed and observed assertion true. **FAIL** = executed and assertion false. **SKIP** = intentionally not executed due to test condition, with reason. **NOT RUN** = not attempted. **BLOCKED** = cannot run due to missing platform/asset/permission or unsafe environment. An old SHA PASS remains historical evidence only and must not be reused as current candidate PASS without a traceable unchanged-code justification accepted by reviewers.

A report claiming 69 PASS is not 69 raw passed results. Store the actual per-case results and make them available to Gemini, including any negative and intermediate failures.

## Minimum test-design contract for Claude

Claude must instantiate [`CLAUDE_TEST_PLAN_TEMPLATE.md`](CLAUDE_TEST_PLAN_TEMPLATE.md) for each feature, written **before** independent execution:
- affected and protected systems, unit/integration/Windows/manual categories, explicit test IDs and independent expected results;
- required negative cases, failure injection, offline/timeout, idempotent retry, resource cleanup, privacy/data integrity and rollback as relevant to scope;
- **can-run vs cannot-run** environment matrix (do not ask a Linux-only agent to sign off Windows visual DPI);
- evidence requirements, authority for installing dependencies, safe synthetic test data and exact launch commands;
- Gate G2 stop conditions and required fresh reruns after code/test changes.

Codex may propose additional tests even when all Claude tests pass. Claude must review the additions and explain any rejected critical test. If tested code or merged test harness changes, assign a new run; never use a previous report on different bytes.

## Claude's G3 decision protocol

For each FAIL, SKIP, BLOCKED, NOT RUN and additional Codex test:
1. Reproduce or verify provenance; identify relevant changed function/line and user impact.
2. Choose: **FIX**, **RETEST**, **ADD TEST**, **ACCEPT WITH OWNER-APPROVED WAIVER** (only when appropriate), or **HOLD**.
3. Give an explicit rationale and link to test evidence. Critical data loss, security and unexplained installed-program or user-file mutation force **HOLD**.
4. If fixing code, update candidate SHA, rebuild package, and ask Codex to rerun affected suites and any mandatory cross-cutting regression checks.
5. Do not send only the favorable subset to Gemini. Send the complete test report, previous failing attempts, raw sanitized artifacts, plan and triage. Provide a signed-off `CLAUDE_QA_READINESS.md` with actual `READY FOR GEMINI` or `HOLD`.

Claude's readiness decision **routes a candidate to audit**. It does not overrule Codex's recorded findings, Gemini's judgment or the Owner's approval.

## Safe testing constraints

Before a destructive-looking or live test, use read-only preflight to identify existing LotRadar, local inventory, photos/drafts, existing server/port 8765, Desktop shortcut and OneDrive roots. Only operate in an ownership-proven synthetic sandbox with explicit user consent for any downloads/installation/network activity. No public repo private branding, no customer data, no live Facebook posting, no global taskkill or killing Chrome/Edge by URL; no deleting folders merely because they share a name prefix. Verify snapshots/hashes, port/lock release and shortcut restoration; explain any orphaned browser tab without touching personal sessions.

Do not infer install/production passes from DEV-NOBRANDING previews or graphical Windows evidence from Linux unit tests.

## Pause, resumption and disagreement

- Claude usage limit: Codex may **run tests and publish a complete report** on the already approved/frozen candidate and plan. G3 remains **WAITING FOR CLAUDE** unless the Owner formally assigns an acting lead. Not an automatic handoff or background agent.
- Unavailable Windows hardware: Codex marks relevant tests **BLOCKED** and supplies source-level review separately; Claude/Owner decide how to obtain environment or limit release scope explicitly. Gemini sees unresolved coverage.
- Disagreement on severity: record both views with evidence; Architect mediates technical scope, Gemini independently assesses final audit, Owner decides acceptance. Nobody deletes dissenting findings.

## Immediate PR #5 pilot

PR #5 current at this design review: `2894b2c50a1347946425254deedb7be5449a16de` (verify anew). `docs/startup/VISUAL_DESIGN_APPROVAL.md` is final Owner-approved minimal logo + blue live progress + four stages. Read `docs/startup/CODEX_IMPLEMENTATION_HANDOFF.md` and `docs/MANUAL_ACCEPTANCE.md`.

**Do not erase existing work.** Claude first writes a test plan that acknowledges reported 116 Python and 69 Windows passes on local `6ebafe2`, the reported corresponding published tree `7194e6c`, prior E1–E6/OneDrive results at earlier commits, the raw logs still requested by Gemini, and the outstanding G10 physical keyboard E3, full private-branding installer, selected DPI/resolution matrix and Windows 10 coverage. Codex then checks provenance, runs/re-runs feasible tests independently and adds failure-oriented tests where helpful. Claude decides HOLD or READY FOR GEMINI with the full evidence pack. Gemini's final QA request already posted can be reused after G3, but **do not claim it is completed or Gemini was triggered**. PR #10 records display coverage left for an explicit Owner decision; no pass by deferral.
