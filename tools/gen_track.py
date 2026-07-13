"""程序化生成 188×120 模拟摄像头视角的赛道 BMP 帧序列。

用法：python tools/gen_track.py [输出根目录]
默认输出到 examples/tracks/。

生成场景：
  straight/  直道（轻微蛇形抖动）40 帧
  s_curve/   S 弯 60 帧
  cross/     十字路口（边线断开数帧，可触发丢线状态机）50 帧
  single/track.bmp  单张直道图
合成模型：透视走廊（近宽远窄）+ 黑边线 + 灰度路面 + 噪声 + 暗角。
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

W, H = 188, 120
RNG = np.random.default_rng(42)


def synth_frame(center_fn, width_fn, gap_rows=(), noise=6.0) -> np.ndarray:
    """center_fn(row_t) -> 中线x偏移（相对画面中心）；width_fn(row_t) -> 半宽。
    row_t: 0=图像底部(最近) 1=顶部(最远)。gap_rows: 这些行不画边线（十字断口）。
    """
    img = np.full((H, W), 120, np.float32)  # 背景（赛道外）
    for y in range(H):
        t = 1.0 - y / (H - 1)          # 底部 t=0，顶部 t=1
        row = H - 1 - int(t * (H - 1))  # 即 y，直接用 y，但 t 语义清楚
        cx = W / 2 + center_fn(t)
        half = width_fn(t)
        x0 = int(round(cx - half))
        x1 = int(round(cx + half))
        # 路面亮
        xs, xe = max(0, x0), min(W, x1 + 1)
        if xs < xe:
            img[row, xs:xe] = 230
        # 边线黑（2px 近处，1px 远处）
        if row not in gap_rows:
            lw = 2 if t < 0.4 else 1
            for k in range(lw):
                for xx in (x0 + k, x1 - k):
                    if 0 <= xx < W:
                        img[row, xx] = 15
    # 噪声 + 暗角
    img += RNG.normal(0, noise, img.shape)
    yy, xx = np.mgrid[0:H, 0:W]
    d2 = ((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2
    img *= 1.0 - 0.25 * d2
    return np.clip(img, 0, 255).astype(np.uint8)


def perspective_width(t: float) -> float:
    return 62.0 * (1.0 - 0.72 * t)  # 底部半宽62px，顶部约17px


def gen_straight(n=40):
    for i in range(n):
        wob = 3.0 * np.sin(i / 6.0)
        yield synth_frame(lambda t, w=wob: w * (1 - t), perspective_width)


def gen_s_curve(n=60):
    for i in range(n):
        phase = i / n * 2 * np.pi
        curv = 55.0 * np.sin(phase)
        yield synth_frame(
            lambda t, c=curv: c * t * t,  # 远处弯曲更明显
            perspective_width,
        )


def gen_cross(n=50):
    for i in range(n):
        # 第 18~32 帧：十字接近，边线出现大断口且断口随接近下移
        gaps = set()
        if 18 <= i <= 32:
            prog = (i - 18) / 14.0            # 0->1 十字由远及近
            g0 = int(H * (0.75 - 0.55 * prog))
            g1 = int(H * (0.95 - 0.45 * prog))
            gaps = set(range(max(0, g0), min(H, g1)))
        yield synth_frame(lambda t: 0.0, perspective_width, gap_rows=gaps)


def save_seq(frames, folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    n = 0
    for i, f in enumerate(frames):
        Image.fromarray(f).save(folder / f"frame_{i:03d}.bmp")
        n = i + 1
    print(f"{folder.name}: {n} 帧 -> {folder}")


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "examples" / "tracks"
    save_seq(gen_straight(), root / "straight")
    save_seq(gen_s_curve(), root / "s_curve")
    save_seq(gen_cross(), root / "cross")
    single = root / "single"
    single.mkdir(parents=True, exist_ok=True)
    Image.fromarray(next(gen_straight(1))).save(single / "track.bmp")
    print(f"single: 1 帧 -> {single}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
