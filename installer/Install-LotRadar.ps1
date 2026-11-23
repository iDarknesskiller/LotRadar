# LotRadar user-level installer: no admin rights needed.
# PowerShell 5.1+; code-only update, saved user data is NEVER touched.
$ErrorActionPreference = 'Stop'
$program = $null
$stageDir = $null
$previousDir = $null
$swapped = $false
$success = $false
$installLock = $null
$launchLock = $null

# DESTINATION guard (install target, its parent, backups, staging): unchanged and strict.
# True for junctions/symlinks and for any other reparse-point DIRECTORY. Reparse-point FILES with other tags
# (e.g. OneDrive cloud placeholders) are allowed because their content is SHA-256 verified.
function Test-UnsafeLink([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) { return $false }
    if ($item.LinkType -eq 'Junction' -or $item.LinkType -eq 'SymbolicLink') { return $true }
    return [bool]$item.PSIsContainer
}

# Zero-touch DESTINATION preflight helper. GetFileAttributes describes the entry itself (a link is not followed),
# so a dangling junction is still seen. A missing entry is fine; any other error is not caught (fails closed).
function Test-ReparseEntryAt([string]$Path) {
    try { $a = [IO.File]::GetAttributes($Path) }
    catch [IO.FileNotFoundException] { return $false }
    catch [IO.DirectoryNotFoundException] { return $false }
    return (($a -band [IO.FileAttributes]::ReparsePoint) -ne 0)
}

