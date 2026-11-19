# ARCHITECT_HANDOFF.md

**To:** GitHub Copilot, hotfix implementer  
**Owner:** LotRadar Project Owner  
**Baseline:** approved `main` SHA `a52bf1d8bcc88a740267bfa5c0226beb4587e67a` (2026-11-19).  
**Branch:** `hotfix/photo-auto-sort-stamp-copilot`. **No merge to main.**

## Request
Fix photo Auto Sort so that opening a vehicle's photo menu initiates classification on the first opening when photos are downloaded but not yet classified. If a sort was missed or failed, reopening must retry, including for previously downloaded galleries. Save a durable per-gallery completion stamp to avoid repeated paid AI calls. This is a narrowly scoped hotfix; use focused tests rather than a broad regression campaign.

## Current behavior and root-cause hypothesis
- `server.py` creates `PhotoCategories` and `AutoSorter`, sets `photo_cache.on_finished=lambda vin,source:auto_sorter.request(vin,source)`, and on GET `/api/photos/selection` requests sorting when `len(known)<len(candidates)`.
- `photo_classify.py` implements a content-hash/version category cache and a memory-only `AutoSorter` queue. It checks enabled, key, pause, and duplicate queue status. Cache hits cost no API credits.
- `photo_selection.py` persists the `_auto_sort` enabled flag, not a per-gallery completion stamp.
- `app.js` fetches photo selection/preview state. Investigate whether the first-open request, delayed gallery availability, and UI refresh correctly trigger and show sorting. **Root cause is not yet proven**; reproduce before editing.
- `server.py:auto_sort_job` returns an empty success when export frames are not ready; do not stamp that as completed.
- Existing GET route may already queue classification. Avoid blindly adding duplicate triggers or paid requests.

## Required behavior
1. On opening the vehicle photo menu, for its exact `(VIN, dealer source)`, inspect downloaded classifiable photos and existing category cache. If Auto Sort enabled and uncached photos exist, enqueue once as soon as photos are ready, including on first opening.
2. If gallery is not ready, leave it pending and retry after download completion or subsequent opening. If AI call fails, is paused, or yields incomplete categories, do not mark complete; retry only when enabled and valid credentials/quota permit.
3. Persist a per-source gallery stamp after full success, with UTC completion timestamp, classifier version, and deterministic identity/fingerprint of the classifiable photo set (prefer stable content hashes). Compare actual cache coverage, not just a timestamp. On unchanged fully cached gallery, no new AI call.
4. When photos change, only classify missing hashes; preserve cached classifications. A gallery of zero classifiable photos must not be falsely stamped as successfully sorted before photos are ready.
5. Respect Auto Sort OFF and existing manual classification behavior. The user should not need to close/reopen the menu to trigger the first sort. Status should reflect queued/running/complete/error without misleading success.
6. Avoid initiating multiple concurrent paid jobs for the same gallery, including rapid UI opens and download callbacks. Persist state atomically; do not mutate source photos.

## Relevant architecture / files
- **Likely edit:** `server.py` (photo-selection GET, download completion hook, job readiness/status).
- **Likely edit:** `photo_classify.py` (AutoSorter state and durable completion metadata in/alongside PhotoCategories, with cache integrity).
- **Possible edit:** `app.js` only if first-open UI fetch/status refresh is the actual blocker.
- **Possible edit:** `photo_selection.py` only if it is the safest existing persistent state owner; avoid redundant metadata in two stores.
- **Tests:** add/update narrow tests for above flows, using mocks and local temp data.
- **Do NOT modify:** inventory DB schema or records, dealer scraper, photo downloads/processing, export selection/order/ZIP, Facebook integration, branding, installers, credentials, or live data.

## Implementation plan
1. Reproduce first-open failure using downloaded, uncategorized fixture photos. Trace GET `/api/photos/selection`, gallery readiness, request result, worker queue, API availability, and client polling.
2. Define completion as **all eligible gallery photos covered by valid category cache for the current classifier version**, not simply a worker return with empty error. Keep current cache hash/version semantics.
3. Implement durable per-(VIN,source,photo-set) completion metadata, written atomically only after verified coverage. Make stale/partial state recoverable.
4. Make first menu opening enqueue when ready; if not ready, arrange retry on download completion and next opening. Preserve enabled/key/paused checks. Deduplicate requests and ensure UI reflects actual progress.
5. Add focused tests; inspect the diff for unintended paid calls, data changes, and scope creep. Provide Copilot's implementation summary and actual test output in PR.

## Protected functionality
- Original dealership photos remain unchanged.
- Existing category cache and export photo order/selection remain intact.
- Auto Sort toggle OFF blocks automatic work; manual sort remains available.
- Dealer/source isolation and VIN validation remain intact.
- No unnecessary OpenAI requests; no credentials or user data committed.

## Acceptance criteria
- First opening of a ready, uncategorized gallery queues exactly one job and classifies it when API mock succeeds.
- Reopening a previously downloaded gallery with incomplete/missed classification retries without requiring download.
- Opening a completed unchanged gallery repeatedly or after server restart makes **zero** new AI calls.
- Changed gallery classifies only new uncached hashes.
- Unready gallery, partial response, invalid key, quota failure, or interrupted worker does not write a false completion stamp.
- Rapid repeated opens never create duplicate simultaneous jobs; UI accurately reports state.
- OFF means no automatic classification; existing manual action works.
- No changes to original photo bytes, export outputs, inventory data, or Facebook behavior.

## Required tests (focused hotfix)
- Unit tests for stamp persistence, invalidation, restart, cache/version coverage, failure/retry, OFF behavior, and queue deduplication.
- Route-level test of first-open GET and previously downloaded gallery with missing categories.
- Mocked AI calls to assert request counts; no live paid calls required.
- Execute relevant existing photo-selection/classification/export tests and report pass/fail/skips honestly.
- Inspect git diff for secrets, data files, photos, and unrelated changes. No broad test suite required unless a focused test exposes regression.

## Risk areas
- Premature success when gallery frames are missing, duplicate paid calls, stale cache/version, cross-source VIN collisions, concurrent worker writes, crashes between classification and stamp persistence, false UI completion, and accidentally reclassifying existing photos.

## Git instructions
Continue on `hotfix/photo-auto-sort-stamp-copilot` from approved baseline. This branch currently contains handoff documentation only. Implement the code and tests on this branch and update the **draft PR**; do not merge to `main`, deploy, release, or touch the installed live application. Request owner approval after review.
