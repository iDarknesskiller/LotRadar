# LotRadar QA kit: Windows self-test of the leftover-cleanup safety rules (TEST-ONLY).
# Dot-sourced by Run-QAKit.ps1 -CleanupSelfTest after its preflight. Uses from Run-QAKit.ps1: Say, Protect-Text,
# Get-Sha, Confirm-Start (local start only), $info, $os, $isWin11, $isAdmin, $resultsDir, $desktopLnk, $qaHome,
# $localAppData, $odParents, $psExe, and the functions of LotRadarQA.Cleanup.ps1 (including Read-QAAnswer).
# The OneDrive cases are a SEPARATE question (default: skip). The general -Yes of the launcher only starts the
# local self-test (10-second countdown); it never includes the OneDrive cases.
#
# Every case runs on SYNTHETIC fixtures: a fake Temp folder, fake Desktop, fake shortcut store and fake ledger, all
# inside one disposable folder "%LOCALAPPDATA%\Temp\LotRadar Test Sandbox <id>" (plus, after consent, one
# "LotRadar QA TEST ONLY <id>" folder in OneDrive). The real Desktop shortcut, the real saved shortcut copy and
# real LotRadar data are never passed to the code under test; they are hashed before and after (CL23).
# NOTE: this file is dot-sourced; it must never call 'exit'. It sets $script:CleanupExit and returns.

$script:CleanupExit = 1
$clRows = New-Object System.Collections.ArrayList
$enc = New-Object System.Text.UTF8Encoding $false

