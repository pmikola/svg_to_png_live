from svg_to_png_live.convert.svg_size import compute_output_px, parse_svg_css_size


def test_parse_svg_css_size_width_height_px() -> None:
    svg = '<svg width="200px" height="100px"></svg>'
    size = parse_svg_css_size(svg)
    assert size.width_px == 200.0
    assert size.height_px == 100.0


def test_parse_svg_css_size_viewbox_fallback() -> None:
    svg = '<svg viewBox="0 0 640 480"></svg>'
    size = parse_svg_css_size(svg)
    assert size.width_px == 640.0
    assert size.height_px == 480.0


def test_compute_output_px_dpi_scaling_and_clamp() -> None:
    svg = '<svg width="100" height="50"></svg>'
    w, h = compute_output_px(svg, dpi=192, max_dim_px=1000)
    assert (w, h) == (200, 100)

    w2, h2 = compute_output_px(svg, dpi=192, max_dim_px=120)
    assert max(w2, h2) == 120





