"""串口图传：帧协议解析 + 后台接收线程。

对接中国大学生智能汽车竞赛生态里两套并存的摄像头灰度图串口协议（字节格式对照
逐飞官方开源库源码逐字节确认），外加一个"自定义 raw"保底协议覆盖自改固件：

  协议 A 山外/逐飞早期库(seekfree_sendimg_03x)：帧头 00 FF 01 01 + uint8[W*H] 逐行灰度
  协议 B 逐飞助手：AA 02 <camera_type> 08 <W_LE16> <H_LE16> + 像素（自描述宽高/像素格式）
  协议 C 自定义：帧头(可空)与 W×H 全部可配

设计要点：
- feed(buf, w, h) 是消费型生成器——把 buf(bytearray) 里所有已完整的帧 yield 出来，
  半帧字节留在 buf 里等下次。接收线程一次 read 到的字节可能是半帧、也可能是多帧。
- 按 header 重同步、**按定长切帧**（不按下一个 header 切——像素里可能天然出现帧头字节）。
"""
from __future__ import annotations

from abc import abstractmethod

import numpy as np

from .base import ImageLink

try:  # pyserial 为可选依赖：没装也不该让整个程序崩，只在真正用串口时提示
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - 取决于运行环境
    serial = None  # type: ignore[assignment]
    list_ports = None  # type: ignore[assignment]

HAVE_PYSERIAL = serial is not None

_SYNC = 0
_PAYLOAD = 1
_MAX_PAYLOAD = 8_000_000  # 拒绝明显不合理的自描述尺寸（防错位后把垃圾当巨帧）


def parse_hex(text: str) -> bytes:
    """把 "00 FF 01 01" / "00ff0101" / "0x00,0xFF" 解析成 bytes；空串返回 b""。"""
    if not text:
        return b""
    cleaned = (
        text.replace(",", " ").replace("0x", " ").replace("0X", " ").split()
    )
    joined = "".join(cleaned) if cleaned else text.replace(" ", "")
    if len(joined) % 2 != 0:
        raise ValueError(f"帧头 hex 位数应为偶数：{text!r}")
    return bytes.fromhex(joined)


# ---- 协议 ----
class FrameProtocol:
    """帧协议策略。子类实现 feed()。"""

    name = "protocol"
    needs_size = True  # True=宽高由 UI 给；False=帧内自带

    @abstractmethod
    def feed(self, buf: bytearray, w: int, h: int):
        """消费 buf 中所有完整帧并 yield (H, W) uint8；未完成字节留在 buf。"""
        raise NotImplementedError

    def reset(self) -> None:
        """清接收状态（重连时调）。"""


class _HeaderFixedProtocol(FrameProtocol):
    """帧头(可空) + 定长 W*H 灰度像素 + 帧尾(可空)。协议 A / 自定义 raw 的共同实现。

    帧尾若配置：收满 W*H 像素后校验紧跟的字节 == 帧尾，符合才交帧（并消费掉帧尾）；
    不符判失步——有帧头则回退按帧头重扫，无帧头则按帧尾重对齐。比只认帧头更抗错位。
    """

    header = b""
    footer = b""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        # 无帧头时纯定长流，直接进 PAYLOAD
        self._state = _SYNC if self.header else _PAYLOAD

    def feed(self, buf: bytearray, w: int, h: int):
        size = w * h
        if size <= 0:
            return
        hdr, ftr = self.header, self.footer
        flen = len(ftr)
        while True:
            if hdr and self._state == _SYNC:
                idx = buf.find(hdr)
                if idx < 0:  # 没找到帧头：只保留尾部可能的半个帧头，其余丢弃（防膨胀）
                    keep = len(hdr) - 1
                    if len(buf) > keep:
                        del buf[: len(buf) - keep]
                    return
                del buf[: idx + len(hdr)]
                self._state = _PAYLOAD
            else:
                need = size + flen
                if len(buf) < need:
                    return
                if flen and bytes(buf[size : size + flen]) != ftr:
                    # 帧尾不匹配 → 失步，恢复
                    if hdr:
                        del buf[:1]            # 跳过这个（伪）帧头字节，回 SYNC 前扫下一个真帧头
                        self._state = _SYNC
                    else:
                        pos = buf.find(ftr, 1)  # 无帧头：按帧尾重新对齐到下一个边界
                        if pos < 0:
                            keep = flen - 1
                            if keep > 0 and len(buf) > keep:
                                del buf[: len(buf) - keep]
                            else:
                                buf.clear()
                            return
                        del buf[: pos + flen]
                    continue
                # 每帧拷成独立不可变副本，避免被后续 del/覆盖影响
                frame = np.frombuffer(bytes(buf[:size]), dtype=np.uint8).reshape(h, w).copy()
                del buf[:need]
                if hdr:
                    self._state = _SYNC
                yield frame


