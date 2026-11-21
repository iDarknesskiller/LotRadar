# LotRadar QA kit: REAL system input for automated keyboard/mouse acceptance (TEST-ONLY). Dot-sourced.
# Used by tests\windows\Test-StartupRealInput.ps1 (preview rows P-*) and by LotRadarQA.ManualUI.ps1 -AutoInput
# (real console rows R-*). Owner direction 2026-11-21: the physical rows must not need the Owner.
#
# Keys and clicks go through SendInput, the system input queue a physical keyboard and mouse feed, so focus,
# mnemonics, Tab order, key repeat and foreground rules apply. Injected input carries LLKHF_INJECTED, which the
# LotRadar window does not read.
# Safety: before EVERY key the foreground window must belong to the process the caller names; before EVERY click
# the point must lie on a window of that process. Otherwise nothing is sent and a 'BLOCKED: ...' error is thrown.
# Windows are only ever closed by WM_CLOSE to handles the caller proves it created; no process is killed here.

if (-not ('LRInput.Native' -as [type])) {
Add-Type -TypeDefinition @'
using System; using System.Collections.Generic; using System.Runtime.InteropServices; using System.Text;
namespace LRInput {
public static class Native {
  [StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT { public int dx; public int dy; public uint mouseData; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
  [StructLayout(LayoutKind.Sequential)] public struct KEYBDINPUT { public ushort wVk; public ushort wScan; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
  [StructLayout(LayoutKind.Explicit)] public struct UNION { [FieldOffset(0)] public MOUSEINPUT mi; [FieldOffset(0)] public KEYBDINPUT ki; }
  [StructLayout(LayoutKind.Sequential)] public struct INPUT { public uint type; public UNION u; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [StructLayout(LayoutKind.Sequential)] public struct TITLEBARINFOEX { public int cbSize; public RECT rcTitleBar; [MarshalAs(UnmanagedType.ByValArray, SizeConst = 6)] public int[] rgstate; [MarshalAs(UnmanagedType.ByValArray, SizeConst = 6)] public RECT[] rgrect; }
  delegate bool EnumProc(IntPtr h, IntPtr l);
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
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint msg, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc f, IntPtr l);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] static extern int GetWindowLong(IntPtr h, int i);
  [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr h, uint msg, IntPtr w, ref TITLEBARINFOEX l);
  public static uint Key(ushort vk, bool up) {
    INPUT[] a = new INPUT[1]; a[0].type = 1; a[0].u.ki.wVk = vk; a[0].u.ki.wScan = (ushort)MapVirtualKey(vk, 0);
    a[0].u.ki.dwFlags = up ? 2u : 0u; return SendInput(1, a, Marshal.SizeOf(typeof(INPUT)));
  }
  public static uint Click(int x, int y) {
    int vx = GetSystemMetrics(76), vy = GetSystemMetrics(77), vw = GetSystemMetrics(78), vh = GetSystemMetrics(79);
    INPUT[] a = new INPUT[3];
    a[0].u.mi.dx = (int)(((long)(x - vx) * 65535) / (vw - 1)); a[0].u.mi.dy = (int)(((long)(y - vy) * 65535) / (vh - 1));
    a[0].u.mi.dwFlags = 0x0001 | 0x8000 | 0x4000; a[1].u.mi.dwFlags = 0x0002; a[2].u.mi.dwFlags = 0x0004;
    return SendInput(3, a, Marshal.SizeOf(typeof(INPUT)));
  }
  public static RECT CloseButtonRect(IntPtr h) {
    // WM_GETTITLEBARINFOEX: asks the window where its caption buttons are (index 5 = Close X). A query, not input.
    TITLEBARINFOEX t = new TITLEBARINFOEX(); t.rgstate = new int[6]; t.rgrect = new RECT[6]; t.cbSize = Marshal.SizeOf(typeof(TITLEBARINFOEX));
    SendMessage(h, 0x033F, IntPtr.Zero, ref t); return t.rgrect[5];
  }
  public static bool IsReadOnlyEdit(IntPtr h) { return (GetWindowLong(h, -16) & 0x0800) != 0; }   // GWL_STYLE, ES_READONLY
  public static uint PidOf(IntPtr h) { uint p; GetWindowThreadProcessId(h, out p); return p; }
  public static uint PidAt(int x, int y) { POINT p; p.X = x; p.Y = y; return PidOf(GetAncestor(WindowFromPoint(p), 2)); }
  public static string Title(IntPtr h) { StringBuilder s = new StringBuilder(512); GetWindowText(h, s, 512); return s.ToString(); }
  public static string ClassOf(IntPtr h) { StringBuilder s = new StringBuilder(256); GetClassName(h, s, 256); return s.ToString(); }
  public static List<IntPtr> TopWindows() {
    List<IntPtr> l = new List<IntPtr>();
    EnumWindows(delegate (IntPtr h, IntPtr x) { if (IsWindowVisible(h)) l.Add(h); return true; }, IntPtr.Zero);
    return l;
  }
}}
'@
}
[void][LRInput.Native]::SetProcessDpiAwarenessContext([IntPtr](-4))   # per-monitor: UIA rectangles = SendInput pixels (ignored if already set)
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Drawing
$RIVK = @{ Tab = 0x09; Shift = 0x10; Alt = 0x12; Esc = 0x1B; F5 = 0x74; S = 0x53; D = 0x44; C = 0x43; R = 0x52; L = 0x4C }

function Get-RIForegroundPid { return [int][LRInput.Native]::PidOf([LRInput.Native]::GetForegroundWindow()) }
function Assert-RINoHeldModifiers { foreach ($vk in 0x10, 0x11, 0x12, 0x5B, 0x5C) { if ([LRInput.Native]::GetAsyncKeyState($vk) -band 0x8000) { throw 'BLOCKED: a modifier key is physically held down; no input sent' } } }
function Assert-RIForeground([int]$WantPid) {
    $fg = Get-RIForegroundPid
    if ($fg -ne $WantPid) { throw "BLOCKED: foreground window is not the intended test window (pid $fg, wanted $WantPid); no input sent" }
}
function Send-RIKeys([int]$WantPid, [int[]]$Down, [int]$HoldMs = 30) {
    # presses the keys in order, then releases them in reverse order
    Assert-RINoHeldModifiers; Assert-RIForeground $WantPid
    foreach ($k in $Down) { [void][LRInput.Native]::Key([uint16]$k, $false); Start-Sleep -Milliseconds 15 }
    Start-Sleep -Milliseconds $HoldMs
    for ($i = $Down.Count - 1; $i -ge 0; $i--) { [void][LRInput.Native]::Key([uint16]$Down[$i], $true); Start-Sleep -Milliseconds 15 }
    Start-Sleep -Milliseconds 250
}
function Send-RIHeldKey([int]$WantPid, [int]$Vk, [int]$Repeats, [int]$IntervalMs) {
    # keyboard auto-repeat: one key-down, further key-downs while held, one key-up
    Assert-RINoHeldModifiers; Assert-RIForeground $WantPid
    [void][LRInput.Native]::Key([uint16]$Vk, $false)
    try { for ($i = 0; $i -lt $Repeats; $i++) { Start-Sleep -Milliseconds $IntervalMs; Assert-RIForeground $WantPid; [void][LRInput.Native]::Key([uint16]$Vk, $false) } }
    finally { [void][LRInput.Native]::Key([uint16]$Vk, $true) }
    Start-Sleep -Milliseconds 250
}
function Get-RICenter($el) {
    if ($el -is [array]) { return $el }   # already an @(x, y) point
    $r = $el.Current.BoundingRectangle; return @([int]($r.X + $r.Width / 2), [int]($r.Y + $r.Height / 2))
}
function Send-RIClick([int]$WantPid, $el) {
    Assert-RINoHeldModifiers
    $xy = Get-RICenter $el
    $at = [int][LRInput.Native]::PidAt($xy[0], $xy[1])
    if ($at -ne $WantPid) { throw "BLOCKED: the click point is covered by another window (pid $at); no click sent" }
    [void][LRInput.Native]::Click($xy[0], $xy[1])
    Start-Sleep -Milliseconds 400
}
function Get-RICloseButtonPoint([IntPtr]$Hwnd) {
    $r = [LRInput.Native]::CloseButtonRect($Hwnd)
    if ($r.R -le $r.L -or $r.B -le $r.T) { throw 'BLOCKED: title-bar Close (X) button position not reported' }
    return @([int](($r.L + $r.R) / 2), [int](($r.T + $r.B) / 2))
}
function Get-RIKids($win) { return @($win.FindAll([Windows.Automation.TreeScope]::Children, [Windows.Automation.Condition]::TrueCondition)) }
function Find-RIKid($win, [string]$Pattern) { return @(Get-RIKids $win | Where-Object { $_.Current.Name -like $Pattern -and -not $_.Current.IsOffscreen }) | Select-Object -First 1 }
function Find-RIDetails($win) { return @(Get-RIKids $win | Where-Object { $_.Current.ClassName -like '*EDIT*' -and -not $_.Current.IsOffscreen }) | Select-Object -First 1 }
function Get-RIFocus { try { $f = [Windows.Automation.AutomationElement]::FocusedElement; return [pscustomobject]@{ Name = $f.Current.Name; Pid = $f.Current.ProcessId; Class = $f.Current.ClassName } } catch { return [pscustomobject]@{ Name = '?'; Pid = 0; Class = '' } } }
function Find-RIClickablePoint($win, [int]$WantPid) {
    # a non-button element of the window (labels, step panels) whose centre is not covered by another window
    foreach ($k in @(Get-RIKids $win | Where-Object { $_.Current.ClassName -notlike '*BUTTON*' -and $_.Current.ClassName -notlike '*EDIT*' -and -not $_.Current.IsOffscreen })) {
        $xy = Get-RICenter $k
        if ([int][LRInput.Native]::PidAt($xy[0], $xy[1]) -eq $WantPid) { return $xy }
    }
    return $null
}
function Set-RIForeground([IntPtr]$Hwnd, [int]$WantPid, $ClickTarget) {
    for ($i = 0; $i -lt 3; $i++) {
        if ((Get-RIForegroundPid) -eq $WantPid) { return 'SetForegroundWindow' }
        [void][LRInput.Native]::SetForegroundWindow($Hwnd); Start-Sleep -Milliseconds 400
    }
    if ((Get-RIForegroundPid) -eq $WantPid) { return 'SetForegroundWindow' }
    if ($ClickTarget) { Send-RIClick $WantPid $ClickTarget; if ((Get-RIForegroundPid) -eq $WantPid) { return 'click' } }
    throw 'BLOCKED: could not bring the test window to the front; no input sent'
}
function Get-RITopWindows {
    return @([LRInput.Native]::TopWindows() | ForEach-Object { [pscustomobject]@{ Hwnd = $_; Pid = [int][LRInput.Native]::PidOf($_); Title = [LRInput.Native]::Title($_); Class = [LRInput.Native]::ClassOf($_) } })
}
function Save-RIShot([IntPtr]$Hwnd, [string]$Path) {
    try {
        $r = New-Object LRInput.Native+RECT; [void][LRInput.Native]::GetWindowRect($Hwnd, [ref]$r)
        $bmp = New-Object Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T); $g = [Drawing.Graphics]::FromImage($bmp); $hdc = $g.GetHdc()
        [void][LRInput.Native]::PrintWindow($Hwnd, $hdc, 2); $g.ReleaseHdc($hdc); $g.Dispose()
        $bmp.Save($Path, [Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
        return (Split-Path -Leaf $Path)
    } catch { return 'screenshot failed' }
}
