import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from smartcar_sim.imaging.loader import load_folder, load_single  # noqa: E402


def test_load_8bit_gray(tmp_path):
    arr = np.arange(256, dtype=np.uint8).reshape(16, 16)
    p = tmp_path / "g.bmp"
    Image.fromarray(arr, mode="L").save(p)
    fs = load_single(p)
    assert fs.count == 1 and fs.w == 16 and fs.h == 16
    assert np.array_equal(fs.frames[0], arr)


def test_load_1bit_binary(tmp_path):
    arr = np.zeros((8, 8), np.uint8)
    arr[::2] = 1
    p = tmp_path / "b.bmp"
    Image.fromarray(arr * 255).convert("1").save(p)
    fs = load_single(p)
    vals = set(np.unique(fs.frames[0]))
    assert vals <= {0, 255}, f"1位图应归一化为0/255, got {vals}"


def test_folder_natural_sort(tmp_path):
    for i in (1, 2, 10, 11):
        Image.fromarray(np.full((4, 4), i, np.uint8)).save(tmp_path / f"frame_{i}.bmp")
    fs = load_folder(tmp_path)
    order = [int(p.stem.split("_")[1]) for p in fs.paths]
    assert order == [1, 2, 10, 11], f"自然排序错误: {order}"


def test_folder_mixed_size_resized(tmp_path):
    Image.fromarray(np.zeros((10, 10), np.uint8)).save(tmp_path / "a1.bmp")
    Image.fromarray(np.zeros((5, 5), np.uint8)).save(tmp_path / "a2.bmp")
    fs = load_folder(tmp_path)
    assert fs.frames.shape == (2, 10, 10), "尺寸不符的帧应缩放到基准"


def test_pack_input_bin(tmp_path):
    arr = np.arange(2 * 4 * 3, dtype=np.uint8).reshape(2, 4, 3)
    Image.fromarray(arr[0]).save(tmp_path / "x1.bmp")
    Image.fromarray(arr[1]).save(tmp_path / "x2.bmp")
    fs = load_folder(tmp_path)
    dst = tmp_path / "in.bin"
    fs.pack_input_bin(dst)
    raw = np.fromfile(dst, dtype=np.uint8)
    assert raw.size == 2 * 4 * 3
