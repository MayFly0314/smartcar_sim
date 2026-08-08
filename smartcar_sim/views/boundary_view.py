"""三条边界数组的白底预览。"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class BoundaryView(QWidget):
    """按行号绘制三条 x 坐标数组，-1/越界值作为无效点跳过。"""

    _COLORS = (QColor("#e53935"), QColor("#1976d2"), QColor("#2e7d32"))

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(180, 140)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._lines: list[tuple[str, np.ndarray]] = []
        self._width = 0
        self._height = 0
        self._frame = 0

    def set_lines(
        self,
        lines: list[tuple[str, np.ndarray]],
        width: int,
        height: int,
    ) -> None:
        self._lines = [(str(name), np.asarray(values).reshape(-1)) for name, values in lines[:3]]
        self._width = max(0, int(width))
        self._height = max(0, int(height))
        self.update()

    def set_current_frame(self, idx: int) -> None:
        self._frame = max(0, int(idx))
        self.update()

    def clear(self) -> None:
        self._lines = []
        self._width = self._height = 0
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#ffffff"))
        if self._width <= 0 or self._height <= 0:
            p.end()
            return

        margin = 14.0
        avail_w = max(1.0, self.width() - 2 * margin)
        avail_h = max(1.0, self.height() - 2 * margin)
        scale = min(avail_w / self._width, avail_h / self._height)
        ox = (self.width() - self._width * scale) / 2.0
        oy = (self.height() - self._height * scale) / 2.0

        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for line_idx, (_name, values) in enumerate(self._lines):
            pen = QPen(self._COLORS[line_idx % len(self._COLORS)])
            pen.setWidthF(max(2.0, min(5.0, 2.2 * scale)))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            prev: QPointF | None = None
            for y, raw_x in enumerate(values[: self._height]):
                try:
                    x = float(raw_x)
                except (TypeError, ValueError):
                    prev = None
                    continue
                if not math.isfinite(x) or x < 0 or x >= self._width:
                    prev = None
                    continue
                pt = QPointF(ox + (x + 0.5) * scale, oy + (y + 0.5) * scale)
                if prev is not None:
                    p.drawLine(prev, pt)
                else:
                    p.drawPoint(pt)
                prev = pt
        p.end()

