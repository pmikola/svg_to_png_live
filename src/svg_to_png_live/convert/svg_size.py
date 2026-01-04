"""SVG size parsing and DPI-based output sizing."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SVG_TAG_RE = re.compile(r"<svg\b[^>]*>", flags=re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class SvgCssSize:
    width_px: float
    height_px: float


def _extract_attr(tag: str, name: str) -> str | None:
    m = re.search(rf'\b{name}\s*=\s*["\']([^"\']+)["\']', tag, flags=re.IGNORECASE)
    if not m:
        return None
    return m.group(1).strip()


_LENGTH_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z%]*)\s*$")


def _length_to_css_px(value: str) -> float | None:
    m = _LENGTH_RE.match(value)
    if not m:
        return None
    num = float(m.group(1))
    unit = (m.group(2) or "px").lower()

    if unit in ("px", ""):
        return num
    if unit == "in":
        return num * 96.0
    if unit == "pt":
        return num * (96.0 / 72.0)
    if unit == "pc":
        return num * 16.0
    if unit == "mm":
        return num * (96.0 / 25.4)
    if unit == "cm":
        return num * (96.0 / 2.54)

    # Units that require a viewport/font context are not supported for sizing here.
    if unit in ("%", "em", "ex", "ch", "rem", "vh", "vw", "vmin", "vmax"):
        return None
    return None


def _parse_viewbox(value: str) -> tuple[float, float] | None:
    parts = re.split(r"[,\s]+", value.strip())
    if len(parts) != 4:
        return None
    try:
        w = float(parts[2])
        h = float(parts[3])
    except ValueError:
        return None
    if w <= 0 or h <= 0:
        return None
    return w, h


def parse_svg_css_size(svg_text: str) -> SvgCssSize:
    """Parse a best-effort CSS pixel size for an SVG."""
    tag_m = _SVG_TAG_RE.search(svg_text)
    if not tag_m:
        return SvgCssSize(width_px=300.0, height_px=150.0)
    tag = tag_m.group(0)

    width_raw = _extract_attr(tag, "width")
    height_raw = _extract_attr(tag, "height")
    viewbox_raw = _extract_attr(tag, "viewBox")

    w = _length_to_css_px(width_raw) if width_raw else None
    h = _length_to_css_px(height_raw) if height_raw else None

    if w is not None and h is not None and w > 0 and h > 0:
        return SvgCssSize(width_px=w, height_px=h)

    if viewbox_raw:
        vb = _parse_viewbox(viewbox_raw)
        if vb is not None:
            return SvgCssSize(width_px=vb[0], height_px=vb[1])

    return SvgCssSize(width_px=300.0, height_px=150.0)


def compute_output_px(svg_text: str, *, dpi: int, max_dim_px: int) -> tuple[int, int]:
    """Compute output pixel dimensions based on SVG size and DPI."""
    css = parse_svg_css_size(svg_text)
    scale = float(dpi) / 96.0
    w = max(1, int(round(css.width_px * scale)))
    h = max(1, int(round(css.height_px * scale)))

    max_dim_px = int(max_dim_px)
    if max_dim_px > 0:
        mx = max(w, h)
        if mx > max_dim_px:
            ratio = max_dim_px / float(mx)
            w = max(1, int(round(w * ratio)))
            h = max(1, int(round(h * ratio)))
    return w, h


