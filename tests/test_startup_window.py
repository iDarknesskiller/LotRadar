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


if __name__ == '__main__':
    unittest.main()
