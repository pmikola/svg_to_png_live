import os

import pytest

from svg_to_png_live.config import AppConfig
from svg_to_png_live.convert.renderer import ResvgRenderer, SvgToPngConverter, find_resvg_exe


def _has_resvg() -> bool:
    try:
        _ = find_resvg_exe()
    except Exception:
        return False
    return True


@pytest.mark.skipif(not _has_resvg(), reason="resvg.exe not available in this environment")
def test_conversion_produces_png_header() -> None:
    cfg = AppConfig(dpi=96, background_hex="#FFFFFF")
    renderer = ResvgRenderer(find_resvg_exe())
    conv = SvgToPngConverter(cfg, renderer)

    svg = '<svg width="10" height="10" xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10" fill="red"/></svg>'
    result = conv.convert(svg)
    assert result.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    assert result.width_px == 10
    assert result.height_px == 10



