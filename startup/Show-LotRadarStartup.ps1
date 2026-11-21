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
  -Preview           (manual UI QA only): the SAME window driven by built-in example steps. Nothing is started,
                     no file or folder is written, no lock or port is touched. First run shows an example failure,
                     Retry shows an example success.
#>
[CmdletBinding()]
param([int]$AutoCloseSeconds = 0, [string]$ResultFile = '', [switch]$Preview)
$ErrorActionPreference = 'Stop'

$programDir = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $programDir 'Launch Marketplace Scanner.cmd'
if ($env:LOTRADAR_STARTUP_GUI_TEST_UNAVAILABLE -eq '1') { exit 90 }   # test hook: simulate "no window possible"
if (-not [Environment]::UserInteractive) { exit 90 }
if (-not $Preview -and -not (Test-Path -LiteralPath $launcher -PathType Leaf)) { exit 90 }
if (-not $Preview -and -not $env:LOCALAPPDATA) { exit 90 }   # the console start reports this problem itself

# The window must not create anything through a link: same rule as the installer. Otherwise use the console start.
$userRoot = ''; $runtimeDir = ''
if (-not $Preview) {
    $userRoot = Join-Path $env:LOCALAPPDATA 'MarketplaceScanner'
    $runtimeDir = Join-Path $userRoot 'runtime'
}
foreach ($p in @(@($userRoot, $runtimeDir) | Where-Object { $_ })) {
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
    [DllImport("kernel32.dll", SetLastError = true)] public static extern bool AttachConsole(uint pid);
    [DllImport("kernel32.dll")] public static extern bool FreeConsole();
    [DllImport("dwmapi.dll")] public static extern int DwmSetWindowAttribute(IntPtr h, int attr, ref int value, int size);
  }
}
'@
$native = $true
try { if (-not ('LotRadarStartup.Native' -as [type])) { Add-Type -TypeDefinition $nativeSource } } catch { $native = $false }

# One startup window at a time (a second double-click while this one is open just says so).
$mutexName = 'Local\LotRadarStartupWindow'
if ($Preview) { $mutexName = 'Local\LotRadarStartupPreview' }
$mutex = New-Object System.Threading.Mutex($false, $mutexName)
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
# The four steps the person sees (Owner decision, docs/startup/VISUAL_DESIGN_APPROVAL.md). Each is derived from the five
# real bootstrap stages above: LOADING MODULES is done only when BOTH python and browser are done, and LAUNCHING
# LOTRADAR is done only after open:complete AND this window's own healthy /api/health (Set-Done).
$Steps = @(
    @{ Id = 'system'; Label = 'SYSTEM CHECK'; Parts = @('install') },
    @{ Id = 'modules'; Label = 'LOADING MODULES'; Parts = @('python', 'browser') },
    @{ Id = 'server'; Label = 'STARTING SERVER'; Parts = @('server') },
    @{ Id = 'launch'; Label = 'LAUNCHING LOTRADAR'; Parts = @('open') }
)

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
if (-not $Preview) { try {
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
} }

