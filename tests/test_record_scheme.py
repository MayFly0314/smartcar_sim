"""数据记录方案单元测试：布局计算 / 编解码 round-trip / C 代码生成。"""
from __future__ import annotations

import struct

import numpy as np
import pytest

from smartcar_sim.record.scheme import (
    CTYPES,
    ParamField,
    RecordScheme,
    default_scheme,
)


def _pack_frame_like_c(s: RecordScheme, img: np.ndarray, values: list) -> bytes:
    """按生成的 C 代码语义打包一帧（magic + 参数小端 + 1bpp MSB-first + 补零）。"""
    out = bytearray(s.magic())
    for p, v in zip(s.params, values):
        fmt, _size, _np, _c = CTYPES[p.ctype]
        out += struct.pack("<" + fmt, v)
    if s.image_mode == "packed1":
        bits = (img.flatten() > 0).astype(np.uint8)
        out += np.packbits(bits).tobytes()  # np.packbits 也是 MSB-first，与 C 端一致
    elif s.image_mode == "raw8":
        out += img.astype(np.uint8).tobytes()
    out += b"\x00" * (s.stride() - len(out))
    return bytes(out)


def _scheme() -> RecordScheme:
    return RecordScheme(
        magic_hex="AA 55",
        params=[
            ParamField("servo", "int32", "servo_angle"),
            ParamField("err", "float", "error"),
            ParamField("flag", "uint8", "protection_flag"),
        ],
        image_mode="packed1",
        img_w=186,
        img_h=70,
    )


def test_layout_sizes():
    s = _scheme()
    assert s.params_bytes() == 4 + 4 + 1
    assert s.image_bytes() == (186 * 70 + 7) // 8  # 1628
    assert s.payload_bytes() == 2 + 9 + 1628
    assert s.sectors_per_frame() == 4              # 1639 -> 4 扇区
    assert s.stride() == 2048


def test_roundtrip_packed1():
    s = _scheme()
    rng = np.random.default_rng(7)
    imgs = [(rng.random((70, 186)) > 0.5).astype(np.uint8) * 255 for _ in range(3)]
    vals = [[100 + i, 1.5 * i, i % 2] for i in range(3)]
    blob = b"".join(_pack_frame_like_c(s, imgs[i], vals[i]) for i in range(3))

    fs, cols, n = s.decode(np.frombuffer(blob, np.uint8))
    assert n == 3 and fs is not None and fs.count == 3
    for i in range(3):
        assert np.array_equal(fs.frames[i], imgs[i])       # 解压后 0/255 逐像素一致
    assert list(cols[0]) == [100, 101, 102]
    assert cols[1][1] == pytest.approx(1.5)
    assert list(cols[2]) == [0, 1, 0]


def test_roundtrip_raw8():
    s = _scheme()
    s.image_mode = "raw8"
    img = np.arange(186 * 70, dtype=np.uint8).reshape(70, 186)
    blob = _pack_frame_like_c(s, img, [1, 2.0, 3])
    fs, _cols, n = s.decode(np.frombuffer(blob, np.uint8))
    assert n == 1 and np.array_equal(fs.frames[0], img)


def test_params_only():
    s = _scheme()
    s.image_mode = "none"
    blob = b"".join(_pack_frame_like_c(s, np.zeros((1, 1)), [i, float(i), 0]) for i in range(5))
    fs, cols, n = s.decode(np.frombuffer(blob, np.uint8))
    assert fs is None and n == 5
    assert list(cols[0]) == [0, 1, 2, 3, 4]


def test_bad_magic_raises():
    s = _scheme()
    blob = b"\x00" * s.stride()
    with pytest.raises(ValueError, match="帧头不匹配"):
        s.decode(np.frombuffer(blob, np.uint8))


def test_find_frame0_offset_realign():
    s = _scheme()
    frame = _pack_frame_like_c(s, np.zeros((70, 186), np.uint8), [1, 1.0, 1])
    junk = b"\x11\x22\x33\x44\x55"  # 故意含 0x55，验证"下一帧也须对上"的校验
    data = np.frombuffer(junk + frame + frame, np.uint8)
    off = s.find_frame0_offset(data)
    assert off == len(junk)
    fs, _cols, n = s.decode(data, skip=off)
    assert n == 2


def test_json_roundtrip():
    s = _scheme()
    s2 = RecordScheme.from_json(s.to_json())
    assert s2.stride() == s.stride()
    assert [p.name for p in s2.params] == ["servo", "err", "flag"]
    assert s2.image_mode == "packed1"


def test_generate_c_contains_layout():
    s = _scheme()
    code = s.generate_c()
    assert "rec_pack_1bpp" in code
    assert "REC_C_SECTORS   4u" in code
    assert "*p++ = 0xAA; *p++ = 0x55;" in code
    assert "memcpy(p, &v, 4)" in code       # int32/float 参数
    assert s.func_name + "(void)" in code


def test_default_scheme_valid():
    s = default_scheme(186, 70)
    assert s.sectors_per_frame() >= 1
    s.generate_c()  # 不抛即可
