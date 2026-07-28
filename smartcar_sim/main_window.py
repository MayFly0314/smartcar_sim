"""主窗口：三区布局 + Run 流水线。"""
from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import (
    QFileSystemWatcher,
    Qt,
    QThread,
    QTimer,
    QUrl,
    Signal,
    Slot,
    QObject,
)
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .build.compiler import compile_sources
from .build.diagnostics import CompileResult
from .build.scan import scan_includes
from .editor.monaco_widget import MonacoWidget
from .imaging.loader import FrameSet, guess_raw_layout, load_path, load_raw
from .link.serial_link import HAVE_PYSERIAL
from .paths import CSIM_DIR, cleanup_old_runs, new_work_dir
from .run.protocol import RunResult
from .run.runner import run_sim
from .settings import Settings
from .views.console import Console
from .views.image_view import ImageView
from .views.serial_dialog import SerialDialog
from .views.tag_panel import TagPanel
from .views.terminal import TerminalWidget
from .views.timeline import Timeline
from .views.watch_panel import WatchPanel


def _read_c_text(p: Path) -> str:
    """读 C 源文件并归一化换行为 \\n。

    必须字节级读取：曾因保存未指定 newline 产生过 \\r\\r\\n 损坏
    （文本模式 read_text 会把它读成两个换行，无法与真空行区分），
    这里先把 \\r\\r\\n 修回 \\r\\n 再统一归一化。
    """
    raw = p.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("gbk", errors="replace")
    text = text.replace("\r\r\n", "\r\n")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _write_c_text(p: Path, text: str) -> None:
    """统一 LF 落盘（newline="" 禁止平台换行翻译，防 \\r\\r\\n 复发）。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text)


class _RawParamDialog(QDialog):
    """SD raw 参数：分辨率 / 每帧帧头字节，配 guess_raw_layout 候选下拉 + 整除预览。"""

    def __init__(self, total_bytes: int, w0: int, h0: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SD 原始数据参数")
        self._total = int(total_bytes)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"文件大小：{self._total} 字节"))

        self._combo = QComboBox()
        self._combo.addItem("（手动指定）", None)
        for w, h, n in guess_raw_layout(self._total):
            self._combo.addItem(f"{w}×{h} → {n} 帧", (w, h))
        self._combo.currentIndexChanged.connect(self._apply_candidate)
        row = QHBoxLayout()
        row.addWidget(QLabel("候选布局"))
        row.addWidget(self._combo, 1)
        lay.addLayout(row)

        self._spin_w = QSpinBox()
        self._spin_w.setRange(1, 8192)
        self._spin_w.setValue(w0)
        self._spin_h = QSpinBox()
        self._spin_h.setRange(1, 8192)
        self._spin_h.setValue(h0)
        self._spin_hdr = QSpinBox()
        self._spin_hdr.setRange(0, 65536)
        self._spin_hdr.setValue(0)
        self._spin_ftr = QSpinBox()
        self._spin_ftr.setRange(0, 65536)
        self._spin_ftr.setValue(0)
        for text, wdg in (
            ("宽", self._spin_w),
            ("高", self._spin_h),
            ("每帧帧头字节", self._spin_hdr),
            ("每帧帧尾字节", self._spin_ftr),
        ):
            r = QHBoxLayout()
            r.addWidget(QLabel(text))
            r.addWidget(wdg, 1)
            lay.addLayout(r)

        self._preview = QLabel()
        self._preview.setWordWrap(True)
        self._preview.setStyleSheet("color:#9cdcfe;")
        lay.addWidget(self._preview)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        for wdg in (self._spin_w, self._spin_h, self._spin_hdr, self._spin_ftr):
            wdg.valueChanged.connect(self._update_preview)
        self._update_preview()

    def _apply_candidate(self) -> None:
        data = self._combo.currentData()
        if data:
            w, h = data
            self._spin_w.setValue(w)
            self._spin_h.setValue(h)

    def _update_preview(self) -> None:
        w, h, hdr, ftr = (
            self._spin_w.value(), self._spin_h.value(),
            self._spin_hdr.value(), self._spin_ftr.value(),
        )
        stride = hdr + w * h + ftr
        n = self._total // stride if stride else 0
        rem = self._total - n * stride if stride else self._total
        note = "✓ 整除" if rem == 0 else f"⚠ 余 {rem} 字节将被丢弃"
        self._preview.setText(f"每帧 {stride} 字节（头{hdr}+像素{w*h}+尾{ftr}）→ {n} 帧　{note}")

    def result_params(self) -> tuple[int, int, int, int]:
        return (
            self._spin_w.value(), self._spin_h.value(),
            self._spin_hdr.value(), self._spin_ftr.value(),
        )


class _Worker(QObject):
    """常驻工作线程里的编译-运行执行器。"""

    finished = Signal(object, object)  # (CompileResult, RunResult|None)

    def __init__(self):
        super().__init__()
        self._cache_key: tuple | None = None
        self._cache_result: CompileResult | None = None

    @staticmethod
    def _sources_key(c_files: list[Path], h_files: list[Path], w: int, h: int, gcc: str) -> tuple | None:
        """所有参与文件的内容哈希；文件读不到返回 None（此时不缓存）。"""
        digest = hashlib.sha1()
        try:
            for f in sorted([*c_files, *h_files]):
                digest.update(str(f).encode("utf-8", "replace"))
                digest.update(f.read_bytes())
        except OSError:
            return None
        return (digest.hexdigest(), w, h, gcc)

    @Slot(object)
    def do_run(self, job: dict) -> None:
        try:
            src: Path = job["src"]
            fs: FrameSet = job["fs"]
            w, h = fs.w, fs.h
            c_files, h_files = scan_includes(src)
            key = self._sources_key(c_files, h_files, w, h, job["gcc"] or "")
            if (
                key is not None
                and key == self._cache_key
                and self._cache_result is not None
                and self._cache_result.exe_path is not None
                and self._cache_result.exe_path.exists()
            ):
                cr = self._cache_result  # 源码没变，跳过编译
            else:
                cr = compile_sources(
                    c_files, w, h, gcc=job["gcc"] or None, header_files=h_files
                )
                if cr.ok and key is not None:
                    self._cache_key, self._cache_result = key, cr
            if not cr.ok:
                self.finished.emit(cr, None)
                return
            out_dir = new_work_dir("run")
            input_bin = out_dir / "input.bin"
            fs.pack_input_bin(input_bin)
            rr: RunResult = run_sim(
                cr.exe_path, input_bin, fs.count, out_dir, w, h,
                timeout_base_s=job["timeout"],
            )
            self.finished.emit(cr, rr)
        except Exception as e:  # noqa: BLE001 — worker 崩溃必须回报 UI，否则永远卡"运行中"
            import traceback
            traceback.print_exc()
            self.finished.emit(
                CompileResult(False, None, friendly_error=f"内部错误：{e}"), None
            )


class MainWindow(QMainWindow):
    _run_requested = Signal(object)  # job dict -> worker

    def __init__(self):
        super().__init__()
        self.setWindowTitle("智能车图像算法仿真器")
        self.resize(1400, 860)

        self.settings = Settings()
        self.frameset: FrameSet | None = None
        self.run_result: RunResult | None = None
        self._watcher = None
        self._watch_timer = None
        self.current_file: Path | None = None
        self._running = False
        self._online_run = False          # 串口在线逐帧跑标志（区别于普通 F5）
        self._online_base = None          # 在线帧底图（结果回来时叠加用）
        self._serial_dialog: SerialDialog | None = None

        # 常驻工作线程
        self._thread = QThread(self)
        self._worker = _Worker()
        self._worker.moveToThread(self._thread)
        self._run_requested.connect(self._worker.do_run)
        self._worker.finished.connect(self._on_pipeline_done)
        self._thread.start()
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._shutdown_thread)

        # ---- 部件 ----
        self.editor = MonacoWidget()
        self.image_view = ImageView()
        self.console = Console()
        self.timeline = Timeline()
        self.terminal = TerminalWidget()
        self.watch_panel = WatchPanel()
        self.tag_panel = TagPanel()

        self.chk_processed = QCheckBox("处理后")
        self.chk_overlay = QCheckBox("叠加")
        self.chk_overlay.setChecked(True)
        self.chk_load_rot = QCheckBox("载入转180°")
        self.chk_load_rot.setToolTip(
            "打开图像时旋转180°写入数据：适配「右下角=(0,0)」坐标约定\n"
            "（摄像头倒装时算法直接以右下角为原点，正的赛道图需勾选此项）"
        )
        self.chk_load_rot.setChecked(self.settings.load_rot180)
        self.chk_view_rot = QCheckBox("旋转显示")
        self.chk_view_rot.setToolTip("显示时旋转180°正着看图；数据与坐标读数不变（仍为右下角原点约定）")
        self.chk_view_rot.setChecked(self.settings.view_rot180)
        self.lbl_pixel = QLabel("")
        self.lbl_pixel.setStyleSheet("color:#9cdcfe; font-family:Consolas")

        view_bar = QHBoxLayout()
        view_bar.setContentsMargins(4, 2, 4, 2)
        view_bar.addWidget(self.chk_processed)
        view_bar.addWidget(self.chk_overlay)
        view_bar.addWidget(self.chk_load_rot)
        view_bar.addWidget(self.chk_view_rot)
        view_bar.addStretch(1)
        view_bar.addWidget(self.lbl_pixel)

        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 0, 0)
        rlay.setSpacing(2)
        rlay.addLayout(view_bar)
        rlay.addWidget(self.image_view, 1)
        rlay.addWidget(self.watch_panel)
        rlay.addWidget(self.tag_panel)
        rlay.addWidget(self.timeline)

        h_split = QSplitter(Qt.Orientation.Horizontal)
        h_split.addWidget(self.editor)
        h_split.addWidget(right)
        h_split.setSizes([700, 700])

        v_split = QSplitter(Qt.Orientation.Vertical)
        v_split.addWidget(h_split)
        self.bottom_tabs = QTabWidget()
        self.bottom_tabs.setDocumentMode(True)
        self.bottom_tabs.addTab(self.console, "输出")
        self.bottom_tabs.addTab(self.terminal, "终端")
        btn_restart = QPushButton("重启终端")
        btn_restart.setFlat(True)
        btn_restart.clicked.connect(self._restart_terminal)
        self.bottom_tabs.setCornerWidget(btn_restart)
        v_split.addWidget(self.bottom_tabs)
        v_split.setSizes([640, 220])
        self.setCentralWidget(v_split)

        self._build_menu()
        self.statusBar().showMessage("就绪")

        # ---- 信号 ----
        self.editor.save_requested.connect(self._save_text)
        self.editor.dirty_changed.connect(self._update_title)
        self.console.jump_requested.connect(self._jump_to)
        self.image_view.pixel_hovered.connect(self._on_pixel)
        self.timeline.frame_changed.connect(self._show_frame)
        self.watch_panel.frame_selected.connect(self.timeline.goto)
        self.tag_panel.tag_selected.connect(self.image_view.set_highlight)
        self.chk_processed.toggled.connect(lambda _: self._show_frame(self.timeline.current()))
        self.chk_overlay.toggled.connect(self._on_overlay_toggle)
        self.chk_load_rot.toggled.connect(self._on_load_rot_toggle)
        self.chk_view_rot.toggled.connect(self._on_view_rot_toggle)
        if self.settings.view_rot180:
            self.image_view.set_view_rot180(True)

        self._restore_session()

    # ---- 菜单 ----
    def _build_menu(self) -> None:
        m_file = self.menuBar().addMenu("文件(&F)")
        self._add_action(m_file, "新建 C 文件（从模板）...", "Ctrl+N", self._new_c_file)
        self._add_action(m_file, "打开 C 文件...", "Ctrl+O", self._open_c_file)
        self._add_action(m_file, "打开图像...", "Ctrl+I", self._open_image)
        self._add_action(m_file, "打开图像文件夹...", "Ctrl+Shift+I", self._open_image_folder)
        self._add_action(m_file, "打开 SD 原始数据(raw)...", None, self._open_sd_raw)
        m_file.addSeparator()
        self._add_action(m_file, "保存代码", "Ctrl+S", self._request_save)
        self._add_action(m_file, "在资源管理器中打开代码位置", None, self._reveal_workspace)

        m_run = self.menuBar().addMenu("运行(&R)")
        self._add_action(m_run, "编译并运行", "F5", self._run_pipeline)
        m_run.addSeparator()
        self._act_watch = self._add_action(
            m_run, "外部编辑模式（VSCode 改完自动运行）", None, self._toggle_watch
        )
        self._act_watch.setCheckable(True)

        m_link = self.menuBar().addMenu("连接(&L)")
        self._add_action(m_link, "串口图传...", None, self._open_serial_dialog)
        self._add_action(m_link, "蓝牙图传（SPP，同串口）...", None, self._open_serial_dialog)

        m_help = self.menuBar().addMenu("帮助(&H)")
        self._add_action(m_help, "API 速查（画线/日志/移植）", "F1", self._show_api_help)
        self._add_action(m_help, "导出单片机移植头文件...", None, self._export_port_header)

    def _add_action(self, menu, text, shortcut, slot) -> QAction:
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    # ---- 文件操作 ----
    _NEW_TEMPLATE = '''#include "sim_api.h"

void image_process(uint8_t img[IMG_H][IMG_W])
{
    /* 在这里写你的图像处理算法。
     * img[y][x]：y=行(0在顶部)，x=列(0在左边)，值 0~255。
     * 按 F1 查看全部 API（画点/画线/日志/移植说明）。 */

    sim_draw_cross(IMG_W / 2, IMG_H / 2, 5, SIM_ORANGE);
    sim_log("hello, frame %d", sim_frame_index());
}
'''

    def _new_c_file(self) -> None:
        start = self.settings.last_workspace or str(Path.home() / "Documents" / "SmartcarSim" / "workspace")
        fn, _ = QFileDialog.getSaveFileName(
            self, "新建 C 文件", str(Path(start) / "my_algo.c"), "C 源文件 (*.c)"
        )
        if not fn:
            return
        p = Path(fn)
        _write_c_text(p, self._NEW_TEMPLATE)
        self._load_c_file(p)

    def _open_c_file(self) -> None:
        start = self.settings.last_workspace or str(Path.home())
        fn, _ = QFileDialog.getOpenFileName(self, "打开 C 文件", start, "C 源文件 (*.c);;所有文件 (*)")
        if fn:
            self._load_c_file(Path(fn))

    def _load_c_file(self, p: Path) -> None:
        text = _read_c_text(p)
        self.current_file = p
        self.settings.last_workspace = str(p.parent)
        self.settings.last_file = str(p)
        self.editor.set_text(text)
        self.terminal.set_cwd(p.parent)  # 终端重启后落在代码目录
        self._update_title()
        self.statusBar().showMessage(f"已打开 {p}")

    def _open_image(self) -> None:
        start = self.settings.last_image or str(Path.home())
        fn, _ = QFileDialog.getOpenFileName(
            self, "打开图像", start, "图像 (*.bmp *.png *.jpg *.pgm);;所有文件 (*)"
        )
        if fn:
            self._load_images(Path(fn))

    def _open_image_folder(self) -> None:
        start = self.settings.last_image or str(Path.home())
        d = QFileDialog.getExistingDirectory(self, "打开图像文件夹", start)
        if d:
            self._load_images(Path(d))

    def _load_images(self, p: Path) -> None:
        try:
            fs = load_path(p)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "加载失败", str(e))
            return
        if self.settings.load_rot180:
            # 右下角原点约定：正的赛道图旋转 180° 后 [0][0] = 原图右下角
            fs = fs.rotated180()
        self.settings.last_image = str(p)
        self.load_frameset(fs, f"已加载 {fs.count} 帧 {fs.w}x{fs.h}")

    def load_frameset(self, fs: FrameSet, label: str) -> None:
        """统一注入口：本地文件 / 串口抓取 / SD raw 三条路的帧都经此进入运行流水线。"""
        self.frameset = fs
        self.run_result = None
        self.watch_panel.clear()
        self.tag_panel.clear()
        self.timeline.set_range(fs.count)
        self.image_view.reset_fit()
        self._show_frame(0)
        self.statusBar().showMessage(label)

    # ---- 串口图传 ----
    def _open_serial_dialog(self) -> None:
        if not HAVE_PYSERIAL:
            QMessageBox.warning(
                self, "缺少依赖",
                "串口图传需要 pyserial。\n请在下方“终端”标签里运行：pip install pyserial",
            )
            return
        if self._serial_dialog is None:
            self._serial_dialog = SerialDialog(self.settings, self)
            self._serial_dialog.frames_captured.connect(self._on_serial_frames)
            self._serial_dialog.frame_online.connect(self.run_single_frame)
        self._serial_dialog.show()
        self._serial_dialog.raise_()
        self._serial_dialog.activateWindow()

    def _on_serial_frames(self, fs: FrameSet, label: str) -> None:
        self.load_frameset(fs, f"{label}（已加载，按 F5 跑算法）")

    def run_single_frame(self, frame) -> None:
        """串口在线模式：把单帧当 1 帧 FrameSet 跑一次算法并叠加显示。

        用现成 self._running 节流——上一帧没跑完就丢掉中间帧，算法慢自动降帧率。
        **不动 self.frameset/timeline/面板**——在线帧只临时喂给运行器、结果直接画到图像视图，
        用户已加载的多帧序列与时间轴保持不变（退出在线即恢复正常）。
        走磁盘上已保存的 .c（不逐帧回写编辑器）；编译缓存保证只有 sim.exe 每帧重跑。
        """
        if self._running or self.current_file is None:
            return
        try:
            fs = FrameSet.from_frames([frame])
        except Exception:  # noqa: BLE001
            return
        self._online_base = frame     # 结果回来时作为底图叠加
        self._online_run = True
        self._running = True
        self._run_requested.emit({
            "src": self.current_file,
            "fs": fs,                 # 仅本次运行用，不写入 self.frameset
            "gcc": self.settings.gcc_path,
            "timeout": self.settings.timeout_base,
        })

    # ---- SD 卡原始数据 ----
    def _open_sd_raw(self) -> None:
        start = self.settings.last_sd_raw or self.settings.last_image or str(Path.home())
        fn, _ = QFileDialog.getOpenFileName(
            self, "打开 SD 原始数据（多帧连续灰度 raw）", start,
            "原始数据 (*.bin *.raw *.dat);;所有文件 (*)",
        )
        if not fn:
            return
        p = Path(fn)
        try:
            total = p.stat().st_size
        except OSError as e:
            QMessageBox.warning(self, "读取失败", str(e))
            return
        dlg = _RawParamDialog(total, self.settings.img_w, self.settings.img_h, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        w, h, header_bytes, footer_bytes = dlg.result_params()
        try:
            fs = load_raw(
                p, w, h, header_bytes=header_bytes,
                frame_stride=header_bytes + w * h + footer_bytes,
            )
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "解析失败", str(e))
            return
        self.settings.last_sd_raw = str(p)
        self.settings.img_w = w
        self.settings.img_h = h
        self.load_frameset(fs, f"SD raw {p.name} · {fs.count} 帧 {fs.w}×{fs.h}")

    def _request_save(self) -> None:
        self.editor.get_text_async(self._save_text)

    def _save_text(self, text: str) -> None:
        if self.current_file is None:
            start = self.settings.last_workspace or str(Path.home())
            fn, _ = QFileDialog.getSaveFileName(self, "保存 C 文件", start, "C 源文件 (*.c)")
            if not fn:
                return
            self.current_file = Path(fn)
            self.settings.last_workspace = str(self.current_file.parent)
        _write_c_text(self.current_file, text)
        self.editor.mark_saved()
        self._update_title()
        self.statusBar().showMessage(f"已保存 {self.current_file.name}")

    def _reveal_workspace(self) -> None:
        target = self.current_file.parent if self.current_file else Path(self.settings.last_workspace or Path.home())
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    # ---- 帮助 ----
    def _show_api_help(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("API 速查")
        dlg.resize(760, 620)
        txt = QPlainTextEdit(dlg)
        txt.setReadOnly(True)
        txt.setStyleSheet("font-family:Consolas,monospace; font-size:13px;")
        txt.setPlainText(_API_HELP_TEXT)
        lay = QVBoxLayout(dlg)
        lay.addWidget(txt)
        dlg.exec()

    def _export_port_header(self) -> None:
        src = CSIM_DIR / "port" / "sim_api.h"
        start = self.settings.last_workspace or str(Path.home())
        fn, _ = QFileDialog.getSaveFileName(
            self, "导出单片机移植版 sim_api.h（放进 MCU 工程后算法零改动）",
            str(Path(start) / "sim_api.h"), "C 头文件 (*.h)"
        )
        if fn:
            Path(fn).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            self.statusBar().showMessage(f"已导出移植头文件到 {fn}")

    # ---- 外部编辑模式 ----
    def _toggle_watch(self, checked: bool) -> None:
        if checked:
            if self.current_file is None:
                QMessageBox.information(self, "提示", "请先打开 C 文件")
                self._act_watch.setChecked(False)
                return
            # 一并监听 include 的依赖文件，改任何一个都自动重跑
            c_files, h_files = scan_includes(self.current_file)
            watch = [str(p) for p in {*c_files, *h_files}]
            self._watcher = QFileSystemWatcher(watch, self)
            self._watcher.fileChanged.connect(self._on_external_change)
            self.editor.setEnabled(False)
            self.statusBar().showMessage(
                f"外部编辑模式：用 VSCode 等编辑 {self.current_file.name}，保存即自动编译运行"
            )
        else:
            if getattr(self, "_watcher", None):
                self._watcher.deleteLater()
                self._watcher = None
            self.editor.setEnabled(True)
            self.statusBar().showMessage("外部编辑模式已关闭")

    def _on_external_change(self, path: str) -> None:
        # 编辑器常用"写临时文件+替换"保存，watcher 会掉监听，重挂
        if getattr(self, "_watcher", None) and Path(path).exists():
            if path not in self._watcher.files():
                self._watcher.addPath(path)
        # 防抖：编辑器保存可能触发多次事件
        if getattr(self, "_watch_timer", None) is None:
            self._watch_timer = QTimer(self)
            self._watch_timer.setSingleShot(True)
            self._watch_timer.timeout.connect(self._run_external)
        self._watch_timer.start(300)

    def _run_external(self) -> None:
        if self.current_file is None or self._running:
            return
        try:
            text = _read_c_text(self.current_file)
        except OSError:
            return
        self.editor.set_text(text)  # 同步显示到内嵌编辑器（只读展示）
        # 直接编译运行磁盘上的文件，不回写（回写会再次触发 watcher 造成循环）
        if self.frameset is not None:
            self.editor.clear_markers()
            self.console.clear_all()
            self.console.append_info(f"[外部编辑] 检测到 {self.current_file.name} 改动，编译运行...")
            self._running = True
            self.statusBar().showMessage("编译运行中...")
            self._run_requested.emit({
                "src": self.current_file,
                "fs": self.frameset,
                "gcc": self.settings.gcc_path,
                "timeout": self.settings.timeout_base,
            })

    # ---- 运行流水线 ----
    def _run_pipeline(self) -> None:
        if self._running:
            return
        if self.frameset is None:
            QMessageBox.information(self, "提示", "请先打开图像（Ctrl+I）")
            return
        if self.current_file is None:
            QMessageBox.information(self, "提示", "请先打开或保存 C 文件（Ctrl+O）")
            return
        # 原子占位：get_text_async 是异步往返 Monaco，若此刻不占位，
        # 在线模式下一帧串口图像会在空窗里插队跑掉，绕过节流。
        self._running = True
        self.editor.get_text_async(self._run_after_save)

    def _run_after_save(self, text: str) -> None:
        self._running = True  # 冗余保险（_run_pipeline 已置）；外部编辑等路径也经此
        try:
            _write_c_text(self.current_file, text)
        except OSError as e:
            self._running = False  # 写盘失败要复位，否则卡在"运行中"
            QMessageBox.warning(self, "保存失败", str(e))
            return
        self.editor.mark_saved()
        self.editor.clear_markers()
        self.console.clear_all()
        self.console.append_info(f"编译 {self.current_file.name} ...")
        self.statusBar().showMessage("编译运行中...")
        self._run_requested.emit({
            "src": self.current_file,
            "fs": self.frameset,
            "gcc": self.settings.gcc_path,
            "timeout": self.settings.timeout_base,
        })

    def _on_pipeline_done(self, cr: CompileResult, rr: RunResult | None) -> None:
        self._running = False
        if self._online_run:
            # 串口在线逐帧：结果直接画到图像视图，不碰 self.frameset/timeline/面板/控制台（否则刷屏、错乱）
            self._online_run = False
            if (
                cr.ok and rr is not None and not rr.crashed and rr.frames
                and self._online_base is not None
            ):
                self.image_view.show_frame(self._online_base, rr.frames[0])
            cleanup_old_runs()  # 在线会话不走下方正常清理，这里补清临时 run_* 目录
            return
        if not cr.ok:
            self.console.append_error("编译失败：")
            if cr.friendly_error:
                self.console.append_error(cr.friendly_error)
            self.console.append_diags(cr.diags)
            if self.current_file:
                mine = [d for d in cr.diags if d.file == str(self.current_file)]
                self.editor.set_markers(mine)
            self.statusBar().showMessage("编译失败")
            return

        warns = [d for d in cr.diags if d.severity == "warning"]
        if warns:
            self.console.append_diags(warns)
            mine = [d for d in warns if d.file == str(self.current_file)]
            self.editor.set_markers(mine)
        self.console.append_success("编译成功。")

        if rr is None:
            return
        self.run_result = rr
        self.watch_panel.set_run(rr.frames)
        self.tag_panel.set_run(rr.frames)
        if rr.crashed:
            where = f"第 {rr.crash_frame} 帧" if rr.crash_frame >= 0 else "启动时"
            self.console.append_error(f"运行崩溃（{where}）：{rr.error_msg}")
            if rr.crash_frame > 0:
                self.timeline.goto(rr.crash_frame - 1)
        else:
            n = rr.frame_count
            total_us = sum(f.t_us for f in rr.frames)
            self.console.append_success(
                f"运行完成：{n} 帧，算法总耗时 {total_us/1000:.2f} ms"
                f"（平均 {total_us/max(1,n):.0f} us/帧）"
            )
        if rr.logs:
            self.console.append_logs(rr.logs[:500])
            if len(rr.logs) > 500:
                self.console.append_info(f"...日志过多，已截断（共 {len(rr.logs)} 条）")
        self._show_frame(self.timeline.current())
        self.statusBar().showMessage("运行完成")
        cleanup_old_runs()

    # ---- 显示 ----
    def _show_frame(self, idx: int) -> None:
        if self.frameset is None or idx < 0 or idx >= self.frameset.count:
            return
        rr = self.run_result
        use_processed = self.chk_processed.isChecked()
        if use_processed and rr is not None and rr.processed is not None and idx < rr.processed.shape[0]:
            base = rr.processed[idx]
        else:
            base = self.frameset.frames[idx]
        fr = None
        if rr is not None and idx < len(rr.frames):
            fr = rr.frames[idx]
        self.image_view.show_frame(base, fr)
        self.watch_panel.set_current_frame(idx)
        self.tag_panel.set_current_frame(idx)

    def _on_overlay_toggle(self, on: bool) -> None:
        self.image_view.set_overlay_visible(on)
        self._show_frame(self.timeline.current())

    def _on_load_rot_toggle(self, on: bool) -> None:
        self.settings.load_rot180 = on
        # 当前已加载的帧就地翻转，重新运行前旧 run 叠加已不对应，直接清掉
        if self.frameset is not None:
            self.frameset = self.frameset.rotated180()
            self.run_result = None
            self.watch_panel.clear()
            self.tag_panel.clear()
            self._show_frame(self.timeline.current())
        self.statusBar().showMessage(
            "载入转180°：已开（数据以右下角为原点）" if on else "载入转180°：已关"
        )

    def _on_view_rot_toggle(self, on: bool) -> None:
        self.settings.view_rot180 = on
        self.image_view.set_view_rot180(on)

    def _on_pixel(self, x: int, y: int, v: int) -> None:
        self.lbl_pixel.setText(f"({x}, {y}) = {v}" if x >= 0 else "")

    def _jump_to(self, file: str, line: int, col: int) -> None:
        if self.current_file and file == str(self.current_file):
            self.editor.goto(line, col)

    def _update_title(self, *_args) -> None:
        path = str(self.current_file) if self.current_file else "未命名"
        star = " ●" if self.editor.is_dirty else ""
        self.setWindowTitle(f"{path}{star} — 智能车图像算法仿真器")

    def _restart_terminal(self) -> None:
        if self.current_file:
            self.terminal.set_cwd(self.current_file.parent)
        self.terminal.start_shell()
        self.bottom_tabs.setCurrentWidget(self.terminal)
        self.statusBar().showMessage("终端已重启")

    # ---- 会话恢复 ----
    def _shutdown_thread(self) -> None:
        if self._serial_dialog is not None:
            self._serial_dialog.shutdown()
        self._thread.quit()
        self._thread.wait(3000)

    def closeEvent(self, ev) -> None:  # noqa: N802
        self.terminal.stop_shell()
        self._shutdown_thread()
        super().closeEvent(ev)

    def _restore_session(self) -> None:
        from .paths import ROOT
        demo = ROOT / "examples" / "workspace_demo" / "image_demo.c"

        def when_ready():
            # 1) 精确恢复上次编辑的文件
            last = self.settings.last_file
            if last and Path(last).is_file():
                self._load_c_file(Path(last))
                return
            # 2) 退而求其次：上次工作区里的第一个 .c
            last_ws = self.settings.last_workspace
            candidates = sorted(Path(last_ws).glob("*.c")) if last_ws and Path(last_ws).is_dir() else []
            if candidates:
                self._load_c_file(candidates[0])
                return
            # 3) 首次启动：把示例拷到用户工作区再打开（不污染模板）
            if demo.exists():
                ws = Path.home() / "Documents" / "SmartcarSim" / "workspace"
                ws.mkdir(parents=True, exist_ok=True)
                target = ws / demo.name
                if not target.exists():
                    _write_c_text(target, _read_c_text(demo))
                self._load_c_file(target)

        self.editor.ready.connect(when_ready)

        last_img = self.settings.last_image
        if last_img and Path(last_img).exists():
            self._load_images(Path(last_img))


_API_HELP_TEXT = """\
════════════════ 智能车图像仿真器 API 速查（按 F1 随时打开）════════════════

