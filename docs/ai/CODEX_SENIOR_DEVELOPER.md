# Codex Senior Developer — Historical Role Note

**Superseded by the Project Owner's updated workflow.** Codex's **default role is now Independent Test Engineer**, not code author, for changes implemented by Claude.

See:
- [`CODEX_INDEPENDENT_TESTER.md`](CODEX_INDEPENDENT_TESTER.md) — current detailed role.
- [`QA_WORKFLOW.md`](QA_WORKFLOW.md) — Claude designs tests → Codex independently executes/extends → Claude reviews and gates → Gemini final independent audit → Owner merge/release decision.
- [`ARCHITECT_HANDOFF.md`](ARCHITECT_HANDOFF.md) — request, architecture, tests, acceptance and migration plan.

Codex retains the **ability** to serve as a Senior Developer for a *separate explicit Owner/Architect assignment* when Claude reaches a usage limit. Such Codex-authored production work is **not independently tested by Codex**, even if Codex runs developer tests itself; require a different independent QA person/agent and full evidence. One branch writer at a time; never edit `main` directly or merge without Owner approval.

**Historical baseline:** Approved main was `bf61207a21999c8ff256b08c0d17650193e3835f` when role changed. Fetch the actual current SHA before work. The previous text of this document is available in PR #9 history, not the governing policy after this correction.