function Add-CL([string]$Id, [string]$Name, [string]$Status, [string]$Detail) {
    [void]$clRows.Add([pscustomobject]@{ Id = $Id; Name = $Name; Status = $Status; Detail = $Detail })
    $c = 'Green'
    if ($Status -eq 'FAIL') { $c = 'Red' } elseif ($Status -ne 'PASS') { $c = 'Yellow' }
    Say ('[' + $Status + '] ' + $Id + ' ' + $Name + ' - ' + $Detail) $c
}
function Invoke-CL([string]$Id, [string]$Name, [scriptblock]$Body) {
    try {
        $d = [string](@(& $Body) | Select-Object -Last 1)
        if ($d -like 'SKIP:*') { Add-CL $Id $Name 'SKIP' $d.Substring(5).Trim() }
        elseif ($d -like 'BLOCKED:*') { Add-CL $Id $Name 'BLOCKED' $d.Substring(8).Trim() }
        else { Add-CL $Id $Name 'PASS' $d }
    } catch { Add-CL $Id $Name 'FAIL' $_.Exception.Message }
}
function Assert-CL([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
# OneDrive cases are opt-in: ONLY an answer of Y or y (spaces around it allowed) includes them. Enter, N, anything
# else, end of input, redirected input or no console at all (the question then fails or returns nothing) = skip.
function Get-QAOneDriveChoice([scriptblock]$Ask) {
    $answer = ''
    try { $answer = [string](& $Ask) } catch { $answer = '' }
    return [bool]($answer -cmatch '^\s*[Yy]\s*$')
}
function New-Hex8 { return (New-QAOwnerToken).Substring(0, 8) }
function Invoke-Cmd([string]$CommandLine) {
    $ErrorActionPreference = 'Continue'
    $out = & cmd.exe /d /c $CommandLine 2>&1 | Out-String
    return [pscustomobject]@{ Code = $LASTEXITCODE; Output = $out }
}
function Write-Synthetic([string]$Dir) {
    New-Item -ItemType Directory -Path (Join-Path $Dir 'sub\deep') -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $Dir 'a.txt'), 'synthetic a', $enc)
    [IO.File]::WriteAllText((Join-Path $Dir 'sub\b.txt'), 'synthetic b', $enc)
    [IO.File]::WriteAllBytes((Join-Path $Dir 'sub\deep\c.bin'), [byte[]](1..200 | ForEach-Object { [byte]($_ % 256) }))
    $ro = Join-Path $Dir 'sub\readonly.txt'
    [IO.File]::WriteAllText($ro, 'read-only synthetic', $enc)
    [IO.File]::SetAttributes($ro, [IO.FileAttributes]::ReadOnly)
}
function Get-Snapshot([string]$Dir) {
    # Relative path + hash (or link kind) of everything under $Dir, WITHOUT following links.
    if (-not (Test-Path -LiteralPath $Dir)) { return '<missing>' }
    $items = New-Object System.Collections.ArrayList
    $stack = New-Object System.Collections.Stack
    $stack.Push($Dir)
    while ($stack.Count -gt 0) {
        $d = [string]$stack.Pop()
        foreach ($e in [IO.Directory]::GetFileSystemEntries($d)) {
            $rel = $e.Substring($Dir.Length)
            $a = [IO.File]::GetAttributes($e)
            if (($a -band [IO.FileAttributes]::ReparsePoint) -ne 0) { [void]$items.Add($rel + ' LINK ' + (Get-QAEntryKind $e)) }
            elseif (($a -band [IO.FileAttributes]::Directory) -ne 0) { [void]$items.Add($rel + ' DIR'); $stack.Push($e) }
            else { [void]$items.Add($rel + ' ' + (Get-Sha $e)) }
        }
    }
    return ((@($items) | Sort-Object) -join '|')
}
function New-Lnk([string]$Path, [string]$Target) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $Path) -Force | Out-Null
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($Path)
    $s.TargetPath = $Target
    $s.Save()
}
function New-Fixture([string]$Id) {
    $base = Join-Path $script:ClCtr $Id
    $f = @{
        Base = $base; Temp = (Join-Path $base 'temp'); Ledger = (Join-Path $base 'ledger'); Desk = (Join-Path $base 'desktop\LotRadar.lnk')
        Store = (Join-Path $base 'store\LotRadar.lnk'); Evid = (Join-Path $base 'evidence'); Out = (Join-Path $base 'outside')
        Std = (Join-Path $base 'local\Programs\MarketplaceScanner\Launch Marketplace Scanner.cmd'); OdParents = @()
    }
    foreach ($k in @('Temp', 'Ledger', 'Evid', 'Out')) { New-Item -ItemType Directory -Path $f[$k] -Force | Out-Null }
    New-Item -ItemType Directory -Path (Split-Path -Parent $f.Std) -Force | Out-Null
    [IO.File]::WriteAllText($f.Std, '@echo standard launcher (synthetic)', $enc)
    [IO.File]::WriteAllText((Join-Path $f.Out 'b.txt'), 'OUTSIDE SENTINEL', $enc)
    return $f
}
function New-Candidate($F, [string]$Kind, [switch]$Owned, [string]$Name = '', [string]$Parent = '') {
    if (-not $Parent) { $Parent = $F.Temp }
    if (-not $Name) {
        if ($Kind -eq 'sandbox') { $Name = 'LotRadar Test Sandbox ' + (New-Hex8) } else { $Name = 'LotRadar QA TEST ONLY ' + (New-Hex8) }
    }
    $p = Join-Path $Parent $Name
    if ($Owned) { [void](New-QAOwnedFolder $p $Kind $F.Ledger 'synthetic self-test fixture') } else { New-Item -ItemType Directory -Path $p | Out-Null }
    Write-Synthetic $p
    return $p
}
function Invoke-Repair($F, [string[]]$Answers) {
    $script:ClQueue = New-Object System.Collections.Queue
    foreach ($a in @($Answers)) { $script:ClQueue.Enqueue($a) }
    $script:ClAsked = 0
    $r = Invoke-QALeftoverRepair -TempParent $F.Temp -OneDriveParents $F.OdParents -LedgerDir $F.Ledger -DesktopLnk $F.Desk `
        -OriginalStore $F.Store -StandardTarget $F.Std -EvidenceDir $F.Evid `
        -Ask { param($q) $script:ClAsked++; if ($script:ClQueue.Count -gt 0) { return [string]$script:ClQueue.Dequeue() } return '' }
    return $r
}
function Get-LedgerFileFor([string]$Ledger, [string]$Path) {
    $e = @(Read-QALedger $Ledger | Where-Object { Test-QASamePath $_.Path $Path }) | Select-Object -First 1
    if ($e) { return $e.File }
    return ''
}
function Remove-LinksInside([string]$Dir) {
    # Removes link NODES (never their targets) found under $Dir, so the fixture folder can be cleaned safely.
    $stack = New-Object System.Collections.Stack
    $stack.Push($Dir)
    while ($stack.Count -gt 0) {
        $d = [string]$stack.Pop()
        foreach ($e in [IO.Directory]::GetFileSystemEntries($d)) {
            $a = [IO.File]::GetAttributes($e)
            $k = 'none'
            if (($a -band [IO.FileAttributes]::ReparsePoint) -ne 0) { $k = Get-QAEntryKind $e }
            if ($k -like 'link:*') {
                if (($a -band [IO.FileAttributes]::Directory) -ne 0) { [IO.Directory]::Delete($e) } else { [IO.File]::Delete($e) }
            } elseif (($a -band [IO.FileAttributes]::Directory) -ne 0) { $stack.Push($e) }
        }
    }
}

