"""QWebChannel 桥：JS <-> Python。"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot


class EditorBridge(QObject):
    """暴露给 Monaco 页面的对象（channel.objects.bridge）。"""

    # 内部信号，转发给 MonacoWidget
    _ready = Signal()
    _save = Signal(str)
    _dirty = Signal()

    @Slot()
    def editor_ready(self) -> None:
        self._ready.emit()

    @Slot(str)
    def save_requested(self, text: str) -> None:
        self._save.emit(text)

    @Slot()
    def content_changed(self) -> None:
        self._dirty.emit()
