"""Windows clipboard helpers.

Qt's clipboard integration is convenient, but for large images Windows may require
explicit clipboard formats to avoid failures when pasting into various targets
(notably File Explorer "paste as file"). In particular:
- The standard registered clipboard format name for PNG is "PNG".

This module sets the "PNG" format (and optionally CF_DIBV5 for broad app support)
using Win32 APIs via ctypes.
"""

from __future__ import annotations

import ctypes
import io
import sys
import time
from dataclasses import dataclass

from PIL import Image

# Allow very large images for clipboard operations – the converter already
# enforces dimension limits via max_output_dim_px.
Image.MAX_IMAGE_PIXELS = None

if not sys.platform.startswith("win"):
    raise RuntimeError("win_clipboard is only supported on Windows")

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

# Ensure pointer-sized WinAPI return types are not truncated on 64-bit Python.
_user32.OpenClipboard.argtypes = [ctypes.c_void_p]
_user32.OpenClipboard.restype = ctypes.c_bool
_user32.CloseClipboard.argtypes = []
_user32.CloseClipboard.restype = ctypes.c_bool
_user32.EmptyClipboard.argtypes = []
_user32.EmptyClipboard.restype = ctypes.c_bool
_user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
_user32.SetClipboardData.restype = ctypes.c_void_p
_user32.RegisterClipboardFormatW.argtypes = [ctypes.c_wchar_p]
_user32.RegisterClipboardFormatW.restype = ctypes.c_uint

_kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
_kernel32.GlobalAlloc.restype = ctypes.c_void_p
_kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
_kernel32.GlobalLock.restype = ctypes.c_void_p
_kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
_kernel32.GlobalUnlock.restype = ctypes.c_bool
_kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
_kernel32.GlobalFree.restype = ctypes.c_void_p


CF_DIBV5 = 17
GMEM_MOVEABLE = 0x0002

BI_BITFIELDS = 3
LCS_sRGB = 0x73524742  # 'sRGB'
LCS_GM_IMAGES = 4


def _dpi_to_pels_per_meter(dpi: int) -> int:
    # 1 inch = 0.0254 m
    return int(round(float(dpi) / 0.0254))


class CIEXYZ(ctypes.Structure):
    _fields_ = [
        ("ciexyzX", ctypes.c_long),
        ("ciexyzY", ctypes.c_long),
        ("ciexyzZ", ctypes.c_long),
    ]


class CIEXYZTRIPLE(ctypes.Structure):
    _fields_ = [
        ("ciexyzRed", CIEXYZ),
        ("ciexyzGreen", CIEXYZ),
        ("ciexyzBlue", CIEXYZ),
    ]


class BITMAPV5HEADER(ctypes.Structure):
    _fields_ = [
        ("bV5Size", ctypes.c_uint32),
        ("bV5Width", ctypes.c_int32),
        ("bV5Height", ctypes.c_int32),
        ("bV5Planes", ctypes.c_uint16),
        ("bV5BitCount", ctypes.c_uint16),
        ("bV5Compression", ctypes.c_uint32),
        ("bV5SizeImage", ctypes.c_uint32),
        ("bV5XPelsPerMeter", ctypes.c_int32),
        ("bV5YPelsPerMeter", ctypes.c_int32),
        ("bV5ClrUsed", ctypes.c_uint32),
        ("bV5ClrImportant", ctypes.c_uint32),
        ("bV5RedMask", ctypes.c_uint32),
        ("bV5GreenMask", ctypes.c_uint32),
        ("bV5BlueMask", ctypes.c_uint32),
        ("bV5AlphaMask", ctypes.c_uint32),
        ("bV5CSType", ctypes.c_uint32),
        ("bV5Endpoints", CIEXYZTRIPLE),
        ("bV5GammaRed", ctypes.c_uint32),
        ("bV5GammaGreen", ctypes.c_uint32),
        ("bV5GammaBlue", ctypes.c_uint32),
        ("bV5Intent", ctypes.c_uint32),
        ("bV5ProfileData", ctypes.c_uint32),
        ("bV5ProfileSize", ctypes.c_uint32),
        ("bV5Reserved", ctypes.c_uint32),
    ]


