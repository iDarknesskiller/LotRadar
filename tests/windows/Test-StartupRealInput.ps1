# LotRadar startup window: automated REAL-INPUT acceptance of the preview window (LR-010, rows P-*). TEST-ONLY.
#
# Replaces the Owner pressing keys by hand (Owner direction 2026-11-21: "it doesnt need me").
# Unlike G10-G13 (window messages posted straight to the form), every key and click here goes through
# SendInput (qa-kit\LotRadarQA.RealInput.ps1), the same system input queue a physical keyboard and mouse feed:
# focus, mnemonics, Tab order, key-repeat (sent as repeated key-downs, like keyboard auto-repeat) and foreground
# rules all apply. Focus is read back with UI Automation. Residual difference to a hardware keyboard: injected
# input carries the LLKHF_INJECTED flag, which the form does not look at.
#
# Safety: nothing is installed or started (the window runs with -Preview). Before EVERY key or click the
# module checks that the foreground window / click point belongs to a process this script started; otherwise
# it sends nothing and stops (BLOCKED). Only processes this script started are stopped at the end. Do not use
# the keyboard or mouse while it runs (about 2.5 minutes).
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
. (Join-Path $PSScriptRoot 'qa-kit\LotRadarQA.RealInput.ps1')
$AE = [Windows.Automation.AutomationElement]
$VK = $RIVK

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
function Get-Mode($win) {
    if (Find-RIKid $win 'LotRadar is open') { return 'done' }
    $r = Find-RIKid $win 'Retry (F5)'
    if ($r -and $r.Current.IsEnabled -and (Find-RIKid $win 'LotRadar could not start')) { return 'failed' }
    return 'running'
}
function Wait-Mode($win, [string]$Mode, [int]$Seconds = 45) {
    $until = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $until) { if ((Get-Mode $win) -eq $Mode) { return $true }; Start-Sleep -Milliseconds 250 }
    return $false
}
function Start-Preview([int]$Run) {
    $res = Join-Path $OutDir "preview-result-$Run.json"
    $p = Start-Process -FilePath $psExe -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-STA', '-File', ('"' + $Gui + '"'), '-Preview', '-ResultFile', ('"' + $res + '"')) -PassThru
    $null = $p.Handle; [void]$script:Owned.Add($p.Id)
    $until = (Get-Date).AddSeconds(30)
    while ($p.MainWindowHandle -eq [IntPtr]::Zero -and (Get-Date) -lt $until) { Start-Sleep -Milliseconds 200; $p.Refresh() }
    if ($p.MainWindowHandle -eq [IntPtr]::Zero) { throw "BLOCKED: preview $Run window did not appear" }
    $win = $AE::FromHandle($p.MainWindowHandle)
    if (-not (Wait-Mode $win 'failed')) { throw "BLOCKED: preview $Run never reached the example failure" }
    [void](Set-RIForeground $p.MainWindowHandle $p.Id (Find-RIKid $win 'LotRadar could not start'))
    return [pscustomobject]@{ Run = $Run; Proc = $p; Hwnd = $p.MainWindowHandle; Win = $win; Pid = $p.Id; Result = $res }
}
function Close-ByTitleBarX($w) {
    $pt = Get-RICloseButtonPoint $w.Hwnd
    [void](Set-RIForeground $w.Hwnd $w.Pid (Find-RIKid $w.Win 'LotRadar is open'))
    Send-RIClick $w.Pid $pt
}
function Read-Result($w) {
    if (-not $w.Proc.WaitForExit(15000)) { throw "BLOCKED: preview $($w.Run) did not close" }
    if (-not (Test-Path -LiteralPath $w.Result)) { throw "BLOCKED: preview $($w.Run) wrote no result file" }
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
$Buttons = @('Show details', 'Show console', 'Retry (F5)', 'Close')
function Focus-Until($w, [string]$Name, [int]$Max = 6) {
    for ($i = 0; $i -lt $Max; $i++) { if ((Get-RIFocus).Name -eq $Name) { return $true }; Send-RIKeys $w.Pid @($VK.Tab) }
    return ((Get-RIFocus).Name -eq $Name)
}

$started = Get-Date
$info = [ordered]@{ gui = $Gui; gui_sha256 = (Get-FileHash -LiteralPath $Gui -Algorithm SHA256).Hash.ToLowerInvariant(); windows = [Environment]::OSVersion.Version.ToString(); powershell = $PSVersionTable.PSVersion.ToString(); utc = $started.ToUniversalTime().ToString('o') }
Write-Host 'LotRadar startup window - automated real-input preview test. Do not use the keyboard or mouse for about 2.5 minutes.' -ForegroundColor Cyan
$blocked = ''
try {
    # ================= run 1: Tab order, mnemonics, F5 retry, F5 while starting / held, F5 after done, Escape
    $w = Start-Preview 1
    Add-Row 'A0' 'INFO' ('screenshot ' + (Save-RIShot $w.Hwnd (Join-Path $OutDir 'window-failure.png')))
    $start = (Get-RIFocus).Name
    $seen = @(); for ($i = 0; $i -lt 4; $i++) { Send-RIKeys $w.Pid @($VK.Tab); $seen += (Get-RIFocus).Name }
    Add-Row 'P-TAB' $(if ((Test-Cycle $seen $Buttons) -and $seen[3] -eq $start) { 'PASS' } else { 'FAIL' }) ("start=$start; after Tab x4: " + ($seen -join ' > '))
    $seenB = @(); for ($i = 0; $i -lt 4; $i++) { Send-RIKeys $w.Pid @($VK.Shift, $VK.Tab); $seenB += (Get-RIFocus).Name }
    $rev = @($Buttons[3], $Buttons[2], $Buttons[1], $Buttons[0])
    Add-Row 'P-STAB' $(if ((Test-Cycle $seenB $rev) -and $seenB[3] -eq $start) { 'PASS' } else { 'FAIL' }) ("after Shift+Tab x4: " + ($seenB -join ' > '))
    Send-RIKeys $w.Pid @($VK.Alt, $VK.S)
    $ok = (Find-RIKid $w.Win 'Hide details') -and (Find-RIDetails $w.Win)
    Add-Row 'P-ALTS' $(if ($ok) { 'PASS' } else { 'FAIL' }) ('details visible=' + [bool](Find-RIDetails $w.Win) + '; button=' + $(if (Find-RIKid $w.Win 'Hide details') { 'Hide details' } else { 'not Hide details' }))
    Send-RIKeys $w.Pid @($VK.Alt, $VK.D)
    $ok = (Find-RIKid $w.Win 'Show details') -and -not (Find-RIDetails $w.Win)
    Add-Row 'P-ALTD' $(if ($ok) { 'PASS' } else { 'FAIL' }) ('details visible=' + [bool](Find-RIDetails $w.Win))
    Send-RIKeys $w.Pid @($VK.Alt, $VK.C)
    $msg = Find-RIKid $w.Win 'Preview: there is no console window*'
    Add-Row 'P-ALTC' $(if ($msg -and (Get-Mode $w.Win) -eq 'failed') { 'PASS' } else { 'FAIL' }) ('preview console message shown=' + [bool]$msg + '; mode=' + (Get-Mode $w.Win))
    $onRetry = Focus-Until $w 'Retry (F5)'
    Send-RIKeys $w.Pid @($VK.F5)
    $f = Get-RIFocus; $m = Get-Mode $w.Win; $retryEnabled = (Find-RIKid $w.Win 'Retry (F5)').Current.IsEnabled
    Add-Row 'P-F5-RETRY' $(if ($onRetry -and $m -eq 'running' -and -not $retryEnabled -and $f.Pid -eq $w.Pid) { 'PASS' } else { 'FAIL' }) ("focus before=Retry (F5):$onRetry; after F5 mode=$m, Retry enabled=$retryEnabled, focus='" + $f.Name + "' (in window: " + ($f.Pid -eq $w.Pid) + ')')
    for ($i = 0; $i -lt 3; $i++) { Send-RIKeys $w.Pid @($VK.F5) }
    Send-RIHeldKey $w.Pid $VK.F5 60 33
    $midMode = Get-Mode $w.Win
    $doneOk = Wait-Mode $w.Win 'done'
    $shot2 = Save-RIShot $w.Hwnd (Join-Path $OutDir 'window-done.png')
    Send-RIKeys $w.Pid @($VK.F5)
    Start-Sleep -Milliseconds 800
    $afterDone = Get-Mode $w.Win
    [void](Set-RIForeground $w.Hwnd $w.Pid $null)
    Send-RIKeys $w.Pid @($VK.Esc)
    $r1 = Read-Result $w
    $log = [string]$r1.retry_log
    Add-Row 'P-F5-RUNNING' $(if ($midMode -eq 'running' -and $doneOk -and $r1.attempts -eq 2 -and (Get-Count $log 'f5:started') -eq 1 -and (Get-Count $log 'f5:repeat') -ge 50 -and (Get-Count $log 'f5:not-eligible') -ge 4) { 'PASS' } else { 'FAIL' }) ("3 taps + held 2 s while starting; attempts=$($r1.attempts); started=" + (Get-Count $log 'f5:started') + ' repeat=' + (Get-Count $log 'f5:repeat') + ' not-eligible=' + (Get-Count $log 'f5:not-eligible') + "; reached done=$doneOk ($shot2)")
    Add-Row 'P-F5-DONE' $(if ($afterDone -eq 'done' -and $r1.attempts -eq 2 -and $log.EndsWith('f5:not-eligible')) { 'PASS' } else { 'FAIL' }) ("F5 after open: mode stayed $afterDone; attempts=$($r1.attempts); last log entry " + @($log.Split(','))[-1])
    Add-Row 'P-ESC' $(if ($r1.mode -eq 'done' -and $r1.exit -eq 0 -and $w.Proc.HasExited) { 'PASS' } else { 'FAIL' }) ("Escape closed the window; result mode=$($r1.mode) exit=$($r1.exit)")
    Add-Row 'R1-LOG' 'INFO' ("run 1 retry_log (compressed): started=" + (Get-Count $log 'f5:started') + ' repeat=' + (Get-Count $log 'f5:repeat') + ' not-eligible=' + (Get-Count $log 'f5:not-eligible') + ' click=' + (@($log.Split(',') | Where-Object { $_ -like 'click:*' }).Count))

    # ================= run 2: F5 while Show details has focus
    $w = Start-Preview 2
    $onBtn = Focus-Until $w 'Show details'
    Send-RIKeys $w.Pid @($VK.F5)
    $f = Get-RIFocus; $m = Get-Mode $w.Win
    $doneOk = Wait-Mode $w.Win 'done'
    Close-ByTitleBarX $w
    $r2 = Read-Result $w
    Add-Row 'P-F5-FOCUS-BTN' $(if ($onBtn -and $m -eq 'running' -and $doneOk -and $r2.attempts -eq 2 -and $r2.retry_log -eq 'f5:started' -and $r2.mode -eq 'done') { 'PASS' } else { 'FAIL' }) ("focus on Show details=$onBtn; after F5 mode=$m focus='" + $f.Name + "'; done=$doneOk; closed with X; attempts=$($r2.attempts) log=$($r2.retry_log)")

    # ================= run 3: F5 inside the details text
    $w = Start-Preview 3
    Send-RIKeys $w.Pid @($VK.Alt, $VK.S)
    $box = Find-RIDetails $w.Win
    if (-not $box) { throw 'BLOCKED: details box did not open in preview 3' }
    Send-RIClick $w.Pid $box
    $inBox = (Get-RIFocus).Class -like '*EDIT*'
    $ro = [LRInput.Native]::IsReadOnlyEdit([IntPtr]$box.Current.NativeWindowHandle)   # the box cannot be edited; F5 is also suppressed by the form
    Send-RIKeys $w.Pid @($VK.F5)
    $m = Get-Mode $w.Win
    $doneOk = Wait-Mode $w.Win 'done'
    Close-ByTitleBarX $w
    $r3 = Read-Result $w
    Add-Row 'P-F5-FOCUS-DETAILS' $(if ($inBox -and $ro -and $m -eq 'running' -and $doneOk -and $r3.attempts -eq 2 -and $r3.retry_log -eq 'f5:started') { 'PASS' } else { 'FAIL' }) ("focus in details=$inBox; box read-only=$ro; after F5 mode=$m; done=$doneOk; attempts=$($r3.attempts) log=$($r3.retry_log)")

    # ================= run 4: mouse click on Retry (F5)
    $w = Start-Preview 4
    Send-RIClick $w.Pid (Find-RIKid $w.Win 'Retry (F5)')
    $f = Get-RIFocus; $m = Get-Mode $w.Win
    $doneOk = Wait-Mode $w.Win 'done'
    Close-ByTitleBarX $w
    $r4 = Read-Result $w
    Add-Row 'P-CLICK-PARITY' $(if ($m -eq 'running' -and $doneOk -and $r4.attempts -eq 2 -and $r4.retry_log -eq 'click:started') { 'PASS' } else { 'FAIL' }) ("mouse click on Retry; after click mode=$m focus='" + $f.Name + "'; done=$doneOk; attempts=$($r4.attempts) log=$($r4.retry_log)")

    # ================= run 5: Alt+R, F5 in another window, label fit, Alt+L
    $w = Start-Preview 5
    Send-RIKeys $w.Pid @($VK.Alt, $VK.R)
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
    $hbox = @(Get-RIKids $hwin | Where-Object { $_.Current.ClassName -like '*EDIT*' }) | Select-Object -First 1
    [void](Set-RIForeground $hp.MainWindowHandle $hp.Id $hbox)
    Send-RIKeys $hp.Id @($VK.F5)
    Start-Sleep -Milliseconds 500
    $helperGot = (Test-Path -LiteralPath $helperLog) -and ((Get-Content -LiteralPath $helperLog) -contains 'F5')
    $mOther = Get-Mode $w.Win
    $retryEl = Find-RIKid $w.Win 'Retry (F5)'
    $rr = $retryEl.Current.BoundingRectangle; $retryName = $retryEl.Current.Name   # read while the window is still open
    $how5 = Set-RIForeground $w.Hwnd $w.Pid (Find-RIKid $w.Win 'LotRadar could not start')
    Send-RIKeys $w.Pid @($VK.Alt, $VK.L)
    $r5 = Read-Result $w
    try { $hp.CloseMainWindow() | Out-Null; if (-not $hp.WaitForExit(5000)) { Stop-Process -Id $hp.Id -Force } } catch { }
    Add-Row 'P-F5-OTHER-WINDOW' $(if ($helperGot -and $mOther -eq 'failed' -and -not $r5.retry_log) { 'PASS' } else { 'FAIL' }) ("F5 went to the other window: $helperGot; LotRadar mode=$mOther; LotRadar retry_log='" + $r5.retry_log + "'")
    Add-Row 'P-LABEL' $(if (-not [string]$r5.clipped -and $retryName -eq 'Retry (F5)') { 'PASS' } else { 'FAIL' }) ("Retry label '" + $retryName + "' button " + [int]$rr.Width + 'x' + [int]$rr.Height + ' px; window clipped-text check: ' + $(if ([string]$r5.clipped) { [string]$r5.clipped } else { 'nothing cut off' }) + " at scale $($r5.scale)")
    Add-Row 'P-ALTL' $(if ($r5.mode -eq 'failed' -and $r5.exit -eq 0 -and $r5.attempts -eq 1 -and $w.Proc.HasExited) { 'PASS' } else { 'FAIL' }) ("refocused via $how5; Alt+L closed it; mode=$($r5.mode) attempts=$($r5.attempts) (Alt+R and other-window F5 started nothing)")
} catch {
    $msg = $_.Exception.Message
    if ($msg -like 'BLOCKED:*') { $blocked = $msg; Add-Row 'BLOCK' 'BLOCKED' $msg }
    else { $blocked = 'test error: ' + $msg + ' @ ' + $_.InvocationInfo.ScriptLineNumber; Add-Row 'ERROR' 'INCONCLUSIVE' $blocked }
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
