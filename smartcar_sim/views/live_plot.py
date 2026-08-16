"""串口实时波形面板：调 PI 时盯着目标速度/当前转速的活曲线。

复用 var_plot 的 _Curve（横/纵缩放、平移、游标读数、悬停一整套交互都在），本面板补上实时特有的三件事：
- **跟随最新**：滚动显示最近 N 点；手动缩放/平移会自动退出跟随，回看历史不被新数据拽走。
- **自动量程**：按「可见窗口」内的数据适配，不是全历史——阶跃测试后量程能快速稳定下来。
- **节流与上限**：收帧只记数据，30Hz 定时重绘；只保留最近 _MAX_POINTS 点，长时间调参不吃内存。
"""
from __future__ import annotations

import math

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .var_plot import Series, _Curve, color_for

_MAX_POINTS = 20_000
_TRIM_SLACK = 4_000     # 攒够这么多再裁一次，避免每帧 O(n) 搬移


class LiveWavePanel(QWidget):
    """按通道（CH1..CHn）累积波形帧并实时绘制。append() 由串口帧回调喂。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._curve = _Curve()
        self._series: list[Series] = []
        self._total = 0      # 累计帧数
        self._rate = 0       # 本秒帧数
        self._dirty = False

        self._chk_follow = QCheckBox("跟随最新")
        self._chk_follow.setChecked(True)
        self._chk_follow.setToolTip("滚动显示最近 N 点；手动缩放/平移会自动退出跟随")
        self._spin_win = QSpinBox()
        self._spin_win.setRange(50, _MAX_POINTS)
        self._spin_win.setValue(500)
        self._spin_win.setSuffix(" 点")
        self._chk_auto = QCheckBox("自动量程")
        self._chk_auto.setChecked(True)
        self._chk_auto.setToolTip("按可见窗口内的数据适配上下限；Ctrl+滚轮手动缩放会自动关闭")
        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(self.clear)
        self._lbl = QLabel("等待数据…")
        self._lbl.setStyleSheet("color:#9cdcfe; font-family:Consolas;")

        bar = QHBoxLayout()
        bar.addWidget(self._chk_follow)
        bar.addWidget(self._spin_win)
        bar.addSpacing(8)
        bar.addWidget(self._chk_auto)
        bar.addWidget(btn_clear)
        bar.addStretch(1)
        bar.addWidget(self._lbl)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(bar)
        lay.addWidget(self._curve, 1)

        self._curve.x_view_changed.connect(
            lambda: self._chk_follow.setChecked(False))
        self._curve.y_range_requested.connect(self._on_y_range)
        self._chk_follow.toggled.connect(self._mark_dirty)
        self._spin_win.valueChanged.connect(self._mark_dirty)
        self._chk_auto.toggled.connect(self._mark_dirty)

        self._flush_timer = QTimer(self)
        self._flush_timer.timeout.connect(self._flush)
        self._flush_timer.start(33)
        self._rate_timer = QTimer(self)
        self._rate_timer.timeout.connect(self._tick_rate)
        self._rate_timer.start(1000)

    # ---- 数据 ----
    def append(self, values) -> None:
        """收到一帧波形：每个元素是一个通道的采样值。通道数变化自动适配。"""
        vals = [float(v) for v in values]
        n_have = len(self._series[0].values) if self._series else 0
        while len(self._series) < len(vals):     # 通道变多：新线的历史补 None（画成空缺）
            i = len(self._series)
            self._series.append(Series(f"CH{i + 1}", [None] * n_have, color_for(i)))
        for i, s in enumerate(self._series):
            s.values.append(vals[i] if i < len(vals) else None)
        if self._series and len(self._series[0].values) > _MAX_POINTS + _TRIM_SLACK:
            cut = len(self._series[0].values) - _MAX_POINTS
            for s in self._series:
                del s.values[:cut]
        self._total += 1
        self._rate += 1
        self._dirty = True

    def clear(self) -> None:
        self._series = []
        self._curve.set_series(self._series)
        self._curve.reset_x_view()
        self._total = 0
        self._rate = 0
        self._dirty = False
        self._lbl.setText("等待数据…")

    # ---- 绘制节流 ----
    def _mark_dirty(self) -> None:
        self._dirty = True

    def _flush(self) -> None:
        if not self._dirty:
            return
        self._dirty = False
        self._curve.set_series(self._series)
        n = self._curve.frame_count()
        if n == 0:
            return
        if self._chk_follow.isChecked():
            self._curve.show_last(self._spin_win.value())
        self._curve.set_current_frame(n - 1)     # 游标钉在最新点 → 左上角就是实时读数
        if self._chk_auto.isChecked():
            self._fit_visible()

    def _fit_visible(self) -> None:
        x0, x1 = self._curve.x_view()
        i0, i1 = max(0, math.ceil(x0)), math.floor(x1)
        vals = [
            v
            for s in self._series
            if s.visible
            for v in s.values[i0 : i1 + 1]
            if v is not None and math.isfinite(v)
        ]
        if not vals:
            return
        lo, hi = min(vals), max(vals)
        span = hi - lo
        pad = span * 0.05 if span > 1e-9 else max(abs(hi) * 0.05, 0.5)
        self._curve.set_range(lo - pad, hi + pad)

    def _on_y_range(self, lo: float, hi: float) -> None:
        self._chk_auto.setChecked(False)         # 手动缩放接管量程
        self._curve.set_range(lo, hi)

    def _tick_rate(self) -> None:
        rate, self._rate = self._rate, 0
        if self._total:
            self._lbl.setText(f"{len(self._series)} 通道｜{rate} 帧/s｜共 {self._total}")
