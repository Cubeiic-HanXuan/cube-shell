
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QFont, QConicalGradient, QPainterPathStroker, QBrush
from PySide6.QtWidgets import QWidget
import math

class RingGauge(QWidget):
    def __init__(self, parent=None, value=0, color="#00A1FF", label="CPU"):
        super().__init__(parent)
        self._value = value
        self._color = QColor(color)
        self._label = label
        self.setMinimumSize(80, 80)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def setValue(self, value):
        self._value = max(0, min(100, float(value)))
        self.update()

    def setLineColor(self, color):
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = self.width()
        height = self.height()
        side = min(width, height)
        
        # Center point
        center = QPointF(width / 2.0, height / 2.0)
        
        # --- 1. Draw Outer Ticks (Scale) ---
        outer_radius = side / 2.0 - 2
        inner_radius_ticks = outer_radius - 4
        
        painter.save()
        painter.translate(center)
        
        # Draw 20 ticks
        tick_pen = QPen(QColor(255, 255, 255, 40))
        tick_pen.setWidthF(1.5)
        painter.setPen(tick_pen)
        
        for i in range(20):
            angle_deg = i * (360.0 / 20.0)
            angle_rad = math.radians(angle_deg)
            p1 = QPointF(math.cos(angle_rad) * inner_radius_ticks, math.sin(angle_rad) * inner_radius_ticks)
            p2 = QPointF(math.cos(angle_rad) * outer_radius, math.sin(angle_rad) * outer_radius)
            painter.drawLine(p1, p2)
            
        painter.restore()

        # --- 2. Draw Background Ring ---
        # Slightly smaller than ticks
        ring_radius = inner_radius_ticks - 6
        rect = QRectF(center.x() - ring_radius, center.y() - ring_radius, ring_radius * 2, ring_radius * 2)
        
        pen_bg = QPen(QColor(255, 255, 255, 20))
        pen_bg.setWidth(6)
        pen_bg.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_bg)
        painter.drawArc(rect, 0, 360 * 16)

        # --- 3. Draw Value Arc with Gradient ---
        start_angle = 90 * 16
        span_angle = - (self._value / 100.0) * 360 * 16
        
        # Glow effect (underlay)
        glow_color = QColor(self._color)
        glow_color.setAlpha(80)
        pen_glow = QPen(glow_color)
        pen_glow.setWidth(10) # Wider
        pen_glow.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_glow)
        painter.drawArc(rect, start_angle, span_angle)

        # Main Arc with Conical Gradient
        # Conical gradient centers at the widget center.
        # It sweeps counter-clockwise from 0 degrees (3 o'clock).
        # We need to map our value range to the gradient.
        # Since we draw a single arc, we can just use a Pen with a gradient brush?
        # QPen doesn't support gradients directly easily in drawArc unless we use a path.
        # However, for a simple "hot" effect, we can just use a solid color that is slightly brighter
        # or use a path stroker to convert arc to path and fill with gradient.
        
        # Let's try QPainterPathStroker for gradient arc
        path = QPainterPath()
        path.arcMoveTo(rect, start_angle / 16.0)
        path.arcTo(rect, start_angle / 16.0, span_angle / 16.0)
        
        stroker = QPainterPathStroker()
        stroker.setWidth(6)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroker_path = stroker.createStroke(path)
        
        # Create Conical Gradient
        # 90 degrees is start (top).
        grad = QConicalGradient(center, 90)
        # We want the gradient to follow the sweep.
        # Value 0 (top) -> Value 100 (top again).
        # We want the color to "heat up".
        # 0.0 is at 90 deg. 
        # But span is negative (clockwise).
        # So we go 90 -> 0 -> 270 ...
        # Conical gradient goes counter-clockwise.
        # So 0.0 (at 90 deg) -> CCW.
        # We are drawing Clockwise.
        # So we need the gradient to go CW from 0.0.
        # 1.0 is 360 deg CCW = 0 deg.
        # Effectively: 0.0 is Start. 1.0 is End (CCW).
        # We draw CW. So we correspond to 1.0 -> 0.0 space?
        # Let's just make it simpler: Darker shade of color to Lighter shade.
        c1 = self._color.darker(150)
        c2 = self._color.lighter(120)
        
        # Since precise mapping is tricky with dynamic span, let's just use a fixed nice gradient
        # that looks "active".
        grad.setColorAt(0.0, c2)
        grad.setColorAt(1.0, c1) # Just a mix
        
        painter.fillPath(stroker_path, QBrush(self._color)) # Fallback to solid for now to ensure visibility/cleanliness, gradients on thin lines often look messy without perfect alignment.
        # Actually, let's stick to the solid color but brighter.
        
        pen_fg = QPen(self._color)
        pen_fg.setWidth(6)
        pen_fg.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_fg)
        painter.drawArc(rect, start_angle, span_angle)
        
        # --- 4. Draw Dot Indicator at End of Arc ---
        # Current angle in radians (Clockwise from top: -90 offset in normal math, 
        # but here we start at 90 (top) and go negative span)
        # Math angle = 90 - (value/100 * 360)
        current_angle_deg = 90 - (self._value / 100.0 * 360)
        current_angle_rad = math.radians(current_angle_deg)
        
        dot_x = center.x() + math.cos(current_angle_rad) * ring_radius
        dot_y = center.y() - math.sin(current_angle_rad) * ring_radius # Y inverted in screen coords? No wait.
        # Screen Y increases down.
        # cos(90) = 0, sin(90) = 1. Top is (0, -r).
        # We want top.
        # Formula: x = cx + r * cos(theta), y = cy - r * sin(theta) (Standard cartesian with y up)
        # Screen coords: y is down.
        # Top (90 deg): x=0, y=-r.
        # Right (0 deg): x=r, y=0.
        # Correct for screen: x = cx + r * cos(-theta_screen?), let's stick to standard transform.
        # Qt drawArc 90*16 is Top (12 o'clock). 0 is 3 o'clock (Right).
        # So 90 deg is -90 deg in Qt? No.
        # Let's just use the calculated point.
        
        # Standard Parametric:
        # x = cx + r * cos(a)
        # y = cy + r * sin(a)
        # Qt 0 deg = 3 o'clock. 90 deg = 12 o'clock. (Counter-clockwise positive)
        # We start at 90.
        # End angle = 90 + (span_angle/16) (span is negative)
        end_angle_qt = 90 + (span_angle / 16.0)
        end_angle_rad = math.radians(end_angle_qt)
        
        # Qt coordinate system for sin/cos matches mathematical if y grows down?
        # No, normally y grows up in math.
        # In Qt: 0 is Right, 90 is Top (negative y direction from center? No wait)
        # drawArc: 90 is 12 o'clock.
        # cos(90) = 0, sin(90) = 1.
        # We want (0, -r).
        # So y = cy - r * sin(a) fits.
        
        dot_x = center.x() + ring_radius * math.cos(end_angle_rad)
        dot_y = center.y() - ring_radius * math.sin(end_angle_rad)
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(QPointF(dot_x, dot_y), 2.5, 2.5)

        # --- 5. Draw Text ---
        # Font styling
        font_family = "Consolas" # Monospace for tech feel
        
        # Value Text
        font_val = QFont(font_family)
        font_val.setBold(True)
        font_val.setPixelSize(int(side * 0.20))
        painter.setFont(font_val)
        painter.setPen(self._color.lighter(120)) # Text matches gauge color
        
        val_rect = QRectF(center.x() - side/2, center.y() - side/6, side, side/2)
        painter.drawText(val_rect, Qt.AlignmentFlag.AlignCenter, f"{int(self._value)}%")

        # Label Text
        font_lbl = QFont("Segoe UI") # Label can be standard sans
        font_lbl.setPixelSize(int(side * 0.12))
        font_lbl.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        painter.setFont(font_lbl)
        painter.setPen(QColor(160, 174, 192)) # Greyish
        
        lbl_rect = QRectF(center.x() - side/2, center.y() + side/10, side, side/4)
        painter.drawText(lbl_rect, Qt.AlignmentFlag.AlignCenter, self._label)
