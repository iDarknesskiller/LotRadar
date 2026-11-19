# LotRadar QA kit: SAFE repair of leftovers from an interrupted test run (TEST-ONLY).
# Dot-sourced by Run-QAKit.ps1 and LotRadarQA.CleanupSelfTest.ps1. Defines functions only; touches nothing on load.
#
# A folder is treated as "created by this kit" ONLY if ALL of these hold:
#   1. its name is exactly "LotRadar Test Sandbox <8 hex>" (local) or "LotRadar QA TEST ONLY <8 hex>" (OneDrive);
#   2. it is a direct child of the expected parent, checked on the canonical (final) path;
#   3. the folder itself is not a junction/symlink (OneDrive: a Cloud Files placeholder folder is allowed);
#   4. it holds LOTRADAR_QA_OWNER.txt with a random 128-bit token, AND the local, unsynced ledger
#      (%LOCALAPPDATA%\LotRadar QA Results\owned\<token>.owned) records the same token, kind and exact path;
#   5. nothing inside it is a junction, symlink or other link (OneDrive: Cloud Files placeholders are allowed);
#   6. it does not hold the only copy of a Desktop shortcut backup.
# Even then it is deleted only after the person types D for THAT folder (Enter or no console = keep).
# Deletion is file-by-file, bottom-up, never recursive: before each delete every parent folder up to the leftover
# is re-checked for links, and the run stops at the first surprise. Nothing is ever followed through a link.
# Anything that fails a check is reported with manual instructions and left exactly as it is.

$script:QAOwnerMarker = 'LOTRADAR_QA_OWNER.txt'
$script:QANamePattern = @{ sandbox = '^LotRadar Test Sandbox [0-9a-f]{8}$'; onedrive = '^LotRadar QA TEST ONLY [0-9a-f]{8}$' }
$script:QAMaxEntries = 200000