# Exact reparse tag via GetFileInformationByHandleEx(FileAttributeTagInfo). The entry itself is opened
# (FILE_FLAG_OPEN_REPARSE_POINT, FILE_READ_ATTRIBUTES only): a link is never followed and a cloud
# placeholder is never hydrated. Compiled in memory on first use only (no download, no elevation).
$script:ReparseTagSource = @'
using System; using System.ComponentModel; using System.Runtime.InteropServices; using Microsoft.Win32.SafeHandles;
namespace LotRadarInstaller {
  public static class ReparseTag {
    [StructLayout(LayoutKind.Sequential)] struct FILE_ATTRIBUTE_TAG_INFO { public uint FileAttributes; public uint ReparseTag; }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern SafeFileHandle CreateFileW(string name, uint access, uint share, IntPtr sa, uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool GetFileInformationByHandleEx(SafeFileHandle h, int infoClass, out FILE_ATTRIBUTE_TAG_INFO info, uint size);
    // 0 = not a reparse point. Throws when the entry cannot be opened or queried (callers fail closed).
    public static uint Get(string path) {
      using (SafeFileHandle h = CreateFileW(path, 0x80, 7, IntPtr.Zero, 3, 0x02000000 | 0x00200000, IntPtr.Zero)) {
        if (h.IsInvalid) throw new Win32Exception(Marshal.GetLastWin32Error());
        FILE_ATTRIBUTE_TAG_INFO info;
        if (!GetFileInformationByHandleEx(h, 9, out info, (uint)Marshal.SizeOf(typeof(FILE_ATTRIBUTE_TAG_INFO)))) throw new Win32Exception(Marshal.GetLastWin32Error());
        return ((info.FileAttributes & 0x400) != 0) ? info.ReparseTag : 0;
      }
    }
    // IO_REPARSE_TAG_CLOUD .. IO_REPARSE_TAG_CLOUD_F = 0x9000001A + n*0x1000 (n = 0..15), i.e. OneDrive/Cloud Files placeholders.
    public static bool IsCloud(uint tag) { return (tag & 0xFFFF0FFF) == 0x9000001A; }
  }
}
'@

# SOURCE guard: ONLY for the extracted, read-only installer package (whose every file is SHA-256 verified).
# A Cloud Files placeholder (OneDrive Files On-Demand, IO_REPARSE_TAG_CLOUD*) is accepted; every other reparse point
# (junction/mount point, symlink, unknown or unreadable tag, attribute without a tag) is refused. Fails closed.
# Never use this for the install target, staging, backups or runtime: those use Test-UnsafeLink.
function Test-UnsafeSourceEntry([string]$Path) {
    $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) { return $false }
    try {
        if (-not ('LotRadarInstaller.ReparseTag' -as [type])) { Add-Type -TypeDefinition $script:ReparseTagSource }
        $tag = [LotRadarInstaller.ReparseTag]::Get($Path)
    } catch {
        throw ('Could not check a link/reparse point inside the installer package (' + $_.Exception.Message + '). Extract the installer ZIP to a normal local folder such as Downloads (not a cloud or network folder) and run it again: ' + $Path)
    }
    if ($tag -ne 0 -and [LotRadarInstaller.ReparseTag]::IsCloud($tag)) { return $false }
    return $true
}
# Every existing segment from the payload folder down to $Path must pass the SOURCE guard.
function Assert-SafeSourcePath([string]$PayloadFull, [string]$Path) {
    $walk = $PayloadFull
    foreach ($segment in $Path.Substring($PayloadFull.Length + 1).Split('\')) {
        $walk = Join-Path $walk $segment
        if ((Test-Path -LiteralPath $walk) -and (Test-UnsafeSourceEntry $walk)) { throw ('Refusing a link/reparse point inside the package: ' + $walk) }
    }
}

try {
    if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA could not be found.' }
    $payloadDir = Join-Path $PSScriptRoot 'MarketplaceScanner'
    $manifestPath = Join-Path $PSScriptRoot 'Install-Manifest.json'
    # The extracted package folder and its manifest are SOURCE entries (OneDrive placeholders allowed, links refused).
    if (Test-UnsafeSourceEntry $PSScriptRoot) { throw ('Refusing to install: the installer folder is a link/reparse point: ' + $PSScriptRoot) }
    if ((Test-Path -LiteralPath $manifestPath) -and (Test-UnsafeSourceEntry $manifestPath)) { throw ('Refusing to install: the manifest is a link/reparse point: ' + $manifestPath) }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.product -ne 'LotRadar / Marketplace Scanner') { throw 'Invalid installer manifest.' }
    # Reject manifests that could write outside the staging folder or are malformed (hardening added to the ported installer).
    if (-not $manifest.payload_files -or @($manifest.payload_files).Count -lt 1) { throw 'Installer manifest lists no payload files.' }
    $seenPaths = @{}
    foreach ($item in $manifest.payload_files) {
        $rel = [string]$item.path
        $parts = $rel -split '[\\/]'
        if ([string]::IsNullOrWhiteSpace($rel) -or $rel.Contains(':') -or ($parts -contains '') -or ($parts -contains '.') -or ($parts -contains '..')) {
            throw ('Unsafe path in installer manifest: ' + $rel)
        }
        foreach ($part in $parts) {
            if ($part -imatch '^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?$' -or $part.EndsWith('.') -or $part.EndsWith(' ')) {
                throw ('Unsafe path segment in installer manifest: ' + $rel)
            }
        }
        if ($seenPaths.ContainsKey($rel.ToLowerInvariant())) { throw ('Duplicate path in installer manifest: ' + $rel) }
        $seenPaths[$rel.ToLowerInvariant()] = $true
        if ([string]$item.sha256 -cnotmatch '^[0-9a-f]{64}$') { throw ('Invalid checksum entry in installer manifest for: ' + $rel) }
    }
    if ($manifest.package_version) {
        Write-Host ('Package ' + $manifest.package_version + ' (' + $manifest.build_type + ', source ' + $manifest.source_commit + ')')
    }
    if ($manifest.build_type -and $manifest.build_type -ne 'production') {
        Write-Warning 'This is a NON-PRODUCTION package (see build_type in Install-Manifest.json). Photo export needs the branding images.'
    }

    $parentDir = Join-Path $env:LOCALAPPDATA 'Programs'
    $program = Join-Path $parentDir 'MarketplaceScanner'
    $userRoot = Join-Path $env:LOCALAPPDATA 'MarketplaceScanner'
    $runtimeDir = Join-Path $userRoot 'runtime'
    $backupRoot = Join-Path $userRoot 'ProgramBackups'
    # Zero-touch preflight: nothing (runtime folder, lock files, backups) may be created through a link. Every per-user
    # destination folder that already exists must be a real folder BEFORE the runtime folder and locks are created.
    # The full destination check below still runs again while the locks are held (lock order unchanged).
    foreach ($guarded in @($parentDir, $program, $userRoot, $runtimeDir, $backupRoot)) {
        if (Test-ReparseEntryAt $guarded) {
            throw ('Refusing to install: ' + $guarded + ' is a link/reparse point (junction/symlink). Use a normal folder.')
        }
    }
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    # Prevent two installers from racing without touching program data.
    try {
        $installLock = [IO.File]::Open((Join-Path $runtimeDir 'lotradar-install.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    } catch [IO.IOException] {
        throw 'Another LotRadar installer is running. Close it and try again.'
    }
    # The launcher/bootstrap holds marketplace-launch.lock while LotRadar is starting or running. Taking it here (never waiting)
    # means an install cannot overlap a launch, and a launch during an install fails safely. Order: install lock, then launch lock.
    try {
        $launchLock = [IO.File]::Open((Join-Path $runtimeDir 'marketplace-launch.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    } catch [IO.IOException] {
        throw 'LotRadar is running or starting (its launch lock is held). Close LotRadar completely, then run the installer again.'
    }

    # Never replace live source while the local server could still be importing code.
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $probe = $client.BeginConnect([Net.IPAddress]::Loopback, 8765, $null, $null)
        $active = $probe.AsyncWaitHandle.WaitOne(350)
        if ($active -and $client.Connected) {
            throw 'Port 8765 is active. Close LotRadar completely before installing.'
        }
    } finally { $client.Dispose() }

    # Confinement: the payload folder must not be a link (SOURCE guard: a OneDrive placeholder folder is allowed);
    # the install/backup parents must be real folders (DESTINATION guard, unchanged).
    if (-not (Test-Path -LiteralPath $payloadDir -PathType Container)) { throw 'Installer payload folder (MarketplaceScanner) is missing.' }
    if (Test-UnsafeSourceEntry $payloadDir) { throw ('Refusing to install: the payload folder is a link/reparse point: ' + $payloadDir) }
    $payloadFull = [IO.Path]::GetFullPath($payloadDir).TrimEnd('\')
    foreach ($guarded in @($parentDir, $program, $backupRoot)) {
        if ((Test-Path -LiteralPath $guarded) -and (Test-UnsafeLink $guarded)) {
            throw ('Refusing to install: ' + $guarded + ' is a link/reparse point (junction/symlink). Use a normal folder.')
        }
    }
    # Validate every source/asset file, including recovered branding, before any changes.
    foreach ($item in $manifest.payload_files) {
        $file = Join-Path $payloadDir ([string]$item.path).Replace('/', '\')
        $full = [IO.Path]::GetFullPath($file)
        if (-not $full.StartsWith($payloadFull + '\', [StringComparison]::OrdinalIgnoreCase)) { throw ('Payload path escapes the package folder: ' + $item.path) }
        Assert-SafeSourcePath $payloadFull $full
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
            throw ('Installer is missing: ' + $item.path)
        }
        if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$item.sha256) {
            throw ('Installer checksum mismatch: ' + $item.path)
        }
    }
    Write-Host ('Verified ' + $manifest.payload_files.Count + ' program files.') -ForegroundColor Green
    New-Item -ItemType Directory -Path $parentDir -Force | Out-Null
    $stageDir = Join-Path $parentDir ('.MarketplaceScanner-stage-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $stageDir -Force | Out-Null
    foreach ($item in $manifest.payload_files) {
        $relPath = ([string]$item.path).Replace('/', '\')
        $srcFile = Join-Path $payloadDir $relPath
        $dstFile = Join-Path $stageDir $relPath
        $dstFolder = Split-Path -Parent $dstFile
        if (-not (Test-Path -LiteralPath $dstFolder)) { New-Item -ItemType Directory -Path $dstFolder -Force | Out-Null }
        # Re-check the source path right before copying (narrows a swap-in-a-link race); the staged hash is checked below.
        Assert-SafeSourcePath $payloadFull ([IO.Path]::GetFullPath($srcFile))
        Copy-Item -LiteralPath $srcFile -Destination $dstFile -Force
        if ((Get-FileHash -LiteralPath $dstFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$item.sha256) {
            throw ('Staging checksum mismatch: ' + $item.path)
        }
    }

    # Re-verify the whole staged tree right before the swap: no links, exactly the manifest files, hashes still match.
    $stagedItems = @(Get-ChildItem -LiteralPath $stageDir -Recurse -Force)
    foreach ($staged in $stagedItems) {
        if (Test-UnsafeLink $staged.FullName) { throw ('Unexpected link in staging folder: ' + $staged.FullName) }
    }
    if (@($stagedItems | Where-Object { -not $_.PSIsContainer }).Count -ne @($manifest.payload_files).Count) { throw 'Staging folder does not contain exactly the manifest files.' }
    foreach ($item in $manifest.payload_files) {
        $stagedFile = Join-Path $stageDir ([string]$item.path).Replace('/', '\')
        if ((Get-FileHash -LiteralPath $stagedFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$item.sha256) { throw ('Staging re-check mismatch: ' + $item.path) }
    }

    # Only the Program folder is replaced. Do NOT read, copy, or overwrite %LOCALAPPDATA%\MarketplaceScanner\data.
    if (Test-Path -LiteralPath $program) {
        New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
        $previousDir = Join-Path $backupRoot ('Before-HomeTransfer-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,6))
        [IO.Directory]::Move($program, $previousDir)
        Write-Host ('Backed up older program to ' + $previousDir)
    }
    try {
        [IO.Directory]::Move($stageDir, $program)
        $swapped = $true
        $stageDir = $null
    } catch {
        if ($previousDir -and (Test-Path -LiteralPath $previousDir) -and -not (Test-Path -LiteralPath $program)) {
            [IO.Directory]::Move($previousDir, $program)
            $previousDir = $null
        }
        throw
    }

    Write-Host 'Installed program:' $program -ForegroundColor Green
    Write-Host 'Existing scanner data was not modified.' -ForegroundColor Green
    # Shortcuts are optional: failed shortcut creation does not damage installed program.
    $shortcutTarget = Join-Path $program 'Launch Marketplace Scanner.cmd'
    $iconPath = Join-Path $program 'LotRadar.ico'
    foreach ($folder in @([Environment]::GetFolderPath('Desktop'), (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'))) {
        if (-not $folder) { continue }
        try {
            New-Item -ItemType Directory -Path $folder -Force | Out-Null
            $shell = New-Object -ComObject WScript.Shell
            $link = $shell.CreateShortcut((Join-Path $folder 'LotRadar.lnk'))
            $link.TargetPath = $shortcutTarget
            $link.WorkingDirectory = $program
            $link.Description = 'LotRadar Marketplace Scanner'
            if (Test-Path -LiteralPath $iconPath) { $link.IconLocation = $iconPath }
            $link.Save()
        } catch {
            Write-Warning ('Could not create a shortcut: ' + $_.Exception.Message)
        }
    }
    $success = $true
    Write-Host ''
    Write-Host 'INSTALL COMPLETE.' -ForegroundColor Green
    Write-Host 'Launch LotRadar from the desktop shortcut. First launch installs Python/Chromium if missing (internet required).'
    Write-Host 'Chrome reader: open chrome://extensions, turn on Developer Mode, Load unpacked from:'
    Write-Host (Join-Path $program 'chrome-extension')
    Write-Host 'Data: %LOCALAPPDATA%\MarketplaceScanner\data (preserved, not in this installer)'
} catch {
    Write-Host ('INSTALL ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    # Failure after the swap: put the previous PROGRAM folder back, or remove a failed first install. Never touches data.
    if (-not $success -and $swapped) {
        try {
            New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
            $failedDir = Join-Path $backupRoot ('Failed-install-' + [Guid]::NewGuid().ToString('N'))
            if (Test-Path -LiteralPath $program) { [IO.Directory]::Move($program, $failedDir) }
            if ($previousDir -and (Test-Path -LiteralPath $previousDir)) {
                [IO.Directory]::Move($previousDir, $program)
                Write-Host 'Original program has been restored.' -ForegroundColor Yellow
            } else {
                Write-Host ('The failed first installation was moved to ' + $failedDir + '; no program is installed.') -ForegroundColor Yellow
            }
        } catch {
            Write-Host ('ROLLBACK ERROR: ' + $_.Exception.Message) -ForegroundColor Red
        }
    }
} finally {
    if ($stageDir -and (Test-Path -LiteralPath $stageDir)) {
        try { Remove-Item -LiteralPath $stageDir -Recurse -Force } catch { }
    }
    if ($launchLock) { $launchLock.Dispose() }
    if ($installLock) { $installLock.Dispose() }
}
if (-not $success) { exit 1 }
exit 0
