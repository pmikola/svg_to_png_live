"""Clipboard watcher and debounced conversion dispatch."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from svg_to_png_live.config import AppConfig
from svg_to_png_live.convert.svg_detect import normalize_svg_markup


@dataclass(frozen=True)
class ConversionResult:
    """Result returned by the conversion worker."""

    svg_hash: str
    png_bytes: bytes
    render_ms: float
    width_px: int | None = None
    height_px: int | None = None


class _WorkerSignals(QObject):
    finished = Signal(object)  # ConversionResult
    failed = Signal(str)


class _ConvertWorker(QRunnable):
    def __init__(self, svg_text: str, fn: Callable[[str], ConversionResult]) -> None:
        super().__init__()
        self._svg_text = svg_text
        self._fn = fn
        self.signals = _WorkerSignals()

    def run(self) -> None:
        try:
            result = self._fn(self._svg_text)
        except Exception as e:
            self.signals.failed.emit(str(e))
            return
        self.signals.finished.emit(result)


class ClipboardWatcher(QObject):
    """Watches the clipboard for SVG text and dispatches conversion off the UI thread."""

    converted = Signal(object)  # ConversionResult
    info = Signal(str)
    error = Signal(str)

    def __init__(self, config: AppConfig, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._log = logging.getLogger("svg_to_png_live.clipboard")

        self._cfg = config
        self._clipboard = QGuiApplication.clipboard()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._on_debounce_timeout)

        self._running = False
        self._pending_svg: str | None = None
        self._last_processed_hash: str | None = None
        self._ignore_until: float = 0.0
        self._in_flight: bool = False
        self._rerun_after_flight: bool = False

        self._converter: Optional[Callable[[str], ConversionResult]] = None

    def set_config(self, config: AppConfig) -> None:
        self._cfg = config
        if self._running:
            self._debounce.setInterval(int(self._cfg.debounce_ms))

    def set_converter(self, converter: Callable[[str], ConversionResult]) -> None:
        self._converter = converter

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._clipboard.dataChanged.connect(self._on_clipboard_changed)
        self._debounce.setInterval(int(self._cfg.debounce_ms))
        self.info.emit("Listening")

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        try:
            self._clipboard.dataChanged.disconnect(self._on_clipboard_changed)
        except Exception:
            pass
        self._pending_svg = None
        self._debounce.stop()
        self._in_flight = False
        self.info.emit("Stopped")

    def suppress_events_for(self, seconds: float = 0.3) -> None:
        self._ignore_until = max(self._ignore_until, time.monotonic() + seconds)

    def _on_clipboard_changed(self) -> None:
        if not self._running:
            return
        if time.monotonic() < self._ignore_until:
            return

        mime = self._clipboard.mimeData()
        if mime is None:
            return
        if mime.hasImage():
            return
        if not mime.hasText():
            return

        raw_text = mime.text()
        if not raw_text:
            return
        if len(raw_text) > int(self._cfg.max_svg_chars):
            self._log.info("clipboard_text_too_large chars=%d", len(raw_text))
            return

        svg = normalize_svg_markup(raw_text)
        if svg is None:
            return

        self._pending_svg = svg
        self._debounce.start(int(self._cfg.debounce_ms))

    def _on_debounce_timeout(self) -> None:
        if not self._running:
            return
        if self._pending_svg is None:
            return
        if self._in_flight:
            # Avoid piling up conversions and spiking CPU; the latest SVG remains in _pending_svg.
            self._rerun_after_flight = True
            return

        mime = self._clipboard.mimeData()
        if mime is None or not mime.hasText():
            return
        current = normalize_svg_markup(mime.text() or "")
        if current is None or current != self._pending_svg:
            return

        svg_hash = hashlib.sha256(current.encode("utf-8")).hexdigest()
        if svg_hash == self._last_processed_hash:
            return

        if self._converter is None:
            self.error.emit("Converter is not configured.")
            return

        self._in_flight = True
        worker = _ConvertWorker(current, self._converter)
        worker.signals.finished.connect(self._on_worker_finished)
        worker.signals.failed.connect(self._on_worker_failed)
        self._pool.start(worker)

    def _on_worker_failed(self, message: str) -> None:
        self._in_flight = False
        self.error.emit(message)
        self._maybe_rerun_latest()

    def _on_worker_finished(self, result: ConversionResult) -> None:
        self._in_flight = False
        self._last_processed_hash = result.svg_hash
        self.converted.emit(result)
        self._maybe_rerun_latest()

    def _maybe_rerun_latest(self) -> None:
        if not self._running:
            self._rerun_after_flight = False
            return
        if not self._rerun_after_flight:
            return
        self._rerun_after_flight = False
        # Re-check clipboard immediately; if it still contains SVG markup, convert once more.
        self._debounce.start(0)




