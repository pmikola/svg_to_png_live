"""SVG clipboard text detection and normalization."""

from __future__ import annotations

import re

_SVG_OPEN_RE = re.compile(r"<svg\b", flags=re.IGNORECASE)
_SVG_CLOSE_RE = re.compile(r"</svg\s*>", flags=re.IGNORECASE)


def looks_like_svg_text(text: str) -> bool:
    """Heuristic check for SVG markup text in a clipboard string."""
    if not text:
        return False
    if _SVG_OPEN_RE.search(text) is None:
        return False
    # Close tag is optional in some snippets, but requiring it reduces false positives.
    if _SVG_CLOSE_RE.search(text) is None:
        return False
    return True


def normalize_svg_markup(text: str) -> str | None:
    """Extract a normalized SVG markup substring.

    Returns:
    - SVG substring from first `<svg` to last `</svg>` (inclusive), stripped.
    - None if the input does not contain a plausible SVG document.
    """
    if not looks_like_svg_text(text):
        return None

    open_m = _SVG_OPEN_RE.search(text)
    close_m = None
    for m in _SVG_CLOSE_RE.finditer(text):
        close_m = m
    if open_m is None or close_m is None:
        return None

    start = open_m.start()
    end = close_m.end()
    svg = text[start:end].strip()
    if not svg:
        return None
    return svg



