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
    -ExtractTo    (OneDrive QA) extract the package and all package test copies under this EXISTING folder
                  instead of the local sandbox. Installed program/data/runtime stay in the local sandbox.
    -OutDir       write the log and JSON to this EXISTING folder instead of next to the ZIP.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$PackageZip,
    [switch]$FullLaunch,
    [switch]$KeepSandbox,
    [string]$ExtractTo = '',
    [string]$OutDir = ''
)
$ErrorActionPreference = 'Stop'
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
$zipPath = (Resolve-Path -LiteralPath $PackageZip).Path
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outFolder = Split-Path -Parent $zipPath
if ($OutDir) { $outFolder = (Resolve-Path -LiteralPath $OutDir).Path }
if ($ExtractTo) { $ExtractTo = (Resolve-Path -LiteralPath $ExtractTo).Path }
$logPath = Join-Path $outFolder ('LotRadar-WindowsTest-' + $stamp + '.log')
$jsonPath = Join-Path $outFolder ('LotRadar-WindowsTest-' + $stamp + '.json')
Start-Transcript -Path $logPath | Out-Null

$script:Results = New-Object System.Collections.ArrayList
$script:Locks = New-Object System.Collections.ArrayList
$script:Listener = $null
$origLocal = $env:LOCALAPPDATA
$origRoam = $env:APPDATA
$sandboxId = [Guid]::NewGuid().ToString('N').Substring(0, 8)
# Use the LONG form of the profile path: $env:TEMP may be an 8.3 short path (MAINOF~1) that does not match what Windows reports for the same folder.
$root = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) ('Temp\LotRadar Test Sandbox ' + $sandboxId)
if ($root.Contains('~')) { throw ('Sandbox path contains an 8.3 short name, refusing: ' + $root) }
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
        $detail = [string](@(& $Body) | Select-Object -Last 1)
        if ($detail -like 'BLOCKED:*') { Add-Result $Id $Name 'SKIP' $detail } else { Add-Result $Id $Name 'PASS' $detail }
    } catch {
        Add-Result $Id $Name 'FAIL' $_.Exception.Message
    }
}
function Skip-Test([string]$Id, [string]$Name, [string]$Why) { Add-Result $Id $Name 'SKIP' $Why }
function Assert-True($Condition, [string]$Message) { if (-not $Condition) { throw $Message } }

# Reparse-tag reader (FindFirstFileW: dwReserved0 holds the tag when the item is a reparse point). Read-only, no hydration.
# Compiled on first use only (built-in .NET Framework compiler), so the default test flow never depends on it.
$script:ReparseTagSource = @'
using System; using System.Runtime.InteropServices;
namespace LotRadarQA {
  public static class ReparseTag {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct WIN32_FIND_DATAW { public uint dwFileAttributes; public uint ftCreationLow, ftCreationHigh, ftAccessLow, ftAccessHigh, ftWriteLow, ftWriteHigh;
      public uint nFileSizeHigh; public uint nFileSizeLow; public uint dwReserved0; public uint dwReserved1;
      [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] public string cFileName; [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 14)] public string cAlternateFileName; }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern IntPtr FindFirstFileW(string name, out WIN32_FIND_DATAW data);
    [DllImport("kernel32.dll")] static extern bool FindClose(IntPtr h);
    public static uint Get(string path) {
      WIN32_FIND_DATAW d; IntPtr h = FindFirstFileW(path.TrimEnd('\\'), out d);
      if (h == new IntPtr(-1)) return 0xFFFFFFFF;
      FindClose(h);
      return ((d.dwFileAttributes & 0x400) != 0) ? d.dwReserved0 : 0;
    }
  }
}
'@
# none | cloud (OneDrive/Files On-Demand placeholder) | symlink | junction | other:0x... | unreadable
function Get-ReparseKind([string]$Path) {
    try {
        if (-not ('LotRadarQA.ReparseTag' -as [type])) { Add-Type -TypeDefinition $script:ReparseTagSource }
        $t = [LotRadarQA.ReparseTag]::Get($Path)
    } catch { return 'unknown' }
    if ($t -eq [uint32]0) { return 'none' }
    if ($t -eq [uint32]4294967295) { return 'unreadable' }
    if ($t -eq [uint32]2684354572) { return 'symlink' }
    if ($t -eq [uint32]2684354563) { return 'junction' }
    if (($t -band [uint32]4294905855) -eq [uint32]2415919130) { return 'cloud' }
    return ('other:0x' + $t.ToString('X8'))
}

