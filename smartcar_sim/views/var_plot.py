"""多变量曲线窗口：叠加显示若干变量，随时勾选/取消某条线。

调 PI 速度环时，目标速度和当前转速必须画在同一张图上才看得出超调、振荡和稳态误差；
再叠一条 PWM 就能看出是不是饱和了。

两条设计原则：
- **不做双 Y 轴。** 两个量纲不同的量放在两根 Y 轴上，交点位置随量程漂移，
  看起来的"相位关系"是假的。同单位的量（目标速度/当前转速）共用一根轴直接比；
  量纲不同的量用「各自归一化」看形状——此时 Y 轴不再是绝对值，界面上会写明。
- **颜色跟着变量走，不跟着序号走。** 取消勾选某条线时，其余线颜色不变，
  否则每点一下所有线都换色，没法读。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ..settings import Settings

_BG = QColor("#1e1e1e")
_GRID = QColor(255, 255, 255, 28)
_CURSOR = QColor("#569cd6")
_TEXT = QColor("#d4d4d4")
_AXIS = QColor("#9cdcfe")
_OUT = QColor("#f48771")     # 超出上下限的点用红色贴边提示

# 分类配色：固定顺序，按变量名分配，不随可见条数变化。
# 已用 dataviz 校验器在本窗口的底色 #1e1e1e 上验过：
# 亮度带/彩度/色盲相邻分离/常视力分离/对比度 全部 PASS。
_PALETTE = [
    "#3987e5",  # 蓝
    "#d95926",  # 橙
    "#199e70",  # 青绿
    "#c98500",  # 黄
    "#d55181",  # 品红
    "#008300",  # 绿
    "#9085e9",  # 紫
    "#e66767",  # 红
]

_PAD_L = 62      # 左侧 Y 轴刻度区
_PAD_R = 10
_PAD_T = 10
_PAD_B = 20      # 底部帧号轴


def _finite(v) -> bool:
    return v is not None and math.isfinite(v)


def color_for(index: int) -> QColor:
    """按槽位取色。超过 8 条时循环——此时更该做的是少选几条。"""
    return QColor(_PALETTE[index % len(_PALETTE)])


@dataclass
class Series:
    name: str
    values: list[float | None] = field(default_factory=list)
    color: QColor = field(default_factory=lambda: QColor(_PALETTE[0]))
    visible: bool = True

    def finite(self) -> list[float]:
        return [v for v in self.values if _finite(v)]


class _Curve(QWidget):
    """多序列曲线区：共享 Y 量程或各自归一化，游标 + 悬停读数。

    滚轮=横向缩放（锚定鼠标下的帧），Ctrl+滚轮=纵向缩放，
    Shift+滚轮=横向平移，右键拖拽=任意方向平移。
    纵向量程归工具条管，这里只发 y_range_requested 信号。
    """

    frame_selected = Signal(int)
    y_range_requested = Signal(float, float)   # Ctrl+滚轮/右键竖直拖拽请求的新量程 (lo, hi)
    x_view_changed = Signal()                  # 用户手动缩放/平移了横向视野（程序化设置不发）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._series: list[Series] = []
        self._cur = 0
        self._lo = 0.0
        self._hi = 1.0
        self._offset = 0.0     # 中值对称：按 (值 - offset) 显示（仅共享量程模式）
        self._norm = False     # 各自归一化
        self._x0 = 0.0         # 可见帧窗口（浮点，缩放才平滑）
        self._x1 = 0.0
        self._x_full = True    # True=铺满全部帧；此时数据增长自动跟随
        self._pan_last: QPointF | None = None   # 右键拖拽平移的上一个位置
        self.setMouseTracking(True)
        self.setMinimumHeight(220)
        self._font = QFont("Consolas", 9)

    # ---- 数据 ----
    def set_series(self, series: list[Series]) -> None:
        self._series = series
        self.update()

    def visible_series(self) -> list[Series]:
        return [s for s in self._series if s.visible and s.values]

    def frame_count(self) -> int:
        return max((len(s.values) for s in self._series), default=0)

    def set_normalized(self, on: bool) -> None:
        self._norm = bool(on)
        self.update()

    def set_offset(self, offset: float) -> None:
        self._offset = float(offset)
        self.update()

    def set_range(self, lo: float, hi: float) -> None:
        if hi - lo < 1e-12:
            hi = lo + 1e-6
        self._lo, self._hi = lo, hi
        self.update()

    def set_current_frame(self, idx: int) -> None:
        self._cur = max(0, min(idx, max(0, self.frame_count() - 1)))
        self.update()

    # ---- 几何 ----
    def _plot_rect(self) -> QRectF:
        return QRectF(
            _PAD_L, _PAD_T,
            max(10, self.width() - _PAD_L - _PAD_R),
            max(10, self.height() - _PAD_T - _PAD_B),
        )

    def _x_view(self) -> tuple[float, float]:
        """当前可见的帧窗口。数据刷新变短时夹回有效范围。"""
        n = self.frame_count()
        full = 0.0, float(max(0, n - 1))
        if self._x_full or n <= 1:
            return full
        x0 = max(0.0, min(self._x0, full[1]))
        x1 = max(x0, min(self._x1, full[1]))
        return (x0, x1) if x1 > x0 else full

    def _x_at(self, i: int, r: QRectF) -> float:
        x0, x1 = self._x_view()
        span = x1 - x0
        if span <= 0:
            return r.center().x()
        return r.left() + (i - x0) / span * r.width()

    def _bounds_of(self, s: Series) -> tuple[float, float]:
        """归一化模式下每条线自己的上下限。"""
        f = s.finite()
        if not f:
            return 0.0, 1.0
        lo, hi = min(f), max(f)
        if hi - lo < 1e-12:                 # 常量线画在中间，别贴边
            pad = max(abs(hi) * 0.05, 0.5)
            lo, hi = lo - pad, hi + pad
        return lo, hi

    def _y_at(self, v: float, r: QRectF, s: Series | None = None) -> float:
        if self._norm and s is not None:
            lo, hi = self._bounds_of(s)
            frac = (v - lo) / (hi - lo)
        else:
            frac = (v - self._offset - self._lo) / (self._hi - self._lo)
        frac = max(0.0, min(1.0, frac))      # 超限贴边
        return r.bottom() - frac * r.height()

    def _frame_at_x(self, x: float, r: QRectF) -> int:
        n = self.frame_count()
        x0, x1 = self._x_view()
        if n <= 1 or x1 - x0 <= 0 or r.width() <= 0:
            return 0
        f = x0 + (x - r.left()) / r.width() * (x1 - x0)
        return max(0, min(int(round(f)), n - 1))

    def _out_of_range(self, v: float, s: Series) -> bool:
        if self._norm:
            return False                     # 归一化后不存在超限
        dv = v - self._offset
        return dv < self._lo or dv > self._hi

    # ---- 绘制 ----
    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), _BG)
        p.setFont(self._font)
        r = self._plot_rect()

        # 网格 + Y 轴刻度（5 等分）
        p.setPen(QPen(_GRID))
        for k in range(6):
            y = r.top() + k / 5 * r.height()
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        p.setPen(_AXIS)
        for k in range(6):
            y = r.top() + k / 5 * r.height()
            if self._norm:
                txt = f"{100 - k * 20}%"
            else:
                txt = f"{self._hi - k / 5 * (self._hi - self._lo):g}"
            p.drawText(QRectF(2, y - 8, _PAD_L - 8, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       txt)

        n = self.frame_count()
        vis = self.visible_series()
        if n == 0 or not vis:
            p.setPen(_TEXT)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter,
                       "没有勾选任何变量" if n else "无数据")
            p.end()
            return

        # 帧号轴（可见范围的首/中/末）
        x0, x1 = self._x_view()
        i0, i1 = math.ceil(x0), math.floor(x1)
        p.setPen(_TEXT)
        for i in {i0, (i0 + i1) // 2, i1}:
            p.drawText(QRectF(self._x_at(i, r) - 24, r.bottom() + 2, 48, 16),
                       Qt.AlignmentFlag.AlignCenter, str(i))

        # 各条曲线（缺失点断段；共享量程下超限点标红）
        # 只画可见范围（两侧各多取一点，保住进出边界线段的斜率），并裁剪到绘图区
        p.save()
        p.setClipRect(r)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for s in vis:
            pen = QPen(s.color)
            pen.setWidthF(2.0)
            p.setPen(pen)
            seg: list[QPointF] = []
            out_pts: list[QPointF] = []
            for i in range(max(0, i0 - 1), min(len(s.values), i1 + 2)):
                v = s.values[i]
                if _finite(v):
                    pt = QPointF(self._x_at(i, r), self._y_at(v, r, s))
                    seg.append(pt)
                    if self._out_of_range(v, s):
                        out_pts.append(pt)
                else:
                    if len(seg) >= 2:
                        p.drawPolyline(seg)
                    elif len(seg) == 1:
                        p.drawEllipse(seg[0], 1.8, 1.8)
                    seg = []
            if len(seg) >= 2:
                p.drawPolyline(seg)
            elif len(seg) == 1:
                p.drawEllipse(seg[0], 1.8, 1.8)
            if out_pts:
                p.setPen(QPen(_OUT))
                p.setBrush(_OUT)
                for pt in out_pts:
                    p.drawEllipse(pt, 1.8, 1.8)
                p.setBrush(Qt.BrushStyle.NoBrush)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # 当前帧游标 + 每条线的读数
        cx = self._x_at(self._cur, r)
        p.setPen(QPen(_CURSOR))
        p.drawLine(QPointF(cx, r.top()), QPointF(cx, r.bottom()))
        y = r.top() + 2
        for s in vis:
            cv = s.values[self._cur] if self._cur < len(s.values) else None
            if not _finite(cv):
                continue
            p.setBrush(s.color)
            p.setPen(QPen(s.color))
            p.drawEllipse(QPointF(cx, self._y_at(cv, r, s)), 3.0, 3.0)
            p.setBrush(Qt.BrushStyle.NoBrush)
            # 色块表身份，文字用中性色（数字才是要读的东西）
            p.fillRect(QRectF(r.left() + 4, y + 4, 8, 8), s.color)
            p.setPen(_TEXT)
            p.drawText(QRectF(r.left() + 16, y, r.width() - 20, 16),
                       Qt.AlignmentFlag.AlignLeft, f"{s.name} = {cv:g}")
            y += 15
        p.setPen(_TEXT)
        tag = f"帧 {self._cur}"
        if i1 - i0 < n - 1:
            tag = f"视野 {i0}–{i1}  ·  {tag}"
        p.drawText(QRectF(r.left() + 4, r.bottom() - 16, r.width() - 8, 16),
                   Qt.AlignmentFlag.AlignRight, tag)
        p.restore()
        p.end()

    # ---- 交互 ----
    def _seek(self, pos) -> None:
        r = self._plot_rect()
        if r.left() <= pos.x() <= r.right():
            self.frame_selected.emit(self._frame_at_x(pos.x(), r))

    def x_view(self) -> tuple[float, float]:
        """当前可见帧窗口（公开只读，实时面板做可见区适配用）。"""
        return self._x_view()

    def show_last(self, count: int) -> None:
        """滚动跟随：视野定到最近 count 个点（实时波形用，不触发 x_view_changed）。"""
        n = self.frame_count()
        if n <= 1 or count >= n - 1:
            self._x_full = True
        else:
            self._x0, self._x1 = float(n - 1 - count), float(n - 1)
            self._x_full = False
        self.update()

    def reset_x_view(self) -> None:
        self._x_full = True
        self.update()

    def _zoom_x(self, anchor: float, factor: float) -> None:
        """围绕 anchor（帧坐标）缩放可见窗口；缩回全程时复位为跟随模式。"""
        n = self.frame_count()
        if n <= 1:
            return
        full = float(n - 1)
        x0, x1 = self._x_view()
        span = min(max((x1 - x0) * factor, min(10.0, full)), full)
        if span >= full:
            self.reset_x_view()
            self.x_view_changed.emit()
            return
        ratio = (anchor - x0) / (x1 - x0)    # 锚点在窗口内的相对位置保持不变
        nx0 = max(0.0, min(anchor - span * ratio, full - span))
        self._x0, self._x1 = nx0, nx0 + span
        self._x_full = False
        self.update()
        self.x_view_changed.emit()

    def _pan_x(self, dframes: float) -> None:
        n = self.frame_count()
        x0, x1 = self._x_view()
        span = x1 - x0
        if n <= 1 or span >= n - 1:
            return
        nx0 = max(0.0, min(x0 + dframes, (n - 1) - span))
        self._x0, self._x1 = nx0, nx0 + span
        self._x_full = False
        self.update()
        self.x_view_changed.emit()

    def _pan_y(self, dpx: float) -> None:
        """按像素位移竖直平移。量程归工具条管，这里只发信号。"""
        r = self._plot_rect()
        if self._norm or r.height() <= 0 or dpx == 0:
            return
        dv = dpx / r.height() * (self._hi - self._lo)
        self.y_range_requested.emit(self._lo + dv, self._hi + dv)

    def wheelEvent(self, ev) -> None:  # noqa: N802
        r = self._plot_rect()
        pos = ev.position()
        d = ev.angleDelta()
        steps = (d.y() if d.y() else d.x()) / 120.0
        if steps == 0 or not r.contains(pos):
            ev.ignore()
            return
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self._norm:                   # 各自归一化时不存在共享量程
                ev.ignore()
                return
            factor = 0.8 ** steps            # 上滚 = 放大（量程变小）
            va = self._lo + (r.bottom() - pos.y()) / r.height() * (self._hi - self._lo)
            lo = va - (va - self._lo) * factor
            hi = va + (self._hi - va) * factor
            if hi - lo > 1e-12:
                self.y_range_requested.emit(lo, hi)
        elif ev.modifiers() & Qt.KeyboardModifier.ShiftModifier or not d.y():
            x0, x1 = self._x_view()
            self._pan_x(-steps * (x1 - x0) * 0.15)
        else:
            x0, x1 = self._x_view()
            anchor = x0 + (pos.x() - r.left()) / r.width() * (x1 - x0)
            self._zoom_x(anchor, 0.8 ** steps)
        ev.accept()

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self._seek(ev.position())
        elif ev.button() == Qt.MouseButton.RightButton:
            self._pan_last = ev.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.RightButton:
            self._pan_last = None
            self.unsetCursor()

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if ev.buttons() & Qt.MouseButton.RightButton and self._pan_last is not None:
            r = self._plot_rect()
            pos = ev.position()
            if r.width() > 0:
                x0, x1 = self._x_view()
                dx = self._pan_last.x() - pos.x()
                self._pan_x(dx / r.width() * (x1 - x0))
            self._pan_y(pos.y() - self._pan_last.y())   # 下拖=看更高的值段，跟手
            self._pan_last = pos
            return
        if ev.buttons() & Qt.MouseButton.LeftButton:
            self._seek(ev.position())
            return
        r = self._plot_rect()
        vis = self.visible_series()
        if r.left() <= ev.position().x() <= r.right() and vis:
            i = self._frame_at_x(ev.position().x(), r)
            rows = [f"帧 {i}"]
            for s in vis:
                v = s.values[i] if i < len(s.values) else None
                # 归一化只影响画法，读数永远给原始值
                rows.append(f"{s.name} = {v:g}" if _finite(v) else f"{s.name} = —")
            QToolTip.showText(ev.globalPosition().toPoint(), "\n".join(rows), self)
        else:
            QToolTip.hideText()


class _Swatch(QFrame):
    """图例色块，点一下 = 只看这一条。"""

    clicked = Signal()

    def __init__(self, color: QColor, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"background:{color.name()}; border:1px solid #555; border-radius:2px;")

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        self.clicked.emit()


class _LegendRow(QWidget):
    """图例兼开关：色块（点击=只看这条）+ 勾选框（勾掉=隐藏这条）。"""

    toggled = Signal(str, bool)
    solo = Signal(str)

    def __init__(self, name: str, color: QColor, checked: bool, parent=None):
        super().__init__(parent)
        self._name = name
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 1, 4, 1)
        lay.setSpacing(6)
        swatch = _Swatch(color)
        swatch.setToolTip(f"只看「{name}」这一条（其余全部隐藏）")
        swatch.clicked.connect(lambda: self.solo.emit(self._name))
        lay.addWidget(swatch)
        self._chk = QCheckBox(name)
        self._chk.setChecked(checked)
        self._chk.setToolTip("取消勾选即隐藏这条线；点左边色块只看这一条")
        self._chk.toggled.connect(lambda on: self.toggled.emit(self._name, on))
        lay.addWidget(self._chk, 1)

    def set_checked(self, on: bool) -> None:
        self._chk.blockSignals(True)
        self._chk.setChecked(on)
        self._chk.blockSignals(False)


class _AddVarsDialog(QDialog):
    """一次勾选多个变量叠加进图。"""

    def __init__(self, names: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("叠加变量")
        self._list = QListWidget()
        for n in names:
            it = QListWidgetItem(n)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            self._list.addItem(it)
        b_all = QPushButton("全选")
        b_none = QPushButton("清空")
        b_all.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
        b_none.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(b_all)
        row.addWidget(b_none)
        row.addStretch(1)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("勾选要叠加到图上的变量："))
        lay.addWidget(self._list, 1)
        lay.addLayout(row)
        lay.addWidget(bb)
        self.resize(260, 360)

    def _set_all(self, state: Qt.CheckState) -> None:
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(state)

    def checked_names(self) -> list[str]:
        return [self._list.item(i).text()
                for i in range(self._list.count())
                if self._list.item(i).checkState() == Qt.CheckState.Checked]


class VarPlotDialog(QDialog):
    """多变量曲线窗口（非模态，可同时开多个）。"""

    frame_selected = Signal(int)

    def __init__(self, name: str, values: list[float | None], parent=None,
                 provider=None):
        """provider: 可选，callable() -> dict[变量名, 值序列]，用来提供"可叠加的其他变量"。"""
        super().__init__(parent)
        self.setWindowTitle(f"变量曲线 — {name}")
        self._settings = Settings()
        self.resize(self._settings.var_plot_w, self._settings.var_plot_h)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self._name = name
        self._provider = provider
        self._series: list[Series] = []
        self._slot: dict[str, int] = {}      # 变量名 -> 配色槽位（固定，不随勾选变化）
        self._rows: dict[str, _LegendRow] = {}

        self._curve = _Curve()
        self._curve.frame_selected.connect(self.frame_selected)

        # ---- 顶部工具条 ----
        self._spin_lo = QDoubleSpinBox()
        self._spin_hi = QDoubleSpinBox()
        for s in (self._spin_lo, self._spin_hi):
            s.setDecimals(4)
            s.setRange(-1e9, 1e9)
            s.setSingleStep(1.0)
            s.setKeyboardTracking(False)
        self._btn_apply = QPushButton("确定")
        self._btn_apply.setToolTip("应用上面填的上下限（也可在输入框里按回车）")
        self._chk_auto = QCheckBox("自动量程")
        self._chk_auto.setChecked(True)
        btn_fit = QPushButton("按当前数据适配")
        btn_fit.setToolTip("上下限设为所有可见曲线的 min/max")

        self._spin_mid = QDoubleSpinBox()
        self._spin_mid.setDecimals(4)
        self._spin_mid.setRange(-1e9, 1e9)
        self._spin_mid.setSingleStep(10.0)
        self._spin_mid.setKeyboardTracking(False)
        self._btn_sym = QPushButton("中值对称")
        self._btn_sym.setToolTip(
            "以中值为 0 点对称显示偏差：\n"
            "如舵机 PWM 1300~1700、中值填 1500，则显示 -200~+200，更直观"
        )
        btn_mid_auto = QPushButton("取中")
        btn_mid_auto.setFixedWidth(46)
        btn_mid_auto.setToolTip("中值设为 (min+max)/2")

        self._chk_norm = QCheckBox("各自归一化")
        self._chk_norm.setToolTip(
            "量纲不同的量（转速 vs PWM）叠在一起时，把每条线各自缩放到 0~100% 看形状。\n"
            "注意：此时 Y 轴不再是绝对值，读数（悬停/游标）仍显示原始值。\n"
            "同单位的量（目标速度/当前转速）不要开，直接共用一根轴比更准。"
        )

        bar = QHBoxLayout()
        bar.addWidget(self._chk_auto)
        bar.addSpacing(6)
        bar.addWidget(QLabel("下限"))
        bar.addWidget(self._spin_lo)
        bar.addWidget(QLabel("上限"))
        bar.addWidget(self._spin_hi)
        bar.addWidget(self._btn_apply)
        bar.addWidget(btn_fit)
        bar.addSpacing(10)
        bar.addWidget(QLabel("中值"))
        bar.addWidget(self._spin_mid)
        bar.addWidget(btn_mid_auto)
        bar.addWidget(self._btn_sym)
        bar.addSpacing(10)
        bar.addWidget(self._chk_norm)
        bar.addSpacing(10)
        btn_reset = QPushButton("复位缩放")
        btn_reset.setToolTip(
            "滚轮：横向缩放（以鼠标位置为锚点）\n"
            "Ctrl+滚轮：纵向缩放\n"
            "Shift+滚轮：左右平移\n"
            "右键拖拽：任意方向平移\n"
            "点此按钮：恢复完整视野并重新自动量程"
        )
        bar.addWidget(btn_reset)
        bar.addStretch(1)
        self._lbl_stat = QLabel("")
        self._lbl_stat.setStyleSheet("color:#9cdcfe; font-family:Consolas;")
        bar.addWidget(self._lbl_stat)
        top = QWidget()
        top.setLayout(bar)

        # ---- 右侧：变量选择（图例 + 开关）----
        side = QVBoxLayout()
        side.setSpacing(4)
        self._btn_add = QPushButton("+ 叠加变量…")
        self._btn_add.setToolTip("一次勾选多个变量，叠加到同一张图上")
        self._btn_add.clicked.connect(self._open_add_dialog)
        side.addWidget(self._btn_add)

        row_sel = QHBoxLayout()
        b_all = QPushButton("全选")
        b_none = QPushButton("全不选")
        b_del = QPushButton("移除未勾选")
        b_del.setToolTip("把没勾选的变量从本图里删掉")
        b_all.clicked.connect(lambda: self._set_all(True))
        b_none.clicked.connect(lambda: self._set_all(False))
        b_del.clicked.connect(self._drop_unchecked)
        for b in (b_all, b_none, b_del):
            b.setMaximumWidth(90)
            row_sel.addWidget(b)
        side.addLayout(row_sel)

        self._rows_box = QVBoxLayout()
        self._rows_box.setSpacing(0)
        self._rows_box.addStretch(1)
        holder = QWidget()
        holder.setLayout(self._rows_box)
        scroll = QScrollArea()
        scroll.setWidget(holder)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(210)
        scroll.setMaximumWidth(260)
        scroll.setStyleSheet("QScrollArea { background:#252526; border:1px solid #333; }")
        side.addWidget(scroll, 1)

        body = QHBoxLayout()
        body.addWidget(self._curve, 1)
        side_w = QWidget()
        side_w.setLayout(side)
        body.addWidget(side_w)

        lay = QVBoxLayout(self)
        lay.addWidget(top)
        lay.addLayout(body, 1)

        self._chk_auto.toggled.connect(self._on_auto)
        self._btn_apply.clicked.connect(self._on_manual)
        self._spin_lo.editingFinished.connect(self._on_manual)
        self._spin_hi.editingFinished.connect(self._on_manual)
        btn_fit.clicked.connect(self._fit)
        self._btn_sym.clicked.connect(self._symmetric)
        btn_mid_auto.clicked.connect(self._auto_mid)
        self._chk_norm.toggled.connect(self._on_norm)
        btn_reset.clicked.connect(self._reset_zoom)
        self._curve.y_range_requested.connect(self._on_y_range_requested)

        self._add_series(name, list(values))
        self._restore_overlays()
        self._refresh_add_btn()
        self._rebuild_rows()
        self._after_data_change()

    # ---- 序列管理 ----
    def _add_series(self, name: str, values: list[float | None]) -> None:
        if name not in self._slot:
            self._slot[name] = len(self._slot)      # 颜色跟变量绑定，之后不再变
        self._series.append(Series(name, list(values), color_for(self._slot[name])))

    def names(self) -> list[str]:
        return [s.name for s in self._series]

    def available_names(self) -> list[str]:
        """还能叠加的变量（provider 目录里去掉已在图上的）。"""
        if self._provider is None:
            return []
        try:
            catalog = self._provider() or {}
        except Exception:  # noqa: BLE001
            return []
        have = set(self.names())
        return [n for n in catalog if n not in have]

    def _refresh_add_btn(self) -> None:
        if self._provider is None:
            self._btn_add.setEnabled(False)
            self._btn_add.setText("（无其他变量）")
            return
        avail = self.available_names()
        self._btn_add.setEnabled(bool(avail))
        self._btn_add.setText("+ 叠加变量…" if avail else "（没有可叠加的变量了）")

    def _open_add_dialog(self) -> None:
        avail = self.available_names()
        if not avail:
            return
        dlg = _AddVarsDialog(avail, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.add_series_by_names(dlg.checked_names())

    def add_series_by_names(self, names: list[str]) -> None:
        """按名字批量叠加；目录里没有的、已在图上的跳过。"""
        if self._provider is None or not names:
            return
        try:
            catalog = self._provider() or {}
        except Exception:  # noqa: BLE001
            return
        have = set(self.names())
        added = False
        for n in names:
            if n in have or n not in catalog:
                continue
            self._add_series(n, list(catalog[n]))
            have.add(n)
            added = True
        if not added:
            return
        self._refresh_add_btn()
        self._rebuild_rows()
        self._after_data_change()
        self._save_overlays()

    # ---- 叠加选择记忆（换 SD 数据/重开窗口后不用重新一个个加）----
    def _save_overlays(self) -> None:
        try:
            data = json.loads(self._settings.var_plot_overlays or "{}")
        except ValueError:
            data = {}
        data[self._name] = [[s.name, s.visible] for s in self._series]
        self._settings.var_plot_overlays = json.dumps(data, ensure_ascii=False)

    def _restore_overlays(self) -> None:
        """按上次的选择把叠加变量加回来；当前数据里没有的跳过（不改动记忆本身）。"""
        if self._provider is None:
            return
        try:
            saved = json.loads(self._settings.var_plot_overlays or "{}").get(self._name)
        except ValueError:
            return
        if not saved:
            return
        try:
            catalog = self._provider() or {}
        except Exception:  # noqa: BLE001
            return
        vis: dict[str, bool] = {}
        for entry in saved:
            try:
                vis[str(entry[0])] = bool(entry[1])
            except (TypeError, IndexError):
                continue
        for n, on in vis.items():
            if n != self._name and n in catalog and n not in self._slot:
                self._add_series(n, list(catalog[n]))
        for s in self._series:
            if s.name != self._name and s.name in vis:   # 主变量刚点开必须可见
                s.visible = vis[s.name]

    def _rebuild_rows(self) -> None:
        while self._rows_box.count() > 1:            # 保留末尾 stretch
            it = self._rows_box.takeAt(0)
            w = it.widget()
            if w is not None:
                # takeAt 只把它从布局里摘掉，parent 还在、还会显示在原位；
                # 必须先断开 parent，否则 deleteLater 处理之前会残留一行幽灵图例
                w.setParent(None)
                w.deleteLater()
        self._rows.clear()
        for s in self._series:
            row = _LegendRow(s.name, s.color, s.visible)
            row.toggled.connect(self._on_row_toggled)
            row.solo.connect(self._on_solo)
            self._rows_box.insertWidget(self._rows_box.count() - 1, row)
            self._rows[s.name] = row

    def _on_row_toggled(self, name: str, on: bool) -> None:
        for s in self._series:
            if s.name == name:
                s.visible = on
        self._after_data_change()
        self._save_overlays()

    def _on_solo(self, name: str) -> None:
        for s in self._series:
            s.visible = (s.name == name)
        for n, row in self._rows.items():
            row.set_checked(n == name)
        self._after_data_change()
        self._save_overlays()

    def _set_all(self, on: bool) -> None:
        for s in self._series:
            s.visible = on
        for row in self._rows.values():
            row.set_checked(on)
        self._after_data_change()
        self._save_overlays()

    def _drop_unchecked(self) -> None:
        keep = [s for s in self._series if s.visible]
        if not keep:                                  # 别把图清空
            return
        self._series = keep
        self._refresh_add_btn()
        self._rebuild_rows()
        self._after_data_change()
        self._save_overlays()

    # ---- 数据 ----
    def set_values(self, values: list[float | None]) -> None:
        """刷新主变量（兼容旧调用）。"""
        self.set_all_values({self._name: list(values)})

    def set_all_values(self, catalog: dict[str, list]) -> None:
        """重跑/换数据后按名字刷新所有序列；取不到的保持原样。"""
        for s in self._series:
            vals = catalog.get(s.name)
            if vals is not None:
                s.values = list(vals)
        self._refresh_add_btn()
        self._after_data_change()

    def _after_data_change(self) -> None:
        self._curve.set_series(self._series)
        vis = [s for s in self._series if s.visible]
        if len(vis) == 1:
            f = vis[0].finite()
            self._lbl_stat.setText(
                f"min {min(f):g}  max {max(f):g}  n={len(vis[0].values)}"
                if f else "无有效数据")
        else:
            self._lbl_stat.setText(f"{len(vis)} 条曲线")
        if self._chk_auto.isChecked():
            self._fit(silent=True)

    def set_current_frame(self, idx: int) -> None:
        self._curve.set_current_frame(idx)

    # ---- 量程 ----
    def _all_finite(self) -> list[float]:
        out: list[float] = []
        for s in self._series:
            if s.visible:
                out.extend(s.finite())
        return out

    def _apply(self, lo: float, hi: float) -> None:
        if hi - lo < 1e-9:                       # 常量序列也要能看
            pad = max(abs(hi) * 0.05, 0.5)
            lo, hi = lo - pad, hi + pad
        self._curve.set_range(lo, hi)
        for s, v in ((self._spin_lo, lo), (self._spin_hi, hi)):
            s.blockSignals(True)
            s.setValue(v)
            s.blockSignals(False)

    def _fit(self, silent: bool = False) -> None:
        finite = self._all_finite()
        if not finite:
            self._apply(0.0, 1.0)
            return
        lo, hi = min(finite), max(finite)
        span = hi - lo
        pad = span * 0.05 if span > 1e-9 else max(abs(hi) * 0.05, 0.5)
        self._apply(lo - pad, hi + pad)
        if not silent:
            self._chk_auto.setChecked(False)

    def _symmetric(self) -> None:
        mid = self._spin_mid.value()
        finite = [abs(v - mid) for v in self._all_finite()]
        m = max(finite) if finite else 1.0
        m = m * 1.05 if m > 1e-9 else 1.0
        self._chk_auto.setChecked(False)
        self._curve.set_offset(mid)
        self._apply(-m, m)

    def _auto_mid(self) -> None:
        finite = self._all_finite()
        if finite:
            self._spin_mid.setValue((min(finite) + max(finite)) / 2.0)

    def _on_auto(self, on: bool) -> None:
        for w in (self._spin_lo, self._spin_hi, self._btn_apply):
            w.setEnabled(not on and not self._chk_norm.isChecked())
        if on:
            self._curve.set_offset(0.0)
            self._fit(silent=True)

    def _on_manual(self) -> None:
        if self._chk_auto.isChecked() or self._chk_norm.isChecked():
            return
        self._curve.set_range(self._spin_lo.value(), self._spin_hi.value())

    def _on_norm(self, on: bool) -> None:
        # 归一化时共享量程那套控件没有意义，禁用掉免得误导
        self._curve.set_normalized(on)
        for w in (self._chk_auto, self._spin_lo, self._spin_hi,
                  self._btn_apply, self._spin_mid, self._btn_sym):
            w.setEnabled(not on)
        if not on:
            self._on_auto(self._chk_auto.isChecked())

    # ---- 缩放 ----
    def _on_y_range_requested(self, lo: float, hi: float) -> None:
        self._chk_auto.setChecked(False)      # 滚轮/拖拽接管量程，自动量程让位
        self._apply(lo, hi)

    def _reset_zoom(self) -> None:
        self._curve.reset_x_view()
        if self._chk_norm.isChecked():
            return                            # 归一化下共享量程不适用，只复位横轴
        if self._chk_auto.isChecked():
            self._fit(silent=True)
        else:
            self._chk_auto.setChecked(True)   # 触发 _on_auto：清中值偏移并重新适配

    def closeEvent(self, ev) -> None:  # noqa: N802
        self._settings.var_plot_w = self.width()
        self._settings.var_plot_h = self.height()
        super().closeEvent(ev)