class ShanwaiProtocol(_HeaderFixedProtocol):
    """协议 A：帧头 00 FF 01 01 + 逐行灰度。宽高不在帧里，由 UI 提供。"""

    name = "shanwai"
    needs_size = True
    header = b"\x00\xff\x01\x01"


class CustomRawProtocol(_HeaderFixedProtocol):
    """协议 C：帧头 / 帧尾 hex 均可配（可空），W×H 由 UI 提供。

    - 只填帧头：帧头 + 定长像素（帧尾靠重同步自动跳过）。
    - 帧头 + 帧尾：收满像素后校验帧尾，最稳。
    - 都不填：纯定长像素流。
    - 只填帧尾：像素 + 帧尾分隔。
    """

    name = "custom"
    needs_size = True

    def __init__(self, header: bytes = b"", footer: bytes = b"") -> None:
        self.header = header
        self.footer = footer
        super().__init__()


class SeekfreeAssistantProtocol(FrameProtocol):
    """协议 B：逐飞助手自描述协议。

    帧头 8 字节：AA │ function=02 │ camera_type │ length=08 │ W(LE16) │ H(LE16)，随后是像素。
    camera_type = (type<<5) | (no_img<<4) | boundary_num；
      type: 灰度=2 → payload W*H；二值=1 → W*H/8；RGB565=3 → W*H*2。
    （灰度 188×120 帧头 = AA 02 40 08 BC 00 78 00）
    """

    name = "seekfree"
    needs_size = False  # 宽高解析自帧头；UI 的 W/H 仅作 fallback
    _HDR = 8

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._pending: tuple[int, int, int, int] | None = None  # (w, h, type, payload)

    @staticmethod
    def _payload_size(camera_type: int, w: int, h: int) -> tuple[int, int]:
        """返回 (像素格式 type, payload 字节数)。"""
        t = (camera_type >> 5) & 0x07
        per = w * h
        if t == 1:  # 二值：1bit/像素
            return t, (per + 7) // 8
        if t == 3:  # RGB565：2字节/像素
            return t, per * 2
        return 2, per  # 灰度（默认）

    @staticmethod
    def _to_gray(raw: bytes, w: int, h: int, t: int) -> np.ndarray | None:
        per = w * h
        if t == 1:  # 二值 → 0/255
            bits = np.unpackbits(np.frombuffer(raw, dtype=np.uint8))
            if bits.size < per:
                return None
            return (bits[:per].reshape(h, w) * 255).astype(np.uint8)
        if t == 3:  # RGB565 LE → 亮度
            px = np.frombuffer(raw, dtype="<u2")
            if px.size < per:
                return None
            px = px[:per]
            r = ((px >> 11) & 0x1F).astype(np.uint16) * 255 // 31
            g = ((px >> 5) & 0x3F).astype(np.uint16) * 255 // 63
            b = (px & 0x1F).astype(np.uint16) * 255 // 31
            lum = (r * 299 + g * 587 + b * 114) // 1000
            return lum.reshape(h, w).astype(np.uint8)
        # 灰度
        if len(raw) < per:
            return None
        return np.frombuffer(raw[:per], dtype=np.uint8).reshape(h, w).copy()

    def feed(self, buf: bytearray, w_fallback: int, h_fallback: int):
        while True:
            if self._pending is None:
                idx = buf.find(b"\xaa\x02")  # 图像包：magic 0xAA + function 0x02
                if idx < 0:
                    if len(buf) > 1:  # 只保留末尾一个可能的 0xAA
                        del buf[: len(buf) - 1]
                    return
                if idx > 0:
                    del buf[:idx]
                if len(buf) < self._HDR:
                    return  # 帧头未收全
                camera_type = buf[2]
                w = buf[4] | (buf[5] << 8)
                h = buf[6] | (buf[7] << 8)
                if w <= 0 or h <= 0:
                    del buf[:1]  # 伪帧头，跳过这个 0xAA 重扫
                    continue
                _t, payload = self._payload_size(camera_type, w, h)
                if payload <= 0 or payload > _MAX_PAYLOAD:
                    del buf[:1]
                    continue
                self._pending = (w, h, camera_type, payload)
                del buf[: self._HDR]
            else:
                w, h, camera_type, payload = self._pending
                if len(buf) < payload:
                    return
                raw = bytes(buf[:payload])
                del buf[:payload]
                self._pending = None
                frame = self._to_gray(raw, w, h, camera_type)
                if frame is not None:
                    yield frame


# UI 下拉用：(key, 显示名, 是否需要 UI 给宽高)
PROTOCOL_CHOICES: list[tuple[str, str, bool]] = [
    ("shanwai", "山外/逐飞 4字节头 (00 FF 01 01)", True),
    ("seekfree", "逐飞助手 (0xAA 自描述)", False),
    ("custom", "自定义 raw (可配帧头)", True),
]


def make_protocol(key: str, header_hex: str = "", footer_hex: str = "") -> FrameProtocol:
    if key == "seekfree":
        return SeekfreeAssistantProtocol()
    if key == "custom":
        return CustomRawProtocol(parse_hex(header_hex), parse_hex(footer_hex))
    return ShanwaiProtocol()