function Get-ReparseTagHex([string]$Path) {
    try {
        if (-not ('LotRadarQA.ReparseTag' -as [type])) { Add-Type -TypeDefinition $script:ReparseTagSource }
        return ('0x' + ([LotRadarQA.ReparseTag]::Get($Path)).ToString('X8'))
    } catch { return 'unknown' }
}
# OneDrive QA: wait (bounded) until OneDrive has turned a freshly created folder into a cloud placeholder.
function Wait-CloudTag([string]$Path, [int]$Seconds = 90) {
    $waited = 0
    while ($waited -lt $Seconds -and (Get-ReparseKind $Path) -ne 'cloud') { Start-Sleep -Seconds 3; $waited += 3 }
    return (Get-ReparseKind $Path)
}

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
function New-PkgCopy([string]$Name, [switch]$WaitCloud) {
    $dst = Join-Path $pkgRoot ('pkg ' + $Name)
    Copy-Item -LiteralPath $pkgDir -Destination $dst -Recurse
    # OneDrive QA: make the "cloud parent + nested malicious link" case real, not a race with the sync client.
    if ($ExtractTo -and $WaitCloud) { [void](Wait-CloudTag (Join-Path $dst 'MarketplaceScanner')) }
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
function Invoke-Cmd([string]$CommandLine) {
    $ErrorActionPreference = 'Continue'
    $out = & cmd.exe /d /c $CommandLine 2>&1 | Out-String
    return [pscustomobject]@{ Code = $LASTEXITCODE; Output = $out }
}
function New-Junction([string]$LinkPath, [string]$TargetPath) {
    $r = Invoke-Cmd ('mklink /J "' + $LinkPath + '" "' + $TargetPath + '"')
    if ($r.Code -ne 0) { throw ('mklink /J failed: ' + $r.Output) }
}
# Removes ONLY a verified junction/symlink (never recurses into the target).
function Remove-Junction([string]$LinkPath) {
    if (-not (Test-Path -LiteralPath $LinkPath)) { return }
    $item = Get-Item -LiteralPath $LinkPath -Force
    if ($item.LinkType -eq 'Junction' -or $item.LinkType -eq 'SymbolicLink') { [IO.Directory]::Delete($LinkPath) }
    else { throw ('Refusing to remove a non-link: ' + $LinkPath) }
}
# A harmless outside folder with a sentinel file; returns its path. Must stay byte-identical after any test.
function New-Sentinel([string]$Name) {
    $dir = Join-Path $root ('outside ' + $Name)
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $dir 'sentinel.txt'), ('sentinel ' + $Name), $utf8NoBom)
    return $dir
}
function Assert-SentinelIntact([string]$Dir, [string]$Name) {
    $names = @(Get-ChildItem -LiteralPath $Dir -Recurse -Force | ForEach-Object { $_.Name })
    Assert-True ($names.Count -eq 1 -and $names[0] -eq 'sentinel.txt') ('outside folder was modified (' + $Name + '): ' + ($names -join ', '))
    Assert-True ([IO.File]::ReadAllText((Join-Path $Dir 'sentinel.txt')) -eq ('sentinel ' + $Name)) ('sentinel content changed: ' + $Name)
}
# Copy of the package whose installer has a test-only line injected after a marker line. The production script is never edited.
function New-InjectedPkg([string]$Name, [string]$After, [string]$Inject) {
    $dst = New-PkgCopy $Name
    $f = Join-Path $dst 'Install-LotRadar.ps1'
    $text = [IO.File]::ReadAllText($f)
    $idx = $text.IndexOf($After)
    if ($idx -lt 0) { throw ('injection marker not found: ' + $After) }
    $eol = $text.IndexOf("`n", $idx)
    $text = $text.Insert($eol + 1, $Inject + "`r`n")
    [IO.File]::WriteAllText($f, $text, $utf8NoBom)
    return $dst
}
function Invoke-Installer-Boot {
    $boot = Join-Path $program 'Marketplace Bootstrap.ps1'
    $ErrorActionPreference = 'Continue'
    $out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $boot 2>&1 | Out-String
    return [pscustomobject]@{ Code = $LASTEXITCODE; Output = $out }
}
function Stop-SandboxProcesses {
    # Only processes that belong to THIS sandbox: python server.py under the sandbox path, and the --app window opened for 127.0.0.1:8765.
    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine })
    $targets = @($all | Where-Object {
        (($_.Name -ieq 'python.exe') -and $_.CommandLine -like '*server.py*' -and $_.CommandLine -like ('*' + $local + '*')) -or
        ((($_.Name -ieq 'chrome.exe') -or ($_.Name -ieq 'msedge.exe')) -and $_.CommandLine -like '*--app=http://127.0.0.1:8765*')
    })
    foreach ($t in $targets) {
        Write-Host ('Stopping sandbox process ' + $t.Name + ' pid ' + $t.ProcessId)
        $ErrorActionPreference = 'Continue'
        & taskkill.exe /PID $t.ProcessId /T /F 2>&1 | Out-Null
    }
    if ($targets.Count) { Start-Sleep -Seconds 3 }
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
    $pkgRoot = $root
    if ($ExtractTo) { $pkgRoot = $ExtractTo }
    $pkgDir = Join-Path $pkgRoot 'Test Package'
    Expand-Archive -LiteralPath $zipPath -DestinationPath $pkgDir -Force
    if ($ExtractTo) {
        # OneDrive QA: give the sync client time to process the new folder, then record what it did. INFO only.
        $waited = 0
        while ($waited -lt 90 -and (Get-ReparseKind (Join-Path $pkgDir 'MarketplaceScanner')) -eq 'none') { Start-Sleep -Seconds 3; $waited += 3 }
        $kinds = @{}
        foreach ($it in @(Get-Item -LiteralPath $pkgDir -Force) + @(Get-ChildItem -LiteralPath $pkgDir -Recurse -Force)) {
            $k = ($(if ($it.PSIsContainer) { 'dir' } else { 'file' })) + ':' + (Get-ReparseKind $it.FullName)
            if ($kinds.ContainsKey($k)) { $kinds[$k]++ } else { $kinds[$k] = 1 }
        }
        $kindText = (($kinds.Keys | Sort-Object | ForEach-Object { $_ + '=' + $kinds[$_] }) -join ' ')
        Add-Result 'OD0' 'OneDrive extraction state' 'INFO' ('waited ' + $waited + 's; payload folder reparse=' + (Get-ReparseKind (Join-Path $pkgDir 'MarketplaceScanner')) + ' tag=' + (Get-ReparseTagHex (Join-Path $pkgDir 'MarketplaceScanner')) + '; items by kind: ' + $kindText)
        Invoke-Test 'OD1' 'Package extracted under -ExtractTo while install target, data and runtime stay in the local sandbox' {
            Assert-True ($pkgDir.StartsWith($ExtractTo + '\', [StringComparison]::OrdinalIgnoreCase)) 'package was not extracted under -ExtractTo'
            foreach ($p in @($program, $dataDir, $runtimeDir, $backupRoot)) {
                Assert-True (-not $p.StartsWith($ExtractTo + '\', [StringComparison]::OrdinalIgnoreCase)) ('a runtime location is inside -ExtractTo: ' + $p)
                Assert-True ($p.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) ('a runtime location is outside the local sandbox: ' + $p)
            }
            return 'package in -ExtractTo; program/data/runtime/backups in local sandbox'
        }
    }
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
        $wantTarget = Join-Path $program 'Launch Marketplace Scanner.cmd'
        Assert-True ($lnk.TargetPath -ieq $wantTarget) ('shortcut target wrong: ' + $lnk.TargetPath + ' (expected ' + $wantTarget + ')')
        Assert-True ($lnk.WorkingDirectory -ieq $program) ('shortcut working dir wrong: ' + $lnk.WorkingDirectory + ' (expected ' + $program + ')')
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
        $script:good = Get-State   # new baseline: T12 added a backup folder
        return 'OK'
    }

    # ======================= handoff #3 hardening tests =======================
    # ---- reparse points / junctions (harmless sentinel folders; links are removed with Directory.Delete only)
    Invoke-Test 'R1' 'Junction INSIDE the payload folder is refused; outside sentinel untouched; nothing changes' {
        $sent = New-Sentinel 'r1'
        $pkg = New-PkgCopy 'r1' -WaitCloud
        $script:R1Parent = Get-ReparseKind (Join-Path $pkg 'MarketplaceScanner')
        try {
            $victim = Join-Path $pkg 'MarketplaceScanner\chrome-extension'
            Assert-True (Test-Path -LiteralPath $victim) 'test setup: chrome-extension folder missing in package'
            Remove-Item -LiteralPath $victim -Recurse -Force
            New-Junction $victim $sent
            $r = Invoke-Installer $pkg
        } finally { Remove-Junction (Join-Path $pkg 'MarketplaceScanner\chrome-extension') }
        Assert-True ($r.Code -ne 0) ('installer accepted a junction inside the payload: ' + $r.Output)
        Assert-True ($r.Output -match '(?s)Refusing a link/reparse point inside the package: .*chrome-extension') ('not refused at the junction itself: ' + $r.Output)
        Assert-SentinelIntact $sent 'r1'
        Assert-Unchanged $good 'payload junction'
        return 'payload folder=' + $script:R1Parent + '; refused: ' + ([string]($r.Output -split "`n" | Where-Object { $_ -match 'INSTALL ERROR' } | Select-Object -First 1)).Trim()
    }
    Invoke-Test 'R2' 'Payload ROOT folder is a junction: refused' {
        $sent = New-Sentinel 'r2'
        $pkg = New-PkgCopy 'r2'
        $real = Join-Path $pkg 'MarketplaceScanner'
        $moved = Join-Path $pkgRoot 'r2-real-payload'   # same folder as the package, so the move never crosses drives
        Move-Item -LiteralPath $real -Destination $moved
        try {
            New-Junction $real $moved
            $r = Invoke-Installer $pkg
        } finally { Remove-Junction $real }
        Assert-True ($r.Code -ne 0) ('installer accepted a junction payload root: ' + $r.Output)
        Assert-True ($r.Output -match 'link|reparse') ('unexpected message: ' + $r.Output)
        Assert-SentinelIntact $sent 'r2'
        Assert-Unchanged $good 'payload root junction'
        return 'refused'
    }
    Invoke-Test 'R3' 'File symlink inside payload is refused BECAUSE it is a link (SKIP/BLOCKED if symlinks cannot be created)' {
        # Hardened (PR #5 QA): the symlink points at a file with the ORIGINAL bytes, so the checksum would pass.
        # A refusal can therefore only come from the link/reparse check, never from a coincidental checksum failure.
        $pkg = New-PkgCopy 'r3' -WaitCloud
        $script:R3Parent = Get-ReparseKind (Join-Path $pkg 'MarketplaceScanner')
        $victim = Join-Path $pkg 'MarketplaceScanner\requirements.txt'
        $entry = @($manifest.payload_files | Where-Object { $_.path -eq 'requirements.txt' })
        Assert-True ($entry.Count -eq 1) 'test setup: requirements.txt is not listed in the manifest'
        $outside = Join-Path $root 'outside r3'
        New-Item -ItemType Directory -Path $outside -Force | Out-Null
        $target = Join-Path $outside 'requirements-original.txt'
        Copy-Item -LiteralPath $victim -Destination $target
        $targetSha = Get-Sha $target
        Assert-True ($targetSha -eq [string]$entry[0].sha256) 'test setup: outside copy does not match the manifest hash'
        Remove-Item -LiteralPath $victim -Force
        $mk = Invoke-Cmd ('mklink "' + $victim + '" "' + $target + '"')
        if ($mk.Code -ne 0 -or -not (Test-Path -LiteralPath $victim)) {
            return ('BLOCKED: this account cannot create file symlinks (enable Windows Developer Mode; do NOT run as administrator). mklink said: ' + $mk.Output.Trim())
        }
        try {
            $li = Get-Item -LiteralPath $victim -Force
            Assert-True ($li.LinkType -eq 'SymbolicLink') ('mklink reported success but the item is not a symlink (LinkType=' + $li.LinkType + ')')
            Assert-True ((($li.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)) 'symlink has no ReparsePoint attribute'
            Assert-True ((Get-Sha $victim) -eq [string]$entry[0].sha256) 'reading through the symlink does not give the manifest bytes (fixture invalid)'
            $r = Invoke-Installer $pkg
        } finally {
            $chk = Get-Item -LiteralPath $victim -Force -ErrorAction SilentlyContinue
            if ($chk -and $chk.LinkType -eq 'SymbolicLink') { [IO.File]::Delete($victim) }
        }
        Assert-True ($r.Code -ne 0) ('installer ACCEPTED a file symlink: ' + $r.Output)
        Assert-True ($r.Output -match '(?s)link/reparse point.*requirements\.txt') ('installer failed, but not with a link/reparse refusal of the symlink: ' + $r.Output)
        Assert-True ($r.Output -notmatch 'checksum mismatch') ('refusal mentions a checksum mismatch, so it is not proof of the link check: ' + $r.Output)
        $names = @(Get-ChildItem -LiteralPath $outside -Force | ForEach-Object { $_.Name })
        Assert-True ($names.Count -eq 1 -and $names[0] -eq 'requirements-original.txt') ('outside folder was modified: ' + ($names -join ', '))
        Assert-True ((Get-Sha $target) -eq $targetSha) 'outside symlink target changed'
        Assert-Unchanged $good 'file symlink'
        $line = ([string]($r.Output -split "`n" | Where-Object { $_ -match 'link/reparse' } | Select-Object -First 1)).Trim()
        $line = $line.Replace($root, '<sandbox>')
        return ('payload folder=' + $script:R3Parent + '; symlink created (LinkType=SymbolicLink, ReparsePoint), checksum-valid target; installer exit ' + $r.Code + '; refused: ' + $line + '; outside target unchanged; program/data unchanged')
    }
    Invoke-Test 'R4' 'Programs\MarketplaceScanner (install target) is a junction: refused, target sentinel untouched' {
        $sent = New-Sentinel 'r4'
        $saved = Join-Path $root 'r4-saved-program'
        Move-Item -LiteralPath $program -Destination $saved
        try {
            New-Junction $program $sent
            $r = Invoke-Installer $pkgDir
        } finally { Remove-Junction $program; Move-Item -LiteralPath $saved -Destination $program }
        Assert-True ($r.Code -ne 0) ('installer accepted a junction as the install target: ' + $r.Output)
        Assert-True ($r.Output -match 'link|reparse') ('unexpected message: ' + $r.Output)
        Assert-SentinelIntact $sent 'r4'
        Assert-Unchanged $good 'install-target junction'
        return 'refused'
    }
    Invoke-Test 'R5' 'ProgramBackups is a junction: refused, outside sentinel untouched' {
        $sent = New-Sentinel 'r5'
        $savedBackups = $null
        if (Test-Path -LiteralPath $backupRoot) { $savedBackups = Join-Path $root 'r5-saved-backups'; Move-Item -LiteralPath $backupRoot -Destination $savedBackups }
        try {
            New-Junction $backupRoot $sent
            $r = Invoke-Installer $pkgDir
        } finally {
            Remove-Junction $backupRoot
            if ($savedBackups) { Move-Item -LiteralPath $savedBackups -Destination $backupRoot }
        }
        Assert-True ($r.Code -ne 0) ('installer accepted a junction as the backup root: ' + $r.Output)
        Assert-SentinelIntact $sent 'r5'
        Assert-Unchanged $good 'backup-root junction'
        return 'refused'
    }

    Invoke-Test 'R6' 'Directory symlink INSIDE the payload is refused (SKIP/BLOCKED if symlinks cannot be created)' {
        $sent = New-Sentinel 'r6'
        $pkg = New-PkgCopy 'r6' -WaitCloud
        $parent = Get-ReparseKind (Join-Path $pkg 'MarketplaceScanner')
        $victim = Join-Path $pkg 'MarketplaceScanner\chrome-extension'
        Assert-True (Test-Path -LiteralPath $victim) 'test setup: chrome-extension folder missing in package'
        Remove-Item -LiteralPath $victim -Recurse -Force
        $mk = Invoke-Cmd ('mklink /D "' + $victim + '" "' + $sent + '"')
        if ($mk.Code -ne 0 -or -not (Test-Path -LiteralPath $victim)) {
            return ('BLOCKED: this account cannot create directory symlinks (enable Windows Developer Mode; do NOT run as administrator). mklink said: ' + $mk.Output.Trim())
        }
        try {
            Assert-True ((Get-Item -LiteralPath $victim -Force).LinkType -eq 'SymbolicLink') 'mklink /D did not create a symbolic link'
            $r = Invoke-Installer $pkg
        } finally { Remove-Junction $victim }
        Assert-True ($r.Code -ne 0) ('installer accepted a directory symlink inside the payload: ' + $r.Output)
        Assert-True ($r.Output -match '(?s)Refusing a link/reparse point inside the package: .*chrome-extension') ('not refused at the symlink itself: ' + $r.Output)
        Assert-SentinelIntact $sent 'r6'
        Assert-Unchanged $good 'payload directory symlink'
        return ('payload folder=' + $parent + '; refused')
    }
    if ($ExtractTo) {
        Invoke-Test 'OD2' 'Cloud-tagged DESTINATION (Programs under OneDrive) is still refused; nothing installed there' {
            $odLocal = Join-Path $ExtractTo 'dest-localappdata'
            $odPrograms = Join-Path $odLocal 'Programs'
            New-Item -ItemType Directory -Path $odPrograms -Force | Out-Null
            $kind = Wait-CloudTag $odPrograms
            if ($kind -ne 'cloud') { return ('BLOCKED: OneDrive did not tag the test Programs folder (kind=' + $kind + ')') }
            $env:LOCALAPPDATA = $odLocal
            try { $r = Invoke-Installer $pkgDir } finally { $env:LOCALAPPDATA = $local }
            Assert-True ($r.Code -ne 0) ('installer ACCEPTED a cloud-tagged destination: ' + $r.Output)
            Assert-True ($r.Output -match '(?s)Programs\s+is a link/reparse point\s+\(junction/symlink\)') ('not refused by the destination guard: ' + $r.Output)
            Assert-True (-not (Test-Path -LiteralPath (Join-Path $odPrograms 'MarketplaceScanner'))) 'a program folder was created in the cloud destination'
            Assert-True (@(Get-ChildItem -LiteralPath $odPrograms -Force | Where-Object { $_.Name -like '.MarketplaceScanner-stage-*' }).Count -eq 0) 'a staging folder was created in the cloud destination'
            Assert-Unchanged $good 'cloud destination'
            return ('destination Programs tag=' + (Get-ReparseTagHex $odPrograms) + '; refused by destination guard; nothing created')
        }
        $r1 = @($script:Results | Where-Object { $_.Id -eq 'R1' }) | Select-Object -First 1
        $r3 = @($script:Results | Where-Object { $_.Id -eq 'R3' }) | Select-Object -First 1
        $r6 = @($script:Results | Where-Object { $_.Id -eq 'R6' }) | Select-Object -First 1
        $cloudCases = ('R1(junction) parent=' + $script:R1Parent + ' ' + $r1.Status + '; R3(file symlink) parent=' + $script:R3Parent + ' ' + $r3.Status + '; R6(dir symlink) ' + $r6.Status + ' ' + $r6.Detail.Split(';')[0])
        if ($script:R1Parent -eq 'cloud' -and $r1.Status -eq 'PASS') { Add-Result 'OD3' 'Cloud-tagged parent + nested malicious link is refused' 'PASS' $cloudCases }
        else { Add-Result 'OD3' 'Cloud-tagged parent + nested malicious link is refused' 'SKIP' ('BLOCKED: not exercised with a cloud-tagged parent: ' + $cloudCases) }
    }

    # ---- install/launch interlock
    Invoke-Test 'C1' 'Held marketplace-launch.lock (LotRadar starting/running): installer aborts, nothing changes' {
        $lock = [IO.File]::Open((Join-Path $runtimeDir 'marketplace-launch.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
        [void]$script:Locks.Add($lock)
        try { $r = Invoke-Installer $pkgDir } finally { Release-Locks }
        Assert-True ($r.Code -ne 0) 'installer ran while the launch lock was held'
        Assert-True ($r.Output -match 'running or starting') ('unexpected message: ' + $r.Output)
        Assert-Unchanged $good 'launch lock'
        $again = Invoke-Installer $pkgDir
        Assert-True ($again.Code -eq 0) ('installer cannot run after the lock was released (stranded lock?): ' + $again.Output)
        $script:good = Get-State
        return 'aborted while held; succeeded after release (no stranded lock)'
    }
    Invoke-Test 'C2' 'Installer-first: real bootstrap launched during an install fails safe, install completes, no stranded locks' {
        $pkg = New-InjectedPkg 'c2' "Write-Host 'Existing scanner data was not modified.'" 'Start-Sleep -Seconds 15'
        $env:LOTRADAR_NO_PAUSE = '1'
        $inst = Start-Process -FilePath powershell.exe -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + (Join-Path $pkg 'Install-LotRadar.ps1') + '"')) -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $root 'c2-install.out') -RedirectStandardError (Join-Path $root 'c2-install.err')
        $null = $inst.Handle   # PS 5.1: cache the process handle, otherwise ExitCode can come back empty
        try {
            $deadline = (Get-Date).AddSeconds(60)
            while ((Get-Date) -lt $deadline -and -not (Test-Path -LiteralPath (Join-Path $root 'c2-install.out') -PathType Leaf)) { Start-Sleep -Milliseconds 300 }
            $sawSwap = $false
            while ((Get-Date) -lt $deadline -and -not $inst.HasExited) {
                if (Test-Path -LiteralPath (Join-Path $root 'c2-install.out')) {
                    $txt = ''
                    try {
                        # the installer still has this file open for writing, so open it with shared access
                        $fs = [IO.File]::Open((Join-Path $root 'c2-install.out'), 'Open', 'Read', 'ReadWrite')
                        try { $txt = (New-Object IO.StreamReader $fs).ReadToEnd() } finally { $fs.Dispose() }
                    } catch { }
                    if ($txt -match 'Installed program:') { $sawSwap = $true; break }
                }
                Start-Sleep -Milliseconds 300
            }
            Assert-True $sawSwap 'installer never reached the injected pause (cannot test overlap)'
            $boot = Invoke-Installer-Boot
            Assert-True ($boot.Code -ne 0) ('bootstrap SUCCEEDED while the installer held the launch lock: ' + $boot.Output)
            Assert-True (-not (Test-PortBusy)) 'a server started during the install'
        } finally {
            [void]$inst.WaitForExit(120000)
            $inst.WaitForExit()
        }
        Assert-True ($null -ne $inst.ExitCode -and $inst.ExitCode -eq 0) ('installer exit ' + $inst.ExitCode + ': ' + [IO.File]::ReadAllText((Join-Path $root 'c2-install.out')))
        Assert-True (-not (Test-PortBusy)) 'a server is listening after the test'
        # locks are free again
        foreach ($n in @('lotradar-install.lock', 'marketplace-launch.lock')) {
            $l = [IO.File]::Open((Join-Path $runtimeDir $n), 'OpenOrCreate', 'ReadWrite', 'None'); $l.Dispose()
        }
        Assert-True (((Get-Inventory $dataDir) -join "`n") -eq $dataBefore) 'DATA CHANGED'
        $script:good = Get-State
        return 'bootstrap refused during install (' + ($boot.Output.Trim() -replace '\s+', ' ') + '); install completed; locks free'
    }

    # ---- post-swap rollback (test-only injected copy of the installer; production script untouched)
    Invoke-Test 'P1' 'Post-swap failure with a prior install: previous program restored byte-for-byte, data/runtime unchanged' {
        $before = Get-State
        $runtimeSnap = (Get-Inventory $runtimeDir | Where-Object { $_ -notlike '*.lock*' }) -join "`n"
        $pkg = New-InjectedPkg 'p1' "Write-Host 'Existing scanner data was not modified.'" "throw 'TEST-INJECTED post-swap failure'"
        $r = Invoke-Installer $pkg
        Assert-True ($r.Code -ne 0) ('injected failure did not fail the installer: ' + $r.Output)
        Assert-True ($r.Output -match 'TEST-INJECTED') 'injection did not run (rollback path NOT reached)'
        Assert-True ($r.Output -match 'Original program has been restored') ('no restore message: ' + $r.Output)
        $now = Get-State
        Assert-True ($now.Program -eq $before.Program) 'restored program differs from the pre-install program'
        Assert-True ($now.Data -eq $before.Data) 'DATA CHANGED'
        Assert-True ((($now.Backups) - ($before.Backups)) -eq 1) ('expected exactly 1 new backup folder (Failed-install-*), delta=' + ($now.Backups - $before.Backups))
        $failed = @(Get-ChildItem -LiteralPath $backupRoot -Directory | Where-Object { $_.Name -like 'Failed-install-*' })
        Assert-True ($failed.Count -ge 1) 'Failed-install-* folder missing'
        Assert-True ((Get-StageDirs).Count -eq 0) 'leftover staging folder'
        $rt = (Get-Inventory $runtimeDir | Where-Object { $_ -notlike '*.lock*' }) -join "`n"
        Assert-True ($rt -eq $runtimeSnap) 'runtime folder changed'
        $script:good = Get-State
        return 'rollback reached and verified: program restored, data identical, failed copy kept as Failed-install-*'
    }
    Invoke-Test 'P2' 'Post-swap failure on a FIRST install (no prior program): no program left, failed copy kept, data unchanged' {
        $savedProgram = Join-Path $root 'p2-saved-program'
        Move-Item -LiteralPath $program -Destination $savedProgram
        $beforeBackups = 0
        if (Test-Path -LiteralPath $backupRoot) { $beforeBackups = @(Get-ChildItem -LiteralPath $backupRoot -Directory).Count }
        try {
            $pkg = New-InjectedPkg 'p2' "Write-Host 'Existing scanner data was not modified.'" "throw 'TEST-INJECTED post-swap failure'"
            $r = Invoke-Installer $pkg
            Assert-True ($r.Code -ne 0) 'injected failure did not fail the installer'
            Assert-True ($r.Output -match 'TEST-INJECTED') 'injection did not run (rollback path NOT reached)'
            Assert-True ($r.Output -match 'failed first installation') ('no first-install message: ' + $r.Output)
            Assert-True (-not (Test-Path -LiteralPath $program)) 'a broken program folder was left installed'
            Assert-True (((Get-Inventory $dataDir) -join "`n") -eq $dataBefore) 'DATA CHANGED'
            $after = @(Get-ChildItem -LiteralPath $backupRoot -Directory)
            Assert-True ($after.Count -eq $beforeBackups + 1) 'expected exactly one Failed-install-* folder to be added'
        } finally {
            if (-not (Test-Path -LiteralPath $program)) { Move-Item -LiteralPath $savedProgram -Destination $program }
        }
        Assert-True ((Get-State).Program -eq $good.Program) 'test cleanup did not restore the program'
        $script:good = Get-State
        return 'rollback reached and verified'
    }

    # ---- stale staging folder
    Invoke-Test 'S1' 'A stale .MarketplaceScanner-stage-* folder is NOT deleted and does not block a normal install' {
        $stale = Join-Path $programsDir '.MarketplaceScanner-stage-deadbeefdeadbeefdeadbeefdeadbeef'
        New-Item -ItemType Directory -Path $stale -Force | Out-Null
        [IO.File]::WriteAllText((Join-Path $stale 'leftover.txt'), 'stale', $utf8NoBom)
        try {
            $r = Invoke-Installer $pkgDir
            Assert-True ($r.Code -eq 0) ('install blocked by a stale stage folder: ' + $r.Output)
            Assert-True (Test-Path -LiteralPath (Join-Path $stale 'leftover.txt')) 'installer deleted a stale stage folder it did not create'
        } finally { Remove-Item -LiteralPath $stale -Recurse -Force -ErrorAction SilentlyContinue }
        $script:good = Get-State
        return 'install OK; stale folder left in place (documented manual cleanup)'
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
        Write-Host 'F0/F1: first launch provisions Python packages and Playwright Chromium inside the sandbox; this can take several minutes. Do not close this window.' -ForegroundColor Yellow
        Invoke-Test 'OFF1' 'Offline first run (nothing provisioned yet): clear failure, data untouched, no server; F0 then proves the retry resumes' {
            $dbPath = Join-Path $dataDir 'marketplace.sqlite3'
            $before = Get-Sha $dbPath
            $saved = @{ HTTP_PROXY = $env:HTTP_PROXY; HTTPS_PROXY = $env:HTTPS_PROXY; ALL_PROXY = $env:ALL_PROXY; NO_PROXY = $env:NO_PROXY }
            try {
                $env:HTTP_PROXY = 'http://127.0.0.1:9'; $env:HTTPS_PROXY = 'http://127.0.0.1:9'; $env:ALL_PROXY = 'http://127.0.0.1:9'; $env:NO_PROXY = '127.0.0.1,localhost'
                $r = Invoke-CmdScript (Join-Path $program 'Launch Marketplace Scanner.cmd')
            } finally {
                foreach ($k in $saved.Keys) { if ($null -eq $saved[$k]) { Remove-Item ('Env:\' + $k) -ErrorAction SilentlyContinue } else { Set-Item ('Env:\' + $k) $saved[$k] } }
            }
            Assert-True ($r.Code -ne 0) ('launcher reported SUCCESS while offline with nothing provisioned: ' + $r.Output)
            Assert-True (-not (Test-PortBusy)) 'a server is listening after the offline failure'
            Assert-True ((Get-Sha $dbPath) -eq $before) 'DATABASE FILE WAS MODIFIED'
            Assert-True ($r.Output -notmatch 'file is not a database') 'bootstrap reached the database although offline (was it already provisioned on this machine?)'
            $tail = (($r.Output -split "`n" | Where-Object { $_.Trim() } | Select-Object -Last 3) -join ' | ')
            return ('exit ' + $r.Code + '; no server; data unchanged; message: ' + $tail)
        }
        Invoke-Test 'F0' 'Real bootstrap refuses a non-SQLite database file and does not modify it' {
            $dbPath = Join-Path $dataDir 'marketplace.sqlite3'
            Assert-True (Test-Path -LiteralPath $dbPath) 'test setup: fixture database missing'
            $before = Get-Sha $dbPath
            $r = Invoke-CmdScript (Join-Path $program 'Launch Marketplace Scanner.cmd')
            Assert-True ($r.Code -ne 0) ('launcher reported success with a corrupt database: ' + $r.Output)
            Assert-True ($r.Output -match 'file is not a database') ('unexpected output (provisioning problem?): ' + $r.Output)
            Assert-True ((Get-Sha $dbPath) -eq $before) 'DATABASE FILE WAS MODIFIED'
            Assert-True (-not (Test-PortBusy)) 'a server is still listening after the failed start'
            return 'exit ' + $r.Code + '; database bytes unchanged; no server left running'
        }
        # F1+ need a clean data folder: set the random-byte fixture aside (it is checked again in F3).
        $fixture = Join-Path $userRoot 'data-fixture'
        Move-Item -LiteralPath $dataDir -Destination $fixture
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
            $ids = @($procs | ForEach-Object { $_.ProcessId })
            $roots = @($procs | Where-Object { $ids -notcontains $_.ParentProcessId })
            $tree = (($procs | ForEach-Object { [string]$_.ProcessId + '<-' + [string]$_.ParentProcessId }) -join ', ')
            Assert-True ($roots.Count -eq 1) ('expected exactly 1 sandbox server process tree, found ' + $roots.Count + ' (' + $tree + ')')
            $listeners = @(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)
            Assert-True ($listeners.Count -ge 1) 'nothing is listening on 8765'
            $owners = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
            Assert-True ($owners.Count -eq 1) ('more than one process listens on 8765: ' + ($owners -join ', '))
            return ('1 server process tree (' + $procs.Count + ' python.exe processes: ' + $tree + '), single listener pid ' + $owners[0])
        }
        Invoke-Test 'F3' 'Real bootstrap: sandbox data folder created, installed program unchanged, no real data touched' {
            Assert-True (Test-Path -LiteralPath $dataDir) 'data dir missing'
            $origRows = @($dataBefore -split "`n")
            $nowRows = @(Get-Inventory $fixture)
            $lost = @($origRows | Where-Object { $nowRows -notcontains $_ })
            Assert-True ($lost.Count -eq 0) ('original fixture files missing or MODIFIED: ' + (($lost | ForEach-Object { ($_ -split '\|')[0] }) -join ', '))
            $script:fixtureAdded = @($nowRows | Where-Object { $origRows -notcontains $_ } | ForEach-Object { ($_ -split '\|')[0] })
            foreach ($item in $manifest.payload_files) {
                Assert-True ((Get-Sha (Join-Path $program $item.path.Replace('/', '\'))) -eq $item.sha256) ('program file changed by launch: ' + $item.path)
            }
            return ('OK; original fixture files byte-identical; files the server added to the data folder during the refused start: ' + $(if ($script:fixtureAdded.Count) { $script:fixtureAdded -join ', ' } else { '(none)' }))
        }
        # stop the sandbox server
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*server.py*' -and $_.CommandLine -like ('*' + $local + '*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        if ($script:launchProc) { [void]$script:launchProc.WaitForExit(60000) }
        Invoke-Test 'F4' 'Already provisioned + temporary internet outage: LotRadar still starts healthy (one server tree)' {
            $saved = @{ HTTP_PROXY = $env:HTTP_PROXY; HTTPS_PROXY = $env:HTTPS_PROXY; ALL_PROXY = $env:ALL_PROXY; NO_PROXY = $env:NO_PROXY }
            $health = $null
            try {
                $env:HTTP_PROXY = 'http://127.0.0.1:9'; $env:HTTPS_PROXY = 'http://127.0.0.1:9'; $env:ALL_PROXY = 'http://127.0.0.1:9'; $env:NO_PROXY = '127.0.0.1,localhost'
                $log4 = Join-Path $root 'launch4.log'
                $runner = Join-Path $root 'launch4.cmd'
                [IO.File]::WriteAllText($runner, ('@echo off' + "`r`n" + 'call "' + (Join-Path $program 'Launch Marketplace Scanner.cmd') + '" > "' + $log4 + '" 2>&1' + "`r`n" + 'exit /b %errorlevel%' + "`r`n"), [Text.Encoding]::ASCII)
                $script:launchProc = Start-Process -FilePath cmd.exe -ArgumentList '/d', '/c', ('"' + $runner + '"') -PassThru -WindowStyle Minimized
                $deadline = (Get-Date).AddMinutes(5)
                while ((Get-Date) -lt $deadline -and -not $script:launchProc.HasExited) {
                    try { $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 3; break } catch { Start-Sleep -Seconds 3 }
                }
                if (-not $health) {
                    $tail = ''
                    if (Test-Path -LiteralPath $log4) { $tail = (Get-Content -LiteralPath $log4 -Tail 25) -join "`n" }
                    throw ('no health response while offline; launcher exited=' + $script:launchProc.HasExited + "`n" + $tail)
                }
            } finally {
                foreach ($k in $saved.Keys) { if ($null -eq $saved[$k]) { Remove-Item ('Env:\' + $k) -ErrorAction SilentlyContinue } else { Set-Item ('Env:\' + $k) $saved[$k] } }
            }
            Assert-True ($health.ok -eq $true -and $health.local_only -eq $true -and $health.service -eq 'Marketplace Scanner') ('unexpected health payload: ' + ($health | ConvertTo-Json -Compress))
            $procs = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*server.py*' -and $_.CommandLine -like ('*' + $local + '*') })
            $ids = @($procs | ForEach-Object { $_.ProcessId })
            $roots = @($procs | Where-Object { $ids -notcontains $_.ParentProcessId })
            Assert-True ($roots.Count -eq 1) ('expected 1 server process tree, found ' + $roots.Count)
            return 'healthy while offline; 1 server tree'
        }
        # stop the sandbox server again
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
            if ((Get-Sha $desktopLnk) -ne (Get-Sha $desktopBackup)) { throw 'restored shortcut does not match the backup' }
            Write-Host 'Original Desktop LotRadar.lnk restored (verified).'
        } elseif (Test-Path -LiteralPath $desktopLnk) {
            Remove-Item -LiteralPath $desktopLnk -Force
            Write-Host 'Test Desktop LotRadar.lnk removed.'
        }
    } catch {
        Write-Host ('WARNING: could not restore Desktop shortcut: ' + $_.Exception.Message) -ForegroundColor Red
        if ($desktopHadLnk) {
            # Never delete the only backup copy: keep the sandbox so the original shortcut can be copied back by hand.
            $KeepSandbox = $true
            Write-Host ('Your original shortcut backup is kept here: ' + $desktopBackup) -ForegroundColor Red
            Add-Result 'SC1' 'Desktop shortcut restored' 'FAIL' 'restore failed; backup kept in the sandbox folder'
        }
    }
    try { Stop-SandboxProcesses } catch { Write-Host ('NOTE: could not stop sandbox processes: ' + $_.Exception.Message) -ForegroundColor Yellow }
    if (-not $KeepSandbox) {
        for ($try = 1; $try -le 3; $try++) {
            try { Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction Stop; break } catch {
                if ($try -eq 3) { Write-Host ('NOTE: sandbox not fully removed (safe to delete by hand): ' + $root) -ForegroundColor Yellow } else { Start-Sleep -Seconds 4 }
            }
        }
    }
    Write-Host ''
    Write-Host '=== SUMMARY ===' -ForegroundColor Cyan
    $script:Results | Format-Table Id, Status, Name -AutoSize | Out-String -Width 200 | Write-Host
    $fail = @($script:Results | Where-Object { $_.Status -eq 'FAIL' }).Count
    $pass = @($script:Results | Where-Object { $_.Status -eq 'PASS' }).Count
    $skip = @($script:Results | Where-Object { $_.Status -eq 'SKIP' }).Count
    Write-Host ('PASS=' + $pass + ' FAIL=' + $fail + ' SKIP=' + $skip)
    Write-Host 'MANUAL checks still required (see docs/MANUAL_ACCEPTANCE.md): Explorer double-click of Installer.cmd/shortcuts; Chrome Reader load-unpacked + pairing; read-only photo export; repeat on Windows 10 AND Windows 11.'
    [IO.File]::WriteAllText($jsonPath, (@{ results = $script:Results; os = ([string]$PSVersionTable.PSVersion); package = $zipPath } | ConvertTo-Json -Depth 5), $utf8NoBom)
    Write-Host ('Log : ' + $logPath)
    Write-Host ('JSON: ' + $jsonPath)
    Stop-Transcript | Out-Null
}
if ($fail -gt 0) { exit 1 }
exit 0
