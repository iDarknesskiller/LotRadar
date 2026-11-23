"""Download-branding fix: a fresh source download must carry working branding, and a branding problem must be
reported by name (never as "photos still fetching"). Synthetic data only; never touches live user data.

    python -m unittest tests.test_committed_branding -v
"""
import hashlib
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / 'scripts'))
import build_installer as bi  # noqa: E402
import photo_cache  # noqa: E402

VIN, SOURCE = '1TESTBRAND0000001', 'toyota_used'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FreshDownloadLayout(unittest.TestCase):
    """AC-01: the runtime paths the program reads exist in the source tree with the approved bytes."""

    def test_runtime_assets_present_with_approved_hashes(self):
        for rel, digest in bi.APPROVED_ASSET_SHA256.items():
            self.assertTrue((REPO / rel).is_file(), rel + ' missing from the source tree')
            self.assertEqual(sha(REPO / rel), digest, rel)

    def test_photo_cache_reads_the_committed_folder(self):
        self.assertEqual(photo_cache.BRANDING_DIR, REPO / 'branding')
        for name in ('business_card.png', 'dedication.jpg'):
            self.assertTrue((photo_cache.BRANDING_DIR / name).is_file(), name)

    def test_server_serves_committed_logo_and_icon(self):
        import server as S
        self.assertEqual(S.BASE, REPO)
        logo = S.read_brand_file('/branding/lotradar_logo.png')
        icon = S.read_brand_file('/favicon.ico')
        self.assertIsNotNone(logo)
        self.assertIsNotNone(icon)
        self.assertEqual(hashlib.sha256(logo).hexdigest(), bi.APPROVED_ASSET_SHA256['branding/lotradar_logo.png'])
        self.assertEqual(hashlib.sha256(icon).hexdigest(), bi.APPROVED_ASSET_SHA256['LotRadar.ico'])
        html = S.branded_index((REPO / 'index.html').read_bytes()).decode('utf-8')
        self.assertIn('class="brand-logo"', html)  # a fresh download shows the logo, not the "LR" fallback
        self.assertIn('rel="icon"', html)

    def test_startup_window_and_installer_use_the_same_paths(self):
        window = (REPO / 'startup' / 'Show-LotRadarStartup.ps1').read_text(encoding='utf-8')
        self.assertIn("Join-Path $programDir 'branding\\lotradar_logo.png'", window)
        self.assertIn("Join-Path $programDir 'LotRadar.ico'", window)
        installer = (REPO / 'installer' / 'Install-LotRadar.ps1').read_text(encoding='utf-8')
        self.assertIn("Join-Path $program 'LotRadar.ico'", installer)


class BrandingErrorsAreNamed(unittest.TestCase):
    """AC-04 (backend): a missing or damaged branding image is reported by file name."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = photo_cache.PhotoCache(Path(self.tmp.name) / 'data')
        self.addCleanup(lambda: getattr(self.cache, 'close', lambda: None)())
        self.brand = Path(self.tmp.name) / 'branding'
        self.brand.mkdir()
        old = photo_cache.BRANDING_DIR
        photo_cache.BRANDING_DIR = self.brand
        self.addCleanup(setattr, photo_cache, 'BRANDING_DIR', old)

    def frames(self):
        return self.cache.prepared_export_frames(VIN, SOURCE, [])

    def put(self, name, data=None):
        (self.brand / name).write_bytes(data if data is not None else (REPO / 'branding' / name).read_bytes())

    def test_both_missing(self):
        with self.assertRaisesRegex(ValueError, r'^branding_assets_missing: business_card\.png, dedication\.jpg; reinstall_R56$'):
            self.frames()

    def test_only_dedication_missing(self):
        self.put('business_card.png')
        with self.assertRaisesRegex(ValueError, r'^branding_assets_missing: dedication\.jpg; reinstall_R56$'):
            self.frames()

    def test_only_card_missing(self):
        self.put('dedication.jpg')
        with self.assertRaisesRegex(ValueError, r'^branding_assets_missing: business_card\.png; reinstall_R56$'):
            self.frames()

    def test_damaged_card(self):
        self.put('business_card.png', b'GIF89a not a png')
        self.put('dedication.jpg')
        with self.assertRaisesRegex(ValueError, r'^branding_assets_invalid: business_card\.png'):
            self.frames()

    def test_damaged_dedication(self):
        self.put('business_card.png')
        self.put('dedication.jpg', b'\xff\xd8\xff\xe0 truncated jpeg')
        with self.assertRaisesRegex(ValueError, r'^branding_assets_invalid: dedication\.jpg'):
            self.frames()

    def test_complete_branding_with_no_photos_is_not_an_error(self):
        self.put('business_card.png')
        self.put('dedication.jpg')
        self.assertEqual(self.frames(), [])


class PreviewMessageStatic(unittest.TestCase):
    """AC-04 (UI, static): app.js shows the named reason; the misleading 'still being fetched' text is gone."""

    @classmethod
    def setUpClass(cls):
        cls.js = (REPO / 'app.js').read_text(encoding='utf-8')

    def test_misleading_message_removed(self):
        self.assertNotIn('Photos are still being fetched or unavailable.', self.js)

    def test_error_text_helper_used_for_stage_and_toast(self):
        self.assertIn('function exportPreviewErrorText(error)', self.js)
        self.assertIn('esc(exportPreviewErrorText(exportPreview.error))', self.js)
        self.assertIn('notify(exportPreviewErrorText(p.error),true)', self.js)

    def test_helper_names_branding_and_reassures_about_photos(self):
        body = self.js[self.js.index('function exportPreviewErrorText(error)'):self.js.index('function resetExportPreview()')]
        self.assertIn('branding_assets_(missing|invalid)', body)
        self.assertIn('Downloaded vehicle photos are not affected', body)
        self.assertNotRegex(body, re.compile(r'still being fetched', re.I))


if __name__ == '__main__':
    unittest.main()
