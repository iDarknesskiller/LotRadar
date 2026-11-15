CURRENT INSTALLED LOTRADAR SOURCE — AUDIT COPY

These files were copied from the installed program, not a proposed update package.
FILE_MANIFEST.json records each included file and its SHA-256 hash.

Excluded: separate private data directory, inventory/database, photo caches,
branding images/binaries, browser profiles, dependencies, logs, and filenames
that indicate credentials, sessions, tokens, or private settings.
This is a source audit bundle, not a runnable backup or installer. Imports may
reference excluded runtime data or assets. Do not infer missing app behavior
solely from those excluded files. Standard manifest.json files are included.
Filename filtering cannot detect credentials manually hardcoded inside code.
Review the ZIP before sharing if you have embedded any keys in source files.

AUDIT REQUEST FOR CLAUDE
Review the actual source. Report reproducible issues with file/function references,
severity, cause, and a focused fix. Distinguish confirmed bugs from hypotheses.
Focus on:
- Trade-in eligibility: a used source stock number must end in a letter.
- Readiness: all gallery photos downloaded plus business card on export photo 1.
- Queue deduplication, priority, cancellation, resume and persistence.
- Automatic 24-hour refresh cache versus immediate manual refresh.
- Failed-refresh cooldown and successful timestamps that failures cannot reset.
- Reuse of downloaded photos and generated branding.
- One-minute readiness checks staying local; all progress in Live Scanner.
- Race conditions, deadlocks, photo selection/export mismatches, stale caches.
Do not change code until the findings and proposed fixes have been reviewed.
