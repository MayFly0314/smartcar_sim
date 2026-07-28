"""串口帧协议单元测试（纯字节逻辑，无需 pyserial / 硬件）。"""
from __future__ import annotations

import numpy as np
import pytest

from smartcar_sim.link.serial_link import (
    CustomRawProtocol,
    SeekfreeAssistantProtocol,
    ShanwaiProtocol,
    make_protocol,
    parse_hex,
)

_HEAD_A = b"\x00\xff\x01\x01"


def _shanwai_stream(frames: list[np.ndarray]) -> bytes:
    return b"".join(_HEAD_A + f.tobytes() for f in frames)


def test_shanwai_single_frame():
    w, h = 4, 3
    frame = np.arange(w * h, dtype=np.uint8).reshape(h, w)
    proto = ShanwaiProtocol()
    buf = bytearray(_shanwai_stream([frame]))
    out = list(proto.feed(buf, w, h))
    assert len(out) == 1
    assert np.array_equal(out[0], frame)
    assert len(buf) == 0  # 全部消费


def test_shanwai_partial_reads_accumulate():
    w, h = 4, 3
    frame = np.arange(w * h, dtype=np.uint8).reshape(h, w)
    stream = _shanwai_stream([frame])
    proto = ShanwaiProtocol()
    buf = bytearray()
    out = []
    # 每次喂 3 字节，模拟 read() 的碎片返回
    for i in range(0, len(stream), 3):
        buf += stream[i : i + 3]
        out += list(proto.feed(buf, w, h))
    assert len(out) == 1 and np.array_equal(out[0], frame)


def test_shanwai_back_to_back():
    w, h = 4, 3
    frames = [np.full((h, w), i, dtype=np.uint8) for i in (7, 8, 9)]
    proto = ShanwaiProtocol()
    buf = bytearray(_shanwai_stream(frames))
    out = list(proto.feed(buf, w, h))
    assert len(out) == 3
    for got, exp in zip(out, frames):
        assert np.array_equal(got, exp)


def test_shanwai_resync_after_garbage():
    w, h = 4, 3
    frame = np.full((h, w), 42, dtype=np.uint8)
    proto = ShanwaiProtocol()
    buf = bytearray(b"\x11\x22\x33garbage" + _HEAD_A + frame.tobytes())
    out = list(proto.feed(buf, w, h))
    assert len(out) == 1 and np.array_equal(out[0], frame)


def test_shanwai_pixels_containing_header_not_missplit():
    # 关键：像素里天然出现 00 FF 01 01 时，按定长切帧不能误判为新帧头
    w, h = 4, 3  # 12 像素
    px = bytearray(range(12))
    px[4:8] = _HEAD_A  # 帧内嵌入帧头字节
    frame = np.frombuffer(bytes(px), np.uint8).reshape(h, w)
    proto = ShanwaiProtocol()
    buf = bytearray(_shanwai_stream([frame, frame]))
    out = list(proto.feed(buf, w, h))
    assert len(out) == 2
    assert np.array_equal(out[0], frame) and np.array_equal(out[1], frame)


def test_shanwai_leftover_partial_stays():
    w, h = 4, 3
    frame = np.zeros((h, w), np.uint8)
    proto = ShanwaiProtocol()
    stream = _shanwai_stream([frame])
    buf = bytearray(stream[:-2])  # 少 2 字节
    out = list(proto.feed(buf, w, h))
    assert out == []
    buf += stream[-2:]  # 补齐
    out = list(proto.feed(buf, w, h))
    assert len(out) == 1 and np.array_equal(out[0], frame)


def _seekfree_stream(frame: np.ndarray) -> bytes:
    h, w = frame.shape
    ctype = 2 << 5  # 灰度 = 0x40
    header = bytes([0xAA, 0x02, ctype, 0x08, w & 0xFF, w >> 8, h & 0xFF, h >> 8])
    return header + frame.tobytes()


def test_seekfree_parses_dims_from_stream():
    w, h = 4, 3
    frame = np.arange(w * h, dtype=np.uint8).reshape(h, w)
    proto = SeekfreeAssistantProtocol()
    buf = bytearray(_seekfree_stream(frame))
    # fallback 尺寸故意给错，协议应从帧头自解析
    out = list(proto.feed(buf, 99, 99))
    assert len(out) == 1 and out[0].shape == (h, w)
    assert np.array_equal(out[0], frame)


