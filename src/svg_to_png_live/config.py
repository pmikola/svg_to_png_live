"""Configuration persistence for svg-to-png-live.

The configuration is stored in a JSON file under `%APPDATA%\\SvgToPngLive\\config.json`.
This keeps settings stable across restarts while remaining easy to inspect or reset.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

APP_DIR_NAME: Final[str] = "SvgToPngLive"
CONFIG_FILE_NAME: Final[str] = "config.json"


def _default_appdata_dir() -> Path:
    appdata = os.getenv("APPDATA")
    if appdata:
        return Path(appdata)
    return Path.home() / "AppData" / "Roaming"


def get_config_path() -> Path:
    return _default_appdata_dir() / APP_DIR_NAME / CONFIG_FILE_NAME


@dataclass
class AppConfig:
    """User-configurable settings.

    Notes:
    - `background_hex` is a solid RGB color in `#RRGGBB` form.
    - `dpi` is used to scale CSS pixel dimensions by `dpi / 96`.
    """

    dpi: int = 300
    background_hex: str = "#FFFFFF"

    listen_enabled: bool = False

    save_enabled: bool = False
    save_dir: str = ""

    debounce_ms: int = 200
    conversion_timeout_s: float = 30.0
    # Large SVGs can legitimately embed base64 images and exceed tens of MB.
    # This limit exists to protect responsiveness; users can raise it in Settings → Advanced.
    max_svg_chars: int = 200_000_000
    # 0 disables pixel-dimension clamping. If you disable the clamp, set a max PNG size
    # to avoid extremely large clipboard payloads.
    max_output_dim_px: int = 16384
    # 0 disables size limiting. If set, the converter will downscale as needed to keep
    # the final PNG at or below this byte size.
    max_output_png_bytes: int = 0
    # Optional post-processing to remove padded borders (common in Mermaid SVGs due to viewBox margins).
    trim_border: bool = False
    trim_tolerance: int = 8

    cache_enabled: bool = True
    cache_max_items: int = 128

    def to_dict(self) -> dict[str, Any]:
        return {
            "dpi": self.dpi,
            "background_hex": self.background_hex,
            "listen_enabled": self.listen_enabled,
            "save_enabled": self.save_enabled,
            "save_dir": self.save_dir,
            "debounce_ms": self.debounce_ms,
            "conversion_timeout_s": self.conversion_timeout_s,
            "max_svg_chars": self.max_svg_chars,
            "max_output_dim_px": self.max_output_dim_px,
            "max_output_png_bytes": self.max_output_png_bytes,
            "trim_border": self.trim_border,
            "trim_tolerance": self.trim_tolerance,
            "cache_enabled": self.cache_enabled,
            "cache_max_items": self.cache_max_items,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AppConfig":
        cfg = cls()
        for k, v in raw.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg

    @classmethod
    def load(cls) -> "AppConfig":
        path = get_config_path()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return cls()
        if not isinstance(data, dict):
            return cls()
        return cls.from_dict(data)

    def save(self) -> None:
        path = get_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")



