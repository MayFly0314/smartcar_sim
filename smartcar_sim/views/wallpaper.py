"""壁纸宿主：作为中央容器绘制背景图（cover 缩放 + 暗色遮罩），子部件透明区透出壁纸。

限制：Monaco 编辑器与终端是 QtWebEngine（独立渲染进程），无法透明——
它们保持原样；壁纸出现在其余区域（控制台/面板缝隙/时间轴/工具条等）。
图像仿真视图按需求保持纯色底，不透壁纸。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

_BASE = QColor("#1e1e1e")


class WallpaperHost(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pix: QPixmap | None = None
        self._scaled: QPixmap | None = None
        self._dim = 55  # 遮罩百分比 0~90

    def set_wallpaper(self, path: str | None) -> bool:
        """设置壁纸文件；None/加载失败清除。返回是否生效。"""
        if not path or not Path(path).is_file():
            self._pix = self._scaled = None
            self.update()
            return False
        pix = QPixmap(path)
        if pix.isNull():
            self._pix = self._scaled = None
            self.update()
            return False
        self._pix = pix
        self._scaled = None
        self.update()
        return True

    def has_wallpaper(self) -> bool:
        return self._pix is not None

    def set_dim(self, percent: int) -> None:
        self._dim = max(0, min(90, int(percent)))
        self.update()

    def resizeEvent(self, ev) -> None:  # noqa: N802
        self._scaled = None  # 尺寸变了，重算 cover 缩放
        super().resizeEvent(ev)

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), _BASE)
        if self._pix is not None:
            if self._scaled is None or self._scaled.size() != self.size():
                self._scaled = self._pix.scaled(
                    self.size(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
            off = QPoint(
                (self.width() - self._scaled.width()) // 2,
                (self.height() - self._scaled.height()) // 2,
            )
            p.drawPixmap(off, self._scaled)
            p.fillRect(self.rect(), QColor(18, 18, 18, int(self._dim * 255 / 100)))
        p.end()
