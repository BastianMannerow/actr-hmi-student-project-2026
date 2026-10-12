"""Shared, inexpensive artwork for the environment and its legend."""
from enum import Enum
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QSizePolicy, QWidget
from gui.environment_assets import draw_asset

class EnvironmentSymbol(str, Enum):
    BURNING_TREE = 'burning_tree'
    BURNING_BUSH = 'burning_bush'
    FIRE_TARGET = 'fire_target'
    ACTR_AGENT = 'actr_agent'
    HUMAN_AGENT = 'human_agent'
    UNKNOWN_TERRAIN = 'unknown_terrain'

ACTR_AGENT_COLOR = QColor('#38bdf8')
HUMAN_AGENT_COLOR = QColor('#fbbf24')

def symbol_for_terrain(entity) -> EnvironmentSymbol:
    if bool(getattr(entity, 'is_target', False)):
        return EnvironmentSymbol.FIRE_TARGET
    if type(entity).__name__ == 'BurningBush' or getattr(entity, 'is_uncertain', False):
        # Never expose the backend's hidden passability through the artwork.
        return EnvironmentSymbol.BURNING_BUSH
    if type(entity).__name__ == 'BurningTree' or getattr(entity, 'blocks_movement', False):
        return EnvironmentSymbol.BURNING_TREE
    return EnvironmentSymbol.UNKNOWN_TERRAIN

def symbol_for_agent(entity) -> EnvironmentSymbol:
    return EnvironmentSymbol.HUMAN_AGENT if getattr(entity, 'is_human_controlled', False) else EnvironmentSymbol.ACTR_AGENT

def draw_environment_symbol(painter: QPainter, rect: QRectF, symbol: EnvironmentSymbol,
                            *, label: str | None = None, fire_frame: QPixmap | None = None) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    side = min(rect.width(), rect.height())
    if symbol == EnvironmentSymbol.BURNING_TREE:
        block = rect.adjusted(.6, .6, -.6, -.6)
        painter.fillRect(block, QColor('#607384'))
        painter.setPen(QPen(QColor('#9aaeb9'), max(1., side * .05)))
        painter.drawLine(block.topLeft(), block.topRight())
        painter.setPen(QPen(QColor('#243744'), max(1., side * .055)))
        painter.drawLine(block.bottomLeft(), block.bottomRight())
        painter.drawLine(block.topRight(), block.bottomRight())
        painter.setPen(QPen(QColor('#344b5b'), max(.7, side * .04)))
        for y in (1 / 3, 2 / 3):
            painter.drawLine(QPointF(block.left(), block.top() + block.height() * y),
                             QPointF(block.right(), block.top() + block.height() * y))
        for index, x in enumerate((.5, .25, .65)):
            px = block.left() + block.width() * x
            painter.drawLine(QPointF(px, block.top() + block.height() * index / 3),
                             QPointF(px, block.top() + block.height() * (index + 1) / 3))
    elif symbol in {EnvironmentSymbol.BURNING_BUSH, EnvironmentSymbol.UNKNOWN_TERRAIN}:
        painter.fillRect(rect.adjusted(1, 1, -1, -1), QColor('#42251e'))
        if fire_frame is not None and not fire_frame.isNull():
            painter.drawPixmap(rect, fire_frame, QRectF(fire_frame.rect()))
        elif not draw_asset(painter, rect, 'fire.gif'):
            painter.fillRect(rect.adjusted(4, 4, -4, -4), QColor('#f97316'))
        if side >= 18:
            badge = QRectF(rect.right() - side * .32, rect.top() + 1, side * .29, side * .35)
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor('#cc34221e'))
            painter.drawRoundedRect(badge, 2, 2)
            painter.setPen(QColor('#fff7d6'))
            font = QFont('Sans Serif'); font.setPixelSize(max(8, int(side * .27))); font.setBold(True)
            painter.setFont(font); painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, '?')
    elif symbol == EnvironmentSymbol.FIRE_TARGET:
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor('#713b36'))
        painter.drawEllipse(rect.adjusted(side * .06, side * .06, -side * .06, -side * .06))
        if not draw_asset(painter, rect.adjusted(1, 1, -1, -1), 'scared-person.svg'):
            painter.setPen(QColor('#fff1bd')); painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, '!')
    elif symbol in {EnvironmentSymbol.ACTR_AGENT, EnvironmentSymbol.HUMAN_AGENT}:
        human = symbol == EnvironmentSymbol.HUMAN_AGENT
        painter.setPen(QPen(HUMAN_AGENT_COLOR if human else ACTR_AGENT_COLOR, max(1., side * .035)))
        painter.setBrush(QColor('#173745'))
        painter.drawEllipse(rect.adjusted(side * .03, side * .03, -side * .03, -side * .03))
        if not draw_asset(painter, rect.adjusted(side * .07, side * .07, -side * .07, -side * .07), 'squirtle.png'):
            painter.setPen(QColor('#e0f2fe')); painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, 'H' if human else 'A')
    painter.restore()

class EnvironmentLegendMarker(QWidget):
    """Static previews do not allocate additional animation decoders."""
    def __init__(self, symbol: EnvironmentSymbol, parent=None) -> None:
        super().__init__(parent); self.symbol = symbol
        self.setFixedSize(28, 28)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        draw_environment_symbol(painter, QRectF(2., 2., 24., 24.), self.symbol)
