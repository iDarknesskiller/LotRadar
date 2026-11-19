# ARCHITECT_HANDOFF.md — Offline Picture Sorting

**To:** Claude — Lead Programmer  
**Status:** Architecture proposal only; implementation not authorized by this document.  
**Baseline:** GitHub main commit `a52bf1d8bcc88a740267bfa5c0226beb4587e67a`; `photo_classify.py` identifies LotRadar 1.9.13.  
**Branch:** `feature/offline-picture-sorting`. Do not merge to main.

## Request
Replace dependence on paid cloud classification for exterior/interior photo sorting with an offline approach that learns the Project Owner's preferred order from hundreds of approved, previously manually organized vehicle photo folders, with capacity for incremental learning from future explicit corrections. Begin with a read-only feasibility study on an initial representative sample, then expand to hundreds of approved folders in batches. Do not assume more folders automatically produce reliable labels.

## Current behavior
`photo_classify.py` contains a cloud OpenAI image classifier and background `AutoSorter`; `server.py` requests classification after downloads and for previously unsorted previews; `photo_selection.py` persists selections and manual categories. The sorter requires `OPENAI_API_KEY`, and can pause on authentication/quota failures. Running behavior on the owner's installed machine has not been verified.

## Required behavior
Use an extensible, versioned local training dataset built from approved, explicitly manually arranged examples to infer image category and preferred presentation order locally, without requiring network/API credits for classification. Preserve manually chosen photo order and groups, originals, cover/dedication positions, export integrity, and current UI semantics. Uncertain images must be reviewable; no silent destructive changes. The system must not learn from unverified automatically exported/dealer-ordered folders.

## Relevant architecture
Inspect `photo_classify.py`, `photo_selection.py`, `server.py`, `photo_cache.py`, `app.js`, installer/build scripts, and photo-related tests. Confirm exact call paths, persisted metadata, concurrency, and installer dependencies before edits.

## Implementation plan
1. Inventory existing classification, download, preview, manual override, persistence, and export paths against the pinned main SHA.
2. Identify and obtain explicit owner approval for the source folders and determine whether they truly encode manual order. Read-only access; avoid copying private photos to a remote service.
3. Define a reproducible, deduplicated, versioned labeled dataset supporting hundreds of folders and future approved corrections. Split by vehicle/VIN (and near-duplicate image groups) into train/validation/held-out test sets before training; keep the held-out test frozen. Separate category classification from ordering preferences.
4. Compare a metadata/rules baseline with a lightweight pretrained local vision embedding/classifier plus learned ranking preferences. With hundreds of folders, assess fine-tuning only if label quality, dataset size, hardware and validation results justify it; never assume training a vision backbone from scratch is necessary.
5. Run incremental batch evaluations as approved folders grow (e.g. initial sample, 100, 200, 400+), retaining the same frozen held-out set. Measure exterior/interior accuracy, uncertain-image rate, ordering agreement, latency, memory and CPU use. Record errors by photo type and confidence calibration. Agree on go/no-go thresholds with Owner before implementation.
6. Design an opt-in, resumable local training pipeline with versioned model checkpoints, rollback, explicit correction capture, deduplication, and safeguards against self-training on unverified predictions. If approved, implement an optional offline backend behind the existing sorter interface; retain manual override precedence, durable classification state, idempotent background jobs, and safe fallback.
7. Package model weights and runtime dependencies reproducibly with license review and integrity verification. No runtime download requirement for offline mode.
8. Add visible sorting status, progress, review-needed and failure reasons. Never claim completion before classification is persisted.

## Protected functionality
Photo download, source fallback, VIN/stock associations, original image bytes, existing manual groups/order, fixed business-card/dedication images, preview, export ZIP, Facebook listing preparation, out-of-stock retention, and Facebook cleanup tracking. Do not change unrelated scanner/database/installer behavior.

## Acceptance criteria
- On an offline machine with no API key, approved test photos can be classified and ordered locally after the model is installed.
- Existing manually selected order/groups take precedence and survive restart, refresh and re-export.
- Originals retain exact hashes; no deletion, rename or modification of originals.
- No model training on unapproved folders; no cross-vehicle or near-duplicate leakage into validation/test. Incremental training never treats automatic predictions as owner-confirmed labels.
- Uncertain predictions remain reviewable and are never silently represented as verified.
- Cover/dedication positions and exported image order remain correct.
- Measured held-out metrics and performance are reported at multiple dataset sizes; model revisions can be rolled back; owner signs off thresholds before default enablement.
- No unintended cloud calls; installer works offline with integrity-checked model assets.

## Required tests
Unit tests for grouping/ranking/override precedence, missing model, missing metadata and confidence thresholds; integration tests for download-to-sort, preview-triggered retry, export, persistence and restart; concurrency/idempotency tests for duplicate downloads and overlapping sorting jobs; offline/no-key tests; batch import, deduplication, incremental retraining, frozen holdout, rollback and corrupted checkpoint tests; model/installer packaging and checksum tests; regression tests for original hashes, fixed cover/dedication order, manual selection, and photo cleanup separation. Run and report exact commands/results, not just proposed tests.

## Risk areas
Insufficient or biased training examples, false labels inferred from file order, self-reinforcing feedback loops, dataset growth and disk usage, training interruption/checkpoint corruption, vehicle-level leakage, local model size/performance, CPU contention with scanner, background race conditions, stale classification caches, repeated retries, wrong dealer association, damaged originals, license/distribution issues, and accidentally changing Facebook cleanup/deletion lifecycle.

## Git instructions
Continue on `feature/offline-picture-sorting` based on pinned approved main. Implement only after architecture review and owner authorization; open follow-up implementation commits/PR review as appropriate. **Do not merge to main.**
