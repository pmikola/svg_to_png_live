"""Qt application wiring (Windows v1)."""

from __future__ import annotations

import logging
import sys
from typing import Optional

from PySide6.QtCore import QObject, QLockFile, QMimeData
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QApplication, QMessageBox

from svg_to_png_live.config import AppConfig, get_config_path
from svg_to_png_live.clipboard.watcher import ClipboardWatcher, ConversionResult
from svg_to_png_live.convert.renderer import ResvgRenderer, SvgToPngConverter, find_resvg_exe
from svg_to_png_live.export.saver import PngAutoSaver
from svg_to_png_live.ui.main_window import MainWindow
from svg_to_png_live.ui.settings_dialog import SettingsDialog
from svg_to_png_live.ui.tray import TrayController


def _setup_logging() -> None:
    config_path = get_config_path()
    log_dir = config_path.parent
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "app.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


class AppController(QObject):
    """Owns top-level app state and connects UI to services."""

    def __init__(self) -> None:
        super().__init__()
        self._log = logging.getLogger("svg_to_png_live")

        self._config = AppConfig.load()
        self._log.info(
            "config_loaded dpi=%s bg=%s timeout=%.1fs save_enabled=%s save_dir=%s",
            self._config.dpi,
            self._config.background_hex,
            float(self._config.conversion_timeout_s),
            bool(self._config.save_enabled),
            self._config.save_dir,
        )

        self._window = MainWindow()
        self._window.set_listening(bool(self._config.listen_enabled))
        self._window.listen_toggled.connect(self._on_listen_toggled)
        self._window.settings_requested.connect(self._open_settings)
        self._window.exit_requested.connect(QApplication.instance().quit)
        self._window.close_requested.connect(self._on_close_requested)

        self._watcher = ClipboardWatcher(self._config, parent=self)
        self._watcher.info.connect(self._window.set_status_text)
        self._watcher.error.connect(self._on_error)
        self._watcher.converted.connect(self._on_converted)

        self._converter: Optional[SvgToPngConverter] = None
        self._init_converter()

        self._saver = PngAutoSaver(self._config, parent=self)
        self._saver.saved.connect(self._on_saved)
        self._saver.error.connect(self._on_error)

        self._tray = TrayController(parent=self)
        self._tray.toggle_listen_requested.connect(self._on_listen_toggled)
        self._tray.open_settings_requested.connect(self._open_settings)
        self._tray.show_window_requested.connect(self._show_main_window)
        self._tray.exit_requested.connect(QApplication.instance().quit)
        self._tray.set_listening(bool(self._config.listen_enabled))
        self._tray.set_save_dir(enabled=bool(self._config.save_enabled), path=self._config.save_dir)
        self._tray.show()

        self._window.show()

        if self._config.listen_enabled:
            self._watcher.start()

    def _on_listen_toggled(self, enabled: bool) -> None:
        self._config.listen_enabled = bool(enabled)
        self._config.save()
        self._window.set_listening(enabled)
        self._tray.set_listening(enabled)
        if enabled:
            self._watcher.start()
        else:
            self._watcher.stop()
        self._log.info("listen=%s", enabled)

    def _open_settings(self) -> None:
        # Use no parent so the dialog always shows, even when the main window is hidden to tray.
        self._log.info("settings_opened")
        dlg = SettingsDialog(self._config, parent=None)
        result = int(dlg.exec())
        self._log.info("settings_closed result=%s", result)

        # SettingsDialog is designed to always Save on close (no cancel paths).
        # Apply whatever is currently in the dialog model.
        self._config = dlg.result_config()
        self._config.save()
        self._window.set_listening(bool(self._config.listen_enabled))
        self._tray.set_listening(bool(self._config.listen_enabled))
        self._tray.set_save_dir(enabled=bool(self._config.save_enabled), path=self._config.save_dir)
        self._watcher.set_config(self._config)
        if self._converter is not None:
            self._converter.set_config(self._config)
        self._saver.set_config(self._config)
        self._log.info(
            "settings_applied dpi=%s bg=%s timeout=%.1fs save_enabled=%s save_dir=%s",
            self._config.dpi,
            self._config.background_hex,
            float(self._config.conversion_timeout_s),
            bool(self._config.save_enabled),
            self._config.save_dir,
        )
        self._tray.notify_info(
            "SVG → PNG Live",
            f"Settings saved: DPI={self._config.dpi}, BG={self._config.background_hex}, timeout={float(self._config.conversion_timeout_s):.1f}s",
        )

    def _init_converter(self) -> None:
        try:
            resvg = find_resvg_exe()
        except Exception as e:
            self._converter = None
            self._watcher.set_converter(lambda _: (_ for _ in ()).throw(RuntimeError(str(e))))
            self._window.set_status_text(f"Missing resvg.exe: {e}")
            self._log.warning("resvg_missing=%s", e)
            return

        renderer = ResvgRenderer(resvg)
        self._converter = SvgToPngConverter(self._config, renderer)
        self._watcher.set_converter(self._converter.convert)
        self._log.info("resvg_path=%s", resvg)

    def _on_error(self, message: str) -> None:
        self._log.warning("error=%s", message)
        self._window.set_status_text(f"Error: {message}")
        self._tray.notify_error("SVG → PNG Live", message)

    def _on_converted(self, result: ConversionResult) -> None:
        ok = self._write_png_to_clipboard(result.png_bytes)
        if not ok:
            return
        ms = result.render_ms
        dims = (
            f"{result.width_px}×{result.height_px}" if result.width_px and result.height_px else "PNG"
        )
        if ms <= 0.0:
            self._window.set_status_text(f"Converted (cached) {dims}")
        else:
            self._window.set_status_text(f"Converted {dims} in {ms:.0f} ms")

        self._saver.save_async(png_bytes=result.png_bytes, svg_hash=result.svg_hash)

    def _write_png_to_clipboard(self, png_bytes: bytes) -> bool:
        width_px, height_px = self._parse_png_dimensions(png_bytes)

        # Prevent clipboard rewrite loops (Qt emits dataChanged for our own write).
        self._watcher.suppress_events_for(0.5)

        # For very large images, setting an uncompressed bitmap (DIB) on the clipboard can
        # allocate hundreds of MB and cause silent paste failures. Prefer a PNG clipboard
        # format for large outputs; add DIB only when reasonably sized.
        max_dib_bytes = 64 * 1024 * 1024
        expected_dib_bytes = int(width_px) * int(height_px) * 4 if width_px and height_px else 0

        if sys.platform.startswith("win"):
            try:
                from svg_to_png_live.clipboard.win_clipboard import set_windows_clipboard_png

                stats = set_windows_clipboard_png(
                    png_bytes,
                    width_px=int(width_px),
                    height_px=int(height_px),
                    dpi=int(self._config.dpi),
                    also_set_dibv5=True,
                    max_dibv5_bytes=max_dib_bytes,
                )
                self._log.info("clipboard_written png=%s dibv5=%s", stats.wrote_png, stats.wrote_dibv5)
                return True
            except Exception as e:
                # Fallback to Qt clipboard if WinAPI path fails (clipboard busy, etc.).
                self._log.warning("win_clipboard_failed=%s", e)

        mime = QMimeData()
        mime.setData("image/png", png_bytes)
        if expected_dib_bytes <= max_dib_bytes:
            img = QImage.fromData(png_bytes, "PNG")
            if img.isNull():
                self._log.warning("qt_image_decode_failed")
            else:
                mime.setImageData(img)
        QGuiApplication.clipboard().setMimeData(mime)
        return True

    @staticmethod
    def _parse_png_dimensions(png_bytes: bytes) -> tuple[int, int]:
        # PNG signature + IHDR chunk parsing (no full decode; safe for very large images).
        if len(png_bytes) < 24:
            return 0, 0
        if png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
            return 0, 0
        # IHDR must be the first chunk.
        if png_bytes[12:16] != b"IHDR":
            return 0, 0
        w = int.from_bytes(png_bytes[16:20], "big", signed=False)
        h = int.from_bytes(png_bytes[20:24], "big", signed=False)
        return int(w), int(h)

    def _on_saved(self, path: str) -> None:
        self._log.info("saved=%s", path)
        self._window.set_status_text(f"Saved: {path}")

    def _show_main_window(self) -> None:
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    def _on_close_requested(self) -> None:
        self._window.hide()
        self._tray.notify_info("SVG → PNG Live", "Running in background (tray).")


def run_app() -> None:
    _setup_logging()

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)

    lock_path = get_config_path().parent / "instance.lock"
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(10_000)
    if not lock.tryLock(0):
        # If a previous run crashed, attempt to clear the stale lock file once.
        try:
            if lock.removeStaleLockFile() and lock.tryLock(0):
                pass
            else:
                QMessageBox.information(
                    None,
                    "SVG → PNG Live",
                    "SVG → PNG Live is already running.\n\nCheck the system tray (near the clock).",
                )
                raise SystemExit(0)
        except Exception:
            QMessageBox.information(
                None,
                "SVG → PNG Live",
                "SVG → PNG Live is already running.\n\nCheck the system tray (near the clock).",
            )
            raise SystemExit(0)

    _ = AppController()
    raise SystemExit(app.exec())


