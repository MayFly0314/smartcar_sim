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
