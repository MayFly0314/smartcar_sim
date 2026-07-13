"""M2 序列验收：文件夹加载 + 多帧运行 + 状态机跨帧演进 + 时间轴。

用法：python -m tests.sequence_check
用 s_curve 序列验证：
  - 文件夹自然排序加载 60 帧
  - 一次运行处理全部帧
  - lost_rows 随弯道弧度跨帧变化（状态机输入随帧演进）
  - 时间轴切帧联动显示
"""
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

state = {"fail": ""}
TRACKS = ROOT / "examples" / "tracks" / "s_curve"
N = 60


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from smartcar_sim.settings import Settings
    s = Settings()
    saved_ws, saved_lf = s.last_workspace, s.last_file
    ws = ROOT / "examples" / "workspace_demo"
    s.last_workspace = str(ws)
    s.last_file = str(ws / "image_demo.c")

    win = MainWindow()
    win.show()

    def restore():
        s.last_workspace = saved_ws
        s.last_file = saved_lf
    app.aboutToQuit.connect(restore)

    def fail(m):
        state["fail"] = m
        print(f"[FAIL] {m}")
        app.quit()

    def step1():
        print("[1] 编辑器就绪，加载 s_curve 文件夹...")
        win._load_images(TRACKS)
        if win.frameset is None or win.frameset.count != N:
            return fail(f"文件夹加载帧数错误: {win.frameset.count if win.frameset else 0}")
        print(f"[2] 文件夹加载 ✓ {win.frameset.count} 帧，自然排序")
        # 校验自然排序
        names = [p.name for p in win.frameset.paths]
        if names != sorted(names):
            return fail("排序错误")
        QTimer.singleShot(500, step2)

    def step2():
        print(f"[3] 运行全部 {N} 帧...")
        win._run_pipeline()
        poll()

    def poll(t=[0]):
        if win.run_result is not None:
            return verify()
        t[0] += 1
        if t[0] > 600:  # 120s：容忍 Defender 扫描新 exe 造成的慢编译
            return fail("运行超时")
        QTimer.singleShot(200, poll)

    def verify():
        rr = win.run_result
        if rr.crashed:
            return fail(f"崩溃: {rr.error_msg}")
        if rr.frame_count != N:
            return fail(f"结果帧数错误: {rr.frame_count}")
        print(f"[4] 运行完成 ✓ {rr.frame_count} 帧")
        # 弯道弧度周期变化 -> lost_rows 跨帧起伏
        lost = [f.watches.get("lost_rows", 0) for f in rr.frames]
        span = max(lost) - min(lost)
        if span < 10:
            return fail(f"状态机输入无跨帧变化: min={min(lost)} max={max(lost)}")
        print(f"[5] 状态机输入跨帧演进 ✓ lost_rows {min(lost):.0f}~{max(lost):.0f}")
        # 时间轴切帧
        win.timeline.goto(25)
        QTimer.singleShot(200, check_timeline)

    def check_timeline():
        if win.timeline.current() != 25:
            return fail("时间轴定位失败")
        print("[6] 时间轴切帧联动 ✓ 当前帧=25")
        proc = win.run_result.processed
        if proc is None or proc.shape[0] != N:
            return fail("处理后序列不完整")
        print(f"[7] 处理后序列 ✓ shape={proc.shape}")
        print("\nM2 序列验收：全部通过 ✓")
        app.quit()

    win.editor.ready.connect(step1)
    QTimer.singleShot(300000, lambda: fail("总超时"))
    app.exec()
    return 1 if state["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
