# LotRadar contributors and development governance

LotRadar is directed by its **Project Owner**, who defines requirements and has final authority over releases and changes to `main`.

This document acknowledges both engineering and review contributions to the project. **AI assistants do not acquire separate GitHub identities from these acknowledgements.** Git commits appear under the account used to make them; the roles below are a record of work and responsibility, not an assertion of GitHub-authored commits.

## Project roles

| Contributor | Role | Responsibilities |
| --- | --- | --- |
| Project Owner | Product owner and final release authority | Sets priorities, accepts or rejects risk, approves changes and merges. |
| **ChatGPT (OpenAI)** | **Chief Architect and development coordinator** | Inspects approved `main`, designs changes, defines scope and protected functionality, prepares `ARCHITECT_HANDOFF.md`, specifies tests and acceptance gates, reviews audits, and records release decisions. |
| **Claude (Anthropic)** | **Lead Programmer** | Implements approved plans on feature branches, maintains code and installer tooling, executes applicable tests, and returns implementation evidence. |
| **Gemini (Google)** | **Independent QA reviewer** | Reviews proposed diffs and evidence, reports regressions/security concerns, identifies untested requirements, and issues audit verdicts. |

Additional tools, including GitHub Copilot, may assist with review; they are not credited with work unless their contributions were actually used and recorded.

## Recorded contribution: installer/bootstrap parity

- **Pull request:** [#1, installer/bootstrap parity](https://github.com/iDarknesskiller/LotRadar/pull/1)
- **Reviewed implementation commit:** `c2a94644f3cb6f2dc1d371dc2c7887721ec38302`
- **Owner-authorized merge commit:** `b9e843111ce1ed39f7d4003dd39c06eb75724325`
- **Scope:** Windows launcher parity, installer packaging, verification, rollback and concurrency protections, documentation, and test harnesses.

Contributions in this cycle:

- **ChatGPT:** Compared the initial installer archive with GitHub `main`; identified missing installer packaging and private-asset boundaries; prepared architectural handoffs for Claude; reviewed successive Gemini audits and GitHub diffs; maintained acceptance gates and documented owner waivers; and carried out the owner-authorized merge of PR #1.
- **Claude:** Implemented the launcher and installer changes, reproducible package builder, Windows and Python test harnesses, release documentation, and evidence helper; supplied package provenance and test evidence.
- **Gemini:** Independently audited the implementation, documented uncovered Windows cases and security gaps, reviewed corrective cycles, and reported a PASS with explicitly documented owner waivers.
- **Project Owner:** Set scope and priorities, exercised manual Windows 10 workflows, accepted the documented Windows 11/OneDrive/R3 test waivers, and explicitly approved the merge.

**Evidence boundary:** Test counts and manual outcomes were reported through the project handoffs; the GitHub source review alone is not proof of executing tests. The release was labeled **"Windows 10 verified; Windows 11 untested."** The production installer and private branding assets are not published in this repository.

## Rules for future contributions

1. Begin from the latest approved `main` commit and record its SHA.
2. Define behavior changes, affected files, protected functionality, acceptance criteria, risks, and required tests in `ARCHITECT_HANDOFF.md`.
3. Implement and review work on a feature branch; preserve existing user databases, photos, drafts, credentials, and private assets.
4. Record tests actually executed, test environments, results, skips, and waivers. Do not equate an unexecuted check with a passing check.
5. Obtain an independent review and **explicit Project Owner approval before merging into `main` or publishing release artifacts**.
6. Acknowledge work accurately: separate planning, programming, testing, and approval rather than attributing everything to the GitHub account that performs the merge.

This document's initial text was drafted by **ChatGPT acting as LotRadar Chief Architect**, for review through the same feature-branch workflow as any other change.
