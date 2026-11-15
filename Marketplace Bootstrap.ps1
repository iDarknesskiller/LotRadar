$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$Host.UI.RawUI.WindowTitle = 'LotRadar Server'

function Open-LotRadarWindow {
    $url = 'http://127.0.0.1:8765/'
    $roots = @($env:LOCALAPPDATA, $env:ProgramFiles, ${env:ProgramFiles(x86)})
    foreach ($relative in @('Google\Chrome\Application\chrome.exe', 'Microsoft\Edge\Application\msedge.exe')) {
        foreach ($root in $roots) {
            if (-not $root) { continue }
            $browser = Join-Path $root $relative
            if (Test-Path -LiteralPath $browser -PathType Leaf) {
                Start-Process -FilePath $browser -ArgumentList "--app=$url"
                return
            }
        }
    }
    Start-Process $url
}

function Test-PythonCode([string]$Executable, [string[]]$Prefix, [string]$Code) {
    # Missing modules and missing browser binaries are expected on the first run.
    $ErrorActionPreference = 'Continue'
    & $Executable @Prefix -c $Code 2>$null | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Find-BasePython {
    $probe = 'import sys, venv, ensurepip; sys.exit(sys.version_info < (3, 10))'
    $registryRoots = @(
        'HKCU:\Software\Python\PythonCore',
        'HKLM:\Software\Python\PythonCore',
        'HKLM:\Software\WOW6432Node\Python\PythonCore'
    )
    foreach ($root in $registryRoots) {
        foreach ($version in (Get-ChildItem -LiteralPath $root -ErrorAction SilentlyContinue | Sort-Object PSChildName -Descending)) {
            $installKey = Get-Item -LiteralPath (Join-Path $version.PSPath 'InstallPath') -ErrorAction SilentlyContinue
            if (-not $installKey) { continue }
            $exe = $installKey.GetValue('ExecutablePath')
            if (-not $exe -and $installKey.GetValue('')) {
                $exe = Join-Path ($installKey.GetValue('')) 'python.exe'
            }
            if ($exe -and (Test-Path -LiteralPath $exe -PathType Leaf) -and (Test-PythonCode $exe @() $probe)) {
                return @{ Exe = $exe; Args = @() }
            }
        }
    }
    $launcher = Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($launcher -and $launcher.Source -notlike '*\Microsoft\WindowsApps\*' -and (Test-PythonCode $launcher.Source @('-3') $probe)) {
        return @{ Exe = $launcher.Source; Args = @('-3') }
    }
    foreach ($python in (Get-Command python.exe -CommandType Application -All -ErrorAction SilentlyContinue)) {
        if ($python.Source -notlike '*\Microsoft\WindowsApps\*' -and (Test-PythonCode $python.Source @() $probe)) {
            return @{ Exe = $python.Source; Args = @() }
        }
    }
}

function Test-PrivatePython([string]$Executable) {
    return ((Test-Path -LiteralPath $Executable -PathType Leaf) -and
        (Test-PythonCode $Executable @() 'import sys; sys.exit(sys.version_info < (3, 10) or sys.prefix == sys.base_prefix)'))
}

function Start-ExistingMarketplace {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 2
    } catch { return $false }
    if ($health.ok -eq $true -and $health.local_only -eq $true -and $health.service -eq 'Marketplace Scanner') {
        Write-Host 'LotRadar is already running.'
        Open-LotRadarWindow
        return $true
    }
    return $false
}

