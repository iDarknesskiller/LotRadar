# LotRadar user-level installer: no admin rights needed.
# PowerShell 5.1+; code-only update, saved user data is NEVER touched.
$ErrorActionPreference = 'Stop'
$program = $null
$stageDir = $null
$previousDir = $null
$swapped = $false
$success = $false
$installLock = $null
try {
    if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA could not be found.' }
    $payloadDir = Join-Path $PSScriptRoot 'MarketplaceScanner'
    $manifestPath = Join-Path $PSScriptRoot 'Install-Manifest.json'
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
        if ($seenPaths.ContainsKey($rel.ToLowerInvariant())) { throw ('Duplicate path in installer manifest: ' + $rel) }
        $seenPaths[$rel.ToLowerInvariant()] = $true
        if ([string]$item.sha256 -notmatch '^[0-9a-f]{64}$') { throw ('Invalid checksum entry in installer manifest for: ' + $rel) }
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
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    # Prevent two installers from racing without touching program data.
    try {
        $installLock = [IO.File]::Open((Join-Path $runtimeDir 'lotradar-install.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    } catch [IO.IOException] {
        throw 'Another LotRadar installer is running. Close it and try again.'
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

    # Validate every source/asset file, including recovered branding, before any changes.
    foreach ($item in $manifest.payload_files) {
        $file = Join-Path $payloadDir ([string]$item.path).Replace('/', '\')
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
        Copy-Item -LiteralPath $srcFile -Destination $dstFile -Force
        if ((Get-FileHash -LiteralPath $dstFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne [string]$item.sha256) {
            throw ('Staging checksum mismatch: ' + $item.path)
        }
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
    # If a committed program fails on a future added step, restore code backup, never data.
    if (-not $success -and $swapped -and $previousDir -and (Test-Path -LiteralPath $previousDir)) {
        try {
            $failedDir = Join-Path $backupRoot ('Failed-install-' + [Guid]::NewGuid().ToString('N'))
            if (Test-Path -LiteralPath $program) { [IO.Directory]::Move($program, $failedDir) }
            [IO.Directory]::Move($previousDir, $program)
            Write-Host 'Original program has been restored.' -ForegroundColor Yellow
        } catch {
            Write-Host ('ROLLBACK ERROR: ' + $_.Exception.Message) -ForegroundColor Red
        }
    }
} finally {
    if ($stageDir -and (Test-Path -LiteralPath $stageDir)) {
        try { Remove-Item -LiteralPath $stageDir -Recurse -Force } catch { }
    }
    if ($installLock) { $installLock.Dispose() }
}
if (-not $success) { exit 1 }
exit 0