def enumerate_ports() -> list[tuple[str, str]]:
    """返回 [(device, description)]，如 [("COM7", "USB-SERIAL CH340")]。"""
    if list_ports is None:
        return []
    out = []
    for p in list_ports.comports():
        out.append((p.device, f"{p.device} — {p.description}" if p.description else p.device))
    return out


# ---- 后台接收线程 ----
try:  # QtCore 一定装了（PySide6 是硬依赖），但把 worker 的导入也隔离清晰些
    from PySide6.QtCore import QObject, Signal, Slot
except ImportError:  # pragma: no cover
    QObject = object  # type: ignore[assignment,misc]

    def Signal(*_a, **_k):  # type: ignore[misc]
        return None

    def Slot(*_a, **_k):  # type: ignore[misc]
        def _d(f):
            return f

        return _d


class SerialWorker(QObject):
    """常驻接收线程：读串口字节 → 喂协议 → 逐帧 emit。moveToThread 到 QThread 使用。"""

    frameReady = Signal(object)   # (H, W) uint8
    opened = Signal(str)
    closed = Signal()
    error = Signal(str)

    def __init__(self, port: str, baud: int, protocol: FrameProtocol, w: int, h: int) -> None:
        super().__init__()
        self._port = port
        self._baud = int(baud)
        self._proto = protocol
        self._w = int(w)
        self._h = int(h)
        self._ser = None
        self._stop = False

    @Slot()
    def run(self) -> None:
        if serial is None:
            self.error.emit("未安装 pyserial（请先 pip install pyserial）")
            self.closed.emit()
            return
        try:
            ser = serial.Serial()
            ser.port = self._port
            ser.baudrate = self._baud
            ser.timeout = 0.15
            ser.open()
            self._ser = ser
            try:
                ser.reset_input_buffer()  # 丢开机残留的半帧
            except Exception:  # noqa: BLE001
                pass
        except Exception as e:  # noqa: BLE001
            self.error.emit(f"打开 {self._port} 失败：{e}")
            self.closed.emit()
            return

        self.opened.emit(f"{self._port} @ {self._baud}")
        buf = bytearray()
        try:
            while not self._stop:
                try:
                    chunk = self._ser.read(4096)
                except Exception as e:  # noqa: BLE001 — 拔线/断开
                    if not self._stop:
                        self.error.emit(f"读取错误（串口断开？）：{e}")
                    break
                if not chunk:
                    continue
                buf += chunk
                try:
                    for frame in self._proto.feed(buf, self._w, self._h):
                        self.frameReady.emit(frame)
                except Exception as e:  # noqa: BLE001 — 解析异常不该弄死线程
                    self.error.emit(f"解析错误：{e}")
                    buf.clear()
        finally:
            try:
                if self._ser is not None and self._ser.is_open:
                    self._ser.close()
            except Exception:  # noqa: BLE001
                pass
            self.closed.emit()

    def stop(self) -> None:
        """由主线程调：置标志并打断阻塞 read（绝不 terminate 线程）。"""
        self._stop = True
        try:
            if self._ser is not None:
                self._ser.cancel_read()
        except Exception:  # noqa: BLE001
            pass


class SerialLink(ImageLink):
    """ImageLink 的串口实现——兑现 base.py 注释承诺，给同步取帧场景留口。

    对话框的实时预览走 SerialWorker(信号)；此类提供阻塞式 read_frame 供未来在线仿真同步循环用。
    """

    def __init__(self) -> None:
        self._ser = None
        self._proto: FrameProtocol | None = None
        self._w = 0
        self._h = 0
        self._buf = bytearray()

    def open(self, config: dict) -> None:
        if serial is None:
            raise RuntimeError("未安装 pyserial")
        self._proto = make_protocol(
            config.get("protocol", "shanwai"),
            config.get("header", ""),
            config.get("footer", ""),
        )
        self._w = int(config["w"])
        self._h = int(config["h"])
        self._buf = bytearray()
        ser = serial.Serial()
        ser.port = config["port"]
        ser.baudrate = int(config.get("baud", 115200))
        ser.timeout = float(config.get("timeout", 0.15))
        ser.open()
        try:
            ser.reset_input_buffer()
        except Exception:  # noqa: BLE001
            pass
        self._ser = ser

    def close(self) -> None:
        try:
            if self._ser is not None and self._ser.is_open:
                self._ser.close()
        except Exception:  # noqa: BLE001
            pass
        self._ser = None

    def read_frame(self) -> np.ndarray | None:
        if self._ser is None or self._proto is None:
            return None
        chunk = self._ser.read(4096)
        if chunk:
            self._buf += chunk
        for frame in self._proto.feed(self._buf, self._w, self._h):
            return frame  # 一次返回一帧；无完整帧返回 None
        return None