Say ''
Say '=== Leftover-cleanup safety self-test ===' 'Cyan'
Say 'All cases use synthetic folders and a fake Desktop. Your real shortcut, photos and data are not used.' 'Green'
Initialize-QACleanup
$realLedger = Join-Path $qaHome 'owned'
$realStore = Join-Path $qaHome 'shortcut-original\LotRadar.lnk'
$realDeskBefore = '<none>'; if (Test-Path -LiteralPath $desktopLnk) { $realDeskBefore = Get-Sha $desktopLnk }
$realStoreBefore = '<none>'; if (Test-Path -LiteralPath $realStore) { $realStoreBefore = Get-Sha $realStore }
$realLedgerBefore = @(Read-QALedger $realLedger | ForEach-Object { $_.Token } | Sort-Object) -join ','

$useOneDrive = $false
if (@($odParents).Count -gt 0) {
    Say ''
    Say 'SEPARATE QUESTION - the local cleanup checks run either way; this is ONLY about two extra OneDrive cases.' 'Yellow'
    Say 'The OneDrive cases (CL21, CL22) create ONE temporary folder "LotRadar QA TEST ONLY <random>" in your OneDrive' 'Yellow'
    Say 'with a few synthetic text files, then delete it. OneDrive may upload it while it exists and keep it in its' 'Yellow'
    Say 'online recycle bin for a while. Your OneDrive settings and your own files are not changed.' 'Yellow'
    # The safe default comes FIRST in the question (C-5: "Type Y ..." first was read as the thing to do).
    $useOneDrive = Get-QAOneDriveChoice { Read-QAAnswer 'OneDrive cases: press Enter to SKIP them (recommended). Type Y only if you were asked to include them' }
    if ($useOneDrive) { Say 'OneDrive cases will run (you typed Y).' 'Yellow' }
    else { Say 'OneDrive cases will be skipped; the local cases still run.' 'Yellow' }
}

# Start of the LOCAL self-test (the launcher's double-click consent): with -Yes a 10-second countdown in which closing
# the window cancels; without -Yes a typed YES. This is ONLY the local start - it never decides the OneDrive cases.
if (-not (Confirm-Start 'cleanup self-test (local synthetic checks only)')) {
    Say 'Cancelled. Nothing was run.' 'Yellow'
    $script:CleanupExit = 9
    return
}

