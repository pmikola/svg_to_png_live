param(
  [string]$Repo = "RazrFalcon/resvg"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $repoRoot

$outDir = Join-Path $repoRoot "vendor\resvg\win64"
$outExe = Join-Path $outDir "resvg.exe"

if (Test-Path $outExe) {
  Write-Host "resvg.exe already present at: $outExe"
  exit 0
}

$api = "https://api.github.com/repos/$Repo/releases/latest"
Write-Host "Fetching latest release metadata: $api"

$headers = @{
  "User-Agent" = "svg-to-png-live"
  "Accept"     = "application/vnd.github+json"
}

$release = Invoke-RestMethod -Uri $api -Headers $headers -Method Get
if (-not $release.assets) {
  throw "No assets found in latest release for $Repo"
}

$asset =
  $release.assets |
  Where-Object { $_.name -match "^resvg-.*win64\.zip$" } |
  Select-Object -First 1

if (-not $asset) {
  $asset =
    $release.assets |
    Where-Object { $_.name -match "resvg" -and $_.name -match "win64" -and $_.name -match "\.zip$" } |
    Select-Object -First 1
}

if (-not $asset) {
  $asset =
    $release.assets |
    Where-Object { $_.name -match "windows" -and $_.name -match "x86_64" -and $_.name -match "\.zip$" } |
    Select-Object -First 1
}

if (-not $asset) {
  $asset =
    $release.assets |
    Where-Object { $_.name -match "windows" -and $_.name -match "\.zip$" } |
    Select-Object -First 1
}

if (-not $asset) {
  $names = ($release.assets | ForEach-Object { $_.name }) -join ", "
  throw "Could not find a Windows zip asset in latest release. Assets: $names"
}

$zipUrl = $asset.browser_download_url
Write-Host "Downloading: $zipUrl"

$tmpDir = Join-Path $env:TEMP ("svg_to_png_live_resvg_" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmpDir | Out-Null
$zipPath = Join-Path $tmpDir $asset.name

Invoke-WebRequest -Uri $zipUrl -Headers $headers -OutFile $zipPath

$extractDir = Join-Path $tmpDir "extract"
Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

$exe = Get-ChildItem -Path $extractDir -Recurse -Filter "resvg.exe" | Select-Object -First 1
if (-not $exe) {
  throw "Downloaded archive did not contain resvg.exe"
}

New-Item -ItemType Directory -Path $outDir -Force | Out-Null
Copy-Item -Path $exe.FullName -Destination $outExe -Force

Write-Host "Installed resvg.exe to: $outExe"


