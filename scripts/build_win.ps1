param(
  [string]$Python = "python",
  [string]$Name = "SvgToPngLive",
  [switch]$OneFile,
  [string]$DistDir = "dist",
  [string]$WorkDir = "build"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $repoRoot

$resvg = Join-Path $repoRoot "vendor\resvg\win64\resvg.exe"
if (-not (Test-Path $resvg)) {
  throw "Missing resvg.exe at $resvg. Place it there or set SVG_TO_PNG_LIVE_RESVG_PATH at runtime."
}

$distPath = Join-Path $repoRoot $DistDir
$workPath = Join-Path $repoRoot $WorkDir

# If the app is currently running from dist\, Windows can lock the directory.
# In that case, build into a different dist directory (e.g. -DistDir dist2).
if (Test-Path $distPath) {
  try {
    # Best-effort cleanup for reproducible builds.
    Remove-Item -Recurse -Force $distPath -ErrorAction Stop
  } catch {
    Write-Host "Warning: could not remove dist directory (likely in use): $distPath"
    Write-Host "Close the running app or rebuild to a different folder, e.g.:"
    Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\build_win.ps1 -DistDir dist2"
  }
}

$entry = Join-Path $repoRoot "src\svg_to_png_live\main.py"
$addBinary = "$resvg;vendor\resvg\win64"

$args = @(
  "-m", "PyInstaller",
  "--name", $Name,
  "--noconfirm",
  "--clean",
  "--noconsole",
  "--distpath", $distPath,
  "--workpath", $workPath,
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

if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Build complete."
Write-Host "Output is in: $distPath\$Name\ (or $distPath\$Name.exe if -OneFile)"



