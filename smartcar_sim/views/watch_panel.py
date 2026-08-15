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
_GROUP = QColor("#4ec9b0")

_HEADER_H = 24
_ROW_H = 28
_CELL_MIN_W = 150
_VALUE_W = 72
_MARGIN = 6
_MAX_VISIBLE_ROWS = 6
MAX_WATCHES = 50


@dataclass
class WatchTrack:
    name: str
    values: list[float | None]
    vmin: float = 0.0
    vmax: float = 0.0
    group: str = ""


@dataclass
class WatchData:
    tracks: list[WatchTrack] = field(default_factory=list)
    frame_count: int = 0

    @property
    def empty(self) -> bool:
        return not self.tracks


def _finite(v: float | None) -> bool:
    return v is not None and math.isfinite(v)


def aggregate_watches(
    frames: list[FrameResult],
    limit: int = MAX_WATCHES,
    groups: dict[str, str] | None = None,
) -> WatchData:
    """per-frame watches -> per-variable 跨帧序列，最多保留前 ``limit`` 项。

    groups: 变量名 -> 组名。给了就按组分块显示；不给则退化成原来的紧凑网格。
    """
    n = len(frames)
    acc: dict[str, list[float | None]] = {}
    for i, fr in enumerate(frames):
        for name, val in fr.watches.items():
            if name not in acc and len(acc) >= limit:
                continue
            col = acc.get(name)
            if col is None:
                col = [None] * n
                acc[name] = col
            col[i] = val

    tracks = []
    for name, col in acc.items():
        finite = [v for v in col if _finite(v)]
        t = WatchTrack(name, col, group=(groups or {}).get(name, ""))
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

    def __init__(
        self,
        parent=None,
        *,
        row_height: int = _ROW_H,
        cell_min_width: int = _CELL_MIN_W,
        font_size: int = 9,
    ):
        super().__init__(parent)
        self._data = WatchData()
        self._cur = 0
        self._hover = -1
        self._layout_rows = -1
        self._headers: list[tuple[int, str]] = []   # [(行号, 组名)]
        self.setMouseTracking(True)
        self._row_height = max(18, int(row_height))
        self._cell_min_width = max(80, int(cell_min_width))
        self._font = QFont("Microsoft YaHei UI", max(8, int(font_size)))
        self._font.setBold(True)
        self._name_color = QColor(_NAME)
        self._value_color = QColor(_VALUE)

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
        return QSize(self._cell_min_width * 3, self._row_count() * self._row_height)

    # ---- 几何 ----
    def _column_count(self) -> int:
        return max(1, int(max(1, self.width()) // self._cell_min_width))

    def _layout(self) -> tuple[list[tuple[int, int, int]], int]:
        """算出每个变量的 (行, 列, 组标题行标记)，返回 (格子位置, 总行数)。

        没有任何分组时退化成原来的纯网格（组标题不占行），行为完全不变。
        """
        cols = self._column_count()
        tracks = self._data.tracks
        groups = [t.group or "" for t in tracks]
        if not any(groups):
            slots = [(i // cols, i % cols, -1) for i in range(len(tracks))]
            return slots, (len(tracks) + cols - 1) // cols

        slots: list[tuple[int, int, int]] = []
        self._headers = []           # [(行号, 组名)]
        row = 0
        i = 0
        while i < len(tracks):
            g = groups[i]
            j = i
            while j < len(tracks) and groups[j] == g:
                j += 1
            if g:
                self._headers.append((row, g))
                row += 1
            for k in range(i, j):
                off = k - i
                slots.append((row + off // cols, off % cols, -1))
            row += (j - i + cols - 1) // cols
            i = j
        return slots, row

    def _row_count(self) -> int:
        return self._layout()[1]

    def _sync_layout_height(self) -> None:
        rows = self._row_count()
        height = rows * self._row_height
        if self.minimumHeight() != height:
            self.setMinimumHeight(height)
        if rows != self._layout_rows:
            self._layout_rows = rows
            self.layout_rows_changed.emit(rows)

    def _cell_rect(self, idx: int) -> QRectF:
        slots, _rows = self._layout()
        if idx < 0 or idx >= len(slots):
            return QRectF()
        cols = self._column_count()
        cell_w = self.width() / cols
        row, col, _ = slots[idx]
        return QRectF(col * cell_w, row * self._row_height, cell_w, self._row_height)

    def _index_at(self, pos) -> int:
        if pos.x() < 0 or pos.y() < 0 or pos.x() >= self.width():
            return -1
        slots, _rows = self._layout()
        cols = self._column_count()
        cell_w = self.width() / cols
        col = min(cols - 1, int(pos.x() // cell_w))
        row = int(pos.y() // self._row_height)
        for i, (r, c, _) in enumerate(slots):
            if r == row and c == col:
                return i
        return -1

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        self._sync_layout_height()

    def set_appearance(
        self,
        *,
        name_color: QColor | str | None = None,
        value_color: QColor | str | None = None,
        font_size: int | None = None,
        bold: bool | None = None,
    ) -> None:
        if name_color is not None:
            self._name_color = QColor(name_color)
        if value_color is not None:
            self._value_color = QColor(value_color)
        if font_size is not None:
            self._font.setPointSize(max(8, int(font_size)))
        if bold is not None:
            self._font.setBold(bool(bold))
        self._sync_layout_height()
        self.updateGeometry()
        self.update()

    # ---- 绘制 ----
    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), _BG)
        p.setFont(self._font)
        data = self._data

        # 组标题（_layout 里填好的）——先画，变量格覆在其下方各行
        self._layout()
        if self._headers:
            gf = QFont(self._font)
            gf.setBold(True)
            p.setFont(gf)
            for row, name in self._headers:
                r = QRectF(0, row * self._row_height, self.width(), self._row_height)
                p.fillRect(r, _HEADER_BG)
                p.setPen(QPen(_GROUP))
                p.drawText(
                    r.adjusted(_MARGIN, 0, -_MARGIN, 0),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    name,
                )
            p.setFont(self._font)

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
            p.setPen(self._name_color)
            p.drawText(name_rect,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       name)
            cur_v = t.values[self._cur] if self._cur < len(t.values) else None
            p.setPen(self._value_color if _finite(cur_v) else _MISSING)
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
        self._font = QFont("Microsoft YaHei UI", 9)
        self._font.setBold(True)

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

    def __init__(
        self,
        parent=None,
        title: str = "监视",
        *,
        max_tracks: int = MAX_WATCHES,
        row_height: int = _ROW_H,
        cell_min_width: int = _CELL_MIN_W,
        font_size: int = 9,
        max_visible_rows: int = _MAX_VISIBLE_ROWS,
    ):
        super().__init__(parent)
        self._max_tracks = max(1, min(MAX_WATCHES, int(max_tracks)))
        self._row_height = max(18, int(row_height))
        self._max_visible_rows = max(1, int(max_visible_rows))
        self._header = _Header(title)
        self._area = _WatchArea(
            row_height=self._row_height,
            cell_min_width=cell_min_width,
            font_size=font_size,
        )
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

    def has_data(self) -> bool:
        return not self._area._data.empty

    # ---- 对外 API ----
    def set_run(self, frames: list[FrameResult],
                groups: dict[str, str] | None = None) -> None:
        data = aggregate_watches(frames, self._max_tracks, groups)
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

    def set_appearance(
        self,
        *,
        name_color: QColor | str | None = None,
        value_color: QColor | str | None = None,
        font_size: int | None = None,
        bold: bool | None = None,
    ) -> None:
        """调整参数名称/数值颜色和字号，中文名称使用系统中文字体绘制。"""
        self._area.set_appearance(
            name_color=name_color,
            value_color=value_color,
            font_size=font_size,
            bold=bold,
        )
        if font_size is not None:
            self._header._font.setPointSize(max(8, int(font_size)))
            self._header.update()

    def _update_scroll_height(self, rows: int) -> None:
        visible_rows = min(max(0, rows), self._max_visible_rows)
        self._scroll.setFixedHeight(visible_rows * self._row_height)

    def _on_toggle(self) -> None:
        self._scroll.setVisible(not self._header.collapsed)
