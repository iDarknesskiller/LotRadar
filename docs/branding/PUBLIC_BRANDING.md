# Owner-approved public branding

On November 19, 2026, the Project Owner supplied the business card and the LotRadar radar logo and explicitly
approved publishing both in this public repository, including the business card's photo and contact details. The
Owner then separately approved publishing the existing promotional dedication image (`dedication.jpg`). This
exception applies only to these four files: the card, the logo, the logo-derived icon and the dedication image. It
does not authorize publishing any other private data, assets, screenshots or evidence.

## Where the files live

There is exactly one committed copy of each file, at the path the program reads at runtime. A fresh
"Download ZIP" of `main` therefore works without any private folder (see `docs/INSTALL.md`).

| File | Bytes | SHA-256 |
| --- | --- | --- |
| [`branding/business_card.png`](../../branding/business_card.png) | 662600 | `be82e63c6035cf337cdc9a7bb038f670393324fa9e1f9aa3c710607bdfa701bd` |
| [`branding/dedication.jpg`](../../branding/dedication.jpg) | 19544 | `f1f86eef4f8d69d9f797e69767e8c1058afeb156d5af2d1ea369a538715db0e5` |
| [`branding/lotradar_logo.png`](../../branding/lotradar_logo.png) | 31958 | `b598d23ba243d30274d59ba78abc1571348b46eefbccd494a9dd3e0af2820e7d` |
| [`LotRadar.ico`](../../LotRadar.ico) | 31980 | `e97981648825570899b7a208fcd7aa82f2a66238fc791a87e18cf24b680d7629` |

The PNGs are byte-for-byte copies of the Owner's attachments. The ICO is a one-frame PNG-backed icon wrapping the
original logo PNG bytes, without redrawing, resizing or changing pixels. The JPEG is the existing Owner-approved
promotional image. `scripts/build_installer.py` (`APPROVED_ASSET_SHA256`) refuses to package a committed file whose
bytes differ from this table.

## LotRadar logo

![Owner-supplied LotRadar logo](../../branding/lotradar_logo.png)

## Business card

![Owner-supplied business card](../../branding/business_card.png)

## Dedication image

![Owner-approved dedication image](../../branding/dedication.jpg)

## History

PR #17 first published the logo, icon and card under `docs/branding/public-assets/` only, which the program does not
read, so a fresh download still reported `branding_assets_missing`. The download-branding fix moved the single copy
of each file to its runtime path and removed the `docs/` duplicates. The logo hash differs from the earlier PR #5
private logo (`792f3c78ebdd62f633ad9e28b928b17812c2d5243e7cef47dcbc33c1be924e86`); the PR #5 audit did not certify
these newer bytes. E3 physical-keyboard acceptance (PR #16) is tracked separately and is not affected by this file.
