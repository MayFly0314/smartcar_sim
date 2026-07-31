"""本帧流程面板：sim_trace / SIM_COND 记录的执行轨迹，随时间轴逐帧显示。

行型：
  · 节点（sim_trace）——白色圆点行，标记"到了哪一步"
  ✓ 条件真（SIM_COND）——绿色
  ✗ 条件假（SIM_COND）——灰红色
逐帧对比着看，就能定位"这帧为什么进/没进某分支"。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from ..run.protocol import FrameResult
from .image_view import _tip_html
from .watch_panel import _Header

_ROW_H = 20
_MAX_VISIBLE_ROWS = 10

_C_NODE = QColor("#d4d4d4")   # 节点：普通白
_C_TRUE = QColor("#4ec9b0")   # 条件✓：绿
_C_FALSE = QColor("#8a5a5a")  # 条件✗：暗红（不刺眼，扫一眼能分辨）


class TracePanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._frames: list[FrameResult] = []
        self._header = _Header("本帧流程")
        self._list = QListWidget()
        self._list.setFont(QFont("Consolas", 9))
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setStyleSheet(
            "QListWidget { background:#1e1e1e; color:#d4d4d4; border:none; outline:0; }"
            "QListWidget::item { padding:1px 6px; }"
            "QListWidget::item:hover { background:#2a2d2e; }"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._header)
        lay.addWidget(self._list)

        self._header.toggled.connect(
            lambda: self._list.setVisible(not self._header.collapsed)
        )
        self.setVisible(False)

    # ---- 对外 API（与 TagPanel 同构）----
    def set_run(self, frames: list[FrameResult]) -> None:
        self._frames = frames
        if not any(fr.traces for fr in frames):
            self.clear()
            return
        max_rows = max(len(fr.traces) for fr in frames)
        self._list.setFixedHeight(min(max_rows, _MAX_VISIBLE_ROWS) * _ROW_H)
        self.setVisible(True)
        self._list.setVisible(not self._header.collapsed)

    def set_current_frame(self, idx: int) -> None:
        traces = self._frames[idx].traces if 0 <= idx < len(self._frames) else []
        self._list.clear()
        for kind, text in traces:
            if kind < 0:
                it = QListWidgetItem(f"· {text}")
                it.setForeground(_C_NODE)
            elif kind == 1:
                it = QListWidgetItem(f"✓ {text}")
                it.setForeground(_C_TRUE)
            else:
                it = QListWidgetItem(f"✗ {text}")
                it.setForeground(_C_FALSE)
            it.setToolTip(_tip_html([text]))
            self._list.addItem(it)
        self._header.set_count(len(traces))

    def clear(self) -> None:
        self._frames = []
        self._list.clear()
        self._header.set_count(None)
        self.setVisible(False)
