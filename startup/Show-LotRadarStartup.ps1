<#
.SYNOPSIS
  LotRadar startup window (Windows PowerShell 5.1, Windows Forms). Started by "Launch Marketplace Scanner.cmd" on an
  interactive double-click.

.DESCRIPTION
  This window only SHOWS progress. "Marketplace Bootstrap.ps1" (run through the same launcher with
  LOTRADAR_STARTUP_GUI=0, in its own minimized console window) stays the only owner of the launch lock, the local
  server and the LotRadar browser window. Closing this window therefore never stops LotRadar or its setup.

  Stage reporting: the window passes a random per-attempt LOTRADAR_STARTUP_NONCE; the bootstrap appends one JSON line
  per stage event to %LOCALAPPDATA%\MarketplaceScanner\runtime\startup-status-<nonce>.jsonl. Lines with another nonce
  or an unknown stage/state are ignored. "Ready" needs BOTH the bootstrap's "window opened" event AND this window's
  own successful /api/health check, so a status file alone can never fake success.

  Close behaviour:
    while starting  -> the window closes; startup continues in the "LotRadar Server" console (restored so it is
                       visible); nothing is stopped; exit 0
    after success   -> exit 0 (LotRadar keeps running in its console window)
    after a failure -> the paused console of the failed attempt is closed (only once its bootstrap has exited); exit 91

  Exit codes: 0 opened / already running / closed while starting | 91 failed (shown to the person; the launcher
              returns 1) | 90 window not available here -> the launcher falls back to the console start. Any other
              code (e.g. this script could not run at all) also makes the launcher fall back to the console start.
  -AutoCloseSeconds N (tests): close by itself N seconds after success or failure.
  -ResultFile path   (tests): write the outcome (exit code, result, event list) as JSON when the window closes.
#>
[CmdletBinding()]
param([int]$AutoCloseSeconds = 0, [string]$ResultFile = '')
$ErrorActionPreference = 'Stop'

$programDir = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $programDir 'Launch Marketplace Scanner.cmd'
if ($env:LOTRADAR_STARTUP_GUI_TEST_UNAVAILABLE -eq '1') { exit 90 }   # test hook: simulate "no window possible"
if (-not [Environment]::UserInteractive) { exit 90 }
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { exit 90 }
if (-not $env:LOCALAPPDATA) { exit 90 }   # the console start reports this problem itself

# The window must not create anything through a link: same rule as the installer. Otherwise use the console start.
$userRoot = Join-Path $env:LOCALAPPDATA 'MarketplaceScanner'
$runtimeDir = Join-Path $userRoot 'runtime'
foreach ($p in @($userRoot, $runtimeDir)) {
    try { $a = [IO.File]::GetAttributes($p) } catch { $a = $null }
    if ($null -ne $a -and (($a -band [IO.FileAttributes]::ReparsePoint) -ne 0)) { exit 90 }
}
try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
} catch { exit 90 }

