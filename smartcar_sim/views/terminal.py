"""内嵌终端：xterm.js (QWebEngineView) + Windows ConPTY (pywinpty)。

在终端里可以运行任何 CLI 工具——包括 claude、atomcode 等 AI agent，
它们能直接读写当前工作区的代码文件；配合"外部编辑模式"，AI 改完保存
即自动编译运行。
"""
from __future__ import annotations

import base64
import shutil
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

from ..editor.scheme_handler import SCHEME, SchemeHandler
from ..paths import ASSETS_DIR


class _TermBridge(QObject):
    """JS <-> Python 桥。data_out/pty_exited 发往 JS；write_in/resize/ready 由 JS 调。"""

    data_out = Signal(str)      # base64 编码的 PTY 输出
    pty_exited = Signal()
    _ready = Signal(int, int)   # cols, rows（转内部信号，主线程处理）
    _data_pending = Signal()    # 读线程 -> 主线程：输出缓冲由空变非空
    _exited = Signal()          # 读线程 -> 主线程：PTY 结束（先刷余量再通知 JS）

    @Slot(int, int)
    def ready(self, cols: int, rows: int) -> None:
        self._ready.emit(cols, rows)

    @Slot(str)
    def write_in(self, b64: str) -> None:
        w = self.parent()
        if w._pty is not None:
            w._used = True  # 用户敲过键：cwd 变化不再自动重启，防打断工作
            try:
                w._pty.write(base64.b64decode(b64).decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001 — PTY 已死时静默
                pass

    @Slot(int, int)
    def resize(self, cols: int, rows: int) -> None:
        if self.parent()._pty is not None:
            try:
                self.parent()._pty.setwinsize(rows, cols)
            except Exception:  # noqa: BLE001
                pass


class TerminalWidget(QWebEngineView):
    """PowerShell 终端，工作目录跟随当前代码文件。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pty = None
        self._reader: threading.Thread | None = None
        self._cwd: str = str(Path.home())
        self._size = (120, 30)
        self._used = False  # 用户是否已在终端里敲过键
        # 输出合帧：TUI（如 claude）高频重绘时每块 4KB 就过一次 QWebChannel
        # 会形成 IPC 风暴。读线程只进缓冲，主线程 8ms 合一帧发往 JS。
        self._buf: list[str] = []
        self._buf_lock = threading.Lock()

        self._profile = QWebEngineProfile(self)
        self._handler = SchemeHandler(ASSETS_DIR, self)
        self._profile.installUrlSchemeHandler(SCHEME, self._handler)
        page = QWebEnginePage(self._profile, self)
        self.setPage(page)

        self._bridge = _TermBridge(self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("termBridge", self._bridge)
        page.setWebChannel(self._channel)
        self._bridge._ready.connect(self._on_term_ready)
        self._bridge._data_pending.connect(self._schedule_flush)
        self._bridge._exited.connect(self._on_pty_exited)

        self.load(QUrl("app://app/terminal.html"))

    # ---- 生命周期 ----
    def set_cwd(self, cwd: str | Path) -> None:
        """设置工作目录。shell 已在跑且用户还没用过时，直接发 cd 命令过去
        （比杀掉重启更可靠：与页面加载顺序无关，用户还能看到发生了什么）。"""
        new = str(cwd)
        if new == self._cwd:
            return
        self._cwd = new
        if self._pty is not None and not self._used:
            try:
                self._pty.write(f'cd "{new}"\r')
            except Exception:  # noqa: BLE001
                pass

    def _on_term_ready(self, cols: int, rows: int) -> None:
        self._size = (cols, rows)
        self.start_shell()

    def start_shell(self) -> None:
        """启动（或重启）shell：pwsh(PS7) 优先，回退 Windows PowerShell。"""
        self.stop_shell()
        self._used = False
        try:
            from winpty import PtyProcess
        except ImportError:
            self._bridge.data_out.emit(
                base64.b64encode(
                    "未安装 pywinpty，终端不可用。运行: pip install pywinpty\r\n".encode()
                ).decode("ascii")
            )
            return
        cols, rows = self._size
        shell = shutil.which("pwsh") or "powershell.exe"
        self._pty = PtyProcess.spawn(
            [shell, "-NoLogo"],
            dimensions=(rows, cols),
            cwd=self._cwd,
        )
        # spawn 的 cwd 参数在部分环境不生效，显式 cd 兜底（用户可见，无副作用）
        try:
            self._pty.write(f'cd "{self._cwd}"\r')
        except Exception:  # noqa: BLE001
            pass
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        """读线程：PTY 输出 -> 缓冲。仅缓冲由空变非空时发一次信号，主线程合帧。"""
        pty = self._pty
        try:
            while pty is not None and pty.isalive():
                data = pty.read(4096)
                if not data:
                    break
                with self._buf_lock:
                    was_empty = not self._buf
                    self._buf.append(data)
                if was_empty:
                    self._bridge._data_pending.emit()
        except (EOFError, OSError):
            pass
        finally:
            if self._pty is pty:
                self._bridge._exited.emit()

    def _schedule_flush(self) -> None:
        # 8ms 合帧：把窗口内到达的所有块拼成一条消息过桥
        QTimer.singleShot(8, self._flush_buf)

    def _flush_buf(self) -> None:
        with self._buf_lock:
            chunks, self._buf = self._buf, []
        if chunks:
            data = "".join(chunks)
            self._bridge.data_out.emit(
                base64.b64encode(data.encode("utf-8", "replace")).decode("ascii")
            )

    def _on_pty_exited(self) -> None:
        self._flush_buf()  # 先把余量刷给 JS，再宣告退出
        self._bridge.pty_exited.emit()

    def stop_shell(self) -> None:
        pty, self._pty = self._pty, None
        if pty is not None:
            try:
                pty.terminate(force=True)
            except Exception:  # noqa: BLE001
                pass
        with self._buf_lock:
            self._buf.clear()

    def closeEvent(self, ev) -> None:  # noqa: N802
        self.stop_shell()
        super().closeEvent(ev)
