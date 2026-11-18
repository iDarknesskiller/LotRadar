# ARCHITECT_WORK_ORDER.md — Chief Architect -> Claude

**Purpose:** Create precise engineering work *after* verifying a Copilot-discovered candidate or receiving a direct Owner request. New work is a scoped backlog proposal, not approval to merge or deploy.

## Intake and authority

- Problem title / unique work ID:
- Origin: COPILOT_FINDING / OWNER REQUEST / QA FINDING
- Copilot or issue URL and report date:
- Chief Architect's decision: VERIFIED / NEEDS INVESTIGATION / FALSE POSITIVE / DUPLICATE / STALE
- Project Owner priority and approval to start implementation: PENDING / approved reference:
- Main repository: `iDarknesskiller/LotRadar`
- Approved `main` SHA and version/manifest:
- Current relevant feature PR/branch SHA:
- Existing related issue/PR duplicates checked:
- Intended new feature branch (not created until assigned):

## Request

What the Project Owner wants and what verified Copilot evidence suggests. Distinguish **actual behavior** from conjecture.

## Current behavior and cause

Exact observed behavior, reproduction, code pointer, confirmed root cause **or explicitly hypothesis/investigation**.

## Required behavior

Objective change and boundaries; UI behavior, data/API semantics, performance threshold where measured.

## Relevant architecture

Affected modules and file paths; data flow, ownership, interaction with launcher/installer/Chrome Reader/Facebook/photos.

## Implementation plan (for Claude)

Numbered, scoped engineering steps; exact files expected to change, any migration/rollback; do not say simply "fix bug."

## Protected functionality / files NOT to change

List core app behavior, database/photo/draft integrity, branding, cloud guards, port/locks, Chrome/browser sessions and unrelated active PRs.

## Acceptance criteria

Numbered, independently measurable conditions tied to the request. For performance, use a measured comparison baseline and acceptable limits.

## Required tests (Claude will turn this into CLAUDE_TEST_PLAN.md)

Tests covering normal use, negative cases, concurrency, malformed input, security/privacy, synthetic data integrity, installer fallback/rollback, OS/GUI real hardware when relevant; label impossible environments BLOCKED.

## Risk areas

Race conditions, caching, migration, symlink/reparse points, OneDrive data leaks, browser automation, offline provisioning, regression and test-oracle weaknesses.

## Git instructions

Feature branch only; start from approved latest `main` unless continuing a specifically owned PR; no force-push, merge to main, release or branch deletion without Owner approval. One implementation writer at a time.

## Handoff destination

**Claude — Lead Programmer and Test Designer.** After coding, Claude produces frozen commit and `CLAUDE_TEST_PLAN.md` for Codex independent testing, reviews Codex's complete results, issues `CLAUDE_QA_READINESS.md`, refers to Gemini only when ready. Gemini audits independently and Owner alone decides release.
