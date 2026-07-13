"""Low-level, responsive rendering of the simulation environment."""

from __future__ import annotations

import hashlib
from typing import Any

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QToolTip, QWidget


class GridCanvas(QWidget):
    """Paint a level matrix without creating one QWidget per cell."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.environment: Any | None = None
        self._grid_rect = QRectF()
        self._cell_size = 0.0
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(560, 560)

    def set_environment(self, environment: Any) -> None:
        self.environment = environment
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0b0f16"))

        matrix = getattr(self.environment, "level_matrix", None)
        if not matrix or not matrix[0]:
            painter.setPen(QColor("#8d98aa"))
            painter.setFont(QFont(self.font().family(), 11))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Environment is initializing…",
            )
            return

        rows = len(matrix)
        columns = len(matrix[0])
        margin = 18.0
        available_width = max(1.0, self.width() - 2 * margin)
        available_height = max(1.0, self.height() - 2 * margin)
        cell_size = min(
            available_width / columns,
            available_height / rows,
        )
        grid_width = cell_size * columns
        grid_height = cell_size * rows
        origin_x = (self.width() - grid_width) / 2.0
        origin_y = (self.height() - grid_height) / 2.0

        self._cell_size = cell_size
        self._grid_rect = QRectF(
            origin_x,
            origin_y,
            grid_width,
            grid_height,
        )

        painter.setPen(QPen(QColor("#2a3342"), 1.0))
        for row in range(rows):
            for column in range(columns):
                rect = QRectF(
                    origin_x + column * cell_size,
                    origin_y + row * cell_size,
                    cell_size,
                    cell_size,
                )
                painter.fillRect(
                    rect,
                    QColor("#141a24")
                    if (row + column) % 2 == 0
                    else QColor("#111720"),
                )
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(rect)
                cell_objects = list(matrix[row][column])
                terrain = [
                    obj for obj in cell_objects
                    if not getattr(obj, "name", None)
                    and getattr(obj, "symbol", None)
                ]
                occupants = [
                    obj for obj in cell_objects
                    if getattr(obj, "name", None)
                ]
                self._draw_terrain(painter, rect, terrain)
                self._draw_occupants(painter, rect, occupants)

        painter.setPen(QPen(QColor("#46536a"), 1.4))
        painter.drawRect(self._grid_rect)

    def _draw_terrain(
        self,
        painter: QPainter,
        rect: QRectF,
        terrain: list[Any],
    ) -> None:
        if not terrain:
            return
        painter.save()
        # A cell can contain more than one terrain marker. Render the most
        # semantically important one instead of relying on insertion order.
        item = sorted(
            terrain,
            key=lambda value: (
                0 if bool(getattr(value, "is_target", False)) else
                1 if type(value).__name__ == "DefinitelyAWall" else
                2 if type(value).__name__ == "Wall" else
                3 if type(value).__name__ == "FakeWall" else 4
            ),
        )[0]
        name = type(item).__name__
        label = ""
        if bool(getattr(item, "is_target", False)):
            painter.setBrush(QColor("#16a34a"))
            painter.setPen(QPen(QColor("#bbf7d0"), 1.5))
            center = rect.center()
            radius = min(rect.width(), rect.height()) * 0.34
            painter.drawEllipse(center, radius, radius)
            painter.setBrush(QColor("#dcfce7"))
            painter.drawEllipse(center, radius * 0.45, radius * 0.45)
            label = "T"
        elif name == "DefinitelyAWall":
            painter.fillRect(rect.adjusted(2, 2, -2, -2), QColor("#475569"))
            painter.setPen(QPen(QColor("#cbd5e1"), 1.2))
            painter.drawLine(rect.topLeft() + QPointF(4, 4), rect.bottomRight() - QPointF(4, 4))
            painter.drawLine(rect.topRight() + QPointF(-4, 4), rect.bottomLeft() + QPointF(4, -4))
            label = "X"
        elif name == "Wall":
            inner = rect.adjusted(2, 2, -2, -2)
            painter.fillRect(inner, QColor("#7f1d1d"))
            painter.setPen(QPen(QColor("#fca5a5"), 1.0))
            for fraction in (0.33, 0.66):
                y = inner.top() + inner.height() * fraction
                painter.drawLine(QPointF(inner.left(), y), QPointF(inner.right(), y))
            label = "W"
        elif name == "FakeWall":
            painter.fillRect(rect.adjusted(3, 3, -3, -3), QColor("#854d0e"))
            painter.setPen(QPen(QColor("#fde68a"), 1.4, Qt.PenStyle.DashLine))
            painter.drawRect(rect.adjusted(4, 4, -4, -4))
            label = "P"
        else:
            painter.fillRect(rect.adjusted(3, 3, -3, -3), QColor("#334155"))
            label = str(getattr(item, "symbol", "?"))[:2]

        if label and rect.width() >= 24 and rect.height() >= 24:
            font = QFont(self.font())
            font.setBold(True)
            font.setPointSizeF(max(6.0, min(10.0, rect.width() * 0.22)))
            painter.setFont(font)
            painter.setPen(QColor("#f8fafc"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()

    def _draw_occupants(
        self,
        painter: QPainter,
        rect: QRectF,
        occupants: list[Any],
    ) -> None:
        if not occupants:
            return

        painter.save()
        visible = occupants[:4]
        radius = max(
            4.0,
            min(rect.width(), rect.height())
            * (0.29 if len(visible) == 1 else 0.19),
        )
        offsets = [
            (0.5, 0.5),
            (0.33, 0.33),
            (0.67, 0.33),
            (0.50, 0.68),
        ]
        for index, occupant in enumerate(visible):
            name = str(getattr(occupant, "name", "A"))
            ox, oy = offsets[index]
            center = QPointF(
                rect.left() + rect.width() * ox,
                rect.top() + rect.height() * oy,
            )
            color = (
                QColor("#f59e0b")
                if bool(getattr(occupant, "is_human_controlled", False))
                else self._agent_color(name)
            )
            painter.setBrush(color)
            painter.setPen(
                QPen(
                    QColor("#f1f4f8"),
                    max(1.0, rect.width() * 0.025),
                )
            )
            painter.drawEllipse(center, radius, radius)

            if rect.width() >= 28:
                label = name if rect.width() >= 75 else name[:3]
                font = QFont(self.font())
                font.setBold(True)
                font.setPointSizeF(
                    max(6.0, min(10.0, radius * 0.42))
                )
                painter.setFont(font)
                painter.setPen(QColor("#081018"))
                painter.drawText(
                    QRectF(
                        center.x() - radius,
                        center.y() - radius,
                        radius * 2,
                        radius * 2,
                    ),
                    Qt.AlignmentFlag.AlignCenter,
                    label,
                )

        if len(occupants) > len(visible):
            painter.setPen(QColor("#d9e0ea"))
            painter.drawText(
                rect.adjusted(3, 3, -3, -3),
                Qt.AlignmentFlag.AlignBottom
                | Qt.AlignmentFlag.AlignRight,
                f"+{len(occupants) - len(visible)}",
            )
        painter.restore()

    @staticmethod
    def _agent_color(name: str) -> QColor:
        digest = hashlib.sha256(name.encode("utf-8")).digest()
        hue = int.from_bytes(digest[:2], "big") % 360
        return QColor.fromHsl(hue, 145, 178)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        matrix = getattr(self.environment, "level_matrix", None)
        if (
            not matrix
            or self._cell_size <= 0
            or not self._grid_rect.contains(event.position())
        ):
            QToolTip.hideText()
            return

        column = int(
            (event.position().x() - self._grid_rect.left())
            / self._cell_size
        )
        row = int(
            (event.position().y() - self._grid_rect.top())
            / self._cell_size
        )
        if 0 <= row < len(matrix) and 0 <= column < len(matrix[0]):
            names = [
                str(getattr(obj, "name"))
                for obj in matrix[row][column]
                if getattr(obj, "name", None)
            ]
            terrain = [
                str(getattr(obj, "display_name", type(obj).__name__))
                for obj in matrix[row][column]
                if not getattr(obj, "name", None)
            ]
            text = f"Row {row + 1}, column {column + 1}"
            details = names + terrain
            if details:
                text += "\n" + "\n".join(details)
            QToolTip.showText(
                event.globalPosition().toPoint(),
                text,
                self,
            )
