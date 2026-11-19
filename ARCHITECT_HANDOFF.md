# Offline Picture Sorting: What We Are Building

## Plain-English explanation for the Project Owner

**The problem today:** LotRadar can download your dealership vehicle photos, but its automatic exterior/interior sorting currently relies on the OpenAI API. When your separate API credits or quota run out, sorting can stop. Your ChatGPT subscription does not fund that API.

**The goal:** Give LotRadar its own **offline picture sorter**. It should study **hundreds of vehicle photo folders that YOU have already arranged correctly**, discover the visual patterns and ordering preferences in your work, and apply those preferences when a new vehicle is imported. Once the local model is installed, **sorting should not require an OpenAI API key or paid calls**.

**Important distinction:** We are teaching two skills, not one:
1. **What the photo shows:** exterior, interior, or uncertain.
2. **Where you prefer it:** the order of exterior angles and interior shots, learned from your confirmed examples.

### Concrete example

Suppose you have organized 300 saved vehicle folders. Each contains photos in the order you actually want. LotRadar analyzes these folders locally, without editing them. For a newly downloaded vehicle with 30 photos, it identifies likely exteriors and interiors, then proposes an order resembling your examples. You can correct any mistakes. Those **explicit corrections**, not its unverified guesses, can become future training examples.

The exact sequence is **not predetermined** by Claude or ChatGPT. It must be learned from your approved folders. Do not assume exterior-first or any particular camera-angle sequence without evidence.

### What happens, step by step

1. **Choose training folders.** Only folders confirmed to represent your own finished ordering qualify. A raw dealer download is not proof of your preference.
2. **Study without touching originals.** Read image content and saved ordering, create a separate local training index, and leave source files exactly as they are.
3. **Learn visual categories and ordering separately.** Start with a pretrained local image recognizer plus a small preference-ranking model. Compare against simple metadata/rules. More data may help, but accuracy must be measured.
4. **Test on vehicles the model has never studied.** Keep complete vehicles and near-duplicate photos out of training. Compare its proposed order with your actual order. Report category accuracy, ordering quality, mistakes, speed and resource use.
5. **Grow to hundreds of folders.** Import approved folders in batches; evaluate at successive sizes. Keep model versions so a bad update can be rolled back.
6. **Sort future imports offline.** When approved for implementation, trigger the local sorter after photo download and for previously unsorted previews, preserving the existing gallery and export behavior.
7. **Learn from your corrections.** A manual change takes priority immediately. Add it to future training only after it is explicitly confirmed; never blindly train on its own predictions.

### What you will see

- New vehicle photos grouped and ordered automatically when confidence is sufficient.
- Photos the model cannot confidently identify marked **Needs Review** instead of being silently misplaced.
- A clear status such as **Sorting**, **Ready**, **Needs Review**, or **Model Unavailable**.
- Your manual choices retained after refreshing, restarting, and exporting.

### What this does NOT do

- It does **not** rewrite, delete, crop, or modify original photos.
- It does **not** move the protected business-card cover or dedication image.
- It does **not** automatically post to Facebook or change Facebook cleanup rules.
- It does **not** send training photos to a cloud AI service.
- It does **not** guarantee perfect recognition merely because there are hundreds of folders.
- It does **not** silently retrain on dealer defaults or automatically sorted folders.
- This PR is **an architecture and evaluation handoff**, not working offline sorting code.

### How we will know it works

Claude must show before/after examples for held-out vehicles, actual accuracy and ordering metrics, sorting time on the target PC, results without internet or an API key, and proof that manually chosen order and original photo hashes remain unchanged. The Project Owner must approve the results and acceptable accuracy thresholds **before offline sorting becomes the default**.

### What Claude is expected to deliver next

First: a feasibility report and measured prototype, using approved folders only. Second, if approved: a production implementation on this feature branch with automated tests, packaging, status UI, and rollback. **No merge to main without the Project Owner's explicit approval.**

---

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
