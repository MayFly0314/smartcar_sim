"""应用入口。scheme 注册必须在 QApplication 之前。"""
import os
import sys


def main() -> int:
    from .editor.scheme_handler import register_scheme
    register_scheme()

    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from .main_window import MainWindow
    win = MainWindow()
    win.show()

    # 自测钩子：SMARTCAR_SELFTEST=<路径> 时，编辑器就绪即写标记并退出。
    # 用于验证打包后 exe 里 Monaco 能正常加载。
    marker = os.environ.get("SMARTCAR_SELFTEST")
    if marker:
        from PySide6.QtCore import QTimer

        def _on_ready():
            try:
                from pathlib import Path
                Path(marker).write_text("ready", encoding="utf-8")
            finally:
                app.quit()

        win.editor.ready.connect(_on_ready)
        QTimer.singleShot(60000, app.quit)  # 兜底超时（frozen 冷启动较慢）

    # 深度自测：SMARTCAR_SELFTEST_FULL=<路径> 时，实跑 加载→编译→运行 全链路。
    full_marker = os.environ.get("SMARTCAR_SELFTEST_FULL")
    if full_marker:
        from PySide6.QtCore import QTimer
        from ._selftest import run_full_selftest
        run_full_selftest(win, full_marker, app.quit)
        QTimer.singleShot(90000, app.quit)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
