"""打包版 exe 深度自测：不只验证 Monaco 就绪，还实际跑一遍 编译+运行，
证明 frozen 模式下 csim 资源定位、gcc 调用、协议解析全链路可用。

由 app.py 在 SMARTCAR_SELFTEST_FULL 环境变量下调用（见 app.py）。
结果写入标记文件：OK / FAIL:<原因>
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
from PIL import Image


def run_full_selftest(win, marker_path: str, quit_fn) -> None:
    from PySide6.QtCore import QTimer

    # 自测会加载临时图/示例代码——退出前恢复用户会话状态，不污染 last_*
    s = win.settings
    saved = (s.last_workspace, s.last_file, s.last_image)

    W, H = 188, 120
    tmp = Path(tempfile.mkdtemp(prefix="exe_selftest_"))
    bmp = tmp / "t.bmp"
    img = np.full((H, W), 200, np.uint8)
    for y in range(H):
        cx = W // 2 + int(15 * np.sin(y / 20))
        img[y, max(0, cx - 30):min(W, cx + 30)] = 240
        for xx in (cx - 30, cx + 30):
            if 0 <= xx < W:
                img[y, xx] = 20
    Image.fromarray(img).save(bmp)

    def write(res: str):
        s.last_workspace, s.last_file, s.last_image = saved
        Path(marker_path).write_text(res, encoding="utf-8")
        quit_fn()

    def step_ready():
        try:
            win._load_images(bmp)
            if win.frameset is None or win.current_file is None:
                return write("FAIL:加载失败")
            QTimer.singleShot(500, step_run)
        except Exception as e:  # noqa: BLE001
            write(f"FAIL:{e}")

    def step_run():
        try:
            win._run_pipeline()
            poll()
        except Exception as e:  # noqa: BLE001
            write(f"FAIL:run:{e}")

    def poll(t=[0]):
        rr = win.run_result
        if rr is not None:
            if rr.crashed:
                return write(f"FAIL:crash:{rr.error_msg}")
            f0 = rr.frames[0] if rr.frames else None
            if not f0 or not any(c.kind == "P" for c in f0.cmds):
                return write("FAIL:无叠加结果")
            return write("OK")
        # 编译失败？
        if "编译失败" in win.console.toPlainText():
            return write("FAIL:编译失败")
        t[0] += 1
        if t[0] > 300:  # 冷启动首次编译较慢，给足 60s
            return write("FAIL:运行超时")
        QTimer.singleShot(200, poll)

    win.editor.ready.connect(step_ready)