$nativeSource = @'
using System; using System.Runtime.InteropServices;
namespace LotRadarStartup {
  public static class Native {
    [DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  }
}
'@
$native = $true
try { if (-not ('LotRadarStartup.Native' -as [type])) { Add-Type -TypeDefinition $nativeSource } } catch { $native = $false }

# One startup window at a time (a second double-click while this one is open just says so).
$mutex = New-Object System.Threading.Mutex($false, 'Local\LotRadarStartupWindow')
$haveMutex = $false
try { $haveMutex = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $haveMutex = $true }
if (-not $haveMutex) {
    [void][Windows.Forms.MessageBox]::Show('LotRadar is already starting in another window.', 'LotRadar', 'OK', 'Information')
    exit 0
}

# Hide the launcher's own (empty) console while the window is shown; it is shown again if we fall back.
$ownConsole = [IntPtr]::Zero
if ($native) {
    try { [void][LotRadarStartup.Native]::SetProcessDPIAware() } catch { }
    try { $ownConsole = [LotRadarStartup.Native]::GetConsoleWindow(); if ($ownConsole -ne [IntPtr]::Zero) { [void][LotRadarStartup.Native]::ShowWindow($ownConsole, 0) } } catch { }
}

$utf8 = New-Object System.Text.UTF8Encoding $false
$Stages = @(
    @{ Id = 'install'; Label = 'Checking installation' },
    @{ Id = 'python'; Label = 'Checking Python and dependencies' },
    @{ Id = 'browser'; Label = 'Checking browser runtime' },
    @{ Id = 'server'; Label = 'Starting local server' },
    @{ Id = 'open'; Label = 'Opening LotRadar' }
)
$States = @('started', 'info', 'complete', 'failed')

function Protect-Message([string]$Text) {
    if ($null -eq $Text) { return '' }
    $out = $Text
    foreach ($pair in @(@($env:LOCALAPPDATA, '%LOCALAPPDATA%'), @($env:USERPROFILE, '%USERPROFILE%'), @($env:COMPUTERNAME, '<computer>'), @($env:USERNAME, '<user>'))) {
        if ($pair[0] -and ([string]$pair[0]).Length -ge 3) { $out = [regex]::Replace($out, [regex]::Escape([string]$pair[0]), [string]$pair[1], 'IgnoreCase') }
    }
    $out = ($out -replace '[\x00-\x1F]', ' ')
    if ($out.Length -gt 300) { $out = $out.Substring(0, 300) }
    return $out
}
function New-Nonce {
    $b = New-Object byte[] 16
    $rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
    try { $rng.GetBytes($b) } finally { $rng.Dispose() }
    return (($b | ForEach-Object { $_.ToString('x2') }) -join '')
}
function Format-Elapsed([TimeSpan]$t) {
    if ($t.TotalSeconds -lt 60) { return ([int]$t.TotalSeconds).ToString() + ' s' }
    return ([int][math]::Floor($t.TotalMinutes)).ToString() + ' min ' + $t.Seconds + ' s'
}

# Bounded leftovers: status files of earlier attempts older than one day (regular files only).
try {
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    foreach ($old in @(Get-ChildItem -LiteralPath $runtimeDir -File -Filter 'startup-status-*.jsonl' -Force -ErrorAction SilentlyContinue)) {
        if ($old.Name -match '^startup-status-[0-9a-f]{32}\.jsonl$' -and (($old.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) -and $old.LastWriteTimeUtc -lt [DateTime]::UtcNow.AddDays(-1)) {
            Remove-Item -LiteralPath $old.FullName -Force -ErrorAction SilentlyContinue
        }
    }
} catch {
    if ($ownConsole -ne [IntPtr]::Zero) { [void][LotRadarStartup.Native]::ShowWindow($ownConsole, 5) }
    $mutex.ReleaseMutex()
    exit 90
}

# ------------------------------------------------------------------ window
[Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object Windows.Forms.Form
$form.Text = 'LotRadar'
$form.AutoScaleMode = [Windows.Forms.AutoScaleMode]::Dpi
$form.Font = New-Object Drawing.Font('Segoe UI', 9)
$form.FormBorderStyle = [Windows.Forms.FormBorderStyle]::FixedSingle
$form.MaximizeBox = $false
$form.StartPosition = [Windows.Forms.FormStartPosition]::CenterScreen
$form.ClientSize = New-Object Drawing.Size(480, 330)
$form.KeyPreview = $true
$ico = Join-Path $programDir 'LotRadar.ico'
if (Test-Path -LiteralPath $ico -PathType Leaf) { try { $form.Icon = New-Object Drawing.Icon($ico) } catch { } }

# Brand: the packaged private logo when present and a real PNG, otherwise a text mark.
$logoPath = Join-Path $programDir 'branding\lotradar_logo.png'
$brand = $null
try {
    if ((Test-Path -LiteralPath $logoPath -PathType Leaf) -and (Get-Item -LiteralPath $logoPath).Length -lt 5MB) {
        $bytes = [IO.File]::ReadAllBytes($logoPath)
        if ($bytes.Length -gt 8 -and $bytes[0] -eq 0x89 -and $bytes[1] -eq 0x50 -and $bytes[2] -eq 0x4E -and $bytes[3] -eq 0x47) {
            $brand = New-Object Windows.Forms.PictureBox
            $brand.Image = [Drawing.Image]::FromStream((New-Object IO.MemoryStream(, $bytes)))
            $brand.SizeMode = [Windows.Forms.PictureBoxSizeMode]::Zoom
        }
    }
} catch { $brand = $null }
if (-not $brand) {
    $brand = New-Object Windows.Forms.Label
    $brand.Text = 'LR'
    $brand.Font = New-Object Drawing.Font('Segoe UI', 20, [Drawing.FontStyle]::Bold)
    $brand.TextAlign = [Drawing.ContentAlignment]::MiddleCenter
    $brand.BackColor = [Drawing.Color]::FromArgb(24, 48, 72)
    $brand.ForeColor = [Drawing.Color]::White
}
$brand.Location = New-Object Drawing.Point(16, 14)
$brand.Size = New-Object Drawing.Size(56, 56)
$brand.AccessibleName = 'LotRadar'
$form.Controls.Add($brand)

$title = New-Object Windows.Forms.Label
$title.Text = 'Starting LotRadar'
$title.Font = New-Object Drawing.Font('Segoe UI', 14, [Drawing.FontStyle]::Bold)
$title.Location = New-Object Drawing.Point(84, 16)
$title.Size = New-Object Drawing.Size(380, 30)
$form.Controls.Add($title)

$status = New-Object Windows.Forms.Label
$status.Text = 'Preparing...'
$status.Location = New-Object Drawing.Point(86, 48)
$status.Size = New-Object Drawing.Size(380, 34)
$form.Controls.Add($status)

$rows = @{}
$y = 90
foreach ($st in $Stages) {
    $name = New-Object Windows.Forms.Label
    $name.Text = $st.Label
    $name.Location = New-Object Drawing.Point(20, $y)
    $name.Size = New-Object Drawing.Size(250, 22)
    $state = New-Object Windows.Forms.Label
    $state.Text = 'Waiting'
    $state.ForeColor = [Drawing.Color]::Gray
    $state.Location = New-Object Drawing.Point(276, $y)
    $state.Size = New-Object Drawing.Size(190, 22)
    $state.AccessibleName = $st.Label
    $form.Controls.Add($name); $form.Controls.Add($state)
    $rows[$st.Id] = @{ Label = $state; State = 'waiting'; Since = $null }
    $y += 24
}
$bar = New-Object Windows.Forms.ProgressBar
$bar.Style = [Windows.Forms.ProgressBarStyle]::Marquee   # no measurable fraction exists: never a fake percentage
$bar.MarqueeAnimationSpeed = 30
$bar.Location = New-Object Drawing.Point(20, 216)
$bar.Size = New-Object Drawing.Size(440, 14)
$form.Controls.Add($bar)

$details = New-Object Windows.Forms.TextBox
$details.Multiline = $true
$details.ReadOnly = $true
$details.ScrollBars = 'Vertical'
$details.Location = New-Object Drawing.Point(20, 238)
$details.Size = New-Object Drawing.Size(440, 0)
$details.Visible = $false
$details.AccessibleName = 'Startup details'
$form.Controls.Add($details)

function New-Button([string]$Text, [int]$X) {
    $b = New-Object Windows.Forms.Button
    $b.Text = $Text
    $b.Location = New-Object Drawing.Point($X, 290)
    $b.Size = New-Object Drawing.Size(108, 28)
    $form.Controls.Add($b)
    return $b
}
$btnDetails = New-Button '&Show details' 20
$btnConsole = New-Button 'Show &console' 136
$btnRetry = New-Button '&Retry' 252
$btnClose = New-Button 'C&lose' 368
$btnConsole.Visible = $false
$btnRetry.Enabled = $false
$form.CancelButton = $btnClose

# ------------------------------------------------------------------ attempt state
$script:Mode = 'running'        # running | done | failed
$script:ExitCode = 0
$script:Events = New-Object System.Collections.ArrayList
$script:Console = $null
$script:BootPid = 0
$script:BootProc = $null
$script:Offset = [int64]0
$script:OpenComplete = $false
$script:OpenAt = $null
$script:HealthOk = $false
$script:HealthReq = $null
$script:HealthAr = $null
$script:HealthAt = $null
$script:LastEventAt = Get-Date
$script:TerminalAt = $null
$script:FailReason = ''

function Set-Row([string]$Id, [string]$State, [string]$Text, $Color) {
    $r = $rows[$Id]
    if (-not $r) { return }
    if ($r.State -ne $State) { $r.Since = Get-Date }
    $r.State = $State
    $r.Label.Text = $Text
    $r.Label.ForeColor = $Color
}
function Update-Details {
    $lines = @()
    $lines += ('Attempt started: ' + $script:AttemptStart.ToString('yyyy-MM-dd HH:mm:ss'))
    foreach ($e in $script:Events) { $lines += ($e.Time + '  ' + $e.Stage + '  ' + $e.State + '  ' + $e.Message) }
    if ($script:FailReason) { $lines += ('Result: ' + $script:FailReason) }
    if ($script:BootProc -and $script:BootProc.HasExited) { try { $lines += ('Startup script exit code: ' + $script:BootProc.ExitCode) } catch { } }
    $lines += ''
    $lines += 'Full output: "Show console" brings up the LotRadar Server window of this attempt.'
    $details.Text = ($lines -join "`r`n")
}
function Start-Attempt {
    $script:Nonce = New-Nonce
    $script:StatusPath = Join-Path $runtimeDir ('startup-status-' + $script:Nonce + '.jsonl')
    $script:Offset = [int64]0
    $script:Events.Clear()
    $script:BootPid = 0; $script:BootProc = $null
    $script:OpenComplete = $false; $script:OpenAt = $null; $script:HealthOk = $false; $script:HealthReq = $null
    $script:Mode = 'running'; $script:FailReason = ''; $script:TerminalAt = $null
    $script:AttemptStart = Get-Date; $script:LastEventAt = Get-Date
    foreach ($st in $Stages) { Set-Row $st.Id 'waiting' 'Waiting' ([Drawing.Color]::Gray) }
    $title.Text = 'Starting LotRadar'
    $status.ForeColor = [Drawing.SystemColors]::ControlText
    $status.Text = 'Starting...'
    $bar.Style = [Windows.Forms.ProgressBarStyle]::Marquee
    $btnRetry.Enabled = $false
    # The child runs the SAME launcher on its console path; the nonce enables stage reporting.
    $env:LOTRADAR_STARTUP_GUI = '0'
    $env:LOTRADAR_STARTUP_NONCE = $script:Nonce
    Remove-Item Env:\LOTRADAR_NO_PAUSE -ErrorAction SilentlyContinue   # keep the failure output on screen for "Show console"
    $cmdLine = 'cmd.exe /d /c ""' + $launcher + '""'
    $conhost = Join-Path $env:SystemRoot 'System32\conhost.exe'
    if (Test-Path -LiteralPath $conhost -PathType Leaf) {
        # classic console window: predictable minimize/restore (not handed to another terminal app)
        $script:Console = Start-Process -FilePath $conhost -ArgumentList $cmdLine -WorkingDirectory $programDir -WindowStyle Minimized -PassThru
    } else {
        $script:Console = Start-Process -FilePath 'cmd.exe' -ArgumentList ('/d /c ""' + $launcher + '""') -WorkingDirectory $programDir -WindowStyle Minimized -PassThru
    }
    $null = $script:Console.Handle   # PS 5.1: keep the handle so HasExited/ExitCode stay readable
    Update-Details
}
function Read-NewEvents {
    if (-not (Test-Path -LiteralPath $script:StatusPath -PathType Leaf)) { return }
    $fs = $null
    try {
        $fs = New-Object IO.FileStream($script:StatusPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
        if ($fs.Length -le $script:Offset) { return }
        if ($fs.Length - $script:Offset -gt 1MB) { return }   # not ours / runaway: ignore
        [void]$fs.Seek($script:Offset, [IO.SeekOrigin]::Begin)
        $buf = New-Object byte[] ([int]($fs.Length - $script:Offset))
        $n = $fs.Read($buf, 0, $buf.Length)
        $text = $utf8.GetString($buf, 0, $n)
        $last = $text.LastIndexOf("`n")
        if ($last -lt 0) { return }                              # only an incomplete line so far
        $script:Offset += $utf8.GetByteCount($text.Substring(0, $last + 1))
        foreach ($line in $text.Substring(0, $last).Split("`n")) {
            if (-not $line.Trim()) { continue }
            try { $e = $line | ConvertFrom-Json } catch { continue }
            if ([string]$e.nonce -ne $script:Nonce) { continue }
            $stage = [string]$e.stage
            $state = [string]$e.state
            if (@($Stages | Where-Object { $_.Id -eq $stage }).Count -eq 0 -or $States -notcontains $state) { continue }
            $evPid = 0
            [void][int]::TryParse([string]$e.pid, [ref]$evPid)
            if ($script:BootPid -eq 0 -and $evPid -gt 0) {
                $script:BootPid = $evPid
                try { $script:BootProc = Get-Process -Id $evPid -ErrorAction Stop; $null = $script:BootProc.Handle } catch { $script:BootProc = $null }
            }
            Invoke-Event $stage $state (Protect-Message ([string]$e.message))
        }
    } catch { } finally { if ($fs) { $fs.Dispose() } }
}
function Invoke-Event([string]$Stage, [string]$State, [string]$Message) {
    $script:LastEventAt = Get-Date
    [void]$script:Events.Add([pscustomobject]@{ Time = (Get-Date).ToString('HH:mm:ss'); Stage = $Stage; State = $State; Message = $Message })
    if ($script:Mode -ne 'running') { return }
    $idx = 0
    for ($i = 0; $i -lt $Stages.Count; $i++) { if ($Stages[$i].Id -eq $Stage) { $idx = $i } }
    if ($State -eq 'started' -or $State -eq 'info') {
        # earlier steps are finished; steps that never ran were not needed (e.g. LotRadar was already running)
        for ($i = 0; $i -lt $idx; $i++) {
            $r = $rows[$Stages[$i].Id]
            if ($r.State -eq 'active') { Set-Row $Stages[$i].Id 'done' 'Done' ([Drawing.Color]::ForestGreen) }
            elseif ($r.State -eq 'waiting') { Set-Row $Stages[$i].Id 'skipped' 'Not needed' ([Drawing.Color]::Gray) }
        }
        if ($rows[$Stage].State -ne 'active') { Set-Row $Stage 'active' 'In progress' ([Drawing.Color]::RoyalBlue) }
        $status.Text = $Message
    } elseif ($State -eq 'complete') {
        Set-Row $Stage 'done' 'Done' ([Drawing.Color]::ForestGreen)
        if ($Stage -eq 'open') { $script:OpenComplete = $true; $script:OpenAt = Get-Date; $status.Text = 'Checking that LotRadar answers...' }
    } elseif ($State -eq 'failed') {
        Set-Failed $Stage $Message
    }
    Update-Details
}
function Test-InstallerActive {
    # The installer holds lotradar-install.lock (no sharing) while it runs; a momentary shared open tells us.
    $p = Join-Path $runtimeDir 'lotradar-install.lock'
    if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { return $false }
    try { $f = [IO.File]::Open($p, 'Open', 'Read', 'ReadWrite'); $f.Dispose(); return $false } catch { return $true }
}
function Set-Failed([string]$Stage, [string]$Message) {
    if ($script:Mode -ne 'running') { return }
    if ($Message -like '*already starting in another window*' -and (Test-InstallerActive)) {
        $Message = 'LotRadar is being installed or updated right now. Wait for the installer to finish, then press Retry.'
    }
    $script:Mode = 'failed'
    $script:ExitCode = 91
    $script:FailReason = $Message
    $script:TerminalAt = Get-Date
    if (-not $Stage) { foreach ($st in $Stages) { if ($rows[$st.Id].State -eq 'active') { $Stage = $st.Id } } }
    if ($Stage) { Set-Row $Stage 'failed' 'Failed' ([Drawing.Color]::Firebrick) }
    $title.Text = 'LotRadar could not start'
    $status.ForeColor = [Drawing.Color]::Firebrick
    $status.Text = $Message
    $bar.Style = [Windows.Forms.ProgressBarStyle]::Blocks
    $bar.Value = 0
    $btnRetry.Enabled = $true
    $btnConsole.Visible = $true
    Update-Details
}
function Set-Done {
    $script:Mode = 'done'
    $script:ExitCode = 0
    $script:TerminalAt = Get-Date
    foreach ($st in $Stages) { if ($rows[$st.Id].State -eq 'active') { Set-Row $st.Id 'done' 'Done' ([Drawing.Color]::ForestGreen) } }
    $title.Text = 'LotRadar is open'
    $status.Text = 'LotRadar is running. Its server window stays in the taskbar; closing that window stops LotRadar.'
    $bar.Style = [Windows.Forms.ProgressBarStyle]::Blocks
    $bar.Value = $bar.Maximum
    Update-Details
}
function Update-Health {
    # Non-blocking: start a request, then only look at it on later ticks.
    if ($script:HealthReq) {
        if ($script:HealthAr.IsCompleted) {
            $resp = $null
            try {
                $resp = $script:HealthReq.EndGetResponse($script:HealthAr)
                $reader = New-Object IO.StreamReader($resp.GetResponseStream())
                $h = $reader.ReadToEnd() | ConvertFrom-Json
                if ($h.ok -eq $true -and $h.local_only -eq $true -and $h.service -eq 'Marketplace Scanner') { $script:HealthOk = $true }
            } catch { } finally { if ($resp) { $resp.Close() } }
            $script:HealthReq = $null
        } elseif (((Get-Date) - $script:HealthAt).TotalSeconds -gt 3) {
            try { $script:HealthReq.Abort() } catch { }
            $script:HealthReq = $null
        }
        return
    }
    $req = [Net.HttpWebRequest]::Create('http://127.0.0.1:8765/api/health')
    $req.Proxy = $null
    $req.Timeout = 3000
    $script:HealthReq = $req
    $script:HealthAt = Get-Date
    $script:HealthAr = $req.BeginGetResponse($null, $null)
}
function Test-ProcessExited($p) {
    if (-not $p) { return $true }
    try { return $p.HasExited } catch { return $true }
}
function Close-FailedConsole {
    # Only after the failed attempt's bootstrap has EXITED: then the console holds nothing (no lock, no server).
    if (-not $script:Console -or (Test-ProcessExited $script:Console)) { return $true }
    if ($script:BootPid -gt 0 -and -not (Test-ProcessExited $script:BootProc)) { return $false }
    if ($script:BootPid -eq 0) {
        # no event ever arrived: refuse to close a console that still runs PowerShell or Python
        $kids = @(Get-CimInstance Win32_Process -Filter ('ParentProcessId=' + $script:Console.Id) -ErrorAction SilentlyContinue)
        foreach ($k in @($kids)) {
            $kids += @(Get-CimInstance Win32_Process -Filter ('ParentProcessId=' + $k.ProcessId) -ErrorAction SilentlyContinue)
        }
        if (@($kids | Where-Object { $_.Name -ieq 'powershell.exe' -or $_.Name -ieq 'python.exe' -or $_.Name -ieq 'pythonw.exe' }).Count -gt 0) { return $false }
    }
    $ErrorActionPreference = 'Continue'
    & taskkill.exe /PID $script:Console.Id /T /F 2>&1 | Out-Null
    return $true
}
function Show-ConsoleWindow {
    if (-not $native -or -not $script:Console -or (Test-ProcessExited $script:Console)) { return }
    try {
        $script:Console.Refresh()
        $h = $script:Console.MainWindowHandle
        if ($h -ne [IntPtr]::Zero) { [void][LotRadarStartup.Native]::ShowWindow($h, 9); [void][LotRadarStartup.Native]::SetForegroundWindow($h) }
    } catch { }
}

# ------------------------------------------------------------------ events (all on the UI thread)
$timer = New-Object Windows.Forms.Timer
$timer.Interval = 300
$timer.Add_Tick({
    try {
        Read-NewEvents
        $now = Get-Date
        if ($script:Mode -eq 'running') {
            foreach ($st in $Stages) {
                $r = $rows[$st.Id]
                if ($r.State -eq 'active' -and $r.Since) { $r.Label.Text = 'In progress (' + (Format-Elapsed ($now - $r.Since)) + ')' }
            }
            if ($script:OpenComplete) {
                Update-Health
                if ($script:HealthOk) { Set-Done }
                elseif (($now - $script:OpenAt).TotalSeconds -gt 15) { Set-Failed 'open' 'LotRadar reported that it opened, but its local server did not answer. Show console for details.' }
            } elseif ((Test-ProcessExited $script:BootProc) -and $script:BootPid -gt 0) {
                Read-NewEvents
                if ($script:Mode -eq 'running' -and -not $script:OpenComplete) { Set-Failed '' 'The startup script stopped before LotRadar was ready. Show console for the full output.' }
            } elseif ($script:BootPid -eq 0 -and (Test-ProcessExited $script:Console)) {
                Read-NewEvents
                if ($script:Mode -eq 'running' -and $script:BootPid -eq 0) { Set-Failed 'install' 'The startup window of this attempt closed before LotRadar reported any progress.' }
            } elseif (($now - $script:LastEventAt).TotalMinutes -ge 10) {
                $status.Text = 'Still working (no new step for ' + (Format-Elapsed ($now - $script:LastEventAt)) + '). Downloads can be slow; Show console to watch it.'
            }
        }
        if ($AutoCloseSeconds -gt 0 -and $script:TerminalAt -and (($now - $script:TerminalAt).TotalSeconds -ge $AutoCloseSeconds)) { $form.Close() }
        elseif ($AutoCloseSeconds -le 0 -and $script:Mode -eq 'done' -and (($now - $script:TerminalAt).TotalSeconds -ge 3)) { $form.Close() }
    } catch { $script:LastTickError = $_.Exception.Message }
})
$btnDetails.Add_Click({
    $details.Visible = -not $details.Visible
    if ($details.Visible) {
        Update-Details
        $details.Height = 120
        $form.ClientSize = New-Object Drawing.Size(480, 460)
        foreach ($b in @($btnDetails, $btnConsole, $btnRetry, $btnClose)) { $b.Top = 420 }
        $btnDetails.Text = 'Hide &details'
        $btnConsole.Visible = $true
    } else {
        $form.ClientSize = New-Object Drawing.Size(480, 330)
        foreach ($b in @($btnDetails, $btnConsole, $btnRetry, $btnClose)) { $b.Top = 290 }
        $btnDetails.Text = '&Show details'
        $btnConsole.Visible = ($script:Mode -eq 'failed')
    }
})
$btnConsole.Add_Click({ Show-ConsoleWindow })
$btnRetry.Add_Click({
    if ($script:Mode -ne 'failed') { return }
    if (-not (Close-FailedConsole)) {
        $status.Text = 'The previous attempt is still finishing. Close its console window (taskbar), then press Retry.'
        return
    }
    if ($script:StatusPath) { Remove-Item -LiteralPath $script:StatusPath -Force -ErrorAction SilentlyContinue }
    try { Start-Attempt } catch { $script:Mode = 'running'; Set-Failed 'install' ('Could not start the LotRadar startup script: ' + (Protect-Message $_.Exception.Message)) }
})
$btnClose.Add_Click({ $form.Close() })
$form.Add_FormClosing({
    $timer.Stop()
    if ($script:Mode -eq 'running') {
        # Setup continues: never stop anything. Make its console visible so progress is not hidden.
        $script:ExitCode = 0
        Show-ConsoleWindow
    } elseif ($script:Mode -eq 'failed') {
        $script:ExitCode = 91
        if (Close-FailedConsole) {
            if ($script:StatusPath) { Remove-Item -LiteralPath $script:StatusPath -Force -ErrorAction SilentlyContinue }
        }
    } else {
        $script:ExitCode = 0
        if ($script:StatusPath) { Remove-Item -LiteralPath $script:StatusPath -Force -ErrorAction SilentlyContinue }
    }
})
$form.Add_Shown({
    $form.Activate()
    try { Start-Attempt } catch { Set-Failed 'install' ('Could not start the LotRadar startup script: ' + (Protect-Message $_.Exception.Message)) }
    $timer.Start()
})

try {
    [Windows.Forms.Application]::Run($form)
} catch {
    # Unexpected window error: never leave startup invisible. If an attempt is running, its console takes over;
    # otherwise hand back to the launcher's console start.
    if ($script:Console -and -not (Test-ProcessExited $script:Console)) { Show-ConsoleWindow; $script:ExitCode = 0 }
    else {
        if ($ownConsole -ne [IntPtr]::Zero) { try { [void][LotRadarStartup.Native]::ShowWindow($ownConsole, 5) } catch { } }
        $script:ExitCode = 90
    }
} finally {
    try { $mutex.ReleaseMutex() } catch { }
    $mutex.Dispose()
    if ($ResultFile) {
        try {
            $evList = @($script:Events | ForEach-Object { $_.Stage + ':' + $_.State })
            [IO.File]::WriteAllText($ResultFile, (@{ exit = $script:ExitCode; mode = $script:Mode; reason = $script:FailReason; events = $evList; health = $script:HealthOk; tick_error = [string]$script:LastTickError } | ConvertTo-Json -Compress), $utf8)
        } catch { }
    }
}
exit $script:ExitCode
