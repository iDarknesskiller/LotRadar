"""Execute cleanup selection with mocked process enumeration; never kill a real process."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

@unittest.skipUnless(os.name == 'nt', 'Windows PowerShell required')
class SandboxCleanup(unittest.TestCase):
    def test_only_sandbox_server_selected(self):
        source = str(Path(__file__).resolve().parent / 'windows' / 'Test-LotRadarInstaller.ps1').replace("'", "''")
        script = r"""
$ErrorActionPreference = 'Stop'
$local = 'C:\QA [fixture]\Local'
$script:killed = @()
function Get-CimInstance {
    @(
      @{Name='python.exe';CommandLine='python C:\QA [fixture]\Local\server.py';ProcessId=101},
      @{Name='python.exe';CommandLine='python C:\QA [fixture]\Local-other\server.py';ProcessId=102},
      @{Name='python.exe';CommandLine='python C:\Live\server.py';ProcessId=103},
      @{Name='chrome.exe';CommandLine='chrome --app=http://127.0.0.1:8765/';ProcessId=104},
      @{Name='msedge.exe';CommandLine='edge --app=http://127.0.0.1:8765/';ProcessId=105},
      @{Name='chrome.exe';CommandLine='chrome --app=http://127.0.0.1:8765/ C:\QA [fixture]\Local\';ProcessId=106}
    ) | ForEach-Object { [pscustomobject]$_ }
}
function taskkill.exe { $script:killed += [int]$args[1] }
function Start-Sleep {}
$ast = [Management.Automation.Language.Parser]::ParseFile('__SOURCE__', [ref]$null, [ref]$null)
$f = $ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Stop-SandboxProcesses'}, $true)
. ([scriptblock]::Create($f.Extent.Text))
Stop-SandboxProcesses
if (($script:killed -join ',') -ne '101') { throw ('unsafe targets: ' + ($script:killed -join ',')) }
""".replace('__SOURCE__', source)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'cleanup-test.ps1'
            p.write_text(script, encoding='ascii')
            result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(p)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
