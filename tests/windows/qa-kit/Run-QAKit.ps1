<#
.SYNOPSIS
  LotRadar Windows QA kit runner (TEST-ONLY). Started by RUN_WINDOWS11_TESTS.cmd / RUN_FULL_LAUNCH_TESTS.cmd.

.DESCRIPTION
  Preflight -> run tools\Test-LotRadarInstaller.ps1 on the bundled DEVELOPMENT installer -> write sanitized
  results to RESULTS\. Uses only Windows PowerShell 5.1. Never elevates, never installs anything system-wide,
  never touches %LOCALAPPDATA%\MarketplaceScanner (the test harness uses its own sandbox folder).

  Exit codes: 0 all tests passed (SKIPs allowed) | 1 a test failed | 2 kit not extracted / wrong place
  3 running as administrator | 4 kit files missing or altered | 5 port 8765 busy | 6 Desktop shortcut
  could not be backed up | 7 harness parse error | 8 wrong PowerShell | 9 cancelled | 10 shortcut not restored
  11 a leftover of an earlier interrupted run needs your attention (nothing was run)

  -OneDrive (RUN_ONEDRIVE_TESTS.cmd only): after the same preflight, runs tools\LotRadarQA.OneDrive.ps1
  (local control run, read-only LOCAL_PHOTO_STORAGE check, consented OneDrive extraction run). Results go to a
  LOCAL folder under %LOCALAPPDATA%\LotRadar QA Results, never into OneDrive.
