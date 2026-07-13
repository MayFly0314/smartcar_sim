"""截图内置终端界面：启动 -> 敲命令 -> 截图。"""
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

SHOT = Path(__file__).parent.parent / "_term_shot.png"


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.resize(1400, 860)
    win.show()
    term = win.terminal

    def go():
        win.bottom_tabs.setCurrentWidget(term)
        term._bridge.write_in(base64.b64encode(
            "Get-Location; echo '在这里可运行 claude / atomcode 等 AI'\r".encode()).decode())
        QTimer.singleShot(1500, shot)

    def shot():
        win.grab().save(str(SHOT))
        print(f"[shot] {SHOT}")
        app.quit()

    win.editor.ready.connect(lambda: QTimer.singleShot(1500, go))
    QTimer.singleShot(30000, app.quit)
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
