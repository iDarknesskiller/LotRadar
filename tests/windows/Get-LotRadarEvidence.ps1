# Read-only evidence helper for docs/MANUAL_ACCEPTANCE.md. It never writes inside %LOCALAPPDATA%\MarketplaceScanner.
#   -Mode Version       -PackageZip <zip>                       manifest name/version + SHA-256: ZIP vs installed
#   -Mode PhotoSnapshot -Vin <VIN> -OutFile <csv outside data>   hash every cached photo file of one vehicle
#   -Mode PhotoCompare  -Vin <VIN> -BeforeFile <csv>             re-hash and report changed / deleted / added files
param(
    [Parameter(Mandatory = $true)][ValidateSet('Version', 'PhotoSnapshot', 'PhotoCompare')][string]$Mode,
    [string]$PackageZip,
    [string]$Vin,
    [string]$OutFile,
    [string]$BeforeFile
)
$ErrorActionPreference = 'Stop'
$installed = Join-Path $env:LOCALAPPDATA 'Programs\MarketplaceScanner\chrome-extension\manifest.json'
$photoRoot = Join-Path $env:LOCALAPPDATA 'MarketplaceScanner\data\vehicle_photos'
function Get-Sha([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Get-Rows([string]$VinDir) {
    $base = (Resolve-Path -LiteralPath $VinDir).Path.TrimEnd('\')
    @(Get-ChildItem -LiteralPath $VinDir -Recurse -File -Force | Sort-Object FullName | ForEach-Object {
        [pscustomobject]@{ Path = $_.FullName.Substring($base.Length).TrimStart('\'); Bytes = $_.Length; Sha256 = (Get-Sha $_.FullName) }
    })
}
if ($Mode -eq 'Version') {
    if (-not $PackageZip) { throw '-PackageZip is required' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $PackageZip).Path)
    try {
        $entry = $zip.Entries | Where-Object { $_.FullName -like '*chrome-extension/manifest.json' } | Select-Object -First 1
        if (-not $entry) { throw 'chrome-extension/manifest.json not found in the ZIP' }
        $ms = New-Object IO.MemoryStream
        $in = $entry.Open(); $in.CopyTo($ms); $in.Dispose()
        $bytes = $ms.ToArray()
        $zipSha = ([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($bytes)) -replace '-', '').ToLowerInvariant()
        $zm = [Text.Encoding]::UTF8.GetString($bytes).TrimStart([char]0xFEFF) | ConvertFrom-Json
    } finally { $zip.Dispose() }
    Write-Host ('ZIP       : ' + $zm.name + ' ' + $zm.version + '  sha256 ' + $zipSha)
    if (-not (Test-Path -LiteralPath $installed)) { throw ('Installed manifest not found: ' + $installed) }
    $im = Get-Content -LiteralPath $installed -Raw -Encoding UTF8 | ConvertFrom-Json
    $instSha = Get-Sha $installed
    Write-Host ('Installed : ' + $im.name + ' ' + $im.version + '  sha256 ' + $instSha)
    Write-Host ('Installed path: ' + $installed)
    if ($instSha -eq $zipSha -and $im.version -eq $zm.version) { Write-Host 'MATCH: installed manifest is identical to the package manifest.' -ForegroundColor Green }
    else { Write-Host 'MISMATCH between installed and package manifest.' -ForegroundColor Red; exit 1 }
    Write-Host 'Now compare with the chrome://extensions card (name, version, Details > Loaded from).'
    exit 0
}
if (-not $Vin) { throw '-Vin is required' }
if ($Vin -notmatch '^[A-Za-z0-9]{6,20}$') { throw 'Vin must be letters/digits only' }
$vinDir = Join-Path $photoRoot $Vin
if (-not (Test-Path -LiteralPath $vinDir -PathType Container)) { throw ('No cached photos for that VIN: ' + $vinDir) }
if ($Mode -eq 'PhotoSnapshot') {
    if (-not $OutFile) { throw '-OutFile is required' }
    $full = [IO.Path]::GetFullPath($OutFile)
    if ($full.StartsWith((Join-Path $env:LOCALAPPDATA 'MarketplaceScanner'), [StringComparison]::OrdinalIgnoreCase)) { throw 'Write the snapshot OUTSIDE the LotRadar data folder.' }
    $rows = Get-Rows $vinDir
    $rows | Export-Csv -LiteralPath $full -NoTypeInformation -Encoding UTF8
    Write-Host ('Snapshot of ' + $rows.Count + ' files saved to ' + $full)
    exit 0
}
if (-not $BeforeFile) { throw '-BeforeFile is required' }
$before = @(Import-Csv -LiteralPath $BeforeFile)
$after = Get-Rows $vinDir
$changed = @(); $deleted = @()
foreach ($b in $before) {
    $a = $after | Where-Object { $_.Path -eq $b.Path } | Select-Object -First 1
    if (-not $a) { $deleted += $b.Path } elseif ($a.Sha256 -ne $b.Sha256 -or [string]$a.Bytes -ne [string]$b.Bytes) { $changed += $b.Path }
}
$added = @($after | Where-Object { $p = $_.Path; -not ($before | Where-Object { $_.Path -eq $p }) } | ForEach-Object { $_.Path })
Write-Host ('Files before: ' + $before.Count + '  after: ' + $after.Count)
Write-Host ('CHANGED: ' + $changed.Count + '   DELETED: ' + $deleted.Count + '   ADDED: ' + $added.Count)
$changed | ForEach-Object { Write-Host ('  changed: ' + $_) }
$deleted | ForEach-Object { Write-Host ('  deleted: ' + $_) }
$added | ForEach-Object { Write-Host ('  added  : ' + $_) }
Write-Host 'Note: manifest.json (cache index) may change legitimately; image files must not.'
if (@($changed | Where-Object { $_ -notlike '*manifest.json*' }).Count -or @($deleted | Where-Object { $_ -notlike '*manifest.json*' }).Count) { Write-Host 'FAIL: an original file changed or was deleted.' -ForegroundColor Red; exit 1 }
Write-Host 'PASS: no original photo file changed or was deleted.' -ForegroundColor Green