#>
[CmdletBinding()]
param([switch]$FullLaunch, [switch]$OneDrive, [switch]$CleanupSelfTest, [switch]$UiPreview, [switch]$ManualUI, [switch]$Yes)
$ErrorActionPreference = 'Stop'
$kit = Split-Path -Parent $PSScriptRoot
$resultsDir = Join-Path $kit 'RESULTS'
if ($OneDrive) { $resultsDir = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) ('LotRadar QA Results\OneDrive-' + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
if ($CleanupSelfTest) { $resultsDir = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) ('LotRadar QA Results\Cleanup-' + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
if ($UiPreview) { $resultsDir = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) ('LotRadar QA Results\UiPreview-' + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
if ($ManualUI) { $resultsDir = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) ('LotRadar QA Results\ManualUI-' + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
$psExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$script:Redact = @()

function Say([string]$Text, [string]$Color = 'Gray') { Write-Host $Text -ForegroundColor $Color }
function Stop-Kit([string]$Text, [int]$Code) {
    Say ''
    Say ('STOPPED: ' + $Text) 'Red'
    Say 'No tests were run and nothing on this PC was changed.' 'Yellow'
    exit $Code
}
function Get-Sha([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Protect-Text([string]$Text) {
    # Remove the Windows user name, profile path and computer name from shared evidence.
    if ($null -eq $Text) { return '' }
    $out = $Text
    foreach ($p in @($script:Redact)) {
        $find = [string]$p[0]
        if ($find.Length -ge 3) {
            # also the JSON-escaped form (backslashes doubled)
            $out = [regex]::Replace($out, [regex]::Escape($find.Replace('\', '\\')), [string]$p[1], [Text.RegularExpressions.RegexOptions]::IgnoreCase)
            $out = [regex]::Replace($out, [regex]::Escape($find), [string]$p[1], [Text.RegularExpressions.RegexOptions]::IgnoreCase)
        }
    }
    $short = ''
    try { $short = (New-Object -ComObject Scripting.FileSystemObject).GetFolder($env:USERPROFILE).ShortPath } catch { $short = '' }
    $pairs = @(
        @($env:USERPROFILE, '%USERPROFILE%'),
        @($short, '%USERPROFILE%'),
        @($env:COMPUTERNAME, '<computer>'),
        @($env:USERNAME, '<user>')
    )
    foreach ($p in $pairs) {
        $find = [string]$p[0]
        if ($find.Length -ge 3) {
            $out = [regex]::Replace($out, [regex]::Escape($find.Replace('\', '\\')), [string]$p[1], [Text.RegularExpressions.RegexOptions]::IgnoreCase)
            $out = [regex]::Replace($out, [regex]::Escape($find), [string]$p[1], [Text.RegularExpressions.RegexOptions]::IgnoreCase)
        }
    }
    return $out
}

# Consent. The Owner chose double-click consent: the separately labeled launchers pass -Yes, so after the disclosure
# the run starts by itself after a 10-second countdown (closing the window cancels). Without -Yes a typed YES is required.
function Confirm-Start([string]$What) {
    if ($Yes) {
        Say ('Starting the ' + $What + ' in 10 seconds. To cancel, close this window now.') 'Yellow'
        for ($i = 10; $i -ge 1; $i--) { Write-Host ('  ' + $i + '...') -NoNewline; Start-Sleep -Seconds 1 }
        Write-Host ''
        return $true
    }
    return ((Read-Host ('Type YES to start the ' + $What)) -eq 'YES')
}

function Test-ShortcutRestored {
    # Independent of the harness: compare the Desktop shortcut with the kit's own verified backup.
    if ($hadShortcut) {
        if ((Test-Path -LiteralPath $desktopLnk) -and ((Get-Sha $desktopLnk) -eq $shortcutSha)) { return 'restored, byte-identical to the backup' }
        Copy-Item -LiteralPath $shortcutBackup -Destination $desktopLnk -Force
        if ((Get-Sha $desktopLnk) -eq $shortcutSha) { return 'harness did not restore it; the kit restored it from its backup' }
        return 'NOT RESTORED - copy shortcut-backup\LotRadar.lnk from the results folder to your Desktop by hand'
    }
    if (Test-Path -LiteralPath $desktopLnk) {
        $target = (New-Object -ComObject WScript.Shell).CreateShortcut($desktopLnk).TargetPath
        if ($target -like '*LotRadar Test Sandbox*') {
            Remove-Item -LiteralPath $desktopLnk -Force
            return 'leftover TEST shortcut found and removed by the kit'
        }
        return 'a LotRadar.lnk now exists that does not point to the test sandbox; left untouched'
    }
    return 'no shortcut before; none left behind'
}

Say '=== LotRadar Windows QA test kit ===' 'Cyan'
if (@(@($FullLaunch, $OneDrive, $CleanupSelfTest, $UiPreview, $ManualUI) | Where-Object { $_ }).Count -gt 1) { Stop-Kit 'Only one optional test mode at a time. Run them separately.' 9 }

# ---- 1. kit must be extracted to a normal folder (not opened inside the ZIP viewer)
if ($kit -like '*\AppData\Local\Temp\*' -or $kit -like '*\Temp1_*') {
    Stop-Kit 'The kit is being run from inside the ZIP file. Right-click the ZIP, choose "Extract All...", then run RUN_WINDOWS11_TESTS.cmd from the extracted folder.' 2
}

# ---- 2. Windows PowerShell 5.1
if ($PSVersionTable.PSVersion.Major -ne 5) { Stop-Kit ('This must run in Windows PowerShell 5.1, found ' + $PSVersionTable.PSVersion) 8 }

# ---- 3. OS and privilege
$os = Get-CimInstance Win32_OperatingSystem
$build = [int]$os.BuildNumber
$isWin11 = ($build -ge 22000)
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Say ('Windows      : ' + $os.Caption + ' (version ' + $os.Version + ', build ' + $os.BuildNumber + ')')
Say ('PowerShell   : ' + $PSVersionTable.PSVersion)
Say ('Administrator: ' + $isAdmin)
if ($isAdmin) {
    Stop-Kit 'This window is running as administrator. Close it and double-click RUN_WINDOWS11_TESTS.cmd normally (do NOT use "Run as administrator").' 3
}
if (-not $isWin11) {
    Say ('NOTE: this PC reports build ' + $build + ', which is not Windows 11. Results will be recorded as evidence for this Windows version, not Windows 11.') 'Yellow'
}
if ($env:OneDrive -and $kit.StartsWith($env:OneDrive, [StringComparison]::OrdinalIgnoreCase)) {
    Say 'NOTE: the kit is inside a OneDrive folder. That is allowed; it will be noted in the results.' 'Yellow'
}

# ---- 4. kit integrity and provenance
$sumsPath = Join-Path $kit 'KIT_SHA256SUMS.txt'
$infoPath = Join-Path $kit 'KIT_INFO.json'
if (-not (Test-Path -LiteralPath $sumsPath) -or -not (Test-Path -LiteralPath $infoPath)) { Stop-Kit 'KIT_SHA256SUMS.txt or KIT_INFO.json is missing. Re-extract the kit ZIP.' 4 }
$checked = 0
foreach ($line in (Get-Content -LiteralPath $sumsPath -Encoding ASCII)) {
    if (-not $line.Trim()) { continue }
    $parts = $line -split '  ', 2
    if ($parts.Count -ne 2) { Stop-Kit ('Bad line in KIT_SHA256SUMS.txt: ' + $line) 4 }
    $rel = $parts[1].Trim()
    if ($rel.Contains('..') -or [IO.Path]::IsPathRooted($rel)) { Stop-Kit ('Unsafe path in KIT_SHA256SUMS.txt: ' + $rel) 4 }
    $file = Join-Path $kit ($rel.Replace('/', '\'))
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { Stop-Kit ('Kit file missing: ' + $rel) 4 }
    if ((Get-Sha $file) -ne $parts[0].Trim().ToLowerInvariant()) { Stop-Kit ('Kit file was changed or damaged: ' + $rel) 4 }
    $checked++
}
$info = Get-Content -LiteralPath $infoPath -Raw -Encoding UTF8 | ConvertFrom-Json
$pkgZip = Join-Path $kit ('package\' + $info.package_file)
$harness = Join-Path $PSScriptRoot 'Test-LotRadarInstaller.ps1'
if (-not (Test-Path -LiteralPath $pkgZip)) { Stop-Kit ('Installer package missing: ' + $info.package_file) 4 }
if ((Get-Sha $pkgZip) -ne [string]$info.package_sha256) { Stop-Kit 'Installer package checksum does not match KIT_INFO.json.' 4 }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($pkgZip)
try {
    $entry = $zip.GetEntry('Install-Manifest.json')
    if (-not $entry) { Stop-Kit 'Install-Manifest.json not found inside the installer package.' 4 }
    $reader = New-Object IO.StreamReader($entry.Open())
    try { $manifest = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
} finally { $zip.Dispose() }
if ([string]$manifest.source_commit -ne [string]$info.source_commit) { Stop-Kit ('Package commit ' + $manifest.source_commit + ' does not match the kit commit ' + $info.source_commit) 4 }
if ([string]$manifest.build_type -ne [string]$info.build_type) { Stop-Kit ('Package build type ' + $manifest.build_type + ' does not match the kit (' + $info.build_type + ')') 4 }
Say ('Kit files    : ' + $checked + ' checksums OK')
Say ('Package      : ' + $info.package_file + ' (' + $manifest.build_type + ', commit ' + $manifest.source_commit + ')')

# ---- 5. nothing may listen on 127.0.0.1:8765 (LotRadar must be closed)
$client = New-Object System.Net.Sockets.TcpClient
$busy = $false
try {
    $probe = $client.BeginConnect([Net.IPAddress]::Loopback, 8765, $null, $null)
    $busy = ($probe.AsyncWaitHandle.WaitOne(500) -and $client.Connected)
} catch { $busy = $false } finally { $client.Dispose() }
if ($busy) { Stop-Kit 'Something is using 127.0.0.1:8765 (probably LotRadar). Close LotRadar and its black server window, then run the kit again.' 5 }

# ---- 6. Desktop shortcut: the harness temporarily writes Desktop\LotRadar.lnk; keep our own verified copy too
New-Item -ItemType Directory -Path $resultsDir -Force | Out-Null
$desktop = [Environment]::GetFolderPath('Desktop')
$desktopLnk = Join-Path $desktop 'LotRadar.lnk'

# ---- 6a. Leftovers of an earlier, INTERRUPTED kit run (a closed window skips that run's own cleanup).
# tools\LotRadarQA.Cleanup.ps1: a folder is offered for deletion only if it is PROVEN kit-created (token marker +
# local ledger + exact canonical location + no links inside), one folder at a time, and only after you type D.
# Anything else is reported and left untouched. A test shortcut is replaced only by a verified standard shortcut.
$localAppData = [Environment]::GetFolderPath('LocalApplicationData')
$qaHome = Join-Path $localAppData 'LotRadar QA Results'
$otherRun = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.ProcessId -ne $PID -and ($_.CommandLine -like '*Test-LotRadarInstaller.ps1*' -or $_.CommandLine -like '*Run-QAKit.ps1*') }).Count -gt 0
if ($otherRun) { Stop-Kit 'Another LotRadar test run is still running (or its window is still open). Let it finish or close it, then run the kit again.' 5 }
$odParents = @()
foreach ($v in @($env:OneDrive, $env:OneDriveConsumer, $env:OneDriveCommercial)) {
    if ($v -and (Test-Path -LiteralPath $v) -and -not (@($odParents) | Where-Object { $_ -eq $v })) { $odParents += $v }
}
foreach ($mod in @('LotRadarQA.Cleanup.ps1', 'LotRadarQA.CleanupSelfTest.ps1')) {
    $tokens = $null; $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $mod), [ref]$tokens, [ref]$errors)
    if (@($errors).Count -gt 0) { Stop-Kit ('Kit script ' + $mod + ' has parse errors: ' + ((@($errors) | ForEach-Object { 'line ' + $_.Extent.StartLineNumber + ': ' + $_.Message }) -join '; ')) 7 }
}
if ($CleanupSelfTest) {
    # Synthetic fixtures only; the real leftover repair below is NOT run in this mode.
    . (Join-Path $PSScriptRoot 'LotRadarQA.Cleanup.ps1')
    $script:CleanupExit = 1
    . (Join-Path $PSScriptRoot 'LotRadarQA.CleanupSelfTest.ps1')
    exit $script:CleanupExit   # never fall through into the normal test flow
}
try {
    . (Join-Path $PSScriptRoot 'LotRadarQA.Cleanup.ps1')
    $repair = Invoke-QALeftoverRepair -TempParent (Join-Path $localAppData 'Temp') -OneDriveParents $odParents -LedgerDir (Join-Path $qaHome 'owned') `
        -DesktopLnk $desktopLnk -OriginalStore (Join-Path $qaHome 'shortcut-original\LotRadar.lnk') `
        -StandardTarget (Join-Path $localAppData 'Programs\MarketplaceScanner\Launch Marketplace Scanner.cmd') `
        -EvidenceDir (Join-Path $resultsDir 'leftover-repair') -Ask { param($q) Read-QAAnswer $q }
} catch { Stop-Kit ('Could not check for leftovers of an earlier test run: ' + $_.Exception.Message) 11 }
$script:LeftoverReport = @($repair.Lines)
if ($repair.Stop) {
    foreach ($l in $script:LeftoverReport) { Say ('Earlier interrupted run: ' + $l) 'Yellow' }
    Stop-Kit $repair.Stop 11
}
if ($script:LeftoverReport.Count -eq 0) { $script:LeftoverReport = @('none') }
foreach ($l in $script:LeftoverReport) { Say ('Earlier interrupted run: ' + $l) 'Yellow' }
$shortcutBackup = Join-Path $resultsDir 'shortcut-backup\LotRadar.lnk'
$hadShortcut = Test-Path -LiteralPath $desktopLnk
$shortcutSha = ''
if ($hadShortcut) {
    try {
        New-Item -ItemType Directory -Path (Split-Path -Parent $shortcutBackup) -Force | Out-Null
        Copy-Item -LiteralPath $desktopLnk -Destination $shortcutBackup -Force
        $shortcutSha = Get-Sha $desktopLnk
        if ((Get-Sha $shortcutBackup) -ne $shortcutSha) { throw 'backup copy differs' }
    } catch { Stop-Kit ('Could not safely back up your Desktop LotRadar shortcut: ' + $_.Exception.Message) 6 }
    Say 'Desktop shortcut: an existing LotRadar.lnk was backed up and will be restored after the tests.' 'Yellow'
} else {
    Say 'Desktop shortcut: none exists now. A test shortcut appears briefly during the tests and is removed afterwards.' 'Yellow'
}

# ---- 7. the bundled harness must parse cleanly in this PowerShell
$toParse = @($harness)
if ($OneDrive) { $toParse += (Join-Path $PSScriptRoot 'LotRadarQA.OneDrive.ps1') }
if ($UiPreview -or $ManualUI) { $toParse += (Join-Path $PSScriptRoot 'LotRadarQA.ManualUI.ps1') }
foreach ($scriptFile in $toParse) {
    $tokens = $null; $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($scriptFile, [ref]$tokens, [ref]$errors)
    if (@($errors).Count -gt 0) { Stop-Kit ('Test script ' + (Split-Path -Leaf $scriptFile) + ' has parse errors: ' + ((@($errors) | ForEach-Object { 'line ' + $_.Extent.StartLineNumber + ': ' + $_.Message }) -join '; ')) 7 }
}

# ---- OneDrive mode: separate, consented flow (it writes its own summary and exits)
if ($OneDrive) {
    $script:OneDriveExit = 1   # stays 1 unless the OneDrive module finishes and reports success
    . (Join-Path $PSScriptRoot 'LotRadarQA.OneDrive.ps1')
    exit $script:OneDriveExit  # never fall through into the normal test flow
}

# ---- Manual UI modes (Stage A preview / Stage B guided real start in a sandbox): own flow, own summary, then exit
if ($UiPreview -or $ManualUI) {
    $script:ManualExit = 1
    . (Join-Path $PSScriptRoot 'LotRadarQA.ManualUI.ps1')
    exit $script:ManualExit   # never fall through into the normal test flow
}

# ---- 8. optional full launch needs explicit consent
if ($FullLaunch) {
    Say ''
    Say 'FULL LAUNCH TEST: this downloads Python packages and the Playwright Chromium browser (several hundred MB)' 'Yellow'
    Say 'into a TEMPORARY test folder, starts LotRadar there, opens its window, then stops and deletes it.' 'Yellow'
    Say 'It needs internet and can take 10-30 minutes. Your real LotRadar data is not used.' 'Yellow'
    $hasPy = $false
    foreach ($cand in @('py.exe', 'python.exe')) {
        # Ignore the Microsoft Store "python.exe" alias stub in WindowsApps; it is not a real Python.
        $found = @(Get-Command $cand -CommandType Application -ErrorAction SilentlyContinue | Where-Object { $_.Source -notlike '*\WindowsApps\*' })
        if ($found.Count -gt 0) { $hasPy = $true }
    }
    if (-not $hasPy) {
        Say 'IMPORTANT: Python was not found on this PC. LotRadar''s own startup script will install Python 3.13' 'Red'
        Say 'for your Windows user with Windows Package Manager (WinGet). Python STAYS INSTALLED after the test' 'Red'
        Say '(the same thing a real LotRadar install does). It can be removed later in Settings > Apps.' 'Red'
    }
    if (-not (Confirm-Start 'full launch test')) { Say 'Cancelled. Nothing was run.'; exit 9 }
}

# ---- 9. run the harness (it writes its log + JSON next to the package ZIP)
Say ''
Say 'Running the tests now. Please do not close this window. This usually takes 3-10 minutes.' 'Cyan'
$started = Get-Date
$harnessArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $harness, '-PackageZip', $pkgZip)
if ($FullLaunch) { $harnessArgs += '-FullLaunch' }
& $psExe @harnessArgs
$harnessExit = $LASTEXITCODE

# ---- 10. shortcut check (independent of the harness)
$shortcutStatus = Test-ShortcutRestored

# ---- 11. sanitized copies of the evidence
$log = Get-ChildItem -LiteralPath (Split-Path -Parent $pkgZip) -Filter 'LotRadar-WindowsTest-*.log' | Where-Object { $_.LastWriteTime -ge $started } | Sort-Object LastWriteTime | Select-Object -Last 1
$json = Get-ChildItem -LiteralPath (Split-Path -Parent $pkgZip) -Filter 'LotRadar-WindowsTest-*.json' | Where-Object { $_.LastWriteTime -ge $started } | Sort-Object LastWriteTime | Select-Object -Last 1
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
$counts = 'unknown'
$r3 = 'not reported'
$t00 = ''
if ($log) { [IO.File]::WriteAllText((Join-Path $resultsDir ('SANITIZED-' + $log.Name)), (Protect-Text ([IO.File]::ReadAllText($log.FullName))), $utf8NoBom) }
# screenshots of the startup window (only the window itself, synthetic test data)
$shots = @(Get-ChildItem -LiteralPath (Split-Path -Parent $pkgZip) -Filter 'startup-window-*.png' -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -ge $started })
foreach ($s in $shots) { Copy-Item -LiteralPath $s.FullName -Destination (Join-Path $resultsDir $s.Name) -Force }
if ($json) {
    $jsonText = Protect-Text ([IO.File]::ReadAllText($json.FullName))
    [IO.File]::WriteAllText((Join-Path $resultsDir ('SANITIZED-' + $json.Name)), $jsonText, $utf8NoBom)
    try {
        $rows = @(($jsonText | ConvertFrom-Json).results)
        $counts = ('PASS=' + @($rows | Where-Object { $_.Status -eq 'PASS' }).Count + ' FAIL=' + @($rows | Where-Object { $_.Status -eq 'FAIL' }).Count + ' SKIP=' + @($rows | Where-Object { $_.Status -eq 'SKIP' }).Count)
        $r3row = @($rows | Where-Object { $_.Id -eq 'R3' }) | Select-Object -First 1
        if ($r3row) { $r3 = ([string]$r3row.Status + ' - ' + [string]$r3row.Detail) }
        $t00row = @($rows | Where-Object { $_.Id -eq 'T00' }) | Select-Object -First 1
        if ($t00row) { $t00 = [string]$t00row.Detail }
    } catch { $counts = 'could not read results JSON: ' + $_.Exception.Message }
}
$summary = @(
    'LotRadar Windows QA kit summary',
    ('Kit commit      : ' + $info.source_commit),
    ('Package         : ' + $info.package_file + ' sha256=' + $info.package_sha256 + ' build_type=' + $info.build_type),
    ('Windows         : ' + $os.Caption + ' version ' + $os.Version + ' build ' + $os.BuildNumber + ' (Windows 11: ' + $isWin11 + ')'),
    ('PowerShell      : ' + $PSVersionTable.PSVersion + '; administrator: ' + $isAdmin),
    ('Full launch     : ' + [bool]$FullLaunch),
    ('Started         : ' + $started.ToString('yyyy-MM-dd HH:mm:ss zzz')),
    ('Harness exit    : ' + $harnessExit),
    ('Results         : ' + $counts),
    ('R3 symlink test : ' + $r3),
    ('Environment     : ' + $t00),
    ('Desktop shortcut: ' + $shortcutStatus),
    ('Leftover repair : ' + ($script:LeftoverReport -join '; ')),
    ('Screenshots     : ' + $(if ($shots.Count) { ($shots | ForEach-Object { $_.Name }) -join ', ' } else { 'none' }))
)
$summaryText = Protect-Text ($summary -join "`r`n")
[IO.File]::WriteAllText((Join-Path $resultsDir 'SUMMARY.txt'), $summaryText + "`r`n", $utf8NoBom)

Say ''
Say '=== KIT SUMMARY ===' 'Cyan'
Say $summaryText
Say ''
Say ('Send back ONLY the files in this folder (they have your user name and PC name removed): ' + (Protect-Text $resultsDir)) 'Green'
Say '  SUMMARY.txt, SANITIZED-...log, SANITIZED-...json   (do not send the shortcut-backup folder)' 'Green'

if ($shortcutStatus -like 'NOT RESTORED*') { exit 10 }
if ($harnessExit -ne 0) { exit 1 }
exit 0
