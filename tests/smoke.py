"""无 GUI 冒烟测试：加载图像 -> 编译 demo -> 运行 -> 校验结果。

用法：python -m tests.smoke
"""
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

# Windows GBK 控制台下强制 UTF-8 输出
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smartcar_sim.build.compiler import compile_sources  # noqa: E402
from smartcar_sim.imaging.loader import load_path  # noqa: E402
from smartcar_sim.paths import new_work_dir  # noqa: E402
from smartcar_sim.run.runner import run_sim  # noqa: E402

W, H = 188, 120


def make_track_bmp(path: Path, shift: int = 0) -> None:
    img = np.full((H, W), 200, np.uint8)
    center = W // 2 + shift
    for y in range(H):
        cx = center + int(15 * np.sin(y / 20))
        img[y, max(0, cx - 30): min(W, cx + 30)] = 240
        for xx in (cx - 30, cx + 30):
            if 0 <= xx < W:
                img[y, xx] = 20
    Image.fromarray(img).save(path)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke_"))

    # 1. 生成并加载测试 BMP（单张 + 中文路径）
    cn_dir = tmp / "中文目录"
    cn_dir.mkdir()
    bmp = cn_dir / "赛道.bmp"
    make_track_bmp(bmp)
    fs = load_path(bmp)
    assert fs.count == 1 and fs.w == W and fs.h == H, "加载失败"
    print(f"[1/4] 加载 OK: {fs.count} 帧 {fs.w}x{fs.h}（中文路径）")

    # 2. 编译 demo（含中文文件名的用户源文件）
    demo_src = ROOT / "examples" / "workspace_demo" / "image_demo.c"
    cn_src = cn_dir / "图像处理.c"
    cn_src.write_text(demo_src.read_text(encoding="utf-8"), encoding="utf-8")
    result = compile_sources([cn_src], W, H)
    assert result.ok, f"编译失败:\n{result.raw_output}"
    print(f"[2/4] 编译 OK: {result.exe_path}")

    # 3. 运行
    out_dir = new_work_dir("run")
    input_bin = out_dir / "input.bin"
    fs.pack_input_bin(input_bin)
    rr = run_sim(result.exe_path, input_bin, fs.count, out_dir, W, H)
    assert not rr.crashed, f"运行崩溃: {rr.error_msg}"
    assert rr.frame_count >= 1, "无帧结果"
    print(f"[3/4] 运行 OK: {rr.frame_count} 帧, 耗时 {rr.frames[0].t_us:.0f}us")

    # 4. 校验协议内容
    f0 = rr.frames[0]
    kinds = {c.kind for c in f0.cmds}
    assert "P" in kinds, "缺边线点"
    assert "T" in kinds, "缺文本"
    assert "X" in kinds, "缺十字"
    assert "threshold" in f0.watches, "缺监视量"
    assert rr.processed is not None and rr.processed.shape == (1, H, W), "处理后图像缺失"
    binary_vals = set(np.unique(rr.processed[0]))
    assert binary_vals <= {0, 255}, f"二值化结果异常: {binary_vals}"
    assert any("otsu" in text for _, text in rr.logs), "缺日志"
    print(f"[4/4] 协议 OK: {len(f0.cmds)} 条指令, watches={f0.watches}, "
          f"日志 {len(rr.logs)} 条, 处理后图像已二值化")

    print("\n冒烟测试全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
