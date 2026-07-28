"""图像加载与归一化：BMP/PNG -> 8 位灰度帧序列。

支持：
- 8 位灰度 BMP（总钻风原图）
- 1 位/已二值化黑白 BMP（归一化为 0/255）
- 文件夹批量加载（自然排序）
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

_IMG_EXTS = {".bmp", ".png", ".jpg", ".jpeg", ".pgm"}


def _natural_key(p: Path):
    """自然排序：frame_2 < frame_10。"""
    parts = re.split(r"(\d+)", p.name)
    return [int(t) if t.isdigit() else t.lower() for t in parts]


def _load_gray(path: Path) -> np.ndarray:
    """读入任意支持格式，返回 uint8 灰度 (H, W)。

    1 位图（mode '1'）按黑白归一化到 0/255。
    """
    img = Image.open(path)
    if img.mode == "1":
        arr = np.asarray(img.convert("L"), dtype=np.uint8)
        # convert('L') 已把 1 位映射为 0/255
        return arr
    if img.mode != "L":
        img = img.convert("L")
    return np.asarray(img, dtype=np.uint8)


@dataclass
class FrameSet:
    """一组同尺寸灰度帧。"""

    frames: np.ndarray  # (N, H, W) uint8
    paths: list[Path]

    @property
    def count(self) -> int:
        return int(self.frames.shape[0])

    @property
    def h(self) -> int:
        return int(self.frames.shape[1])

    @property
    def w(self) -> int:
        return int(self.frames.shape[2])

    def pack_input_bin(self, dst: Path) -> None:
        """按帧顺序写出连续 uint8 供 sim.exe 读取。"""
        self.frames.astype(np.uint8, copy=False).tofile(dst)

    @classmethod
    def from_frames(cls, frames: list[np.ndarray]) -> "FrameSet":
        """从内存中的 (H, W) uint8 帧列表构造（串口抓取 / raw 解析共用）。

        paths 全仓库无消费方，内存来源留空即可。
        """
        if not frames:
            raise ValueError("帧列表为空")
        arr = np.stack([np.ascontiguousarray(f, dtype=np.uint8) for f in frames])
        return cls(frames=arr, paths=[])

    def rotated180(self) -> "FrameSet":
        """整组帧旋转 180°（右下角原点约定：正图旋转后 [0][0]=原图右下角）。"""
        return FrameSet(
            frames=np.ascontiguousarray(self.frames[:, ::-1, ::-1]), paths=self.paths
        )


def load_single(path: str | Path) -> FrameSet:
    p = Path(path)
    arr = _load_gray(p)
    return FrameSet(frames=arr[None, ...], paths=[p])


def load_folder(path: str | Path) -> FrameSet:
    """加载文件夹内所有图片为帧序列（自然排序）。

    以第一帧尺寸为基准；尺寸不符的帧会被最近邻缩放到基准尺寸。
    """
    folder = Path(path)
    files = sorted(
        (p for p in folder.iterdir() if p.suffix.lower() in _IMG_EXTS),
        key=_natural_key,
    )
    if not files:
        raise ValueError(f"文件夹内没有支持的图片：{folder}")

    first = _load_gray(files[0])
    h, w = first.shape
    out = [first]
    for f in files[1:]:
        a = _load_gray(f)
        if a.shape != (h, w):
            a = np.asarray(
                Image.fromarray(a).resize((w, h), Image.NEAREST), dtype=np.uint8
            )
        out.append(a)
    return FrameSet(frames=np.stack(out), paths=files)


def load_path(path: str | Path) -> FrameSet:
    """自动判断：文件 -> 单帧；文件夹 -> 序列。"""
    p = Path(path)
    return load_folder(p) if p.is_dir() else load_single(p)


# ---- SD 卡原始数据（raw）解析 ----
# 单片机把摄像头灰度帧写进 SD 卡最常见的形式是"多帧 uint8 连续拼接"的裸二进制，
# 与本仿真器喂给 sim.exe 的 input.bin 完全同构，因此可直接 np.fromfile + reshape 还原。

_RAW_CANDIDATES = ((188, 120), (160, 120), (80, 60), (94, 60), (320, 240))


def load_raw(
    path: str | Path,
    w: int,
    h: int,
    header_bytes: int = 0,
    frame_stride: int | None = None,
) -> FrameSet:
    """把单个 raw 文件按 (n, h, w) 还原成帧序列。

    - w, h：单帧灰度分辨率（MCU 侧 img[H][W] 行优先，reshape 直接对上，无需转置）。
    - header_bytes：每帧数据前的固定帧头字节数（无则 0），解析时跳过。
    - frame_stride：每帧总步长，默认 header_bytes + w*h；当每帧尾部另有填充/校验时可显式给更大值。

    末尾不足一整帧的余数丢弃。字节数不足一帧时抛 ValueError。
    """
    if w <= 0 or h <= 0:
        raise ValueError("分辨率必须为正")
    per = w * h
    stride = int(frame_stride) if frame_stride else header_bytes + per
    if stride < header_bytes + per:
        raise ValueError(f"帧步长 {stride} 小于 帧头 {header_bytes} + 像素 {per}")
    data = np.fromfile(str(path), dtype=np.uint8)
    n = data.size // stride
    if n == 0:
        raise ValueError(
            f"字节数 {data.size} 不足一帧（每帧需 {stride} 字节 = {header_bytes} 帧头 + {w}×{h}）"
        )
    body = data[: n * stride].reshape(n, stride)[:, header_bytes : header_bytes + per]
    return FrameSet(frames=body.reshape(n, h, w), paths=[])


def guess_raw_layout(
    total: int, candidates: tuple[tuple[int, int], ...] = _RAW_CANDIDATES
) -> list[tuple[int, int, int]]:
    """从总字节数猜测可能的 (w, h, 帧数)：能整除且帧数≥1 的候选分辨率。

    宽度猜错时画面会斜向撕裂，配合 UI 即时预览可一眼判定选哪个。
    """
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int, int]] = []
    for w, h in candidates:
        if (w, h) in seen:
            continue
        seen.add((w, h))
        per = w * h
        if per > 0 and total % per == 0 and total // per >= 1:
            out.append((w, h, total // per))
    return out
