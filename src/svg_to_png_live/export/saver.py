"""Asynchronous PNG saving (auto-save)."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from svg_to_png_live.config import AppConfig


def generate_png_filename(svg_hash: str, *, now: datetime | None = None) -> str:
    ts = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    short = (svg_hash or "unknown")[:10]
    return f"{ts}_{short}.png"


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}"
    tmp_path = path.parent / tmp_name
    try:
        tmp_path.write_bytes(data)
        os.replace(tmp_path, path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


@dataclass(frozen=True)
class SaveResult:
    path: str


class _SaveSignals(QObject):
    finished = Signal(object)  # SaveResult
    failed = Signal(str)


class _SaveWorker(QRunnable):
    def __init__(self, png_bytes: bytes, out_dir: Path, filename: str) -> None:
        super().__init__()
        self._png = png_bytes
        self._out_dir = out_dir
        self._filename = filename
        self.signals = _SaveSignals()

    def run(self) -> None:
        try:
            out_path = self._out_dir / self._filename
            atomic_write_bytes(out_path, self._png)
        except Exception as e:
            self.signals.failed.emit(str(e))
            return
        self.signals.finished.emit(SaveResult(path=str(out_path)))


class PngAutoSaver(QObject):
    """Manages optional disk saving of converted PNG bytes."""

    saved = Signal(str)  # path
    error = Signal(str)

    def __init__(self, config: AppConfig, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._cfg = config

    def set_config(self, config: AppConfig) -> None:
        self._cfg = config

    def save_async(self, *, png_bytes: bytes, svg_hash: str) -> None:
        if not self._cfg.save_enabled:
            return
        out_dir = Path(self._cfg.save_dir).expanduser()
        filename = generate_png_filename(svg_hash)
        worker = _SaveWorker(png_bytes, out_dir, filename)
        worker.signals.finished.connect(lambda r: self.saved.emit(r.path))
        worker.signals.failed.connect(self.error.emit)
        self._pool.start(worker)





