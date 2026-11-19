# ARCHITECT_HANDOFF: public-branding packaging integration

To: Claude, Lead Programmer
From: LotRadar Chief Architect
Date: November 19, 2026
Owner objective: publish the supplied LotRadar logo/icon and business card, and ensure application branding can use the approved assets.

## Identity and current behavior

Baseline main 4e2451fb7fb4252deed0b0b28d5bdf3a21bb446b (PR5 merge). Recheck main, target PR HEAD and sole writer before implementation. Publication assets are documented in PUBLIC_BRANDING.md with exact hashes and public-disclosure approval.

VERIFIED: scripts/build_installer.py reads assets only through --asset-dir; production requires business_card.png, dedication.jpg, lotradar_logo.png and LotRadar.ico, and rejects tracked nonignored in-repository asset inputs. load_committed_source rejects unknown tracked paths outside its exclusions. UI already loads branding/lotradar_logo.png and LotRadar.ico when installed. Publishing files under docs/ avoids changing payload rules but does not make a checkout/package use them.

Root cause: prior build policy treats all branding as private external input. Owner has now approved a narrow publication exception for the supplied files. dedication.jpg remains external/private; production completeness must not be silently weakened.

## Ordering and scope

Publication is assets/documentation only. Do not start packaging implementation before E3 PR #16 is resolved or Owner explicitly changes priority. This handoff defines the proposed next integration; it is not permission to bypass that gate, alter main or merge/release. Owner must authorize the concrete integration assignment after E3.

Claude should inspect exact builder source and propose a minimal, explicit committed-asset input mechanism. Preserve external --asset-dir support and define precedence visibly; do not replace a supplied external logo silently or silently substitute missing production dedication. Require clean-tree provenance and exact manifest hashes. Preserve DEV fallback when assets are intentionally absent and production fail-closed behavior for any required missing/corrupt asset.

Potential edit targets after authorization: scripts/build_installer.py, narrowly affected packaging tests, docs/INSTALL.md, and only necessary ignore/allowlist entries. Runtime UI should not need a redesign. Do not touch server/core, photo selection/export order, Facebook drafts, inventory/database, Chrome Reader, bootstrap/locks, installer rollback or live private asset folders. Current public-assets path is documentation storage; design any migration as a reviewed change, not an untracked local copy.

## Acceptance and tests

- AC-01: Fresh clean committed-source build uses exactly the Owner-approved public bytes under the chosen documented mechanism; package manifest identifies their path/hash and source commit.
- AC-02: External override precedence is explicit and tested; missing/corrupt logo/card/icon and unavailable dedication fail or fallback exactly as documented, never silently bypassed.
- AC-03: Production still requires the full four-asset set; dedication and unrelated private files never enter public Git. No privacy exception extends beyond the approved files.
- AC-04: Startup/sidebar logo, shortcut/favicon icon and synthetic photo export are verified on exact candidate; business card first, dedication next, original photos and selection order unchanged. Earlier PR5 package audit is historical for these different bytes.
- AC-05: Header/IHDR/ICO directory validation, transparent RGBA requirements, manifest byte/hash checks, deterministic package output, DEV fallback, unknown-file rejection and clean-tree checks remain meaningful. Author targeted tests; execute only under the concrete approved scope.
- AC-06: Claude plan -> frozen candidate -> independent Codex results/raw evidence -> Claude triage/readiness -> Gemini -> separate Owner merge/release decisions. No new-SHA PASS by inheritance.

Risks: supplied PNG color mode/dimensions, 256px icon compatibility, changed asset precedence, dedication disclosure, package allowlist weakening, branding overlay changing originals, and accidentally overwriting live private assets. Use synthetic fixtures and isolated packages; no live data migration or posting.

Git: continue this publication branch only if Owner confirms Claude ownership for integration; otherwise a separately assigned branch based on approved main. No force/reset/push/merge/release without applicable authorization. Chief did not contact Claude or claim receipt.
