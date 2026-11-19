<#
.SYNOPSIS
  Deterministic Windows regression tests for the PR #5 QA-kit fixes A (CLN1 cleanup outcome) and B (separate,
  default-No OneDrive choice in the cleanup self-test). TEST-ONLY, SYNTHETIC FIXTURES ONLY.

.DESCRIPTION
  The exact functions under test are taken from the real files with the PowerShell parser (not copied by hand):
    A: Add-Result and Complete-SandboxCleanup from Test-LotRadarInstaller.ps1
    B: Get-QAOneDriveChoice from LotRadarQA.CleanupSelfTest.ps1, Read-QAAnswer from LotRadarQA.Cleanup.ps1
  Nothing here starts LotRadar, installs anything, opens a browser, touches the real Desktop shortcut, the real
  %LOCALAPPDATA%\MarketplaceScanner, the kit ledger or OneDrive, or stops any process. Fixtures live in one new
  folder "%LOCALAPPDATA%\Temp\LotRadar AB SelfTest <random>" that this script creates and removes again (no links are ever
  created in it). A file handle that this script opens itself is what makes the cleanup fail in case A4.

  Run in Windows PowerShell 5.1 as a normal user, from a checkout of the candidate:
      powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests\windows\Test-QAKitFixesAB.ps1 -OutDir <folder>
  Writes AB-results.json to -OutDir (which must exist and must be OUTSIDE the repository). Exit 0 = all PASS.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OutDir,
    [string]$HarnessPath = '',
    [string]$SelfTestPath = '',
    [string]$CleanupModulePath = ''
)
$ErrorActionPreference = 'Stop'
if (-not $HarnessPath) { $HarnessPath = Join-Path $PSScriptRoot 'Test-LotRadarInstaller.ps1' }
if (-not $SelfTestPath) { $SelfTestPath = Join-Path $PSScriptRoot 'qa-kit\LotRadarQA.CleanupSelfTest.ps1' }
if (-not $CleanupModulePath) { $CleanupModulePath = Join-Path $PSScriptRoot 'qa-kit\LotRadarQA.Cleanup.ps1' }
$OutDir = (Resolve-Path -LiteralPath $OutDir).Path
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
$abRows = New-Object System.Collections.ArrayList

function Add-AB([string]$Id, [string]$Name, [string]$Status, [string]$Detail) {
    [void]$abRows.Add([pscustomobject]@{ Id = $Id; Name = $Name; Status = $Status; Detail = $Detail })
    $c = 'Green'; if ($Status -eq 'FAIL') { $c = 'Red' } elseif ($Status -ne 'PASS') { $c = 'Yellow' }
    Write-Host ('[' + $Status + '] ' + $Id + ' ' + $Name + ' :: ' + $Detail) -ForegroundColor $c
}
function Invoke-AB([string]$Id, [string]$Name, [scriptblock]$Body) {
    try { $d = [string](@(& $Body) | Select-Object -Last 1); Add-AB $Id $Name 'PASS' $d } catch { Add-AB $Id $Name 'FAIL' $_.Exception.Message }
}
function Assert-AB([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Get-FunctionText([string]$Path, [string]$Name) {
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
    if (@($errors).Count -gt 0) { throw ('parse errors in ' + (Split-Path -Leaf $Path)) }
    $f = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $Name }, $true)
    if (-not $f) { throw ('function ' + $Name + ' not found in ' + (Split-Path -Leaf $Path)) }
    return $f.Extent.Text
}

