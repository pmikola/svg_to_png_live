# svg-to-png-live

Clipboard utility for Windows 11:

- Copy **SVG markup text** (clipboard text containing `<svg>...</svg>`)
- The app converts it to **PNG** using configured **DPI** and **background color**
- The app replaces the clipboard with the **PNG image**, so paste in other apps pastes an image
- Optional: auto-save every converted PNG to a chosen folder

## How it works (high level)

1. You start the app (tray app).
2. You enable **Listen**.
3. When the clipboard changes and contains SVG markup text, the app renders it to PNG and writes an image back to the clipboard.

## Requirements (v1)

- Windows 11
- Python 3.11+ (for development)
- `resvg.exe` (used for SVG rasterization)

## Quick start (development)

```bash
python -m venv .venv
.venv\\Scripts\\activate
python -m pip install -e .[dev]
powershell -ExecutionPolicy Bypass -File scripts\\fetch_resvg_win64.ps1
svg-to-png-live
```

## Usage

- **Listen**: when enabled, SVG text copied to clipboard is replaced by PNG image data
- **Settings**:
  - **DPI**: output scale relative to 96 CSS DPI (scale = dpi / 96)
  - **Background**: solid `#RRGGBB` composited behind the SVG
  - **Auto-save**: when enabled, the PNG is also written to disk (folder is persisted across restarts)

## Build Windows `.exe` (double-clickable)

```bash
python -m pip install -e .[dev]
powershell -ExecutionPolicy Bypass -File scripts\\fetch_resvg_win64.ps1
powershell -ExecutionPolicy Bypass -File scripts\\build_win.ps1
```

Output:

- `dist\\SvgToPngLive\\SvgToPngLive.exe`

Optional single-file build:

```bash
powershell -ExecutionPolicy Bypass -File scripts\\build_win.ps1 -OneFile
```

Optional custom executable icon:

- Place `assets\\app.ico` before building.

## `resvg.exe` location

By default the app expects:

- `vendor\\resvg\\win64\\resvg.exe`

Override (for dev or custom installs):

- `SVG_TO_PNG_LIVE_RESVG_PATH`

## Limitations (v1)

- Only supports SVG copied as **markup text** (not “copy an .svg file”).
- The app rewrites clipboard content after copy; it does not intercept the paste action.
