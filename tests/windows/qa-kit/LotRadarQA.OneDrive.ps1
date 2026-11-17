# LotRadar OneDrive QA (TEST-ONLY). Dot-sourced by Run-QAKit.ps1 -OneDrive after its normal preflight.
# Uses from Run-QAKit.ps1: Say, Stop-Kit, Get-Sha, Protect-Text, Test-ShortcutRestored, $kit, $pkgZip, $harness,
# $info, $os, $isWin11, $isAdmin, $resultsDir, $psExe, $script:Redact.
# Never changes OneDrive settings, never moves/deletes real files, never sets pin/unpin/offline flags.
# Only after typed consent does it create ONE disposable folder "LotRadar QA TEST ONLY <id>" in OneDrive,
# fills it with the synthetic test package, and deletes exactly that folder at the end.

$pathInfoSource = @'
using System; using System.Text; using System.Runtime.InteropServices; using Microsoft.Win32.SafeHandles;
namespace LotRadarQA {
  public static class PathInfo {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern SafeFileHandle CreateFileW(string name, uint access, uint share, IntPtr sa, uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern uint GetFinalPathNameByHandleW(SafeFileHandle h, StringBuilder buffer, uint size, uint flags);
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct WIN32_FIND_DATAW { public uint dwFileAttributes; public uint ftCreationLow, ftCreationHigh, ftAccessLow, ftAccessHigh, ftWriteLow, ftWriteHigh;
      public uint nFileSizeHigh; public uint nFileSizeLow; public uint dwReserved0; public uint dwReserved1;
      [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] public string cFileName; [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 14)] public string cAlternateFileName; }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern IntPtr FindFirstFileW(string name, out WIN32_FIND_DATAW data);
    [DllImport("kernel32.dll")] static extern bool FindClose(IntPtr h);
    // Real (canonical) path after junctions/symlinks, using a zero-access handle (does not read or hydrate content).
    public static string Final(string path) {
      using (SafeFileHandle h = CreateFileW(path, 0, 7, IntPtr.Zero, 3, 0x02000000, IntPtr.Zero)) {
        if (h.IsInvalid) return null;
        StringBuilder b = new StringBuilder(32768);
        uint n = GetFinalPathNameByHandleW(h, b, (uint)b.Capacity, 0);
        if (n == 0 || n >= (uint)b.Capacity) return null;
        string s = b.ToString();
        if (s.StartsWith(@"\\?\UNC\")) return @"\\" + s.Substring(8);
        if (s.StartsWith(@"\\?\")) return s.Substring(4);
        return s;
      }
    }
    public static uint Tag(string path) {
      WIN32_FIND_DATAW d; IntPtr h = FindFirstFileW(path.TrimEnd('\\'), out d);
      if (h == new IntPtr(-1)) return 0xFFFFFFFF;
      FindClose(h);
      return ((d.dwFileAttributes & 0x400) != 0) ? d.dwReserved0 : 0;
    }
  }
}
'@
try { if (-not ('LotRadarQA.PathInfo' -as [type])) { Add-Type -TypeDefinition $pathInfoSource } }
catch { Say ('Could not load the path-checking helper (Add-Type): ' + $_.Exception.Message) 'Red'; $script:OneDriveExit = 4; return }

function Get-Kind([string]$Path) {
    $t = [LotRadarQA.PathInfo]::Tag($Path)
    if ($t -eq [uint32]0) { return 'none' }
    if ($t -eq [uint32]4294967295) { return 'unreadable' }
    if ($t -eq [uint32]2684354572) { return 'symlink' }
    if ($t -eq [uint32]2684354563) { return 'junction' }
    if (($t -band [uint32]4294905855) -eq [uint32]2415919130) { return 'cloud' }
    return ('other:0x' + $t.ToString('X8'))
}
function Invoke-Native([string]$CommandLine) {
    # Windows PowerShell 5.1 turns native stderr into terminating errors under 'Stop'; contain it here.
    $ErrorActionPreference = 'Continue'
    $out = & cmd.exe /d /c $CommandLine 2>&1 | Out-String
    return [pscustomobject]@{ Code = $LASTEXITCODE; Output = $out }
}
function Test-Under([string]$Path, [string]$Root) {
    if (-not $Path -or -not $Root) { return $false }
    $r = $Root.TrimEnd('\')
    return ($Path.Equals($r, [StringComparison]::OrdinalIgnoreCase) -or $Path.StartsWith($r + '\', [StringComparison]::OrdinalIgnoreCase))
}
function Get-SyncRoots {
    $list = New-Object System.Collections.ArrayList
    $acc = 'HKCU:\Software\Microsoft\OneDrive\Accounts'
    if (Test-Path -LiteralPath $acc) {
        foreach ($k in @(Get-ChildItem -LiteralPath $acc -ErrorAction SilentlyContinue)) {
            $p = Get-ItemProperty -LiteralPath $k.PSPath -ErrorAction SilentlyContinue
            if ($p -and $p.UserFolder -and (Test-Path -LiteralPath $p.UserFolder -PathType Container)) {
                $kind = 'Personal'
                if ($k.PSChildName -like 'Business*') { $kind = 'Business' }
                [void]$list.Add([pscustomobject]@{ Label = ('OneDrive-' + $kind + '-' + $k.PSChildName); Path = [string]$p.UserFolder; Final = [LotRadarQA.PathInfo]::Final([string]$p.UserFolder); Verified = $true })
            }
        }
    }
    foreach ($name in @('OneDrive', 'OneDriveConsumer', 'OneDriveCommercial')) {
        $v = [Environment]::GetEnvironmentVariable($name)
        if ($v -and (Test-Path -LiteralPath $v -PathType Container)) {
            $f = [LotRadarQA.PathInfo]::Final($v)
            $dup = @($list | Where-Object { $_.Final -and $f -and $_.Final.Equals($f, [StringComparison]::OrdinalIgnoreCase) })
            if ($dup.Count -eq 0) { [void]$list.Add([pscustomobject]@{ Label = ('env-' + $name + '-unverified'); Path = $v; Final = $f; Verified = $false }) }
        }
    }
    return @($list)
}
# LOCAL_ONLY | IN_ONEDRIVE | IN_CLOUD_SYNC | UNKNOWN, judged on the canonical path (junctions/symlinks resolved).
function Get-PathClass([string]$Path, $Roots) {
    $probe = $Path; $tail = ''
    while ($probe -and -not (Test-Path -LiteralPath $probe)) {
        $leaf = Split-Path -Leaf $probe
        if ($tail) { $tail = $leaf + '\' + $tail } else { $tail = $leaf }
        $probe = Split-Path -Parent $probe
    }
    $present = ($tail -eq '')
    if (-not $probe) { return [pscustomobject]@{ Class = 'UNKNOWN'; Present = $present; Why = 'no existing ancestor' } }
    $final = [LotRadarQA.PathInfo]::Final($probe)
    if (-not $final) { return [pscustomobject]@{ Class = 'UNKNOWN'; Present = $present; Why = 'could not resolve the real path' } }
    if ($tail) { $final = $final.TrimEnd('\') + '\' + $tail }
    $kinds = @()
    $walk = $probe
    while ($walk -and $walk.Length -gt 3) { $kinds += (Get-Kind $walk); $walk = Split-Path -Parent $walk }
    $linkNote = ''
    if (@($kinds | Where-Object { $_ -eq 'junction' -or $_ -eq 'symlink' }).Count -gt 0) { $linkNote = ' (reached through a junction/symlink)' }
    foreach ($r in $Roots) {
        $rf = $r.Final
        if (-not $rf) { $rf = $r.Path }
        if (Test-Under $final $rf) { return [pscustomobject]@{ Class = 'IN_ONEDRIVE'; Present = $present; Why = ('real path is inside ' + $r.Label + $linkNote) } }
    }
    if ($kinds -contains 'cloud') { return [pscustomobject]@{ Class = 'IN_CLOUD_SYNC'; Present = $present; Why = 'a parent folder is a cloud-sync placeholder (other provider)' } }
    if ($kinds -contains 'unreadable') { return [pscustomobject]@{ Class = 'UNKNOWN'; Present = $present; Why = 'a parent folder could not be inspected' } }
    return [pscustomobject]@{ Class = 'LOCAL_ONLY'; Present = $present; Why = ('real path is outside every OneDrive root' + $linkNote) }
}
function Read-HarnessRows([string]$JsonPath) {
    try { return @(([IO.File]::ReadAllText($JsonPath) | ConvertFrom-Json).results) } catch { return @() }
}
function Get-Counts($Rows) {
    return ('PASS=' + @($Rows | Where-Object { $_.Status -eq 'PASS' }).Count + ' FAIL=' + @($Rows | Where-Object { $_.Status -eq 'FAIL' }).Count + ' SKIP=' + @($Rows | Where-Object { $_.Status -eq 'SKIP' }).Count)
}
function Get-Row($Rows, [string]$Id) {
    $r = @($Rows | Where-Object { $_.Id -eq $Id }) | Select-Object -First 1
    if (-not $r) { return 'not reported' }
    $d = ([string]$r.Detail -replace '\s+', ' ')
    if ($d.Length -gt 400) { $d = $d.Substring(0, 400) + '...' }
    return ([string]$r.Status + ' - ' + $d)
}
function Invoke-HarnessPass([string]$Zip, [string]$Extract) {
    $before = @(Get-ChildItem -LiteralPath $resultsDir -Filter 'LotRadar-WindowsTest-*.json' -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
    $a = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $harness, '-PackageZip', $Zip, '-OutDir', $resultsDir)
    if ($Extract) { $a += @('-ExtractTo', $Extract) }
    & $psExe @a
    $code = $LASTEXITCODE
    $json = @(Get-ChildItem -LiteralPath $resultsDir -Filter 'LotRadar-WindowsTest-*.json' | Where-Object { $before -notcontains $_.FullName } | Sort-Object LastWriteTime | Select-Object -Last 1)
    $rows = @()
    if ($json.Count -gt 0) { $rows = Read-HarnessRows $json[0].FullName }
    return [pscustomobject]@{ Exit = $code; Rows = $rows }
}

$lines = New-Object System.Collections.ArrayList
function Note([string]$Text) { [void]$lines.Add($Text); Say $Text }
$failures = 0

Say ''
Say '=== OneDrive QA mode ===' 'Cyan'
Say 'LotRadar vehicle photos and Facebook photo exports stay local; only the disposable installer-compatibility test fixture is placed in OneDrive.' 'Green'
Note ('Mode            : OneDrive QA (kit commit ' + $info.source_commit + ')')
Note ('Windows         : ' + $os.Caption + ' version ' + $os.Version + ' build ' + $os.BuildNumber + ' (Windows 11: ' + $isWin11 + ')')
Note ('PowerShell      : ' + $PSVersionTable.PSVersion + '; administrator: ' + $isAdmin)
Note ('Package         : ' + $info.package_file + ' sha256=' + $info.package_sha256 + ' build_type=' + $info.build_type)
Note ('Leftover repair : ' + ($script:LeftoverReport -join '; '))

# ---- A. OneDrive detection (read-only)
$roots = @(Get-SyncRoots)
$n = 0
foreach ($r in $roots) { $n++; $script:Redact += ,@($r.Path, ('<' + $r.Label + '>')); if ($r.Final) { $script:Redact += ,@($r.Final, ('<' + $r.Label + '>')) } }
$verifiedRoots = @($roots | Where-Object { $_.Verified })
$client = @(Get-Process -Name 'OneDrive' -ErrorAction SilentlyContinue).Count -gt 0
Note ('OneDrive roots  : ' + $(if ($roots.Count) { (($roots | ForEach-Object { $_.Label }) -join ', ') } else { 'none found' }))
Note ('Sync client     : ' + $(if ($client) { 'OneDrive.exe is running' } else { 'OneDrive.exe is NOT running' }))
foreach ($kf in @(@('Desktop', [Environment]::GetFolderPath('Desktop')), @('Documents', [Environment]::GetFolderPath('MyDocuments')), @('Pictures', [Environment]::GetFolderPath('MyPictures')))) {
    $c = Get-PathClass $kf[1] $roots
    Note ('Known folder    : ' + $kf[0] + ' = ' + $c.Class + ' (' + $c.Why + ')')
}

# ---- B. LOCAL_PHOTO_STORAGE: where the REAL LotRadar keeps photos/exports (read-only; nothing is opened for reading)
$realLocal = [Environment]::GetFolderPath('LocalApplicationData')
$realData = Join-Path $realLocal 'MarketplaceScanner\data'
$storageItems = @(
    @('data root', $realData),
    @('vehicle photos', (Join-Path $realData 'vehicle_photos')),
    @('Facebook photo exports', (Join-Path $realData 'facebook_photos')),
    @('photo selection', (Join-Path $realData 'photo_selection.json')),
    @('database', (Join-Path $realData 'marketplace.sqlite3')),
    @('installed program', (Join-Path $realLocal 'Programs\MarketplaceScanner'))
)
$storageClasses = @()
foreach ($it in $storageItems) {
    $c = Get-PathClass $it[1] $roots
    $storageClasses += $c.Class
    $pres = 'present'
    if (-not $c.Present) { $pres = 'not present yet' }
    Note ('LOCAL_PHOTO_STORAGE ' + $it[0] + ': ' + $c.Class + ' (' + $pres + '; ' + $c.Why + ')')
}
$lnkInfo = 'no Desktop LotRadar shortcut'
$lnkPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'LotRadar.lnk'
if (Test-Path -LiteralPath $lnkPath) {
    $sc = (New-Object -ComObject WScript.Shell).CreateShortcut($lnkPath)
    $std = (Join-Path $realLocal 'Programs\MarketplaceScanner\Launch Marketplace Scanner.cmd')
    if ($sc.TargetPath -ieq $std -and -not $sc.Arguments) { $lnkInfo = 'standard launcher, no extra arguments (bootstrap always uses %LOCALAPPDATA%\MarketplaceScanner\data)' }
    else { $lnkInfo = 'NON-STANDARD shortcut target or arguments: effective data folder could not be confirmed' ; $storageClasses += 'UNKNOWN' }
}
Note ('LOCAL_PHOTO_STORAGE shortcut: ' + $lnkInfo)
$storage = 'LOCAL_ONLY'
if ($storageClasses -contains 'UNKNOWN') { $storage = 'UNKNOWN' }
if (($storageClasses -contains 'IN_ONEDRIVE') -or ($storageClasses -contains 'IN_CLOUD_SYNC')) { $storage = 'IN_ONEDRIVE' }
Note ('LOCAL_PHOTO_STORAGE overall: ' + $storage)
if ($storage -eq 'IN_ONEDRIVE') {
    Say 'WARNING: some real LotRadar storage resolves inside a sync folder. Nothing was moved. This needs a separate, approved migration plan.' 'Red'
    $failures++
} elseif ($storage -eq 'UNKNOWN') { $failures++ }
$resClass = Get-PathClass $resultsDir $roots
Note ('Results folder  : ' + $resClass.Class + ' (logs and the shortcut backup are kept here)')

# ---- C. Local control pass (same tests as the normal kit, package extracted locally)
Say ''
Say 'Step 1 of 2: local control run (package extracted to a local temporary folder). About 1-3 minutes.' 'Cyan'
$local = Invoke-HarnessPass $pkgZip ''
Note ('Local control   : exit ' + $local.Exit + '; ' + (Get-Counts $local.Rows) + '; R3: ' + (Get-Row $local.Rows 'R3'))
if ($local.Exit -ne 0) { $failures++ }
$shortcut1 = Test-ShortcutRestored
Note ('Shortcut after local control: ' + $shortcut1)

# ---- D. OneDrive pass (consent required)
$odStatus = 'NOT TESTED'
$odTestDir = $null
if ($verifiedRoots.Count -eq 0) {
    $odStatus = 'BLOCKED: no OneDrive folder registered for this Windows user (environment variables alone are not proof)'
} elseif (-not $client) {
    $odStatus = 'BLOCKED: OneDrive.exe is not running, so files in OneDrive are not being synced right now'
} else {
    $root = $verifiedRoots[0]
    if ($verifiedRoots.Count -gt 1) {
        Say ''
        $i = 0
        foreach ($r in $verifiedRoots) { $i++; Say ('  ' + $i + ') ' + $r.Label) }
        if ($Yes) {
            # no prompt: prefer the personal OneDrive, otherwise the first one listed
            $personal = @($verifiedRoots | Where-Object { $_.Label -like 'OneDrive-Personal-*' })
            if ($personal.Count -gt 0) { $root = $personal[0] }
            Say ('Using ' + $root.Label + ' (more than one OneDrive is signed in).') 'Yellow'
        } else {
            $pick = Read-Host 'More than one OneDrive is signed in. Type the number to use for the test'
            $num = 0
            if ([int]::TryParse($pick, [ref]$num) -and $num -ge 1 -and $num -le $verifiedRoots.Count) { $root = $verifiedRoots[$num - 1] } else { $root = $null }
        }
    }
    if (-not $root) {
        $odStatus = 'BLOCKED: no OneDrive selected'
    } else {
        Say ''
        Say ('Step 2 of 2 creates ONE temporary folder in ' + $root.Label + ':') 'Yellow'
        Say '   "LotRadar QA TEST ONLY <random>"  containing only the synthetic test installer (no real data, no photos).' 'Yellow'
        Say 'OneDrive may upload these test files while the test runs. The folder is deleted at the end' 'Yellow'
        Say '(OneDrive may keep it in its online recycle bin for a while). Your OneDrive settings are not changed.' 'Yellow'
        Say 'LotRadar vehicle photos and Facebook photo exports stay local; only the disposable installer-compatibility test fixture is placed in OneDrive.' 'Green'
        if (-not (Confirm-Start 'OneDrive test')) {
            $odStatus = 'NOT TESTED: Owner declined the OneDrive write'
        } else {
            $rootFinal = $root.Final
            if (-not $rootFinal) { $rootFinal = $root.Path }
            $odTestDir = Join-Path $rootFinal ('LotRadar QA TEST ONLY ' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
            $odParent = $rootFinal
            # ownership record (token marker + local ledger) so an interrupted run can be recognised and removed safely
            [void](New-QAOwnedFolder $odTestDir 'onedrive' (Join-Path $qaHome 'owned') 'Disposable LotRadar QA OneDrive test folder. Synthetic files only.')
            [IO.File]::WriteAllText((Join-Path $odTestDir 'LOTRADAR_QA_TEST_FOLDER.txt'), 'Disposable LotRadar QA test folder. Synthetic files only. Safe to delete.', (New-Object System.Text.UTF8Encoding $false))
            $odClass = Get-PathClass $odTestDir $roots
            Note ('OneDrive test folder: ' + $odClass.Class + ' (' + $odClass.Why + ')')
            if ($odClass.Class -ne 'IN_ONEDRIVE') {
                $odStatus = 'BLOCKED: the test folder did not resolve inside OneDrive'
            } else {
                # D1. synthetic path-containment checks of the classifier itself
                $pcLocal = Join-Path $realLocal ('Temp\LotRadar QA paths ' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
                $junction = Join-Path $pcLocal 'junction-data'
                try {
                    New-Item -ItemType Directory -Path (Join-Path $pcLocal 'data\vehicle_photos'), (Join-Path $odTestDir 'custom-data\vehicle_photos'), (Join-Path $odTestDir 'junction-target\vehicle_photos') -Force | Out-Null
                    $pc = @(
                        @('PC1 default-style local data root', (Join-Path $pcLocal 'data\vehicle_photos'), 'LOCAL_ONLY'),
                        @('PC2 custom --data-dir inside OneDrive', (Join-Path $odTestDir 'custom-data\vehicle_photos'), 'IN_ONEDRIVE')
                    )
                    foreach ($t in $pc) {
                        $c = Get-PathClass $t[1] $roots
                        $ok = ($c.Class -eq $t[2])
                        if (-not $ok) { $failures++ }
                        Note ($t[0] + ': expected ' + $t[2] + ', got ' + $c.Class + ' -> ' + $(if ($ok) { 'PASS' } else { 'FAIL' }))
                    }
                    $mk = Invoke-Native ('mklink /J "' + $junction + '" "' + (Join-Path $odTestDir 'junction-target') + '"')
                    if ($mk.Code -eq 0) {
                        $c = Get-PathClass (Join-Path $junction 'vehicle_photos') $roots
                        $ok = ($c.Class -eq 'IN_ONEDRIVE')
                        if (-not $ok) { $failures++ }
                        Note ('PC3 local junction into OneDrive: expected IN_ONEDRIVE, got ' + $c.Class + ' -> ' + $(if ($ok) { 'PASS' } else { 'FAIL' }))
                    } else { Note ('PC3 local junction into OneDrive: SKIP (mklink /J failed: ' + $mk.Output.Trim() + ')') }
                } finally {
                    if ((Test-Path -LiteralPath $junction) -and ((Get-Kind $junction) -eq 'junction')) { [IO.Directory]::Delete($junction) }
                    # exactly the two folders created above, non-recursively (the junction was removed first)
                    foreach ($pd in @((Join-Path $pcLocal 'data\vehicle_photos'), (Join-Path $pcLocal 'data'), $pcLocal)) {
                        if ((Test-Path -LiteralPath $pd) -and ((Get-Kind $pd) -eq 'none')) { try { [IO.Directory]::Delete($pd, $false) } catch { Note ('NOTE: test folder not removed (safe to delete by hand): ' + (Split-Path -Leaf $pcLocal)) } }
                    }
                }
                # D2. installer compatibility with the package extracted INSIDE OneDrive (installed copy stays in the local sandbox)
                $odZip = Join-Path $odTestDir $info.package_file
                Copy-Item -LiteralPath $pkgZip -Destination $odZip
                $zipOk = ((Get-Sha $odZip) -eq [string]$info.package_sha256)
                Note ('Package copy in OneDrive: checksum ' + $(if ($zipOk) { 'OK' } else { 'MISMATCH' }))
                if (-not $zipOk) { $failures++ }
                Say ''
                Say 'Step 2 of 2: OneDrive run (package extracted inside the OneDrive test folder). About 2-5 minutes.' 'Cyan'
                $od = Invoke-HarnessPass $odZip $odTestDir
                Note ('OneDrive run    : exit ' + $od.Exit + '; ' + (Get-Counts $od.Rows))
                Note ('  OD0 ' + (Get-Row $od.Rows 'OD0'))
                Note ('  OD1 ' + (Get-Row $od.Rows 'OD1'))
                Note ('  T02 ' + (Get-Row $od.Rows 'T02'))
                Note ('  T03 ' + (Get-Row $od.Rows 'T03'))
                Note ('  R1  ' + (Get-Row $od.Rows 'R1'))
                Note ('  R3  ' + (Get-Row $od.Rows 'R3'))
                Note ('  R6  ' + (Get-Row $od.Rows 'R6'))
                Note ('  OD2 ' + (Get-Row $od.Rows 'OD2'))
                Note ('  OD3 ' + (Get-Row $od.Rows 'OD3'))
                $zipAfter = ((Test-Path -LiteralPath $odZip) -and ((Get-Sha $odZip) -eq [string]$info.package_sha256))
                Note ('Package copy after OneDrive run: checksum ' + $(if ($zipAfter) { 'unchanged' } else { 'CHANGED or missing' }))
                if (-not $zipAfter) { $failures++ }
                $t03 = @($od.Rows | Where-Object { $_.Id -eq 'T03' }) | Select-Object -First 1
                $od0 = [string](Get-Row $od.Rows 'OD0')
                $od2 = [string](Get-Row $od.Rows 'OD2')
                if ($od.Exit -eq 0 -and ($od0 -match 'dir:cloud') -and ($od2 -like 'PASS*')) {
                    $odStatus = 'PASS: installed from a OneDrive-extracted package whose folders were cloud-tagged, into the local sandbox; full suite FAIL=0; cloud-tagged destination still refused'
                } elseif ($od.Exit -eq 0) {
                    $odStatus = 'INCONCLUSIVE (not a pass): the suite passed but OneDrive never cloud-tagged the package, or OD2 did not run'
                    $failures++
                } elseif ($t03 -and $t03.Status -eq 'FAIL' -and ([string]$t03.Detail -match 'link/reparse') -and ($od0 -match 'dir:cloud')) {
                    $odStatus = 'SAFE REFUSAL (compatibility FAIL): the installer refuses OneDrive cloud folders as if they were links. Nothing was installed or changed. Reported to the Architect; installer not modified.'
                    $failures++
                } else {
                    $odStatus = 'FAIL: see the OneDrive run log'
                    $failures++
                }
                $shortcut2 = Test-ShortcutRestored
                Note ('Shortcut after OneDrive run: ' + $shortcut2)
            }
            # cleanup: exactly the folder created in THIS run (consented above), only if its ownership still checks out
            # and nothing inside is a link; file-by-file, never recursive. Otherwise it is left for manual review.
            if ($odTestDir -and (Test-Path -LiteralPath $odTestDir)) {
                $safeShas = @()
                if (Test-Path -LiteralPath $desktopLnk -PathType Leaf) { $safeShas += (Get-Sha $desktopLnk) }
                $own = Test-QAOwnedFolder $odTestDir 'onedrive' $odParent @(Read-QALedger (Join-Path $qaHome 'owned')) $safeShas
                if ($own.Owned) { $res = Remove-QAOwnedFolder $own $odParent } else { $res = ('left in place: ' + $own.Reason) }
                if ($res -ne 'deleted') { $res = $res + ' (delete "' + (Split-Path -Leaf $odTestDir) + '" in OneDrive by hand after checking it)' }
                Note ('OneDrive test folder cleanup: ' + $res)
            }
        }
    }
}
Note ('OneDrive extraction: ' + $odStatus)
Note 'Not tested here : online-only (dehydrated) placeholders (would need forced dehydration), non-ASCII folder names, sync-race/locked-file injection.'
$finalShortcut = Test-ShortcutRestored
Note ('Desktop shortcut: ' + $finalShortcut)
if ($finalShortcut -like 'NOT RESTORED*') { $failures++ }

# ---- E. sanitized evidence
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
foreach ($f in @(Get-ChildItem -LiteralPath $resultsDir -File | Where-Object { $_.Name -like 'LotRadar-WindowsTest-*' })) {
    [IO.File]::WriteAllText((Join-Path $resultsDir ('SANITIZED-' + $f.Name)), (Protect-Text ([IO.File]::ReadAllText($f.FullName))), $utf8NoBom)
}
$summaryText = Protect-Text (('LotRadar OneDrive QA summary' + "`r`n") + ($lines -join "`r`n"))
[IO.File]::WriteAllText((Join-Path $resultsDir 'SUMMARY.txt'), $summaryText + "`r`n", $utf8NoBom)
Say ''
Say ('Results are in this LOCAL folder (not in OneDrive): ' + (Protect-Text $resultsDir)) 'Green'
Say 'Send back ONLY: SUMMARY.txt and the SANITIZED-... files. Do not send the shortcut-backup folder or the other files.' 'Green'
try { Start-Process -FilePath 'explorer.exe' -ArgumentList ('"' + $resultsDir + '"') } catch { }
# NOTE: this file is dot-sourced; 'exit' here would only end this file and the caller would carry on.
# Hand the result back instead; Run-QAKit.ps1 exits with it immediately.
if ($failures -gt 0) { $script:OneDriveExit = 1 } else { $script:OneDriveExit = 0 }
return
