"""Panel-level presentation of the simulation environment."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from gui.environment_canvas import GridCanvas


class EnvironmentView(QFrame):
    """Panel containing grid metadata, legend, and the reusable renderer."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.environment: Any | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        heading = QHBoxLayout()
        title = QLabel("Environment")
        title.setObjectName("sectionTitle")
        self.info_label = QLabel("Not initialized")
        self.info_label.setObjectName("muted")
        self.info_label.setAlignment(
            Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignVCenter
        )
        heading.addWidget(title)
        heading.addStretch(1)
        heading.addWidget(self.info_label)
        layout.addLayout(heading)

        self.canvas = GridCanvas(self)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self._build_legend())

    def _build_legend(self) -> QWidget:
        legend = QFrame(self)
        legend.setObjectName("toolbar")
        row = QHBoxLayout(legend)
        row.setContentsMargins(10, 7, 10, 7)
        row.setSpacing(14)
        row.addWidget(self._legend_item("#7f1d1d", "X", "Burning tree (blocked)"))
        row.addWidget(self._legend_item("#9a3412", "B", "Burning bush (unknown)"))
        row.addWidget(self._legend_item("#16a34a", "F", "Fire target"))
        row.addWidget(self._legend_item("#2563eb", "A", "ACT-R agent", circular=True))
        row.addWidget(self._legend_item("#f59e0b", "H", "Human agent", circular=True))
        row.addStretch(1)
        return legend

    @staticmethod
    def _legend_item(
        color: str,
        symbol: str,
        text: str,
        *,
        circular: bool = False,
    ) -> QWidget:
        item = QWidget()
        item_layout = QHBoxLayout(item)
        item_layout.setContentsMargins(0, 0, 0, 0)
        item_layout.setSpacing(5)
        marker = QLabel(symbol)
        marker.setAlignment(Qt.AlignmentFlag.AlignCenter)
        marker.setFixedSize(22, 22)
        radius = "11px" if circular else "4px"
        marker.setStyleSheet(
            f"background: {color}; color: white; border: 1px solid #cbd5e1; "
            f"border-radius: {radius}; font-weight: 700;"
        )
        label = QLabel(text)
        label.setObjectName("muted")
        item_layout.addWidget(marker)
        item_layout.addWidget(label)
        return item

    def set_environment(self, environment: Any) -> None:
        self.environment = environment
        self.canvas.set_environment(environment)
        self.refresh()

    def refresh(self) -> None:
        matrix = getattr(self.environment, "level_matrix", None)
        if matrix and matrix[0]:
            agent_count = sum(
                1
                for row in matrix
                for cell in row
                for obj in cell
                if getattr(obj, "name", None)
            )
            backend = str(getattr(self.environment, "backend_name", "virtual")).upper()
            level_name = str(getattr(self.environment, "level_name", "")).strip()
            level_text = f" · {level_name}" if level_name else ""
            self.info_label.setText(
                f"{backend}{level_text} · {len(matrix[0])} × {len(matrix)} · "
                f"{agent_count} agent"
                f"{'s' if agent_count != 1 else ''}"
            )
        else:
            self.info_label.setText("Not initialized")
        self.canvas.update()
