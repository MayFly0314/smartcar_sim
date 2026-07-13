"""外部编辑模式验收：开启监听 -> 外部修改 .c 文件 -> 自动编译运行。

用法：python -m tests.watch_check（PowerShell）
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from smartcar_sim.editor.scheme_handler import register_scheme  # noqa: E402
register_scheme()

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from smartcar_sim.main_window import MainWindow  # noqa: E402

state = {"fail": ""}

CODE_V1 = '''#include "sim_api.h"
void image_process(uint8_t img[IMG_H][IMG_W]) {
    sim_draw_point(10, 10, SIM_RED);
    sim_log("version 1");
    (void)img;
}
'''
CODE_V2 = '''#include "sim_api.h"
void image_process(uint8_t img[IMG_H][IMG_W]) {
    sim_draw_point(20, 20, SIM_GREEN);
    sim_draw_point(21, 20, SIM_GREEN);
    sim_log("version 2");
    (void)img;
}
'''


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    tmp = Path(tempfile.mkdtemp(prefix="watch_"))
    src = tmp / "algo.c"
    src.write_text(CODE_V1, encoding="utf-8")
    bmp = tmp / "t.bmp"
    Image.fromarray(np.full((120, 188), 128, np.uint8)).save(bmp)

    from smartcar_sim.settings import Settings
    s = Settings()
    saved_ws, saved_img, saved_lf = s.last_workspace, s.last_image, s.last_file
    s.last_workspace = str(tmp)
    s.last_image = ""
    s.last_file = str(src)
    win = MainWindow()
    win.show()

    def restore():
        s.last_workspace = saved_ws
        s.last_image = saved_img
        s.last_file = saved_lf
    app.aboutToQuit.connect(restore)

    def fail(m):
        state["fail"] = m
        print(f"[FAIL] {m}")
        app.quit()

    def step1():
        win._load_images(bmp)
        win._load_c_file(src)
        print("[1] 已加载图像与 V1 代码")
        win._act_watch.setChecked(True)
        win._toggle_watch(True)
        if win._watcher is None:
            return fail("watcher 未启动")
        if win.editor.isEnabled():
            return fail("编辑器未置灰")
        print("[2] 外部编辑模式已开启 ✓（编辑器已置灰）")
        print("[3] 模拟 VSCode：外部写入 V2 并保存...")
        src.write_text(CODE_V2, encoding="utf-8")  # 触发 QFileSystemWatcher
        poll_v2()

    def poll_v2(t=[0]):
        rr = win.run_result
        if rr is not None:
            f0 = rr.frames[0]
            greens = [c for c in f0.cmds if c.kind == "P" and c.color == 0x00CC44]
            if len(greens) != 2:
                return fail(f"V2 结果不对：绿点数={len(greens)}")
            if not any("version 2" in t2 for _, t2 in rr.logs):
                return fail("V2 日志缺失")
            print("[4] 外部保存自动触发编译运行 ✓（结果已是 V2：2 个绿点）")
            win._act_watch.setChecked(False)
            win._toggle_watch(False)
            if not win.editor.isEnabled():
                return fail("关闭后编辑器未恢复")
            print("[5] 关闭外部编辑模式 ✓（编辑器恢复可用）")
            print("\n外部编辑模式验收：全部通过 ✓")
            app.quit()
            return
        t[0] += 1
        if t[0] > 200:
            print("--- 控制台 ---"); print(win.console.toPlainText()[:400])
            return fail("外部修改未触发自动运行（40s 超时）")
        QTimer.singleShot(200, poll_v2)

    win.editor.ready.connect(step1)
    QTimer.singleShot(60000, lambda: fail("总超时"))
    app.exec()
    return 1 if state["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
