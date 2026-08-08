"""编辑器关闭后使用的宽屏参数与边界线工作区。"""
from __future__ import annotations

from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..run.protocol import FrameResult
from .boundary_view import BoundaryView
from .watch_panel import MAX_WATCHES, WatchPanel


class ParameterDashboard(QWidget):
    """大尺寸参数区，最多显示 50 个变量，同时保留三线白底预览。"""

    appearance_changed = Signal(object, object, int, bool)
    var_activated = Signal(str, object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._name_color = QColor("#ffcc66")
        self._value_color = QColor("#ffffff")
        self._font_size = 14
        self._bold = True

        tools = QHBoxLayout()
        tools.setContentsMargins(6, 5, 6, 5)
        tools.addWidget(QLabel("参数面板"))
        tools.addWidget(QLabel("名称"))
        self._name_btn = QPushButton("选择")
        self._name_btn.setToolTip("选择参数名称颜色")
        tools.addWidget(self._name_btn)
        tools.addWidget(QLabel("数值"))
        self._value_btn = QPushButton("选择")
        self._value_btn.setToolTip("选择参数数值颜色")
        tools.addWidget(self._value_btn)
        tools.addWidget(QLabel("字号"))
        self._font_spin = QSpinBox()
        self._font_spin.setRange(10, 28)
        self._font_spin.setValue(self._font_size)
        tools.addWidget(self._font_spin)
        self._bold_chk = QCheckBox("粗体")
        self._bold_chk.setChecked(self._bold)
        tools.addWidget(self._bold_chk)
        tools.addStretch(1)

        self.monitor_panel = WatchPanel(
            title=f"监视（最多 {MAX_WATCHES} 项）",
            max_tracks=MAX_WATCHES,
            row_height=36,
            cell_min_width=220,
            font_size=self._font_size,
            max_visible_rows=10,
        )
        self.record_panel = WatchPanel(
            title=f"车端记录（最多 {MAX_WATCHES} 项）",
            max_tracks=MAX_WATCHES,
            row_height=36,
            cell_min_width=220,
            font_size=self._font_size,
            max_visible_rows=10,
        )
        self.monitor_panel.var_activated.connect(self.var_activated)
        self.record_panel.var_activated.connect(self.var_activated)
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.addTab(self.monitor_panel, "监视参数")
        self._tabs.addTab(self.record_panel, "车端记录")

        self.boundary_view = BoundaryView()
        self._boundary_box = QWidget()
        boundary_lay = QVBoxLayout(self._boundary_box)
        boundary_lay.setContentsMargins(0, 0, 0, 0)
        boundary_lay.addWidget(QLabel("三条边界线（白底）"))
        boundary_lay.addWidget(self.boundary_view, 1)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self._tabs)
        split.addWidget(self._boundary_box)
        split.setSizes([420, 300])

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(tools)
        root.addWidget(split, 1)

        self._name_btn.clicked.connect(lambda: self._choose_color("name"))
        self._value_btn.clicked.connect(lambda: self._choose_color("value"))
        self._font_spin.valueChanged.connect(self._apply_controls)
        self._bold_chk.toggled.connect(self._apply_controls)
        self._update_color_buttons()
        self._apply_appearance(emit=False)

    def _update_color_buttons(self) -> None:
        for btn, color in ((self._name_btn, self._name_color), (self._value_btn, self._value_color)):
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {color.name()}; color: #111111; "
                "border:1px solid #888; padding:3px 12px; }"
            )

    def _choose_color(self, which: str) -> None:
        current = self._name_color if which == "name" else self._value_color
        color = QColorDialog.getColor(current, self, "选择参数颜色")
        if not color.isValid():
            return
        if which == "name":
            self._name_color = color
        else:
            self._value_color = color
        self._update_color_buttons()
        self._apply_appearance()

    def _apply_controls(self) -> None:
        self._font_size = self._font_spin.value()
        self._bold = self._bold_chk.isChecked()
        self._apply_appearance()

    def _apply_appearance(self, *, emit: bool = True) -> None:
        for panel in (self.monitor_panel, self.record_panel):
            panel.set_appearance(
                name_color=self._name_color,
                value_color=self._value_color,
                font_size=self._font_size,
                bold=self._bold,
            )
        if emit:
            self.appearance_changed.emit(
                QColor(self._name_color), QColor(self._value_color), self._font_size, self._bold
            )

    def set_appearance(self, name_color: QColor, value_color: QColor, font_size: int, bold: bool) -> None:
        self._name_color = QColor(name_color)
        self._value_color = QColor(value_color)
        self._font_size = int(font_size)
        self._bold = bool(bold)
        self._font_spin.blockSignals(True)
        self._font_spin.setValue(self._font_size)
        self._font_spin.blockSignals(False)
        self._bold_chk.blockSignals(True)
        self._bold_chk.setChecked(self._bold)
        self._bold_chk.blockSignals(False)
        self._update_color_buttons()
        self._apply_appearance(emit=False)

    def set_monitor_run(self, frames: list[FrameResult]) -> None:
        self.monitor_panel.set_run(frames)

    def set_record_run(self, frames: list[FrameResult]) -> None:
        self.record_panel.set_run(frames)

    def clear(self) -> None:
        self.monitor_panel.clear()
        self.record_panel.clear()
        self.boundary_view.clear()

    def set_current_frame(self, idx: int) -> None:
        self.monitor_panel.set_current_frame(idx)
        self.record_panel.set_current_frame(idx)
        self.boundary_view.set_current_frame(idx)

    def set_lines(self, lines, width: int, height: int) -> None:
        self.boundary_view.set_lines(lines, width, height)
