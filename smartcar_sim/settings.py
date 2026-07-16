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
