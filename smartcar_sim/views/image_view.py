"""图像视图：缩放/平移/像素读数/图层合成（原图|处理后 + 叠加 + 文本）+ tag 悬停/高亮。"""
from __future__ import annotations

import html

import numpy as np
from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QToolTip,
)

from ..run.protocol import FrameResult
from .overlay import render_overlay, text_items

_GRID_MIN_SCALE = 8.0
_TAG_HIT_PX = 12.0     # tag 悬停命中半径（屏幕像素）
_HL_RADIUS_PX = 10.0   # 高亮环半径（屏幕像素）
_HL_COLOR = QColor("#FFD500")
_HUD_M = 12            # 状态板距视口边距
_HUD_MAX_LINES = 8     # 最多显示几行，防刷屏


def _tip_html(lines: list[str]) -> str:
    """强制富文本 + 转义：防止文本里的 < 被 Qt 误判为 HTML 吞掉。"""
    return "<div style='white-space:pre'>" + html.escape("\n".join(lines)) + "</div>"


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
        self._rot180 = False   # 显示旋转 180°（数据/坐标不动，只是正着看）
        self._hud_on = True    # 状态板：sim_draw_text 放大显示在视口角落
        self._hud_texts: list[tuple[int, str]] = []   # (rgb, text)
        self._tags: list[tuple[int, int, str]] = []
        self._highlight: tuple[int, int] | None = None

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

        # tag 不渲染到图上，关"叠加"也应能悬停查看
        self._tags = list(frame_result.tags) if frame_result is not None else []
        self._highlight = None
        QToolTip.hideText()  # 防播放时挂着上一帧的陈旧 tooltip

        for it in self._text_items:
            self._scene.removeItem(it)
        self._text_items.clear()

        if frame_result is not None and self._show_overlay:
            ov = render_overlay(frame_result, w, h)
            self._overlay_item.setPixmap(QPixmap.fromImage(ov))
            self._overlay_item.setVisible(True)
            font = QFont("Consolas", 11)
            font.setBold(True)
            for x, y, rgb, text in text_items(frame_result):
                it = QGraphicsSimpleTextItem(text)
                it.setFont(font)
                it.setBrush(QBrush(QColor((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF)))
                it.setPen(QPen(QColor(0, 0, 0, 220), 2.0))  # 粗黑描边，浅色底图上也看得清
                it.setPos(x, y)
                it.setFlag(it.GraphicsItemFlag.ItemIgnoresTransformations)
                it.setVisible(not self._hud_on)   # 状态板开着就不在图上重复画一遍
                self._scene.addItem(it)
                self._text_items.append(it)
        else:
            self._overlay_item.setVisible(False)

        # 状态板只收 (0,0) 位置的文本（约定：状态文字锚定左上角原点）
        # 其余位置的 T 指令（cross_type=x、CROSS 等调试标注）保留在图上锚点，不进状态板
        self._hud_texts = (
            [(rgb, t) for x, y, rgb, t in text_items(frame_result) if x == 0 and y == 0]
            if frame_result is not None else []
        )

        rect = QRectF(0, 0, w, h)
        self._scene.setSceneRect(rect)
        if not self._fitted:
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
            self.scale(0.95, 0.95)
            self._fitted = True
        self.viewport().update()  # HUD 画在视口坐标系，场景脏标记不覆盖它，需显式触发

    def set_overlay_visible(self, on: bool) -> None:
        self._show_overlay = on

    def set_hud_visible(self, on: bool) -> None:
        """状态板开关：开=文字集中到视口角落大字板；关=回到图上锚点原位显示。

        两者互斥，避免同一句话显示两遍（图上那份也就能被关掉了）。
        """
        self._hud_on = on
        for it in self._text_items:
            it.setVisible(not on)
        self.viewport().update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        """先由 QGraphicsView 画场景，再在视口坐标系叠状态板。

        画在视口而非场景：不受缩放/旋转影响，字号恒定、永远正向、永远在最上层。
        """
        super().paintEvent(ev)
        if not self._hud_on or not self._hud_texts:
            return
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Consolas 无中文字形，Windows 字体回退导致度量错乱、描边糊字
        # Microsoft YaHei 在所有 Win10/11 系统均存在，中英文度量均准确
        font = QFont("Microsoft YaHei", 13)
        font.setBold(True)
        p.setFont(font)
        fm = p.fontMetrics()

        pad, gap = 10, 4
        lines = self._hud_texts[:_HUD_MAX_LINES]
        wmax = max(fm.horizontalAdvance(t) for _c, t in lines)
        lh = fm.height() + gap
        box = QRectF(_HUD_M, _HUD_M, wmax + pad * 2, lh * len(lines) - gap + pad * 2)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 165))          # 半透明黑底：任何底图上都读得清
        p.drawRoundedRect(box, 6, 6)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 40)))
        p.drawRoundedRect(box, 6, 6)

        y = box.top() + pad
        for rgb, text in lines:
            col = QColor((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF)
            if col.lightness() < 110:             # 深色字在黑底上看不清，自动提亮
                col = col.lighter(190)
            r = QRectF(box.left() + pad, y, wmax, fm.height())
            p.setPen(QColor(0, 0, 0, 200))        # 描边
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                p.drawText(r.translated(dx, dy), Qt.AlignmentFlag.AlignLeft, text)
            p.setPen(col)
            p.drawText(r, Qt.AlignmentFlag.AlignLeft, text)
            y += lh
        p.end()

    def set_view_rot180(self, on: bool) -> None:
        """显示旋转 180°（右下角原点约定下正着看图）。场景坐标不变，读数仍是约定坐标。"""
        if on != self._rot180:
            self._rot180 = on
            self.rotate(180)
            self.viewport().update()

    def set_highlight(self, x: int, y: int) -> None:
        self._highlight = (x, y)
        self.viewport().update()

    def reset_fit(self) -> None:
        self._fitted = False

    # ---- 交互 ----
    def wheelEvent(self, ev) -> None:  # noqa: N802
        factor = 1.25 if ev.angleDelta().y() > 0 else 0.8
        cur = abs(self.transform().m11())  # 旋转 180° 时 m11 为负，取绝对值
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

        # tag 悬停（ScrollHandDrag 拖拽平移中不弹）
        if ev.buttons() & Qt.MouseButton.LeftButton:
            QToolTip.hideText()
            return
        near = self._tags_near(pt)
        if near:
            QToolTip.showText(
                ev.globalPosition().toPoint(),
                _tip_html([f"({tx}, {ty})  {t}" for tx, ty, t in near]),
                self,
            )
        else:
            QToolTip.hideText()

    def _tags_near(self, pt) -> list[tuple[int, int, str]]:
        if not self._tags:
            return []
        scale = abs(self.transform().m11())
        r = max(2.0, _TAG_HIT_PX / max(scale, 1e-6))
        r2 = r * r
        return [(x, y, t) for x, y, t in self._tags
                if (x + 0.5 - pt.x()) ** 2 + (y + 0.5 - pt.y()) ** 2 <= r2]

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        """高倍缩放像素网格 + tag 高亮环。"""
        if self._gray is None:
            return
        scale = abs(self.transform().m11())  # 旋转 180° 时 m11 为负
        if scale >= _GRID_MIN_SCALE:
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

        if self._highlight is not None:
            hx, hy = self._highlight
            r = _HL_RADIUS_PX / max(scale, 1e-6)  # 屏幕恒定大小
            pen = QPen(_HL_COLOR)
            pen.setWidthF(2.0)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.drawEllipse(QPointF(hx + 0.5, hy + 0.5), r, r)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
