"""图像视图：缩放/平移/像素读数/图层合成（原图|处理后 + 叠加 + 文本）。"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from ..run.protocol import FrameResult
from .overlay import render_overlay, text_items

_GRID_MIN_SCALE = 8.0


def gray_to_qimage(arr: np.ndarray) -> QImage:
    h, w = arr.shape
    arr = np.ascontiguousarray(arr)
    img = QImage(arr.data, w, h, w, QImage.Format.Format_Grayscale8)
    return img.copy()  # 拷贝一份摆脱 numpy 生命周期


class ImageView(QGraphicsView):
    pixel_hovered = Signal(int, int, int)  # x, y, value（-1 表示离开）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setBackgroundBrush(QBrush(QColor("#252526")))
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setMouseTracking(True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

        self._base_item = QGraphicsPixmapItem()
        self._base_item.setTransformationMode(Qt.TransformationMode.FastTransformation)
        self._overlay_item = QGraphicsPixmapItem()
        self._overlay_item.setTransformationMode(Qt.TransformationMode.FastTransformation)
        self._scene.addItem(self._base_item)
        self._scene.addItem(self._overlay_item)
        self._text_items: list[QGraphicsSimpleTextItem] = []

        self._gray: np.ndarray | None = None       # 当前底图数组（读像素用）
        self._show_overlay = True
        self._fitted = False

    # ---- 内容 ----
    def show_frame(
        self,
        base: np.ndarray,
        frame_result: FrameResult | None = None,
    ) -> None:
        """base: (H,W) uint8；frame_result 为 None 时只显示底图。"""
        self._gray = base
        h, w = base.shape
        self._base_item.setPixmap(QPixmap.fromImage(gray_to_qimage(base)))

        for it in self._text_items:
            self._scene.removeItem(it)
        self._text_items.clear()

        if frame_result is not None and self._show_overlay:
            ov = render_overlay(frame_result, w, h)
            self._overlay_item.setPixmap(QPixmap.fromImage(ov))
            self._overlay_item.setVisible(True)
            font = QFont("Consolas", 9)
            for x, y, rgb, text in text_items(frame_result):
                it = QGraphicsSimpleTextItem(text)
                it.setFont(font)
                it.setBrush(QBrush(QColor((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF)))
                it.setPen(QPen(QColor(0, 0, 0, 180), 0.5))
                it.setPos(x, y)
                it.setFlag(it.GraphicsItemFlag.ItemIgnoresTransformations)
                self._scene.addItem(it)
                self._text_items.append(it)
        else:
            self._overlay_item.setVisible(False)

        rect = QRectF(0, 0, w, h)
        self._scene.setSceneRect(rect)
        if not self._fitted:
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
            self.scale(0.95, 0.95)
            self._fitted = True

    def set_overlay_visible(self, on: bool) -> None:
        self._show_overlay = on

    def reset_fit(self) -> None:
        self._fitted = False

    # ---- 交互 ----
    def wheelEvent(self, ev) -> None:  # noqa: N802
        factor = 1.25 if ev.angleDelta().y() > 0 else 0.8
        cur = self.transform().m11()
        if 0.2 <= cur * factor <= 80:
            self.scale(factor, factor)
            self.viewport().update()

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        super().mouseMoveEvent(ev)
        if self._gray is None:
            return
        pt = self.mapToScene(ev.position().toPoint())
        x, y = int(pt.x()), int(pt.y())
        h, w = self._gray.shape
        if 0 <= x < w and 0 <= y < h:
            self.pixel_hovered.emit(x, y, int(self._gray[y, x]))
        else:
            self.pixel_hovered.emit(-1, -1, -1)

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        """高倍缩放时画像素网格。"""
        scale = self.transform().m11()
        if scale < _GRID_MIN_SCALE or self._gray is None:
            return
        h, w = self._gray.shape
        pen = QPen(QColor(128, 128, 128, 60))
        pen.setCosmetic(True)
        painter.setPen(pen)
        x0 = max(0, int(rect.left()))
        x1 = min(w, int(rect.right()) + 1)
        y0 = max(0, int(rect.top()))
        y1 = min(h, int(rect.bottom()) + 1)
        for x in range(x0, x1 + 1):
            painter.drawLine(x, y0, x, y1)
        for y in range(y0, y1 + 1):
            painter.drawLine(x0, y, x1, y)