$qaCleanupNativeSource = @'
using System; using System.Text; using System.Runtime.InteropServices; using Microsoft.Win32.SafeHandles;
namespace LotRadarQA {
  public static class OwnedFs {
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
    // Canonical path of the entry ITSELF (FILE_FLAG_OPEN_REPARSE_POINT: a link is not followed). null if unreadable.
    public static string Final(string path) { return FinalPath(path, 0x02000000 | 0x00200000); }
    // Canonical path with links followed (used only for the trusted parent folder).
    public static string FinalFollow(string path) { return FinalPath(path, 0x02000000); }
    static string FinalPath(string path, uint flags) {
      using (SafeFileHandle h = CreateFileW(path, 0, 7, IntPtr.Zero, 3, flags, IntPtr.Zero)) {
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
    // Reparse tag of the entry itself; 0 = not a reparse point; 0xFFFFFFFF = could not read.
    public static uint Tag(string path) {
      WIN32_FIND_DATAW d; IntPtr h = FindFirstFileW(path.TrimEnd('\\'), out d);
      if (h == new IntPtr(-1)) return 0xFFFFFFFF;
      FindClose(h);
      return ((d.dwFileAttributes & 0x400) != 0) ? d.dwReserved0 : 0;
    }
  }
}
'@

function Initialize-QACleanup {
    if (-not ('LotRadarQA.OwnedFs' -as [type])) { Add-Type -TypeDefinition $qaCleanupNativeSource }
}

function Get-QAEntryKind([string]$Path) {
    # none | cloud | link:<tag hex> | unreadable
    $t = [LotRadarQA.OwnedFs]::Tag($Path)
    if ($t -eq [uint32]0) { return 'none' }
    if ($t -eq [uint32]4294967295) { return 'unreadable' }
    if (($t -band [uint32]4294905855) -eq [uint32]2415919130) { return 'cloud' }
    return ('link:0x' + $t.ToString('X8'))
}

function Test-QAEntryAllowed([string]$Path, [bool]$AllowCloud) {
    # True if the entry is not a link. A Cloud Files placeholder is accepted only when $AllowCloud.
    $attr = [IO.File]::GetAttributes($Path)   # GetFileAttributes: describes the entry itself, never follows a link
    if (($attr -band [IO.FileAttributes]::ReparsePoint) -eq 0) { return $true }
    return ($AllowCloud -and ((Get-QAEntryKind $Path) -eq 'cloud'))
}

function Test-QASamePath([string]$A, [string]$B) {
    if (-not $A -or -not $B) { return $false }
    return $A.TrimEnd('\').Equals($B.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)
}

function New-QAOwnerToken {
    $bytes = New-Object byte[] 16
    $rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return (($bytes | ForEach-Object { $_.ToString('x2') }) -join '')
}

function New-QAOwnedFolder([string]$Path, [string]$Kind, [string]$LedgerDir, [string]$Note) {
    # Creates a NEW folder (refuses if it exists) and records ownership. Returns the token.
    if (Test-Path -LiteralPath $Path) { throw ('Refusing to reuse an existing folder: ' + $Path) }
    $enc = New-Object System.Text.UTF8Encoding $false
    $token = New-QAOwnerToken
    New-Item -ItemType Directory -Path $Path | Out-Null
    [IO.File]::WriteAllText((Join-Path $Path $script:QAOwnerMarker), ('token=' + $token + "`r`nkind=" + $Kind + "`r`n" + $Note + "`r`n"), $enc)
    New-Item -ItemType Directory -Path $LedgerDir -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $LedgerDir ($token + '.owned')), ('token=' + $token + "`r`nkind=" + $Kind + "`r`npath=" + $Path + "`r`ncreated=" + (Get-Date).ToString('o') + "`r`n"), $enc)
    return $token
}

function Read-QALedger([string]$LedgerDir) {
    $out = @()
    if (-not $LedgerDir -or -not (Test-Path -LiteralPath $LedgerDir)) { return $out }
    foreach ($f in @(Get-ChildItem -LiteralPath $LedgerDir -File -Filter '*.owned' -Force -ErrorAction SilentlyContinue)) {
        if ($f.Length -gt 4096) { continue }
        if (($f.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { continue }
        $map = @{}
        foreach ($line in [IO.File]::ReadAllLines($f.FullName)) {
            $i = $line.IndexOf('=')
            if ($i -gt 0) { $map[$line.Substring(0, $i)] = $line.Substring($i + 1) }
        }
        $tok = [string]$map['token']
        if ($tok -notmatch '^[0-9a-f]{32}$') { continue }
        if ($f.Name -ne ($tok + '.owned')) { continue }
        $out += [pscustomobject]@{ Token = $tok; Kind = [string]$map['kind']; Path = [string]$map['path']; File = $f.FullName }
    }
    return $out
}

function Get-QAShortcutTarget([string]$Lnk) {
    try { return [string](New-Object -ComObject WScript.Shell).CreateShortcut($Lnk).TargetPath } catch { return '' }
}

function Get-QASha([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }

function Test-QAOwnedFolder([string]$Dir, [string]$Kind, [string]$Parent, $Ledger, $SafeShas) {
    # Returns an object; Owned=$true only if every ownership and safety check passes. Reads only.
    Initialize-QACleanup
    $name = Split-Path -Leaf $Dir
    $r = [pscustomobject]@{ Path = $Dir; Name = $name; Kind = $Kind; Owned = $false; Reason = ''; Files = @(); Dirs = @(); Bytes = [int64]0; Newest = $null; LedgerFile = '' }
    $allowCloud = ($Kind -eq 'onedrive')
    if ($name -notmatch $script:QANamePattern[$Kind]) { $r.Reason = 'name does not match the kit pattern'; return $r }
    $selfKind = Get-QAEntryKind $Dir
    if (-not ($selfKind -eq 'none' -or ($allowCloud -and $selfKind -eq 'cloud'))) { $r.Reason = ('the folder itself is a link (' + $selfKind + ')'); return $r }
    $parentFinal = [LotRadarQA.OwnedFs]::FinalFollow($Parent)
    $dirFinal = [LotRadarQA.OwnedFs]::Final($Dir)
    if (-not $parentFinal -or -not $dirFinal) { $r.Reason = 'could not read its real path'; return $r }
    if (-not (Test-QASamePath $dirFinal (Join-Path $parentFinal $name))) { $r.Reason = 'its real path is not directly inside the expected folder'; return $r }
    $marker = Join-Path $Dir $script:QAOwnerMarker
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) { $r.Reason = ('no ' + $script:QAOwnerMarker + ' (not created by this kit version)'); return $r }
    if (-not (Test-QAEntryAllowed $marker $allowCloud)) { $r.Reason = 'its owner marker is a link'; return $r }
    if ((Get-Item -LiteralPath $marker -Force).Length -gt 4096) { $r.Reason = 'owner marker too large'; return $r }
    $m = [regex]::Match([IO.File]::ReadAllText($marker), '(?m)^token=([0-9a-f]{32})\r?$')
    if (-not $m.Success) { $r.Reason = 'owner marker has no valid token'; return $r }
    $entry = @($Ledger | Where-Object { $_.Token -eq $m.Groups[1].Value }) | Select-Object -First 1
    if (-not $entry) { $r.Reason = 'its token is not in this PC''s kit ledger'; return $r }
    if ($entry.Kind -ne $Kind) { $r.Reason = 'ledger kind does not match'; return $r }
    if (-not (Test-QASamePath $entry.Path $Dir)) { $r.Reason = 'ledger records a different path for this token'; return $r }
    $r.LedgerFile = $entry.File
    # Walk WITHOUT following links. Any link (other than allowed cloud placeholders) refuses the whole folder.
    $files = New-Object System.Collections.ArrayList
    $dirs = New-Object System.Collections.ArrayList
    $stack = New-Object System.Collections.Stack
    $stack.Push($Dir)
    try {
        while ($stack.Count -gt 0) {
            $d = [string]$stack.Pop()
            foreach ($e in [IO.Directory]::GetFileSystemEntries($d)) {
                if (($files.Count + $dirs.Count) -gt $script:QAMaxEntries) { $r.Reason = 'too many files to check'; return $r }
                if (-not (Test-QAEntryAllowed $e $allowCloud)) { $r.Reason = ('contains a link: ' + $e.Substring($Dir.Length).TrimStart('\') + ' (' + (Get-QAEntryKind $e) + ')'); return $r }
                $attr = [IO.File]::GetAttributes($e)
                if (($attr -band [IO.FileAttributes]::Directory) -ne 0) { [void]$dirs.Add($e); $stack.Push($e) }
                else {
                    [void]$files.Add($e)
                    $fi = New-Object IO.FileInfo $e
                    $r.Bytes += $fi.Length
                    if (-not $r.Newest -or $fi.LastWriteTime -gt $r.Newest) { $r.Newest = $fi.LastWriteTime }
                }
            }
        }
    } catch { $r.Reason = ('could not check every file: ' + $_.Exception.Message); return $r }
    $bk = Join-Path $Dir 'desktop-backup\LotRadar.lnk'
    if (Test-Path -LiteralPath $bk -PathType Leaf) {
        if (@($SafeShas) -notcontains (Get-QASha $bk)) { $r.Reason = 'it holds the only copy of a Desktop shortcut backup'; return $r }
    }
    $r.Files = @($files)
    $r.Dirs = @($dirs)
    $r.Owned = $true
    $r.Reason = 'owned by this kit'
    return $r
}

function Test-QAChainSafe([string]$Path, [string]$Top, [bool]$AllowCloud) {
    # Every folder from $Path's parent up to and including $Top must still be a non-link folder.
    $p = Split-Path -Parent $Path
    while ($true) {
        if (-not (Test-QAEntryAllowed $p $AllowCloud)) { return $false }
        if (Test-QASamePath $p $Top) { return $true }
        $next = Split-Path -Parent $p
        if (-not $next -or (Test-QASamePath $next $p)) { return $false }
        $p = $next
    }
}

function Invoke-QADeleteOne([string]$Path, [bool]$IsDir) {
    # One entry, never recursive. Retries briefly because a sync client may hold a file for a moment.
    for ($i = 1; $i -le 4; $i++) {
        try {
            if ($IsDir) { [IO.Directory]::Delete($Path, $false) } else { [IO.File]::Delete($Path) }
            return
        } catch {
            if ($i -eq 4) { throw }
            Start-Sleep -Seconds 2
        }
    }
}

function Remove-QAOwnedFolder($Info, [string]$Parent) {
    # Bottom-up, one entry at a time, never recursive, re-checking for links before every delete.
    # Returns 'deleted' or a sentence describing where it stopped.
    Initialize-QACleanup
    $allowCloud = ($Info.Kind -eq 'onedrive')
    $top = $Info.Path
    $parentFinal = [LotRadarQA.OwnedFs]::FinalFollow($Parent)
    $dirFinal = [LotRadarQA.OwnedFs]::Final($top)
    if (-not $parentFinal -or -not $dirFinal -or -not (Test-QASamePath $dirFinal (Join-Path $parentFinal $Info.Name))) { return 'stopped: its real path changed since it was checked; nothing deleted' }
    if (-not (Test-QAEntryAllowed $top $allowCloud)) { return 'stopped: the folder became a link; nothing deleted' }
    $n = 0
    try {
        foreach ($f in $Info.Files) {
            if (-not (Test-Path -LiteralPath $f)) { continue }
            if (-not (Test-QAChainSafe $f $top $allowCloud)) { return ('stopped: a folder above ' + $f.Substring($top.Length).TrimStart('\') + ' became a link; ' + $n + ' items deleted, the rest kept') }
            if (-not (Test-QAEntryAllowed $f $allowCloud)) { return ('stopped: ' + $f.Substring($top.Length).TrimStart('\') + ' became a link; ' + $n + ' items deleted, the rest kept') }
            $a = [IO.File]::GetAttributes($f)
            if (($a -band [IO.FileAttributes]::ReadOnly) -ne 0) { [IO.File]::SetAttributes($f, ($a -band (-bnot [IO.FileAttributes]::ReadOnly))) }
            Invoke-QADeleteOne $f $false
            $n++
        }
        $ordered = @($Info.Dirs | Sort-Object -Property @{ Expression = { ($_.Split('\')).Count } } -Descending)
        foreach ($d in $ordered) {
            if (-not (Test-Path -LiteralPath $d)) { continue }
            if (-not (Test-QAChainSafe $d $top $allowCloud) -or -not (Test-QAEntryAllowed $d $allowCloud)) { return ('stopped: ' + $d.Substring($top.Length).TrimStart('\') + ' or a folder above it became a link; ' + $n + ' items deleted, the rest kept') }
            Invoke-QADeleteOne $d $true   # non-recursive: fails if anything unexpected is inside
            $n++
        }
        if (-not (Test-QAEntryAllowed $top $allowCloud)) { return ('stopped: the folder became a link; ' + $n + ' items deleted') }
        Invoke-QADeleteOne $top $true
    } catch { return ('stopped: ' + $_.Exception.Message + '; ' + $n + ' items deleted, the rest kept') }
    if ($Info.LedgerFile -and (Test-Path -LiteralPath $Info.LedgerFile)) { Remove-Item -LiteralPath $Info.LedgerFile -Force }
    return 'deleted'
}

function Invoke-QALeftoverRepair {
    # Returns @{ Lines = report lines; Stop = $null or a message (the kit must not run tests then) }.
    param(
        [string]$TempParent, [string[]]$OneDriveParents, [string]$LedgerDir,
        [string]$DesktopLnk, [string]$OriginalStore, [string]$StandardTarget, [string]$EvidenceDir,
        [scriptblock]$Ask
    )
    Initialize-QACleanup
    $lines = New-Object System.Collections.ArrayList
    $ledger = @(Read-QALedger $LedgerDir)

    # ---- 1. Desktop shortcut
    if (Test-Path -LiteralPath $DesktopLnk -PathType Leaf) {
        $target = Get-QAShortcutTarget $DesktopLnk
        $m = [regex]::Match($target, '^(.*\\LotRadar Test Sandbox [0-9a-f]{8})\\', [Text.RegularExpressions.RegexOptions]::IgnoreCase)
        if (Test-QASamePath $target $StandardTarget) {
            # the real shortcut: keep a verified copy for future repairs
            New-Item -ItemType Directory -Path (Split-Path -Parent $OriginalStore) -Force | Out-Null
            Copy-Item -LiteralPath $DesktopLnk -Destination $OriginalStore -Force
            if ((Get-QASha $OriginalStore) -ne (Get-QASha $DesktopLnk)) { return @{ Lines = $lines; Stop = 'Could not keep a verified copy of your Desktop LotRadar shortcut.' } }
        } elseif ($m.Success) {
            $sandbox = $m.Groups[1].Value
            $known = @($ledger | Where-Object { $_.Kind -eq 'sandbox' -and (Test-QASamePath $_.Path $sandbox) }).Count -gt 0
            if (-not $known) {
                return @{ Lines = $lines; Stop = ('Your Desktop LotRadar.lnk points into a test folder this kit has no record of (' + (Split-Path -Leaf $sandbox) + '). Nothing was changed. Delete that shortcut yourself, reinstall LotRadar to get the real one, then run the kit again.') }
            }
            $source = $null; $from = ''
            $sbk = Join-Path $sandbox 'desktop-backup\LotRadar.lnk'
            foreach ($c in @(@($sbk, 'the interrupted run''s own backup'), @($OriginalStore, 'the kit''s saved copy'))) {
                if (-not $source -and (Test-Path -LiteralPath $c[0] -PathType Leaf) -and (Test-QAEntryAllowed $c[0] $false) -and (Test-QASamePath (Get-QAShortcutTarget $c[0]) $StandardTarget)) { $source = $c[0]; $from = $c[1] }
            }
            New-Item -ItemType Directory -Path $EvidenceDir -Force | Out-Null
            $kept = Join-Path $EvidenceDir 'replaced-test-shortcut.lnk'
            if ($source) {
                Copy-Item -LiteralPath $DesktopLnk -Destination $kept -Force
                Copy-Item -LiteralPath $source -Destination $DesktopLnk -Force
                if ((Get-QASha $DesktopLnk) -ne (Get-QASha $source)) { return @{ Lines = $lines; Stop = 'A leftover TEST shortcut was on the Desktop, but your real shortcut could not be put back (copy did not verify).' } }
                [void]$lines.Add('leftover TEST Desktop shortcut replaced by your standard LotRadar shortcut from ' + $from + ' (verified)')
                if (-not (Test-QASamePath $source $OriginalStore)) {
                    New-Item -ItemType Directory -Path (Split-Path -Parent $OriginalStore) -Force | Out-Null
                    Copy-Item -LiteralPath $DesktopLnk -Destination $OriginalStore -Force
                }
            } else {
                $ans = [string](& $Ask 'A leftover TEST shortcut is on your Desktop (LotRadar.lnk) and no verified copy of your real shortcut was found. Type D and press Enter to delete the test shortcut, or just press Enter to stop')
                if ($ans.Trim() -eq 'D') {
                    Copy-Item -LiteralPath $DesktopLnk -Destination $kept -Force
                    Remove-Item -LiteralPath $DesktopLnk -Force
                    [void]$lines.Add('leftover TEST Desktop shortcut deleted at your request (no verified original existed; reinstall LotRadar to get the real one)')
                } else {
                    return @{ Lines = $lines; Stop = 'A leftover TEST shortcut is on your Desktop and no verified copy of your real shortcut exists. Nothing was changed. Delete Desktop\LotRadar.lnk yourself, reinstall LotRadar, then run the kit again.' }
                }
            }
        } else {
            [void]$lines.Add('Desktop LotRadar.lnk does not point to the standard LotRadar launcher; left untouched and not used for repairs')
        }
    }

    # ---- 2. leftover test folders
    $safe = @()
    if (Test-Path -LiteralPath $DesktopLnk -PathType Leaf) { $safe += (Get-QASha $DesktopLnk) }
    if (Test-Path -LiteralPath $OriginalStore -PathType Leaf) { $safe += (Get-QASha $OriginalStore) }
    $groups = @(,@($TempParent, 'sandbox', 'LotRadar Test Sandbox *'))
    foreach ($odp in @($OneDriveParents)) { if ($odp) { $groups += ,@($odp, 'onedrive', 'LotRadar QA TEST ONLY *') } }
    foreach ($g in $groups) {
        $parent = [string]$g[0]
        if (-not $parent -or -not (Test-Path -LiteralPath $parent)) { continue }
        foreach ($d in @(Get-ChildItem -LiteralPath $parent -Directory -Filter $g[2] -Force -ErrorAction SilentlyContinue)) {
            $info = Test-QAOwnedFolder $d.FullName $g[1] $parent $ledger $safe
            if (-not $info.Owned) {
                [void]$lines.Add('test-looking folder "' + $d.Name + '" left untouched: ' + $info.Reason + '. Check it and delete it by hand only if you are sure.')
                continue
            }
            $mb = [math]::Round($info.Bytes / 1MB, 1)
            $newest = 'none'
            if ($info.Newest) { $newest = $info.Newest.ToString('yyyy-MM-dd HH:mm') }
            $where = 'your Temp folder'
            if ($g[1] -eq 'onedrive') { $where = 'OneDrive (OneDrive may keep it in its online recycle bin for a while)' }
            $ans = [string](& $Ask ('Old test folder from an interrupted run: "' + $d.Name + '" in ' + $where + ': ' + $info.Files.Count + ' files, ' + $mb + ' MB, newest file ' + $newest + '. Type D and press Enter to delete it, or just press Enter to keep it'))
            if ($ans.Trim() -eq 'D') {
                $res = Remove-QAOwnedFolder $info $parent
                [void]$lines.Add('leftover test folder "' + $d.Name + '": ' + $res)
            } else {
                [void]$lines.Add('leftover test folder "' + $d.Name + '": kept (your choice)')
            }
        }
    }

    # ---- 3. forget ledger entries whose folder no longer exists (the ledger only describes kit folders)
    foreach ($e in @(Read-QALedger $LedgerDir)) {
        if ($e.Path -and -not (Test-Path -LiteralPath $e.Path)) { Remove-Item -LiteralPath $e.File -Force -ErrorAction SilentlyContinue }
    }
    return @{ Lines = $lines; Stop = $null }
}

function Read-QAAnswer([string]$Question) {
    # Real console prompt. No console (redirected input) = keep everything.
    if ([Console]::IsInputRedirected) { return '' }
    Write-Host ''
    return (Read-Host $Question)
}
