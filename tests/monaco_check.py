"""Monaco 集成验证：无人值守启动编辑器，捕获 JS 控制台错误，
确认编辑器 ready、能取值。5 秒内自动退出，输出结果到 stdout。

用法：python -m tests.monaco_check
退出码 0 = 成功；非 0 = 失败。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer  # noqa: E402

# scheme 必须在 QApplication 之前注册
from smartcar_sim.editor.scheme_handler import register_scheme  # noqa: E402
register_scheme()

from PySide6.QtWidgets import QApplication  # noqa: E402
from smartcar_sim.editor.monaco_widget import MonacoWidget  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

js_errors: list[str] = []
result = {"ready": False, "text_ok": False}


def main() -> int:
    app = QApplication(sys.argv)
    w = MonacoWidget()

    def on_console(level, msg, line, src):
        line_s = f"[JS L{level}] {msg} ({src}:{line})"
        print(line_s)
        if level >= 2:  # 2 = Error
            js_errors.append(line_s)

    w.console_message.connect(on_console)
    w.loadFinished.connect(lambda ok: print(f"[check] loadFinished ok={ok}"))
    w.resize(700, 500)
    w.show()

    def probe():
        # 直接探测页面 JS 环境
        w.page().runJavaScript(
            "JSON.stringify({require: typeof require, qt: typeof qt, "
            "monaco: typeof monaco, editor: (typeof editor!=='undefined' && !!editor)})",
            0, lambda r: print(f"[probe] {r}")
        )

    QTimer.singleShot(2000, probe)
    QTimer.singleShot(4000, probe)

    SAMPLE = "#include \"sim_api.h\"\nvoid image_process(uint8_t img[IMG_H][IMG_W]) {\n    sim_draw_point(1,2,SIM_RED);\n}\n"

    def on_ready():
        result["ready"] = True
        print("[check] editor ready ✓")
        w.set_text(SAMPLE)

        def got(text):
            ok = "image_process" in (text or "")
            result["text_ok"] = ok
            print(f"[check] getText round-trip {'✓' if ok else '✗'} (len={len(text or '')})")
            QTimer.singleShot(300, finish)

        QTimer.singleShot(300, lambda: w.get_text_async(got))

    def finish():
        app.quit()

    w.ready.connect(on_ready)
    # 兜底超时
    QTimer.singleShot(8000, lambda: (print("[check] TIMEOUT: editor 未就绪"), app.quit()))
    app.exec()

    print("\n=== 结果 ===")
    print(f"ready      : {result['ready']}")
    print(f"text round : {result['text_ok']}")
    print(f"JS errors  : {len(js_errors)}")
    for e in js_errors:
        print("   " + e)

    ok = result["ready"] and result["text_ok"] and not js_errors
    print("Monaco 集成验证：" + ("通过 ✓" if ok else "失败 ✗"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
