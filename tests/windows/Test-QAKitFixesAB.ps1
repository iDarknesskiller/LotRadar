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
        return 'order and flags OK'
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
    Invoke-AB 'AB-A4' 'Deterministic failure (held file handle): CLN1 FAIL, masked first error, folder and ledger kept, run would exit 1' {
        $f = New-AFixture 'a4'; $before = @(Get-CLN1Rows).Count
        $held = [IO.File]::Open((Join-Path $f.Root 'Local\sub\held.txt'), 'OpenOrCreate', 'ReadWrite', 'None')
        try {
            Complete-SandboxCleanup -root $f.Root -OperatorKeep $false -ProtectKeep $false -qaLedgerFile $f.Ledger -Attempts 2 -DelaySeconds 0
        } finally { $held.Dispose() }
        $rows = @(Get-CLN1Rows); Assert-AB ($rows.Count -eq $before + 1) 'not exactly one CLN1 row'
        $r = $rows[-1]
        Assert-AB ($r.Status -eq 'FAIL') ('status ' + $r.Status)
        Assert-AB ($r.Detail -like '*<sandbox>*') 'first error not reported with the masked sandbox path'
        Assert-AB (-not $r.Detail.Contains($f.Root)) 'raw sandbox path leaked'
        if ($env:USERPROFILE) { Assert-AB (-not $r.Detail.Contains($env:USERPROFILE)) 'profile path leaked' }
        Assert-AB ((Test-Path -LiteralPath $f.Root) -and (Test-Path -LiteralPath $f.Ledger)) 'folder or ledger removed although cleanup failed'
        # the harness computes its exit code from the FAIL rows after this point: exit 1
        Assert-AB (@($script:Results | Where-Object { $_.Status -eq 'FAIL' }).Count -gt 0) 'no FAIL row for the exit code'
        return $r.Detail
    }
    Invoke-AB 'AB-A5' 'Nothing to remove (folder absent): CLN1 PASS, no error, no NOTE' {
        $missing = Join-Path $fixRoot 'sandbox never created'; $before = @(Get-CLN1Rows).Count
        Complete-SandboxCleanup -root $missing -OperatorKeep $false -ProtectKeep $false -qaLedgerFile '' -Attempts 2 -DelaySeconds 0
        $rows = @(Get-CLN1Rows); Assert-AB ($rows.Count -eq $before + 1 -and $rows[-1].Status -eq 'PASS') 'not one PASS row'
        return $rows[-1].Detail
    }
    # Fix B cases are appended below this line by the Fix B change.
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
