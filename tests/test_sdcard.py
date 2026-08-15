"""SD 卡直读的扇区寻址 / 扫描 / 帧数探测（用假块设备，不需要真卡）。

真卡上实测的两条硬约束在 _FakeDevice 里被强制执行：
  - seek 偏移与 read 长度必须 512 对齐，否则 OSError(22)
  - seek(0, SEEK_END) 不可用（这就是 probe_size 要二分的原因）
"""
from __future__ import annotations

import io

import pytest

from smartcar_sim.imaging import sdcard

SEC = sdcard.SECTOR
MAGIC = b"\xAA\x55"
STRIDE = 5 * SEC


class _FakeDevice(io.RawIOBase):
    """模拟 Windows 裸卷：强制扇区对齐，未写区读作 0xFF，末尾之后读作 0。"""

    def __init__(self, data: bytes, size: int) -> None:
        self._d = data
        self._size = size
        self._pos = 0
        self.reads = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, off, whence=io.SEEK_SET):
        if whence == io.SEEK_END:
            raise OSError(22, "Invalid argument")
        if off % SEC:
            raise OSError(22, "Invalid argument")
        self._pos = off
        return self._pos

    def tell(self) -> int:
        return self._pos

    def readinto(self, b):
        n = len(b)
        if n % SEC or self._pos % SEC:
            raise OSError(22, "Invalid argument")
        if self._pos >= self._size:
            return 0
        self.reads += 1
        n = min(n, self._size - self._pos)
        chunk = self._d[self._pos:self._pos + n]
        b[:n] = chunk + b"\xFF" * (n - len(chunk))
        self._pos += n
        return n


def _card(n_frames: int, start_lba: int = 4, size_sectors: int = 200_000) -> _FakeDevice:
    body = bytearray()
    for i in range(n_frames):
        fr = bytearray(b"\xFF" * STRIDE)
        fr[0:2] = MAGIC
        fr[2:6] = i.to_bytes(4, "little")
        body += fr
    return _FakeDevice(bytes(bytearray(start_lba * SEC) + body), size_sectors * SEC)


def test_read_sectors_alignment_and_length():
    dev = _card(10)
    data = sdcard.read_sectors(dev, 4, 5)
    assert len(data) == STRIDE
    assert bytes(data[:2]) == MAGIC


def test_read_sectors_chunks_large_requests():
    """超过单次 syscall 上限时要正确分片拼接，不能错位。"""
    dev = _card(2000, start_lba=0)
    n = sdcard._MAX_SECTORS_PER_READ * 2 + 7
    data = sdcard.read_sectors(dev, 0, n)
    assert len(data) == n * SEC
    assert bytes(data[:2]) == MAGIC
    assert bytes(data[STRIDE:STRIDE + 2]) == MAGIC


def test_read_sectors_past_end_truncates():
    dev = _card(10, start_lba=0, size_sectors=1000)
    data = sdcard.read_sectors(dev, 995, 20)
    assert len(data) == 5 * SEC          # 只剩 5 个扇区


def test_read_sectors_rejects_bad_args():
    dev = _card(1)
    with pytest.raises(ValueError):
        sdcard.read_sectors(dev, -1, 1)
    with pytest.raises(ValueError):
        sdcard.read_sectors(dev, 0, 0)


@pytest.mark.parametrize("start", [0, 4, 100, 2048])
def test_find_magic_lba(start):
    dev = _card(10, start_lba=start)
    assert sdcard.find_magic_lba(dev, MAGIC, STRIDE, size_bytes=dev._size) == start


def test_find_magic_lba_requires_second_frame():
    """孤立的 magic（图像数据里偶然出现）不能被当成录制起点。"""
    buf = bytearray(b"\x00" * (100 * SEC))
    buf[10 * SEC:10 * SEC + 2] = MAGIC       # 只有一处，下一帧位置没有
    dev = _FakeDevice(bytes(buf), 100 * SEC)
    assert sdcard.find_magic_lba(dev, MAGIC, STRIDE, size_bytes=dev._size) is None


def test_find_magic_lba_start_lba_skips_first_segment():
    dev = _card(10, start_lba=4)
    first = sdcard.find_magic_lba(dev, MAGIC, STRIDE, size_bytes=dev._size)
    assert first == 4
    nxt = first + 10 * STRIDE // SEC
    assert sdcard.find_magic_lba(
        dev, MAGIC, STRIDE, size_bytes=dev._size, start_lba=nxt
    ) is None


def test_find_magic_lba_rejects_unaligned_stride():
    dev = _card(1)
    with pytest.raises(ValueError):
        sdcard.find_magic_lba(dev, MAGIC, STRIDE + 1)


