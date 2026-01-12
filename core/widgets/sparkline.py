from __future__ import annotations

from collections import deque
from typing import Deque, Iterable, Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QLinearGradient
from PySide6.QtWidgets import QWidget


class SparklineWidget(QWidget):
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        max_points: int = 48,
        line_color: Optional[QColor] = None,
    ):
        super().__init__(parent)
        self._values: Deque[float] = deque(maxlen=max(8, int(max_points)))
        self._line_color = line_color or QColor("#00A1FF")
        self._fill_color = QColor(self._line_color)
        self._fill_color.setAlpha(60)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def setLineColor(self, color: QColor):
        self._line_color = QColor(color)
        self._fill_color = QColor(color)
        self._fill_color.setAlpha(60)
        self.update()

    def addPoint(self, value: float):
        try:
            v = float(value)
        except Exception:
            return
        self._values.append(v)
        self.update()

    def setPoints(self, values: Iterable[float]):
        self._values.clear()
        for v in values:
            try:
                self._values.append(float(v))
            except Exception:
                continue
        self.update()

    def points(self) -> list[float]:
        return list(self._values)

    def paintEvent(self, _event):
        if len(self._values) < 2:
            return

        w = self.width()
        h = self.height()
        if w <= 2 or h <= 2:
            return

        rect = QRectF(0.0, 0.0, float(w), float(h))
        inset = 1.0
        rect = rect.adjusted(inset, inset, -inset, -inset)
        if rect.width() <= 2 or rect.height() <= 2:
            return

        values = list(self._values)
        v_min = min(values)
        v_max = max(values)
        if v_max - v_min < 1e-6:
            v_max = v_min + 1.0

        x_step = rect.width() / max(1, (len(values) - 1))

        def y_for(v: float) -> float:
            t = (v - v_min) / (v_max - v_min)
            return rect.bottom() - t * rect.height()

        points = [QPointF(rect.left() + i * x_step, y_for(v)) for i, v in enumerate(values)]

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        
        # --- Draw Grid Background ---
        grid_pen = QPen(QColor(255, 255, 255, 15))
        grid_pen.setWidth(1)
        grid_pen.setStyle(Qt.PenStyle.DotLine)
        painter.setPen(grid_pen)
        
        # Vertical grid lines
        grid_step_x = w / 6.0
        for i in range(1, 6):
            gx = i * grid_step_x
            painter.drawLine(QPointF(gx, 0), QPointF(gx, h))
            
        # Horizontal grid lines
        grid_step_y = h / 3.0
        for i in range(1, 3):
            gy = i * grid_step_y
            painter.drawLine(QPointF(0, gy), QPointF(w, gy))

        # --- Draw Fill with Gradient ---
        painter.setPen(Qt.PenStyle.NoPen)
        fill_path = QPainterPath()
        fill_path.moveTo(points[0])
        for p in points[1:]:
            fill_path.lineTo(p)
        fill_path.lineTo(QPointF(points[-1].x(), rect.bottom()))
        fill_path.lineTo(QPointF(points[0].x(), rect.bottom()))
        fill_path.closeSubpath()
        
        # Linear Gradient for fill
        fill_grad = QLinearGradient(0, 0, 0, h)
        c_top = QColor(self._line_color)
        c_top.setAlpha(100)
        c_bottom = QColor(self._line_color)
        c_bottom.setAlpha(10)
        fill_grad.setColorAt(0, c_top)
        fill_grad.setColorAt(1, c_bottom)
        
        painter.fillPath(fill_path, fill_grad)

        # --- Draw Line (Glow) ---
        # Draw a thicker, transparent line first for glow
        glow_pen = QPen(self._line_color)
        glow_pen.setWidthF(4.0)
        glow_color = QColor(self._line_color)
        glow_color.setAlpha(80)
        glow_pen.setColor(glow_color)
        glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        glow_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(glow_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        line_path = QPainterPath()
        line_path.moveTo(points[0])
        for p in points[1:]:
            line_path.lineTo(p)
        painter.drawPath(line_path)

        # --- Draw Line (Core) ---
        pen = QPen(self._line_color)
        pen.setWidthF(1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(line_path)

