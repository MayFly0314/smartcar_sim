"""变量监视面板：sim_plot 记录的数值 -> 每变量一行（名 | 当前帧值 | 跨帧 sparkline）。

点击/拖动 sparkline 跳帧；悬停显示 (帧号, 值)；标题条点击折叠。
无任何 sim_plot 数据时面板自动隐藏。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QScrollArea, QToolTip, QVBoxLayout, QWidget

from ..run.protocol import FrameResult

_BG = QColor("#1e1e1e")
_HEADER_BG = QColor("#2d2d2d")
_NAME = QColor("#9cdcfe")
_VALUE = QColor("#d4d4d4")
_CURVE = QColor("#4ec9b0")
_CURSOR = QColor("#569cd6")
_MISSING = QColor("#808080")

_HEADER_H = 20
_ROW_H = 22
_NAME_W = 96
_VALUE_W = 68
_PAD = 3          # sparkline 上下留白
_MARGIN = 6       # 行区左右边距
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


class _WatchArea(QWidget):
    """行区：一次 paintEvent 画所有行；命中测试纯算术。"""

    frame_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = WatchData()
        self._cur = 0
        self.setMouseTracking(True)
        self._font = QFont("Consolas", 9)

    # ---- 数据 ----
    def set_data(self, data: WatchData) -> None:
        self._data = data
        self._cur = min(self._cur, max(0, data.frame_count - 1))
        self.updateGeometry()
        self.update()

    def set_current_frame(self, idx: int) -> None:
        self._cur = max(0, min(idx, self._data.frame_count - 1))
        self.update()

    def sizeHint(self):  # noqa: N802
        from PySide6.QtCore import QSize
        return QSize(200, _ROW_H * len(self._data.tracks))

    # ---- 几何 ----
    def _spark_rect(self, row: int) -> QRectF:
        sx = _MARGIN + _NAME_W + _VALUE_W
        return QRectF(sx, row * _ROW_H, max(10, self.width() - sx - _MARGIN), _ROW_H)

    def _x_at(self, i: int, r: QRectF) -> float:
        n = self._data.frame_count
        if n <= 1:
            return r.center().x()
        return r.left() + i / (n - 1) * r.width()

    def _y_at(self, v: float, t: WatchTrack, r: QRectF) -> float:
        span = t.vmax - t.vmin
        frac = (v - t.vmin) / span if span > 1e-9 else 0.5
        return r.top() + _PAD + (1.0 - frac) * (r.height() - 2 * _PAD)

    def _frame_at_x(self, x: float, r: QRectF) -> int:
        n = self._data.frame_count
        if n <= 1 or r.width() <= 0:
            return 0
        i = round((x - r.left()) / r.width() * (n - 1))
        return max(0, min(int(i), n - 1))

    def _row_at_y(self, y: float) -> int:
        row = int(y // _ROW_H)
        return row if 0 <= row < len(self._data.tracks) else -1

    # ---- 绘制 ----
    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), _BG)
        p.setFont(self._font)
        data = self._data

        for row, t in enumerate(data.tracks):
            y0 = row * _ROW_H
            r = self._spark_rect(row)

            p.setPen(_NAME)
            p.drawText(QRectF(_MARGIN, y0, _NAME_W - 4, _ROW_H),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       t.name)
            cur_v = t.values[self._cur] if self._cur < len(t.values) else None
            p.setPen(_VALUE if _finite(cur_v) else _MISSING)
            p.drawText(QRectF(_MARGIN + _NAME_W, y0, _VALUE_W - 8, _ROW_H),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       _fmt(cur_v))

            # 曲线（缺失点断段）
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            pen = QPen(_CURVE)
            pen.setWidthF(1.2)
            p.setPen(pen)
            seg: list[QPointF] = []
            for i, v in enumerate(t.values):
                if _finite(v):
                    seg.append(QPointF(self._x_at(i, r), self._y_at(v, t, r)))
                else:
                    self._flush_segment(p, seg)
                    seg = []
            self._flush_segment(p, seg)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

            # 当前帧游标
            cx = self._x_at(self._cur, r)
            p.setPen(QPen(_CURSOR))
            p.drawLine(QPointF(cx, r.top()), QPointF(cx, r.bottom()))
            if _finite(cur_v):
                p.setBrush(_CURSOR)
                p.drawEllipse(QPointF(cx, self._y_at(cur_v, t, r)), 2.0, 2.0)
                p.setBrush(Qt.BrushStyle.NoBrush)
        p.end()

    @staticmethod
    def _flush_segment(p: QPainter, seg: list[QPointF]) -> None:
        if len(seg) >= 2:
            p.drawPolyline(seg)
        elif len(seg) == 1:
            p.drawEllipse(seg[0], 1.5, 1.5)

    # ---- 交互 ----
    def _seek(self, pos) -> None:
        row = self._row_at_y(pos.y())
        if row < 0:
            return
        r = self._spark_rect(row)
        if r.left() <= pos.x() <= r.right():
            self.frame_selected.emit(self._frame_at_x(pos.x(), r))

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self._seek(ev.position())

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if ev.buttons() & Qt.MouseButton.LeftButton:
            self._seek(ev.position())
            return
        row = self._row_at_y(ev.position().y())
        if row >= 0:
            r = self._spark_rect(row)
            if r.left() <= ev.position().x() <= r.right():
                t = self._data.tracks[row]
                i = self._frame_at_x(ev.position().x(), r)
                v = t.values[i] if i < len(t.values) else None
                txt = f"帧 {i}｜{t.name} = {_fmt(v)}" if _finite(v) else f"帧 {i}｜{t.name}：无值"
                QToolTip.showText(ev.globalPosition().toPoint(), txt, self)
                return
        QToolTip.hideText()


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
    frame_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._header = _Header()
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
        self._area.frame_selected.connect(self.frame_selected)
        self.setVisible(False)

    # ---- 对外 API ----
    def set_run(self, frames: list[FrameResult]) -> None:
        data = aggregate_watches(frames)
        if data.empty:
            self.clear()
            return
        self._area.set_data(data)
        rows = min(len(data.tracks), _MAX_VISIBLE_ROWS)
        self._scroll.setFixedHeight(rows * _ROW_H)
        self.setVisible(True)
        self._scroll.setVisible(not self._header.collapsed)

    def set_current_frame(self, idx: int) -> None:
        self._area.set_current_frame(idx)  # 纯游标更新，不回发信号（断环点）

    def clear(self) -> None:
        self._area.set_data(WatchData())
        self.setVisible(False)

    def _on_toggle(self) -> None:
        self._scroll.setVisible(not self._header.collapsed)
