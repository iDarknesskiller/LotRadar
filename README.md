# LotRadar (Private Development Repository)

LotRadar is an independent Windows inventory-scanner and Facebook Marketplace listing-preparation application.

## Baseline
This repository was initialized from `LotRadar_Current_Source_Audit_20261114-180024(1).zip`, an **audit-only copy** of the installed source. It is not a complete runnable backup or installer. Do not deploy it over a working installation.

The original archive's `AUDIT_README.txt` and `FILE_MANIFEST.json` are included for provenance. The manifest refers to the original archive paths, not this restructured repository.

## Safety
Never commit data directories, customer information, photos, local databases, browser profiles, paired extension keys, credentials, tokens or local config. Always review diffs before committing. Keep a separate offline backup of the working installation and private data.

## Paths (documented by bundled source)
- Program: `%LOCALAPPDATA%\Programs\MarketplaceScanner`
- Data: `%LOCALAPPDATA%\MarketplaceScanner\data`
- Runtime: `%LOCALAPPDATA%\MarketplaceScanner\runtime`

## AI handoff process
1. Architect audits source and defines scope, acceptance criteria.
2. Programmer makes changes on a branch (not live app).
3. Security reviewer examines actual diff.
4. Tester records executed tests and omissions.
5. Independent reviewer validates findings.
6. Human authorizes merge/release after backup, regression and rollback verification.

Initial review priorities are recorded in `AUDIT_README.txt`.
