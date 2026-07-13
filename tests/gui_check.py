"""GUI 端到端验收：自动驾驶主窗口跑通黄金路径，截图留证。

用法：python -m tests.gui_check
流程：启动 -> 等编辑器就绪 -> 加载测试图 -> F5 运行 -> 校验结果+截图 -> 退出。
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

W, H = 188, 120
state = {"step": "", "fail": ""}
SHOT_DIR = Path(tempfile.gettempdir()) / "smartcar_gui_check"
SHOT_DIR.mkdir(exist_ok=True)


def make_track(path: Path) -> None:
    img = np.full((H, W), 200, np.uint8)
    for y in range(H):
        cx = W // 2 + int(15 * np.sin(y / 20))
        img[y, max(0, cx - 30):min(W, cx + 30)] = 240
        for xx in (cx - 30, cx + 30):
            if 0 <= xx < W:
                img[y, xx] = 20
    Image.fromarray(img).save(path)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    tmp = Path(tempfile.mkdtemp(prefix="guicheck_"))
    bmp = tmp / "track.bmp"
    make_track(bmp)

    # 隔离：测试用独立临时工作区，避免污染真实示例/用户工作区
    ws = tmp / "workspace"
    ws.mkdir()
    demo = ROOT / "examples" / "workspace_demo" / "image_demo.c"
    (ws / "image_demo.c").write_text(demo.read_text(encoding="utf-8"), encoding="utf-8")

    from smartcar_sim.settings import Settings
    s = Settings()
    saved_ws, saved_img, saved_lf = s.last_workspace, s.last_image, s.last_file
    s.last_workspace = str(ws)
    s.last_image = ""
    s.last_file = str(ws / "image_demo.c")

    win = MainWindow()
    win.show()

    def restore_settings():
        s.last_workspace = saved_ws
        s.last_image = saved_img
        s.last_file = saved_lf

    app.aboutToQuit.connect(restore_settings)

    def fail(msg: str):
        state["fail"] = msg
        print(f"[FAIL] {msg}")
        shot("fail")
        app.quit()

    def shot(name: str):
        p = SHOT_DIR / f"{name}.png"
        win.grab().save(str(p))
        print(f"[shot] {p}")

    def step1_editor_ready():
        state["step"] = "editor_ready"
        print("[1] 编辑器就绪 ✓")
        # 加载图像（绕过文件对话框直接调内部方法）
        win._load_images(bmp)
        if win.frameset is None or win.frameset.count != 1:
            return fail("图像加载失败")
        print(f"[2] 图像加载 ✓ {win.frameset.w}x{win.frameset.h}")
        # 确保用的是 demo 代码文件
        if win.current_file is None:
            return fail("未自动加载示例代码")
        print(f"[3] 代码文件 ✓ {win.current_file.name}")
        QTimer.singleShot(800, step2_run)

    def step2_run():
        state["step"] = "run"
        print("[4] 触发 F5 运行...")
        win._run_pipeline()
        poll_result()

    def poll_result(tries=[0]):
        if win.run_result is not None:
            return step3_verify()
        tries[0] += 1
        if tries[0] > 600:  # 120s：容忍 Defender 扫描新 exe 造成的慢编译
            return fail("运行超时未出结果")
        QTimer.singleShot(200, poll_result)

    def step3_verify():
        state["step"] = "verify"
        rr = win.run_result
        if rr.crashed:
            return fail(f"运行崩溃: {rr.error_msg}")
        if rr.frame_count < 1:
            return fail("无帧结果")
        f0 = rr.frames[0]
        kinds = {c.kind for c in f0.cmds}
        if "P" not in kinds:
            return fail("叠加指令缺失")
        print(f"[5] 运行结果 ✓ {len(f0.cmds)} 条指令, watches={f0.watches}")
        shot("overlay_on")
        # 切换处理后视图
        win.chk_processed.setChecked(True)
        QTimer.singleShot(300, step4_processed)

    def step4_processed():
        shot("processed_view")
        vals = set(np.unique(win.run_result.processed[0]))
        if not vals <= {0, 255}:
            return fail(f"处理后图像未二值化: {vals}")
        print(f"[6] 处理后视图 ✓ 像素值 {vals}")
        # 语法错误路径
        win.chk_processed.setChecked(False)
        win.editor.set_text('#include "sim_api.h"\nvoid image_process(uint8_t img[IMG_H][IMG_W]) {\n    int x = ;\n}\n')
        QTimer.singleShot(500, step5_error_run)

    def step5_error_run():
        print("[7] 触发编译错误运行...")
        win._run_pipeline()
        poll_error()

    def poll_error(tries=[0]):
        # 编译失败时 run_result 不更新，看控制台文本
        text = win.console.toPlainText()
        if "编译失败" in text:
            if "error" not in text:
                return fail("控制台无 error 诊断")
            print("[8] 编译错误诊断 ✓")
            shot("compile_error")
            print("\nGUI 端到端验收：全部通过 ✓")
            app.quit()
            return
        tries[0] += 1
        if tries[0] > 450:  # 90s：容忍慢环境
            return fail("编译错误路径超时")
        QTimer.singleShot(200, poll_error)

    win.editor.ready.connect(step1_editor_ready)
    QTimer.singleShot(300000, lambda: fail("总超时"))
    app.exec()
    return 1 if state["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
