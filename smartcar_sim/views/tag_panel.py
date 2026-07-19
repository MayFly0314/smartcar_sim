"""本帧标注面板：sim_tag 记录的 (x, y, 文本) 列表，点击行在图上高亮该点。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from ..run.protocol import FrameResult
from .image_view import _tip_html
from .watch_panel import _Header

_ROW_H = 20
_MAX_VISIBLE_ROWS = 6


class TagPanel(QWidget):
    tag_selected = Signal(int, int)  # (x, y)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frames: list[FrameResult] = []
        self._header = _Header("本帧标注")
        self._list = QListWidget()
        self._list.setFont(QFont("Consolas", 9))
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setStyleSheet(
            "QListWidget { background:#1e1e1e; color:#d4d4d4; border:none; outline:0; }"
            "QListWidget::item { padding:1px 6px; }"
            "QListWidget::item:hover { background:#2a2d2e; }"
            "QListWidget::item:selected { background:#264f78; color:#ffffff; }"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._header)
        lay.addWidget(self._list)

        self._header.toggled.connect(
            lambda: self._list.setVisible(not self._header.collapsed)
        )
        self._list.itemClicked.connect(self._on_item)
        self.setVisible(False)

    # ---- 对外 API（与 WatchPanel 同构）----
    def set_run(self, frames: list[FrameResult]) -> None:
        self._frames = frames
        if not any(fr.tags for fr in frames):
            self.clear()
            return
        # 高度按整 run 的最大行数定死，播放时不抖动
        max_rows = max(len(fr.tags) for fr in frames)
        self._list.setFixedHeight(min(max_rows, _MAX_VISIBLE_ROWS) * _ROW_H)
        self.setVisible(True)
        self._list.setVisible(not self._header.collapsed)

    def set_current_frame(self, idx: int) -> None:
        tags = self._frames[idx].tags if 0 <= idx < len(self._frames) else []
        self._list.clear()
        for x, y, t in tags:
            it = QListWidgetItem(f"({x}, {y})  {t}")
            it.setData(Qt.ItemDataRole.UserRole, (x, y))
            it.setToolTip(_tip_html([t]))  # 长文本被裁时兜底
            self._list.addItem(it)
        self._header.set_count(len(tags))

    def clear(self) -> None:
        self._frames = []
        self._list.clear()
        self._header.set_count(None)
        self.setVisible(False)

    def _on_item(self, item: QListWidgetItem) -> None:
        x, y = item.data(Qt.ItemDataRole.UserRole)
        self.tag_selected.emit(x, y)
