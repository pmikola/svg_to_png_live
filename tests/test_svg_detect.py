from svg_to_png_live.convert.svg_detect import looks_like_svg_text, normalize_svg_markup


def test_svg_detection_basic() -> None:
    s = '<svg width="10" height="10"></svg>'
    assert looks_like_svg_text(s) is True
    assert normalize_svg_markup(s) == s


def test_svg_detection_with_preamble_and_trailing_text() -> None:
    s = 'abc <?xml version="1.0"?>\\n<svg></svg>\\nxyz'
    assert looks_like_svg_text(s) is True
    assert normalize_svg_markup(s) == "<svg></svg>"


def test_svg_detection_reject_non_svg() -> None:
    assert looks_like_svg_text("hello") is False
    assert normalize_svg_markup("hello") is None




