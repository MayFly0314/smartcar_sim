"""主窗口：三区布局 + Run 流水线。"""
from __future__ import annotations

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
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .build.compiler import compile_sources
from .build.diagnostics import CompileResult
from .editor.monaco_widget import MonacoWidget
from .imaging.loader import FrameSet, load_path
from .paths import CSIM_DIR, cleanup_old_runs, new_work_dir
from .run.protocol import RunResult
from .run.runner import run_sim
from .settings import Settings
from .views.console import Console
from .views.image_view import ImageView
from .views.terminal import TerminalWidget
from .views.timeline import Timeline


class _Worker(QObject):
    """常驻工作线程里的编译-运行执行器。"""

    finished = Signal(object, object)  # (CompileResult, RunResult|None)

    @Slot(object)
    def do_run(self, job: dict) -> None:
        try:
            src: Path = job["src"]
            fs: FrameSet = job["fs"]
            w, h = fs.w, fs.h
            cr: CompileResult = compile_sources([src], w, h, gcc=job["gcc"] or None)
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

        self.chk_processed = QCheckBox("处理后")
        self.chk_overlay = QCheckBox("叠加")
        self.chk_overlay.setChecked(True)
        self.lbl_pixel = QLabel("")
        self.lbl_pixel.setStyleSheet("color:#9cdcfe; font-family:Consolas")

        view_bar = QHBoxLayout()
        view_bar.setContentsMargins(4, 2, 4, 2)
        view_bar.addWidget(self.chk_processed)
        view_bar.addWidget(self.chk_overlay)
        view_bar.addStretch(1)
        view_bar.addWidget(self.lbl_pixel)

        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 0, 0)
        rlay.setSpacing(2)
        rlay.addLayout(view_bar)
        rlay.addWidget(self.image_view, 1)
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
        self.chk_processed.toggled.connect(lambda _: self._show_frame(self.timeline.current()))
        self.chk_overlay.toggled.connect(self._on_overlay_toggle)

        self._restore_session()

    # ---- 菜单 ----
    def _build_menu(self) -> None:
        m_file = self.menuBar().addMenu("文件(&F)")
        self._add_action(m_file, "新建 C 文件（从模板）...", "Ctrl+N", self._new_c_file)
        self._add_action(m_file, "打开 C 文件...", "Ctrl+O", self._open_c_file)
        self._add_action(m_file, "打开图像...", "Ctrl+I", self._open_image)
        self._add_action(m_file, "打开图像文件夹...", "Ctrl+Shift+I", self._open_image_folder)
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
        a_serial = self._add_action(m_link, "串口（待实现）", None, lambda: None)
        a_bt = self._add_action(m_link, "蓝牙（待实现）", None, lambda: None)
        a_serial.setEnabled(False)
        a_bt.setEnabled(False)

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
        p.write_text(self._NEW_TEMPLATE, encoding="utf-8")
        self._load_c_file(p)

    def _open_c_file(self) -> None:
        start = self.settings.last_workspace or str(Path.home())
        fn, _ = QFileDialog.getOpenFileName(self, "打开 C 文件", start, "C 源文件 (*.c);;所有文件 (*)")
        if fn:
            self._load_c_file(Path(fn))

    def _load_c_file(self, p: Path) -> None:
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = p.read_text(encoding="gbk", errors="replace")
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
        self.frameset = fs
        self.run_result = None
        self.settings.last_image = str(p)
        self.timeline.set_range(fs.count)
        self.image_view.reset_fit()
        self._show_frame(0)
        self.statusBar().showMessage(f"已加载 {fs.count} 帧 {fs.w}x{fs.h}")

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
        self.current_file.write_text(text, encoding="utf-8")
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
            self._watcher = QFileSystemWatcher([str(self.current_file)], self)
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
            text = self.current_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
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
        self.editor.get_text_async(self._run_after_save)

    def _run_after_save(self, text: str) -> None:
        self.current_file.write_text(text, encoding="utf-8")
        self.editor.mark_saved()
        self.editor.clear_markers()
        self.console.clear_all()
        self.console.append_info(f"编译 {self.current_file.name} ...")
        self._running = True
        self.statusBar().showMessage("编译运行中...")
        self._run_requested.emit({
            "src": self.current_file,
            "fs": self.frameset,
            "gcc": self.settings.gcc_path,
            "timeout": self.settings.timeout_base,
        })

    def _on_pipeline_done(self, cr: CompileResult, rr: RunResult | None) -> None:
        self._running = False
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

    def _on_overlay_toggle(self, on: bool) -> None:
        self.image_view.set_overlay_visible(on)
        self._show_frame(self.timeline.current())

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
                    target.write_text(demo.read_text(encoding="utf-8"), encoding="utf-8")
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
  sim_plot("error", err);          记录数值随帧变化（曲线面板规划中）
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
