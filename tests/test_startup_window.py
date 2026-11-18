"""Static checks of the PR #5 startup window. Its behaviour is exercised on Windows by tests/windows (G cases)."""
import os, re, unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(REPO, 'startup', 'Show-LotRadarStartup.ps1')


class TestStartupWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(PATH, 'rb') as h:
            cls.raw = h.read()
        cls.text = cls.raw.decode('ascii')
        cls.code = '\n'.join(l for l in cls.text.splitlines() if not l.lstrip().startswith('#'))

    def test_ascii_and_packaged(self):
        self.raw.decode('ascii')
        with open(os.path.join(REPO, 'scripts', 'build_installer.py'), encoding='utf-8') as h:
            self.assertIn("'startup/Show-LotRadarStartup.ps1'", h.read())

    def test_never_owns_server_lock_or_browser(self):
        c = self.code
        for banned in ('Open-LotRadarWindow', '--app=', 'server.py', 'marketplace-launch.lock', 'python.exe -',
                       'Stop-Process', 'Remove-Item -LiteralPath $runtimeDir', '-Recurse'):
            self.assertNotIn(banned, c)
        # it starts only the existing launcher, on its console path, with the nonce
        self.assertIn("$env:LOTRADAR_STARTUP_GUI = '0'", c)
        self.assertIn('$env:LOTRADAR_STARTUP_NONCE = $script:Nonce', c)
        self.assertEqual(len(re.findall(r'Start-Process ', c)), 1)
        self.assertIn("Start-Process -FilePath $comSpec -ArgumentList ('/d /c \"\"' + $launcher + '\"\"')", c)
        self.assertNotIn('conhost.exe', c)   # Windows 11 run of 05a17dd: direct conhost launch never ran the launcher

    def test_ready_needs_event_and_health(self):
        c = self.code
        self.assertIn("if ($Stage -eq 'open') { $script:OpenComplete = $true", c)
        self.assertIn("if ($h.ok -eq $true -and $h.local_only -eq $true -and $h.service -eq 'Marketplace Scanner') { $script:HealthOk = $true }", c)
        self.assertIn('if ($script:HealthOk) { Set-Done }', c)
        self.assertIn("if ([string]$e.nonce -ne $script:Nonce) { continue }", c)
        self.assertIn('$req.Proxy = $null', c)
        self.assertIn('BeginGetResponse', c)            # health never blocks the UI thread
        self.assertNotIn('Invoke-RestMethod', c)
        self.assertNotIn('Start-Sleep', c)              # nothing sleeps on the UI thread

    def test_honest_progress(self):
        c = self.code
        self.assertIn('ProgressBarStyle]::Marquee', c)
        self.assertNotIn('.Value = $bar.Value +', c)
        shown = ' '.join(re.findall(r"'[^']*'", c))        # texts the window can display
        self.assertNotRegex(shown, r"(?i)\d\s*%|percent|\beta\b|remaining")   # no invented percentages or time estimates

    def test_fallback_and_exit_codes(self):
        c = self.code
        self.assertGreaterEqual(c.count('exit 90'), 5)
        self.assertIn("if ($env:LOTRADAR_STARTUP_GUI_TEST_UNAVAILABLE -eq '1') { exit 90 }", c)
        self.assertIn('if (-not [Environment]::UserInteractive) { exit 90 }', c)
        self.assertIn('exit $script:ExitCode', c)
        self.assertEqual(c.count('$script:ExitCode = 91'), 2)      # failure shown; the launcher maps 91 to 1
        self.assertNotIn('$script:ExitCode = 1\n', c)
        run = c[c.index('[Windows.Forms.Application]::Run($form)'):]
        self.assertIn('Show-ConsoleWindow; $script:ExitCode = 0', run)  # crash while starting: console takes over
        self.assertIn('$script:ExitCode = 90', run)
        self.assertIn("'Local\\LotRadarStartupWindow'", c)

    def test_failed_console_closed_only_after_bootstrap_exit(self):
        c = self.code
        body = c[c.index('function Close-FailedConsole'):c.index('function Show-ConsoleWindow')]
        self.assertIn('if ($script:BootPid -gt 0 -and -not (Test-ProcessExited $script:BootProc)) { return $false }', body)
        self.assertIn("$_.Name -ieq 'python.exe'", body)
        self.assertLess(body.index('return $false'), body.index('taskkill.exe'))
        closing = c[c.index('$form.Add_FormClosing'):]
        self.assertIn("if ($script:Mode -eq 'running') {", closing)
        self.assertIn('Show-ConsoleWindow', closing[:closing.index("elseif ($script:Mode -eq 'failed')")])
        self.assertNotIn('Close-FailedConsole', closing[:closing.index("elseif ($script:Mode -eq 'failed')")])

    def test_status_files_bounded(self):
        c = self.code
        self.assertIn("'^startup-status-[0-9a-f]{32}\\.jsonl$'", c)
        self.assertIn('AddDays(-1)', c)

    def test_preview_mode_starts_and_writes_nothing(self):
        c = self.code
        self.assertIn('[switch]$Preview', c)
        sp = c[c.index('function Start-PreviewAttempt'):c.index('function Read-NewEvents')]
        for banned in ('Start-Process', 'WriteAllText', 'New-Item', 'Remove-Item', 'Open(', 'LOTRADAR_STARTUP', '$launcher', 'HttpWebRequest'):
            self.assertNotIn(banned, sp)
        self.assertIn("'EXAMPLE: Port 8765 is in use", sp)
        # no runtime folder in preview: no cleanup pass, no status file, separate mutex, early exits in the hooks
        self.assertIn("if (-not $Preview) {\n    $userRoot = Join-Path $env:LOCALAPPDATA 'MarketplaceScanner'", c)
        self.assertIn('if (-not $Preview) { try {\n    New-Item -ItemType Directory -Path $runtimeDir', c)
        self.assertIn("if ($Preview) { $mutexName = 'Local\\LotRadarStartupPreview' }", c)
        self.assertIn('if ($Preview) { Start-PreviewAttempt; $timer.Start(); return }', c)
        self.assertIn('if ($Preview) { Start-PreviewAttempt; return }', c)
        self.assertIn("if ($Preview) { $status.Text = 'Preview: there is no console window to show", c)
        self.assertIn('if ($Preview) { $script:ExitCode = 0; return }', c)
        tick = c[c.index('$timer.Add_Tick({'):]
        self.assertLess(tick.index('Step-Preview'), tick.index('Read-NewEvents'))
        self.assertIn('PREVIEW (example steps, nothing is started)', c)
    def test_show_console_records_why(self):
        c = self.code
        self.assertIn('[DllImport("kernel32.dll", SetLastError = true)] public static extern bool AttachConsole(uint pid);', c)
        for d in ("'no-native'", "'console-exited'", "'shown'", "'no-console-window'", "'attach-failed:'"):
            self.assertIn(d, c)
        self.assertIn("console_diag = (@($script:ConsoleDiag) -join ',')", c)
        self.assertIn("[void]$script:ConsoleDiag.Add('click')", c)
    def test_layout_scales_with_display_dpi(self):
        """Windows 11 preview at 150% (f9742a7): text and buttons were cut off - fonts grew, layout did not."""
        c = self.code
        self.assertIn('$form.AutoScaleMode = [Windows.Forms.AutoScaleMode]::None', c)
        self.assertIn('$script:Scale = [math]::Max(1.0, $gs.DpiX / 96.0)', c)
        # every position/size goes through the scale helpers (only the helpers build raw Point/Size objects)
        raw = [l for l in c.splitlines() if ('New-Object Drawing.Point(' in l or 'New-Object Drawing.Size(' in l) and 'MeasureText' not in l]
        self.assertEqual(len(raw), 2, raw)
        self.assertTrue(all(l.startswith('function ScalePoint(') or l.startswith('function ScaleSize(') for l in raw), raw)
        for k in ('$form.ClientSize = (ScaleSize 480 330)', '$form.ClientSize = (ScaleSize 480 460)', '$b.Top = (ScalePx 420)', '$b.Top = (ScalePx 290)', '$details.Height = (ScalePx 120)'):
            self.assertIn(k, c)
        self.assertNotRegex(c, r'\.(Top|Height|Width|Left) = \d')
        # the window measures its own texts while it still exists and reports them in the ResultFile
        fc = c[c.index('$form.Add_FormClosing({'):]
        self.assertLess(fc.index('Get-ClippedText'), fc.index('if ($Preview)'))
        self.assertIn('clipped = [string]$script:Clipped; scale = $script:Scale', c)
    def test_function_names_do_not_shadow_builtin_aliases(self):
        """2c0cac1 on Windows 11: a function named Sc was shadowed by the built-in alias sc (Set-Content); the window
        hung invisibly waiting for input. In PowerShell an alias wins over a function of the same name."""
        builtin = {'ac', 'asnp', 'cat', 'cd', 'chdir', 'clc', 'clear', 'clhy', 'cli', 'clp', 'cls', 'clv', 'cnsn', 'compare',
                   'copy', 'cp', 'cpi', 'cpp', 'curl', 'cvpa', 'dbp', 'del', 'diff', 'dir', 'dnsn', 'ebp', 'echo', 'epal',
                   'epcsv', 'epsn', 'erase', 'etsn', 'exsn', 'fc', 'fhx', 'fl', 'foreach', 'ft', 'fw', 'gal', 'gbp', 'gc',
                   'gcb', 'gci', 'gcm', 'gcs', 'gdr', 'ghy', 'gi', 'gin', 'gjb', 'gl', 'gm', 'gmo', 'gp', 'gps', 'gpv', 'group',
                   'gsn', 'gsnp', 'gsv', 'gtz', 'gu', 'gv', 'gwmi', 'h', 'history', 'icm', 'iex', 'ihy', 'ii', 'ipal', 'ipcsv',
                   'ipmo', 'ipsn', 'irm', 'ise', 'iwmi', 'iwr', 'kill', 'lp', 'ls', 'man', 'md', 'measure', 'mi', 'mount',
                   'move', 'mp', 'mv', 'nal', 'ndr', 'ni', 'nmo', 'npssc', 'nsn', 'nv', 'ogv', 'oh', 'popd', 'ps', 'pushd',
                   'pwd', 'r', 'rbp', 'rcjb', 'rcsn', 'rd', 'rdr', 'ren', 'ri', 'rjb', 'rm', 'rmdir', 'rmo', 'rni', 'rnp', 'rp',
                   'rsn', 'rsnp', 'rujb', 'rv', 'rvpa', 'rwmi', 'sajb', 'sal', 'saps', 'sasv', 'sbp', 'sc', 'scb', 'select',
                   'set', 'shcm', 'si', 'sl', 'sleep', 'sls', 'sort', 'sp', 'spjb', 'spps', 'spsv', 'start', 'stz', 'sujb',
                   'sv', 'swmi', 'tee', 'trcm', 'type', 'wget', 'where', 'wjb', 'write'}
        import glob
        for path in [PATH] + sorted(glob.glob(os.path.join(REPO, '**', '*.ps1'), recursive=True)):
            with open(path, encoding='utf-8', errors='replace') as h:
                names = re.findall(r'^\s*function\s+([A-Za-z0-9_-]+)', h.read(), re.M)
            clash = [n for n in names if n.lower() in builtin]
            self.assertEqual(clash, [], path)

if __name__ == '__main__':
    unittest.main()
