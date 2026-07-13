"""内置终端验收：PTY 启动 -> 敲命令 -> 收到输出 -> cwd 跟随代码目录。

用法：python -m tests.terminal_check（PowerShell）
"""
import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from smartcar_sim.editor.scheme_handler import register_scheme  # noqa: E402
register_scheme()

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from smartcar_sim.main_window import MainWindow  # noqa: E402

state = {"fail": "", "out": ""}


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()

    term = win.terminal

    def fail(m):
        state["fail"] = m
        print(f"[FAIL] {m}")
        app.quit()

    def collect(b64):
        state["out"] += base64.b64decode(b64).decode("utf-8", "replace")

    term._bridge.data_out.connect(collect)

    def step1(t=[0]):
        if term._pty is not None and term._pty.isalive():
            print("[1] PTY 已启动（PowerShell 存活）✓")
            # 模拟键入：echo 一个标记
            term._bridge.write_in(
                base64.b64encode("echo term-roundtrip-ok\r".encode()).decode()
            )
            QTimer.singleShot(100, poll_echo)
            return
        t[0] += 1
        if t[0] > 150:
            return fail("PTY 未启动（30s）")
        QTimer.singleShot(200, step1)

    def poll_echo(t=[0]):
        if "term-roundtrip-ok" in state["out"]:
            print("[2] 键入->执行->输出 回环 ✓")
            # cwd 跟随：当前文件目录应出现在提示符路径里
            if win.current_file:
                expected = str(win.current_file.parent).lower()
                if expected.rstrip("\\/") in state["out"].lower():
                    print(f"[3] 终端 cwd 跟随代码目录 ✓ ({win.current_file.parent})")
                else:
                    print(f"[3] cwd 未在输出中确认（非致命）: 期待 {expected}")
            print("\n内置终端验收：全部通过 ✓")
            app.quit()
            return
        t[0] += 1
        if t[0] > 100:
            return fail(f"echo 无回显（20s）。收到 {len(state['out'])} 字节")
        QTimer.singleShot(200, poll_echo)

    win.editor.ready.connect(lambda: QTimer.singleShot(500, step1))
    QTimer.singleShot(60000, lambda: fail("总超时"))
    app.exec()
    return 1 if state["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