def test_seekfree_188x120_header_bytes():
    # 灰度 188×120 帧头应为 AA 02 40 08 BC 00 78 00
    frame = np.zeros((120, 188), np.uint8)
    stream = _seekfree_stream(frame)
    assert stream[:8] == bytes([0xAA, 0x02, 0x40, 0x08, 0xBC, 0x00, 0x78, 0x00])


def test_custom_with_header():
    w, h = 2, 2
    head = b"\x55\xAA"
    frames = [np.full((h, w), i, dtype=np.uint8) for i in (1, 2)]
    proto = CustomRawProtocol(head)
    buf = bytearray(b"".join(head + f.tobytes() for f in frames))
    out = list(proto.feed(buf, w, h))
    assert len(out) == 2 and np.array_equal(out[1], frames[1])


def test_custom_no_header_pure_fixed_length():
    w, h = 2, 2
    frames = [np.full((h, w), i, dtype=np.uint8) for i in (3, 4)]
    proto = CustomRawProtocol(b"")
    buf = bytearray(b"".join(f.tobytes() for f in frames))
    out = list(proto.feed(buf, w, h))
    assert len(out) == 2
    assert np.array_equal(out[0], frames[0]) and np.array_equal(out[1], frames[1])


def test_custom_header_and_footer():
    # 帧头 + 定长像素 + 帧尾：完整一帧
    w, h = 2, 2
    head, tail = b"\xAA\xBB", b"\x0D\x0A"
    frames = [np.full((h, w), i, dtype=np.uint8) for i in (5, 6)]
    proto = CustomRawProtocol(head, tail)
    buf = bytearray(b"".join(head + f.tobytes() + tail for f in frames))
    out = list(proto.feed(buf, w, h))
    assert len(out) == 2
    assert np.array_equal(out[0], frames[0]) and np.array_equal(out[1], frames[1])
    assert len(buf) == 0


def test_custom_footer_mismatch_resync():
    # 帧尾校验：坏帧尾判失步 → 按帧头重扫，下一帧完好应正常交付
    w, h = 2, 2
    head, tail = b"\xAA\xBB", b"\xEE\xEF"
    good = np.full((h, w), 9, dtype=np.uint8)
    bad = head + bytes([1, 2, 3, 4]) + b"\x00\x00"  # 帧尾损坏
    proto = CustomRawProtocol(head, tail)
    buf = bytearray(bad + head + good.tobytes() + tail)
    out = list(proto.feed(buf, w, h))
    assert len(out) == 1 and np.array_equal(out[0], good)


def test_custom_footer_only_delimiter():
    # 无帧头、仅帧尾分隔
    w, h = 2, 2
    tail = b"\xFF\xFE"
    frames = [np.full((h, w), i, dtype=np.uint8) for i in (3, 4)]
    proto = CustomRawProtocol(b"", tail)
    buf = bytearray(b"".join(f.tobytes() + tail for f in frames))
    out = list(proto.feed(buf, w, h))
    assert len(out) == 2
    assert np.array_equal(out[0], frames[0]) and np.array_equal(out[1], frames[1])


def test_custom_header_footer_partial_reads():
    # 头+像素+尾 分多次碎片喂入也能拼回
    w, h = 4, 3
    head, tail = b"\x55\xAA", b"\x0D\x0A"
    frame = np.arange(w * h, dtype=np.uint8).reshape(h, w)
    stream = head + frame.tobytes() + tail
    proto = CustomRawProtocol(head, tail)
    buf = bytearray()
    out = []
    for i in range(0, len(stream), 5):
        buf += stream[i : i + 5]
        out += list(proto.feed(buf, w, h))
    assert len(out) == 1 and np.array_equal(out[0], frame)


def test_make_protocol_keys():
    assert isinstance(make_protocol("shanwai"), ShanwaiProtocol)
    assert isinstance(make_protocol("seekfree"), SeekfreeAssistantProtocol)
    assert isinstance(make_protocol("custom", "55 AA"), CustomRawProtocol)
    assert isinstance(make_protocol("unknown"), ShanwaiProtocol)  # 兜底


def test_parse_hex():
    assert parse_hex("55 AA") == b"\x55\xaa"
    assert parse_hex("00ff0101") == _HEAD_A
    assert parse_hex("0x55,0xAA") == b"\x55\xaa"
    assert parse_hex("") == b""
    with pytest.raises(ValueError):
        parse_hex("ABC")  # 奇数位
