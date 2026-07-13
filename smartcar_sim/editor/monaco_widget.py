"""MonacoWidget：QWebEngineView 封装的 C 代码编辑器。"""
from __future__ import annotations

import json
from typing import Callable

from PySide6.QtCore import QUrl, Signal
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

from ..paths import ASSETS_DIR
from .bridge import EditorBridge
from .scheme_handler import SCHEME, SchemeHandler


class _EditorPage(QWebEnginePage):
    console_message = Signal(int, str, int, str)  # level, msg, line, src

    def javaScriptConsoleMessage(self, level, msg, line, src):  # noqa: N802
        self.console_message.emit(int(level.value) if hasattr(level, "value") else int(level), msg, line, src)


class MonacoWidget(QWebEngineView):
    ready = Signal()
    save_requested = Signal(str)   # Ctrl+S，携带全文
    dirty_changed = Signal(bool)
    console_message = Signal(int, str, int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_ready = False
        self._dirty = False

        self._profile = QWebEngineProfile(self)  # 独立 profile，不落盘
        self._handler = SchemeHandler(ASSETS_DIR, self)
        self._profile.installUrlSchemeHandler(SCHEME, self._handler)

        page = _EditorPage(self._profile, self)
        page.console_message.connect(self.console_message)
        self.setPage(page)

        self._bridge = EditorBridge(self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("bridge", self._bridge)
        page.setWebChannel(self._channel)

        self._bridge._ready.connect(self._on_ready)
        self._bridge._save.connect(self.save_requested)
        self._bridge._dirty.connect(self._on_dirty)

        self.load(QUrl("app://app/editor.html"))

    # ---- 状态 ----
    def _on_ready(self) -> None:
        self._is_ready = True
        self.ready.emit()

    def _on_dirty(self) -> None:
        if not self._dirty:
            self._dirty = True
            self.dirty_changed.emit(True)

    def mark_saved(self) -> None:
        if self._dirty:
            self._dirty = False
            self.dirty_changed.emit(False)

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    # ---- 内容操作 ----
    def set_text(self, text: str) -> None:
        self.page().runJavaScript(f"setText({json.dumps(text)})")
        self.mark_saved()

    def get_text_async(self, callback: Callable[[str], None]) -> None:
        self.page().runJavaScript("getText()", 0, callback)

    def goto(self, line: int, col: int = 1) -> None:
        self.page().runJavaScript(f"gotoLine({int(line)}, {int(col)})")

    def set_markers(self, diags) -> None:
        """diags: list[Diagnostic]（只传当前文件的）。"""
        markers = [
            {"line": d.line, "col": d.col, "message": d.msg, "severity": d.severity}
            for d in diags
        ]
        self.page().runJavaScript(f"setMarkers({json.dumps(json.dumps(markers))})")

    def clear_markers(self) -> None:
        self.page().runJavaScript("clearMarkers()")
