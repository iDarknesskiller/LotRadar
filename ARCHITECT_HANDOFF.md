# ARCHITECT_HANDOFF.md

**To:** Claude — Lead Programmer  
**Project:** LotRadar / Out of Stock Facebook Cleanup  
**Status:** Architecture handoff; implementation not yet authorized for merge  
**Source:** approved `main` at `a52bf1d8bcc88a740267bfa5c0226beb4587e67a` (2026-11-19)  
**Branch:** `feature/outstock-facebook-cleanup`  
**Version:** README calls repository a development baseline; server identifies as `MarketplaceScanner/1.0`. No separate release version established by this inspection.

## Request
The Project Owner wants the Out of Stock workflow to automatically remove Facebook Marketplace listings when safe and supported, or, failing that, make removing the corresponding Facebook posts exceptionally easy. Scope is Facebook post lifecycle, not deletion of vehicle inventory or media.

## Current behavior (confirmed from main)
- `index.html` already labels the section **Out of stock & FB cleanup**, includes **Recheck Out of Stock** and local **Trash**.
- `app.js` renders out-of-stock cards with **Open Facebook** and conditional **Move to Trash**. A separate **Delete listing** control explicitly moves the *local tracking record* to 30-day Trash; it does **not** delete the Facebook post. This naming is misleading.
- `server.py` implements `/api/recheck-outstock`, `/api/listing-trash`, `/api/action` actions `trash_cleanup_listing`, `trash_listing`, `restore_listing`, and `complete_facebook_cleanup`.
- `core.py:1241-1270` calculates `cleanup_status`, `probable_out_of_stock`, and `can_trash`. `can_trash` requires both the tracked Facebook link and all recorded dealer links to have outcome `unavailable`. This is a **local archival eligibility** predicate, not proof of remote deletion or even necessarily a sold vehicle.
- `core.py:1272-1300` archives a draft into `listing_trash` for 30 days, unlinks tracking, and leaves Facebook unchanged.
- `core.py:1302-1338` already supports a user attestation that the Facebook post was removed, checks the expected listing ID, then archives locally. Its current UI exposure needs verification.
- `facebook_auto.py` is explicitly a bounded, read-only, user-requested listing-check queue. `chrome-extension/facebook_reader.js` reads listing information. No verified Facebook deletion API or remote deletion implementation was found in the inspected paths.
- `feed_sync.py` expressly refuses to treat failed feeds or incomplete snapshots as proof of removed stock.
- Latest main merge is PR #18, LR-011 branding/photo-preview. Existing PR #16 remains open according to main commit message.

## Required behavior
1. Show **dealer inventory status**, **Facebook listing status**, and **local tracking status** as separate concepts.
2. Provide a primary **Open Facebook to Remove** action for each linked out-of-stock candidate; open the *exact saved listing ID*, never a search or guessed URL.
3. Provide a **I've removed it on Facebook** confirmation flow, explicitly showing vehicle VIN, listing ID and URL. Recheck expected listing ID server-side before local archival, using the existing `complete_facebook_cleanup` behavior.
4. Rename ambiguous **Delete listing** / **Move to Trash** actions to **Remove from LotRadar (Facebook unchanged)** wherever applicable. Never claim a Facebook post was deleted after local archival.
5. Preserve unresolved listings in a visible cleanup queue until user attestation or verified remote removal. Show clear states: `needs_inventory_review`, `ready_for_facebook_review`, `manual_removal_pending`, `removal_confirmed_by_user`, `remote_removed_verified`, `failed` (exact names subject to compatibility review).
6. Investigate automatic remote removal **only** if a supported, authorized, stable method exists for this personal Marketplace account. Do not assume Meta Graph API supports personal Marketplace deletion. Do not implement stealth, credential capture, CAPTCHA bypass, hidden browser clicks, or uncontrolled background deletion. If no approved capability is demonstrated, ship the assisted manual path only.
7. Any future automatic removal must be **opt-in, individually confirmed, idempotent, scoped to the linked listing ID, with independently verified postcondition**. No unattended batch deletion in this PR.

## Relevant architecture
- `index.html`: Out of Stock labels/actions.
- `app.js`: card actions, cleanup confirmation, error and progress feedback, local Trash wording.
- `styles.css`: layout for new actions/status labels.
- `core.py`: `cleanup_status`, `complete_facebook_cleanup`, `trash_listing`, local audit and persistence.
- `server.py`: existing routes and validation.
- `facebook_auto.py`, `chrome-extension/facebook_reader.js`, `chrome-extension/background.js`, `chrome-extension/manifest.json`: read-only Facebook checks, capability investigation only; changes require explicit justification.
- `tests/`: add focused regression coverage.

