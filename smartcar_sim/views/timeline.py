"""帧时间轴：上一帧/播放/下一帧/滑块。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QWidget


class Timeline(QWidget):
    frame_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._count = 0
        self._fps = 10

        self._btn_prev = QPushButton("|<")
        self._btn_play = QPushButton("播放")
        self._btn_next = QPushButton(">|")
        for b in (self._btn_prev, self._btn_play, self._btn_next):
            b.setFixedWidth(48)
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._label = QLabel("0 / 0")
        self._label.setFixedWidth(80)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.addWidget(self._btn_prev)
        lay.addWidget(self._btn_play)
        lay.addWidget(self._btn_next)
        lay.addWidget(self._slider, 1)
        lay.addWidget(self._label)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        self._btn_prev.clicked.connect(lambda: self.step(-1))
        self._btn_next.clicked.connect(lambda: self.step(+1))
        self._btn_play.clicked.connect(self.toggle_play)
        self._slider.valueChanged.connect(self._on_slider)
        self.set_range(0)

    # ---- API ----
    def set_range(self, count: int) -> None:
        self._count = count
        self.stop()
        self._slider.setRange(0, max(0, count - 1))
        self._slider.setValue(0)
        self._update_label(0)
        enabled = count > 1
        for w in (self._btn_prev, self._btn_play, self._btn_next, self._slider):
            w.setEnabled(enabled)

    def set_fps(self, fps: int) -> None:
        self._fps = max(1, fps)
        if self._timer.isActive():
            self._timer.start(1000 // self._fps)

    def current(self) -> int:
        return self._slider.value()

    def goto(self, idx: int) -> None:
        self._slider.setValue(max(0, min(idx, self._count - 1)))

    def step(self, d: int) -> None:
        self.goto(self.current() + d)

    def toggle_play(self) -> None:
        if self._timer.isActive():
            self.stop()
        else:
            if self._count > 1:
                self._timer.start(1000 // self._fps)
                self._btn_play.setText("暂停")

    def stop(self) -> None:
        self._timer.stop()
        self._btn_play.setText("播放")

    # ---- 内部 ----
    def _tick(self) -> None:
        nxt = self.current() + 1
        if nxt >= self._count:
            nxt = 0  # 循环播放
        self._slider.setValue(nxt)

    def _on_slider(self, v: int) -> None:
        self._update_label(v)
        self.frame_changed.emit(v)

    def _update_label(self, v: int) -> None:
        self._label.setText(f"{v + 1} / {self._count}" if self._count else "0 / 0")