@pytest.mark.parametrize("n", [1, 2, 3, 930, 1024, 1025, 5000])
def test_probe_frame_count_exact(n):
    dev = _card(n)
    assert sdcard.probe_frame_count(dev, 4, MAGIC, STRIDE) == n


def test_probe_frame_count_is_logarithmic():
    """倍增+二分：5000 帧不该读 5000 次。"""
    dev = _card(5000)
    sdcard.probe_frame_count(dev, 4, MAGIC, STRIDE)
    assert dev.reads < 40


def test_probe_frame_count_respects_hard_cap():
    """回归：曾在 hard_cap 处直接返回上限，导致 524289 帧被报成 1048576。"""
    dev = _card(300)
    assert sdcard.probe_frame_count(dev, 4, MAGIC, STRIDE, hard_cap=128) == 128
    assert sdcard.probe_frame_count(dev, 4, MAGIC, STRIDE, hard_cap=1024) == 300


def test_probe_frame_count_zero_when_no_magic():
    dev = _card(5)
    assert sdcard.probe_frame_count(dev, 0, MAGIC, STRIDE) == 0
    assert sdcard.probe_frame_count(dev, 4, b"", STRIDE) == 0


@pytest.mark.parametrize("sectors", [1000, 131_072_000])
def test_probe_size_bisect(sectors):
    """seek(0, END) 在裸卷上不可用，只能二分——含真卡的 62.5GB 规模。"""
    dev = _FakeDevice(b"", sectors * SEC)
    assert sdcard.probe_size(dev) == sectors * SEC


def test_open_readonly_rejects_bad_letter():
    for bad in ("", "CD", "1", "::"):
        with pytest.raises(ValueError):
            sdcard.open_readonly(bad)


def test_explain_oserror_distinguishes_empty_slot_from_denied():
    """空插槽的 ERROR_NOT_READY(21) 被 CPython 映射成 errno 13，
    看着像权限不足其实只是没插卡——filename 为 None 是判据。"""
    empty = PermissionError(13, "Permission denied")
    empty.filename = None
    assert "没插卡" in sdcard.explain_oserror(empty, "D")

    denied = PermissionError(13, "Permission denied")
    denied.filename = r"\\.\C:"
    assert "可移动盘" in sdcard.explain_oserror(denied, "C")


def test_frame_ok_predicate_truncates_stale_frames():
    """核心回归：只看 magic 会把「昨天没跑完的残留帧」当成今天的数据。

    场景：昨天跑 1000 帧未提交，今天只跑 300 帧从头覆盖。
    第 300 帧起读到的是昨天的帧，magic 完全正确、时间轴连续、无任何报错。
    加了 run_id/seq 判据才能正确截断在 300。
    """
    off_run, off_seq = 2, 6          # 紧跟 2 字节 magic，落在第 0 扇区内

    def frame(run_id: int, seq: int) -> bytes:
        fr = bytearray(b"\x00" * STRIDE)
        fr[0:2] = MAGIC
        fr[off_run:off_run + 4] = run_id.to_bytes(4, "little")
        fr[off_seq:off_seq + 4] = seq.to_bytes(4, "little")
        return bytes(fr)

    old_n, new_n = 1000, 300
    body = bytearray()
    for i in range(max(old_n, new_n)):
        body += frame(8, i) if i < new_n else frame(7, i)
    dev = _FakeDevice(bytes(bytearray(4 * SEC) + body), 500_000 * SEC)

    # 只看 magic：被陈旧数据骗过
    assert sdcard.probe_frame_count(dev, 4, MAGIC, STRIDE) == old_n

    def make_ok():
        base: list[int] = []

        def ok(sector0: bytes, idx: int) -> bool:
            run = int.from_bytes(sector0[off_run:off_run + 4], "little")
            seq = int.from_bytes(sector0[off_seq:off_seq + 4], "little")
            if idx == 0 or not base:
                base[:] = [run]
            return run == base[0] and seq == idx

        return ok

    assert sdcard.probe_frame_count(dev, 4, MAGIC, STRIDE, frame_ok=make_ok()) == new_n


def test_frame_ok_default_keeps_old_behaviour():
    """老数据（没有 run_id/seq）必须照样能读——不传谓词就退回只比 magic。"""
    dev = _card(42)
    assert sdcard.probe_frame_count(dev, 4, MAGIC, STRIDE) == 42
    assert sdcard.probe_frame_count(dev, 4, MAGIC, STRIDE, frame_ok=None) == 42


