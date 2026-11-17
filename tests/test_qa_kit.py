"""The private Windows QA kit is built only from committed files, verifies itself, and carries no private assets."""
import hashlib, io, json, os, subprocess, sys, tempfile, unittest, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRIVATE = ('business_card.png', 'dedication.jpg', 'lotradar_logo.png', 'lotradar.ico')


def run(*args, cwd=None):
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True)


import re
# an 'exit' statement (PowerShell is case-insensitive), but not a hashtable key / property such as 'Exit = $code'
EXIT_STMT = re.compile(r'(?im)(?:^|[;{])\s*exit\b(?!\s*=)')


class QAKit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.clone = os.path.join(cls.tmp.name, 'repo')
        r = run('git', 'clone', '-q', ROOT, cls.clone)
        if r.returncode:
            raise unittest.SkipTest('git clone failed: ' + r.stderr)
        cls.head = run('git', 'rev-parse', 'HEAD', cwd=cls.clone).stdout.strip()
        cls.zips = []
        for n in (1, 2):
            out = os.path.join(cls.tmp.name, 'out%d' % n)
            r = run(sys.executable, os.path.join(cls.clone, 'scripts', 'build_qa_kit.py'), '--out-dir', out)
            if r.returncode:
                raise AssertionError('kit build failed: ' + r.stdout + r.stderr)
            with open(os.path.join(out, 'LotRadar-Win11-R3-QA-%s.zip' % cls.head[:7]), 'rb') as fh:
                cls.zips.append(fh.read())
        cls.z = zipfile.ZipFile(io.BytesIO(cls.zips[0]))
        cls.prefix = 'LotRadar-Win11-R3-QA-%s/' % cls.head[:7]

    @classmethod
    def tearDownClass(cls):
        cls.z.close()
        cls.tmp.cleanup()

    def read(self, name):
        return self.z.read(self.prefix + name)

    def test_deterministic(self):
        self.assertEqual(hashlib.sha256(self.zips[0]).hexdigest(), hashlib.sha256(self.zips[1]).hexdigest())

    def test_layout_and_checksums(self):
        names = sorted(n[len(self.prefix):] for n in self.z.namelist())
        for need in ('START_HERE.txt', 'RUN_WINDOWS11_TESTS.cmd', 'RUN_FULL_LAUNCH_TESTS.cmd', 'RUN_ONEDRIVE_TESTS.cmd',
                     'tools/Run-QAKit.ps1', 'tools/LotRadarQA.OneDrive.ps1', 'tools/Test-LotRadarInstaller.ps1',
                     'KIT_INFO.json', 'KIT_SHA256SUMS.txt'):
            self.assertIn(need, names)
        sums = {}
        for line in self.read('KIT_SHA256SUMS.txt').decode('ascii').splitlines():
            sha, rel = line.split('  ', 1)
            sums[rel] = sha
        self.assertEqual(sorted(sums), [n for n in names if n != 'KIT_SHA256SUMS.txt'])
        for rel, sha in sums.items():
            self.assertEqual(hashlib.sha256(self.read(rel)).hexdigest(), sha, rel)

    def test_provenance_matches_head(self):
        info = json.loads(self.read('KIT_INFO.json'))
        self.assertEqual(info['source_commit'], self.head)
        self.assertEqual(info['build_type'], 'development')
        pkg = self.read('package/' + info['package_file'])
        self.assertEqual(hashlib.sha256(pkg).hexdigest(), info['package_sha256'])
        man = json.loads(zipfile.ZipFile(io.BytesIO(pkg)).read('Install-Manifest.json'))
        self.assertEqual(man['source_commit'], self.head)
        self.assertEqual(man['build_type'], 'development')
        start = self.read('START_HERE.txt').decode('ascii')
        self.assertIn(self.head, start)
        self.assertIn(info['package_sha256'], start)
        self.assertNotIn('{{', start)

    def test_no_private_assets_anywhere(self):
        info = json.loads(self.read('KIT_INFO.json'))
        inner = zipfile.ZipFile(io.BytesIO(self.read('package/' + info['package_file']))).namelist()
        for n in list(self.z.namelist()) + inner:
            self.assertNotIn(n.lower().rsplit('/', 1)[-1], PRIVATE, n)

    def test_windows_text_files_ascii_crlf(self):
        for rel in ('START_HERE.txt', 'RUN_WINDOWS11_TESTS.cmd', 'RUN_FULL_LAUNCH_TESTS.cmd', 'RUN_ONEDRIVE_TESTS.cmd',
                    'tools/Run-QAKit.ps1', 'tools/LotRadarQA.OneDrive.ps1', 'tools/Test-LotRadarInstaller.ps1'):
            data = self.read(rel)
            data.decode('ascii')
            self.assertEqual(data.count(b'\n'), data.count(b'\r\n'), rel + ' has bare LF line endings')

    def test_launchers_use_relative_paths_and_builtin_powershell(self):
        for rel in ('RUN_WINDOWS11_TESTS.cmd', 'RUN_FULL_LAUNCH_TESTS.cmd', 'RUN_ONEDRIVE_TESTS.cmd'):
            text = self.read(rel).decode('ascii')
            self.assertIn('%~dp0tools\\Run-QAKit.ps1', text)
            self.assertIn('%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe', text)
            self.assertIn('exit /b %RC%', text)
            self.assertNotIn('C:\\Users', text)
        self.assertIn('-FullLaunch', self.read('RUN_FULL_LAUNCH_TESTS.cmd').decode('ascii'))
        self.assertNotIn('-FullLaunch', self.read('RUN_WINDOWS11_TESTS.cmd').decode('ascii'))
        self.assertNotIn('-OneDrive', self.read('RUN_WINDOWS11_TESTS.cmd').decode('ascii'))
        self.assertNotIn('-OneDrive', self.read('RUN_FULL_LAUNCH_TESTS.cmd').decode('ascii'))
        self.assertIn('-OneDrive', self.read('RUN_ONEDRIVE_TESTS.cmd').decode('ascii'))

    def test_runner_guards_present(self):
        text = self.read('tools/Run-QAKit.ps1').decode('ascii')
        for needle in ('IsInRole', 'KIT_SHA256SUMS.txt', 'source_commit', '8765', 'shortcut-backup',
                       'Type YES', 'Protect-Text', 'ParseFile'):
            self.assertIn(needle, text)

    def test_r3_requires_link_refusal(self):
        text = self.read('tools/Test-LotRadarInstaller.ps1').decode('ascii')
        r3 = text[text.index("Invoke-Test 'R3'"):text.index("Invoke-Test 'R4'")]
        self.assertIn("LinkType -eq 'SymbolicLink'", r3)
        self.assertIn("-match 'link/reparse point'", r3)
        self.assertIn("-notmatch 'checksum mismatch'", r3)
        self.assertIn('BLOCKED:', r3)
        # The fixture target carries the original (manifest-valid) bytes, so only the link check can refuse it.
        self.assertIn('outside copy does not match the manifest hash', r3)


    def test_onedrive_mode_is_opt_in_local_results_and_disclosed(self):
        sentence = ('LotRadar vehicle photos and Facebook photo exports stay local; only the disposable '
                    'installer-compatibility test fixture is placed in OneDrive.')
        flat = lambda b: ' '.join(b.decode('ascii').split())
        for rel in ('START_HERE.txt', 'RUN_ONEDRIVE_TESTS.cmd', 'tools/LotRadarQA.OneDrive.ps1'):
            self.assertIn(sentence, flat(self.read(rel)), rel)
        runner = self.read('tools/Run-QAKit.ps1').decode('ascii')
        self.assertIn("if ($OneDrive) { $resultsDir = Join-Path ([Environment]::GetFolderPath('LocalApplicationData'))", runner)
        od = self.read('tools/LotRadarQA.OneDrive.ps1').decode('ascii')
        for needle in ("Read-Host 'Type YES to allow the OneDrive test'", 'LOCAL_PHOTO_STORAGE', 'HKCU:\\Software\\Microsoft\\OneDrive\\Accounts',
                       'GetFinalPathNameByHandleW', "'LotRadar QA TEST ONLY *'", 'LOTRADAR_QA_TEST_FOLDER.txt', 'rmdir /s /q',
                       'PC1 ', 'PC2 ', 'PC3 ', 'Invoke-Native'):
            self.assertIn(needle, od)
        # never changes OneDrive state or real files
        for banned in ('attrib ', '+U', '-P ', 'Set-ItemProperty', 'Remove-Item -LiteralPath $realData', 'Move-Item'):
            self.assertNotIn(banned, od)

    def test_onedrive_module_never_exits_and_runner_stops_after_it(self):
        # Regression (Windows 11 run 2026-11-17): 'exit' inside the dot-sourced module only ended the module, so the
        # runner fell through into a normal run, overwrote the OneDrive SUMMARY.txt and returned that run's exit code.
        import re
        od = self.read('tools/LotRadarQA.OneDrive.ps1').decode('ascii')
        code = '\n'.join(l for l in od.splitlines() if not l.lstrip().startswith('#'))
        self.assertIsNone(EXIT_STMT.search(code), 'module must not call exit')
        self.assertNotIn('Stop-Kit', code)
        self.assertIn('$script:OneDriveExit', code)
        runner = self.read('tools/Run-QAKit.ps1').decode('ascii')
        i = runner.index(". (Join-Path $PSScriptRoot 'LotRadarQA.OneDrive.ps1')")
        self.assertIn('exit $script:OneDriveExit', runner[i:i + 200])

    def test_harness_extract_to_and_outdir(self):
        text = self.read('tools/Test-LotRadarInstaller.ps1').decode('ascii')
        for needle in ("[string]$ExtractTo = ''", "[string]$OutDir = ''", "Add-Result 'OD0'", "Invoke-Test 'OD1'",
                       "$dst = Join-Path $pkgRoot ('pkg ' + $Name)", 'ftCreationLow'):
            self.assertIn(needle, text)
        self.assertNotIn('public long ft', text)


if __name__ == '__main__':
    unittest.main()
