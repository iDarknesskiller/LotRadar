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
                     'RUN_CLEANUP_SAFETY_TESTS.cmd', 'tools/LotRadarQA.Cleanup.ps1', 'tools/LotRadarQA.CleanupSelfTest.ps1',
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
                    'RUN_CLEANUP_SAFETY_TESTS.cmd', 'tools/LotRadarQA.Cleanup.ps1', 'tools/LotRadarQA.CleanupSelfTest.ps1',
                    'tools/Run-QAKit.ps1', 'tools/LotRadarQA.OneDrive.ps1', 'tools/Test-LotRadarInstaller.ps1'):
            data = self.read(rel)
            data.decode('ascii')
            self.assertEqual(data.count(b'\n'), data.count(b'\r\n'), rel + ' has bare LF line endings')

    def test_launchers_use_relative_paths_and_builtin_powershell(self):
        for rel in ('RUN_WINDOWS11_TESTS.cmd', 'RUN_FULL_LAUNCH_TESTS.cmd', 'RUN_ONEDRIVE_TESTS.cmd', 'RUN_CLEANUP_SAFETY_TESTS.cmd'):
            text = self.read(rel).decode('ascii')
            self.assertIn('%~dp0tools\\Run-QAKit.ps1', text)
            self.assertIn('%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe', text)
            self.assertIn('exit /b %RC%', text)
            self.assertNotIn('C:\\Users', text)
        self.assertIn('-FullLaunch', self.read('RUN_FULL_LAUNCH_TESTS.cmd').decode('ascii'))
        self.assertNotIn('-FullLaunch', self.read('RUN_WINDOWS11_TESTS.cmd').decode('ascii'))
        self.assertNotIn('-OneDrive', self.read('RUN_WINDOWS11_TESTS.cmd').decode('ascii'))
        self.assertNotIn('-OneDrive', self.read('RUN_FULL_LAUNCH_TESTS.cmd').decode('ascii'))
        self.assertIn('-OneDrive -Yes', self.read('RUN_ONEDRIVE_TESTS.cmd').decode('ascii'))
        self.assertIn('-FullLaunch -Yes', self.read('RUN_FULL_LAUNCH_TESTS.cmd').decode('ascii'))
        self.assertNotIn('-Yes', self.read('RUN_WINDOWS11_TESTS.cmd').decode('ascii'))
        runner = self.read('tools/Run-QAKit.ps1').decode('ascii')
        self.assertIn('close this window now', runner)                  # disclosure + cancel window remain
        self.assertIn("(Read-Host ('Type YES to start the ' + $What)) -eq 'YES'", runner)  # without -Yes a typed YES is still required

    def test_runner_guards_present(self):
        text = self.read('tools/Run-QAKit.ps1').decode('ascii')
        for needle in ('IsInRole', 'KIT_SHA256SUMS.txt', 'source_commit', '8765', 'shortcut-backup',
                       'function Confirm-Start', 'Protect-Text', 'ParseFile'):
            self.assertIn(needle, text)

    def test_r3_requires_link_refusal(self):
        text = self.read('tools/Test-LotRadarInstaller.ps1').decode('ascii')
        r3 = text[text.index("Invoke-Test 'R3'"):text.index("Invoke-Test 'R4'")]
        self.assertIn("LinkType -eq 'SymbolicLink'", r3)
        self.assertIn("-match '(?s)link/reparse point.*requirements\\.txt'", r3)
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
        for needle in ("if (-not (Confirm-Start 'OneDrive test'))", 'LOCAL_PHOTO_STORAGE', 'HKCU:\\Software\\Microsoft\\OneDrive\\Accounts',
                       'GetFinalPathNameByHandleW', "('LotRadar QA TEST ONLY '", 'LOTRADAR_QA_TEST_FOLDER.txt',
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


    def test_onedrive_fix_harness_cases(self):
        text = self.read('tools/Test-LotRadarInstaller.ps1').decode('ascii')
        for needle in ("Invoke-Test 'R6'", "mklink /D", "Invoke-Test 'OD2'", "Add-Result 'OD3'",
                       "New-PkgCopy 'r1' -WaitCloud", "New-PkgCopy 'r3' -WaitCloud", "New-PkgCopy 'r6' -WaitCloud",
                       'function Wait-CloudTag', ' tag=', "installer ACCEPTED a cloud-tagged destination"):
            self.assertIn(needle, text)
        od2 = text[text.index("Invoke-Test 'OD2'"):text.index("Add-Result 'OD3'")]
        self.assertIn('$env:LOCALAPPDATA = $odLocal', od2)
        self.assertIn('finally { $env:LOCALAPPDATA = $local }', od2)   # sandbox env always restored
        self.assertIn("return ('BLOCKED:", od2)                         # never a PASS without a real cloud tag

    def test_startup_window_harness_cases(self):
        text = self.read('tools/Test-LotRadarInstaller.ps1').decode('ascii')
        for tid in ('G1', 'G2', 'G3', 'G4', 'G5', 'G6', 'G7', 'G8', 'G9', 'G10'):
            self.assertIn("Invoke-Test '" + tid + "'", text)
        self.assertIn("'-AutoCloseSeconds', [string]$AutoClose, '-ResultFile'", text)
        g10 = text[text.index("Invoke-Test 'G10'"):]
        self.assertIn('Send-StartupTestKey $p 0x0106 0x63', g10)
        self.assertIn("$w.Result.console_shown -eq $true", g10)
        g9 = text[text.index("Invoke-Test 'G9'"):text.index("Invoke-Test 'G10'")]
        self.assertIn("Assert-True ($alive -ge 1)", g9)
        g4 = text[text.index("Invoke-Test 'G4'"):text.index("Invoke-Test 'G5'")]
        self.assertIn("$w.Result.health -ne $true", g4)               # forged ready never accepted
        g6 = text[text.index("Invoke-Test 'G6'"):text.index("Invoke-Test 'G7'")]
        self.assertIn("Where-Object { $_ -eq 'open:complete' }).Count -eq 1", g6)   # browser opened exactly once
        self.assertIn('Assert-True $held', g6)                              # launch lock still held by the bootstrap
        info = json.loads(self.read('KIT_INFO.json'))
        inner = zipfile.ZipFile(io.BytesIO(self.read('package/' + info['package_file'])))
        self.assertIn('MarketplaceScanner/startup/Show-LotRadarStartup.ps1', inner.namelist())

    def test_no_bare_count_on_function_results(self):
        # Windows run of a3fe6bb: (Get-ServerRoots).Count was EMPTY when exactly one process matched (PowerShell 5.1
        # unrolls a 1-item result to a single CimInstance, which has no intrinsic .Count). Always wrap in @().
        text = self.read('tools/Test-LotRadarInstaller.ps1').decode('ascii')
        self.assertIsNone(re.search(r'(?<!@)\(Get-[A-Za-z]+(?: [^()]*)?\)\.Count', text))

    def test_full_launch_checks_clean_stop(self):
        text = self.read('tools/Test-LotRadarInstaller.ps1').decode('ascii')
        f5 = text[text.index("Invoke-Test 'F5'"):]
        f5 = f5[:f5.index('} catch {')]
        for needle in ("-not (Test-PortBusy)", "$script:launchProc.HasExited", "'marketplace-launch.lock'), 'OpenOrCreate', 'ReadWrite', 'None')",
                       "$lock.Dispose()", "no graceful-quit path exists yet"):
            self.assertIn(needle, f5)
        for tid in ("'F1'", "'F4'"):
            self.assertIn('Invoke-Test ' + tid, text)

    def test_destination_preflight_harness_cases(self):
        text = self.read('tools/Test-LotRadarInstaller.ps1').decode('ascii')
        for tid, var in (("'R7'", 'New-Junction $userRoot $sent'), ("'R8'", 'New-Junction $runtimeDir $sent')):
            seg = text[text.index('Invoke-Test ' + tid):]
            seg = seg[:seg.index('Invoke-Test ', 10)]
            self.assertIn(var, seg)
            self.assertIn('Assert-SentinelIntact $sent', seg)   # nothing created through the link
            self.assertIn('Assert-Unchanged $good', seg)
            self.assertIn('Move-Item -LiteralPath $saved -Destination', seg)  # sandbox restored in finally
        od2 = text[text.index("Invoke-Test 'OD2'"):text.index("Add-Result 'OD3'")]
        self.assertIn("(Join-Path $odLocal 'MarketplaceScanner')", od2)

    def test_onedrive_pass_requires_cloud_tag_and_destination_refusal(self):
        od = self.read('tools/LotRadarQA.OneDrive.ps1').decode('ascii')
        self.assertIn("$od.Exit -eq 0 -and ($od0 -match 'dir:cloud') -and ($od2 -like 'PASS*')", od)
        self.assertIn('INCONCLUSIVE (not a pass)', od)
        for row in ("'R6'", "'OD2'", "'OD3'"):
            self.assertIn('Get-Row $od.Rows ' + row, od)


    def test_leftover_cleanup_is_ownership_proven_consented_and_never_recursive(self):
        # Architect b150a4d step 2: no unattended recursive delete; delete only proven kit-created folders.
        runner = self.read('tools/Run-QAKit.ps1').decode('ascii')
        rep = runner[runner.index('# ---- 6a.'):runner.index("$shortcutBackup = Join-Path $resultsDir")]
        self.assertIn('Invoke-QALeftoverRepair', rep)
        self.assertIn('Another LotRadar test run is still running', rep)   # never cleans under a live run
        self.assertIn('-Ask { param($q) Read-QAAnswer $q }', rep)
        self.assertIn('Stop-Kit $repair.Stop 11', rep)
        self.assertIn("'Leftover repair : '", runner)
        cl = self.read('tools/LotRadarQA.Cleanup.ps1').decode('ascii')
        od = self.read('tools/LotRadarQA.OneDrive.ps1').decode('ascii')
        code = lambda t: '\n'.join(l for l in t.splitlines() if not l.lstrip().startswith('#'))
        for name, text in (('runner', runner), ('cleanup', cl), ('onedrive', od)):
            self.assertNotIn('rmdir', code(text).lower(), name)
            self.assertNotIn('-Recurse', code(text), name)
            self.assertIsNone(re.search(r'Directory\]::Delete\([^)]*\$true', code(text)), name + ': recursive Directory.Delete')
        # ownership proof: name pattern, canonical containment, link refusal, token marker + ledger match
        for needle in ("'^LotRadar Test Sandbox [0-9a-f]{8}$'", "'^LotRadar QA TEST ONLY [0-9a-f]{8}$'",
                       '0x02000000 | 0x00200000', 'FinalFollow($Parent)', "'its real path is not directly inside the expected folder'",
                       "'(?m)^token=([0-9a-f]{32})\\r?$'", "'its token is not in this PC''s kit ledger'",
                       "'ledger records a different path for this token'", "('contains a link: '",
                       "'it holds the only copy of a Desktop shortcut backup'", 'RNGCryptoServiceProvider',
                       "if ($ans.Trim() -eq 'D')", 'if ([Console]::IsInputRedirected) { return \'\' }',
                       'Test-QAChainSafe', '[IO.Directory]::Delete($Path, $false)'):
            self.assertIn(needle, cl)
        # shortcut: restored only from a backup verified to target the standard launcher; otherwise ask or stop
        self.assertIn('(Test-QASamePath (Get-QAShortcutTarget $c[0]) $StandardTarget)', cl)
        self.assertIn('this kit has no record of', cl)
        # the harness records ownership of its sandbox and forgets it only once the sandbox is gone
        h = self.read('tools/Test-LotRadarInstaller.ps1').decode('ascii')
        self.assertIn("'LOTRADAR_QA_OWNER.txt'", h)
        self.assertIn("'LotRadar QA Results\\owned'", h)
        self.assertIn('-not (Test-Path -LiteralPath $root) -and (Test-Path -LiteralPath $qaLedgerFile)', h)
        # the OneDrive module creates its folder with an ownership record and removes it with the same safe deleter
        self.assertIn("New-QAOwnedFolder $odTestDir 'onedrive'", od)
        self.assertIn('Remove-QAOwnedFolder $own $odParent', od)

    def test_harness_records_cleanup_outcome(self):
        """PR #5 fix A: a sandbox left behind must be a CLN1 FAIL row (exit 1), never only a console NOTE."""
        h = self.read('tools/Test-LotRadarInstaller.ps1').decode('ascii')
        f = h[h.index('function Complete-SandboxCleanup'):]
        f = f[:f.index('\r\n}\r\n') + 3]
        self.assertEqual(f.count("Add-Result 'CLN1'"), 4)                  # PASS / INFO operator / INFO shortcut / FAIL
        for status in ("'PASS' 'no sandbox folder left'", "'INFO' 'kept on purpose: -KeepSandbox",
                       "'INFO' 'kept on purpose: it holds the only backup of your Desktop shortcut", "'FAIL' ('sandbox NOT removed"):
            self.assertIn(status, f)
        self.assertIn("Replace($root, '<sandbox>')", f)                      # first error masked
        self.assertIn("Replace($env:USERPROFILE, '%USERPROFILE%')", f)
        self.assertIn('NOTE: sandbox not fully removed', f)                   # console note kept for operators
        # A2: the ownership marker is deleted LAST (a failed delete keeps the kit's ownership proof), the folder itself
        # non-recursively, and the FAIL text only promises a kit repair when marker AND ledger entry are still there
        kids = f.index("Where-Object { $_.Name -ne 'LOTRADAR_QA_OWNER.txt' }")
        self.assertLess(kids, f.index('Remove-Item -LiteralPath $ownerMarker -Force -ErrorAction Stop'))
        self.assertLess(f.index('Remove-Item -LiteralPath $ownerMarker -Force -ErrorAction Stop'),
                        f.index('Remove-Item -LiteralPath $root -Force -ErrorAction Stop'))
        self.assertNotIn('Remove-Item -LiteralPath $root -Recurse', f)
        self.assertIn("(Test-Path -LiteralPath $ownerMarker) -and $qaLedgerFile -and (Test-Path -LiteralPath $qaLedgerFile)", f)
        self.assertIn('so the next kit run can offer to remove it', f)
        self.assertIn('the kit cannot prove it is a test folder: check it and delete it by hand', f)
        self.assertNotIn('it stays recorded so the kit can offer', f)            # the old, unconditional promise is gone
        self.assertIn('-not (Test-Path -LiteralPath $root) -and (Test-Path -LiteralPath $qaLedgerFile)', f)  # ledger kept while folder exists
        # recorded in the final block AFTER the processes are stopped and BEFORE totals, exit code and JSON
        fin = h[h.rindex('} finally {'):]
        call = fin.index('Complete-SandboxCleanup -root $root -OperatorKeep $operatorKeepSandbox -ProtectKeep $shortcutProtectKeep')
        self.assertLess(fin.index('try { Stop-SandboxProcesses }'), call)
        self.assertLess(call, fin.index('$fail = @($script:Results'))
        self.assertLess(call, fin.index('WriteAllText($jsonPath'))
        self.assertIn('if ($fail -gt 0) { exit 1 }', h)
        # the operator switch is never overwritten; the shortcut-protection keep has its own flag
        self.assertIn('$operatorKeepSandbox = [bool]$KeepSandbox', h)
        self.assertIn('$shortcutProtectKeep = $true', h)
        self.assertNotIn('$KeepSandbox = $true', h)
        self.assertNotIn('Stop-Process', f)
        self.assertNotIn('taskkill', f)
        # the runner already turns a nonzero harness exit and FAIL rows into its own FAIL summary and exit 1
        runner = self.read('tools/Run-QAKit.ps1').decode('ascii')
        self.assertIn("' FAIL=' + @($rows | Where-Object { $_.Status -eq 'FAIL' }).Count", runner)
        self.assertIn('if ($harnessExit -ne 0) { exit 1 }', runner)

    def test_cleanup_selftest_mode(self):
        launcher = self.read('RUN_CLEANUP_SAFETY_TESTS.cmd').decode('ascii')
        self.assertIn('-CleanupSelfTest -Yes', launcher)
        self.assertIn('%~dp0tools\\Run-QAKit.ps1', launcher)
        runner = self.read('tools/Run-QAKit.ps1').decode('ascii')
        i = runner.index(". (Join-Path $PSScriptRoot 'LotRadarQA.CleanupSelfTest.ps1')")
        self.assertIn('exit $script:CleanupExit', runner[i:i + 200])
        self.assertLess(i, runner.index('$repair = Invoke-QALeftoverRepair'))   # self-test never runs the real repair
        st = self.read('tools/LotRadarQA.CleanupSelfTest.ps1').decode('ascii')
        for mod in (st, self.read('tools/LotRadarQA.Cleanup.ps1').decode('ascii')):
            code = '\n'.join(l for l in mod.splitlines() if not l.lstrip().startswith('#'))
            self.assertIsNone(EXIT_STMT.search(code), 'module must not call exit')
            self.assertNotIn('Stop-Kit', code)
        ids = sorted(set(re.findall(r"'(CL\d\d)'", st)))
        self.assertEqual(ids, ['CL%02d' % n for n in range(1, 24)])
        # fixtures never receive the real Desktop shortcut, real store or real ledger
        rep = st[st.index('function Invoke-Repair'):st.index('function Get-LedgerFileFor')]
        self.assertIn('-DesktopLnk $F.Desk', rep)
        self.assertIn('-OriginalStore $F.Store', rep)
        self.assertIn('-LedgerDir $F.Ledger', rep)
        self.assertNotIn('$desktopLnk', rep)
        # PR #5 fix B: OneDrive cases are a SEPARATE, default-No question that the launcher's -Yes cannot answer
        code = '\n'.join(l for l in st.splitlines() if not l.lstrip().startswith('#'))
        # B3: Confirm-Start (which honours -Yes) is used exactly once, only to START the local run (10 s countdown),
        # after the OneDrive question and before the first fixture; it never decides the OneDrive cases
        self.assertEqual(code.count('Confirm-Start'), 1)
        local = code.index("Confirm-Start 'cleanup self-test (local synthetic checks only)'")
        self.assertLess(code.index('$useOneDrive = Get-QAOneDriveChoice'), local)
        self.assertLess(local, code.index("New-QAOwnedFolder $script:ClCtr 'sandbox'"))
        self.assertFalse([l for l in code.splitlines() if 'useOneDrive' in l and 'Confirm-Start' in l])
        self.assertIn('$script:CleanupExit = 9', code)                         # cancelled -> runner exit 9
        self.assertIn('function Get-QAOneDriveChoice([scriptblock]$Ask)', st)
        self.assertIn("-cmatch '^\\s*[Yy]\\s*$'", st)                          # only Y / y includes them
        self.assertIn('catch { $answer = \'\' }', st)                           # no console / error -> skip
        # B2: the question leads with the safe default; the opt-in comes last and is conditional
        self.assertIn("$useOneDrive = Get-QAOneDriveChoice { Read-QAAnswer 'OneDrive cases: press Enter to SKIP them (recommended). "
                      "Type Y only if you were asked to include them' }", st)
        self.assertNotIn('Type Y and press Enter to include them', st)
        gate = code.index('if (-not $useOneDrive) {')
        self.assertEqual(code.count("New-QAOwnedFolder $odCtr 'onedrive'"), 1)
        self.assertLess(gate, code.index("New-QAOwnedFolder $odCtr 'onedrive'"))   # the only cloud write is behind the choice
        self.assertIn('online recycle bin', st)                                     # disclosed before the question
        self.assertLess(st.index('online recycle bin'), st.index('$useOneDrive = Get-QAOneDriveChoice'))
        flat = lambda b: ' '.join(b.decode('ascii').split())
        for rel in ('RUN_CLEANUP_SAFETY_TESTS.cmd', 'START_HERE.txt'):
            self.assertIn('press Enter to SKIP them (recommended). Type Y only if you were asked to include them.', flat(self.read(rel)), rel)
        self.assertIn('your OK for the LOCAL checks only', flat(self.read('RUN_CLEANUP_SAFETY_TESTS.cmd')))
        # unchanged: the OneDrive installer test keeps its own double-click consent
        self.assertIn('-OneDrive -Yes', self.read('RUN_ONEDRIVE_TESTS.cmd').decode('ascii'))

    def test_manual_ui_modes(self):
        """Architect 51fcd34: Stage A preview (nothing started) and Stage B guided real start in an owned sandbox."""
        prev = self.read('RUN_UI_PREVIEW.cmd').decode('ascii')
        man = self.read('RUN_MANUAL_UI_TESTS.cmd').decode('ascii')
        self.assertIn('-UiPreview -Yes', prev)
        self.assertIn('-ManualUI -Yes', man)
        runner = self.read('tools/Run-QAKit.ps1').decode('ascii')
        self.assertIn('$FullLaunch, $OneDrive, $CleanupSelfTest, $UiPreview, $ManualUI', runner)   # one mode at a time
        i = runner.index(". (Join-Path $PSScriptRoot 'LotRadarQA.ManualUI.ps1')")
        self.assertIn('exit $script:ManualExit', runner[i:i + 200])
        self.assertLess(runner.index('$busy) { Stop-Kit'), i)                 # port 8765 busy -> stop first
        self.assertLess(runner.index('$repair = Invoke-QALeftoverRepair'), i)
        self.assertLess(i, runner.index('# ---- 8. optional full launch needs explicit consent'))
        m = self.read('tools/LotRadarQA.ManualUI.ps1').decode('ascii')
        code = '\n'.join(l for l in m.splitlines() if not l.lstrip().startswith('#'))
        self.assertIsNone(EXIT_STMT.search(code), 'module must not call exit')
        # Stage A: only the GUI script is taken out of the verified package and it runs with -Preview
        a = m[m.index('if ($UiPreview) {'):m.index('# ===', m.index('if ($UiPreview) {'))]
        self.assertIn("GetEntry('MarketplaceScanner/startup/Show-LotRadarStartup.ps1')", a)
        self.assertIn("'-Preview'", a)
        self.assertIn("'-ResultFile'", a)
        self.assertIn("Add-M 'E4a'", a)                             # automatic cut-off check reported
        self.assertIn("Add-M 'E0' 'Appearance matches the approved minimal design", a)
        self.assertIn('the automatic check found text cut off', a)  # a person's yes cannot override it
        for banned in ('Install-LotRadar', 'Expand-KitPackage', 'TcpListener', 'taskkill', 'Confirm-Start'):
            self.assertNotIn(banned, a)
        b = m[m.index('# ---- B0'):]
        # never WinGet/Python install; BLOCKED without an existing Python; WinGet hidden from the test start
        self.assertNotIn('winget install', b.lower())
        self.assertIn("'BLOCKED'", b)
        self.assertIn('Microsoft\\WindowsApps=%', b)
        self.assertIn('where winget.exe', b)
        self.assertNotIn('--scope user', b)
        # owned sandbox, removed only by the ownership-proving deleter; no recursive deletes, no name-based kills
        self.assertIn("New-QAOwnedFolder $sandbox 'sandbox'", b)
        self.assertIn('Test-QAOwnedFolder $sandbox', b)
        self.assertIn('Remove-QAOwnedFolder $own', b)
        self.assertNotIn('-Recurse -Force', b)
        self.assertNotIn('Remove-Item -LiteralPath $sandbox', b)
        self.assertNotIn('/IM', b)
        self.assertNotIn('Stop-Process', b)
        self.assertIn("$_.CommandLine -like ('*' + $sbLocal + '*')", b)    # only processes inside the sandbox
        self.assertIn('taskkill.exe /PID $s.ProcessId', b)
        # the E6 conflict is our own loopback listener, always stopped
        self.assertIn('[Net.IPAddress]::Loopback, 8765', b)
        self.assertIn('if ($listener) { try { $listener.Stop() }', b)
        # real shortcut restored byte-identical; real program/data/runtime/OneDrive fingerprinted before and after
        self.assertIn('Copy-Item -LiteralPath $lnkBackup -Destination $desktopLnk -Force', b)
        self.assertIn('(Get-Sha $desktopLnk) -eq $lnkSha', b)
        for k in ('$after.Program -eq $before.Program', '$after.Data -eq $before.Data', '$odAfter -eq $odBefore', '$lnkNow -eq $before.Shortcut'):
            self.assertIn(k, b)
        # install runs with sandbox LOCALAPPDATA/APPDATA and the environment is put back
        self.assertIn('$env:LOCALAPPDATA = $sbLocal; $env:APPDATA = $sbRoam', b)
        self.assertIn('finally { foreach ($k in $savedEnv.Keys)', b)
        # the test shortcut is removed only when it points into this sandbox
        self.assertIn('$t.StartsWith($sandbox, [StringComparison]::OrdinalIgnoreCase)', b)
        self.assertIn('Confirm-Start', b)
        for case in ("'E1'", "'E2'", "'E5'", "'E6'", "'B9'"):
            self.assertIn(case, b)

    def test_preview_physical_rows_are_sixteen_distinct_named_rows(self):
        """LR-010-05: without a leading comma PowerShell flattens nested @(...) rows, so the Owner saw blank prompts.
        Every physical row must be its own ,@(run,'ID','instruction') element, with 16 unique IDs across runs 1-5."""
        m = self.read('tools/LotRadarQA.ManualUI.ps1').decode('ascii').replace('\r\n', '\n')
        start = m.index('$steps = @(')
        block = m[start:m.index('\n    )', start)]
        entries = [l.strip() for l in block.splitlines()[1:] if l.strip()]
        self.assertTrue(entries)
        for line in entries:
            self.assertTrue(line.startswith(',@('), 'row is not wrapped with a leading comma (would be flattened): ' + line)
        rows = re.findall(r"^,@\(([1-5]),'(P-[A-Z0-9-]+)','([^']{10,})'\)$", '\n'.join(entries), re.M)
        self.assertEqual(len(rows), len(entries), 'every row must be (run, ID, instruction)')
        ids = [r[1] for r in rows]
        self.assertEqual(len(ids), 16)
        self.assertEqual(len(set(ids)), 16, 'duplicate physical row ID')
        self.assertEqual(sorted({int(r[0]) for r in rows}), [1, 2, 3, 4, 5])
        self.assertIn("throw 'Incomplete physical row evidence'", m)   # run-time guard against missing/duplicate rows

    def test_real_input_driver_covers_the_same_sixteen_rows_safely(self):
        """LR-010 automated physical rows: tests/windows/Test-StartupRealInput.ps1 must cover exactly the 16 P IDs of the
        manual preview, use real system input (SendInput), check the foreground before every input, save rows at once,
        and stop only the processes it started."""
        drv = open(os.path.join(ROOT, 'tests', 'windows', 'Test-StartupRealInput.ps1'), 'rb').read()
        drv.decode('ascii')
        d = drv.decode('ascii')
        manual = self.read('tools/LotRadarQA.ManualUI.ps1').decode('ascii')
        manual_ids = set(re.findall(r",@\([1-5],'(P-[A-Z0-9-]+)'", manual))
        driver_ids = set(re.findall(r"Add-Row '(P-[A-Z0-9-]+)'", d))
        self.assertEqual(len(manual_ids), 16)
        self.assertEqual(driver_ids, manual_ids)
        self.assertIn("qa-kit\\LotRadarQA.RealInput.ps1", d)  # shared guarded input module
        self.assertIn("'-Preview'", d)                       # nothing is installed or started
        ri = open(os.path.join(ROOT, 'tests', 'windows', 'qa-kit', 'LotRadarQA.RealInput.ps1'), 'rb').read().decode('ascii')
        self.assertIn('SendInput', ri)
        self.assertGreaterEqual(ri.count('Assert-RIForeground $WantPid'), 3)   # Send-RIKeys and Send-RIHeldKey (also per repeat)
        self.assertIn('PidAt(', ri)                            # clicks only on a test window
        self.assertIn('Add-Content -LiteralPath $rowsFile', d) # each row saved immediately
        self.assertIn('foreach ($id in @($script:Owned))', d)  # cleanup limited to own processes
        self.assertNotIn('MarketplaceScanner', d)              # never touches live data

    def test_auto_input_stage_b_replaces_the_person_safely(self):
        """LR-010 automated session R: -AutoInput works only with -ManualUI, the shared real-input module is in the kit,
        every R row is produced without Read-YesNo/Wait-Key, and windows are only closed by WM_CLOSE when proven new."""
        run = self.read('tools/Run-QAKit.ps1').decode('ascii')
        self.assertIn('[switch]$AutoInput', run)
        self.assertIn("if ($AutoInput -and -not $ManualUI) { Stop-Kit", run)
        ri = self.read('tools/LotRadarQA.RealInput.ps1').decode('ascii')
        self.assertIn('function Assert-RIForeground', ri)
        self.assertIn('Assert-RINoHeldModifiers; Assert-RIForeground $WantPid', ri)
        self.assertIn("throw \"BLOCKED: the click point is covered", ri)
        self.assertNotIn('Stop-Process', ri)
        self.assertNotIn('taskkill', ri)
        cmd = self.read('RUN_AUTOMATED_REAL_TESTS.cmd').decode('ascii')
        self.assertIn('-ManualUI -AutoInput -Yes', cmd)
        m = self.read('tools/LotRadarQA.ManualUI.ps1').decode('ascii')
        auto = m[m.index('    if ($AutoInput) {\r\n    function Add-AutoRow'):m.index('    function Read-RealRow')]
        for rid in ('R-F5-FAIL', 'R-ALTC-RETURN', 'R-F5-OK', 'R-CLICK-PARITY', 'R-GUARD'):
            self.assertIn("'" + rid + "'", auto)
        self.assertNotIn('Read-YesNo', auto)
        self.assertNotIn('Wait-Key', auto)
        self.assertNotIn('Read-Host', auto)
        self.assertIn('$Snapshot -notcontains', m)   # only app windows that appeared after this launch are closed
        self.assertIn("-not $AutoInput) {", m)       # E1/E2 (person-only checks) are skipped in automatic mode

    def test_gui_cases_cleanup_never_fails_and_report_console_diag(self):
        """Windows 11 run of dc4244e: G9 failed on taskkill "not found" under ErrorActionPreference Stop."""
        h = self.read('tools/Test-LotRadarInstaller.ps1').decode('ascii')
        f = h[h.index('function Stop-GuiTestProcesses'):]
        f = f[:f.index('\r\n}')]
        self.assertIn("$ErrorActionPreference = 'Continue'", f)
        self.assertNotIn('Get-ProcessesMentioning $gDir | ForEach-Object { & taskkill', h)
        self.assertGreaterEqual(h.count('Stop-GuiTestProcesses'), 6)
        g10 = h[h.index("Invoke-Test 'G10'"):]
        self.assertIn('console_diag', g10)
        self.assertIn('Send-StartupTestKey $p 0x0100 0x1B', g10)
        self.assertNotIn('SendKeys', g10)
        self.assertIn("$w.Result.console_diag -match 'click'", g10)
        g3 = h[h.index("Invoke-Test 'G3'"):h.index("Invoke-Test 'G4'")]
        self.assertIn("$w.Result.clipped -eq ''", g3)
        # screenshots: visible frame only (no slivers of the desktop behind the window)
        self.assertIn('DwmGetWindowAttribute($h, 9, [ref]$r, 16)', h)
        mu = self.read('tools/LotRadarQA.ManualUI.ps1').decode('ascii')
        self.assertIn('DwmGetWindowAttribute($h, 9, [ref]$r, 16)', mu)
        # the window draws itself (PrintWindow): overlapping windows can never be captured
        for src in (h, mu):
            self.assertNotIn('CopyFromScreen', src)
            self.assertIn('PrintWindow($h, $hdc, 2)', src)
        self.assertIn('SIGN OUT of Windows and back in', mu)

if __name__ == '__main__':
    unittest.main()
