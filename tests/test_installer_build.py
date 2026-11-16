"""Tests for scripts/build_installer.py and the launcher. Run from the repo root:

    python -m unittest discover -s tests -v

Builds use a throw-away clone of this repository's HEAD, never the live installation or any user data.
Fake branding assets are generated on the fly; no private images are needed or stored.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'scripts'))
import build_installer as bi  # noqa: E402

PNG = b'\x89PNG\r\n\x1a\n' + b'x' * 200
JPG = b'\xff\xd8\xff\xe0' + b'y' * 200
ICO = b'\x00\x00\x01\x00' + b'z' * 200


def rb(path):
    with open(path, 'rb') as handle:
        return handle.read()


def run(cwd, *args):
    subprocess.check_call(['git', '-C', cwd, '-c', 'user.name=t', '-c', 'user.email=t@example.invalid'] + list(args),
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class BuilderTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='lotradar-test-')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.join(self.tmp, 'repo')
        # Clone the committed HEAD of the repo under test (uncommitted edits are intentionally not used).
        subprocess.check_call(['git', 'clone', '-q', '--no-hardlinks', REPO, self.repo])
        self.assets = os.path.join(self.tmp, 'assets')
        os.makedirs(self.assets)

    def write_assets(self, png=True, jpg=True, ico=True):
        for flag, name, data in ((png, 'business_card.png', PNG), (jpg, 'dedication.jpg', JPG), (ico, 'LotRadar.ico', ICO)):
            if flag:
                with open(os.path.join(self.assets, name), 'wb') as h:
                    h.write(data)

    def build(self, mode='development', asset_dir=None, out='out'):
        return bi.build(self.repo, mode, asset_dir, os.path.join(self.tmp, out))

    def commit_change(self, rel, data=None, remove=False):
        path = os.path.join(self.repo, rel)
        if remove:
            run(self.repo, 'rm', '-q', rel)
        else:
            os.makedirs(os.path.dirname(path) or self.repo, exist_ok=True)
            with open(path, 'wb') as h:
                h.write(data)
            run(self.repo, 'add', rel)
        run(self.repo, 'commit', '-q', '-m', 'test change')

    @staticmethod
    def rewrite(zip_path, edit):
        """Return new zip bytes after edit(dict name->bytes) mutated the entries."""
        with zipfile.ZipFile(zip_path) as z:
            entries = {n: z.read(n) for n in z.namelist()}
        edit(entries)
        return bi.zip_bytes(list(entries.items()), 1700000000)


class TestDevelopmentBuild(BuilderTestCase):
    def test_builds_and_verifies(self):
        path, manifest, _digest, _dirty = self.build()
        self.assertTrue(path.endswith('-DEV-NOBRANDING.zip'))
        self.assertEqual(bi.verify_bytes(rb(path)), [])
        self.assertEqual(manifest['build_type'], 'development')
        self.assertEqual(len(manifest['payload_files']), len(bi.SOURCE_ALLOWLIST))

    def test_every_payload_file_listed_exactly_once_and_matches(self):
        path, manifest, *_ = self.build()
        listed = [i['path'] for i in manifest['payload_files']]
        self.assertEqual(len(listed), len(set(listed)))
        with zipfile.ZipFile(path) as z:
            actual = sorted(n[len('MarketplaceScanner/'):] for n in z.namelist() if n.startswith('MarketplaceScanner/'))
            self.assertEqual(sorted(listed), actual)
            for item in manifest['payload_files']:
                self.assertEqual(bi.sha256(z.read('MarketplaceScanner/' + item['path'])), item['sha256'])

    def test_provenance_in_manifest(self):
        _p, manifest, *_ = self.build()
        head = subprocess.check_output(['git', '-C', self.repo, 'rev-parse', 'HEAD']).decode().strip()
        self.assertEqual(manifest['source_commit'], head)
        self.assertTrue(manifest['package_version'].endswith(head[:7]))

    def test_build_is_bit_for_bit_reproducible(self):
        p1, m1, d1, _ = self.build(out='a')
        p2, m2, d2, _ = self.build(out='b')
        self.assertEqual(d1, d2)
        self.assertEqual(rb(p1), rb(p2))
        self.assertEqual(m1['payload_files'], m2['payload_files'])

    def test_reproducible_with_assets(self):
        self.write_assets()
        _p, _m, d1, _ = self.build('production', self.assets, 'a')
        _p, _m, d2, _ = self.build('production', self.assets, 'b')
        self.assertEqual(d1, d2)

    def test_no_executables_no_private_data_in_package(self):
        path, *_ = self.build()
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                self.assertFalse(re.search(r'\.(exe|sqlite3|db|zip|log)$', name, re.I), name)
                self.assertNotRegex(name, r'(^|/)(data|runtime|photos)(/|$)')

    def test_installer_files_match_repo_sources(self):
        path, *_ = self.build()
        with zipfile.ZipFile(path) as z:
            for name, src in bi.PACKAGE_FILES.items():
                with open(os.path.join(self.repo, src), 'rb') as h:
                    self.assertEqual(z.read(name), h.read())

    def test_uncommitted_edits_are_not_packaged(self):
        with open(os.path.join(self.repo, 'server.py'), 'ab') as h:
            h.write(b'\n# uncommitted\n')
        path, manifest, _d, dirty = self.build()
        self.assertTrue(dirty)
        with zipfile.ZipFile(path) as z:
            self.assertNotIn(b'# uncommitted', z.read('MarketplaceScanner/server.py'))


class TestVerifyRejectsTampering(BuilderTestCase):
    def setUp(self):
        super().setUp()
        self.path, self.manifest, *_ = self.build()

    def test_corrupted_payload_file_rejected(self):
        def edit(e):
            e['MarketplaceScanner/server.py'] += b'#'
        errors = bi.verify_bytes(self.rewrite(self.path, edit))
        self.assertTrue(any('SHA-256 mismatch: MarketplaceScanner/server.py' in x for x in errors), errors)

    def test_same_size_corruption_rejected(self):
        def edit(e):
            d = bytearray(e['MarketplaceScanner/core.py'])
            d[10] ^= 1
            e['MarketplaceScanner/core.py'] = bytes(d)
        errors = bi.verify_bytes(self.rewrite(self.path, edit))
        self.assertTrue(any('SHA-256 mismatch' in x for x in errors), errors)

    def test_missing_file_rejected(self):
        def edit(e):
            del e['MarketplaceScanner/app.js']
        errors = bi.verify_bytes(self.rewrite(self.path, edit))
        self.assertTrue(any('listed but missing' in x for x in errors), errors)

    def test_unlisted_extra_file_rejected(self):
        def edit(e):
            e['MarketplaceScanner/extra.py'] = b'print(1)'
        errors = bi.verify_bytes(self.rewrite(self.path, edit))
        self.assertTrue(any('not in manifest' in x for x in errors), errors)

    def test_manifest_duplicate_and_unsafe_paths_rejected(self):
        def edit(e):
            m = json.loads(e['Install-Manifest.json'])
            m['payload_files'].append(dict(m['payload_files'][0]))
            m['payload_files'].append({'path': '../evil.py', 'sha256': '0' * 64, 'bytes': 1})
            e['Install-Manifest.json'] = json.dumps(m).encode()
        errors = bi.verify_bytes(self.rewrite(self.path, edit))
        self.assertTrue(any('more than once' in x for x in errors), errors)
        self.assertTrue(any('unsafe manifest path' in x for x in errors), errors)

    def test_missing_manifest_rejected(self):
        def edit(e):
            del e['Install-Manifest.json']
        self.assertIn('Install-Manifest.json is missing', bi.verify_bytes(self.rewrite(self.path, edit)))

    def test_planted_secret_or_database_rejected(self):
        def edit(e):
            e['MarketplaceScanner/marketplace.sqlite3'] = b'SQLite format 3'
        errors = bi.verify_bytes(self.rewrite(self.path, edit))
        self.assertTrue(any('forbidden path' in x for x in errors), errors)

    def test_garbage_is_not_a_zip(self):
        self.assertTrue(bi.verify_bytes(b'not a zip'))

    def test_development_package_fails_require_production(self):
        with open(self.path, 'rb') as h:
            errors = bi.verify_bytes(h.read(), require_production=True)
        self.assertTrue(any('not a production package' in x for x in errors), errors)


class TestBuildGuards(BuilderTestCase):
    def test_missing_mandatory_source_file_fails_build(self):
        self.commit_change('trade_ready.py', remove=True)
        with self.assertRaisesRegex(bi.BuildError, 'trade_ready.py'):
            self.build()

    def test_unlisted_tracked_file_fails_build(self):
        self.commit_change('new_module.py', b'x = 1\n')
        with self.assertRaisesRegex(bi.BuildError, 'new_module.py'):
            self.build()

    def test_secret_in_source_fails_build(self):
        fake = 'sk-' + 'A1b2C3d4' * 4
        self.commit_change('ai_copy.py', rb(os.path.join(self.repo, 'ai_copy.py'))
                           + ('\nKEY = "%s"\n' % fake).encode())
        with self.assertRaisesRegex(bi.BuildError, 'OpenAI-style key'):
            self.build()

    def test_production_requires_asset_dir(self):
        with self.assertRaisesRegex(bi.BuildError, 'require --asset-dir'):
            self.build('production')

    def test_production_requires_both_branding_images(self):
        self.write_assets(jpg=False)
        with self.assertRaisesRegex(bi.BuildError, 'dedication.jpg'):
            self.build('production', self.assets)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'out')), 'no package may be written on failure')

    def test_production_requires_clean_tree(self):
        self.write_assets()
        with open(os.path.join(self.repo, 'server.py'), 'ab') as h:
            h.write(b'\n#x\n')
        with self.assertRaisesRegex(bi.BuildError, 'clean working tree'):
            self.build('production', self.assets)

    def test_bad_asset_header_rejected(self):
        self.write_assets()
        with open(os.path.join(self.assets, 'business_card.png'), 'wb') as h:
            h.write(b'GIF89a' + b'0' * 100)
        with self.assertRaisesRegex(bi.BuildError, 'bad header'):
            self.build('production', self.assets)

    def test_empty_asset_rejected(self):
        self.write_assets()
        open(os.path.join(self.assets, 'dedication.jpg'), 'wb').close()
        with self.assertRaisesRegex(bi.BuildError, 'implausible size'):
            self.build('production', self.assets)

    def test_asset_dir_not_a_directory(self):
        with self.assertRaisesRegex(bi.BuildError, 'not a directory'):
            self.build('development', os.path.join(self.tmp, 'nope'))

    def test_asset_inside_repo_must_be_git_ignored(self):
        inside = os.path.join(self.repo, 'my-assets')
        os.makedirs(inside)
        for name, data in (('business_card.png', PNG), ('dedication.jpg', JPG)):
            with open(os.path.join(inside, name), 'wb') as h:
                h.write(data)
        with self.assertRaisesRegex(bi.BuildError, 'NOT git-ignored'):
            self.build('development', inside)

    def test_asset_in_ignored_branding_dir_inside_repo_is_allowed(self):
        inside = os.path.join(self.repo, 'branding')
        os.makedirs(inside)
        for name, data in (('business_card.png', PNG), ('dedication.jpg', JPG)):
            with open(os.path.join(inside, name), 'wb') as h:
                h.write(data)
        path, manifest, *_ = self.build('development', inside)
        self.assertEqual(manifest['branding_assets_missing'], [])

    def test_production_package_contents(self):
        self.write_assets()
        path, manifest, *_ = self.build('production', self.assets)
        self.assertNotIn('DEV', os.path.basename(path))
        self.assertEqual(manifest['build_type'], 'production')
        self.assertEqual(manifest['working_tree_clean'], True)
        self.assertEqual(manifest['branding_assets_included'],
                         ['LotRadar.ico', 'branding/business_card.png', 'branding/dedication.jpg'])
        self.assertEqual(bi.verify_bytes(rb(path), require_production=True), [])
        with zipfile.ZipFile(path) as z:
            self.assertEqual(z.read('MarketplaceScanner/branding/business_card.png'), PNG)
            self.assertEqual(len(manifest['payload_files']), len(bi.SOURCE_ALLOWLIST) + 3)

    def test_production_without_icon_is_allowed(self):
        self.write_assets(ico=False)
        path, manifest, *_ = self.build('production', self.assets)
        self.assertNotIn('LotRadar.ico', manifest['branding_assets_included'])

    def test_production_package_missing_branding_fails_verify(self):
        self.write_assets()
        path, *_ = self.build('production', self.assets)

        def edit(e):
            m = json.loads(e['Install-Manifest.json'])
            m['payload_files'] = [i for i in m['payload_files'] if i['path'] != 'branding/dedication.jpg']
            e['Install-Manifest.json'] = json.dumps(m).encode()
            del e['MarketplaceScanner/branding/dedication.jpg']
        errors = bi.verify_bytes(self.rewrite(path, edit))
        self.assertTrue(any('lacks required asset' in x for x in errors), errors)


class TestRepositoryHygiene(unittest.TestCase):
    def test_allowlist_files_exist_and_no_private_files_tracked(self):
        tracked = subprocess.check_output(['git', '-C', REPO, 'ls-files', '-z']).decode().split('\0')
        for path in bi.SOURCE_ALLOWLIST:
            self.assertIn(path, tracked)
        for path in tracked:
            self.assertFalse(re.search(r'\.(exe|zip|sqlite3|db|png|jpg|jpeg|ico)$', path, re.I), path)
            self.assertFalse(path.startswith(('branding/', 'dist/')), path)

    def test_gitignore_covers_private_and_generated(self):
        for probe in ('branding/business_card.png', 'dist/x.zip', 'data/marketplace.sqlite3',
                      'runtime/venv/a.py', 'LotRadar.exe', 'x.sqlite3', '.env'):
            rc = subprocess.run(['git', '-C', REPO, 'check-ignore', '-q', probe]).returncode
            self.assertEqual(rc, 0, probe + ' must be git-ignored')

    def test_scan_secrets_unit(self):
        self.assertTrue(bi.scan_secrets('data/x.txt', b'hi'))
        self.assertTrue(bi.scan_secrets('a.py', b'-----BEGIN RSA PRIVATE KEY-----'))
        self.assertEqual(bi.scan_secrets('server.py', b'api_key = os.environ.get("X")'), [])
        self.assertEqual(bi.scan_secrets('branding/business_card.png', PNG), [])


class TestLauncher(unittest.TestCase):
    """Static checks only. The launcher itself can only be executed on Windows."""

    def setUp(self):
        with open(os.path.join(REPO, 'Launch Marketplace Scanner.cmd'), 'rb') as h:
            self.raw = h.read()
        self.text = self.raw.decode('ascii')

    def test_uses_bootstrap_not_exe(self):
        code = '\n'.join(l for l in self.text.splitlines() if not l.lower().startswith('rem '))
        self.assertIn('Marketplace Bootstrap.ps1', code)
        self.assertNotIn('.exe"', code.replace('powershell.exe', ''))
        self.assertNotIn('LotRadar.exe', code)
        self.assertNotIn('LotRadar_Setup', code)

    def test_crlf_only(self):
        self.assertNotRegex(self.raw, rb'(?<!\r)\n')

    def test_propagates_exit_code_and_sets_cwd(self):
        self.assertIn('exit /b %RC%', self.text)
        self.assertIn('set "RC=%ERRORLEVEL%"', self.text)
        self.assertIn('cd /d "%~dp0"', self.text)
        self.assertIn('-File "%BOOTSTRAP%"', self.text)

    def test_pause_is_deterministic_not_cmdcmdline_heuristic(self):
        self.assertNotIn('cmdcmdline', self.text)
        self.assertIn('if not defined LOTRADAR_NO_PAUSE pause', self.text)

    def test_missing_bootstrap_branch_returns_nonzero(self):
        self.assertRegex(self.text, r'if not exist "%BOOTSTRAP%" \(\r\n(?:.*\r\n)*? set "RC=2"')

    def test_bootstrap_unchanged_from_baseline(self):
        baseline = subprocess.check_output(['git', '-C', REPO, 'show', '6164c78de3fd568b0c45525ee337c3e604c65e32:Marketplace Bootstrap.ps1'])
        with open(os.path.join(REPO, 'Marketplace Bootstrap.ps1'), 'rb') as h:
            self.assertEqual(h.read(), baseline)


if __name__ == '__main__':
    unittest.main()