【入口函数 —— 你必须实现的唯一函数】
  void image_process(uint8_t img[IMG_H][IMG_W]);
    · 每帧调用一次；img[行y][列x]，左上角(0,0)，值0~255
    · img 可读可写：写回的结果在"处理后"视图查看（如二值化结果）
    · static/全局变量跨帧保持 → 状态机直接用 static
    · IMG_W=188, IMG_H=120（编译时自动注入，可在代码里直接用）

【绘图 —— 结果叠加显示在右侧图像上（越界自动忽略，不会崩）】
  sim_draw_point(x, y, SIM_RED);            画一个点（边线逐点画）
  sim_draw_line(x0,y0, x1,y1, SIM_GREEN);   画线段（中线/补线）
  sim_draw_rect(x, y, w, h, SIM_BLUE);      空心矩形（框ROI区域）
  sim_draw_circle(cx, cy, r, SIM_CYAN);     空心圆（环岛拟合）
  sim_draw_cross(x, y, size, SIM_ORANGE);   十字标记（角点/拐点）
  sim_draw_text(x, y, SIM_YELLOW, "th=%d", th);  文字标注（printf风格）

【日志与监视】
  sim_log("otsu = %d", th);        打印到底部控制台，自动带[帧号]前缀
  sim_plot("error", err);          记录数值→图像下方监视面板（每变量一行：
                                   当前帧值+跨帧曲线；点击曲线跳帧，悬停看值）
  sim_tag(x, y, "L角点 t=%d", t);  给图上某位置附加说明（不画到图上）：
                                   鼠标悬停该处弹出查看；图像下方"本帧标注"
                                   列表逐条列出，点击行图上高亮该点。
                                   同一帧可多次调用（逐个拐点标注类型/坐标）
  sim_frame_index();               当前帧号(0起)。仅调试用，别参与算法！