## Implementation plan
1. Audit all existing Out of Stock and Facebook cleanup entry points and map every UI action to server transaction and database effect. Confirm whether `complete_facebook_cleanup` is wired in the current UI.
2. Define a strict state machine separating dealer availability, FB reachability, FB removal evidence, and local archive. Treat 403, timeout, login wall, missing reader, and failed dealer check as **unknown**, never `sold` or `deleted`.
3. Implement the manual-first UI: exact Facebook link, step-by-step removal guidance, explicit confirmation, persistent pending/retry status, and correct local-only Trash labeling.
4. Reuse `complete_facebook_cleanup` instead of introducing a second archival code path. Validate VIN, current tracked listing ID, expected URL, and explicit confirmations atomically under the existing store lock. Retain audit provenance: user-attested vs remotely verified.
5. If persistence requires a schema change, write a forward-only migration with backups and backward-compatibility tests; avoid reusing `listing_link_checks.unavailable` as proof of deletion.
6. Preserve old links/history until the confirmation transaction commits. Ensure reappearing dealer inventory does not silently relist, archive, or delete anything.
7. Investigate official Meta capabilities and authenticated-browser UX separately; document supported/unsupported approaches and permissions. No remote deletion code until owner approves a demonstrated supported method.
8. Add tests and a manual Windows/Chrome Reader acceptance script; produce evidence and open a **draft PR** from the feature branch only after implementation.

## Protected functionality / do not modify without justification
- Dealer ingestion, Toyota/Mitsubishi matching, VIN identity, source priority, photo cache and selection, Facebook drafting/publishing preparation, and installed reader read-only checks.
- Existing 30-day Trash restoration, copy locks, SQLite backup and transaction safety, export data, installer and startup paths.
- Do not modify branding/photo pipeline, `photo_cache.py`, `photo_selection.py`, `installer/`, or `startup/` for this feature.
- Never delete local vehicle records/photos because a Facebook listing is removed.
- No credentials, session cookies, private data, or customer information in Git or logs.

## Acceptance criteria
- Every linked candidate has a working action that opens its exact saved Facebook Marketplace URL.
- Manual removal confirmation requires explicit user action and exact current listing ID; a changed/relinked ID is rejected with no data mutation.
- User confirmation is visibly distinguished from independently verified remote deletion.
- No Facebook post changes when clicking local Trash; label and confirmation explicitly state this.
- Unknown dealer/FB link results never cause automatic deletion or a claim of confirmed removal.
- No duplicate removal actions from double-clicks, retries, or concurrent scans.
- Pending/failed records remain actionable across application restart.
- Restoring from local Trash continues to work within the existing retention window.
- A formerly out-of-stock vehicle reappearing does not silently delete or republish a Facebook listing.
- All tests pass; any unsupported remote automation remains disabled.

## Required tests (execute and report evidence)
1. Unit tests: `cleanup_status` combinations across both dealers, FB reachable/unavailable/check_failed, missing links, sold markers, and contradictory evidence.
2. Unit tests: exact-ID manual confirmation, stale-ID rejection, duplicate click/idempotency, rollback on failed transaction, retention and restoration.
3. API tests: unauthorized/absent token, invalid VIN/URL, missing explicit confirmation, concurrent recheck and archive, correct status responses.
4. UI/browser tests: all actions visible, exact link opened, accessible confirmation/cancel, truthful wording, errors/retry, narrow viewport, keyboard operation.
5. Integration tests: Chrome Reader disconnected, logged out, expired permission, timeout, Facebook unavailable, dealer 403, and interrupted recheck.
6. Database migration tests if schema changes: old DB upgrade, backup, crash recovery, no lost drafts, no duplicate listing IDs.
7. Run existing Python and JavaScript test suites, document actual commands, counts and failures. Manual Windows/Chrome test is required for release confidence; no invented PASS results.

## Risk areas
- False sold inference from transient dealer unavailability.
- Facebook's dynamic UI and restrictions on personal Marketplace automation.
- Remote deletion is irreversible; local Trash is reversible. Never conflate them.
- Race between a changed listing URL and cleanup confirmation; duplicate VIN/listing-ID mapping.
- SQLite transaction/backup integrity and retained 30-day records.
- UI showing a success state before external verification.
- Browser tab duplication, session expiration, rate limiting, extension permissions, and concurrent scans.

## Git instructions
Continue on `feature/outstock-facebook-cleanup`, based on approved main SHA above. Do not work directly on `main`. Commit focused changes and test evidence. Open a **draft** PR for review, request independent Gemini QA, and return implementation report to Chief Architect. **Do not merge to main, deploy, or publish a release without explicit Project Owner approval.**

## Open decision
Should LotRadar only help remove the Facebook post, or also offer a distinct **Mark as Sold** action? These are different Marketplace operations and must not be conflated. Default scope is removal, pending Owner direction.
