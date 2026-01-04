"""Main application window (minimal control surface)."""

from __future__ import annotations

from PySide6.QtCore import Signal, QSignalBlocker
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class MainWindow(QMainWindow):
    """Main window.

    This window is intentionally minimal: the app is meant to run tray-first once implemented.
    """

    listen_toggled = Signal(bool)
    settings_requested = Signal()
    exit_requested = Signal()
    close_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SVG → PNG Live")

        self._listen_btn = QPushButton("Listen")
        self._listen_btn.setCheckable(True)
        self._listen_btn.toggled.connect(self.listen_toggled)

        self._settings_btn = QPushButton("Settings")
        self._settings_btn.clicked.connect(self.settings_requested)

        self._exit_btn = QPushButton("Exit")
        self._exit_btn.clicked.connect(self.exit_requested)

        self._status = QLabel("Stopped")

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._listen_btn)
        btn_row.addWidget(self._settings_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self._exit_btn)

        root = QVBoxLayout()
        root.addLayout(btn_row)
        root.addWidget(self._status)

        w = QWidget()
        w.setLayout(root)
        self.setCentralWidget(w)

        self.resize(520, 120)

    def set_listening(self, enabled: bool) -> None:
        if self._listen_btn.isChecked() != enabled:
            with QSignalBlocker(self._listen_btn):
                self._listen_btn.setChecked(enabled)
        self._status.setText("Listening" if enabled else "Stopped")

    def set_status_text(self, text: str) -> None:
        self._status.setText(text)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.close_requested.emit()
        event.ignore()