# ------------------------------------------------------------------ window
[Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object Windows.Forms.Form
$form.Text = 'LotRadar'
if ($Preview) { $form.Text = 'LotRadar - PREVIEW (example steps, nothing is started)' }
# Layout is written in 96-dpi units and scaled here by the real display scale (Windows 11 preview at 150%:
# fonts grew with the DPI but positions/sizes did not, so text and buttons were cut off). WinForms' own
# AutoScale is off so nothing is scaled twice; fonts are in points and follow the DPI by themselves.
$form.AutoScaleMode = [Windows.Forms.AutoScaleMode]::None
$script:Scale = 1.0
try { $gs = [Drawing.Graphics]::FromHwnd([IntPtr]::Zero); $script:Scale = [math]::Max(1.0, $gs.DpiX / 96.0); $gs.Dispose() } catch { $script:Scale = 1.0 }
# NOTE: names must not collide with built-in aliases - an alias wins over a function in PowerShell. 'Sc' is
# Set-Content: in 2c0cac1 every layout call became Set-Content, which waited invisibly for input (window never opened).
function ScalePx([int]$v) { return [int][math]::Round($v * $script:Scale) }
function ScalePoint([int]$x, [int]$y) { return (New-Object Drawing.Point((ScalePx $x), (ScalePx $y))) }
function ScaleSize([int]$w, [int]$h) { return (New-Object Drawing.Size((ScalePx $w), (ScalePx $h))) }
function Set-DoubleBuffered($Control) {
    # DoubleBuffered is protected in WinForms; without it the glow and the animated bar flicker.
    try { [Windows.Forms.Control].GetProperty('DoubleBuffered', [Reflection.BindingFlags]'NonPublic,Instance').SetValue($Control, $true, $null) } catch { }
}
# Colours: dark window, steel-blue trim, blue bar. Windows high-contrast themes get the system colours instead.
$script:HighContrast = [Windows.Forms.SystemInformation]::HighContrast
function Get-Rgb([int]$R, [int]$G, [int]$B) { return [Drawing.Color]::FromArgb($R, $G, $B) }
if ($script:HighContrast) {
    $Pal = @{ Back = [Drawing.SystemColors]::Window; Text = [Drawing.SystemColors]::WindowText; Muted = [Drawing.SystemColors]::WindowText
        Trim = [Drawing.SystemColors]::WindowText; Glow = [Drawing.SystemColors]::Window; Track = [Drawing.SystemColors]::Window
        Bar = [Drawing.SystemColors]::Highlight; BarHi = [Drawing.SystemColors]::Highlight; Pending = [Drawing.SystemColors]::GrayText
        Active = [Drawing.SystemColors]::Highlight; Done = [Drawing.SystemColors]::WindowText; Failed = [Drawing.SystemColors]::WindowText
        Button = [Drawing.SystemColors]::Control; ButtonText = [Drawing.SystemColors]::ControlText; Box = [Drawing.SystemColors]::Window }
} else {
    $Pal = @{ Back = (Get-Rgb 17 19 23); Text = (Get-Rgb 232 235 240); Muted = (Get-Rgb 160 168 180)
        Trim = (Get-Rgb 58 96 140); Glow = (Get-Rgb 60 130 210); Track = (Get-Rgb 36 41 51)
        Bar = (Get-Rgb 30 110 230); BarHi = (Get-Rgb 110 175 255); Pending = (Get-Rgb 112 119 131)
        Active = (Get-Rgb 96 165 255); Done = (Get-Rgb 92 196 120); Failed = (Get-Rgb 240 96 96)
        Button = (Get-Rgb 34 38 47); ButtonText = (Get-Rgb 232 235 240); Box = (Get-Rgb 24 27 33) }
}
$form.Font = New-Object Drawing.Font('Segoe UI', 9)
$form.FormBorderStyle = [Windows.Forms.FormBorderStyle]::FixedSingle
$form.MaximizeBox = $false
$form.StartPosition = [Windows.Forms.FormStartPosition]::CenterScreen
$form.BackColor = $Pal.Back
$form.ForeColor = $Pal.Text
Set-DoubleBuffered $form
# Layout (96-dpi units): logo 120 at the top, status, bar, four steps, buttons. Details open below the steps.
$LayoutW = 560; $LayoutH = 384; $ButtonsY = 340; $DetailsH = 100
$form.ClientSize = (ScaleSize $LayoutW $LayoutH)
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
$script:HasLogo = [bool]$brand
if (-not $brand) {
    # Development package without the private logo: a plain code-drawn mark (no image, no wordmark).
    $brand = New-Object Windows.Forms.Label
    $brand.Text = 'LR'
    $brand.Font = New-Object Drawing.Font('Segoe UI', 26, [Drawing.FontStyle]::Bold)
    $brand.TextAlign = [Drawing.ContentAlignment]::MiddleCenter
    $brand.ForeColor = $Pal.Text
}
$brand.BackColor = [Drawing.Color]::Transparent   # the glow painted on the form shows around the logo
$LogoSize = 120; $LogoX = [int](($LayoutW - $LogoSize) / 2); $LogoY = 16
$brand.Location = (ScalePoint $LogoX $LogoY)
$brand.Size = (ScaleSize $LogoSize $LogoSize)
$brand.AccessibleName = 'LotRadar'
$form.Controls.Add($brand)

# Restrained steel-blue trim and a soft blue glow behind the logo, drawn in code (no background image).
$form.Add_Paint({
    param($s, $e)
    $g = $e.Graphics
    $g.SmoothingMode = [Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $cw = $s.ClientSize.Width; $ch = $s.ClientSize.Height
    if (-not $script:HighContrast) {
        $cx = ScalePx ($LogoX + $LogoSize / 2); $cy = ScalePx ($LogoY + $LogoSize / 2)
        for ($i = 10; $i -ge 1; $i--) {
            $rad = ScalePx (($LogoSize / 2) + 4 + $i * 3)
            $br = New-Object Drawing.SolidBrush([Drawing.Color]::FromArgb(7, $Pal.Glow))
            $g.FillEllipse($br, ($cx - $rad), ($cy - $rad), (2 * $rad), (2 * $rad)); $br.Dispose()
        }
    }
    if (-not $script:HasLogo) {
        $pen = New-Object Drawing.Pen($Pal.Trim, (ScalePx 3))
        $g.DrawEllipse($pen, (ScalePx ($LogoX + 6)), (ScalePx ($LogoY + 6)), (ScalePx ($LogoSize - 12)), (ScalePx ($LogoSize - 12))); $pen.Dispose()
    }
    $top = New-Object Drawing.SolidBrush($Pal.Trim)
    $g.FillRectangle($top, 0, 0, $cw, (ScalePx 3)); $top.Dispose()
    $edge = New-Object Drawing.Pen($Pal.Trim, 1)
    $g.DrawRectangle($edge, 0, 0, ($cw - 1), ($ch - 1)); $edge.Dispose()
})

$title = New-Object Windows.Forms.Label
$title.Text = 'Initializing LotRadar'
$title.Font = New-Object Drawing.Font('Segoe UI', 12)
$title.TextAlign = [Drawing.ContentAlignment]::MiddleCenter
$title.Location = (ScalePoint 20 144)
$title.Size = (ScaleSize ($LayoutW - 40) 26)
$form.Controls.Add($title)

$status = New-Object Windows.Forms.Label
$status.Text = 'Preparing...'
$status.ForeColor = $Pal.Muted
$status.TextAlign = [Drawing.ContentAlignment]::TopCenter
$status.Location = (ScalePoint 40 172)
$status.Size = (ScaleSize ($LayoutW - 80) 48)
$form.Controls.Add($status)

# Blue indeterminate bar, painted here: the native ProgressBar follows the Windows theme (green) and cannot be made
# blue reliably. It only shows "working" (a moving segment), "complete" or "failed"; there is no measurable
# fraction, so it never shows an invented percentage.
$script:BarMode = 'run'      # run | done | failed
$script:BarPhase = 0
$bar = New-Object Windows.Forms.Panel
$bar.Location = (ScalePoint 40 228)
$bar.Size = (ScaleSize ($LayoutW - 80) 8)
$bar.AccessibleRole = [Windows.Forms.AccessibleRole]::ProgressBar
$bar.AccessibleName = 'Startup progress'
$bar.AccessibleDescription = 'Working'
Set-DoubleBuffered $bar
$bar.Add_Paint({
    param($s, $e)
    $g = $e.Graphics
    $w = $s.ClientSize.Width; $h = $s.ClientSize.Height
    $tb = New-Object Drawing.SolidBrush($Pal.Track); $g.FillRectangle($tb, 0, 0, $w, $h); $tb.Dispose()
    if ($script:BarMode -eq 'done') {
        $fb = New-Object Drawing.SolidBrush($Pal.Bar); $g.FillRectangle($fb, 0, 0, $w, $h); $fb.Dispose()
    } elseif ($script:BarMode -eq 'failed') {
        $fb = New-Object Drawing.SolidBrush($Pal.Failed); $g.FillRectangle($fb, 0, 0, $w, $h); $fb.Dispose()
    } else {
        $seg = [int]($w * 0.3)
        $x = ($script:BarPhase % ($w + $seg)) - $seg
        $rect = New-Object Drawing.Rectangle($x, 0, $seg, $h)
        $lb = New-Object Drawing.Drawing2D.LinearGradientBrush($rect, $Pal.Bar, $Pal.BarHi, [Drawing.Drawing2D.LinearGradientMode]::Horizontal)
        $g.FillRectangle($lb, $rect); $lb.Dispose()
    }
    if ($script:HighContrast) { $p = New-Object Drawing.Pen($Pal.Text, 1); $g.DrawRectangle($p, 0, 0, ($w - 1), ($h - 1)); $p.Dispose() }
})
$form.Controls.Add($bar)
function Set-BarMode([string]$Mode) {
    $script:BarMode = $Mode
    $bar.AccessibleDescription = @{ run = 'Working'; done = 'Complete'; failed = 'Failed' }[$Mode]
    $bar.Invalidate()
}

# Real bootstrap stage states (waiting | active | done | skipped | failed) and the four visible steps built from them.
$rows = @{}
foreach ($st in $Stages) { $rows[$st.Id] = @{ State = 'waiting' } }
$view = @{}
$ColW = [int](($LayoutW - 40) / $Steps.Count)
for ($i = 0; $i -lt $Steps.Count; $i++) {
    $sp = $Steps[$i]
    $x = 20 + $i * $ColW
    $dot = New-Object Windows.Forms.Panel
    $dot.Location = (ScalePoint ($x + [int](($ColW - 14) / 2)) 248)
    $dot.Size = (ScaleSize 14 14)
    $dot.Tag = $sp.Id
    $dot.AccessibleRole = [Windows.Forms.AccessibleRole]::Graphic
    $dot.AccessibleName = $sp.Label
    Set-DoubleBuffered $dot
    $dot.Add_Paint({
        param($s, $e)
        $g = $e.Graphics
        $g.SmoothingMode = [Drawing.Drawing2D.SmoothingMode]::AntiAlias
        $st = $view[[string]$s.Tag].Shown
        $d = $s.ClientSize.Width - 2
        $col = @{ pending = $Pal.Pending; skipped = $Pal.Pending; active = $Pal.Active; done = $Pal.Done; failed = $Pal.Failed }[$st]
        if (-not $col) { $col = $Pal.Pending }
        $pw = [math]::Max(1, (ScalePx 2))
        if ($st -eq 'pending' -or $st -eq 'skipped') {
            $p = New-Object Drawing.Pen($col, $pw); $g.DrawEllipse($p, 1, 1, $d, $d)
            if ($st -eq 'skipped') { $g.DrawLine($p, [int]($d * 0.3), [int]($d / 2 + 1), [int]($d * 0.75), [int]($d / 2 + 1)) }
            $p.Dispose()
        } else {
            $b = New-Object Drawing.SolidBrush($col); $g.FillEllipse($b, 1, 1, $d, $d); $b.Dispose()
            $p = New-Object Drawing.Pen($Pal.Back, $pw)
            if ($st -eq 'done') { $g.DrawLines($p, [Drawing.PointF[]]@((New-Object Drawing.PointF(($d * 0.28), ($d * 0.52))), (New-Object Drawing.PointF(($d * 0.45), ($d * 0.7))), (New-Object Drawing.PointF(($d * 0.75), ($d * 0.35))))) }
            elseif ($st -eq 'failed') { $g.DrawLine($p, [int]($d * 0.32), [int]($d * 0.32), [int]($d * 0.72), [int]($d * 0.72)); $g.DrawLine($p, [int]($d * 0.72), [int]($d * 0.32), [int]($d * 0.32), [int]($d * 0.72)) }
            $p.Dispose()
        }
    })
    $name = New-Object Windows.Forms.Label
    $name.Text = $sp.Label
    $name.Font = New-Object Drawing.Font('Segoe UI', 8.25, [Drawing.FontStyle]::Bold)
    $name.TextAlign = [Drawing.ContentAlignment]::TopCenter
    $name.Location = (ScalePoint $x 266)
    $name.Size = (ScaleSize $ColW 32)
    $state = New-Object Windows.Forms.Label
    $state.Text = 'Waiting'
    $state.Font = New-Object Drawing.Font('Segoe UI', 8.25)
    $state.ForeColor = $Pal.Pending
    $state.TextAlign = [Drawing.ContentAlignment]::TopCenter
    $state.Location = (ScalePoint $x 298)
    $state.Size = (ScaleSize $ColW 32)
    $state.AccessibleName = $sp.Label
    $form.Controls.Add($dot); $form.Controls.Add($name); $form.Controls.Add($state)
    $view[$sp.Id] = @{ Dot = $dot; Label = $state; Shown = 'pending'; Since = $null; Step = $sp }
}

$details = New-Object Windows.Forms.TextBox
$details.Multiline = $true
$details.ReadOnly = $true
$details.ScrollBars = 'Vertical'
$details.BackColor = $Pal.Box
$details.ForeColor = $Pal.Text
$details.BorderStyle = [Windows.Forms.BorderStyle]::FixedSingle
$details.Location = (ScalePoint 20 $ButtonsY)
$details.Size = (ScaleSize ($LayoutW - 40) 0)
$details.Visible = $false
$details.AccessibleName = 'Startup details'
$form.Controls.Add($details)

function New-Button([string]$Text, [int]$X) {
    $b = New-Object Windows.Forms.Button
    $b.Text = $Text
    $b.Location = (ScalePoint $X $ButtonsY)
    $b.Size = (ScaleSize 116 30)
    $b.FlatStyle = [Windows.Forms.FlatStyle]::Flat
    $b.BackColor = $Pal.Button
    $b.ForeColor = $Pal.ButtonText
    $b.FlatAppearance.BorderColor = $Pal.Trim
    $b.UseVisualStyleBackColor = $false
    $form.Controls.Add($b)
    return $b
}
$btnDetails = New-Button '&Show details' 30
$btnConsole = New-Button 'Show &console' 158
$btnRetry = New-Button 'Retry (F5)' 286
$btnClose = New-Button 'C&lose' 414
$btnConsole.Visible = $false
$btnRetry.Enabled = $false
$form.CancelButton = $btnClose

$script:AttemptCount = 0
$script:RetryLog = New-Object System.Collections.ArrayList
$script:RetryVia = 'click'
$script:F5Down = $false
$form.Add_KeyDown({
    param($sender, $e)
    if ($e.KeyCode -ne [Windows.Forms.Keys]::F5 -or $e.Modifiers -ne [Windows.Forms.Keys]::None) { return }
    $e.Handled = $true
    $e.SuppressKeyPress = $true
    if ($script:F5Down) { [void]$script:RetryLog.Add('f5:repeat'); return }
    $script:F5Down = $true
    if ($script:Mode -ne 'failed' -or -not $btnRetry.Enabled -or -not $btnRetry.Visible) {
        [void]$script:RetryLog.Add('f5:not-eligible')
        return
    }
    $script:RetryVia = 'f5'
    try { $btnRetry.PerformClick() } finally { $script:RetryVia = 'click' }
})
$form.Add_KeyUp({
    param($sender, $e)
    if ($e.KeyCode -eq [Windows.Forms.Keys]::F5) { $script:F5Down = $false }
})
$form.Add_Deactivate({ $script:F5Down = $false })


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
$script:ConsoleShown = $false

function Set-Row([string]$Id, [string]$State) {
    # $State: waiting | active | done | skipped | failed (one real bootstrap stage)
    $r = $rows[$Id]
    if (-not $r) { return }
    $r.State = $State
    Update-StepView
}
function Get-StepState($Step) {
    # One visible step from its real stage(s). A step with one part done and another still waiting is in progress
    # (Python ready, browser runtime not checked yet), never done early.
    $parts = @($Step.Parts | ForEach-Object { $rows[$_].State })
    if ($parts -contains 'failed') { return 'failed' }
    if ($parts -contains 'active') { return 'active' }
    if (@($parts | Where-Object { $_ -eq 'waiting' }).Count -eq $parts.Count) { return 'pending' }
    if (@($parts | Where-Object { $_ -eq 'skipped' }).Count -eq $parts.Count) { return 'skipped' }
    if ($parts -contains 'waiting') { return 'active' }
    # LAUNCHING LOTRADAR: "window opened" alone is not success; done only after the health check (Set-Done).
    if ($Step.Id -eq 'launch' -and $script:Mode -ne 'done') { return 'active' }
    return 'done'
}
function Update-StepView {
    $now = Get-Date
    foreach ($sp in $Steps) {
        $v = $view[$sp.Id]
        $st = Get-StepState $sp
        if ($v.Shown -ne $st) { $v.Since = $now; $v.Shown = $st; $v.Dot.Invalidate() }
        switch ($st) {
            'pending' { $v.Label.Text = 'Waiting'; $v.Label.ForeColor = $Pal.Pending }
            'skipped' { $v.Label.Text = 'Not needed'; $v.Label.ForeColor = $Pal.Pending }
            'active' { $v.Label.Text = 'In progress (' + (Format-Elapsed ($now - $v.Since)) + ')'; $v.Label.ForeColor = $Pal.Active }
            'done' { $v.Label.Text = 'Done'; $v.Label.ForeColor = $Pal.Done }
            'failed' { $v.Label.Text = 'Failed'; $v.Label.ForeColor = $Pal.Failed }
        }
    }
}
function Get-StepSummary { return ((@($Steps | ForEach-Object { $_.Id + ':' + $view[$_.Id].Shown })) -join ',') }
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
    $script:AttemptCount++
    $script:Nonce = New-Nonce
    $script:StatusPath = Join-Path $runtimeDir ('startup-status-' + $script:Nonce + '.jsonl')
    $script:Offset = [int64]0
    $script:Events.Clear()
    $script:BootPid = 0; $script:BootProc = $null
    $script:OpenComplete = $false; $script:OpenAt = $null; $script:HealthOk = $false; $script:HealthReq = $null
    $script:Mode = 'running'; $script:FailReason = ''; $script:TerminalAt = $null
    $script:AttemptStart = Get-Date; $script:LastEventAt = Get-Date
    foreach ($st in $Stages) { Set-Row $st.Id 'waiting' }
    $title.Text = 'Initializing LotRadar'
    $status.ForeColor = $Pal.Muted
    $status.Text = 'Starting...'
    Set-BarMode 'run'
    $btnRetry.Enabled = $false
    # The child runs the SAME launcher on its console path; the nonce enables stage reporting.
    $env:LOTRADAR_STARTUP_GUI = '0'
    $env:LOTRADAR_STARTUP_NONCE = $script:Nonce
    Remove-Item Env:\LOTRADAR_NO_PAUSE -ErrorAction SilentlyContinue   # keep the failure output on screen for "Show console"
    # Plain cmd.exe in its own new console (Windows decides the console host, as for a normal double-click).
    # Windows 11 run of 05a17dd: launching conhost.exe directly never ran the launcher (no events at all).
    $comSpec = $env:ComSpec
    if (-not $comSpec -or -not (Test-Path -LiteralPath $comSpec -PathType Leaf)) { $comSpec = Join-Path $env:SystemRoot 'System32\cmd.exe' }
    $script:Console = Start-Process -FilePath $comSpec -ArgumentList ('/d /c ""' + $launcher + '""') -WorkingDirectory $programDir -WindowStyle Minimized -PassThru
    $null = $script:Console.Handle   # PS 5.1: keep the handle so HasExited/ExitCode stay readable
    Update-Details
}
# ---- preview: example steps only (first attempt fails, Retry succeeds). Nothing is started or written.
$script:PreviewRun = 0
$PreviewSteps = @(
    @('install', 'started', 'Checking installation'), @('install', 'complete', 'Installation found'),
    @('python', 'started', 'Checking Python and dependencies'), @('python', 'info', 'Downloading missing Python packages (example)'),
    @('python', 'complete', 'Python and packages ready'), @('browser', 'started', 'Checking browser runtime'),
    @('browser', 'info', 'Downloading the browser runtime (example)'),
    @('browser', 'complete', 'Browser runtime ready'), @('server', 'started', 'Starting the local LotRadar server'))
function Start-PreviewAttempt {
    $script:AttemptCount++
    $script:PreviewRun++
    $script:PreviewIdx = 0; $script:PreviewAt = Get-Date
    $script:Events.Clear()
    $script:Mode = 'running'; $script:FailReason = ''; $script:TerminalAt = $null
    $script:AttemptStart = Get-Date; $script:LastEventAt = Get-Date
    foreach ($st in $Stages) { Set-Row $st.Id 'waiting' }
    $title.Text = 'Initializing LotRadar'
    $status.ForeColor = $Pal.Muted
    $status.Text = 'Starting... (preview)'
    Set-BarMode 'run'
    $btnRetry.Enabled = $false
    Update-Details
}
function Step-Preview {
    if ($script:Mode -ne 'running' -or ((Get-Date) - $script:PreviewAt).TotalMilliseconds -lt 1200) { return }
    $script:PreviewAt = Get-Date
    if ($script:PreviewIdx -lt $PreviewSteps.Count) {
        $s = $PreviewSteps[$script:PreviewIdx]; $script:PreviewIdx++
        Invoke-Event $s[0] $s[1] $s[2]
    } elseif ($script:PreviewRun -le 1) {
        Invoke-Event 'server' 'failed' 'EXAMPLE: Port 8765 is in use. Close the application using it, then retry. (Preview: nothing was started.)'
    } elseif ($script:PreviewIdx -eq $PreviewSteps.Count) {
        $script:PreviewIdx++
        Invoke-Event 'open' 'started' 'LotRadar is running; opening its window'
    } else {
        Invoke-Event 'open' 'complete' 'LotRadar window opened'
        Set-Done
        $status.Text = 'Preview finished. Nothing was started. Close this window when you are done looking.'
    }
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
            if ($r.State -eq 'active') { Set-Row $Stages[$i].Id 'done' }
            elseif ($r.State -eq 'waiting') { Set-Row $Stages[$i].Id 'skipped' }
        }
        if ($rows[$Stage].State -ne 'active') { Set-Row $Stage 'active' }
        $status.Text = $Message   # the exact sub-step (e.g. Python packages vs browser runtime) is named here
    } elseif ($State -eq 'complete') {
        Set-Row $Stage 'done'
        if ($Message) { $status.Text = $Message }
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
    if ($Stage) { Set-Row $Stage 'failed' }
    $title.Text = 'LotRadar could not start'
    $status.ForeColor = $Pal.Failed
    $status.Text = $Message
    Set-BarMode 'failed'
    $btnRetry.Enabled = $true
    $btnConsole.Visible = $true
    Update-Details
}
function Set-Done {
    $script:Mode = 'done'
    $script:ExitCode = 0
    $script:TerminalAt = Get-Date
    foreach ($st in $Stages) { if ($rows[$st.Id].State -eq 'active') { Set-Row $st.Id 'done' } }
    Update-StepView   # LAUNCHING LOTRADAR becomes done only here (open:complete + healthy /api/health)
    $title.Text = 'LotRadar is open'
    $status.Text = 'LotRadar is running. Its server window stays in the taskbar; closing that window stops LotRadar.'
    Set-BarMode 'done'
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
function Get-ClippedText {
    # Automatic display check (tests and preview only, via ResultFile): every visible label/button text must fit
    # its control at the current scale. Returns short descriptions of the ones that do not.
    $out = @()
    foreach ($c in @($form.Controls)) {
        if (-not $c.Visible -or -not $c.Text -or -not ($c -is [Windows.Forms.Label] -or $c -is [Windows.Forms.Button])) { continue }
        if ($c -is [Windows.Forms.Button]) {
            $avail = $c.ClientSize.Width - (ScalePx 8)
            $m = [Windows.Forms.TextRenderer]::MeasureText($c.Text, $c.Font, (New-Object Drawing.Size([int]::MaxValue, [int]::MaxValue)), [Windows.Forms.TextFormatFlags]::SingleLine)
            if ($m.Width -gt $avail -or $m.Height -gt $c.ClientSize.Height) { $out += ('button "' + $c.Text.Replace('&', '') + '"') }
        } else {
            $flags = [Windows.Forms.TextFormatFlags]::WordBreak -bor [Windows.Forms.TextFormatFlags]::TextBoxControl
            $m = [Windows.Forms.TextRenderer]::MeasureText($c.Text, $c.Font, (New-Object Drawing.Size($c.ClientSize.Width, [int]::MaxValue)), $flags)
            if ($m.Height -gt $c.ClientSize.Height -or $m.Width -gt $c.ClientSize.Width) {
                $t = $c.Text; if ($t.Length -gt 24) { $t = $t.Substring(0, 24) + '...' }
                $out += ('label "' + $t + '"')
            }
        }
    }
    return $out
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
$script:ConsoleDiag = New-Object System.Collections.ArrayList   # why "Show console" did or did not work (ResultFile only)
function Show-ConsoleWindow {
    if (-not $native) { [void]$script:ConsoleDiag.Add('no-native'); return }
    if (-not $script:Console) { [void]$script:ConsoleDiag.Add('no-console'); return }
    if (Test-ProcessExited $script:Console) { [void]$script:ConsoleDiag.Add('console-exited'); return }
    # The console window belongs to the console host, not to cmd.exe: briefly attach to cmd's console to get it.
    try {
        [void][LotRadarStartup.Native]::FreeConsole()
        if ([LotRadarStartup.Native]::AttachConsole([uint32]$script:Console.Id)) {
            $h = [LotRadarStartup.Native]::GetConsoleWindow()
            [void][LotRadarStartup.Native]::FreeConsole()
            if ($h -ne [IntPtr]::Zero) { [void][LotRadarStartup.Native]::ShowWindow($h, 9); [void][LotRadarStartup.Native]::SetForegroundWindow($h); $script:ConsoleShown = $true; [void]$script:ConsoleDiag.Add('shown') }
            else { [void]$script:ConsoleDiag.Add('no-console-window') }
        } else { [void]$script:ConsoleDiag.Add('attach-failed:' + [Runtime.InteropServices.Marshal]::GetLastWin32Error()) }
    } catch { [void]$script:ConsoleDiag.Add('error:' + $_.Exception.GetType().Name) }
}

# ------------------------------------------------------------------ events (all on the UI thread)
$timer = New-Object Windows.Forms.Timer
$timer.Interval = 300
$timer.Add_Tick({
    try {
        if ($Preview) {
            Step-Preview
            if ($script:Mode -eq 'running') { Update-StepView }
            if ($AutoCloseSeconds -gt 0 -and $script:TerminalAt -and (((Get-Date) - $script:TerminalAt).TotalSeconds -ge $AutoCloseSeconds)) { $form.Close() }
            return
        }
        Read-NewEvents
        $now = Get-Date
        if ($script:Mode -eq 'running') {
            Update-StepView   # elapsed time of the step in progress
            if ($script:OpenComplete) {
                Update-Health
                if ($script:HealthOk) { Set-Done }
                elseif (($now - $script:OpenAt).TotalSeconds -gt 15) { Set-Failed 'open' 'LotRadar reported that it opened, but its local server did not answer. Show console for details.' }
            } elseif ((Test-ProcessExited $script:BootProc) -and $script:BootPid -gt 0) {
                Read-NewEvents
                if ($script:Mode -eq 'running' -and -not $script:OpenComplete) { Set-Failed '' 'The startup script stopped before LotRadar was ready. Show console for the full output.' }
            } elseif ($script:BootPid -eq 0 -and (Test-ProcessExited $script:Console)) {
                Read-NewEvents
                if ($script:Mode -eq 'running' -and $script:BootPid -eq 0) {
                    $code = '?'
                    try { $code = [string]$script:Console.ExitCode } catch { }
                    Set-Failed 'install' ('The startup window of this attempt closed before LotRadar reported any progress (exit code ' + $code + ').')
                }
            } elseif (($now - $script:LastEventAt).TotalMinutes -ge 10) {
                $status.Text = 'Still working (no new step for ' + (Format-Elapsed ($now - $script:LastEventAt)) + '). Downloads can be slow; Show console to watch it.'
            }
        }
        if ($AutoCloseSeconds -gt 0 -and $script:TerminalAt -and (($now - $script:TerminalAt).TotalSeconds -ge $AutoCloseSeconds)) { $form.Close() }
        elseif ($AutoCloseSeconds -le 0 -and $script:Mode -eq 'done' -and (($now - $script:TerminalAt).TotalSeconds -ge 3)) { $form.Close() }
    } catch { $script:LastTickError = $_.Exception.Message }
})
# Bar animation: only while working (a moving segment; no fraction is measured).
$anim = New-Object Windows.Forms.Timer
$anim.Interval = 40
$anim.Add_Tick({ if ($script:BarMode -eq 'run') { $script:BarPhase += (ScalePx 6); $bar.Invalidate() } })
$btnDetails.Add_Click({
    $details.Visible = -not $details.Visible
    if ($details.Visible) {
        Update-Details
        # Details open below the steps; on a short screen the box gets smaller so the buttons stay visible.
        $dh = $DetailsH; $wa = $null
        try {
            $wa = [Windows.Forms.Screen]::FromControl($form).WorkingArea
            $frame = $form.Height - $form.ClientSize.Height
            $room = [int][math]::Floor(($wa.Height - $frame) / $script:Scale) - $LayoutH - 10
            $dh = [math]::Max(40, [math]::Min($DetailsH, $room))
        } catch { }
        $details.Height = (ScalePx $dh)
        $form.ClientSize = (ScaleSize $LayoutW ($LayoutH + $dh + 10))
        foreach ($b in @($btnDetails, $btnConsole, $btnRetry, $btnClose)) { $b.Top = (ScalePx ($ButtonsY + $dh + 10)) }
        if ($wa -and $form.Bottom -gt $wa.Bottom) { $form.Top = [math]::Max($wa.Top, $wa.Bottom - $form.Height) }
        $btnDetails.Text = 'Hide &details'
        $btnConsole.Visible = $true
    } else {
        $form.ClientSize = (ScaleSize $LayoutW $LayoutH)
        foreach ($b in @($btnDetails, $btnConsole, $btnRetry, $btnClose)) { $b.Top = (ScalePx $ButtonsY) }
        $btnDetails.Text = '&Show details'
        $btnConsole.Visible = ($script:Mode -eq 'failed')
    }
    $form.Invalidate()
})
$btnConsole.Add_Click({
    if ($Preview) { $status.Text = 'Preview: there is no console window to show (nothing was started).'; return }
    [void]$script:ConsoleDiag.Add('click')
    Show-ConsoleWindow
})
$btnRetry.Add_Click({
    if ($script:Mode -ne 'failed') { [void]$script:RetryLog.Add($script:RetryVia + ':ignored'); return }
    if (-not (Close-FailedConsole)) {
        [void]$script:RetryLog.Add($script:RetryVia + ':finishing')
        $status.Text = 'The previous attempt is still finishing. Close its console window (taskbar), then press Retry.'
        return
    }
    [void]$script:RetryLog.Add($script:RetryVia + ':started')
    if ($Preview) { Start-PreviewAttempt; return }
    if ($script:StatusPath) { Remove-Item -LiteralPath $script:StatusPath -Force -ErrorAction SilentlyContinue }
    try { Start-Attempt } catch { $script:Mode = 'running'; Set-Failed 'install' ('Could not start the LotRadar startup script: ' + (Protect-Message $_.Exception.Message)) }
})
$btnClose.Add_Click({ $form.Close() })
$script:Clipped = 'not checked'
$script:StepsAtClose = ''
$form.Add_FormClosing({
    $timer.Stop(); $anim.Stop()
    # measured while the window still exists (after Run returns its controls are disposed)
    try { $script:Clipped = (@(Get-ClippedText) -join '; ') } catch { $script:Clipped = 'check failed: ' + $_.Exception.Message }
    try { $script:StepsAtClose = Get-StepSummary } catch { }
    if ($Preview) { $script:ExitCode = 0; return }   # preview: nothing was started, nothing to show or clean up
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
    # Dark title bar to match the window (Windows 10 2004+/11; ignored elsewhere). Not with high contrast.
    if ($native -and -not $script:HighContrast) { try { $on = 1; [void][LotRadarStartup.Native]::DwmSetWindowAttribute($form.Handle, 20, [ref]$on, 4) } catch { } }
    $form.Activate()
    $anim.Start()
    if ($Preview) { Start-PreviewAttempt; $timer.Start(); return }
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
            $consoleExit = $null
            try { if ($script:Console -and $script:Console.HasExited) { $consoleExit = $script:Console.ExitCode } } catch { }
            [IO.File]::WriteAllText($ResultFile, (@{ attempts = $script:AttemptCount; retry_log = (@($script:RetryLog) -join ','); exit = $script:ExitCode; mode = $script:Mode; reason = $script:FailReason; events = $evList; health = $script:HealthOk; tick_error = [string]$script:LastTickError; console_exit = $consoleExit; boot_pid = $script:BootPid; console_shown = [bool]$script:ConsoleShown; console_diag = (@($script:ConsoleDiag) -join ','); clipped = [string]$script:Clipped; scale = $script:Scale; steps = [string]$script:StepsAtClose; logo = [bool]$script:HasLogo } | ConvertTo-Json -Compress), $utf8)
        } catch { }
    }
}
exit $script:ExitCode