@dataclass(frozen=True)
class ClipboardWriteStats:
    wrote_png: bool
    wrote_dibv5: bool


def _alloc_global_bytes(data: bytes) -> ctypes.c_void_p:
    hglobal = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not hglobal:
        raise MemoryError("GlobalAlloc failed")
    ptr = _kernel32.GlobalLock(hglobal)
    if not ptr:
        _kernel32.GlobalFree(hglobal)
        raise MemoryError("GlobalLock failed")
    ctypes.memmove(ptr, data, len(data))
    _kernel32.GlobalUnlock(hglobal)
    return ctypes.c_void_p(hglobal)


def _set_clipboard_data(fmt: int, data: bytes) -> None:
    hglobal = _alloc_global_bytes(data)
    # After SetClipboardData succeeds, the system owns the memory handle.
    if not _user32.SetClipboardData(fmt, hglobal):
        _kernel32.GlobalFree(hglobal)
        raise RuntimeError(f"SetClipboardData failed for format {fmt}")


def _register_format(name: str) -> int:
    fmt = _user32.RegisterClipboardFormatW(name)
    if not fmt:
        raise RuntimeError(f"RegisterClipboardFormatW failed for {name!r}")
    return int(fmt)


def set_windows_clipboard_png(
    png_bytes: bytes,
    *,
    width_px: int,
    height_px: int,
    dpi: int,
    also_set_dibv5: bool,
    max_dibv5_bytes: int,
    open_retries: int = 10,
    open_retry_delay_s: float = 0.05,
) -> ClipboardWriteStats:
    """Replace the clipboard with PNG (and optionally DIBV5) data."""
    png_fmt = _register_format("PNG")

    dibv5_bytes: bytes | None = None
    if also_set_dibv5:
        expected_pixel_bytes = int(width_px) * int(height_px) * 4
        if expected_pixel_bytes <= int(max_dibv5_bytes):
            try:
                with Image.open(io.BytesIO(png_bytes)) as im:
                    rgba = im.convert("RGBA")
                    pixel_bytes = rgba.tobytes("raw", "BGRA")
            except (MemoryError, Exception):
                # Image too large for in-memory RGBA decode; skip DIBv5.
                pixel_bytes = b""

            if pixel_bytes and len(pixel_bytes) <= int(max_dibv5_bytes):
                hdr = BITMAPV5HEADER()
                hdr.bV5Size = ctypes.sizeof(BITMAPV5HEADER)
                hdr.bV5Width = int(width_px)
                hdr.bV5Height = -int(height_px)  # top-down
                hdr.bV5Planes = 1
                hdr.bV5BitCount = 32
                hdr.bV5Compression = BI_BITFIELDS
                hdr.bV5SizeImage = int(len(pixel_bytes))
                ppm = _dpi_to_pels_per_meter(int(dpi))
                hdr.bV5XPelsPerMeter = int(ppm)
                hdr.bV5YPelsPerMeter = int(ppm)
                hdr.bV5RedMask = 0x00FF0000
                hdr.bV5GreenMask = 0x0000FF00
                hdr.bV5BlueMask = 0x000000FF
                hdr.bV5AlphaMask = 0xFF000000
                hdr.bV5CSType = LCS_sRGB
                hdr.bV5Intent = LCS_GM_IMAGES
                dib_hdr = ctypes.string_at(ctypes.byref(hdr), ctypes.sizeof(hdr))
                dibv5_bytes = dib_hdr + pixel_bytes

    for _ in range(int(open_retries)):
        if _user32.OpenClipboard(None):
            break
        time.sleep(float(open_retry_delay_s))
    else:
        raise RuntimeError("OpenClipboard failed (clipboard busy)")

    wrote_png = False
    wrote_dibv5 = False
    try:
        if not _user32.EmptyClipboard():
            raise RuntimeError("EmptyClipboard failed")

        _set_clipboard_data(png_fmt, png_bytes)
        wrote_png = True

        if dibv5_bytes is not None:
            _set_clipboard_data(CF_DIBV5, dibv5_bytes)
            wrote_dibv5 = True
    finally:
        _user32.CloseClipboard()

    return ClipboardWriteStats(wrote_png=wrote_png, wrote_dibv5=wrote_dibv5)