def test_segment_predicate_absent_without_runid_params():
    """方案里没有 run_id/seq 时不能启用判据，否则老数据只会认出 1 帧。"""
    pytest.importorskip("PySide6")
    from smartcar_sim.record.scheme import ParamField, RecordScheme
    from smartcar_sim.views.sdcard_dialog import SdCardDialog

    plain = RecordScheme(magic_hex="AA 55", params=[ParamField("err", "float", "e")],
                         image_mode="none", img_w=186, img_h=70, line_fields=[])
    assert SdCardDialog._segment_predicate(plain) is None

    tagged = RecordScheme(
        magic_hex="AA 55",
        params=[ParamField("run_id", "uint32", "r"), ParamField("seq", "uint32", "s"),
                ParamField("err", "float", "e")],
        image_mode="none", img_w=186, img_h=70, line_fields=[],
    )
    make = SdCardDialog._segment_predicate(tagged)
    assert make is not None
    ok = make()
    good = bytearray(SEC)
    good[0:2] = MAGIC
    good[2:6] = (5).to_bytes(4, "little")
    good[6:10] = (0).to_bytes(4, "little")
    assert ok(bytes(good), 0)
    stale = bytearray(good)
    stale[2:6] = (4).to_bytes(4, "little")     # 不同 run_id = 陈旧帧
    stale[6:10] = (1).to_bytes(4, "little")
    assert not ok(bytes(stale), 1)


def test_legacy_data_reads_as_one_frame_without_fallback():
    """加 run_id 之前录的老数据，用带判据的新方案只会认出 1 帧。

    老数据那片 padding 是 0，于是 run_id=0、seq=0；判据 seq==idx 只在 idx=0 成立。
    这就是 sdcard_dialog 必须做「回落到只比 magic」的原因——否则 930 帧显示成 1 帧。
    """
    off_run, off_seq = 2, 6
    n_frames = 40
    body = bytearray()
    for _ in range(n_frames):
        fr = bytearray(b"\x00" * STRIDE)
        fr[0:2] = MAGIC                      # 只有 magic，没有 run_id/seq
        body += fr
    dev = _FakeDevice(bytes(bytearray(4 * SEC) + body), 100_000 * SEC)

    def make_ok():
        base: list[int] = []

        def ok(sector0: bytes, idx: int) -> bool:
            run = int.from_bytes(sector0[off_run:off_run + 4], "little")
            seq = int.from_bytes(sector0[off_seq:off_seq + 4], "little")
            if idx == 0 or not base:
                base[:] = [run]
            return run == base[0] and seq == idx

        return ok

    assert sdcard.probe_frame_count(dev, 4, MAGIC, STRIDE, frame_ok=make_ok()) == 1
    assert sdcard.probe_frame_count(dev, 4, MAGIC, STRIDE) == n_frames


def test_run_id_must_survive_power_cycle():
    """run_id 掉电归零会让判据完全失效——这是「开机读回上次 run_id」的理由。

    昨天 run=1 跑 1000 帧；今天上电 run 又是 1，只跑 300 帧。
    今天的 seq 0..299 和昨天残留的 seq 300..999 天然接续、run_id 又相同，
    三重判据全部通过 → 和不加 run_id 时一样被骗。
    车端必须开机从卡上读回上次的 run_id 再 +1。
    """
    off_run, off_seq = 2, 6

    def frame(run_id: int, seq: int) -> bytes:
        fr = bytearray(b"\x00" * STRIDE)
        fr[0:2] = MAGIC
        fr[off_run:off_run + 4] = run_id.to_bytes(4, "little")
        fr[off_seq:off_seq + 4] = seq.to_bytes(4, "little")
        return bytes(fr)

    def make_ok():
        base: list[int] = []

        def ok(sector0: bytes, idx: int) -> bool:
            run = int.from_bytes(sector0[off_run:off_run + 4], "little")
            seq = int.from_bytes(sector0[off_seq:off_seq + 4], "little")
            if idx == 0 or not base:
                base[:] = [run]
            return run == base[0] and seq == idx

        return ok

    def card(frames):
        body = bytearray()
        for r, s in frames:
            body += frame(r, s)
        return _FakeDevice(bytes(bytearray(4 * SEC) + body), 500_000 * SEC)

    # 撞号：两次都是 run_id=1 → 判据失效，读出 1000 而不是 300
    collided = card([(1, i) for i in range(1000)])
    assert sdcard.probe_frame_count(
        collided, 4, MAGIC, STRIDE, frame_ok=make_ok()) == 1000

    # 不撞号：今天 run_id=2 → 正确截断在 300
    fixed = card([(2, i) if i < 300 else (1, i) for i in range(1000)])
    assert sdcard.probe_frame_count(
        fixed, 4, MAGIC, STRIDE, frame_ok=make_ok()) == 300
