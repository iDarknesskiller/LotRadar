# LotRadar startup window: automated REAL-INPUT acceptance of the preview window (LR-010, rows P-*). TEST-ONLY.
#
# Replaces the Owner pressing keys by hand (Owner direction 2026-11-21: "it doesnt need me").
# Unlike G10-G13 (window messages posted straight to the form), every key and click here goes through
# SendInput, the same system input queue a physical keyboard and mouse feed: focus, mnemonics, Tab order,
# key-repeat (sent as repeated key-downs, like keyboard auto-repeat) and foreground rules all apply.
# Focus is read back with UI Automation. Residual difference to a hardware keyboard: injected input carries
# the LLKHF_INJECTED flag, which the form does not look at.
#
# Safety: nothing is installed or started (the window runs with -Preview). Before EVERY key or click the
# script checks that the foreground window belongs to a process this script started; otherwise it sends
# nothing and stops (BLOCKED). Mouse clicks are only sent after WindowFromPoint confirms the point lies on
# a test window. Only processes this script started are stopped at the end. Do not use the keyboard or
# mouse while it runs (about 2 minutes).
#
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -File tests\windows\Test-StartupRealInput.ps1 [-Gui <path>] [-OutDir <dir>]
# Exit: 0 all PASS, 1 any FAIL, 2 BLOCKED/INCONCLUSIVE.
param([string]$Gui = '', [string]$OutDir = '')
$ErrorActionPreference = 'Stop'
if (-not $Gui) { $Gui = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'startup\Show-LotRadarStartup.ps1' }
if (-not (Test-Path -LiteralPath $Gui -PathType Leaf)) { Write-Host "startup window script not found: $Gui"; exit 2 }
if (-not $OutDir) { $OutDir = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) ('LotRadar QA Results\RealInput-' + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
$psExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

Add-Type -TypeDefinition @'
using System; using System.Runtime.InteropServices;
namespace LRInput {
public static class Native {
  [StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT { public int dx; public int dy; public uint mouseData; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
  [StructLayout(LayoutKind.Sequential)] public struct KEYBDINPUT { public ushort wVk; public ushort wScan; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
  [StructLayout(LayoutKind.Explicit)] public struct UNION { [FieldOffset(0)] public MOUSEINPUT mi; [FieldOffset(0)] public KEYBDINPUT ki; }
  [StructLayout(LayoutKind.Sequential)] public struct INPUT { public uint type; public UNION u; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll", SetLastError = true)] static extern uint SendInput(uint n, INPUT[] inputs, int size);
  [DllImport("user32.dll")] static extern uint MapVirtualKey(uint code, uint type);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern short GetAsyncKeyState(int vk);
  [DllImport("user32.dll")] static extern int GetSystemMetrics(int i);
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr v);
  [DllImport("user32.dll")] public static extern IntPtr WindowFromPoint(POINT p);
  [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h, uint flags);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  public static uint Key(ushort vk, bool up) {
    INPUT[] a = new INPUT[1]; a[0].type = 1; a[0].u.ki.wVk = vk; a[0].u.ki.wScan = (ushort)MapVirtualKey(vk, 0);
    a[0].u.ki.dwFlags = up ? 2u : 0u; return SendInput(1, a, Marshal.SizeOf(typeof(INPUT)));
  }
  public static uint Click(int x, int y) {
    int vx = GetSystemMetrics(76), vy = GetSystemMetrics(77), vw = GetSystemMetrics(78), vh = GetSystemMetrics(79);
    INPUT[] a = new INPUT[3];
    for (int i = 0; i < 3; i++) { a[i].type = 0; }
    a[0].u.mi.dx = (int)(((long)(x - vx) * 65535) / (vw - 1)); a[0].u.mi.dy = (int)(((long)(y - vy) * 65535) / (vh - 1));
    a[0].u.mi.dwFlags = 0x0001 | 0x8000 | 0x4000;
    a[1].u.mi.dwFlags = 0x0002; a[2].u.mi.dwFlags = 0x0004;
    return SendInput(3, a, Marshal.SizeOf(typeof(INPUT)));
  }
  [StructLayout(LayoutKind.Sequential)] public struct TITLEBARINFOEX { public int cbSize; public RECT rcTitleBar; [MarshalAs(UnmanagedType.ByValArray, SizeConst = 6)] public int[] rgstate; [MarshalAs(UnmanagedType.ByValArray, SizeConst = 6)] public RECT[] rgrect; }
  [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr h, uint msg, IntPtr w, ref TITLEBARINFOEX l);
  public static RECT CloseButtonRect(IntPtr h) {
    // WM_GETTITLEBARINFOEX: asks the window where its caption buttons are (index 5 = Close X). A query, not input.
    TITLEBARINFOEX t = new TITLEBARINFOEX(); t.rgstate = new int[6]; t.rgrect = new RECT[6]; t.cbSize = Marshal.SizeOf(typeof(TITLEBARINFOEX));
    SendMessage(h, 0x033F, IntPtr.Zero, ref t); return t.rgrect[5];
  }
  [DllImport("user32.dll")] static extern int GetWindowLong(IntPtr h, int i);
  public static bool IsReadOnlyEdit(IntPtr h) { return (GetWindowLong(h, -16) & 0x0800) != 0; }   // GWL_STYLE, ES_READONLY
  public static uint PidOf(IntPtr h) { uint p; GetWindowThreadProcessId(h, out p); return p; }
  public static uint PidAt(int x, int y) { POINT p; p.X = x; p.Y = y; return PidOf(GetAncestor(WindowFromPoint(p), 2)); }
}}
'@
[void][LRInput.Native]::SetProcessDpiAwarenessContext([IntPtr](-4))   # per-monitor: UIA rectangles = SendInput pixels
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Drawing
$AE = [Windows.Automation.AutomationElement]

$rowsFile = Join-Path $OutDir 'rows.jsonl'
$script:Rows = New-Object System.Collections.ArrayList
$script:Owned = New-Object System.Collections.ArrayList   # PIDs this script started (the only ones it may stop or type into)
function Add-Row([string]$Id, [string]$Status, [string]$Detail) {
    $row = [pscustomobject]@{ id = $Id; status = $Status; detail = $Detail; utc = (Get-Date).ToUniversalTime().ToString('o') }
    [void]$script:Rows.Add($row)
    Add-Content -LiteralPath $rowsFile -Value ($row | ConvertTo-Json -Compress) -Encoding UTF8   # saved at once (LR-010-07 lesson)
    $c = 'Green'; if ($Status -eq 'FAIL') { $c = 'Red' } elseif ($Status -ne 'PASS') { $c = 'Yellow' }
    Write-Host ("[$Status] $Id - $Detail") -ForegroundColor $c
}
class Blocked : Exception { Blocked([string]$m) : base($m) { } }

# ---------------------------------------------------------------- guarded input
function Assert-NoHeldModifiers { foreach ($vk in 0x10, 0x11, 0x12, 0x5B, 0x5C) { if ([LRInput.Native]::GetAsyncKeyState($vk) -band 0x8000) { throw [Blocked]::new('a modifier key is physically held down; no input sent') } } }
function Assert-OwnedForeground([int]$WantPid) {
    $fg = [int][LRInput.Native]::PidOf([LRInput.Native]::GetForegroundWindow())
    if ($fg -ne $WantPid) { throw [Blocked]::new("foreground window is not the intended test window (pid $fg, wanted $WantPid); no input sent") }
}
function Send-Keys([int]$WantPid, [int[]]$Down, [int]$HoldMs = 30) {
    # presses the keys in order, then releases them in reverse order
    Assert-NoHeldModifiers; Assert-OwnedForeground $WantPid
    foreach ($k in $Down) { [void][LRInput.Native]::Key([uint16]$k, $false); Start-Sleep -Milliseconds 15 }
    Start-Sleep -Milliseconds $HoldMs
    for ($i = $Down.Count - 1; $i -ge 0; $i--) { [void][LRInput.Native]::Key([uint16]$Down[$i], $true); Start-Sleep -Milliseconds 15 }
    Start-Sleep -Milliseconds 250
}
function Send-HeldKey([int]$WantPid, [int]$Vk, [int]$Repeats, [int]$IntervalMs) {
    # keyboard auto-repeat: one key-down, further key-downs while held, one key-up
    Assert-NoHeldModifiers; Assert-OwnedForeground $WantPid
    [void][LRInput.Native]::Key([uint16]$Vk, $false)
    for ($i = 0; $i -lt $Repeats; $i++) { Start-Sleep -Milliseconds $IntervalMs; Assert-OwnedForeground $WantPid; [void][LRInput.Native]::Key([uint16]$Vk, $false) }
    [void][LRInput.Native]::Key([uint16]$Vk, $true)
    Start-Sleep -Milliseconds 250
}
function Get-Center($el) {
    if ($el -is [array]) { return $el }   # already an @(x, y) point
    $r = $el.Current.BoundingRectangle; return @([int]($r.X + $r.Width / 2), [int]($r.Y + $r.Height / 2))
}
function Send-Click([int]$WantPid, $el) {
    Assert-NoHeldModifiers
    $xy = Get-Center $el
    $at = [int][LRInput.Native]::PidAt($xy[0], $xy[1])
    if ($at -ne $WantPid) { throw [Blocked]::new("the click point is covered by another window (pid $at); no click sent") }
    [void][LRInput.Native]::Click($xy[0], $xy[1])
    Start-Sleep -Milliseconds 400
}
function Set-OwnedForeground([IntPtr]$Hwnd, [int]$WantPid, $ClickTarget) {
    for ($i = 0; $i -lt 3; $i++) {
        if ([int][LRInput.Native]::PidOf([LRInput.Native]::GetForegroundWindow()) -eq $WantPid) { return 'already/SetForegroundWindow' }
        [void][LRInput.Native]::SetForegroundWindow($Hwnd); Start-Sleep -Milliseconds 400
    }
    if ([int][LRInput.Native]::PidOf([LRInput.Native]::GetForegroundWindow()) -eq $WantPid) { return 'SetForegroundWindow' }
    if ($ClickTarget) { Send-Click $WantPid $ClickTarget; if ([int][LRInput.Native]::PidOf([LRInput.Native]::GetForegroundWindow()) -eq $WantPid) { return 'click' } }
    throw [Blocked]::new('could not bring the test window to the front; no input sent')
}

# ---------------------------------------------------------------- UI Automation reads
function Get-Kids($win) { return @($win.FindAll([Windows.Automation.TreeScope]::Children, [Windows.Automation.Condition]::TrueCondition)) }
function Find-Kid($win, [string]$Pattern) { return @(Get-Kids $win | Where-Object { $_.Current.Name -like $Pattern -and -not $_.Current.IsOffscreen }) | Select-Object -First 1 }
function Find-Details($win) { return @(Get-Kids $win | Where-Object { $_.Current.ClassName -like '*EDIT*' -and -not $_.Current.IsOffscreen }) | Select-Object -First 1 }
function Get-Focus { try { $f = $AE::FocusedElement; return [pscustomobject]@{ Name = $f.Current.Name; Pid = $f.Current.ProcessId; Class = $f.Current.ClassName } } catch { return [pscustomobject]@{ Name = '?'; Pid = 0; Class = '' } } }
function Get-Mode($win) {
    if (Find-Kid $win 'LotRadar is open') { return 'done' }
    $r = Find-Kid $win 'Retry (F5)'
    if ($r -and $r.Current.IsEnabled -and (Find-Kid $win 'LotRadar could not start')) { return 'failed' }
    return 'running'
}
function Wait-Mode($win, [string]$Mode, [int]$Seconds = 45) {
    $until = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $until) { if ((Get-Mode $win) -eq $Mode) { return $true }; Start-Sleep -Milliseconds 250 }
    return $false
}
function Save-Shot([IntPtr]$Hwnd, [string]$Name) {
    try {
        $r = New-Object LRInput.Native+RECT; [void][LRInput.Native]::GetWindowRect($Hwnd, [ref]$r)
        $bmp = New-Object Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T); $g = [Drawing.Graphics]::FromImage($bmp); $hdc = $g.GetHdc()
        [void][LRInput.Native]::PrintWindow($Hwnd, $hdc, 2); $g.ReleaseHdc($hdc); $g.Dispose()
        $bmp.Save((Join-Path $OutDir ("window-$Name.png")), [Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
        return "window-$Name.png"
    } catch { return 'screenshot failed' }
}

# ---------------------------------------------------------------- windows under test
function Start-Preview([int]$Run) {
    $res = Join-Path $OutDir "preview-result-$Run.json"
    $p = Start-Process -FilePath $psExe -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-STA', '-File', ('"' + $Gui + '"'), '-Preview', '-ResultFile', ('"' + $res + '"')) -PassThru
    $null = $p.Handle; [void]$script:Owned.Add($p.Id)
    $until = (Get-Date).AddSeconds(30)
    while ($p.MainWindowHandle -eq [IntPtr]::Zero -and (Get-Date) -lt $until) { Start-Sleep -Milliseconds 200; $p.Refresh() }
    if ($p.MainWindowHandle -eq [IntPtr]::Zero) { throw [Blocked]::new("preview $Run window did not appear") }
    $win = $AE::FromHandle($p.MainWindowHandle)
    return [pscustomobject]@{ Run = $Run; Proc = $p; Hwnd = $p.MainWindowHandle; Win = $win; Pid = $p.Id; Result = $res }
}
function Close-ByTitleBarX($w) {
    $r = [LRInput.Native]::CloseButtonRect($w.Hwnd)
    if ($r.R -le $r.L -or $r.B -le $r.T) { throw [Blocked]::new('title-bar Close (X) button position not reported') }
    Set-OwnedForeground $w.Hwnd $w.Pid (Find-Kid $w.Win 'LotRadar is open') | Out-Null
    Send-Click $w.Pid @([int](($r.L + $r.R) / 2), [int](($r.T + $r.B) / 2))
}
function Read-Result($w) {
    if (-not $w.Proc.WaitForExit(15000)) { throw [Blocked]::new("preview $($w.Run) did not close") }
    if (-not (Test-Path -LiteralPath $w.Result)) { throw [Blocked]::new("preview $($w.Run) wrote no result file") }
    return (Get-Content -Raw -LiteralPath $w.Result | ConvertFrom-Json)
}
function Get-Count([string]$Log, [string]$Item) { return @(([string]$Log).Split(',') | Where-Object { $_ -eq $Item }).Count }
function Test-Cycle([string[]]$Seen, [string[]]$Order) {
    # $Seen = focus after each of 4 presses; must visit all 4 buttons once, in $Order (cyclic), ending where it started
    if ($Seen.Count -ne 4 -or @($Seen | Select-Object -Unique).Count -ne 4) { return $false }
    $i = [array]::IndexOf($Order, $Seen[0]); if ($i -lt 0) { return $false }
    for ($k = 0; $k -lt 4; $k++) { if ($Seen[$k] -ne $Order[($i + $k) % 4]) { return $false } }
    return $true
}
$VK = @{ Tab = 0x09; Shift = 0x10; Alt = 0x12; Esc = 0x1B; F5 = 0x74; S = 0x53; D = 0x44; C = 0x43; R = 0x52; L = 0x4C }
$Buttons = @('Show details', 'Show console', 'Retry (F5)', 'Close')
function Focus-Until($w, [string]$Name, [int]$Max = 6) {
    for ($i = 0; $i -lt $Max; $i++) { if ((Get-Focus).Name -eq $Name) { return $true }; Send-Keys $w.Pid @($VK.Tab) }
    return ((Get-Focus).Name -eq $Name)
}

$started = Get-Date
$info = [ordered]@{ gui = $Gui; gui_sha256 = (Get-FileHash -LiteralPath $Gui -Algorithm SHA256).Hash.ToLowerInvariant(); windows = [Environment]::OSVersion.Version.ToString(); powershell = $PSVersionTable.PSVersion.ToString(); utc = $started.ToUniversalTime().ToString('o') }
Write-Host 'LotRadar startup window - automated real-input preview test. Do not use the keyboard or mouse for about 2 minutes.' -ForegroundColor Cyan
$blocked = ''
try {
    # ================= run 1: Tab order, mnemonics, F5 retry, F5 while starting / held, F5 after done, Escape
    $w = Start-Preview 1
    if (-not (Wait-Mode $w.Win 'failed')) { throw [Blocked]::new('preview 1 never reached the example failure') }
    $how = Set-OwnedForeground $w.Hwnd $w.Pid (Find-Kid $w.Win 'LotRadar could not start')
    $shot = Save-Shot $w.Hwnd 'failure'
    Add-Row 'A0' 'INFO' ("window to front via $how; screenshot $shot")
    $start = (Get-Focus).Name
    $seen = @(); for ($i = 0; $i -lt 4; $i++) { Send-Keys $w.Pid @($VK.Tab); $seen += (Get-Focus).Name }
    Add-Row 'P-TAB' $(if ((Test-Cycle $seen $Buttons) -and $seen[3] -eq $start) { 'PASS' } else { 'FAIL' }) ("start=$start; after Tab x4: " + ($seen -join ' > '))
    $seenB = @(); for ($i = 0; $i -lt 4; $i++) { Send-Keys $w.Pid @($VK.Shift, $VK.Tab); $seenB += (Get-Focus).Name }
    $rev = @($Buttons[3], $Buttons[2], $Buttons[1], $Buttons[0])
    Add-Row 'P-STAB' $(if ((Test-Cycle $seenB $rev) -and $seenB[3] -eq $start) { 'PASS' } else { 'FAIL' }) ("after Shift+Tab x4: " + ($seenB -join ' > '))
    Send-Keys $w.Pid @($VK.Alt, $VK.S)
    $ok = (Find-Kid $w.Win 'Hide details') -and (Find-Details $w.Win)
    Add-Row 'P-ALTS' $(if ($ok) { 'PASS' } else { 'FAIL' }) ('details visible=' + [bool](Find-Details $w.Win) +'; button=' + $(if (Find-Kid $w.Win 'Hide details') { 'Hide details' } else { 'not Hide details' }))
    Send-Keys $w.Pid @($VK.Alt, $VK.D)
    $ok = (Find-Kid $w.Win 'Show details') -and -not (Find-Details $w.Win)
    Add-Row 'P-ALTD' $(if ($ok) { 'PASS' } else { 'FAIL' }) ('details visible=' + [bool](Find-Details $w.Win))
    Send-Keys $w.Pid @($VK.Alt, $VK.C)
    $msg = Find-Kid $w.Win 'Preview: there is no console window*'
    Add-Row 'P-ALTC' $(if ($msg -and (Get-Mode $w.Win) -eq 'failed') { 'PASS' } else { 'FAIL' }) ('preview console message shown=' + [bool]$msg + '; mode=' + (Get-Mode $w.Win))
    $onRetry = Focus-Until $w 'Retry (F5)'
    Send-Keys $w.Pid @($VK.F5)
    $f = Get-Focus; $m = Get-Mode $w.Win; $retryEnabled = (Find-Kid $w.Win 'Retry (F5)').Current.IsEnabled
    Add-Row 'P-F5-RETRY' $(if ($onRetry -and $m -eq 'running' -and -not $retryEnabled -and $f.Pid -eq $w.Pid) { 'PASS' } else { 'FAIL' }) ("focus before=Retry (F5):$onRetry; after F5 mode=$m, Retry enabled=$retryEnabled, focus='" + $f.Name + "' (in window: " + ($f.Pid -eq $w.Pid) + ')')
    for ($i = 0; $i -lt 3; $i++) { Send-Keys $w.Pid @($VK.F5) }
    Send-HeldKey $w.Pid $VK.F5 60 33
    $midMode = Get-Mode $w.Win
    $doneOk = Wait-Mode $w.Win 'done'
    $shot2 = Save-Shot $w.Hwnd 'done'
    Send-Keys $w.Pid @($VK.F5)
    Start-Sleep -Milliseconds 800
    $afterDone = Get-Mode $w.Win
    Set-OwnedForeground $w.Hwnd $w.Pid $null | Out-Null
    Send-Keys $w.Pid @($VK.Esc)
    $r1 = Read-Result $w
    $log = [string]$r1.retry_log
    Add-Row 'P-F5-RUNNING' $(if ($midMode -eq 'running' -and $doneOk -and $r1.attempts -eq 2 -and (Get-Count $log 'f5:started') -eq 1 -and (Get-Count $log 'f5:repeat') -ge 50 -and (Get-Count $log 'f5:not-eligible') -ge 4) { 'PASS' } else { 'FAIL' }) ("3 taps + held 2 s while starting; attempts=$($r1.attempts); started=" + (Get-Count $log 'f5:started') + ' repeat=' + (Get-Count $log 'f5:repeat') + ' not-eligible=' + (Get-Count $log 'f5:not-eligible') + "; reached done=$doneOk ($shot2)")
    Add-Row 'P-F5-DONE' $(if ($afterDone -eq 'done' -and $r1.attempts -eq 2 -and $log.EndsWith('f5:not-eligible')) { 'PASS' } else { 'FAIL' }) ("F5 after open: mode stayed $afterDone; attempts=$($r1.attempts); last log entry " + @($log.Split(','))[-1])
    Add-Row 'P-ESC' $(if ($r1.mode -eq 'done' -and $r1.exit -eq 0 -and $w.Proc.HasExited) { 'PASS' } else { 'FAIL' }) ("Escape closed the window; result mode=$($r1.mode) exit=$($r1.exit)")
    Add-Row 'R1-LOG' 'INFO' ("run 1 retry_log (compressed): started=" + (Get-Count $log 'f5:started') + ' repeat=' + (Get-Count $log 'f5:repeat') + ' not-eligible=' + (Get-Count $log 'f5:not-eligible') + ' click=' + (@($log.Split(',') | Where-Object { $_ -like 'click:*' }).Count))

    # ================= run 2: F5 while Show details has focus
    $w = Start-Preview 2
    if (-not (Wait-Mode $w.Win 'failed')) { throw [Blocked]::new('preview 2 never reached the example failure') }
    Set-OwnedForeground $w.Hwnd $w.Pid (Find-Kid $w.Win 'LotRadar could not start') | Out-Null
    $onBtn = Focus-Until $w 'Show details'
    Send-Keys $w.Pid @($VK.F5)
    $f = Get-Focus; $m = Get-Mode $w.Win
    $doneOk = Wait-Mode $w.Win 'done'
    Close-ByTitleBarX $w
    $r2 = Read-Result $w
    Add-Row 'P-F5-FOCUS-BTN' $(if ($onBtn -and $m -eq 'running' -and $doneOk -and $r2.attempts -eq 2 -and $r2.retry_log -eq 'f5:started' -and $r2.mode -eq 'done') { 'PASS' } else { 'FAIL' }) ("focus on Show details=$onBtn; after F5 mode=$m focus='" + $f.Name + "'; done=$doneOk; closed with X; attempts=$($r2.attempts) log=$($r2.retry_log)")

    # ================= run 3: F5 inside the details text
    $w = Start-Preview 3
    if (-not (Wait-Mode $w.Win 'failed')) { throw [Blocked]::new('preview 3 never reached the example failure') }
    Set-OwnedForeground $w.Hwnd $w.Pid (Find-Kid $w.Win 'LotRadar could not start') | Out-Null
    Send-Keys $w.Pid @($VK.Alt, $VK.S)
    $box = Find-Details $w.Win
    if (-not $box) { throw [Blocked]::new('details box did not open in preview 3') }
    Send-Click $w.Pid $box
    $inBox = (Get-Focus).Class -like '*EDIT*'
    $ro = [LRInput.Native]::IsReadOnlyEdit([IntPtr]$box.Current.NativeWindowHandle)
    $textBefore = ''; try { $textBefore = $box.GetCurrentPattern([Windows.Automation.ValuePattern]::Pattern).Current.Value } catch { }
    Send-Keys $w.Pid @($VK.F5)
    $m = Get-Mode $w.Win
    $box2 = Find-Details $w.Win; $textAfter = ''; try { $textAfter = $box2.GetCurrentPattern([Windows.Automation.ValuePattern]::Pattern).Current.Value } catch { }
    $doneOk = Wait-Mode $w.Win 'done'
    Close-ByTitleBarX $w
    $r3 = Read-Result $w
    $noEdit = ($ro -eq $true)   # the box cannot be edited; F5 is also suppressed by the form (SuppressKeyPress)
    Add-Row 'P-F5-FOCUS-DETAILS' $(if ($inBox -and $noEdit -and $m -eq 'running' -and $doneOk -and $r3.attempts -eq 2 -and $r3.retry_log -eq 'f5:started') { 'PASS' } else { 'FAIL' }) ("focus in details=$inBox; box read-only=$ro; after F5 mode=$m; done=$doneOk; attempts=$($r3.attempts) log=$($r3.retry_log)")

    # ================= run 4: mouse click on Retry (F5)
    $w = Start-Preview 4
    if (-not (Wait-Mode $w.Win 'failed')) { throw [Blocked]::new('preview 4 never reached the example failure') }
    Set-OwnedForeground $w.Hwnd $w.Pid (Find-Kid $w.Win 'LotRadar could not start') | Out-Null
    Send-Click $w.Pid (Find-Kid $w.Win 'Retry (F5)')
    $f = Get-Focus; $m = Get-Mode $w.Win
    $doneOk = Wait-Mode $w.Win 'done'
    Close-ByTitleBarX $w
    $r4 = Read-Result $w
    Add-Row 'P-CLICK-PARITY' $(if ($m -eq 'running' -and $doneOk -and $r4.attempts -eq 2 -and $r4.retry_log -eq 'click:started') { 'PASS' } else { 'FAIL' }) ("mouse click on Retry; after click mode=$m focus='" + $f.Name + "'; done=$doneOk; attempts=$($r4.attempts) log=$($r4.retry_log)")

    # ================= run 5: Alt+R, F5 in another window, label fit, Alt+L
    $w = Start-Preview 5
    if (-not (Wait-Mode $w.Win 'failed')) { throw [Blocked]::new('preview 5 never reached the example failure') }
    Set-OwnedForeground $w.Hwnd $w.Pid (Find-Kid $w.Win 'LotRadar could not start') | Out-Null
    Send-Keys $w.Pid @($VK.Alt, $VK.R)
    Start-Sleep -Milliseconds 800
    $mAltR = Get-Mode $w.Win
    Add-Row 'P-ALTR-NONE' $(if ($mAltR -eq 'failed') { 'PASS' } else { 'FAIL' }) "after Alt+R mode=$mAltR (final attempt count checked at close)"
    $helperLog = Join-Path $OutDir 'helper-keys.txt'
    $helperPs = Join-Path $OutDir 'helper-window.ps1'
    Set-Content -LiteralPath $helperPs -Encoding ASCII -Value @'
param([string]$Log)
Add-Type -AssemblyName System.Windows.Forms
$f = New-Object Windows.Forms.Form; $f.Text = 'LotRadar QA helper window (test only)'; $f.KeyPreview = $true
$f.StartPosition = 'Manual'; $f.Left = 40; $f.Top = 40; $f.Width = 420; $f.Height = 160
$t = New-Object Windows.Forms.TextBox; $t.Multiline = $true; $t.Dock = 'Fill'; $f.Controls.Add($t)
$f.Add_KeyDown({ param($s, $e) Add-Content -LiteralPath $Log -Value ([string]$e.KeyCode) })
$f.Add_Shown({ $f.Activate() })
[Windows.Forms.Application]::Run($f)
'@
    $hp = Start-Process -FilePath $psExe -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-STA', '-File', ('"' + $helperPs + '"'), '-Log', ('"' + $helperLog + '"')) -PassThru
    $null = $hp.Handle; [void]$script:Owned.Add($hp.Id)
    $until = (Get-Date).AddSeconds(20); while ($hp.MainWindowHandle -eq [IntPtr]::Zero -and (Get-Date) -lt $until) { Start-Sleep -Milliseconds 200; $hp.Refresh() }
    $hwin = $AE::FromHandle($hp.MainWindowHandle)
    $hbox = @(Get-Kids $hwin | Where-Object { $_.Current.ControlType -eq [Windows.Automation.ControlType]::Edit }) | Select-Object -First 1
    Set-OwnedForeground $hp.MainWindowHandle $hp.Id $hbox | Out-Null
    Send-Keys $hp.Id @($VK.F5)
    Start-Sleep -Milliseconds 500
    $helperGot = (Test-Path -LiteralPath $helperLog) -and ((Get-Content -LiteralPath $helperLog) -contains 'F5')
    $mOther = Get-Mode $w.Win
    $retryEl = Find-Kid $w.Win 'Retry (F5)'
    $rr = $retryEl.Current.BoundingRectangle; $retryName = $retryEl.Current.Name   # read while the window is still open
    $how5 = Set-OwnedForeground $w.Hwnd $w.Pid (Find-Kid $w.Win 'LotRadar could not start')
    Send-Keys $w.Pid @($VK.Alt, $VK.L)
    $r5 = Read-Result $w
    try { $hp.CloseMainWindow() | Out-Null; if (-not $hp.WaitForExit(5000)) { Stop-Process -Id $hp.Id -Force } } catch { }
    Add-Row 'P-F5-OTHER-WINDOW' $(if ($helperGot -and $mOther -eq 'failed' -and -not $r5.retry_log) { 'PASS' } else { 'FAIL' }) ("F5 went to the other window: $helperGot; LotRadar mode=$mOther; LotRadar retry_log='" + $r5.retry_log + "'")
    Add-Row 'P-LABEL' $(if (-not [string]$r5.clipped -and $retryName -eq 'Retry (F5)') { 'PASS' } else { 'FAIL' }) ("Retry label '" + $retryName + "' button " + [int]$rr.Width + 'x' + [int]$rr.Height + ' px; window clipped-text check: ' + $(if ([string]$r5.clipped) { [string]$r5.clipped } else { 'nothing cut off' }) + " at scale $($r5.scale)")
    Add-Row 'P-ALTL' $(if ($r5.mode -eq 'failed' -and $r5.exit -eq 0 -and $r5.attempts -eq 1 -and $w.Proc.HasExited) { 'PASS' } else { 'FAIL' }) ("refocused via $how5; Alt+L closed it; mode=$($r5.mode) attempts=$($r5.attempts) (Alt+R and other-window F5 started nothing)")
} catch [Blocked] {
    $blocked = $_.Exception.Message
    Add-Row 'BLOCK' 'BLOCKED' $blocked
} catch {
    $blocked = 'test error: ' + $_.Exception.Message + ' @ ' + $_.InvocationInfo.ScriptLineNumber
    Add-Row 'ERROR' 'INCONCLUSIVE' $blocked
} finally {
    foreach ($id in @($script:Owned)) { try { $pp = Get-Process -Id $id -ErrorAction Stop; Stop-Process -Id $pp.Id -Force } catch { } }
}
$expected = 'P-TAB', 'P-STAB', 'P-ALTS', 'P-ALTD', 'P-ALTC', 'P-F5-RETRY', 'P-F5-RUNNING', 'P-F5-DONE', 'P-ESC', 'P-F5-FOCUS-BTN', 'P-F5-FOCUS-DETAILS', 'P-CLICK-PARITY', 'P-ALTR-NONE', 'P-F5-OTHER-WINDOW', 'P-LABEL', 'P-ALTL'
foreach ($id in $expected) { if (-not (@($script:Rows | Where-Object { $_.id -eq $id }))) { Add-Row $id 'NOT RUN' $(if ($blocked) { 'stopped earlier: ' + $blocked } else { 'missing' }) } }
$p = @($script:Rows | Where-Object { $expected -contains $_.id })
$pass = @($p | Where-Object { $_.status -eq 'PASS' }).Count; $fail = @($p | Where-Object { $_.status -eq 'FAIL' }).Count
$info.rows = @($script:Rows); $info.pass = $pass; $info.fail = $fail; $info.seconds = [int]((Get-Date) - $started).TotalSeconds
$info | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $OutDir 'real-input-result.json') -Encoding UTF8
Write-Host ("P rows: PASS=$pass FAIL=$fail other=" + (16 - $pass - $fail) + " ($($info.seconds) s). Results: $OutDir") -ForegroundColor Cyan
if ($fail -gt 0) { exit 1 } elseif ($pass -ne 16) { exit 2 } else { exit 0 }
