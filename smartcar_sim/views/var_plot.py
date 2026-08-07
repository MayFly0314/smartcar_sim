"""单变量曲线窗口：双击监视面板的变量打开，Y 轴上下限可手动设定。

自动量程按整段数据的 min/max 归一，小幅波动会被压平；这里允许手填上下限，
把感兴趣的区间放大，细节就出来了。窗口可开多个（每变量一个），与时间轴联动。
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

_BG = QColor("#1e1e1e")
_GRID = QColor(255, 255, 255, 28)
_CURVE = QColor("#4ec9b0")
_CURSOR = QColor("#569cd6")
_TEXT = QColor("#d4d4d4")
_AXIS = QColor("#9cdcfe")
_OUT = QColor("#f48771")     # 超出上下限的点用红色贴边提示

_PAD_L = 62      # 左侧 Y 轴刻度区
_PAD_R = 10
_PAD_T = 10
_PAD_B = 20      # 底部帧号轴


def _finite(v) -> bool:
    return v is not None and math.isfinite(v)


class _Curve(QWidget):
    """曲线绘制区：手动 Y 量程 + 游标 + 悬停读数。"""

    frame_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._values: list[float | None] = []
        self._name = ""
        self._cur = 0
        self._lo = 0.0
        self._hi = 1.0
        self._offset = 0.0     # 中值对称：按 (值 - offset) 显示
        self.setMouseTracking(True)
        self.setMinimumHeight(220)
        self._font = QFont("Consolas", 9)

    def set_data(self, name: str, values: list[float | None]) -> None:
        self._name = name
        self._values = values
        self.update()

    def set_offset(self, offset: float) -> None:
        """设中值：绘制与读数都用 (值 - offset)。0 表示显示绝对值。"""
        self._offset = float(offset)
        self.update()

    def _disp(self, v: float) -> float:
        return v - self._offset

    def set_range(self, lo: float, hi: float) -> None:
        if hi - lo < 1e-12:
            hi = lo + 1e-6
        self._lo, self._hi = lo, hi
        self.update()

    def set_current_frame(self, idx: int) -> None:
        self._cur = max(0, min(idx, max(0, len(self._values) - 1)))
        self.update()

    # ---- 几何 ----
    def _plot_rect(self) -> QRectF:
        return QRectF(
            _PAD_L, _PAD_T,
            max(10, self.width() - _PAD_L - _PAD_R),
            max(10, self.height() - _PAD_T - _PAD_B),
        )

    def _x_at(self, i: int, r: QRectF) -> float:
        n = len(self._values)
        return r.center().x() if n <= 1 else r.left() + i / (n - 1) * r.width()

    def _y_at(self, v: float, r: QRectF) -> float:
        frac = (v - self._lo) / (self._hi - self._lo)
        frac = max(0.0, min(1.0, frac))          # 超限贴边
        return r.bottom() - frac * r.height()

    def _frame_at_x(self, x: float, r: QRectF) -> int:
        n = len(self._values)
        if n <= 1 or r.width() <= 0:
            return 0
        return max(0, min(int(round((x - r.left()) / r.width() * (n - 1))), n - 1))

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
            val = self._hi - k / 5 * (self._hi - self._lo)
            p.drawText(QRectF(2, y - 8, _PAD_L - 8, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{val:g}")

        n = len(self._values)
        if n == 0:
            p.end()
            return

        # 帧号轴（首/中/末）
        p.setPen(_TEXT)
        for i in (0, (n - 1) // 2, n - 1):
            p.drawText(QRectF(self._x_at(i, r) - 24, r.bottom() + 2, 48, 16),
                       Qt.AlignmentFlag.AlignCenter, str(i))

        # 曲线（缺失点断段；超限点标红）
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(_CURVE)
        pen.setWidthF(1.4)
        p.setPen(pen)
        seg: list[QPointF] = []
        out_pts: list[QPointF] = []
        for i, v in enumerate(self._values):
            if _finite(v):
                dv = self._disp(v)
                pt = QPointF(self._x_at(i, r), self._y_at(dv, r))
                seg.append(pt)
                if dv < self._lo or dv > self._hi:
                    out_pts.append(pt)
            else:
                if len(seg) >= 2:
                    p.drawPolyline(seg)
                elif len(seg) == 1:
                    p.drawEllipse(seg[0], 1.6, 1.6)
                seg = []
        if len(seg) >= 2:
            p.drawPolyline(seg)
        elif len(seg) == 1:
            p.drawEllipse(seg[0], 1.6, 1.6)
        p.setPen(QPen(_OUT))
        p.setBrush(_OUT)
        for pt in out_pts:
            p.drawEllipse(pt, 1.8, 1.8)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # 当前帧游标
        cx = self._x_at(self._cur, r)
        p.setPen(QPen(_CURSOR))
        p.drawLine(QPointF(cx, r.top()), QPointF(cx, r.bottom()))
        cv = self._values[self._cur] if self._cur < n else None
        if _finite(cv):
            p.setBrush(_CURSOR)
            p.drawEllipse(QPointF(cx, self._y_at(self._disp(cv), r)), 3.0, 3.0)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(_TEXT)
            rel = (f"  (相对中值 {self._disp(cv):+g})" if abs(self._offset) > 1e-12 else "")
            p.drawText(QRectF(r.left() + 4, r.top() + 2, r.width() - 8, 16),
                       Qt.AlignmentFlag.AlignLeft,
                       f"帧 {self._cur}  {self._name} = {cv:g}{rel}")
        p.end()

    # ---- 交互 ----
    def _seek(self, pos) -> None:
        r = self._plot_rect()
        if r.left() <= pos.x() <= r.right():
            self.frame_selected.emit(self._frame_at_x(pos.x(), r))

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self._seek(ev.position())

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if ev.buttons() & Qt.MouseButton.LeftButton:
            self._seek(ev.position())
            return
        r = self._plot_rect()
        if r.left() <= ev.position().x() <= r.right() and self._values:
            i = self._frame_at_x(ev.position().x(), r)
            v = self._values[i] if i < len(self._values) else None
            if _finite(v):
                rel = (f"  ({self._disp(v):+g})" if abs(self._offset) > 1e-12 else "")
                txt = f"帧 {i}｜{self._name} = {v:g}{rel}"
            else:
                txt = f"帧 {i}｜无值"
            QToolTip.showText(ev.globalPosition().toPoint(), txt, self)
        else:
            QToolTip.hideText()


class VarPlotDialog(QDialog):
    """单变量曲线窗口（非模态，可同时开多个）。"""

    frame_selected = Signal(int)

    def __init__(self, name: str, values: list[float | None], parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"变量曲线 — {name}")
        self.resize(720, 380)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self._name = name

        self._curve = _Curve()
        self._curve.frame_selected.connect(self.frame_selected)

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
        btn_fit.setToolTip("上下限设为数据的 min/max")

        # 中值对称：以某个中值为 0 看偏差（如舵机 PWM 中值 1500 → 1300 显示为 -200）
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

        bar = QHBoxLayout()
        bar.addWidget(self._chk_auto)
        bar.addSpacing(8)
        bar.addWidget(QLabel("下限"))
        bar.addWidget(self._spin_lo)
        bar.addWidget(QLabel("上限"))
        bar.addWidget(self._spin_hi)
        bar.addWidget(self._btn_apply)
        bar.addWidget(btn_fit)
        bar.addSpacing(12)
        bar.addWidget(QLabel("中值"))
        bar.addWidget(self._spin_mid)
        bar.addWidget(btn_mid_auto)
        bar.addWidget(self._btn_sym)
        bar.addStretch(1)
        self._lbl_stat = QLabel("")
        self._lbl_stat.setStyleSheet("color:#9cdcfe; font-family:Consolas;")
        bar.addWidget(self._lbl_stat)

        top = QWidget()
        top.setLayout(bar)
        lay = QVBoxLayout(self)
        lay.addWidget(top)
        lay.addWidget(self._curve, 1)

        self._chk_auto.toggled.connect(self._on_auto)
        # 只在"确定"/回车时生效，避免边输边刷（输 1300 途中经过 1、13、130）
        self._btn_apply.clicked.connect(self._on_manual)
        self._spin_lo.editingFinished.connect(self._on_manual)
        self._spin_hi.editingFinished.connect(self._on_manual)
        btn_fit.clicked.connect(self._fit)
        self._btn_sym.clicked.connect(self._symmetric)
        btn_mid_auto.clicked.connect(self._auto_mid)

        self.set_values(values)

    # ---- 数据 ----
    def set_values(self, values: list[float | None]) -> None:
        self._values = list(values)
        self._curve.set_data(self._name, self._values)
        finite = [v for v in self._values if _finite(v)]
        if finite:
            lo, hi = min(finite), max(finite)
            self._lbl_stat.setText(f"min {lo:g}  max {hi:g}  n={len(self._values)}")
        else:
            self._lbl_stat.setText("无有效数据")
        if self._chk_auto.isChecked():
            self._fit(silent=True)

    def set_current_frame(self, idx: int) -> None:
        self._curve.set_current_frame(idx)

    # ---- 量程 ----
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
        finite = [v for v in self._values if _finite(v)]
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
        """以中值为 0 对称显示偏差（舵机 PWM 1500 中值 → 1300 显示 -200）。"""
        mid = self._spin_mid.value()
        finite = [abs(v - mid) for v in self._values if _finite(v)]
        m = max(finite) if finite else 1.0
        m = m * 1.05 if m > 1e-9 else 1.0
        self._chk_auto.setChecked(False)
        self._curve.set_offset(mid)          # 曲线按"值 - 中值"绘制与读数
        self._apply(-m, m)

    def _auto_mid(self) -> None:
        finite = [v for v in self._values if _finite(v)]
        if finite:
            self._spin_mid.setValue((min(finite) + max(finite)) / 2.0)

    def _on_auto(self, on: bool) -> None:
        for w in (self._spin_lo, self._spin_hi, self._btn_apply):
            w.setEnabled(not on)
        if on:
            self._curve.set_offset(0.0)      # 回到绝对值显示
            self._fit(silent=True)

    def _on_manual(self) -> None:
        if self._chk_auto.isChecked():
            return
        self._curve.set_range(self._spin_lo.value(), self._spin_hi.value())
