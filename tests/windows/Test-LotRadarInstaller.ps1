<#
.SYNOPSIS
  Windows acceptance tests for the LotRadar installer package. SYNTHETIC DATA ONLY, fully sandboxed.

.DESCRIPTION
  Run in Windows PowerShell 5.1 (powershell.exe) as a NORMAL user (not administrator):

      powershell.exe -NoProfile -ExecutionPolicy Bypass -File Test-LotRadarInstaller.ps1 -PackageZip "C:\path\LotRadar-Installer-....zip"

  Safety model:
    * LOCALAPPDATA and APPDATA are pointed at a throw-away sandbox folder (path contains spaces on purpose)
      for this script and every child process, so the real %LOCALAPPDATA%\MarketplaceScanner,
      %LOCALAPPDATA%\Programs and the real Start menu are never touched.
    * The ONE shared location is your real Desktop: the installer always writes LotRadar.lnk there.
      An existing LotRadar.lnk is backed up first and restored at the end (or the test one is deleted).
    * Fixture "inventory", drafts and photos are random bytes created by this script. No real data is read.
    * Close the real LotRadar first: tests that need port 8765 are skipped if something already listens there.

  Output: a transcript log and a results JSON next to the ZIP. Send both back.
  Switches:
    -FullLaunch   also runs the REAL bootstrap in the sandbox (downloads Python packages and Playwright
                  Chromium into the sandbox, may take many minutes, opens the app window, then stops it).
    -KeepSandbox  do not delete the sandbox folder afterwards.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PackageZip,
    [switch]$FullLaunch,
    [switch]$KeepSandbox
)
$ErrorActionPreference = 'Stop'
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
$zipPath = (Resolve-Path -LiteralPath $PackageZip).Path
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$logPath = Join-Path (Split-Path -Parent $zipPath) ('LotRadar-WindowsTest-' + $stamp + '.log')
$jsonPath = Join-Path (Split-Path -Parent $zipPath) ('LotRadar-WindowsTest-' + $stamp + '.json')
Start-Transcript -Path $logPath | Out-Null

$script:Results = New-Object System.Collections.ArrayList
$script:Locks = New-Object System.Collections.ArrayList
$script:Listener = $null
$origLocal = $env:LOCALAPPDATA
$origRoam = $env:APPDATA
$sandboxId = [Guid]::NewGuid().ToString('N').Substring(0, 8)
$root = Join-Path $env:TEMP ('LotRadar Test Sandbox ' + $sandboxId)
$local = Join-Path $root 'Local'
$roam = Join-Path $root 'Roaming'
$program = Join-Path $local 'Programs\MarketplaceScanner'
$programsDir = Join-Path $local 'Programs'
$userRoot = Join-Path $local 'MarketplaceScanner'
$dataDir = Join-Path $userRoot 'data'
$runtimeDir = Join-Path $userRoot 'runtime'
$backupRoot = Join-Path $userRoot 'ProgramBackups'
$desktop = [Environment]::GetFolderPath('Desktop')
$desktopLnk = Join-Path $desktop 'LotRadar.lnk'
$desktopBackup = Join-Path $root 'desktop-backup\LotRadar.lnk'
$desktopHadLnk = $false

# ---------------------------------------------------------------- helpers
function Add-Result([string]$Id, [string]$Name, [string]$Status, [string]$Detail) {
    $row = [pscustomobject]@{ Id = $Id; Name = $Name; Status = $Status; Detail = $Detail }
    [void]$script:Results.Add($row)
    $color = 'Gray'
    if ($Status -eq 'PASS') { $color = 'Green' } elseif ($Status -eq 'FAIL') { $color = 'Red' } elseif ($Status -eq 'SKIP') { $color = 'Yellow' }
    Write-Host ('[{0}] {1} {2} {3}' -f $Status, $Id, $Name, $Detail) -ForegroundColor $color
}
function Invoke-Test([string]$Id, [string]$Name, [scriptblock]$Body) {
    try {
        $detail = @(& $Body) | Select-Object -Last 1
        Add-Result $Id $Name 'PASS' ([string]$detail)
    } catch {
        Add-Result $Id $Name 'FAIL' $_.Exception.Message
    }
}
function Skip-Test([string]$Id, [string]$Name, [string]$Why) { Add-Result $Id $Name 'SKIP' $Why }
function Assert-True($Condition, [string]$Message) { if (-not $Condition) { throw $Message } }