# ---- owned fixture folder (never the kit's "LotRadar Test Sandbox <hex8>" pattern, so no kit logic treats it as its own)
# Long form of the profile path, as the harness uses: %TEMP% may be an 8.3 short path that Windows error messages do not use.
$fixRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) ('Temp\LotRadar AB SelfTest ' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
if ($fixRoot.Contains('~')) { throw ('Fixture path contains an 8.3 short name, refusing: ' + $fixRoot) }
New-Item -ItemType Directory -Path $fixRoot | Out-Null
function New-AFixture([string]$Name) {
    $r = Join-Path $fixRoot ('sandbox ' + $Name)
    New-Item -ItemType Directory -Path (Join-Path $r 'Local\sub') -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $r 'Local\sub\file.txt'), 'synthetic', $utf8NoBom)
    [IO.File]::WriteAllText((Join-Path $r 'LOTRADAR_QA_OWNER.txt'), 'token=synthetic', $utf8NoBom)   # same name the harness uses
    $l = Join-Path $fixRoot ('ledger ' + $Name + '.owned')
    [IO.File]::WriteAllText($l, 'token=synthetic', $utf8NoBom)
    return [pscustomobject]@{ Root = $r; Ledger = $l }
}
function Get-CLN1Rows { return @($script:Results | Where-Object { $_.Id -eq 'CLN1' }) }

