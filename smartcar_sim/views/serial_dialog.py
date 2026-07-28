"""串口图传对话框：独立顶层窗口（非模态），不堆砌在主界面上。

职责：选端口/波特率/协议 → 后台线程实时收帧 → 预览；"抓取 N 帧"攒成 FrameSet
经信号交给主窗口走现成运行流水线；可选"逐帧在线跑算法叠加"。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..imaging.loader import FrameSet
from ..link.serial_link import (
    HAVE_PYSERIAL,
    PROTOCOL_CHOICES,
    SerialWorker,
    enumerate_ports,
    make_protocol,
    parse_hex,
)
from ..settings import Settings
from .image_view import gray_to_qimage

_BAUDS = ["115200", "230400", "460800", "921600", "1500000", "2000000"]


class SerialDialog(QDialog):
    frames_captured = Signal(object, str)  # (FrameSet, 描述)
    frame_online = Signal(object)          # (H, W) uint8，逐帧在线跑用

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("串口图传")
        self.resize(520, 640)
        # 非模态：不阻塞主窗口
        self.setWindowFlag(Qt.WindowType.Window, True)

        self._thread: QThread | None = None
        self._worker: SerialWorker | None = None
        self._connected = False
        self._port_label = ""
        self._total = 0
        self._fps_count = 0
        self._captured: list = []
        self._capture_remaining = 0
        self._capture_target = 0
        self._online = False

        self._build_ui()
        self._refresh_ports()
        self._on_proto_changed()

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._tick_status)

    # ---- UI ----
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # 连接区
        gb_conn = QGroupBox("连接")
        grid = QGridLayout(gb_conn)
        self._combo_port = QComboBox()
        self._combo_port.setMinimumWidth(220)
        btn_refresh = QPushButton("刷新")
        btn_refresh.setFixedWidth(52)
        btn_refresh.clicked.connect(self._refresh_ports)

        self._combo_baud = QComboBox()
        self._combo_baud.setEditable(True)
        self._combo_baud.addItems(_BAUDS)
        self._combo_baud.setCurrentText(str(self.settings.serial_baud))

        self._combo_proto = QComboBox()
        for key, text, _needs in PROTOCOL_CHOICES:
            self._combo_proto.addItem(text, key)
        self._select_data(self._combo_proto, self.settings.serial_protocol)
        self._combo_proto.currentIndexChanged.connect(self._on_proto_changed)

        self._spin_w = QSpinBox()
        self._spin_w.setRange(1, 4096)
        self._spin_w.setValue(self.settings.img_w)
        self._spin_h = QSpinBox()
        self._spin_h.setRange(1, 4096)
        self._spin_h.setValue(self.settings.img_h)

        self._edit_header = QLineEdit(self.settings.serial_header)
        self._edit_header.setPlaceholderText("自定义帧头 hex，如 55 AA（空=纯定长）")
        self._edit_footer = QLineEdit(self.settings.serial_footer)
        self._edit_footer.setPlaceholderText("自定义帧尾 hex，如 0D 0A（空=无，校验帧尾更抗错位）")

        self._btn_conn = QPushButton("连接")
        self._btn_conn.clicked.connect(self._toggle_conn)

        r = 0
        grid.addWidget(QLabel("端口"), r, 0)
        grid.addWidget(self._combo_port, r, 1)
        grid.addWidget(btn_refresh, r, 2)
        r += 1
        grid.addWidget(QLabel("波特率"), r, 0)
        grid.addWidget(self._combo_baud, r, 1, 1, 2)
        r += 1
        grid.addWidget(QLabel("协议"), r, 0)
        grid.addWidget(self._combo_proto, r, 1, 1, 2)
        r += 1
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("宽"))
        size_row.addWidget(self._spin_w)
        size_row.addWidget(QLabel("高"))
        size_row.addWidget(self._spin_h)
        size_row.addStretch(1)
        wrap = QWidget()
        wrap.setLayout(size_row)
        grid.addWidget(QLabel("分辨率"), r, 0)
        grid.addWidget(wrap, r, 1, 1, 2)
        r += 1
        grid.addWidget(QLabel("帧头"), r, 0)
        grid.addWidget(self._edit_header, r, 1, 1, 2)
        r += 1
        grid.addWidget(QLabel("帧尾"), r, 0)
        grid.addWidget(self._edit_footer, r, 1, 1, 2)
        r += 1
        grid.addWidget(self._btn_conn, r, 0, 1, 3)
        root.addWidget(gb_conn)

        # 预览区
        self._preview = QLabel("未连接")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumHeight(260)
        self._preview.setStyleSheet("background:#1e1e1e; color:#888; border:1px solid #333;")
        root.addWidget(self._preview, 1)

        self._lbl_status = QLabel("未连接")
        self._lbl_status.setStyleSheet("color:#9cdcfe; font-family:Consolas;")
        root.addWidget(self._lbl_status)

        self._lbl_bw = QLabel("")
        self._lbl_bw.setStyleSheet("color:#888;")
        root.addWidget(self._lbl_bw)

        # 抓取区
        gb_cap = QGroupBox("抓取帧序列（存下后可用 F5 跑算法/回放）")
        cap = QHBoxLayout(gb_cap)
        cap.addWidget(QLabel("帧数"))
        self._spin_n = QSpinBox()
        self._spin_n.setRange(1, 2000)
        self._spin_n.setValue(self.settings.capture_count)
        cap.addWidget(self._spin_n)
        self._btn_capture = QPushButton("抓取 N 帧")
        self._btn_capture.clicked.connect(self._start_capture)
        cap.addWidget(self._btn_capture, 1)
        root.addWidget(gb_cap)

        # 在线区
        self._chk_online = QCheckBox("逐帧在线跑算法并叠加显示（在线仿真）")
        self._chk_online.toggled.connect(self._on_online_toggled)
        root.addWidget(self._chk_online)

        self._update_bw_hint()
        self._spin_w.valueChanged.connect(self._update_bw_hint)
        self._spin_h.valueChanged.connect(self._update_bw_hint)
        self._combo_baud.currentTextChanged.connect(self._update_bw_hint)

    @staticmethod
    def _select_data(combo: QComboBox, data) -> None:
        i = combo.findData(data)
        if i >= 0:
            combo.setCurrentIndex(i)

    def _refresh_ports(self) -> None:
        self._combo_port.clear()
        ports = enumerate_ports()
        if not ports:
            self._combo_port.addItem("（未发现串口）", "")
        for device, desc in ports:
            self._combo_port.addItem(desc, device)
        self._select_data(self._combo_port, self.settings.serial_port)

    def _on_proto_changed(self) -> None:
        key = self._combo_proto.currentData()
        needs_size = True
        for k, _t, n in PROTOCOL_CHOICES:
            if k == key:
                needs_size = n
                break
        # 协议 B 自描述宽高 → 置灰 W/H；仅自定义协议启用帧头/帧尾输入
        self._spin_w.setEnabled(needs_size)
        self._spin_h.setEnabled(needs_size)
        self._edit_header.setEnabled(key == "custom")
        self._edit_footer.setEnabled(key == "custom")

    def _update_bw_hint(self) -> None:
        try:
            baud = int(self._combo_baud.currentText())
        except ValueError:
            self._lbl_bw.setText("")
            return
        per = self._spin_w.value() * self._spin_h.value()
        if baud <= 0:
            self._lbl_bw.setText("")
            return
        sec = per * 10 / baud  # 8N1 每字节约 10 bit
        fps = 1.0 / sec if sec > 0 else 0
        self._lbl_bw.setText(f"带宽估算：{per} 字节/帧 ≈ {sec*1000:.0f} ms/帧 ≈ {fps:.1f} fps")

    # ---- 连接 ----
    def _toggle_conn(self) -> None:
        if self._connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self) -> None:
        if not HAVE_PYSERIAL:
            QMessageBox.warning(self, "缺少依赖", "未安装 pyserial。\n请在终端运行：pip install pyserial")
            return
        port = self._combo_port.currentData()
        if not port:
            QMessageBox.information(self, "提示", "请选择串口（插上设备后点刷新）")
            return
        try:
            baud = int(self._combo_baud.currentText())
        except ValueError:
            QMessageBox.warning(self, "提示", "波特率必须是整数")
            return
        key = self._combo_proto.currentData()
        header = self._edit_header.text()
        footer = self._edit_footer.text()
        try:
            if key == "custom":
                parse_hex(header)  # 提前校验帧头/帧尾 hex
                parse_hex(footer)
            proto = make_protocol(key, header, footer)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "帧头/帧尾解析失败", str(e))
            return
        w, h = self._spin_w.value(), self._spin_h.value()

        # 持久化配置
        self.settings.serial_port = port
        self.settings.serial_baud = baud
        self.settings.serial_protocol = key
        self.settings.serial_header = header
        self.settings.serial_footer = footer
        self.settings.img_w = w
        self.settings.img_h = h

        self._thread = QThread(self)
        self._worker = SerialWorker(port, baud, proto, w, h)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.frameReady.connect(self._on_frame)   # 跨线程自动队列连接
        self._worker.opened.connect(self._on_opened)
        self._worker.error.connect(self._on_error)
        self._worker.closed.connect(self._on_closed)

        self._connected = True
        self._port_label = port
        self._total = 0
        self._fps_count = 0
        self._set_config_enabled(False)
        self._btn_conn.setText("断开")
        self._lbl_status.setText(f"连接中… {port} @ {baud}")
        self._thread.start()
        self._status_timer.start(1000)

    def _disconnect(self) -> None:
        self._connected = False  # 先置位：让意外 closed 回调不再重复复位
        self._status_timer.stop()
        self._stop_thread()
        self._set_config_enabled(True)
        self._btn_conn.setText("连接")
        self._lbl_status.setText("已断开")
        self._reset_capture()

    def _stop_thread(self) -> None:
        if self._worker is not None:
            self._worker.stop()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
            self._thread.deleteLater()  # 线程有 C++ parent(dialog)，须显式回收，否则重连累积
        self._worker = None
        self._thread = None

    def _set_config_enabled(self, on: bool) -> None:
        for wdg in (self._combo_port, self._combo_baud, self._combo_proto):
            wdg.setEnabled(on)
        if on:
            self._on_proto_changed()  # 恢复 W/H/header 的按协议禁用状态
        else:
            for wdg in (self._spin_w, self._spin_h, self._edit_header, self._edit_footer):
                wdg.setEnabled(False)

    # ---- 帧回调 ----
    def _on_frame(self, frame) -> None:
        self._total += 1
        self._fps_count += 1
        self._update_preview(frame)
        if self._online:
            self.frame_online.emit(frame)
        if self._capture_remaining > 0:
            self._captured.append(frame)
            self._capture_remaining -= 1
            self._btn_capture.setText(f"抓取中… {len(self._captured)}/{self._capture_target}")
            if self._capture_remaining == 0:
                self._finish_capture()

    def _update_preview(self, frame) -> None:
        pix = QPixmap.fromImage(gray_to_qimage(frame))
        self._preview.setPixmap(
            pix.scaled(
                self._preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )
        )

    def _on_opened(self, desc: str) -> None:
        self._lbl_status.setText(f"已连 {desc}")

    def _on_error(self, msg: str) -> None:
        self._lbl_status.setText(f"⚠ {msg}")
        self._lbl_status.setStyleSheet("color:#f48771; font-family:Consolas;")

    def _on_closed(self) -> None:
        # 仅处理"意外断开"（正常断开在 _disconnect 里已置 _connected=False）
        if self._connected:
            self._connected = False
            self._status_timer.stop()
            self._set_config_enabled(True)
            self._btn_conn.setText("连接")
            self._reset_capture()
            self._stop_thread()  # 回收线程，避免重连时泄漏孤儿线程

    def _tick_status(self) -> None:
        if not self._connected:
            return
        fps = self._fps_count
        self._fps_count = 0
        buf_note = "抓取中" if self._capture_remaining > 0 else ""
        self._lbl_status.setStyleSheet("color:#9cdcfe; font-family:Consolas;")
        self._lbl_status.setText(
            f"已连 {self._port_label}｜实时 {fps} fps｜共收 {self._total} 帧 {buf_note}"
        )

    # ---- 抓取 ----
    def _start_capture(self) -> None:
        if not self._connected:
            QMessageBox.information(self, "提示", "请先连接串口")
            return
        if self._capture_remaining > 0:  # 再次点击 = 取消
            self._reset_capture()
            return
        n = self._spin_n.value()
        self.settings.capture_count = n
        self._captured = []
        self._capture_target = n
        self._capture_remaining = n
        self._btn_capture.setText(f"抓取中… 0/{n}（点此取消）")

    def _finish_capture(self) -> None:
        frames = self._captured
        self._reset_capture()
        if not frames:
            return
        try:
            fs = FrameSet.from_frames(frames)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "抓取失败", str(e))
            return
        label = f"串口 {self._port_label} · {fs.count} 帧 {fs.w}×{fs.h}"
        self.frames_captured.emit(fs, label)
        self._lbl_status.setText(f"已抓取 {fs.count} 帧，已加载到主窗口（按 F5 跑算法）")

    def _reset_capture(self) -> None:
        self._captured = []
        self._capture_remaining = 0
        self._capture_target = 0
        self._btn_capture.setText("抓取 N 帧")

    def _on_online_toggled(self, on: bool) -> None:
        self._online = on

    # ---- 生命周期 ----
    def closeEvent(self, ev) -> None:  # noqa: N802
        self._connected = False
        self._status_timer.stop()
        self._stop_thread()
        super().closeEvent(ev)

    def shutdown(self) -> None:
        """供主窗口在退出前调用，确保线程停掉。"""
        self._connected = False
        self._status_timer.stop()
        self._stop_thread()