$script:ClCtr = Join-Path $localAppData ('Temp\LotRadar Test Sandbox ' + (New-Hex8))
[void](New-QAOwnedFolder $script:ClCtr 'sandbox' $realLedger 'Disposable LotRadar cleanup self-test fixtures. Synthetic files only.')
$odCtr = ''
try {
    Invoke-CL 'CL01' 'Owned interrupted local sandbox, answer D: deleted, ledger entry removed' {
        $f = New-Fixture 'CL01'
        $c = New-Candidate $f 'sandbox' -Owned
        $lf = Get-LedgerFileFor $f.Ledger $c
        $r = Invoke-Repair $f @('D')
        Assert-CL (-not (Test-Path -LiteralPath $c)) ('folder still exists; report: ' + ($r.Lines -join '; '))
        Assert-CL (-not (Test-Path -LiteralPath $lf)) 'ledger entry not removed'
        Assert-CL ($script:ClAsked -eq 1) ('asked ' + $script:ClAsked + ' times, expected 1')
        Assert-CL ($null -eq $r.Stop) 'repair stopped'
        return ('deleted (incl. a read-only file); report: ' + ($r.Lines -join '; '))
    }
    Invoke-CL 'CL02' 'Owned leftover, consent declined (Enter): nothing changes' {
        $f = New-Fixture 'CL02'
        $c = New-Candidate $f 'sandbox' -Owned
        $before = Get-Snapshot $c
        $r = Invoke-Repair $f @('')
        Assert-CL ((Get-Snapshot $c) -eq $before) 'folder changed'
        Assert-CL ((Get-LedgerFileFor $f.Ledger $c) -ne '') 'ledger entry lost'
        Assert-CL (($r.Lines -join ';') -like '*kept (your choice)*') 'kept line missing'
        return 'kept byte-identical'
    }
    Invoke-CL 'CL03' 'Unrelated same-prefix folder (no owner marker): untouched, never offered' {
        $f = New-Fixture 'CL03'
        $c = New-Candidate $f 'sandbox'
        $before = Get-Snapshot $c
        $r = Invoke-Repair $f @('D')
        Assert-CL ((Get-Snapshot $c) -eq $before) 'folder changed'
        Assert-CL ($script:ClAsked -eq 0) 'it was offered for deletion'
        return ($r.Lines -join '; ')
    }
    Invoke-CL 'CL04' 'Owned folder whose name is not exactly the kit pattern: untouched' {
        $f = New-Fixture 'CL04'
        $c = New-Candidate $f 'sandbox' -Owned -Name 'LotRadar Test Sandbox my notes'
        $before = Get-Snapshot $c
        $r = Invoke-Repair $f @('D')
        Assert-CL ((Get-Snapshot $c) -eq $before) 'folder changed'
        Assert-CL ($script:ClAsked -eq 0) 'it was offered for deletion'
        return ($r.Lines -join '; ')
    }
    Invoke-CL 'CL05' 'Modified owner marker (token not in ledger): untouched' {
        $f = New-Fixture 'CL05'
        $c = New-Candidate $f 'sandbox' -Owned
        [IO.File]::WriteAllText((Join-Path $c $script:QAOwnerMarker), ('token=' + (New-QAOwnerToken) + "`r`nkind=sandbox`r`n"), $enc)
        $before = Get-Snapshot $c
        $r = Invoke-Repair $f @('D')
        Assert-CL ((Get-Snapshot $c) -eq $before) 'folder changed'
        Assert-CL ($script:ClAsked -eq 0) 'it was offered for deletion'
        return ($r.Lines -join '; ')
    }
    Invoke-CL 'CL06' 'Ledger records a different path for the token (renamed/moved folder): untouched' {
        $f = New-Fixture 'CL06'
        $c = New-Candidate $f 'sandbox' -Owned
        $lf = Get-LedgerFileFor $f.Ledger $c
        $other = Join-Path $f.Temp ('LotRadar Test Sandbox ' + (New-Hex8))
        New-Item -ItemType Directory -Path $other | Out-Null   # keeps the entry from being pruned
        [IO.File]::WriteAllText($lf, ([IO.File]::ReadAllText($lf) -replace '(?m)^path=.*$', ('path=' + $other.Replace('$', '$$'))), $enc)
        $before = Get-Snapshot $c
        $r = Invoke-Repair $f @('D', 'D')
        Assert-CL ((Get-Snapshot $c) -eq $before) 'folder changed'
        Assert-CL ($script:ClAsked -eq 0) 'something was offered for deletion'
        return ($r.Lines -join '; ')
    }
    Invoke-CL 'CL07' 'Owned leftover containing a JUNCTION to an outside folder: refused, junction and target untouched' {
        $f = New-Fixture 'CL07'
        $c = New-Candidate $f 'sandbox' -Owned
        $mk = Invoke-Cmd ('mklink /J "' + (Join-Path $c 'sub\escape') + '" "' + $f.Out + '"')
        Assert-CL ($mk.Code -eq 0) ('mklink /J failed: ' + $mk.Output)
        $before = Get-Snapshot $c; $outBefore = Get-Snapshot $f.Out
        $r = Invoke-Repair $f @('D')
        Assert-CL ((Get-Snapshot $c) -eq $before) 'leftover changed'
        Assert-CL ((Get-Snapshot $f.Out) -eq $outBefore) 'OUTSIDE target changed'
        Assert-CL ($script:ClAsked -eq 0) 'it was offered for deletion'
        Assert-CL (($r.Lines -join ';') -like '*contains a link*') 'reason missing'
        return ($r.Lines -join '; ')
    }
    Invoke-CL 'CL08' 'Owned leftover containing a FILE SYMLINK: refused, link and target untouched' {
        $f = New-Fixture 'CL08'
        $c = New-Candidate $f 'sandbox' -Owned
        $mk = Invoke-Cmd ('mklink "' + (Join-Path $c 'sub\link.txt') + '" "' + (Join-Path $f.Out 'b.txt') + '"')
        if ($mk.Code -ne 0) { return ('BLOCKED: cannot create a file symlink on this account (Developer Mode off?): ' + $mk.Output.Trim()) }
        $before = Get-Snapshot $c; $outBefore = Get-Snapshot $f.Out
        $r = Invoke-Repair $f @('D')
        Assert-CL ((Get-Snapshot $c) -eq $before) 'leftover changed'
        Assert-CL ((Get-Snapshot $f.Out) -eq $outBefore) 'OUTSIDE target changed'
        Assert-CL ($script:ClAsked -eq 0) 'it was offered for deletion'
        return ($r.Lines -join '; ')
    }
    Invoke-CL 'CL09' 'Leftover that is ITSELF a junction (to a folder with a valid marker): refused, target untouched' {
        $f = New-Fixture 'CL09'
        $realDir = New-Candidate $f 'sandbox' -Owned -Parent $f.Out
        $link = Join-Path $f.Temp ('LotRadar Test Sandbox ' + (New-Hex8))
        $mk = Invoke-Cmd ('mklink /J "' + $link + '" "' + $realDir + '"')
        Assert-CL ($mk.Code -eq 0) ('mklink /J failed: ' + $mk.Output)
        $lf = Get-LedgerFileFor $f.Ledger $realDir
        [IO.File]::WriteAllText($lf, ([IO.File]::ReadAllText($lf) -replace '(?m)^path=.*$', ('path=' + $link.Replace('$', '$$'))), $enc)
        $before = Get-Snapshot $realDir
        $r = Invoke-Repair $f @('D')
        Assert-CL ((Get-Snapshot $realDir) -eq $before) 'junction TARGET changed'
        Assert-CL ((Get-QAEntryKind $link) -like 'link:*') 'junction removed'
        Assert-CL ($script:ClAsked -eq 0) 'it was offered for deletion'
        return ($r.Lines -join '; ')
    }
    Invoke-CL 'CL10' 'Owned leftover holding the ONLY copy of a Desktop shortcut backup: refused' {
        $f = New-Fixture 'CL10'
        $c = New-Candidate $f 'sandbox' -Owned
        New-Lnk (Join-Path $c 'desktop-backup\LotRadar.lnk') $f.Std
        $before = Get-Snapshot $c
        $r = Invoke-Repair $f @('D')
        Assert-CL ((Get-Snapshot $c) -eq $before) 'folder changed'
        Assert-CL ($script:ClAsked -eq 0) 'it was offered for deletion'
        return ($r.Lines -join '; ')
    }
    Invoke-CL 'CL11' 'Leftover TEST Desktop shortcut + owned sandbox with a standard backup: restored byte-identical' {
        $f = New-Fixture 'CL11'
        $c = New-Candidate $f 'sandbox' -Owned
        $bk = Join-Path $c 'desktop-backup\LotRadar.lnk'
        New-Lnk $bk $f.Std
        $testTarget = Join-Path $c 'Local\Programs\MarketplaceScanner\Launch Marketplace Scanner.cmd'
        New-Item -ItemType Directory -Path (Split-Path -Parent $testTarget) -Force | Out-Null
        [IO.File]::WriteAllText($testTarget, '@echo test launcher', $enc)
        New-Lnk $f.Desk $testTarget
        $testSha = Get-Sha $f.Desk
        $r = Invoke-Repair $f @('')
        Assert-CL ($null -eq $r.Stop) ('stopped: ' + $r.Stop)
        Assert-CL ((Get-Sha $f.Desk) -eq (Get-Sha $bk)) 'Desktop shortcut is not byte-identical to the backup'
        Assert-CL (Test-QASamePath (Get-QAShortcutTarget $f.Desk) $f.Std) 'restored shortcut does not target the standard launcher'
        Assert-CL ((Get-Sha (Join-Path $f.Evid 'replaced-test-shortcut.lnk')) -eq $testSha) 'replaced test shortcut not kept as evidence'
        Assert-CL ((Get-Sha $f.Store) -eq (Get-Sha $bk)) 'saved copy not updated'
        Assert-CL (Test-Path -LiteralPath $c) 'sandbox removed although the answer was Enter'
        return ($r.Lines -join '; ')
    }
    Invoke-CL 'CL12' 'TEST shortcut whose only backup is itself a test shortcut, no saved copy, answer Enter: STOP, nothing changed' {
        $f = New-Fixture 'CL12'
        $c = New-Candidate $f 'sandbox' -Owned
        $testTarget = Join-Path $c 'Local\Programs\MarketplaceScanner\Launch Marketplace Scanner.cmd'
        New-Item -ItemType Directory -Path (Split-Path -Parent $testTarget) -Force | Out-Null
        [IO.File]::WriteAllText($testTarget, '@echo test launcher', $enc)
        New-Lnk (Join-Path $c 'desktop-backup\LotRadar.lnk') $testTarget
        New-Lnk $f.Desk $testTarget
        $deskSha = Get-Sha $f.Desk; $before = Get-Snapshot $c
        $r = Invoke-Repair $f @('')
        Assert-CL ($null -ne $r.Stop) 'did not stop'
        Assert-CL ((Get-Sha $f.Desk) -eq $deskSha) 'Desktop shortcut changed'
        Assert-CL ((Get-Snapshot $c) -eq $before) 'sandbox changed'
        Assert-CL (-not (Test-Path -LiteralPath $f.Store)) 'a saved copy was created from a test shortcut'
        return ('stopped: ' + $r.Stop)
    }
    Invoke-CL 'CL13' 'TEST shortcut with NO backup anywhere, answer D: test shortcut deleted, copy kept as evidence' {
        $f = New-Fixture 'CL13'
        $c = New-Candidate $f 'sandbox' -Owned
        New-Lnk $f.Desk (Join-Path $c 'Local\Programs\MarketplaceScanner\Launch Marketplace Scanner.cmd')
        $deskSha = Get-Sha $f.Desk
        $r = Invoke-Repair $f @('D', '')
        Assert-CL ($null -eq $r.Stop) ('stopped: ' + $r.Stop)
        Assert-CL (-not (Test-Path -LiteralPath $f.Desk)) 'test shortcut still on the Desktop'
        Assert-CL ((Get-Sha (Join-Path $f.Evid 'replaced-test-shortcut.lnk')) -eq $deskSha) 'evidence copy missing'
        return ($r.Lines -join '; ')
    }
    Invoke-CL 'CL14' 'Unfamiliar same-name Desktop shortcut (another target): untouched, not saved' {
        $f = New-Fixture 'CL14'
        # A target OUTSIDE every test folder (the fixture container itself is named "LotRadar Test Sandbox <id>",
        # so a target inside it is, correctly, treated as an unrecorded test sandbox: Windows run 2026-11-17).
        # Only the shortcut points at it; the program itself is never run or touched.
        $other = Join-Path $env:SystemRoot 'System32\notepad.exe'
        New-Lnk $f.Desk $other
        $deskSha = Get-Sha $f.Desk
        $r = Invoke-Repair $f @('D')
        Assert-CL ($null -eq $r.Stop) ('stopped: ' + $r.Stop)
        Assert-CL ((Get-Sha $f.Desk) -eq $deskSha) 'shortcut changed'
        Assert-CL (-not (Test-Path -LiteralPath $f.Store)) 'unfamiliar shortcut was saved as the original'
        return ($r.Lines -join '; ')
    }
    Invoke-CL 'CL15' 'Shortcut into a test sandbox this kit has no record of: STOP, untouched' {
        $f = New-Fixture 'CL15'
        $c = New-Candidate $f 'sandbox'
        New-Lnk $f.Desk (Join-Path $c 'Local\Programs\MarketplaceScanner\Launch Marketplace Scanner.cmd')
        $deskSha = Get-Sha $f.Desk; $before = Get-Snapshot $c
        $r = Invoke-Repair $f @('D', 'D')
        Assert-CL ($null -ne $r.Stop) 'did not stop'
        Assert-CL ((Get-Sha $f.Desk) -eq $deskSha) 'shortcut changed'
        Assert-CL ((Get-Snapshot $c) -eq $before) 'folder changed'
        Assert-CL ($script:ClAsked -eq 0) 'something was offered'
        return ('stopped: ' + $r.Stop)
    }
    Invoke-CL 'CL16' 'Standard Desktop shortcut: untouched, verified copy saved' {
        $f = New-Fixture 'CL16'
        New-Lnk $f.Desk $f.Std
        $deskSha = Get-Sha $f.Desk
        $r = Invoke-Repair $f @()
        Assert-CL ($null -eq $r.Stop) ('stopped: ' + $r.Stop)
        Assert-CL ((Get-Sha $f.Desk) -eq $deskSha) 'shortcut changed'
        Assert-CL ((Get-Sha $f.Store) -eq $deskSha) 'saved copy missing or different'
        return 'saved copy byte-identical'
    }
    Invoke-CL 'CL17' 'Mismatched saved copy (not a standard shortcut) is never used to restore: STOP' {
        $f = New-Fixture 'CL17'
        $c = New-Candidate $f 'sandbox' -Owned
        $other = Join-Path $f.Out 'other-app.cmd'
        [IO.File]::WriteAllText($other, '@echo other', $enc)
        New-Lnk $f.Store $other
        New-Lnk $f.Desk (Join-Path $c 'Local\Programs\MarketplaceScanner\Launch Marketplace Scanner.cmd')
        $deskSha = Get-Sha $f.Desk; $storeSha = Get-Sha $f.Store
        $r = Invoke-Repair $f @('')
        Assert-CL ($null -ne $r.Stop) 'did not stop'
        Assert-CL ((Get-Sha $f.Desk) -eq $deskSha) 'Desktop shortcut changed'
        Assert-CL ((Get-Sha $f.Store) -eq $storeSha) 'saved copy changed'
        return ('stopped: ' + $r.Stop)
    }
    Invoke-CL 'CL18' 'Folder swapped for a junction AFTER the check (race): deletion stops, outside target untouched' {
        $f = New-Fixture 'CL18'
        $c = New-Candidate $f 'sandbox' -Owned
        $own = Test-QAOwnedFolder $c 'sandbox' $f.Temp @(Read-QALedger $f.Ledger) @()
        Assert-CL $own.Owned ('setup: not owned: ' + $own.Reason)
        $sub = Join-Path $c 'sub'
        foreach ($x in @((Join-Path $sub 'deep\c.bin'), (Join-Path $sub 'b.txt'))) { [IO.File]::Delete($x) }
        [IO.File]::SetAttributes((Join-Path $sub 'readonly.txt'), [IO.FileAttributes]::Normal); [IO.File]::Delete((Join-Path $sub 'readonly.txt'))
        [IO.Directory]::Delete((Join-Path $sub 'deep')); [IO.Directory]::Delete($sub)
        $mk = Invoke-Cmd ('mklink /J "' + $sub + '" "' + $f.Out + '"')
        Assert-CL ($mk.Code -eq 0) ('mklink /J failed: ' + $mk.Output)
        $outBefore = Get-Snapshot $f.Out
        $res = Remove-QAOwnedFolder $own $f.Temp
        Assert-CL ($res -like 'stopped*') ('deletion did not stop: ' + $res)
        Assert-CL ((Get-Snapshot $f.Out) -eq $outBefore) 'OUTSIDE target changed (same-named b.txt deleted through the junction?)'
        Assert-CL ((Get-QAEntryKind $sub) -like 'link:*') 'junction removed'
        return $res
    }
    Invoke-CL 'CL19' 'No console (input redirected): the question is answered "keep" without reading input' {
        $mod = Join-Path $PSScriptRoot 'LotRadarQA.Cleanup.ps1'
        $cmd = "& { . '" + $mod.Replace("'", "''") + "'; `$a = Read-QAAnswer 'q'; if (`$a -eq '') { 'EMPTY' } else { 'GOT:' + `$a } }"
        $out = ('D' | & $psExe -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command $cmd 2>&1 | Out-String).Trim()
        Assert-CL (($out -match '(?m)^EMPTY$') -and ($out -notmatch 'GOT:')) ('got: ' + $out)
        return 'redirected input -> keep'
    }
    Invoke-CL 'CL20' 'Ledger entries for folders that are gone are forgotten; others kept' {
        $f = New-Fixture 'CL20'
        $c = New-Candidate $f 'sandbox' -Owned
        $gone = New-Candidate $f 'sandbox' -Owned
        $goneLedger = Get-LedgerFileFor $f.Ledger $gone
        Remove-LinksInside $gone
        $own = Test-QAOwnedFolder $gone 'sandbox' $f.Temp @(Read-QALedger $f.Ledger) @()
        Assert-CL ((Remove-QAOwnedFolder $own $f.Temp) -eq 'deleted') 'setup delete failed'
        [IO.File]::WriteAllText($goneLedger, ('token=' + [IO.Path]::GetFileNameWithoutExtension($goneLedger) + "`r`nkind=sandbox`r`npath=" + $gone + "`r`n"), $enc)
        $r = Invoke-Repair $f @('')
        Assert-CL (-not (Test-Path -LiteralPath $goneLedger)) 'stale ledger entry kept'
        Assert-CL ((Get-LedgerFileFor $f.Ledger $c) -ne '') 'live ledger entry removed'
        return 'stale entry removed, live entry kept'
    }
    if (-not $useOneDrive) {
        Add-CL 'CL21' 'OneDrive owned leftover (cloud placeholders), answer D: deleted' 'SKIP' 'no OneDrive found, or OneDrive cases not consented'
        Add-CL 'CL22' 'OneDrive same-prefix folder without owner record: untouched' 'SKIP' 'no OneDrive found, or OneDrive cases not consented'
    } else {
        $odCtr = Join-Path $odParents[0] ('LotRadar QA TEST ONLY ' + (New-Hex8))
        [void](New-QAOwnedFolder $odCtr 'onedrive' $realLedger 'Disposable LotRadar cleanup self-test fixture (OneDrive). Synthetic files only.')
        Invoke-CL 'CL21' 'OneDrive owned leftover (cloud placeholders), answer D: deleted' {
            $f = New-Fixture 'CL21'
            $odp = Join-Path $odCtr 'parent'
            New-Item -ItemType Directory -Path $odp | Out-Null
            $f.OdParents = @($odp)
            $c = New-Candidate $f 'onedrive' -Owned -Parent $odp
            $kind = 'none'
            for ($i = 0; $i -lt 30 -and $kind -ne 'cloud'; $i++) { Start-Sleep -Seconds 1; $kind = Get-QAEntryKind $c }
            $r = Invoke-Repair $f @('D')
            Assert-CL (-not (Test-Path -LiteralPath $c)) ('folder still exists; report: ' + ($r.Lines -join '; '))
            Assert-CL ($script:ClAsked -eq 1) ('asked ' + $script:ClAsked + ' times')
            return ('folder kind before delete=' + $kind + ' tag ' + [LotRadarQA.OwnedFs]::Tag($odp).ToString('X8') + '; deleted')
        }
        Invoke-CL 'CL22' 'OneDrive same-prefix folder without owner record: untouched' {
            $f = New-Fixture 'CL22'
            $odp = Join-Path $odCtr 'parent22'
            New-Item -ItemType Directory -Path $odp | Out-Null
            $f.OdParents = @($odp)
            $c = New-Candidate $f 'onedrive' -Parent $odp
            $before = Get-Snapshot $c
            $r = Invoke-Repair $f @('D')
            Assert-CL ((Get-Snapshot $c) -eq $before) 'folder changed'
            Assert-CL ($script:ClAsked -eq 0) 'it was offered for deletion'
            return ($r.Lines -join '; ')
        }
    }
} finally {
    # Remove the fixture folders created above: link NODES first (never their targets), then the safe deleter.
    foreach ($pair in @(@($script:ClCtr, 'sandbox', (Join-Path $localAppData 'Temp')), @($odCtr, 'onedrive', $(if ($odCtr) { Split-Path -Parent $odCtr } else { '' })))) {
        if (-not $pair[0] -or -not (Test-Path -LiteralPath $pair[0])) { continue }
        $res = ''
        try {
            Remove-LinksInside $pair[0]
            $own = Test-QAOwnedFolder $pair[0] $pair[1] $pair[2] @(Read-QALedger $realLedger) @()
            if ($own.Owned) { $res = Remove-QAOwnedFolder $own $pair[2] } else { $res = 'left in place: ' + $own.Reason }
        } catch { $res = 'left in place: ' + $_.Exception.Message }
        Say ('Fixture folder ' + (Split-Path -Leaf $pair[0]) + ': ' + $res) 'Gray'
        if ($res -ne 'deleted') { [void]$clRows.Add([pscustomobject]@{ Id = 'CLX'; Name = 'Fixture cleanup'; Status = 'FAIL'; Detail = ((Split-Path -Leaf $pair[0]) + ': ' + $res + ' (safe to delete by hand)') }) }
    }
}

