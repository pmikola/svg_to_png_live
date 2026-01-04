"""Settings dialog for conversion and auto-save behavior."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from svg_to_png_live.config import AppConfig


def _normalize_hex_rgb(value: str) -> str:
    v = value.strip()
    if not v:
        return "#FFFFFF"
    if not v.startswith("#"):
        v = f"#{v}"
    if len(v) != 7:
        raise ValueError("Background color must be in #RRGGBB format.")
    int(v[1:], 16)
    return v.upper()


class SettingsDialog(QDialog):
    """Modal dialog used to edit `AppConfig`."""

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)

        self._allow_close_without_accept = False

        self._original = config
        self._working = replace(config)

        self._dpi = QSpinBox()
        self._dpi.setRange(24, 2400)
        self._dpi.setValue(int(self._working.dpi))

        self._bg = QLineEdit(self._working.background_hex)
        self._bg_btn = QPushButton("Pick…")
        self._bg_btn.clicked.connect(self._pick_bg)

        bg_row = QHBoxLayout()
        bg_row.addWidget(self._bg)
        bg_row.addWidget(self._bg_btn)

        self._save_enabled = QCheckBox("Save converted PNGs to disk")
        self._save_enabled.setChecked(bool(self._working.save_enabled))

        self._save_dir = QLineEdit(self._working.save_dir)
        self._save_dir.setPlaceholderText("Select an output folder…")
        self._save_dir_btn = QPushButton("Browse…")
        self._save_dir_btn.clicked.connect(self._browse_save_dir)
        self._open_dir_btn = QPushButton("Open")
        self._open_dir_btn.clicked.connect(self._open_save_dir)

        save_row = QHBoxLayout()
        save_row.addWidget(self._save_dir)
        save_row.addWidget(self._save_dir_btn)
        save_row.addWidget(self._open_dir_btn)

        self._adv_group = QGroupBox("Advanced")
        self._adv_group.setCheckable(False)
        adv_form = QFormLayout()

        self._debounce = QSpinBox()
        self._debounce.setRange(50, 2000)
        self._debounce.setValue(int(self._working.debounce_ms))
        adv_form.addRow("Debounce (ms)", self._debounce)

        self._max_svg = QSpinBox()
        self._max_svg.setRange(10_000, 20_000_000)
        self._max_svg.setSingleStep(100_000)
        self._max_svg.setValue(int(self._working.max_svg_chars))
        adv_form.addRow("Max SVG size (chars)", self._max_svg)

        self._max_dim = QSpinBox()
        self._max_dim.setRange(512, 32768)
        self._max_dim.setValue(int(self._working.max_output_dim_px))
        adv_form.addRow("Max output dimension (px)", self._max_dim)

        self._timeout_s = QDoubleSpinBox()
        self._timeout_s.setRange(0.5, 120.0)
        self._timeout_s.setSingleStep(0.5)
        self._timeout_s.setValue(float(self._working.conversion_timeout_s))
        adv_form.addRow("Conversion timeout (s)", self._timeout_s)

        self._adv_group.setLayout(adv_form)

        form = QFormLayout()
        form.addRow("DPI", self._dpi)
        form.addRow("Background", bg_row)
        form.addRow("", self._save_enabled)
        form.addRow("Save folder", save_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self._on_cancel)

        err = QLabel("")
        err.setTextInteractionFlags(Qt.TextSelectableByMouse)
        err.setStyleSheet("color: #a00;")
        self._error = err

        root = QVBoxLayout()
        root.addLayout(form)
        root.addWidget(self._adv_group)
        root.addWidget(self._error)
        root.addWidget(buttons)

        self.setLayout(root)
        self.resize(560, 260)

        self._save_enabled.toggled.connect(self._sync_save_enabled_ui)
        self._sync_save_enabled_ui(self._save_enabled.isChecked())

    def _on_cancel(self) -> None:
        self._allow_close_without_accept = True
        super().reject()

    def result_config(self) -> AppConfig:
        return self._working

    def _sync_save_enabled_ui(self, enabled: bool) -> None:
        self._save_dir.setEnabled(enabled)
        self._save_dir_btn.setEnabled(enabled)
        self._open_dir_btn.setEnabled(enabled)

    def _pick_bg(self) -> None:
        current = QColor(self._bg.text().strip() or "#FFFFFF")
        color = QColorDialog.getColor(current, self, "Pick background color")
        if not color.isValid():
            return
        self._bg.setText(color.name(QColor.NameFormat.HexRgb).upper())

    def _browse_save_dir(self) -> None:
        start = self._save_dir.text().strip()
        if start and not Path(start).exists():
            start = ""
        path = QFileDialog.getExistingDirectory(self, "Select output folder", start)
        if path:
            self._save_dir.setText(path)

    def _open_save_dir(self) -> None:
        path = self._save_dir.text().strip()
        if not path:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def accept(self) -> None:
        self._error.setText("")
        try:
            self._working.dpi = int(self._dpi.value())
            self._working.background_hex = _normalize_hex_rgb(self._bg.text())
            self._working.save_enabled = bool(self._save_enabled.isChecked())
            self._working.save_dir = self._save_dir.text().strip()
            self._working.debounce_ms = int(self._debounce.value())
            self._working.max_svg_chars = int(self._max_svg.value())
            self._working.max_output_dim_px = int(self._max_dim.value())
            self._working.conversion_timeout_s = float(self._timeout_s.value())

            if self._working.save_enabled and not self._working.save_dir:
                raise ValueError("Auto-save is enabled, but no output folder is selected.")
        except Exception as e:
            self._error.setText(str(e))
            return

        super().accept()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        # Treat window close (X) as an implicit "OK" to reduce accidental loss of settings.
        # Explicit "Cancel" still discards changes.
        if self._allow_close_without_accept:
            event.accept()
            return
        event.ignore()
        self.accept()


