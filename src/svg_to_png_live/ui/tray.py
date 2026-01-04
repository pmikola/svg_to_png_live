"""System tray integration (Windows v1).

The tray icon is the primary surface for long-running background control:
- Toggle listen on/off
- Open settings / show main window
- Open save folder (if enabled)
- Exit
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtCore import QSignalBlocker
from PySide6.QtGui import QAction, QDesktopServices, QIcon
from PySide6.QtWidgets import QMenu, QStyle, QSystemTrayIcon, QWidget


class TrayController(QObject):
    """Owns the QSystemTrayIcon and its menu."""

    toggle_listen_requested = Signal(bool)
    open_settings_requested = Signal()
    show_window_requested = Signal()
    exit_requested = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tray = QSystemTrayIcon(self._default_icon(), None)
        self._tray.setToolTip("SVG → PNG Live")

        menu = QMenu()

        self._listen_action = QAction("Listen", menu)
        self._listen_action.setCheckable(True)
        self._listen_action.toggled.connect(self.toggle_listen_requested)

        self._show_action = QAction("Show", menu)
        self._show_action.triggered.connect(self.show_window_requested)

        self._settings_action = QAction("Settings", menu)
        self._settings_action.triggered.connect(self.open_settings_requested)

        self._open_save_dir_action = QAction("Open Save Folder", menu)
        self._open_save_dir_action.triggered.connect(self._open_save_dir)
        self._open_save_dir_action.setEnabled(False)
        self._save_dir: Path | None = None

        self._exit_action = QAction("Exit", menu)
        self._exit_action.triggered.connect(self.exit_requested)

        menu.addAction(self._listen_action)
        menu.addSeparator()
        menu.addAction(self._show_action)
        menu.addAction(self._settings_action)
        menu.addAction(self._open_save_dir_action)
        menu.addSeparator()
        menu.addAction(self._exit_action)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_activated)

    def show(self) -> None:
        self._tray.show()

    def hide(self) -> None:
        self._tray.hide()

    def set_listening(self, enabled: bool) -> None:
        if self._listen_action.isChecked() != enabled:
            with QSignalBlocker(self._listen_action):
                self._listen_action.setChecked(enabled)

    def set_save_dir(self, *, enabled: bool, path: str) -> None:
        if enabled and path:
            p = Path(path)
            self._save_dir = p
            self._open_save_dir_action.setEnabled(True)
        else:
            self._save_dir = None
            self._open_save_dir_action.setEnabled(False)

    def notify_error(self, title: str, message: str) -> None:
        self._tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Critical)

    def notify_info(self, title: str, message: str) -> None:
        self._tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information)

    def _default_icon(self) -> QIcon:
        w = QWidget()
        return w.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_window_requested.emit()

    def _open_save_dir(self) -> None:
        if self._save_dir is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._save_dir)))