【颜色常量】
  SIM_RED  SIM_GREEN  SIM_BLUE  SIM_YELLOW  SIM_CYAN
  SIM_MAGENTA  SIM_ORANGE  SIM_PURPLE  SIM_WHITE  SIM_BLACK
  也可直接写 0xRRGGBB，如 0xFF8800

【printf 安全格式符】 %d %u %x %s %c %f
  ✗ 不要用 %zu %hhu %lld —— Windows和单片机都不支持

【典型用法：画左右边线】
  for (y = IMG_H-1; y >= 0; y--) {
      // ...你的扫线逻辑得到 left_x, right_x ...
      sim_draw_point(left_x,  y, SIM_RED);    // 左边界红色
      sim_draw_point(right_x, y, SIM_BLUE);   // 右边界蓝色
      sim_draw_point((left_x+right_x)/2, y, SIM_GREEN);  // 中线绿色
  }

【移植到单片机 —— 算法代码零改动】
  1. 菜单【帮助 → 导出单片机移植头文件】，把导出的 sim_api.h
     放进 MCU 工程（和你的算法 .c 同目录）
  2. 你的算法 .c 原样拷入 MCU 工程
  3. 主循环里每帧调用 image_process(mt9v03x_image)
  原理：移植版头文件把所有 sim_* 定义为空宏，零体积零开销。
  ⚠ 唯一注意：宏不求值参数，别写 sim_log("%d", cnt++) 这种带副作用的！

【常用操作】
  F5        编译并运行          Ctrl+S    保存代码
  Ctrl+I    打开图像            Ctrl+Shift+I  打开图像文件夹
  滚轮      缩放图像（≥8倍显示像素网格）
  编译错误  在底部控制台点击错误行 → 自动跳到出错代码行
"""