function Get-Sha([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Get-Inventory([string]$Dir) {
    if (-not (Test-Path -LiteralPath $Dir)) { return @('<absent>') }
    $base = (Resolve-Path -LiteralPath $Dir).Path.TrimEnd('\')
    $rows = @(Get-ChildItem -LiteralPath $Dir -Recurse -File -Force | Sort-Object FullName | ForEach-Object {
        $_.FullName.Substring($base.Length).TrimStart('\') + '|' + (Get-Sha $_.FullName)
    })
    if ($rows.Count -eq 0) { return @('<empty>') }
    return $rows
}
function Get-State {
    $backupCount = 0
    if (Test-Path -LiteralPath $backupRoot) { $backupCount = @(Get-ChildItem -LiteralPath $backupRoot -Directory -Force).Count }
    return [pscustomobject]@{
        Program = (Get-Inventory $program) -join "`n"
        Data    = (Get-Inventory $dataDir) -join "`n"
        Backups = $backupCount
    }
}
function Get-StageDirs {
    if (-not (Test-Path -LiteralPath $programsDir)) { return @() }
    return @(Get-ChildItem -LiteralPath $programsDir -Directory -Force | Where-Object { $_.Name -like '.MarketplaceScanner-stage-*' })
}
function Assert-Unchanged($Before, [string]$What) {
    $now = Get-State
    Assert-True ($now.Program -eq $Before.Program) ($What + ': installed program folder CHANGED')
    Assert-True ($now.Data -eq $Before.Data) ($What + ': data folder CHANGED')
    Assert-True ($now.Backups -eq $Before.Backups) ($What + ': a program backup was created/removed')
    Assert-True ((Get-StageDirs).Count -eq 0) ($What + ': leftover staging folder')
}
function Invoke-Installer([string]$PkgDir) {
    $ErrorActionPreference = 'Continue'
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PkgDir 'Install-LotRadar.ps1') 2>&1 | Out-String
    $code = $LASTEXITCODE
    return [pscustomobject]@{ Code = $code; Output = $out }
}
function Invoke-CmdScript([string]$ScriptPath) {
    $runner = Join-Path $env:TEMP ('lotradar-run-' + [Guid]::NewGuid().ToString('N') + '.cmd')
    $lines = @('@echo off', ('call "' + $ScriptPath + '" < nul'), 'exit /b %errorlevel%')
    [IO.File]::WriteAllText($runner, (($lines -join "`r`n") + "`r`n"), [Text.Encoding]::ASCII)
    $ErrorActionPreference = 'Continue'
    $out = & cmd.exe /d /c $runner 2>&1 | Out-String
    $code = $LASTEXITCODE
    Remove-Item -LiteralPath $runner -Force -ErrorAction SilentlyContinue
    return [pscustomobject]@{ Code = $code; Output = $out }
}
function Test-PortBusy {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $probe = $client.BeginConnect([Net.IPAddress]::Loopback, 8765, $null, $null)
        return ($probe.AsyncWaitHandle.WaitOne(500) -and $client.Connected)
    } catch { return $false } finally { $client.Dispose() }
}
function New-PkgCopy([string]$Name) {
    $dst = Join-Path $root ('pkg ' + $Name)
    Copy-Item -LiteralPath $pkgDir -Destination $dst -Recurse
    return $dst
}
function Get-Manifest([string]$Dir) { return (Get-Content -LiteralPath (Join-Path $Dir 'Install-Manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json) }
function Save-Manifest([string]$Dir, $Manifest) {
    [IO.File]::WriteAllText((Join-Path $Dir 'Install-Manifest.json'), ($Manifest | ConvertTo-Json -Depth 8), $utf8NoBom)
}
function Add-ManifestEntry($Manifest, [string]$Path, [string]$Sha) {
    $entry = [pscustomobject]@{ path = $Path; sha256 = $Sha; bytes = 1 }
    $Manifest.payload_files = @($Manifest.payload_files) + $entry
}
function Release-Locks {
    foreach ($l in @($script:Locks)) { try { $l.Dispose() } catch { } }
    $script:Locks.Clear()
    if ($script:Listener) { try { $script:Listener.Stop() } catch { }; $script:Listener = $null }
}

# ---------------------------------------------------------------- run
try {
    Write-Host '=== LotRadar Windows installer acceptance tests ===' -ForegroundColor Cyan
    Write-Host ('Package : ' + $zipPath)
    Write-Host ('Sandbox : ' + $root)
    New-Item -ItemType Directory -Path $local, $roam -Force | Out-Null
    if (Test-Path -LiteralPath $desktopLnk) {
        $desktopHadLnk = $true
        New-Item -ItemType Directory -Path (Split-Path -Parent $desktopBackup) -Force | Out-Null
        Copy-Item -LiteralPath $desktopLnk -Destination $desktopBackup -Force
        Write-Host 'Existing Desktop LotRadar.lnk backed up; it will be restored.' -ForegroundColor Yellow
    }
    $env:LOCALAPPDATA = $local
    $env:APPDATA = $roam
    $env:LOTRADAR_NO_PAUSE = '1'

    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    $os = Get-CimInstance Win32_OperatingSystem
    Add-Result 'T00' 'Environment' 'INFO' ('OS=' + $os.Caption + ' build ' + $os.BuildNumber + '; PowerShell=' + $PSVersionTable.PSVersion + '; edition=' + $PSVersionTable.PSEdition + '; admin=' + $isAdmin + '; user=' + $env:USERNAME)
    if ($isAdmin) { Add-Result 'T00a' 'Standard user' 'FAIL' 'Running as administrator. Re-run in a normal (non-elevated) PowerShell.' }
    if ($PSVersionTable.PSVersion.Major -ne 5) { Add-Result 'T00b' 'Windows PowerShell 5.1' 'FAIL' ('This host is PowerShell ' + $PSVersionTable.PSVersion + '. Use powershell.exe (5.1). Child installer runs still use powershell.exe.') }
    $portWasBusy = Test-PortBusy
    if ($portWasBusy) { Add-Result 'T00c' 'Port 8765 free' 'FAIL' 'Something already listens on 127.0.0.1:8765 (real LotRadar?). Close it and re-run; contention and launch tests are skipped.' }

    # ---- extract package (path with spaces)
    $pkgDir = Join-Path $root 'Test Package'
    Expand-Archive -LiteralPath $zipPath -DestinationPath $pkgDir -Force
    $manifest = Get-Manifest $pkgDir
    Add-Result 'T00d' 'Package identity' 'INFO' ('version=' + $manifest.package_version + ' build_type=' + $manifest.build_type + ' commit=' + $manifest.source_commit + ' payload=' + @($manifest.payload_files).Count)

    Invoke-Test 'T01' 'PowerShell 5.1 parser: zero errors in every .ps1 in the package' {
        $files = @(Get-ChildItem -LiteralPath $pkgDir -Recurse -Filter *.ps1 -File)
        Assert-True ($files.Count -ge 2) 'expected at least Install-LotRadar.ps1 and Marketplace Bootstrap.ps1'
        foreach ($f in $files) {
            $tokens = $null; $errors = $null
            [void][System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$tokens, [ref]$errors)
            Assert-True (@($errors).Count -eq 0) ('parser errors in ' + $f.Name + ': ' + ((@($errors) | ForEach-Object { $_.Message }) -join '; '))
        }
        return ('parsed ' + $files.Count + ' files, 0 errors')
    }

    Invoke-Test 'T02' 'Package manifest independently re-verified (hash, exactly once, no extras)' {
        $payloadDir = Join-Path $pkgDir 'MarketplaceScanner'
        $listed = @($manifest.payload_files | ForEach-Object { $_.path.Replace('/', '\') })
        Assert-True ($listed.Count -eq (@($listed | Sort-Object -Unique)).Count) 'duplicate manifest paths'
        foreach ($item in $manifest.payload_files) {
            $f = Join-Path $payloadDir $item.path.Replace('/', '\')
            Assert-True (Test-Path -LiteralPath $f -PathType Leaf) ('missing ' + $item.path)
            Assert-True ((Get-Sha $f) -eq $item.sha256) ('hash mismatch ' + $item.path)
        }
        $actual = @(Get-ChildItem -LiteralPath $payloadDir -Recurse -File | ForEach-Object { $_.FullName.Substring($payloadDir.Length + 1) })
        Assert-True ($actual.Count -eq $listed.Count) ('payload has ' + $actual.Count + ' files but manifest lists ' + $listed.Count)
        return ($listed.Count.ToString() + ' files verified')
    }

    # ---- clean install through the real entry point
    Invoke-Test 'T03' 'Clean install via Installer.cmd (standard user, sandbox path with spaces)' {
        $r = Invoke-CmdScript (Join-Path $pkgDir 'Installer.cmd')
        Assert-True ($r.Code -eq 0) ('exit code ' + $r.Code + "`n" + $r.Output)
        Assert-True ($r.Output -match 'LotRadar is installed') 'success message missing'
        foreach ($item in $manifest.payload_files) {
            $f = Join-Path $program $item.path.Replace('/', '\')
            Assert-True (Test-Path -LiteralPath $f -PathType Leaf) ('not installed: ' + $item.path)
            Assert-True ((Get-Sha $f) -eq $item.sha256) ('installed hash mismatch: ' + $item.path)
        }
        Assert-True (Test-Path -LiteralPath (Join-Path $roam 'Microsoft\Windows\Start Menu\Programs\LotRadar.lnk')) 'Start menu shortcut missing'
        Assert-True (Test-Path -LiteralPath $desktopLnk) 'Desktop shortcut missing'
        $shell = New-Object -ComObject WScript.Shell
        $lnk = $shell.CreateShortcut($desktopLnk)
        Assert-True ($lnk.TargetPath -eq (Join-Path $program 'Launch Marketplace Scanner.cmd')) ('shortcut target wrong: ' + $lnk.TargetPath)
        Assert-True ($lnk.WorkingDirectory -eq $program) ('shortcut working dir wrong: ' + $lnk.WorkingDirectory)
        Assert-True (-not (Test-Path -LiteralPath $backupRoot)) 'fresh install created a backup folder'
        Assert-True ((Get-StageDirs).Count -eq 0) 'leftover staging folder'
        return 'installed, shortcuts OK, all hashes match'
    }

    # ---- synthetic user data
    $rng = New-Object System.Random 12345
    New-Item -ItemType Directory -Path (Join-Path $dataDir 'photos'), (Join-Path $dataDir 'drafts') -Force | Out-Null
    foreach ($spec in @(@('marketplace.sqlite3', 262144), @('photos\a.jpg', 50000), @('photos\b.jpg', 60000), @('photos\c.jpg', 70000))) {
        $bytes = New-Object byte[] $spec[1]; $rng.NextBytes($bytes)
        [IO.File]::WriteAllBytes((Join-Path $dataDir $spec[0]), $bytes)
    }
    [IO.File]::WriteAllText((Join-Path $dataDir 'drafts\draft1.json'), '{"vin":"TESTVIN0000000001","note":"synthetic draft"}', $utf8NoBom)
    [IO.File]::WriteAllText((Join-Path $runtimeDir 'fixture.txt'), 'runtime fixture', $utf8NoBom)
    $dataBefore = (Get-Inventory $dataDir) -join "`n"
    $runtimeBefore = (Get-Inventory $runtimeDir | Where-Object { $_ -notlike 'lotradar-install.lock*' }) -join "`n"
    $stateInstalled = Get-State

    Invoke-Test 'T04' 'Upgrade keeps data byte-for-byte and backs up previous program' {
        $r = Invoke-Installer $pkgDir
        Assert-True ($r.Code -eq 0) ('exit code ' + $r.Code + "`n" + $r.Output)
        Assert-True (((Get-Inventory $dataDir) -join "`n") -eq $dataBefore) 'DATA CHANGED by upgrade'
        $rt = (Get-Inventory $runtimeDir | Where-Object { $_ -notlike 'lotradar-install.lock*' }) -join "`n"
        Assert-True ($rt -eq $runtimeBefore) 'RUNTIME folder content changed by upgrade'
        $backups = @(Get-ChildItem -LiteralPath $backupRoot -Directory)
        Assert-True ($backups.Count -eq 1) ('expected 1 backup, found ' + $backups.Count)
        Assert-True (((Get-Inventory $backups[0].FullName) -join "`n") -eq $stateInstalled.Program) 'backup does not equal the previous program'
        Assert-True (((Get-Inventory $program) -join "`n") -eq $stateInstalled.Program) 'new program differs from expected (same package)'
        Assert-True ((Get-StageDirs).Count -eq 0) 'leftover staging folder'
        return 'data+runtime identical, 1 backup equals previous program'
    }
    $good = Get-State

    # ---- tampering and malformed packages
    Invoke-Test 'T05' 'Altered payload byte is rejected BEFORE anything is replaced' {
        $d = New-PkgCopy 'tamper'
        $f = Join-Path $d 'MarketplaceScanner\core.py'
        $b = [IO.File]::ReadAllBytes($f); $b[10] = $b[10] -bxor 1; [IO.File]::WriteAllBytes($f, $b)
        $r = Invoke-Installer $d
        Assert-True ($r.Code -ne 0) 'installer accepted a tampered package'
        Assert-True ($r.Output -match 'checksum mismatch') ('unexpected message: ' + $r.Output)
        Assert-Unchanged $good 'tamper'
        return 'rejected: checksum mismatch; program/data/backups untouched'
    }
    Invoke-Test 'T06' 'Missing payload file is rejected before swap' {
        $d = New-PkgCopy 'missing'
        Remove-Item -LiteralPath (Join-Path $d 'MarketplaceScanner\app.js') -Force
        $r = Invoke-Installer $d
        Assert-True ($r.Code -ne 0) 'installer accepted a package with a missing file'
        Assert-Unchanged $good 'missing file'
        return 'rejected'
    }
    Invoke-Test 'T07' 'Missing Install-Manifest.json is rejected' {
        $d = New-PkgCopy 'nomanifest'
        Remove-Item -LiteralPath (Join-Path $d 'Install-Manifest.json') -Force
        $r = Invoke-Installer $d
        Assert-True ($r.Code -ne 0) 'installer accepted a package without a manifest'
        Assert-Unchanged $good 'no manifest'
        return 'rejected'
    }

    # ---- adversarial manifests
    $anyHex = ('a' * 64)
    $cases = @(
        @{ Id = 'M01'; Name = 'traversal ..\evil.txt (file planted so hash would match)'; Path = '..\evil.txt'; Plant = 'evil.txt' },
        @{ Id = 'M02'; Name = 'traversal ../evil.txt'; Path = '../evil.txt'; Plant = 'evil.txt' },
        @{ Id = 'M03'; Name = 'absolute drive path'; Path = ($root + '\escape\evil.txt'); Plant = '' },
        @{ Id = 'M04'; Name = 'UNC path'; Path = '\\localhost\c$\evil.txt'; Plant = '' },
        @{ Id = 'M05'; Name = 'leading slash'; Path = '/evil.txt'; Plant = '' },
        @{ Id = 'M06'; Name = 'empty segment a//b.txt'; Path = 'a//b.txt'; Plant = '' },
        @{ Id = 'M07'; Name = 'dot segment a\.\b.txt'; Path = 'a\.\b.txt'; Plant = '' },
        @{ Id = 'M08'; Name = 'reserved device name NUL.txt'; Path = 'NUL.txt'; Plant = '' },
        @{ Id = 'M09'; Name = 'reserved device directory con\x.txt'; Path = 'con\x.txt'; Plant = '' },
        @{ Id = 'M10'; Name = 'trailing dot directory sub.\x.txt'; Path = 'sub.\x.txt'; Plant = '' },
        @{ Id = 'M11'; Name = 'trailing space x.txt<space>'; Path = 'x.txt '; Plant = '' },
        @{ Id = 'M12'; Name = 'alternate data stream core.py:evil'; Path = 'core.py:evil'; Plant = '' }
    )
    foreach ($c in $cases) {
        $case = $c
        Invoke-Test $case.Id ('Manifest rejected: ' + $case.Name) {
            $d = New-PkgCopy $case.Id
            $sha = $anyHex
            if ($case.Plant) {
                $planted = Join-Path $d $case.Plant
                [IO.File]::WriteAllText($planted, 'planted', $utf8NoBom)
                $sha = Get-Sha $planted
            }
            $m = Get-Manifest $d
            Add-ManifestEntry $m $case.Path $sha
            Save-Manifest $d $m
            $r = Invoke-Installer $d
            Assert-True ($r.Code -ne 0) 'installer ACCEPTED the malicious manifest'
            Assert-True (-not (Test-Path -LiteralPath (Join-Path $programsDir 'evil.txt'))) 'FILE ESCAPED the staging folder'
            Assert-Unchanged $good $case.Name
            $line = ($r.Output -split "`r?`n" | Where-Object { $_ -match 'INSTALL ERROR' } | Select-Object -First 1)
            return ('rejected; ' + $line)
        }
    }
    Invoke-Test 'M13' 'Manifest rejected: duplicate path' {
        $d = New-PkgCopy 'M13'; $m = Get-Manifest $d
        $first = @($m.payload_files)[0]
        Add-ManifestEntry $m $first.path $first.sha256; Save-Manifest $d $m
        $r = Invoke-Installer $d
        Assert-True ($r.Code -ne 0) 'accepted'; Assert-Unchanged $good 'duplicate'; return 'rejected'
    }
    Invoke-Test 'M14' 'Manifest rejected: NTFS case-collision (CORE.PY vs core.py)' {
        $d = New-PkgCopy 'M14'; $m = Get-Manifest $d
        $core = @($m.payload_files) | Where-Object { $_.path -eq 'core.py' } | Select-Object -First 1
        Add-ManifestEntry $m 'CORE.PY' $core.sha256; Save-Manifest $d $m
        $r = Invoke-Installer $d
        Assert-True ($r.Code -ne 0) 'accepted'; Assert-Unchanged $good 'case collision'; return 'rejected'
    }
    Invoke-Test 'M15' 'Manifest rejected: malformed hash (too short)' {
        $d = New-PkgCopy 'M15'; $m = Get-Manifest $d
        @($m.payload_files)[0].sha256 = 'abc'; Save-Manifest $d $m
        $r = Invoke-Installer $d
        Assert-True ($r.Code -ne 0) 'accepted'; Assert-Unchanged $good 'short hash'; return 'rejected'
    }
    Invoke-Test 'M16' 'Manifest rejected: UPPERCASE hash' {
        $d = New-PkgCopy 'M16'; $m = Get-Manifest $d
        $e = @($m.payload_files)[0]; $e.sha256 = $e.sha256.ToUpperInvariant(); Save-Manifest $d $m
        $r = Invoke-Installer $d
        Assert-True ($r.Code -ne 0) 'accepted'; Assert-Unchanged $good 'uppercase hash'; return 'rejected'
    }
    Invoke-Test 'M17' 'Manifest rejected: wrong hash value' {
        $d = New-PkgCopy 'M17'; $m = Get-Manifest $d
        @($m.payload_files)[0].sha256 = $anyHex; Save-Manifest $d $m
        $r = Invoke-Installer $d
        Assert-True ($r.Code -ne 0) 'accepted'; Assert-Unchanged $good 'wrong hash'; return 'rejected'
    }
    Invoke-Test 'M18' 'Manifest rejected: empty payload list' {
        $d = New-PkgCopy 'M18'; $m = Get-Manifest $d
        $m.payload_files = @(); Save-Manifest $d $m
        $r = Invoke-Installer $d
        Assert-True ($r.Code -ne 0) 'accepted'; Assert-Unchanged $good 'empty payload'; return 'rejected'
    }
    Invoke-Test 'M19' 'Manifest rejected: wrong product' {
        $d = New-PkgCopy 'M19'; $m = Get-Manifest $d
        $m.product = 'Something Else'; Save-Manifest $d $m
        $r = Invoke-Installer $d
        Assert-True ($r.Code -ne 0) 'accepted'; Assert-Unchanged $good 'wrong product'; return 'rejected'
    }

    # ---- contention and faults
    Invoke-Test 'T08' 'Missing LOCALAPPDATA is reported, nothing changes' {
        $saved = $env:LOCALAPPDATA
        try {
            Remove-Item Env:\LOCALAPPDATA
            $r = Invoke-Installer $pkgDir
        } finally { $env:LOCALAPPDATA = $saved }
        Assert-True ($r.Code -ne 0) 'installer succeeded without LOCALAPPDATA'
        Assert-True ($r.Output -match 'LOCALAPPDATA') ('message does not mention LOCALAPPDATA: ' + $r.Output)
        Assert-Unchanged $good 'no LOCALAPPDATA'
        return 'rejected with explicit message'
    }
    Invoke-Test 'T09' 'Held installer lock aborts safely' {
        New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
        $lock = [IO.File]::Open((Join-Path $runtimeDir 'lotradar-install.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
        [void]$script:Locks.Add($lock)
        try { $r = Invoke-Installer $pkgDir } finally { Release-Locks }
        Assert-True ($r.Code -ne 0) 'installer ran while the lock was held'
        Assert-True ($r.Output -match 'Another LotRadar installer') ('unexpected message: ' + $r.Output)
        Assert-Unchanged $good 'installer lock'
        return 'aborted; nothing changed'
    }
    if ($portWasBusy) {
        Skip-Test 'T10' 'Foreign listener on 127.0.0.1:8765 aborts safely' 'port already busy before the run'
    } else {
        Invoke-Test 'T10' 'Foreign listener on 127.0.0.1:8765 aborts safely' {
            $script:Listener = [System.Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 8765)
            $script:Listener.Start()
            try { $r = Invoke-Installer $pkgDir } finally { Release-Locks }
            Assert-True ($r.Code -ne 0) 'installer ran while port 8765 was active'
            Assert-True ($r.Output -match '8765') ('unexpected message: ' + $r.Output)
            Assert-Unchanged $good 'active port'
            return 'aborted; nothing changed'
        }
    }
    Invoke-Test 'T11' 'Locked file inside installed program: backup/swap fails, old program intact' {
        $held = [System.IO.FileStream]::new((Join-Path $program 'server.py'), [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        [void]$script:Locks.Add($held)
        try { $r = Invoke-Installer $pkgDir } finally { Release-Locks }
        Assert-True ($r.Code -ne 0) 'installer reported success although the program folder could not be moved'
        Assert-Unchanged $good 'locked program file'
        return ('exit ' + $r.Code + '; program, data, backups unchanged. NOTE: the post-swap rollback branch is NOT exercised by any test here.')
    }
    Invoke-Test 'T12' 'Recovery: normal upgrade succeeds again after the failed attempts' {
        $r = Invoke-Installer $pkgDir
        Assert-True ($r.Code -eq 0) ('exit code ' + $r.Code + "`n" + $r.Output)
        Assert-True (((Get-Inventory $dataDir) -join "`n") -eq $dataBefore) 'DATA CHANGED'
        Assert-True (((Get-Inventory $program) -join "`n") -eq $good.Program) 'program differs from package'
        return 'OK'
    }

    # ---- launcher
    $launcherSrc = Join-Path $pkgDir 'MarketplaceScanner\Launch Marketplace Scanner.cmd'
    $lDir = Join-Path $root 'Launcher Test Dir'
    New-Item -ItemType Directory -Path $lDir -Force | Out-Null
    Copy-Item -LiteralPath $launcherSrc -Destination $lDir -Force
    $lPath = Join-Path $lDir 'Launch Marketplace Scanner.cmd'
    $stub = Join-Path $lDir 'Marketplace Bootstrap.ps1'

    Invoke-Test 'L1' 'Launcher: missing bootstrap -> exit 2 and clear message' {
        if (Test-Path -LiteralPath $stub) { Remove-Item -LiteralPath $stub -Force }
        $r = Invoke-CmdScript $lPath
        Assert-True ($r.Code -eq 2) ('exit ' + $r.Code + "`n" + $r.Output)
        Assert-True ($r.Output -match 'was not found') ('message: ' + $r.Output)
        return 'exit 2'
    }
    Invoke-Test 'L2' 'Launcher: runs bootstrap from its own folder (path with spaces), no EXE present' {
        [IO.File]::WriteAllText($stub, 'Write-Host ("STUB-CWD=" + (Get-Location).Path); exit 0', [Text.Encoding]::ASCII)
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $lDir 'LotRadar.exe'))) 'test setup: EXE should be absent'
        $r = Invoke-CmdScript $lPath
        Assert-True ($r.Code -eq 0) ('exit ' + $r.Code + "`n" + $r.Output)
        Assert-True ($r.Output -match [regex]::Escape('STUB-CWD=' + $lDir)) ('working directory wrong: ' + $r.Output)
        return 'exit 0; cwd = launcher folder'
    }
    Invoke-Test 'L3' 'Launcher: dummy LotRadar.exe present is ignored (bootstrap still used)' {
        [IO.File]::WriteAllText((Join-Path $lDir 'LotRadar.exe'), 'not a real exe', [Text.Encoding]::ASCII)
        $r = Invoke-CmdScript $lPath
        Assert-True ($r.Code -eq 0) ('exit ' + $r.Code + "`n" + $r.Output)
        Assert-True ($r.Output -match 'STUB-CWD=') 'bootstrap was not run'
        return 'exit 0; bootstrap ran'
    }
    Invoke-Test 'L4' 'Launcher: failing bootstrap (exit 7) propagates code and shows message' {
        [IO.File]::WriteAllText($stub, 'Write-Host "STUB-FAIL"; exit 7', [Text.Encoding]::ASCII)
        $r = Invoke-CmdScript $lPath
        Assert-True ($r.Code -eq 7) ('exit ' + $r.Code + "`n" + $r.Output)
        Assert-True ($r.Output -match 'error code 7') ('message: ' + $r.Output)
        Assert-True ($r.Output -notmatch 'Press any key') 'paused although LOTRADAR_NO_PAUSE=1'
        return 'exit 7, no pause when LOTRADAR_NO_PAUSE=1'
    }
    Invoke-Test 'L5' 'Launcher: pause appears on error when LOTRADAR_NO_PAUSE is not set' {
        $saved = $env:LOTRADAR_NO_PAUSE
        try {
            Remove-Item Env:\LOTRADAR_NO_PAUSE
            $r = Invoke-CmdScript $lPath
        } finally { $env:LOTRADAR_NO_PAUSE = $saved }
        Assert-True ($r.Code -eq 7) ('exit ' + $r.Code)
        Assert-True ($r.Output -match 'Press any key') ('no pause prompt in output: ' + $r.Output)
        return 'pause prompt shown'
    }
    Invoke-Test 'L6' 'Launcher: successful bootstrap never pauses' {
        [IO.File]::WriteAllText($stub, 'exit 0', [Text.Encoding]::ASCII)
        $saved = $env:LOTRADAR_NO_PAUSE
        try {
            Remove-Item Env:\LOTRADAR_NO_PAUSE
            $r = Invoke-CmdScript $lPath
        } finally { $env:LOTRADAR_NO_PAUSE = $saved }
        Assert-True ($r.Code -eq 0) ('exit ' + $r.Code)
        Assert-True ($r.Output -notmatch 'Press any key') 'paused on success'
        return 'exit 0, no pause'
    }

    # ---- optional: real bootstrap in the sandbox
    if (-not $FullLaunch) {
        Skip-Test 'F1' 'Real bootstrap launch, /api/health, second launch, single server' 'pass -FullLaunch to run (downloads packages, opens the app window)'
    } elseif ($portWasBusy) {
        Skip-Test 'F1' 'Real bootstrap launch' 'port 8765 busy'
    } else {
        Invoke-Test 'F1' 'Real bootstrap: first launch serves healthy local-only API' {
            $launcher = Join-Path $program 'Launch Marketplace Scanner.cmd'
            $log1 = Join-Path $root 'launch1.log'
            $runner = Join-Path $root 'launch1.cmd'
            [IO.File]::WriteAllText($runner, ('@echo off' + "`r`n" + 'call "' + $launcher + '" > "' + $log1 + '" 2>&1' + "`r`n" + 'exit /b %errorlevel%' + "`r`n"), [Text.Encoding]::ASCII)
            $script:launchProc = Start-Process -FilePath cmd.exe -ArgumentList '/d', '/c', ('"' + $runner + '"') -PassThru -WindowStyle Minimized
            $health = $null
            $deadline = (Get-Date).AddMinutes(20)
            while ((Get-Date) -lt $deadline -and -not $script:launchProc.HasExited) {
                try { $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 3; break } catch { Start-Sleep -Seconds 5 }
            }
            if (-not $health) {
                $tail = ''
                if (Test-Path -LiteralPath $log1) { $tail = (Get-Content -LiteralPath $log1 -Tail 25) -join "`n" }
                throw ('no health response; launcher exited=' + $script:launchProc.HasExited + "`n" + $tail)
            }
            Assert-True ($health.ok -eq $true -and $health.local_only -eq $true -and $health.service -eq 'Marketplace Scanner') ('unexpected health payload: ' + ($health | ConvertTo-Json -Compress))
            return 'healthy'
        }
        Invoke-Test 'F2' 'Real bootstrap: second launch does not start a second server' {
            $r = Invoke-CmdScript (Join-Path $program 'Launch Marketplace Scanner.cmd')
            Assert-True ($r.Code -eq 0) ('exit ' + $r.Code + "`n" + $r.Output)
            Assert-True ($r.Output -match 'already running') ('message: ' + $r.Output)
            $procs = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*server.py*' -and $_.CommandLine -like ('*' + $local + '*') })
            Assert-True ($procs.Count -eq 1) ('expected exactly 1 sandbox server process, found ' + $procs.Count)
            return '1 server process'
        }
        Invoke-Test 'F3' 'Real bootstrap: sandbox data folder created, installed program unchanged, no real data touched' {
            Assert-True (Test-Path -LiteralPath $dataDir) 'data dir missing'
            foreach ($item in $manifest.payload_files) {
                Assert-True ((Get-Sha (Join-Path $program $item.path.Replace('/', '\'))) -eq $item.sha256) ('program file changed by launch: ' + $item.path)
            }
            return 'OK'
        }
        # stop the sandbox server
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*server.py*' -and $_.CommandLine -like ('*' + $local + '*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        if ($script:launchProc) { [void]$script:launchProc.WaitForExit(60000) }
    }
} catch {
    Add-Result 'FATAL' 'Test run aborted' 'FAIL' $_.Exception.Message
} finally {
    Release-Locks
    $env:LOCALAPPDATA = $origLocal
    $env:APPDATA = $origRoam
    Remove-Item Env:\LOTRADAR_NO_PAUSE -ErrorAction SilentlyContinue
    try {
        if ($desktopHadLnk) {
            Copy-Item -LiteralPath $desktopBackup -Destination $desktopLnk -Force
            Write-Host 'Original Desktop LotRadar.lnk restored.'
        } elseif (Test-Path -LiteralPath $desktopLnk) {
            Remove-Item -LiteralPath $desktopLnk -Force
            Write-Host 'Test Desktop LotRadar.lnk removed.'
        }
    } catch { Write-Host ('WARNING: could not restore Desktop shortcut: ' + $_.Exception.Message) -ForegroundColor Red }
    if (-not $KeepSandbox) {
        try { Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction Stop } catch { Write-Host ('NOTE: sandbox not fully removed: ' + $root) -ForegroundColor Yellow }
    }
    Write-Host ''
    Write-Host '=== SUMMARY ===' -ForegroundColor Cyan
    $script:Results | Format-Table Id, Status, Name -AutoSize | Out-String -Width 200 | Write-Host
    $fail = @($script:Results | Where-Object { $_.Status -eq 'FAIL' }).Count
    $pass = @($script:Results | Where-Object { $_.Status -eq 'PASS' }).Count
    $skip = @($script:Results | Where-Object { $_.Status -eq 'SKIP' }).Count
    Write-Host ('PASS=' + $pass + ' FAIL=' + $fail + ' SKIP=' + $skip)
    Write-Host 'MANUAL checks still required (not automatable here): double-click the Desktop shortcut and a launcher failure from Explorer; offline first run then retry; Chrome Reader load-unpacked + pairing; repeat on Windows 10 and 11.'
    [IO.File]::WriteAllText($jsonPath, (@{ results = $script:Results; os = ([string]$PSVersionTable.PSVersion); package = $zipPath } | ConvertTo-Json -Depth 5), $utf8NoBom)
    Write-Host ('Log : ' + $logPath)
    Write-Host ('JSON: ' + $jsonPath)
    Stop-Transcript | Out-Null
}
if ($fail -gt 0) { exit 1 }
exit 0
