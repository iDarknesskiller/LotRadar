# Owner-approved public branding

On November 19, 2026, the Project Owner supplied the business card and LotRadar radar logo and explicitly approved publishing both, including the business card's photo/contact details, in this public repository. This exception applies only to these supplied assets and the logo-derived icon. It does not authorize publishing unrelated private data or dedication.jpg.

## LotRadar logo

![Owner-supplied LotRadar logo](public-assets/lotradar_logo.png)

[Download the logo-derived Windows icon](public-assets/LotRadar.ico).

## Business card

![Juan Madrigal business card](public-assets/business_card.png)

## Exact asset identity

| File | Bytes | SHA-256 |
| --- | --- | --- |
| business_card.png | 662600 | `be82e63c6035cf337cdc9a7bb038f670393324fa9e1f9aa3c710607bdfa701bd` |
| lotradar_logo.png | 31958 | `b598d23ba243d30274d59ba78abc1571348b46eefbccd494a9dd3e0af2820e7d` |
| LotRadar.ico | 31980 | `e97981648825570899b7a208fcd7aa82f2a66238fc791a87e18cf24b680d7629` |

The PNGs are byte-for-byte copies of the new Owner attachments. The ICO is a one-frame PNG-backed icon wrapping the original logo PNG bytes, without redrawing, resizing or changing pixels. The attached logo hash differs from the earlier PR5 private-logo hash 792f3c78ebdd62f633ad9e28b928b17812c2d5243e7cef47dcbc33c1be924e86. Do not claim the earlier audit certified these newly supplied bytes.

## Publication versus application integration

These files are under docs/ so current installer allowlisting excludes them from payload input. This PR does not change runtime code, build rules, private asset stores or installed branding. Current production builds still load all four assets through --asset-dir, and development builds without assets still show LR. Publication alone does not remove that requirement.

Follow the separate architecture handoff before packaging integration. E3 physical-keyboard acceptance in PR #16 remains required before the next implementation work. No merge, release or deployment is authorized by this publication PR.
