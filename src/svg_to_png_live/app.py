"""Qt application wiring (Windows v1)."""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QObject
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QApplication

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
        dlg = SettingsDialog(self._config, parent=self._window)
        if dlg.exec() == dlg.Accepted:
            self._config = dlg.result_config()
            self._config.save()
            self._window.set_listening(bool(self._config.listen_enabled))
            self._tray.set_listening(bool(self._config.listen_enabled))
            self._tray.set_save_dir(enabled=bool(self._config.save_enabled), path=self._config.save_dir)
            self._watcher.set_config(self._config)
            if self._converter is not None:
                self._converter.set_config(self._config)
            self._saver.set_config(self._config)
            self._log.info("settings_updated")

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
        img = QImage.fromData(png_bytes, "PNG")
        if img.isNull():
            self._on_error("Failed to load PNG bytes into QImage.")
            return False

        # Prevent clipboard rewrite loops (Qt emits dataChanged for our own write).
        self._watcher.suppress_events_for(0.5)
        QGuiApplication.clipboard().setImage(img)
        return True

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

    _ = AppController()
    raise SystemExit(app.exec())


