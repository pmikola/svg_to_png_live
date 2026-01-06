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

        width_px, height_px = compute_output_px(
            svg_text,
            dpi=int(cfg.dpi),
            max_dim_px=int(cfg.max_output_dim_px),
        )
        settings_key = f"dpi={int(cfg.dpi)};bg={cfg.background_hex};w={width_px};h={height_px}"
        cache_key = f"{svg_hash}:{hashlib.sha256(settings_key.encode('utf-8')).hexdigest()}"

        with self._cache_lock:
            cache = self._cache
        if cache is not None:
            hit = cache.get(cache_key)
            if hit is not None:
                png, w, h = hit
                return ConversionResult(svg_hash=svg_hash, png_bytes=png, render_ms=0.0, width_px=w, height_px=h)

        t0 = time.perf_counter()
        raw = self._renderer.render_svg_to_png_bytes(
            svg_text,
            width_px=width_px,
            height_px=height_px,
            dpi=int(cfg.dpi),
            timeout_s=float(cfg.conversion_timeout_s),
        )
        composed = apply_solid_background(raw, background_hex=cfg.background_hex)

        # Ensure final dimensions match computed expectations even if the renderer ignored sizing flags.
        with Image.open(BytesIO(composed)) as im:
            if im.size != (width_px, height_px):
                resized = im.convert("RGBA").resize((width_px, height_px), resample=Image.Resampling.LANCZOS)
                buf = BytesIO()
                resized.save(buf, format="PNG")
                composed = buf.getvalue()

        dt_ms = (time.perf_counter() - t0) * 1000.0

        with self._cache_lock:
            cache = self._cache
        if cache is not None:
            cache.put(cache_key, (composed, width_px, height_px))

        self._log.info(
            "converted svg_hash=%s ms=%.1f w=%d h=%d dpi=%d bg=%s timeout=%.1fs",
            svg_hash[:10],
            dt_ms,
            width_px,
            height_px,
            int(cfg.dpi),
            cfg.background_hex,
            float(cfg.conversion_timeout_s),
        )
        return ConversionResult(
            svg_hash=svg_hash,
            png_bytes=composed,
            render_ms=dt_ms,
            width_px=width_px,
            height_px=height_px,
        )


