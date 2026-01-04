param(
  [string]$Python = "python",
  [string]$Name = "SvgToPngLive",
  [switch]$OneFile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $repoRoot

$resvg = Join-Path $repoRoot "vendor\resvg\win64\resvg.exe"
if (-not (Test-Path $resvg)) {
  throw "Missing resvg.exe at $resvg. Place it there or set SVG_TO_PNG_LIVE_RESVG_PATH at runtime."
}

$entry = Join-Path $repoRoot "src\svg_to_png_live\main.py"
$addBinary = "$resvg;vendor\resvg\win64"

$args = @(
  "-m", "PyInstaller",
  "--name", $Name,
  "--noconfirm",
  "--clean",
  "--noconsole",
  "--add-binary", $addBinary
)

$iconPath = Join-Path $repoRoot "assets\app.ico"
if (Test-Path $iconPath) {
  $args += @("--icon", $iconPath)
}

if ($OneFile) {
  $args += @("--onefile")
}

$args += @($entry)

& $Python @args

Write-Host ""
Write-Host "Build complete."
Write-Host "Output is in: $repoRoot\dist\$Name\ (or $repoRoot\dist\$Name.exe if -OneFile)"


