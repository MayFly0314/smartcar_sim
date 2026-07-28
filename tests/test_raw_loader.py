"""raw 解析器单元测试（headless，无需硬件）。"""
from __future__ import annotations

import numpy as np
import pytest

from smartcar_sim.imaging.loader import FrameSet, guess_raw_layout, load_raw


def _write(tmp_path, name, data: bytes):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def test_load_raw_basic(tmp_path):
    w, h, n = 4, 3, 5
    frames = [np.full((h, w), i, dtype=np.uint8) for i in range(n)]
    blob = b"".join(f.tobytes() for f in frames)
    fs = load_raw(_write(tmp_path, "a.bin", blob), w, h)
    assert fs.count == n and fs.w == w and fs.h == h
    for i in range(n):
        assert np.all(fs.frames[i] == i)


def test_load_raw_row_major_matches_mcu(tmp_path):
    # MCU 侧 img[H][W] 行优先，reshape(n,h,w) 应逐字节对上
    w, h = 4, 2
    frame = np.arange(w * h, dtype=np.uint8).reshape(h, w)
    fs = load_raw(_write(tmp_path, "b.bin", frame.tobytes()), w, h)
    assert np.array_equal(fs.frames[0], frame)


def test_load_raw_header_bytes(tmp_path):
    w, h, n = 2, 2, 3
    per = w * h
    hdr = 2
    parts = []
    for i in range(n):
        parts.append(bytes([0xAB, i]))  # 每帧 2 字节帧头
        parts.append(np.full((h, w), 100 + i, dtype=np.uint8).tobytes())
    fs = load_raw(_write(tmp_path, "c.bin", b"".join(parts)), w, h, header_bytes=hdr)
    assert fs.count == n
    for i in range(n):
        assert np.all(fs.frames[i] == 100 + i)


def test_load_raw_header_and_footer(tmp_path):
    # 每帧：帧头 + 像素 + 帧尾，用 frame_stride 跳过头尾只取像素
    w, h, n = 2, 2, 3
    hdr, ftr = 2, 3
    parts = []
    for i in range(n):
        parts.append(bytes([0xAA, i]))                              # 帧头
        parts.append(np.full((h, w), 50 + i, dtype=np.uint8).tobytes())  # 像素
        parts.append(b"\xFF\xFF\xFF")                              # 帧尾
    stride = hdr + w * h + ftr
    fs = load_raw(
        _write(tmp_path, "hf.bin", b"".join(parts)), w, h,
        header_bytes=hdr, frame_stride=stride,
    )
    assert fs.count == n
    for i in range(n):
        assert np.all(fs.frames[i] == 50 + i)


def test_load_raw_truncates_remainder(tmp_path):
    w, h = 4, 3
    blob = b"\x00" * (w * h * 2 + 5)  # 2 整帧 + 5 字节余数
    fs = load_raw(_write(tmp_path, "d.bin", blob), w, h)
    assert fs.count == 2


def test_load_raw_insufficient_raises(tmp_path):
    w, h = 100, 100
    with pytest.raises(ValueError):
        load_raw(_write(tmp_path, "e.bin", b"\x00" * 10), w, h)


def test_guess_raw_layout():
    total = 188 * 120 * 5
    got = guess_raw_layout(total)
    assert (188, 120, 5) in got
    # 每个候选都必须整除
    for w, h, n in got:
        assert total % (w * h) == 0 and n == total // (w * h)


def test_from_frames():
    fs = FrameSet.from_frames([np.zeros((3, 4), np.uint8), np.ones((3, 4), np.uint8)])
    assert isinstance(fs, FrameSet) and fs.count == 2 and fs.w == 4 and fs.h == 3
    assert fs.paths == []


def test_from_frames_empty_raises():
    with pytest.raises(ValueError):
        FrameSet.from_frames([])


def test_rotated180():
    # 右下角原点约定：旋转后 [0][0] == 原图右下角
    a = np.arange(12, dtype=np.uint8).reshape(3, 4)
    fs = FrameSet.from_frames([a]).rotated180()
    assert fs.frames[0][0, 0] == a[-1, -1]
    assert fs.frames[0][-1, -1] == a[0, 0]
    assert np.array_equal(fs.frames[0], a[::-1, ::-1])
    # 旋转两次还原
    back = fs.rotated180()
    assert np.array_equal(back.frames[0], a)
