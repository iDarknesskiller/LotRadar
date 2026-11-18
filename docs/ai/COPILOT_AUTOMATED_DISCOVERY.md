# Copilot Automated Discovery -> Chief Architect Triage

**Status:** Proposed project governance on draft PR #9. This file is **not** a GitHub Actions configuration or proof that Copilot automation is running. The Project Owner reports that GitHub Copilot already performs its own automated issue-finding work. Preserve that automation's existing setup, permissions and schedule; do not add or enable a second scheduler without authorization.

## Role and authority

**GitHub Copilot** is the independent, automated *issue scout* for LotRadar. It proactively inspects repository code and open PRs and raises *candidates*: suspected bugs, performance weaknesses, maintainability debt, security/data hazards, missing regression coverage and conflicts between branches. A Copilot suggestion is **untrusted input for verification**, not a proven defect, approved feature, test pass or permission to modify production.

**ChatGPT Chief Architect** owns issue *triage and work creation*. Upon receiving Copilot findings, the Chief re-fetches latest approved `main` and pertinent PR SHAs, checks the actual code, searches existing issues/PRs for duplicates, assesses impact and scope, then creates a precise **new backlog item / GitHub issue and `ARCHITECT_HANDOFF.md` task for Claude** only when the claim is substantiated or explicitly framed as an investigation. New work can be drafted into the backlog without treating it as authorized implementation. The **Project Owner sets priority and approves starting coding**, merge/release and any waiver. No agent automatically merges.

## Discovery and work-intake loop

```text
Copilot scheduled issue discovery (existing Owner-configured task)
    -> COPILOT_FINDING.md or existing GitHub issue/PR comment
    -> Chief checks SHA, actual code, duplicates, impact and evidence
    -> Reject false positive / request evidence / create scoped work item
    -> Owner chooses priority and approves implementation
    -> Chief issues exact ARCHITECT_HANDOFF.md to Claude
    -> Claude implements + designs test plan
    -> Codex independently tests and can add tests -> reports to Claude
    -> Claude fixes/triages -> READY FOR GEMINI (or HOLD)
    -> Gemini independently audits -> Owner approves merge/release
```

**Important operational limitation:** A PR comment or GitHub issue does not itself automatically awaken ChatGPT. The Chief executes this triage when invoked via chat, a deliberately configured automation with supported access, or explicit manual handoff. Do not claim ongoing real-time supervision if no integration exists. No invented GitHub labels, CI check statuses or automatic Copilot permissions.

## What Copilot must produce (candidate format)

Use one **candidate** per independently reproducible problem, ideally in `COPILOT_FINDING.md` or a structured GitHub issue:

- **Identifier / title**: concise, unique; issue/PR URL if created by automation.
- **Observed repository and immutable `main`/PR commit SHA**. Never report a moving branch as a frozen source.
- **Category**: correctness, performance, security, data integrity, reliability, packaging, accessibility, test gap, docs.
- **Relevant file and line/function** with source pointer; affected app surface and environment.
- **Observed behavior / reproducible evidence** or state clearly **HYPOTHESIS - NOT REPRODUCED**.
- **Expected behavior** based on actual documented LotRadar requirements.
- **Minimal reproduction**, preconditions and harmless fixtures; no real production data or Facebook publishing.
- **Severity suggestion** P0/P1/P2/P3 and confidence HIGH/MEDIUM/LOW; these are suggestions, not final classification.
- **Performance issues** must cite measured baseline, method, size, environment, and target; no "slow" without evidence.
- **Security issues** report privately if exploit detail/secret/user information is sensitive; public finding contains only sanitized description and affected area.
- **Potential false positives/limitations** and candidate regression tests.
- **Suggested solution** as a hypothesis, not an order to rewrite code or add dependency.
- **No automatic production patch**; draft code branches, if configured, remain isolated and unmerged until Architect/Owner review.

Copilot must not fabricate benchmarks, test execution, affected users or reproduction; do not treat generated tests as passed without execution.

## Architect's intake decision (mandatory)

For each candidate, record:

1. **Revalidate source:** inspect current approved `main` SHA, relevant feature PR HEAD, app version/build manifest and exact affected file/function. If a candidate targets an old SHA, mark stale or re-check.
2. **De-duplicate:** search open/closed issues, draft PRs, code review threads and previously accepted handoffs for same underlying root cause. If covered, link existing issue and mark **DUPLICATE**; do not create parallel coding requests.
3. **Substantiate:** reproduce safely or establish a clear source-level reason; record **VERIFIED**, **NEEDS INVESTIGATION**, **FALSE POSITIVE**, **STALE/RESOLVED**, **DUPLICATE**, or **OUT OF SCOPE**.
4. **Risk/priority:** classify P0 (urgent security/data corruption), P1 (serious broken core functionality), P2 (normal bug), P3 (minor polish/maintenance). The Owner alone selects what is implemented next. P0/P1 warn Owner promptly; no unaudited auto-fix.
5. **Scope:** identify affected vs protected files, probable root cause and uncertainty, minimal implementation plan, source behavior, expected behavior, acceptance criteria, regression/integrity/security tests.
6. **Create work:** for VERIFIED issues create **one** scoped GitHub issue and an Architect handoff linked to source findings and intended draft feature branch; for NEEDS INVESTIGATION create an **investigation-only** work item, not an unproven bug-fix directive. The Chief may populate the backlog, but does not authorize code deployment or merging.
7. **Owner approval:** place verified/new issue into a proposed priority queue, request Owner's approval for beginning implementation or changing priority; do not silently interrupt Claude's active task.
8. **Feedback loop:** close the candidate as false positive/duplicate or attach final fixed PR, Gemini audit and Owner release evidence. Copilot can rescan changed code but cannot declare its earlier finding closed solely by its own suggestion.

## Backlog fields and issue template

```md
# [P1/P2/P3] Concise problem title
Discovery origin: Copilot automation [link and execution time]
Architect triage: VERIFIED / NEEDS INVESTIGATION
Approved main SHA: ...
Affected PR HEAD (if relevant): ...
Current observed behavior: ...
Required behavior: ...
Evidence and minimal reproduction: ...
Root cause hypothesis vs verified cause: ...
Affected files / protected files: ...
Risk: security, data, Windows, OneDrive, UI, performance, concurrency
Acceptance criteria: AC-01, AC-02 ...
Required tests: TEST-01, TEST-02 ...
Regression data and rollback safeguards: ...
Duplicate check: links/search results ...
Owner priority / implementation authorization: PENDING or linked decision
Claude branch assignment: NOT ASSIGNED until authorized
```

## Queue hygiene and anti-spam

- Do not open duplicate issues for the same root cause or turn one minor lint finding into multiple tasks.
- For low-confidence scans, aggregate evidence requests in a **triage digest** rather than creating implementation work.
- Limit repetitive low-value findings; include severity, confidence and affected user impact so the Owner can prioritize.
- An open draft PR addressing an issue means link the PR rather than assigning a competing writer; no conflicting concurrent edits.
- Keep separation between Copilot detecting, Chief validating, Claude implementing, Codex executing tests, and Gemini final auditing.

## Protected data and permissions

Never expose customer identities, VIN/phone combinations, local SQLite, vehicle photo originals, customer drafts, private branding, tokens, login sessions, personal paths or unsanitized logs in automated public issues. Protect `%LOCALAPPDATA%\MarketplaceScanner\data`, Windows installer/reparse safety, OneDrive local-only storage, single localhost server/locks, and real user browser sessions. No destructive "verification", no unattended installation, no GitHub `main` merge or force push. Owner makes release decisions.
