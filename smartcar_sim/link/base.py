"""串口/蓝牙实时图传抽象基类（占位，M3 实现）。

未来：从串口/蓝牙接收 188×120 图像帧，实时喂给 image_process 并显示叠加，
实现"在线仿真"——车在跑，上位机同步显示算法看到的边线。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class ImageLink(ABC):
    """实时图像链路接口。实现类：SerialLink / BluetoothLink。"""

    @abstractmethod
    def open(self, config: dict) -> None:
        ...

    @abstractmethod
    def close(self) -> None:
        ...

    @abstractmethod
    def read_frame(self) -> np.ndarray | None:
        """返回一帧 (H, W) uint8 灰度，无数据返回 None。"""
        ...
