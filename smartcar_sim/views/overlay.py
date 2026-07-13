"""绘图指令 -> 叠加层 QImage / 文本项。

叠加层与底图同尺寸（H×W），一个绘图点严格对应一个像素格；
与底图一起最近邻放大，得到像素级叠加观感。
文本例外：在小图里嵌字看不清，交由 image_view 用 ItemIgnoresTransformations 渲染。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen

from ..run.protocol import DrawCmd, FrameResult


def _qcolor(rgb: int) -> QColor:
    return QColor((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF)


def render_overlay(frame: FrameResult, w: int, h: int) -> QImage:
    """把一帧的绘图指令渲染到透明 RGBA 图（不含文本）。"""
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    for c in frame.cmds:
        col = _qcolor(c.color)
        if c.kind == "P":
            x, y = c.args
            img.setPixelColor(x, y, col) if 0 <= x < w and 0 <= y < h else None
        elif c.kind == "L":
            p.setPen(QPen(col))
            x0, y0, x1, y1 = c.args
            p.drawLine(x0, y0, x1, y1)
        elif c.kind == "R":
            p.setPen(QPen(col))
            x, y, rw, rh = c.args
            p.drawRect(x, y, rw, rh)
        elif c.kind == "C":
            p.setPen(QPen(col))
            cx, cy, r = c.args
            p.drawEllipse(cx - r, cy - r, 2 * r, 2 * r)
        elif c.kind == "X":
            p.setPen(QPen(col))
            x, y, s = c.args
            p.drawLine(x - s, y, x + s, y)
            p.drawLine(x, y - s, x, y + s)
        # T 文本不在此渲染
    p.end()
    return img


def text_items(frame: FrameResult) -> list[tuple[int, int, int, str]]:
    """返回该帧文本项 (x, y, rgb, text)。"""
    return [(c.args[0], c.args[1], c.color, c.text) for c in frame.cmds if c.kind == "T"]