try {
    # =========================================================== Fix A: CLN1 (harness final cleanup)
    $script:Results = New-Object System.Collections.ArrayList
    . ([ScriptBlock]::Create((Get-FunctionText $HarnessPath 'Add-Result')))
    . ([ScriptBlock]::Create((Get-FunctionText $HarnessPath 'Complete-SandboxCleanup')))

    Invoke-AB 'AB-A0' 'Harness records CLN1 before totals, exit code and JSON; operator keep is separate from shortcut keep' {
        $h = [IO.File]::ReadAllText($HarnessPath)
        $call = $h.IndexOf('Complete-SandboxCleanup -root $root -OperatorKeep $operatorKeepSandbox -ProtectKeep $shortcutProtectKeep')
        Assert-AB ($call -gt 0) 'cleanup call not found'
        Assert-AB ($call -gt $h.IndexOf('try { Stop-SandboxProcesses }')) 'CLN1 recorded before sandbox processes are stopped'
        Assert-AB ($call -lt $h.IndexOf('$fail = @($script:Results')) 'CLN1 recorded after the FAIL total'
        Assert-AB ($call -lt $h.IndexOf('WriteAllText($jsonPath')) 'CLN1 recorded after the JSON is written'
        Assert-AB ($h.Contains('$operatorKeepSandbox = [bool]$KeepSandbox')) 'operator intent not captured'
        Assert-AB ($h.Contains('$shortcutProtectKeep = $true')) 'shortcut-protection keep flag not set on SC1 failure'
        Assert-AB (-not $h.Contains('$KeepSandbox = $true')) 'operator switch is still overwritten internally'
        Assert-AB ($h.Contains("Where-Object { `$_.Name -ne 'LOTRADAR_QA_OWNER.txt' }")) 'ownership marker is not deleted last'
        return 'order and flags OK; marker deleted last'
    }
    Invoke-AB 'AB-A1' 'Normal cleanup: exactly one CLN1 PASS, folder gone, ledger entry removed' {
        $f = New-AFixture 'a1'; $before = @(Get-CLN1Rows).Count
        Complete-SandboxCleanup -root $f.Root -OperatorKeep $false -ProtectKeep $false -qaLedgerFile $f.Ledger -Attempts 2 -DelaySeconds 0
        $rows = @(Get-CLN1Rows); Assert-AB ($rows.Count -eq $before + 1) 'not exactly one CLN1 row'
        Assert-AB ($rows[-1].Status -eq 'PASS') ('status ' + $rows[-1].Status)
        Assert-AB (-not (Test-Path -LiteralPath $f.Root)) 'folder still present'
        Assert-AB (-not (Test-Path -LiteralPath $f.Ledger)) 'ledger entry not removed'
        return $rows[-1].Detail
    }
    Invoke-AB 'AB-A2' 'Operator -KeepSandbox: CLN1 INFO (operator reason), folder and ledger kept, INFO is not a PASS' {
        $f = New-AFixture 'a2'; $before = @(Get-CLN1Rows).Count; $passBefore = @($script:Results | Where-Object { $_.Status -eq 'PASS' }).Count
        Complete-SandboxCleanup -root $f.Root -OperatorKeep $true -ProtectKeep $false -qaLedgerFile $f.Ledger -Attempts 2 -DelaySeconds 0
        $rows = @(Get-CLN1Rows); Assert-AB ($rows.Count -eq $before + 1) 'not exactly one CLN1 row'
        Assert-AB ($rows[-1].Status -eq 'INFO' -and $rows[-1].Detail -like '*-KeepSandbox*') ('row ' + $rows[-1].Status + ' ' + $rows[-1].Detail)
        Assert-AB ((Test-Path -LiteralPath $f.Root) -and (Test-Path -LiteralPath $f.Ledger)) 'folder or ledger removed'
        Assert-AB (@($script:Results | Where-Object { $_.Status -eq 'PASS' }).Count -eq $passBefore) 'INFO counted as PASS'
        return $rows[-1].Detail
    }
    Invoke-AB 'AB-A3' 'Shortcut-protection keep: CLN1 INFO with its own reason, folder (backup) and ledger kept' {
        $f = New-AFixture 'a3'; $before = @(Get-CLN1Rows).Count
        Complete-SandboxCleanup -root $f.Root -OperatorKeep $false -ProtectKeep $true -qaLedgerFile $f.Ledger -Attempts 2 -DelaySeconds 0
        $rows = @(Get-CLN1Rows); Assert-AB ($rows.Count -eq $before + 1) 'not exactly one CLN1 row'
        Assert-AB ($rows[-1].Status -eq 'INFO' -and $rows[-1].Detail -like '*Desktop shortcut*' -and $rows[-1].Detail -notlike '*-KeepSandbox*') ('row ' + $rows[-1].Detail)
        Assert-AB ((Test-Path -LiteralPath $f.Root) -and (Test-Path -LiteralPath $f.Ledger)) 'folder or ledger removed'
        return $rows[-1].Detail
    }
    Invoke-AB 'AB-A4' 'Deterministic failure (held file next to the marker): CLN1 FAIL, no private path, marker and ledger kept, run would exit 1' {
        $f = New-AFixture 'a4'; $before = @(Get-CLN1Rows).Count
        # held directly in the sandbox root, next to the ownership marker (the C-5 NA-05 situation)
        $held = [IO.File]::Open((Join-Path $f.Root 'QA-HELD-HANDLE.txt'), 'CreateNew', 'ReadWrite', 'None')
        try {
            Complete-SandboxCleanup -root $f.Root -OperatorKeep $false -ProtectKeep $false -qaLedgerFile $f.Ledger -Attempts 2 -DelaySeconds 0
        } finally { $held.Dispose() }
        $rows = @(Get-CLN1Rows); Assert-AB ($rows.Count -eq $before + 1) 'not exactly one CLN1 row'
        $r = $rows[-1]
        Assert-AB ($r.Status -eq 'FAIL') ('status ' + $r.Status)
        # Windows may report only the file name; any path it does report must be masked. Never a raw private path.
        Assert-AB ($r.Detail -match 'First error: \S') 'first error not reported'
        Assert-AB (-not $r.Detail.Contains($f.Root)) 'raw sandbox path leaked'
        if ($env:USERPROFILE) { Assert-AB (-not $r.Detail.Contains($env:USERPROFILE)) 'profile path leaked' }
        Assert-AB (Test-Path -LiteralPath (Join-Path $f.Root 'LOTRADAR_QA_OWNER.txt')) 'ownership marker deleted although cleanup failed'
        Assert-AB ((Test-Path -LiteralPath $f.Root) -and (Test-Path -LiteralPath $f.Ledger)) 'folder or ledger removed although cleanup failed'
        Assert-AB ($r.Detail -like '*next kit run can offer to remove it*') 'FAIL text does not say the kit can repair it'
        # the harness computes its exit code from the FAIL rows after this point: exit 1
        Assert-AB (@($script:Results | Where-Object { $_.Status -eq 'FAIL' }).Count -gt 0) 'no FAIL row for the exit code'
        return $r.Detail
    }
    Invoke-AB 'AB-A6' 'Kit-format leftover after a failed cleanup: the kit''s own ownership check accepts it and its own repair delete removes it' {
        . $CleanupModulePath   # defines functions only (LotRadarQA.Cleanup.ps1, unchanged)
        $tmpParent = Join-Path $fixRoot 'Temp'
        New-Item -ItemType Directory -Path $tmpParent -Force | Out-Null
        $ledgerDir = Join-Path $fixRoot 'owned'
        $sb = Join-Path $tmpParent ('LotRadar Test Sandbox ' + (New-QAOwnerToken).Substring(0, 8))
        [void](New-QAOwnedFolder $sb 'sandbox' $ledgerDir 'AB-A6 synthetic fixture. Synthetic files only.')
        New-Item -ItemType Directory -Path (Join-Path $sb 'Local\sub') -Force | Out-Null
        [IO.File]::WriteAllText((Join-Path $sb 'Local\sub\file.txt'), 'synthetic', $utf8NoBom)
        $ledgerFile = @(Read-QALedger $ledgerDir)[0].File
        $before = @(Get-CLN1Rows).Count
        $held = [IO.File]::Open((Join-Path $sb 'QA-HELD-HANDLE.txt'), 'CreateNew', 'ReadWrite', 'None')
        try {
            Complete-SandboxCleanup -root $sb -OperatorKeep $false -ProtectKeep $false -qaLedgerFile $ledgerFile -Attempts 2 -DelaySeconds 0
        } finally { $held.Dispose() }
        $rows = @(Get-CLN1Rows); Assert-AB ($rows.Count -eq $before + 1 -and $rows[-1].Status -eq 'FAIL') 'not one CLN1 FAIL row'
        $info = Test-QAOwnedFolder -Dir $sb -Kind 'sandbox' -Parent $tmpParent -Ledger @(Read-QALedger $ledgerDir) -SafeShas @()
        Assert-AB ($info.Owned) ('kit refuses the leftover: ' + $info.Reason)
        $res = Remove-QAOwnedFolder $info $tmpParent
        Assert-AB ($res -eq 'deleted' -and -not (Test-Path -LiteralPath $sb)) ('kit repair did not remove it: ' + $res)
        Assert-AB (-not (Test-Path -LiteralPath $ledgerFile)) 'kit repair left the ledger entry'
        return 'ownership proven after failed cleanup; kit repair delete: deleted, ledger entry removed'
    }
    Invoke-AB 'AB-A5' 'Nothing to remove (folder absent): CLN1 PASS, no error, no NOTE' {
        $missing = Join-Path $fixRoot 'sandbox never created'; $before = @(Get-CLN1Rows).Count
        Complete-SandboxCleanup -root $missing -OperatorKeep $false -ProtectKeep $false -qaLedgerFile '' -Attempts 2 -DelaySeconds 0
        $rows = @(Get-CLN1Rows); Assert-AB ($rows.Count -eq $before + 1 -and $rows[-1].Status -eq 'PASS') 'not one PASS row'
        return $rows[-1].Detail
    }
    # =========================================================== Fix B: separate, default-No OneDrive choice
    $choiceText = Get-FunctionText $SelfTestPath 'Get-QAOneDriveChoice'
    . ([ScriptBlock]::Create($choiceText))

    Invoke-AB 'AB-B1' 'Decline answers skip the OneDrive cases: Enter, spaces, N, n, no, YES, yes, x, nothing' {
        foreach ($a in @('', '   ', 'N', 'n', 'no', 'YES', 'yes', 'x', 'D', $null)) {
            $ans = $a
            Assert-AB (-not (Get-QAOneDriveChoice { $ans })) ('answer "' + [string]$ans + '" included the OneDrive cases')
        }
        return '10 decline answers -> skip'
    }
    Invoke-AB 'AB-B2' 'Only Y or y (spaces allowed) includes the OneDrive cases' {
        foreach ($a in @('Y', 'y', ' y ', 'Y ')) {
            $ans = $a
            Assert-AB (Get-QAOneDriveChoice { $ans }) ('answer "' + $ans + '" did not include the OneDrive cases')
        }
        return 'Y, y, " y ", "Y " -> include'
    }
    Invoke-AB 'AB-B3' 'No console / question fails: skip (never include by accident)' {
        Assert-AB (-not (Get-QAOneDriveChoice { throw 'no console available' })) 'a failing question included the OneDrive cases'
        return 'question error -> skip'
    }
    # Child Windows PowerShell with REDIRECTED standard input that contains "Y": the real Read-QAAnswer must return
    # nothing, so even a piped Y is skipped. Variant 2 simulates the runner's -Yes (and a Confirm-Start that always
    # says yes) to prove the general -Yes has no influence on the OneDrive decision.
    $psExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    function Invoke-ChoiceChild([string]$Prelude) {
        $body = $Prelude + "`r`n. '" + $CleanupModulePath.Replace("'", "''") + "'`r`n" + $choiceText + "`r`n" +
            "if (Get-QAOneDriveChoice { Read-QAAnswer 'Include the OneDrive cases?' }) { 'CHOICE=INCLUDED' } else { 'CHOICE=SKIPPED' }"
        $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($body))
        $inFile = Join-Path $fixRoot ('stdin-' + [Guid]::NewGuid().ToString('N').Substring(0, 6) + '.txt')
        $outFile = $inFile + '.out'
        [IO.File]::WriteAllText($inFile, "Y`r`n", (New-Object System.Text.ASCIIEncoding))
        $p = Start-Process -FilePath $psExe -ArgumentList @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $enc) `
            -RedirectStandardInput $inFile -RedirectStandardOutput $outFile -NoNewWindow -Wait -PassThru
        return [pscustomobject]@{ Code = $p.ExitCode; Out = [IO.File]::ReadAllText($outFile) }
    }
    Invoke-AB 'AB-B4' 'Real Read-QAAnswer, input redirected with "Y": OneDrive cases skipped' {
        $r = Invoke-ChoiceChild ''
        Assert-AB ($r.Out -match 'CHOICE=SKIPPED') ('child said: ' + $r.Out.Trim())
        return ('exit ' + $r.Code + '; ' + ($r.Out.Trim() -split "`r?`n" | Select-Object -Last 1))
    }
    Invoke-AB 'AB-B5' 'Runner -Yes simulated (Yes=true, Confirm-Start always yes): OneDrive decision still skips' {
        $r = Invoke-ChoiceChild '$Yes = $true; function Confirm-Start([string]$What) { return $true }'
        Assert-AB ($r.Out -match 'CHOICE=SKIPPED') ('child said: ' + $r.Out.Trim())
        return ('exit ' + $r.Code + '; ' + ($r.Out.Trim() -split "`r?`n" | Select-Object -Last 1))
    }
    Invoke-AB 'AB-B6' 'Self-test source: OneDrive creation only behind the separate choice; Confirm-Start used once, for the LOCAL start only' {
        $st = [IO.File]::ReadAllText($SelfTestPath)
        $code = (($st -split "`r?`n") | Where-Object { -not $_.TrimStart().StartsWith('#') }) -join "`n"
        $decision = $code.IndexOf('$useOneDrive = Get-QAOneDriveChoice { Read-QAAnswer ')
        Assert-AB ($decision -gt 0) 'decision does not use the separate question'
        # Confirm-Start honours -Yes, so it must never decide the OneDrive cases; it only starts the local run (B3)
        Assert-AB (([regex]::Matches($code, 'Confirm-Start')).Count -eq 1) 'Confirm-Start is not used exactly once'
        $local = $code.IndexOf("Confirm-Start 'cleanup self-test (local synthetic checks only)'")
        Assert-AB ($local -gt $decision) 'local start confirmation missing or before the OneDrive question'
        Assert-AB ($local -lt $code.IndexOf("New-QAOwnedFolder `$script:ClCtr 'sandbox'")) 'fixtures created before the local start confirmation'
        Assert-AB (@(($code -split "`n") | Where-Object { $_ -match 'useOneDrive' -and $_ -match 'Confirm-Start' }).Count -eq 0) 'OneDrive decision tied to Confirm-Start'
        Assert-AB ($code.Contains('$script:CleanupExit = 9')) 'cancel path does not report exit 9'
        Assert-AB (([regex]::Matches($code, [regex]::Escape("New-QAOwnedFolder `$odCtr 'onedrive'"))).Count -eq 1) 'OneDrive folder created in more than one place'
        $gate = $code.IndexOf('if (-not $useOneDrive) {')
        Assert-AB ($gate -gt 0 -and $gate -lt $code.IndexOf("New-QAOwnedFolder `$odCtr 'onedrive'")) 'OneDrive folder creation is not behind the choice'
        Assert-AB ($code.Contains("Add-CL 'CL21' 'OneDrive owned leftover (cloud placeholders), answer D: deleted' 'SKIP'")) 'CL21 SKIP path missing'
        return 'single gated OneDrive creation; Confirm-Start only for the local start, before fixtures'
    }
    Invoke-AB 'AB-B7' 'Runner Confirm-Start with -Yes really waits about 10 seconds (the cancel window the launcher promises)' {
        $runner = Join-Path (Split-Path -Parent $SelfTestPath) 'Run-QAKit.ps1'
        $body = (Get-FunctionText $runner 'Say') + "`r`n" + (Get-FunctionText $runner 'Confirm-Start') + "`r`n" +
            '$Yes = $true; $sw = [Diagnostics.Stopwatch]::StartNew(); $ok = Confirm-Start ''cleanup self-test (local synthetic checks only)''; ' +
            '''RESULT='' + $ok + '' ELAPSED_MS='' + $sw.ElapsedMilliseconds'
        $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($body))
        $outFile = Join-Path $fixRoot 'countdown.out'
        $p = Start-Process -FilePath $psExe -ArgumentList @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $enc) `
            -RedirectStandardOutput $outFile -NoNewWindow -Wait -PassThru
        $o = [IO.File]::ReadAllText($outFile)
        $m = [regex]::Match($o, 'RESULT=(\w+) ELAPSED_MS=(\d+)')
        Assert-AB ($m.Success) ('no result from child (exit ' + $p.ExitCode + ')')
        Assert-AB ($m.Groups[1].Value -eq 'True') 'Confirm-Start with -Yes did not return true'
        Assert-AB ([int]$m.Groups[2].Value -ge 9500) ('countdown too short: ' + $m.Groups[2].Value + ' ms')
        return ('returned True after ' + $m.Groups[2].Value + ' ms')
    }
} finally {
    # remove only the fixture folder this script created (it never contains links)
    if ($fixRoot -and (Test-Path -LiteralPath $fixRoot) -and ((Split-Path -Leaf $fixRoot) -like 'LotRadar AB SelfTest *')) {
        Remove-Item -LiteralPath $fixRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
    $fixLeft = Test-Path -LiteralPath $fixRoot
    Add-AB 'AB-Z1' 'Own fixture folder removed' $(if ($fixLeft) { 'FAIL' } else { 'PASS' }) $(if ($fixLeft) { 'fixture folder still present (safe to delete by hand)' } else { 'removed' })
    $out = Join-Path $OutDir 'AB-results.json'
    [IO.File]::WriteAllText($out, (@{ results = @($abRows); powershell = [string]$PSVersionTable.PSVersion; harness = (Get-FileHash -LiteralPath $HarnessPath -Algorithm SHA256).Hash.ToLowerInvariant() } | ConvertTo-Json -Depth 4), $utf8NoBom)
    Write-Host ('Results: ' + $out)
}
$failed = @($abRows | Where-Object { $_.Status -ne 'PASS' }).Count
if ($failed -gt 0) { exit 1 }
exit 0