Invoke-CL 'CL23' 'Real Desktop shortcut, real saved copy and real ledger unchanged by the self-test' {
    $deskNow = '<none>'; if (Test-Path -LiteralPath $desktopLnk) { $deskNow = Get-Sha $desktopLnk }
    $storeNow = '<none>'; if (Test-Path -LiteralPath $realStore) { $storeNow = Get-Sha $realStore }
    $ledgerNow = @(Read-QALedger $realLedger | ForEach-Object { $_.Token } | Sort-Object) -join ','
    Assert-CL ($deskNow -eq $realDeskBefore) 'real Desktop LotRadar.lnk changed'
    Assert-CL ($storeNow -eq $realStoreBefore) 'real saved shortcut copy changed'
    Assert-CL ($ledgerNow -eq $realLedgerBefore) 'real ledger changed (fixture entry left behind?)'
    return ('Desktop LotRadar.lnk ' + $(if ($deskNow -eq '<none>') { 'absent before and after' } else { 'byte-identical' }) + '; saved copy unchanged; ledger unchanged')
}

# ---- summary (local results folder; sanitized)
$fails = @($clRows | Where-Object { $_.Status -eq 'FAIL' }).Count
$pass = @($clRows | Where-Object { $_.Status -eq 'PASS' }).Count
$skip = @($clRows | Where-Object { $_.Status -eq 'SKIP' }).Count
$blocked = @($clRows | Where-Object { $_.Status -eq 'BLOCKED' }).Count
$lines = @(
    'LotRadar QA kit: leftover-cleanup safety self-test',
    ('Kit commit      : ' + $info.source_commit),
    ('Windows         : ' + $os.Caption + ' version ' + $os.Version + ' build ' + $os.BuildNumber + ' (Windows 11: ' + $isWin11 + ')'),
    ('PowerShell      : ' + $PSVersionTable.PSVersion + '; administrator: ' + $isAdmin),
    ('OneDrive cases  : ' + $(if ($useOneDrive) { 'run' } else { 'skipped' })),
    ('Results         : PASS=' + $pass + ' FAIL=' + $fails + ' SKIP=' + $skip + ' BLOCKED=' + $blocked)
)
foreach ($row in $clRows) { $lines += ($row.Id + ' ' + $row.Status + ' - ' + $row.Name + ' :: ' + $row.Detail) }
$text = Protect-Text ($lines -join "`r`n")
[IO.File]::WriteAllText((Join-Path $resultsDir 'SUMMARY.txt'), $text + "`r`n", $enc)
[IO.File]::WriteAllText((Join-Path $resultsDir 'SANITIZED-cleanup-selftest.json'), (Protect-Text (@{ results = @($clRows); kit_commit = $info.source_commit } | ConvertTo-Json -Depth 4)), $enc)
Say ''
Say '=== CLEANUP SELF-TEST SUMMARY ===' 'Cyan'
Say $text
Say ''
Say ('Send back SUMMARY.txt and SANITIZED-cleanup-selftest.json from: ' + (Protect-Text $resultsDir)) 'Green'
try { Start-Process -FilePath 'explorer.exe' -ArgumentList ('"' + $resultsDir + '"') } catch { }
if ($fails -gt 0) { $script:CleanupExit = 1 } else { $script:CleanupExit = 0 }
return