$launchLock = $null
$exitCode = 1
try {
    $server = Join-Path $PSScriptRoot 'server.py'
    $requirements = Join-Path $PSScriptRoot 'requirements.txt'
    if (-not (Test-Path -LiteralPath $server -PathType Leaf) -or
        -not (Test-Path -LiteralPath $requirements -PathType Leaf)) {
        throw 'Marketplace Manager source is missing. Install Marketplace Manager first, then launch it again.'
    }

    if (Start-ExistingMarketplace) { exit 0 }
    if (-not $env:LOCALAPPDATA) { throw 'Windows LOCALAPPDATA is missing.' }
    $dataDir = Join-Path $env:LOCALAPPDATA 'MarketplaceScanner\data'
    $runtimeDir = Join-Path $env:LOCALAPPDATA 'MarketplaceScanner\runtime'
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    try {
        $launchLock = [IO.File]::Open((Join-Path $runtimeDir 'marketplace-launch.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    } catch [IO.IOException] {
        if (Start-ExistingMarketplace) { exit 0 }
        throw 'Marketplace is already starting in another window. Check that window for progress.'
    }

    $portProbe = [Net.Sockets.TcpClient]::new()
    try {
        $connect = $portProbe.ConnectAsync([Net.IPAddress]::Loopback, 8765)
        try { [void]$connect.Wait(500) } catch { }
        if ($portProbe.Connected) {
            if (Start-ExistingMarketplace) { exit 0 }
            throw 'Port 8765 is in use. Close the application using it, then retry.'
        }
    } finally { $portProbe.Dispose() }

    $legacy = Join-Path $runtimeDir 'venv\Scripts\python.exe'
    $managed = Join-Path $runtimeDir 'setup-venv'
    $managedPython = Join-Path $managed 'Scripts\python.exe'
    $runtime = $legacy
    if (Test-PrivatePython $managedPython) { $runtime = $managedPython }
    elseif (-not (Test-PrivatePython $legacy)) {
        $basePython = Find-BasePython
        if (-not $basePython) {
            $winget = Get-Command winget.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if (-not $winget) {
                throw 'Python 3.10+ is missing and Windows Package Manager (WinGet) is unavailable. Install App Installer or get Python at https://www.python.org/downloads/windows/ and relaunch.'
            }
            Write-Host 'Downloading Python 3.13 for this Windows user...'
            & $winget.Source install --id Python.Python.3.13 --exact --source winget --scope user --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
            $installCode = $LASTEXITCODE
            $basePython = Find-BasePython
            if (-not $basePython) {
                throw "Python setup failed (WinGet exit $installCode). Check internet access or install Python 3.10+ from python.org, then relaunch."
            }
        }
        Write-Host 'Creating the private Marketplace Python environment...'
        $pythonArgs = $basePython.Args
        & $basePython.Exe @pythonArgs -m venv $managed
        if ($LASTEXITCODE -ne 0 -or -not (Test-PrivatePython $managedPython)) {
            throw 'Could not create the Marketplace Python environment. Check the output above and retry.'
        }
        $runtime = $managedPython
    }

    $modules = 'import bs4, PIL.Image; from playwright.sync_api import sync_playwright'
    if (-not (Test-PythonCode $runtime @() $modules)) {
        if (-not (Test-PythonCode $runtime @() 'import pip')) {
            & $runtime -m ensurepip --upgrade
            if ($LASTEXITCODE -ne 0) { throw 'Could not repair pip in the Marketplace Python environment.' }
        }
        Write-Host 'Downloading missing Marketplace Python packages...'
        & $runtime -m pip install --disable-pip-version-check --no-input -r $requirements
        if ($LASTEXITCODE -ne 0 -or -not (Test-PythonCode $runtime @() $modules)) {
            throw 'Could not install Marketplace Python packages. Check the output above and retry.'
        }
    }

    $chromium = @'
from playwright.sync_api import sync_playwright
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, timeout=15000)
    browser.close()
'@
    if (-not (Test-PythonCode $runtime @() $chromium)) {
        Write-Host 'Checking or downloading Playwright Chromium...'
        & $runtime -m playwright install chromium
        if ($LASTEXITCODE -ne 0) { throw 'Chromium download failed. Check the output above and retry.' }
        & $runtime -c $chromium
        if ($LASTEXITCODE -ne 0) { throw 'Playwright Chromium could not start. Check the output above.' }
    }

    # One-time copy of legacy data before first independent start. Never overwrite an existing scanner database.
    $legacyData = Join-Path $env:LOCALAPPDATA 'SalesmanHub\MarketplaceManager'
    if ((Test-Path -LiteralPath (Join-Path $legacyData 'marketplace.sqlite3') -PathType Leaf) -and
        -not (Test-Path -LiteralPath (Join-Path $dataDir 'marketplace.sqlite3') -PathType Leaf)) {
        if (Test-Path -LiteralPath $dataDir) {
            throw 'New scanner data folder already exists without a database. Review it before migrating; no overwrite attempted.'
        }
        Write-Host 'Copying original Marketplace records to independent storage (original remains untouched)...'
        & $runtime -u (Join-Path $PSScriptRoot 'migrate_legacy.py') --apply --source $legacyData --destination $dataDir
        if ($LASTEXITCODE -ne 0) { throw 'Marketplace data migration failed. Original data is unchanged.' }
    }
    New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
    Write-Host 'Starting LotRadar at http://127.0.0.1:8765/.'
    $serverArgs = '-u "{0}" --data-dir "{1}" --no-browser' -f $server, $dataDir
    $serverProcess = Start-Process -FilePath $runtime -ArgumentList $serverArgs -NoNewWindow -PassThru
    $ready = $false
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    while (-not $serverProcess.HasExited -and [DateTime]::UtcNow -lt $deadline) {
        if (Start-ExistingMarketplace) {
            $ready = $true
            break
        }
        Start-Sleep -Milliseconds 300
    }
    if (-not $ready) {
        if (-not $serverProcess.HasExited) { $serverProcess.Kill() }
        throw 'LotRadar could not start its local server. Check the server window for details.'
    }
    $serverProcess.WaitForExit()
    $exitCode = $serverProcess.ExitCode
} catch {
    Write-Host ('LOTRADAR STARTUP ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    if ($env:LOTRADAR_EXE) {
        Add-Type -AssemblyName System.Windows.Forms
        [void][Windows.Forms.MessageBox]::Show($_.Exception.Message, 'LotRadar', 'OK', 'Error')
    }
} finally {
    if ($launchLock) { $launchLock.Dispose() }
}
exit $exitCode
