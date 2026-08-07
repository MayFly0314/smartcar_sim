"""变量监视面板：紧凑显示变量名与当前帧值，双击打开独立曲线窗口。

变量按可用宽度自动排成多列；标题条点击折叠。无数据时面板自动隐藏。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QScrollArea, QToolTip, QVBoxLayout, QWidget

from ..run.protocol import FrameResult

_BG = QColor("#1e1e1e")
_HEADER_BG = QColor("#2d2d2d")
_NAME = QColor("#9cdcfe")
_VALUE = QColor("#d4d4d4")
_MISSING = QColor("#808080")
_DIVIDER = QColor("#383838")
_HOVER_BG = QColor("#2a2d2e")

_HEADER_H = 20
_ROW_H = 24
_CELL_MIN_W = 150
_VALUE_W = 72
_MARGIN = 6
_MAX_VISIBLE_ROWS = 6


@dataclass
class WatchTrack:
    name: str
    values: list[float | None]
    vmin: float = 0.0
    vmax: float = 0.0


@dataclass
class WatchData:
    tracks: list[WatchTrack] = field(default_factory=list)
    frame_count: int = 0

    @property
    def empty(self) -> bool:
        return not self.tracks


def _finite(v: float | None) -> bool:
    return v is not None and math.isfinite(v)


def aggregate_watches(frames: list[FrameResult]) -> WatchData:
    """per-frame watches -> per-variable 跨帧序列。变量按首次出现顺序。"""
    n = len(frames)
    acc: dict[str, list[float | None]] = {}
    for i, fr in enumerate(frames):
        for name, val in fr.watches.items():
            col = acc.get(name)
            if col is None:
                col = [None] * n
                acc[name] = col
            col[i] = val

    tracks = []
    for name, col in acc.items():
        finite = [v for v in col if _finite(v)]
        t = WatchTrack(name, col)
        if finite:
            t.vmin, t.vmax = min(finite), max(finite)
        tracks.append(t)
    return WatchData(tracks, n)


def _fmt(v: float | None) -> str:
    if not _finite(v):
        return "—"
    return f"{v:g}"


def _grid_columns(width: int) -> int:
    """按可用宽度计算紧凑网格列数，窄窗口至少保留一列。"""
    return max(1, int(width) // _CELL_MIN_W)


class _WatchArea(QWidget):
    """紧凑变量网格：每格仅绘制变量名和当前帧值。"""

    var_activated = Signal(str)   # 双击变量项 -> 变量名
    layout_rows_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = WatchData()
        self._cur = 0
        self._hover = -1
        self._layout_rows = -1
        self.setMouseTracking(True)
        self._font = QFont("Consolas", 9)

    # ---- 数据 ----
    def set_data(self, data: WatchData) -> None:
        self._data = data
        self._cur = min(self._cur, max(0, data.frame_count - 1))
        self._hover = -1
        self._sync_layout_height()
        self.updateGeometry()
        self.update()

    def set_current_frame(self, idx: int) -> None:
        self._cur = max(0, min(idx, self._data.frame_count - 1))
        self.update()

    def sizeHint(self):  # noqa: N802
        return QSize(_CELL_MIN_W * 3, self._row_count() * _ROW_H)

    # ---- 几何 ----
    def _column_count(self) -> int:
        return _grid_columns(max(1, self.width()))

    def _row_count(self) -> int:
        n = len(self._data.tracks)
        cols = self._column_count()
        return (n + cols - 1) // cols

    def _sync_layout_height(self) -> None:
        rows = self._row_count()
        height = rows * _ROW_H
        if self.minimumHeight() != height:
            self.setMinimumHeight(height)
        if rows != self._layout_rows:
            self._layout_rows = rows
            self.layout_rows_changed.emit(rows)

    def _cell_rect(self, idx: int) -> QRectF:
        cols = self._column_count()
        cell_w = self.width() / cols
        row, col = divmod(idx, cols)
        return QRectF(col * cell_w, row * _ROW_H, cell_w, _ROW_H)

    def _index_at(self, pos) -> int:
        if pos.x() < 0 or pos.y() < 0 or pos.x() >= self.width():
            return -1
        cols = self._column_count()
        cell_w = self.width() / cols
        col = min(cols - 1, int(pos.x() // cell_w))
        row = int(pos.y() // _ROW_H)
        idx = row * cols + col
        return idx if 0 <= idx < len(self._data.tracks) else -1

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        self._sync_layout_height()

    # ---- 绘制 ----
    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), _BG)
        p.setFont(self._font)
        data = self._data

        metrics = QFontMetrics(self._font)
        for idx, t in enumerate(data.tracks):
            r = self._cell_rect(idx)
            if idx == self._hover:
                p.fillRect(r, _HOVER_BG)

            value_rect = QRectF(r.right() - _VALUE_W, r.top(), _VALUE_W - _MARGIN, r.height())
            name_rect = QRectF(
                r.left() + _MARGIN,
                r.top(),
                max(0.0, r.width() - _VALUE_W - 2 * _MARGIN),
                r.height(),
            )
            name = metrics.elidedText(
                t.name,
                Qt.TextElideMode.ElideRight,
                max(0, int(name_rect.width())),
            )
            p.setPen(_NAME)
            p.drawText(name_rect,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       name)
            cur_v = t.values[self._cur] if self._cur < len(t.values) else None
            p.setPen(_VALUE if _finite(cur_v) else _MISSING)
            p.drawText(value_rect,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       _fmt(cur_v))

            p.setPen(QPen(_DIVIDER))
            p.drawLine(r.bottomLeft(), r.bottomRight())
            if idx % self._column_count() != self._column_count() - 1:
                p.drawLine(r.topRight(), r.bottomRight())
        p.end()

    # ---- 交互 ----
    def mouseDoubleClickEvent(self, ev) -> None:  # noqa: N802
        """双击变量项，单独打开该变量的曲线窗口。"""
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        idx = self._index_at(ev.position())
        if idx >= 0:
            self.var_activated.emit(self._data.tracks[idx].name)

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        idx = self._index_at(ev.position())
        if idx != self._hover:
            self._hover = idx
            self.update()
        if idx >= 0:
            t = self._data.tracks[idx]
            v = t.values[self._cur] if self._cur < len(t.values) else None
            QToolTip.showText(
                ev.globalPosition().toPoint(),
                f"{t.name} = {_fmt(v)}",
                self,
            )
        else:
            QToolTip.hideText()

    def leaveEvent(self, ev) -> None:  # noqa: N802
        self._hover = -1
        QToolTip.hideText()
        self.update()
        super().leaveEvent(ev)


class _Header(QWidget):
    """可点击标题条：标题(+可选计数) + 折叠三角。"""

    toggled = Signal()

    def __init__(self, title: str = "监视", parent=None):
        super().__init__(parent)
        self.collapsed = False
        self._title = title
        self._count: int | None = None
        self.setFixedHeight(_HEADER_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._font = QFont("Consolas", 9)

    def set_count(self, n: int | None) -> None:
        self._count = n
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), _HEADER_BG)
        p.setFont(self._font)
        p.setPen(_VALUE)
        arrow = "▸" if self.collapsed else "▾"
        suffix = f" ({self._count})" if self._count is not None else ""
        p.drawText(self.rect().adjusted(_MARGIN, 0, -_MARGIN, 0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   f"{arrow} {self._title}{suffix}")
        p.end()

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self.collapsed = not self.collapsed
            self.update()
            self.toggled.emit()


class WatchPanel(QWidget):
    var_activated = Signal(str, object)   # 双击 -> (变量名, 跨帧值列表)

    def __init__(self, parent=None, title: str = "监视"):
        super().__init__(parent)
        self._header = _Header(title)
        self._area = _WatchArea()
        self._scroll = QScrollArea()
        self._scroll.setWidget(self._area)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background:#1e1e1e; }")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._header)
        lay.addWidget(self._scroll)

        self._header.toggled.connect(self._on_toggle)
        self._area.var_activated.connect(self._on_var_activated)
        self._area.layout_rows_changed.connect(self._update_scroll_height)
        self.setVisible(False)

    def _on_var_activated(self, name: str) -> None:
        for t in self._area._data.tracks:
            if t.name == name:
                self.var_activated.emit(name, list(t.values))
                return

    def values_of(self, name: str) -> list | None:
        """取某变量的跨帧序列（曲线窗口刷新用）。"""
        for t in self._area._data.tracks:
            if t.name == name:
                return list(t.values)
        return None

    # ---- 对外 API ----
    def set_run(self, frames: list[FrameResult]) -> None:
        data = aggregate_watches(frames)
        if data.empty:
            self.clear()
            return
        self._area.set_data(data)
        self._header.set_count(len(data.tracks))
        self._update_scroll_height(self._area._row_count())
        self.setVisible(True)
        self._scroll.setVisible(not self._header.collapsed)

    def set_current_frame(self, idx: int) -> None:
        self._area.set_current_frame(idx)  # 纯游标更新，不回发信号（断环点）

    def clear(self) -> None:
        self._area.set_data(WatchData())
        self._header.set_count(None)
        self.setVisible(False)

    def _update_scroll_height(self, rows: int) -> None:
        visible_rows = min(max(0, rows), _MAX_VISIBLE_ROWS)
        self._scroll.setFixedHeight(visible_rows * _ROW_H)

    def _on_toggle(self) -> None:
        self._scroll.setVisible(not self._header.collapsed)
