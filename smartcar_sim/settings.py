"""QSettings 封装。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from .paths import find_gcc

_ORG = "SmartcarSim"
_APP = "Simulator"


class Settings:
    def __init__(self):
        self._s = QSettings(_ORG, _APP)

    @property
    def img_w(self) -> int:
        return int(self._s.value("img_w", 188))

    @img_w.setter
    def img_w(self, v: int) -> None:
        self._s.setValue("img_w", int(v))

    @property
    def img_h(self) -> int:
        return int(self._s.value("img_h", 120))

    @img_h.setter
    def img_h(self, v: int) -> None:
        self._s.setValue("img_h", int(v))

    @property
    def gcc_path(self) -> str:
        saved = str(self._s.value("gcc_path", "") or "")
        if saved and Path(saved).is_file():
            return saved
        found = find_gcc() or ""
        if found:
            self._s.setValue("gcc_path", found)  # 写回，避免每次编译都扫 PATH
        return found

    @gcc_path.setter
    def gcc_path(self, v: str) -> None:
        self._s.setValue("gcc_path", v)

    @property
    def fps(self) -> int:
        return int(self._s.value("fps", 10))

    @fps.setter
    def fps(self, v: int) -> None:
        self._s.setValue("fps", int(v))

    @property
    def timeout_base(self) -> float:
        return float(self._s.value("timeout_base", 5.0))

    @property
    def last_workspace(self) -> str:
        return str(self._s.value("last_workspace", "") or "")

    @last_workspace.setter
    def last_workspace(self, v: str) -> None:
        self._s.setValue("last_workspace", v)

    @property
    def last_file(self) -> str:
        return str(self._s.value("last_file", "") or "")

    @last_file.setter
    def last_file(self, v: str) -> None:
        self._s.setValue("last_file", v)

    @property
    def last_image(self) -> str:
        return str(self._s.value("last_image", "") or "")

    @last_image.setter
    def last_image(self, v: str) -> None:
        self._s.setValue("last_image", v)

    # ---- 串口图传 ----
    @property
    def serial_port(self) -> str:
        return str(self._s.value("serial_port", "") or "")

    @serial_port.setter
    def serial_port(self, v: str) -> None:
        self._s.setValue("serial_port", v)

    @property
    def serial_baud(self) -> int:
        return int(self._s.value("serial_baud", 115200))

    @serial_baud.setter
    def serial_baud(self, v: int) -> None:
        self._s.setValue("serial_baud", int(v))

    @property
    def serial_protocol(self) -> str:
        return str(self._s.value("serial_protocol", "shanwai") or "shanwai")

    @serial_protocol.setter
    def serial_protocol(self, v: str) -> None:
        self._s.setValue("serial_protocol", v)

    @property
    def serial_header(self) -> str:
        """自定义协议的帧头（hex 字符串，如 "55 AA"；空表示无帧头纯定长）。"""
        return str(self._s.value("serial_header", "") or "")

    @serial_header.setter
    def serial_header(self, v: str) -> None:
        self._s.setValue("serial_header", v)

    @property
    def serial_footer(self) -> str:
        """自定义协议的帧尾（hex 字符串，如 "0D 0A"；空表示无帧尾）。"""
        return str(self._s.value("serial_footer", "") or "")

    @serial_footer.setter
    def serial_footer(self, v: str) -> None:
        self._s.setValue("serial_footer", v)

    @property
    def capture_count(self) -> int:
        return int(self._s.value("capture_count", 30))

    @capture_count.setter
    def capture_count(self, v: int) -> None:
        self._s.setValue("capture_count", int(v))

    @property
    def last_sd_raw(self) -> str:
        return str(self._s.value("last_sd_raw", "") or "")

    @last_sd_raw.setter
    def last_sd_raw(self, v: str) -> None:
        self._s.setValue("last_sd_raw", v)

    # ---- 图像坐标约定（右下角原点）----
    @property
    def load_rot180(self) -> bool:
        """打开本地图像时旋转 180°，使数组符合「右下角=(0,0)」约定。"""
        return bool(self._s.value("load_rot180", False, type=bool))

    @load_rot180.setter
    def load_rot180(self, v: bool) -> None:
        self._s.setValue("load_rot180", bool(v))

    @property
    def view_rot180(self) -> bool:
        """显示时旋转 180°（数据不动，只是正着看）。"""
        return bool(self._s.value("view_rot180", False, type=bool))

    @view_rot180.setter
    def view_rot180(self, v: bool) -> None:
        self._s.setValue("view_rot180", bool(v))
