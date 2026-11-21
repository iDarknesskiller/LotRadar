# LotRadar QA kit: guided MANUAL startup-window acceptance (TEST-ONLY). Dot-sourced by Run-QAKit.ps1 -UiPreview / -ManualUI.
# Uses from Run-QAKit.ps1: Say, Get-Sha, Protect-Text, Confirm-Start, $pkgZip, $info, $os, $isWin11, $isAdmin,
# $resultsDir, $qaHome, $localAppData, $desktopLnk, $psExe, and the functions of LotRadarQA.Cleanup.ps1.
#
# Stage A (-UiPreview): the REAL startup window in -Preview mode (example steps, nothing started or written). For
#   E3 keyboard and E4 display scaling. Appearance/interaction only; it proves nothing about a real launch.
# Stage B (-ManualUI): a REAL start inside a disposable sandbox for E1, E2, E5, E6, started by the person with an
#   Explorer double-click on a separate TEST shortcut. The real LotRadar program, data, runtime and shortcut are
#   never written (read-only fingerprints before/after), WinGet is hidden from the test start (no Python is ever
#   installed), and only processes/listeners this script can attribute to the sandbox are ever stopped.
# NOTE: dot-sourced; never call 'exit'. Sets $script:ManualExit and returns.

$script:ManualExit = 1
$mRows = New-Object System.Collections.ArrayList
$enc = New-Object System.Text.UTF8Encoding $false
function Add-M([string]$Id, [string]$Name, [string]$Status, [string]$Detail) {
    [void]$mRows.Add([pscustomobject]@{ Id = $Id; Name = $Name; Status = $Status; Detail = $Detail })
    $c = 'Green'; if ($Status -eq 'FAIL') { $c = 'Red' } elseif ($Status -ne 'PASS') { $c = 'Yellow' }
    Say ('[' + $Status + '] ' + $Id + ' ' + $Name + ' - ' + $Detail) $c
}
function Read-YesNo([string]$Question) {
    # One key: Y = yes, N = no, S = skip. No console -> skip.
    if ([Console]::IsInputRedirected) { return 'S' }
    Write-Host ''
    Write-Host ($Question + '  [Y = yes, N = no, S = skip] ') -ForegroundColor Cyan -NoNewline
    while ($true) {
        $k = [Console]::ReadKey($true).KeyChar.ToString().ToUpperInvariant()
        if (@('Y', 'N', 'S') -contains $k) { Write-Host $k; return $k }
    }
}
function Wait-Key([string]$Text) {
    if ([Console]::IsInputRedirected) { return }
    Write-Host ''
    Write-Host ($Text + '  (press any key)') -ForegroundColor Cyan
    [void][Console]::ReadKey($true)
}
function Get-Dpi {
    try {
        Add-Type -AssemblyName System.Drawing
        $src = 'using System; using System.Runtime.InteropServices; namespace LotRadarQA { public static class Dpi { [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); } }'
        if (-not ('LotRadarQA.Dpi' -as [type])) { Add-Type -TypeDefinition $src; [void][LotRadarQA.Dpi]::SetProcessDPIAware() }
        $g = [Drawing.Graphics]::FromHwnd([IntPtr]::Zero)
        $d = [int]$g.DpiX; $g.Dispose()
        return $d
    } catch { return 0 }
}
function Save-Shot($Proc, [string]$Name) {
    # Only the window's own rectangle; it is brought to the front first. Inspect before sharing.
    try {
        $src = 'using System; using System.Runtime.InteropServices; namespace LotRadarQA { public static class MWin { [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; } [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r); [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h); [DllImport("dwmapi.dll")] public static extern int DwmGetWindowAttribute(IntPtr h, int a, out RECT r, int s); [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags); } }'
        if (-not ('LotRadarQA.MWin' -as [type])) { Add-Type -TypeDefinition $src; [void][LotRadarQA.MWin]::SetProcessDPIAware() }
        Add-Type -AssemblyName System.Drawing
        $Proc.Refresh(); $h = $Proc.MainWindowHandle
        if ($h -eq [IntPtr]::Zero) { return 'no window to capture' }
        [void][LotRadarQA.MWin]::SetForegroundWindow($h); Start-Sleep -Milliseconds 600
        $r = New-Object LotRadarQA.MWin+RECT
        if ([LotRadarQA.MWin]::DwmGetWindowAttribute($h, 9, [ref]$r, 16) -ne 0) { [void][LotRadarQA.MWin]::GetWindowRect($h, [ref]$r) }   # visible frame only
        # PrintWindow asks the window to draw itself, so nothing that overlaps it on screen (other apps, chats,
        # names) can end up in the picture (Windows 11 preview run of 9b81e2c captured an overlapping window).
        $wr = New-Object LotRadarQA.MWin+RECT; [void][LotRadarQA.MWin]::GetWindowRect($h, [ref]$wr)
        $fw = $wr.R - $wr.L; $fh = $wr.B - $wr.T
        if ($fw -le 0 -or $fh -le 0) { return 'window has no size' }
        $full = New-Object Drawing.Bitmap $fw, $fh
        $g = [Drawing.Graphics]::FromImage($full); $hdc = $g.GetHdc()
        $okPrint = [LotRadarQA.MWin]::PrintWindow($h, $hdc, 2)
        $g.ReleaseHdc($hdc); $g.Dispose()
        if (-not $okPrint) { $full.Dispose(); return 'window could not draw itself (no picture saved)' }
        $cx = [math]::Max(0, $r.L - $wr.L); $cy = [math]::Max(0, $r.T - $wr.T)
        $w = [math]::Min($r.R - $r.L, $fw - $cx); $hh = [math]::Min($r.B - $r.T, $fh - $cy)
        $bmp = $full.Clone((New-Object Drawing.Rectangle $cx, $cy, $w, $hh), $full.PixelFormat); $full.Dispose()
        $path = Join-Path $resultsDir ('startup-window-' + $Name + '.png')
        $bmp.Save($path, [Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
        return (Split-Path -Leaf $path) + ' ' + $w + 'x' + $hh
    } catch { return ('screenshot failed: ' + $_.Exception.Message) }
}
function Write-ManualSummary([string]$Title, [string[]]$Head) {
    $fails = @($mRows | Where-Object { $_.Status -eq 'FAIL' }).Count
    $lines = @($Title, ('Kit commit      : ' + $info.source_commit), ('Package         : ' + $info.package_file + ' sha256=' + $info.package_sha256),
        ('Windows         : ' + $os.Caption + ' version ' + $os.Version + ' build ' + $os.BuildNumber + ' (Windows 11: ' + $isWin11 + ')'),
        ('PowerShell      : ' + $PSVersionTable.PSVersion + '; administrator: ' + $isAdmin)) + $Head
    $lines += ('Results         : PASS=' + @($mRows | Where-Object { $_.Status -eq 'PASS' }).Count + ' FAIL=' + $fails + ' SKIP/BLOCKED=' + @($mRows | Where-Object { $_.Status -ne 'PASS' -and $_.Status -ne 'FAIL' }).Count)
    foreach ($row in $mRows) { $lines += ($row.Id + ' ' + $row.Status + ' - ' + $row.Name + ' :: ' + $row.Detail) }
    $shots = @(Get-ChildItem -LiteralPath $resultsDir -Filter 'startup-window-*.png' -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
    $lines += ('Screenshots     : ' + $(if ($shots.Count) { ($shots -join ', ') + ' (window only; LOOK at them before sharing)' } else { 'none' }))
    $text = Protect-Text ($lines -join "`r`n")
    [IO.File]::WriteAllText((Join-Path $resultsDir 'SUMMARY.txt'), $text + "`r`n", $enc)
    [IO.File]::WriteAllText((Join-Path $resultsDir 'SANITIZED-manual-ui.json'), (Protect-Text (@{ results = @($mRows); kit_commit = $info.source_commit } | ConvertTo-Json -Depth 4)), $enc)
    Say ''
    Say $text
    Say ''
    Say ('Results are in: ' + (Protect-Text $resultsDir)) 'Green'
    try { Start-Process -FilePath 'explorer.exe' -ArgumentList ('"' + $resultsDir + '"') } catch { }
    if ($fails -gt 0) { $script:ManualExit = 1 } else { $script:ManualExit = 0 }
}
function Expand-KitPackage([string]$Dest) {
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
    Expand-Archive -LiteralPath $pkgZip -DestinationPath $Dest -Force
    return $Dest
}

# =====================================================================================================  Stage A
if ($UiPreview) {
    Say ''
    Say '=== Startup window PREVIEW (Stage A) ===' 'Cyan'
    Say 'This shows the real LotRadar startup window with EXAMPLE steps. Nothing is started, installed or written.' 'Green'
    $dpi = Get-Dpi
    $pct = 0; if ($dpi -gt 0) { $pct = [int][math]::Round($dpi * 100 / 96) }
    Say ('Display scaling now: ' + $pct + '% (' + $dpi + ' dpi). Keep current display settings for LR-010.') 'Yellow'
    Say 'Keep display settings unchanged for LR-010. For a separately scheduled E4 scale change, SIGN OUT of Windows and back in before measuring.' 'Gray'
    # Only the startup window script is taken from the verified package (no other program files are unpacked).
    $gui = Join-Path $resultsDir 'preview\startup\Show-LotRadarStartup.ps1'
    New-Item -ItemType Directory -Path (Split-Path -Parent $gui) -Force | Out-Null
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $z = [IO.Compression.ZipFile]::OpenRead($pkgZip)
    try {
        $ge = $z.GetEntry('MarketplaceScanner/startup/Show-LotRadarStartup.ps1')
        if (-not $ge) { throw 'the startup window is not in this package' }
        [IO.Compression.ZipFileExtensions]::ExtractToFile($ge, $gui, $true)
    } finally { $z.Dispose() }
    $steps = @(
        @(1,'P-TAB','At failure press Tab four times. Focus cycles Details, Console, Retry (F5), Close.')
        @(1,'P-STAB','Press Shift+Tab four times. Focus cycles in reverse.')
        @(1,'P-ALTS','Press Alt+S. Details open and Hide details appears.')
        @(1,'P-ALTD','Press Alt+D. Details close.')
        @(1,'P-ALTC','Press Alt+C. Read the preview message about no console.')
        @(1,'P-F5-RETRY','Tab to Retry and press plain F5 once. Observe the focused control after Retry disables.')
        @(1,'P-F5-RUNNING','While starting tap F5 repeatedly and hold it for two seconds. Startup continues once.')
        @(1,'P-F5-DONE','After LotRadar is open press F5. No new attempt.')
        @(1,'P-ESC','Press Escape. The window closes.')
        @(2,'P-F5-FOCUS-BTN','At failure focus Show details using Tab, press F5 once. Watch focus and wait for success, then close with X.')
        @(3,'P-F5-FOCUS-DETAILS','At failure open details, click in the details text and press F5. No keystroke edits the text. Wait for success, then close with X.')
        @(4,'P-CLICK-PARITY','At failure click Retry (F5) once. Observe resulting focus, wait for success, then close with X.')
        @(5,'P-ALTR-NONE','At failure focus the form and press Alt+R. LotRadar stays failed. Observe any other application response.')
        @(5,'P-F5-OTHER-WINDOW','Focus the QA console and press F5. LotRadar stays failed. Observe the console response.')
        @(5,'P-LABEL','Before closing, inspect Retry (F5). The whole label must fit.')
        @(5,'P-ALTL','Refocus the failed LotRadar window and press Alt+L. It closes.')
    )
    for ($run = 1; $run -le 5; $run++) {
        $rows = @($steps | Where-Object { $_[0] -eq $run })
        Say ("Preview run $run. Read these actions in advance. Wait for the example failure before starting.") 'Cyan'
        foreach ($row in $rows) { Say ($row[1] + ' ' + $row[2]) 'Gray' }
        Wait-Key 'Press Enter when ready to open this preview'
        $pvResult = Join-Path $resultsDir ("preview-result-$run.json")
        $p = Start-Process -FilePath $psExe -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-STA','-File',('"' + $gui + '"'),'-Preview','-ResultFile',('"' + $pvResult + '"')) -PassThru
        $null = $p.Handle
        if ($run -eq 1) {
            Start-Sleep -Seconds 4
            $s1 = Save-Shot $p 'preview-progress'
            Start-Sleep -Seconds 9
            $s2 = Save-Shot $p 'preview-failure'
            Add-M 'A0' 'Preview window captured' 'INFO' ($s1 + '; ' + $s2)
        }
        $p.WaitForExit()
        $auto = $null
        if (Test-Path -LiteralPath $pvResult) { $auto = Get-Content -Raw -LiteralPath $pvResult | ConvertFrom-Json }
        $expected = if ($run -eq 5) { 1 } else { 2 }
        if ($auto -and $auto.attempts -gt $expected) { throw "Stop: preview $run exceeded $expected attempts" }
        foreach ($row in $rows) {
            $id = $row[1]
            $answer = Read-YesNo ($id + ' Did you observe this exact result? ' + $row[2])
            $observation = Read-Host 'Record actual focused control, mode, Retry enabled/disabled and observed result (include focus after retry)'
            $state = switch ($answer) { 'Y' { 'PASS' } 'N' { 'FAIL' } default { 'SKIP' } }
            if ($state -eq 'PASS') {
                if ($null -eq $auto) { $state = 'INCONCLUSIVE' }
                elseif ($auto.attempts -ne $expected -or $p.ExitCode -ne 0) { $state = 'FAIL' }
                elseif ($run -lt 5 -and $auto.mode -ne 'done') { $state = 'FAIL' }
                elseif ($run -eq 5 -and ($auto.mode -ne 'failed' -or $auto.retry_log)) { $state = 'FAIL' }
                elseif ($run -in 1,2,3 -and $auto.retry_log -notmatch '(^|,)f5:started(,|$)') { $state = 'FAIL' }
                elseif ($run -eq 4 -and $auto.retry_log -ne 'click:started') { $state = 'FAIL' }
                elseif ($id -eq 'P-F5-RUNNING' -and ($auto.retry_log -notmatch 'f5:repeat' -or $auto.retry_log -notmatch 'f5:not-eligible')) { $state = 'FAIL' }
                elseif ($id -eq 'P-F5-DONE' -and @($auto.retry_log.Split(',') | Where-Object { $_ -eq 'f5:not-eligible' }).Count -lt 2) { $state = 'INCONCLUSIVE' }
                elseif ($id -eq 'P-LABEL' -and $auto.clipped) { $state = 'FAIL' }
            }
            Add-M $id $row[2] $state (Protect-Text ("Windows " + [Environment]::OSVersion.Version + " PS " + $PSVersionTable.PSVersion + " DPI $dpi scale $pct% run $run attempts=" + $auto.attempts + " log=" + $auto.retry_log + " observed=" + $observation))
        }
    }
    $incomplete = @($mRows | Where-Object { $_.Id -like 'P-*' -and $_.Status -ne 'PASS' })
    $e3Status = 'PASS'
    foreach ($status in 'SKIP','INCONCLUSIVE','BLOCKED','FAIL') { if ($incomplete.Status -contains $status) { $e3Status = $status } }
    Add-M 'E3' 'Physical keyboard results' $e3Status ('Rows requiring review: ' + ($incomplete.Id -join ', '))


    if ($null -eq $auto -or [string]$auto.clipped -eq 'not checked') { Add-M 'E4a' 'Automatic check: no text cut off' 'SKIP' 'the window did not report a measurement' }
    elseif ([string]$auto.clipped) { Add-M 'E4a' 'Automatic check: no text cut off' 'FAIL' ('cut off at ' + $pct + '%: ' + $auto.clipped) }
    else { Add-M 'E4a' 'Automatic check: no text cut off' 'PASS' ('every label and button fits at ' + $pct + '% (layout scale ' + $auto.scale + ')') }
    $e4 = Read-YesNo ('E4 display at ' + $pct + '%: was ALL text and every button fully visible (also with details open)?')
    $e4Status = switch ($e4) { 'Y' { 'PASS' } 'N' { 'FAIL' } default { 'SKIP' } }
    $e4Detail = ('scaling ' + $pct + '%')
    if ($e4Status -eq 'PASS' -and $null -ne $auto -and [string]$auto.clipped -and [string]$auto.clipped -ne 'not checked') { $e4Status = 'FAIL'; $e4Detail += ' (person answered yes, but the automatic check found text cut off)' }
    if ($e4Status -eq 'PASS' -and $pct -lt 150) { $e4Status = 'INCOMPLETE'; $e4Detail += ' (looks fine here; E4 needs a run at 150%)' }
    Add-M 'E4' 'Display scaling: no clipped text or controls' $e4Status $e4Detail
    $e0 = Read-YesNo 'E0 look: a small dark window with only the round LotRadar mark in the middle (an "LR" circle in this preview), "Initializing LotRadar", a BLUE moving bar with no percentage and the four steps SYSTEM CHECK / LOADING MODULES / STARTING SERVER / LAUNCHING LOTRADAR?'
    Add-M 'E0' 'Appearance matches the approved minimal design (logo, status, blue bar, four steps)' $(switch ($e0) { 'Y' { 'PASS' } 'N' { 'FAIL' } default { 'SKIP' } }) ('answered by the person at ' + $pct + '%; the private logo itself is shown only by a production package')
    Write-ManualSummary 'LotRadar manual UI acceptance - Stage A (preview only; proves appearance/keyboard, NOT a real launch)' @(('Display scaling : ' + $pct + '% (' + $dpi + ' dpi)'))
    return
}

# =====================================================================================================  Stage B
Say ''
Say '=== Real start in a TEST folder (Stage B: E1, E2, E5, E6) ===' 'Cyan'
$realLocal = $localAppData
$realProgram = Join-Path $realLocal 'Programs\MarketplaceScanner'
$realUser = Join-Path $realLocal 'MarketplaceScanner'
$realData = Join-Path $realUser 'data'

# ---- B0 read-only preflight (nothing is written here)
function Get-Fingerprint([string]$Dir) {
    # names + sizes + modified times of every file (read-only; contents of photos are not read)
    if (-not (Test-Path -LiteralPath $Dir)) { return 'absent' }
    $sb = New-Object System.Text.StringBuilder
    $n = 0
    foreach ($f in @(Get-ChildItem -LiteralPath $Dir -Recurse -File -Force -ErrorAction SilentlyContinue | Sort-Object FullName)) {
        [void]$sb.Append($f.FullName.Substring($Dir.Length)).Append('|').Append($f.Length).Append('|').Append($f.LastWriteTimeUtc.Ticks).Append("`n"); $n++
    }
    $sha = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($enc.GetBytes($sb.ToString()))).Replace('-', '').ToLowerInvariant()
    return ($n.ToString() + ' files, listing sha256 ' + $sha.Substring(0, 16))
}
function Find-BasePythonQA {
    # Same rules as the bootstrap: registry PythonCore, py -3, python.exe outside WindowsApps; 3.10+ with venv + ensurepip.
    $probe = 'import sys, venv, ensurepip; sys.exit(sys.version_info < (3, 10))'
    $cands = @()
    foreach ($root in @('HKCU:\Software\Python\PythonCore', 'HKLM:\Software\Python\PythonCore', 'HKLM:\Software\WOW6432Node\Python\PythonCore')) {
        foreach ($v in @(Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue)) {
            $k = Get-Item -LiteralPath (Join-Path $v.PSPath 'InstallPath') -ErrorAction SilentlyContinue
            if ($k) { $e = $k.GetValue('ExecutablePath'); if (-not $e -and $k.GetValue('')) { $e = Join-Path ($k.GetValue('')) 'python.exe' }; if ($e) { $cands += ,@($e, @()) } }
        }
    }
    $py = Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($py -and $py.Source -notlike '*\Microsoft\WindowsApps\*') { $cands += ,@($py.Source, @('-3')) }
    foreach ($pp in @(Get-Command python.exe -CommandType Application -All -ErrorAction SilentlyContinue)) { if ($pp.Source -notlike '*\Microsoft\WindowsApps\*') { $cands += ,@($pp.Source, @()) } }
    foreach ($c in $cands) {
        if (-not (Test-Path -LiteralPath $c[0] -PathType Leaf)) { continue }
        $ErrorActionPreference = 'Continue'
        $pre = $c[1]
        & $c[0] @pre -c $probe 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { return $c[0] }
    }
    return ''
}
$testLnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'LotRadar TEST (sandbox).lnk'
if (Test-Path -LiteralPath $testLnk) {
    # Leftover of an interrupted Stage B run: removed only if it verifiably points into a kit sandbox folder.
    $t = ''; try { $t = (New-Object -ComObject WScript.Shell).CreateShortcut($testLnk).TargetPath } catch { }
    if ($t -match '\\LotRadar Test Sandbox [0-9a-f]{8}\\Start LotRadar TEST\.cmd$') { Remove-Item -LiteralPath $testLnk -Force; Say 'Removed a leftover "LotRadar TEST (sandbox)" shortcut from an earlier run.' 'Yellow' }
    else { Add-M 'B0' 'Leftover check' 'FAIL' 'a "LotRadar TEST (sandbox)" shortcut exists that this kit did not make; left untouched, test not run'; Write-ManualSummary 'LotRadar manual UI acceptance - Stage B (stopped)' @(); return }
}
$lnkInfo = 'none'
if (Test-Path -LiteralPath $desktopLnk) { $lnkInfo = 'present sha256 ' + (Get-Sha $desktopLnk).Substring(0, 16) }
$before = @{ Program = (Get-Fingerprint $realProgram); Data = (Get-Fingerprint $realData); Runtime = (Test-Path -LiteralPath (Join-Path $realUser 'runtime')); Shortcut = $lnkInfo }
$odBefore = 0
foreach ($od in @($env:OneDrive, $env:OneDriveConsumer, $env:OneDriveCommercial)) { if ($od -and (Test-Path -LiteralPath $od)) { $odBefore += @(Get-ChildItem -LiteralPath $od -Directory -Filter 'LotRadar*' -ErrorAction SilentlyContinue).Count } }
Add-M 'B0' 'Read-only preflight of the REAL LotRadar (nothing written)' 'INFO' ('program: ' + $before.Program + '; data: ' + $before.Data + '; runtime folder present: ' + $before.Runtime + '; Desktop LotRadar.lnk: ' + $before.Shortcut)
$basePy = Find-BasePythonQA
if (-not $basePy) {
    foreach ($id in @('E1', 'E2', 'E5', 'E6')) { Add-M $id 'Real start in the test folder' 'BLOCKED' 'no Python 3.10+ is installed for this user; the test never installs one (would need WinGet). Needs an Owner-approved Python first.' }
    Write-ManualSummary 'LotRadar manual UI acceptance - Stage B (BLOCKED: no existing Python)' @('Python          : none found (no install attempted)')
    return
}
Add-M 'B1' 'Existing Python 3.10+ found (nothing will be installed globally)' 'INFO' (Protect-Text $basePy)

Say ''
Say 'This test installs LotRadar into a TEMPORARY test folder and lets YOU start it from a separate Desktop' 'Yellow'
Say 'shortcut called "LotRadar TEST (sandbox)". The first start downloads Python packages and a browser runtime' 'Yellow'
Say '(several hundred MB) INTO THE TEST FOLDER only. Your real LotRadar program, data, photos, drafts and your' 'Yellow'
Say 'real Desktop shortcut are not changed (they are fingerprinted before and after). OneDrive is not used.' 'Yellow'
Say 'Takes about 15-30 minutes, you will be asked to double-click and answer Y/N a few times.' 'Yellow'
if (-not (Confirm-Start 'guided real-start test')) { Add-M 'B2' 'Consent' 'SKIP' 'cancelled'; Write-ManualSummary 'LotRadar manual UI acceptance - Stage B (cancelled)' @(); return }

$sandbox = Join-Path $realLocal ('Temp\LotRadar Test Sandbox ' + (New-QAOwnerToken).Substring(0, 8))
[void](New-QAOwnedFolder $sandbox 'sandbox' (Join-Path $qaHome 'owned') 'Disposable LotRadar manual UI test sandbox. Synthetic data only.')
$sbLocal = Join-Path $sandbox 'Local'; $sbRoam = Join-Path $sandbox 'Roaming'
New-Item -ItemType Directory -Path $sbLocal, $sbRoam -Force | Out-Null
$sbProgram = Join-Path $sbLocal 'Programs\MarketplaceScanner'
$sbRuntime = Join-Path $sbLocal 'MarketplaceScanner\runtime'
$lnkBackup = Join-Path $resultsDir 'shortcut-backup\LotRadar.lnk'
$hadLnk = Test-Path -LiteralPath $desktopLnk
$lnkSha = ''
function Get-SandboxServers { return @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*server.py*' -and $_.CommandLine -like ('*' + $sbLocal + '*') }) }
function Get-SandboxRoots { $p = @(Get-SandboxServers); $ids = @($p | ForEach-Object { $_.ProcessId }); return @($p | Where-Object { $ids -notcontains $_.ParentProcessId }) }
function Stop-SandboxServer {
    foreach ($s in @(Get-SandboxServers)) { $ErrorActionPreference = 'Continue'; & taskkill.exe /PID $s.ProcessId /T /F 2>&1 | Out-Null }
    $dl = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $dl -and (@(Get-SandboxServers).Count -gt 0)) { Start-Sleep -Seconds 1 }
}
function Test-Health {
    try { $h = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 3; return ($h.ok -eq $true -and $h.local_only -eq $true -and $h.service -eq 'Marketplace Scanner') } catch { return $false }
}
function Test-LockHeld {
    try { $l = [IO.File]::Open((Join-Path $sbRuntime 'marketplace-launch.lock'), 'OpenOrCreate', 'ReadWrite', 'None'); $l.Dispose(); return $false } catch { return $true }
}
function Get-AutoCheck {
    $roots = @(Get-SandboxRoots).Count
    return [pscustomobject]@{ Health = (Test-Health); Roots = $roots; Lock = (Test-LockHeld); Text = ('health=' + (Test-Health) + ' server trees=' + $roots + ' launch lock held=' + (Test-LockHeld)) }
}
function Wait-Healthy([int]$Minutes) {
    $dl = (Get-Date).AddMinutes($Minutes)
    while ((Get-Date) -lt $dl) { if (Test-Health) { return $true }; Start-Sleep -Seconds 3 }
    return $false
}
$listener = $null
try {
    if ($hadLnk) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $lnkBackup) -Force | Out-Null
        Copy-Item -LiteralPath $desktopLnk -Destination $lnkBackup -Force; $lnkSha = Get-Sha $desktopLnk
        # Second copy where the kit's leftover repair looks for it if this window is closed mid-install.
        $sbBackup = Join-Path $sandbox 'desktop-backup\LotRadar.lnk'
        New-Item -ItemType Directory -Path (Split-Path -Parent $sbBackup) -Force | Out-Null
        Copy-Item -LiteralPath $desktopLnk -Destination $sbBackup -Force
        if ((Get-Sha $lnkBackup) -ne $lnkSha -or (Get-Sha $sbBackup) -ne $lnkSha) { throw 'could not make verified copies of the Desktop LotRadar shortcut' }
    }
    # ---- install into the sandbox (the installer writes Desktop\LotRadar.lnk; restored right after)
    $pkg = Expand-KitPackage (Join-Path $sandbox 'Package')
    $savedEnv = @{ LOCALAPPDATA = $env:LOCALAPPDATA; APPDATA = $env:APPDATA; LOTRADAR_NO_PAUSE = $env:LOTRADAR_NO_PAUSE }
    try {
        $env:LOCALAPPDATA = $sbLocal; $env:APPDATA = $sbRoam; $env:LOTRADAR_NO_PAUSE = '1'
        $ErrorActionPreference = 'Continue'
        $out = & $psExe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $pkg 'Install-LotRadar.ps1') 2>&1 | Out-String
        $instCode = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
    } finally { foreach ($k in $savedEnv.Keys) { if ($null -eq $savedEnv[$k]) { Remove-Item ('Env:\' + $k) -ErrorAction SilentlyContinue } else { Set-Item ('Env:\' + $k) $savedEnv[$k] } } }
    if ($hadLnk) { Copy-Item -LiteralPath $lnkBackup -Destination $desktopLnk -Force } elseif (Test-Path -LiteralPath $desktopLnk) { Remove-Item -LiteralPath $desktopLnk -Force }
    $lnkOk = ((-not $hadLnk -and -not (Test-Path -LiteralPath $desktopLnk)) -or ($hadLnk -and (Get-Sha $desktopLnk) -eq $lnkSha))
    Add-M 'B3' 'Install into the test folder; real Desktop shortcut put back' $(if ($instCode -eq 0 -and $lnkOk) { 'PASS' } else { 'FAIL' }) ('installer exit ' + $instCode + '; Desktop LotRadar.lnk restored byte-identical: ' + $lnkOk)
    if ($instCode -ne 0 -or -not $lnkOk) { throw 'sandbox install or shortcut restore failed' }

    # ---- the TEST start: a .cmd that points LOCALAPPDATA/APPDATA at the sandbox and hides WinGet (no Python install)
    $wrapper = Join-Path $sandbox 'Start LotRadar TEST.cmd'
    $cmd = @('@echo off', 'rem LotRadar TEST start (sandbox only). Safe to delete.', ('set "LOCALAPPDATA=' + $sbLocal + '"'), ('set "APPDATA=' + $sbRoam + '"'),
        'set "LOTRADAR_NO_PAUSE="', 'set "LOTRADAR_STARTUP_GUI="',
        ('set "PATH=%PATH:' + $realLocal + '\Microsoft\WindowsApps=%"'),
        'where winget.exe >nul 2>&1 && (echo WinGet is still visible, so this TEST start is stopped ^(it must never install Python^). & pause & exit /b 1)',
        ('call "' + (Join-Path $sbProgram 'Launch Marketplace Scanner.cmd') + '"'))
    [IO.File]::WriteAllText($wrapper, (($cmd -join "`r`n") + "`r`n"), [Text.Encoding]::ASCII)
    $sc = (New-Object -ComObject WScript.Shell).CreateShortcut($testLnk)
    $sc.TargetPath = $wrapper; $sc.WorkingDirectory = $sbProgram; $sc.Description = 'LotRadar TEST (sandbox) - created by the QA kit, removed at the end'
    $sc.Save()

    # ---- E5 first start (slow, downloads into the sandbox): close the window while starting
    Wait-Key 'E5: Double-click "LotRadar TEST (sandbox)" on your Desktop NOW. When the LotRadar window shows "In progress", click its X to close it. Then come back here'
    Say 'Waiting for LotRadar to finish starting by itself (first start can take 5-20 minutes)...' 'Gray'
    $ok5 = Wait-Healthy 25
    $a5 = Get-AutoCheck
    $q5 = Read-YesNo 'E5: after you closed the window, did the black "LotRadar Server" window come up and keep working, and did LotRadar open by itself?'
    $s5 = 'FAIL'; if ($q5 -eq 'Y' -and $ok5 -and $a5.Roots -eq 1 -and $a5.Lock) { $s5 = 'PASS' } elseif ($q5 -eq 'S') { $s5 = 'SKIP' }
    Add-M 'E5' 'Close the startup window while starting: startup continues, console shown, LotRadar opens' $s5 ('person: ' + $q5 + '; ' + $a5.Text)
    Wait-Key 'Close the LotRadar app window that opened (not this window). I will stop the test server next'
    Stop-SandboxServer

    Add-M 'R-E5' 'Close during first start' $s5 ('Owner ' + $q5 + '; ' + $a5.Text)
    if ($a5.Roots -gt 1) { throw 'Stop: second server tree' }
    if ($env:LOTRADAR_QA_LR010_R -ne '1') {
    # ---- E1 normal start (provisioned)
    Wait-Key 'E1: Double-click "LotRadar TEST (sandbox)" again and just WATCH (do not click). Then come back here'
    $ok1 = Wait-Healthy 5
    Start-Sleep -Seconds 5
    $a1 = Get-AutoCheck
    $q1 = Read-YesNo 'E1: did the steps go Waiting > In progress > Done, LotRadar open ONCE, and the startup window close by itself?'
    $s1 = 'FAIL'; if ($q1 -eq 'Y' -and $ok1 -and $a1.Roots -eq 1 -and $a1.Lock) { $s1 = 'PASS' } elseif ($q1 -eq 'S') { $s1 = 'SKIP' }
    Add-M 'E1' 'Explorer double-click: honest steps, LotRadar opens once, one server, lock held' $s1 ('person: ' + $q1 + '; ' + $a1.Text)

    # ---- E2 second double-click while running
    Wait-Key 'E2: Double-click "LotRadar TEST (sandbox)" once more while it runs. Then come back here'
    Start-Sleep -Seconds 8
    $a2 = Get-AutoCheck
    $q2 = Read-YesNo 'E2: did LotRadar open again (a second app window is fine) with still only ONE "LotRadar Server" window?'
    $s2 = 'FAIL'; if ($q2 -eq 'Y' -and $a2.Health -and $a2.Roots -eq 1) { $s2 = 'PASS' } elseif ($q2 -eq 'S') { $s2 = 'SKIP' }
    Add-M 'E2' 'Second double-click: no second server' $s2 ('person: ' + $q2 + '; ' + $a2.Text)
    Wait-Key 'Close the LotRadar app window(s). I will stop the test server next'
    Stop-SandboxServer

    }
    # Sample only cmd children of the startup form in this owned sandbox.
    $trace = Join-Path $resultsDir 'startup-attempts.csv'
    $sampler = Start-Job -ArgumentList $sbProgram,$trace -ScriptBlock {
        param($program,$trace)
        $seen = @{}
        while ($true) {
            $forms = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object {
                $_.CommandLine -like ('*' + $program + '*Show-LotRadarStartup.ps1*')
            })
            foreach ($formProcess in $forms) {
                foreach ($child in @(Get-CimInstance Win32_Process -Filter ("Name='cmd.exe' AND ParentProcessId=" + $formProcess.ProcessId))) {
                    $key = "$($formProcess.ProcessId)/$($child.ProcessId)/$($child.CreationDate.Ticks)"
                    if (-not $seen.ContainsKey($key)) {
                        $seen[$key] = $true
                        [pscustomobject]@{ utc=[DateTime]::UtcNow.ToString('o'); form=$formProcess.ProcessId; console=$child.ProcessId } | Export-Csv -LiteralPath $trace -NoTypeInformation -Append
                    }
                }
            }
            Start-Sleep -Milliseconds 500
        }
    }
    function Get-AttemptTotal {
        if ($sampler.State -ne 'Running') { throw 'Attempt sampler stopped' }
        if (Test-Path -LiteralPath $trace) { return @(Import-Csv -LiteralPath $trace).Count }
        return 0
    }
    function Read-RealRow($id,$action,$beforeCount,$delta,$wantHealthy) {
        Wait-Key $action
        $check = Get-AutoCheck
        $afterCount = Get-AttemptTotal
        $observed = $afterCount - $beforeCount
        if ($check.Roots -gt 1 -or $observed -gt $delta) { throw ("Stop at $id - " + $check.Text + " new attempts=$observed") }
        $answer = Read-YesNo ($id + ' Did the specified action give the expected result?')
        $detail = Read-Host 'Record actual focused control, Retry state, mode and result'
        $state = 'PASS'
        if ($answer -eq 'S') { $state = 'SKIP' }
        elseif ($answer -eq 'N' -or $check.Roots -ne [int]$wantHealthy -or ($wantHealthy -and (-not $check.Lock -or -not $check.Health))) { $state = 'FAIL' }
        elseif ($observed -lt $delta) { $state = 'INCONCLUSIVE' }
        Add-M $id $action $state (Protect-Text ("new attempts $observed/$delta, " + $check.Text + ", observation: " + $detail))
    }
    try {
        foreach ($method in 'F5','click') {
            $beforeStart = Get-AttemptTotal
            $listener = New-Object System.Net.Sockets.TcpListener([Net.IPAddress]::Loopback, 8765)
            $listener.Start()
            Wait-Key 'Double-click the TEST shortcut. Wait for its port failure and enabled Retry. Leave the startup window open.'
            $first = Get-AttemptTotal
            if ($first -ne ($beforeStart + 1)) { throw "Expected exactly one observed initial attempt, observed $($first-$beforeStart)" }
            if ($method -eq 'F5') {
                Read-RealRow 'R-F5-FAIL' 'With the test listener active, press F5 once. Wait for another port failure. Expect one attempt and zero servers.' $first 1 $false
                $first = Get-AttemptTotal
                Read-RealRow 'R-ALTC-RETURN' 'Press Alt+C, click back into the form and press Tab. Confirm the real console appeared and focus moves within the form.' $first 0 $false
            }
            $listener.Stop(); $listener = $null
            $first = Get-AttemptTotal
            if ($method -eq 'F5') {
                Read-RealRow 'R-F5-OK' 'Press F5 once then tap F5 while starting. Wait for LotRadar to open. Expect one new attempt and one healthy server.' $first 1 $true
            } else {
                Read-RealRow 'R-CLICK-PARITY' 'Click Retry once. Wait for LotRadar to open. Expect one new attempt and one healthy server.' $first 1 $true
            }
            Wait-Key 'Close only the new TEST app window. Press Enter so the kit can stop its test server.'
            Stop-SandboxServer
        }
    } finally { Stop-Job $sampler; Remove-Job $sampler }
    $guard = Read-YesNo 'Did you naturally see the previous attempt is still finishing message after pressing F5? Y to record, N or S if unobserved.'
    if ($guard -eq 'Y') {
        $note = Read-Host 'Record focus, time and actual result so the attempt trace can be correlated'
        Add-M 'R-GUARD' 'Previous console still finishing' 'INCONCLUSIVE' (Protect-Text ("Observed: " + $note + ". Compare sampled console identities before assigning PASS."))
    } else { Add-M 'R-GUARD' 'Previous console still finishing' 'NOT RUN' 'Did not occur during physical session' }
    $errorsR = @($mRows | Where-Object { $_.Id -in 'R-F5-FAIL','R-ALTC-RETURN','R-F5-OK','R-CLICK-PARITY' -and $_.Status -ne 'PASS' })
    Add-M 'E6' 'Real port conflict and Retry parity' $(if ($errorsR.Count) { 'INCOMPLETE' } else { 'PASS' }) ($errorsR.Id -join ', ')


} catch {
    Add-M 'BX' 'Guided test stopped' 'FAIL' (Protect-Text $_.Exception.Message)
} finally {
    if ($listener) { try { $listener.Stop() } catch { } }
    Stop-SandboxServer
    $lockFree = -not (Test-Path -LiteralPath (Join-Path $sbRuntime 'marketplace-launch.lock')) -or -not (Test-LockHeld)
    $portFree = $true
    try { $c = New-Object Net.Sockets.TcpClient; $ar = $c.BeginConnect([Net.IPAddress]::Loopback, 8765, $null, $null); $portFree = -not ($ar.AsyncWaitHandle.WaitOne(500) -and $c.Connected); $c.Dispose() } catch { }
    if (Test-Path -LiteralPath $testLnk) {
        $t = ''; try { $t = (New-Object -ComObject WScript.Shell).CreateShortcut($testLnk).TargetPath } catch { }
        if ($t -and $t.StartsWith($sandbox, [StringComparison]::OrdinalIgnoreCase)) { Remove-Item -LiteralPath $testLnk -Force }
    }
    $lnkNow = 'none'; if (Test-Path -LiteralPath $desktopLnk) { $lnkNow = 'present sha256 ' + (Get-Sha $desktopLnk).Substring(0, 16) }
    $after = @{ Program = (Get-Fingerprint $realProgram); Data = (Get-Fingerprint $realData); Runtime = (Test-Path -LiteralPath (Join-Path $realUser 'runtime')) }
    $odAfter = 0
    foreach ($od in @($env:OneDrive, $env:OneDriveConsumer, $env:OneDriveCommercial)) { if ($od -and (Test-Path -LiteralPath $od)) { $odAfter += @(Get-ChildItem -LiteralPath $od -Directory -Filter 'LotRadar*' -ErrorAction SilentlyContinue).Count } }
    $same = ($after.Program -eq $before.Program -and $after.Data -eq $before.Data -and $after.Runtime -eq $before.Runtime -and $lnkNow -eq $before.Shortcut -and $odAfter -eq $odBefore)
    Add-M 'B9' 'Real LotRadar program/data/runtime, real shortcut and OneDrive unchanged; no test server, port free, lock free' $(if ($same -and $lockFree -and $portFree -and -not (Test-Path -LiteralPath $testLnk)) { 'PASS' } else { 'FAIL' }) ('program ' + $after.Program + '; data ' + $after.Data + '; shortcut ' + $lnkNow + '; OneDrive LotRadar* folders ' + $odBefore + '->' + $odAfter + '; lock free ' + $lockFree + '; port free ' + $portFree)
    # sandbox removal: only with ownership proof, file by file (may take a minute: it holds the downloaded runtime)
    $safe = @(); if ($hadLnk -and (Test-Path -LiteralPath $desktopLnk) -and (Get-Sha $desktopLnk) -eq $lnkSha) { $safe = @($lnkSha) }
    $own = Test-QAOwnedFolder $sandbox 'sandbox' (Join-Path $realLocal 'Temp') @(Read-QALedger (Join-Path $qaHome 'owned')) $safe
    if ($own.Owned) { $res = Remove-QAOwnedFolder $own (Join-Path $realLocal 'Temp') } else { $res = 'left in place: ' + $own.Reason }
    $cleanup = @($mRows | Where-Object { $_.Id -eq 'B9' })[-1]
    Add-M 'R-CLEAN' 'Protected resources and sandbox cleanup' $(if ($cleanup.Status -eq 'PASS' -and ($res -eq 'deleted' -or $own.Owned)) { 'PASS' } else { 'FAIL' }) ($cleanup.Detail + '; ' + $res)
    Add-M 'B10' 'Test folder removed' $(if ($res -eq 'deleted') { 'PASS' } else { 'INFO' }) $res
}
Write-ManualSummary 'LotRadar manual UI acceptance - Stage B (real start in a test folder)' @(('Python          : existing (' + (Protect-Text $basePy) + '); nothing installed globally'))
return
