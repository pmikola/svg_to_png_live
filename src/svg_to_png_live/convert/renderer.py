"""SVG → PNG conversion pipeline.

This module delegates SVG rasterization to the `resvg` CLI for performance and fidelity,
then applies background compositing in Python to ensure predictable results.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from threading import Lock

from PIL import Image

from svg_to_png_live.clipboard.watcher import ConversionResult
from svg_to_png_live.config import AppConfig
from svg_to_png_live.convert.cache import LruCache
from svg_to_png_live.convert.svg_size import compute_output_px


def _parse_hex_rgb(value: str) -> tuple[int, int, int]:
    v = value.strip()
    if not v.startswith("#"):
        v = f"#{v}"
    if len(v) != 7:
        raise ValueError("background_hex must be in #RRGGBB format")
    r = int(v[1:3], 16)
    g = int(v[3:5], 16)
    b = int(v[5:7], 16)
    return r, g, b


def inject_solid_background(svg_text: str, *, background_hex: str) -> str:
    """Inject a viewport-filling solid background into SVG markup.

    This avoids decoding and re-encoding large raster images in Python. The inserted rect
    uses percentage units so it covers the entire viewport even when the viewBox origin
    is not (0, 0) (which is common in Mermaid-generated SVGs).
    """
    if not svg_text:
        return svg_text
    lower = svg_text.lower()
    start = lower.find("<svg")
    if start < 0:
        return svg_text
    end = svg_text.find(">", start)
    if end < 0:
        return svg_text

    rect = f'\n  <rect x="0%" y="0%" width="100%" height="100%" fill="{background_hex}" />\n'
    return svg_text[: end + 1] + rect + svg_text[end + 1 :]


def trim_png_border(
    png_bytes: bytes,
    *,
    background_hex: str,
    tolerance: int,
) -> tuple[bytes, int, int]:
    """Crop away solid-background padding around content.

    This targets common cases where SVGs include margins in the viewBox (e.g. Mermaid),
    leading to unwanted borders in the rasterized output.
    """
    tol = max(0, min(255, int(tolerance)))
    bg = _parse_hex_rgb(background_hex)

    with Image.open(BytesIO(png_bytes)) as im:
        rgb = im.convert("RGB")
        w, h = rgb.size
        if w <= 2 or h <= 2:
            return png_bytes, w, h

        # Downsample for scanning performance on very large images.
        max_probe = 1024
        scale = max(1, max(w, h) // max_probe)
        sw = max(1, w // scale)
        sh = max(1, h // scale)
        small = rgb.resize((sw, sh), resample=Image.Resampling.BOX)
        data = list(small.getdata())

        def is_bg(px: tuple[int, int, int]) -> bool:
            return (
                abs(px[0] - bg[0]) <= tol
                and abs(px[1] - bg[1]) <= tol
                and abs(px[2] - bg[2]) <= tol
            )

        min_x, min_y = sw, sh
        max_x, max_y = -1, -1
        for idx, px in enumerate(data):
            if is_bg(px):
                continue
            y, x = divmod(idx, sw)
            if x < min_x:
                min_x = x
            if y < min_y:
                min_y = y
            if x > max_x:
                max_x = x
            if y > max_y:
                max_y = y

        if max_x < 0 or max_y < 0:
            return png_bytes, w, h

        # Map back to original coordinates and add a small padding to avoid cropping antialiased edges.
        pad = max(1, scale)
        left = max(0, min_x * scale - pad)
        top = max(0, min_y * scale - pad)
        right = min(w, (max_x + 1) * scale + pad)
        bottom = min(h, (max_y + 1) * scale + pad)

        if left == 0 and top == 0 and right == w and bottom == h:
            return png_bytes, w, h

        cropped = im.crop((left, top, right, bottom))
        buf = BytesIO()
        cropped.save(buf, format="PNG")
        out = buf.getvalue()
        return out, int(right - left), int(bottom - top)

def _resource_base_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    # Dev: renderer.py -> convert -> svg_to_png_live -> src -> repo root
    return Path(__file__).resolve().parents[3]


def find_resvg_exe() -> Path:
    override = os.getenv("SVG_TO_PNG_LIVE_RESVG_PATH")
    if override:
        p = Path(override)
        if p.exists():
            return p
        raise FileNotFoundError(f"SVG_TO_PNG_LIVE_RESVG_PATH points to missing file: {p}")

    candidate = _resource_base_dir() / "vendor" / "resvg" / "win64" / "resvg.exe"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(
        "resvg.exe not found. Expected vendor/resvg/win64/resvg.exe "
        "or set SVG_TO_PNG_LIVE_RESVG_PATH."
    )


class ResvgRenderer:
    """Thin wrapper around the `resvg` CLI."""

    def __init__(self, resvg_path: Path) -> None:
        self._log = logging.getLogger("svg_to_png_live.resvg")
        self._resvg = Path(resvg_path)
        self._caps_lock = Lock()
        self._caps: dict[str, bool] | None = None

    def _probe_caps(self) -> dict[str, bool]:
        with self._caps_lock:
            if self._caps is not None:
                return self._caps

            try:
                p = subprocess.run(
                    [str(self._resvg), "--help"],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                )
                help_text = (p.stdout or "") + "\n" + (p.stderr or "")
            except Exception:
                help_text = ""

            caps = {
                "width": "--width" in help_text,
                "height": "--height" in help_text,
                "zoom": "--zoom" in help_text,
                "dpi": "--dpi" in help_text,
            }
            self._caps = caps
            return caps

    def render_svg_to_png_bytes(
        self,
        svg_text: str,
        *,
        width_px: int,
        height_px: int,
        dpi: int,
        timeout_s: float,
    ) -> bytes:
        caps = self._probe_caps()

        with tempfile.TemporaryDirectory(prefix="svg_to_png_live_") as td:
            td_path = Path(td)
            in_svg = td_path / "in.svg"
            out_png = td_path / "out.png"
            in_svg.write_text(svg_text, encoding="utf-8")

            args: list[str] = [str(self._resvg)]
            if caps.get("dpi", False):
                args += ["--dpi", str(int(dpi))]
            if caps.get("width", False):
                args += ["--width", str(int(width_px))]
            if caps.get("height", False):
                args += ["--height", str(int(height_px))]
            elif caps.get("zoom", False):
                zoom = float(dpi) / 96.0
                args += ["--zoom", f"{zoom:.6f}"]

            args += [str(in_svg), str(out_png)]

            creationflags = 0
            if sys.platform.startswith("win"):
                # Prevent console window flashes and keep CPU usage less disruptive.
                creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
                creationflags |= getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)

            try:
                p = subprocess.run(
                    args,
                    capture_output=True,
                    timeout=float(timeout_s),
                    creationflags=creationflags,
                )
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(
                    f"SVG render timed out after {timeout_s:.1f}s. "
                    "Increase 'Conversion timeout (s)' in Settings → Advanced."
                ) from e
            if p.returncode != 0 or not out_png.exists():
                stderr = (p.stderr or b"").decode("utf-8", errors="replace")
                stdout = (p.stdout or b"").decode("utf-8", errors="replace")
                raise RuntimeError(f"resvg failed (code={p.returncode}): {stderr or stdout}".strip())

            if out_png.stat().st_size <= 0:
                raise RuntimeError(
                    "Renderer produced an empty PNG file. "
                    "This SVG may be unsupported or exceeded renderer limits."
                )

            return out_png.read_bytes()


def apply_solid_background(png_bytes: bytes, *, background_hex: str) -> bytes:
    r, g, b = _parse_hex_rgb(background_hex)
    with Image.open(BytesIO(png_bytes)) as im:
        rgba = im.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (r, g, b, 255))
        out = Image.alpha_composite(bg, rgba)
        buf = BytesIO()
        out.save(buf, format="PNG")
        return buf.getvalue()


class SvgToPngConverter:
    """Thread-safe converter used by the clipboard worker."""

    def __init__(self, config: AppConfig, renderer: ResvgRenderer) -> None:
        self._log = logging.getLogger("svg_to_png_live.converter")
        self._renderer = renderer
        self._cfg_lock = Lock()
        self._cfg = replace(config)

        self._cache_lock = Lock()
        self._cache: LruCache[str, tuple[bytes, int, int]] | None = None
        self._rebuild_cache()

    def set_config(self, config: AppConfig) -> None:
        with self._cfg_lock:
            self._cfg = replace(config)
        self._rebuild_cache()

    def _rebuild_cache(self) -> None:
        with self._cfg_lock:
            enabled = bool(self._cfg.cache_enabled)
            max_items = int(self._cfg.cache_max_items)
        with self._cache_lock:
            self._cache = LruCache(max_items) if enabled else None

    def convert(self, svg_text: str) -> ConversionResult:
        svg_hash = hashlib.sha256(svg_text.encode("utf-8")).hexdigest()

        with self._cfg_lock:
            cfg = replace(self._cfg)

        svg_for_render = inject_solid_background(svg_text, background_hex=cfg.background_hex)
        width_px, height_px = compute_output_px(
            svg_text,
            dpi=int(cfg.dpi),
            max_dim_px=int(cfg.max_output_dim_px),
        )
        settings_key = (
            f"dpi={int(cfg.dpi)};bg={cfg.background_hex};w={width_px};h={height_px};"
            f"max_png={int(getattr(cfg, 'max_output_png_bytes', 0))}"
        )
        cache_key = f"{svg_hash}:{hashlib.sha256(settings_key.encode('utf-8')).hexdigest()}"

        with self._cache_lock:
            cache = self._cache
        if cache is not None:
            hit = cache.get(cache_key)
            if hit is not None:
                png, w, h = hit
                return ConversionResult(svg_hash=svg_hash, png_bytes=png, render_ms=0.0, width_px=w, height_px=h)

        t0 = time.perf_counter()
        max_png_bytes = int(getattr(cfg, "max_output_png_bytes", 0))

        render_w = int(width_px)
        render_h = int(height_px)
        composed = b""

        max_attempts = 6
        for _ in range(max_attempts):
            composed = self._renderer.render_svg_to_png_bytes(
                svg_for_render,
                width_px=render_w,
                height_px=render_h,
                dpi=int(cfg.dpi),
                timeout_s=float(cfg.conversion_timeout_s),
            )

            if bool(getattr(cfg, "trim_border", False)):
                composed, render_w, render_h = trim_png_border(
                    composed,
                    background_hex=cfg.background_hex,
                    tolerance=int(getattr(cfg, "trim_tolerance", 8)),
                )

            if max_png_bytes <= 0 or len(composed) <= max_png_bytes:
                break

            # Roughly scale pixels by sqrt(byte_ratio) and apply a safety factor.
            ratio = max_png_bytes / float(len(composed))
            scale = max(0.10, min(0.95, (ratio**0.5) * 0.90))
            next_w = max(1, int(round(render_w * scale)))
            next_h = max(1, int(round(render_h * scale)))
            if next_w == render_w and next_h == render_h:
                break
            render_w, render_h = next_w, next_h

        if max_png_bytes > 0 and len(composed) > max_png_bytes:
            raise RuntimeError(
                f"PNG size limit exceeded ({len(composed)} bytes > {max_png_bytes} bytes). "
                "Increase 'Max output PNG size (MB)' or lower DPI."
            )

        dt_ms = (time.perf_counter() - t0) * 1000.0

        with self._cache_lock:
            cache = self._cache
        if cache is not None:
            cache.put(cache_key, (composed, render_w, render_h))

        self._log.info(
            "converted svg_hash=%s ms=%.1f w=%d h=%d dpi=%d bg=%s timeout=%.1fs",
            svg_hash[:10],
            dt_ms,
            render_w,
            render_h,
            int(cfg.dpi),
            cfg.background_hex,
            float(cfg.conversion_timeout_s),
        )
        return ConversionResult(
            svg_hash=svg_hash,
            png_bytes=composed,
            render_ms=dt_ms,
            width_px=render_w,
            height_px=render_h,
        )


