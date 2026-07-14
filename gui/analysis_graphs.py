"""Zoomable, exportable graph views for ACT-R explainability."""

from __future__ import annotations

import json
import math
import textwrap
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtSvg import QSvgGenerator
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsTextItem,
    QGraphicsView,
    QMenu,
)

from simulation.inspection.declarative_memory import DeclarativeMemorySnapshot
from gui.graph_layout import (
    LayoutEdge,
    LayoutNode,
    assign_label_positions,
)

from gui.ux_graph_layout import layout_state_graph, route_semantic_columns

from simulation.inspection.source_analysis import (
    AgentStaticAnalysis,
    MethodBufferInteraction,
    StateTransitionAnalysis,
)


SCENE_BACKGROUND = QColor("#0f172a")
TEXT_COLOR = QColor("#f8fafc")
MUTED_TEXT = QColor("#cbd5e1")
LABEL_BACKGROUND = QColor(15, 23, 42, 225)
MAX_RASTER_EXPORT_DIMENSION = 4096


class ZoomableGraphicsView(QGraphicsView):
    """Graphics view with wheel zoom, panning, and transparent export."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(SCENE_BACKGROUND))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._fit_pending = False
        self._llm_payload: dict[str, Any] | None = None
        self._llm_default_name = "agent_analysis"

    def wheelEvent(self, event):  # noqa: N802
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def reset_zoom(self) -> None:
        self.resetTransform()
        if self.scene() is None:
            return
        if not self.isVisible() or self.viewport().width() < 50:
            self._fit_pending = True
            return
        bounds = self.scene().sceneRect()
        if bounds.isNull() or bounds.isEmpty():
            bounds = self.scene().itemsBoundingRect().adjusted(-24, -24, 24, 24)
        self.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)
        self._fit_pending = False

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self._fit_pending:
            self.reset_zoom()

    def contextMenuEvent(self, event):  # noqa: N802
        menu = QMenu(self)
        fit_action = QAction("Fit to view", self)
        fit_action.triggered.connect(self.reset_zoom)
        menu.addAction(fit_action)
        png_action = QAction("Export PNG", self)
        png_action.triggered.connect(lambda: self.export_dialog("png"))
        menu.addAction(png_action)
        svg_action = QAction("Export SVG", self)
        svg_action.triggered.connect(lambda: self.export_dialog("svg"))
        menu.addAction(svg_action)
        llm_action = QAction("Export for LLM", self)
        llm_action.setEnabled(self._llm_payload is not None)
        llm_action.triggered.connect(self.export_for_llm_dialog)
        menu.addAction(llm_action)
        menu.exec(event.globalPos())

    def set_llm_export_data(
        self, payload: dict[str, Any] | None, *, default_name: str = "agent_analysis"
    ) -> None:
        self._llm_payload = payload
        self._llm_default_name = default_name or "agent_analysis"

    def export_for_llm_dialog(self) -> Path | None:
        if self._llm_payload is None:
            return None
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export for LLM",
            str(Path.home() / f"{self._llm_default_name}.json"),
            "Structured JSON (*.json)",
        )
        if not path:
            return None
        return self.export_llm_to(path)

    def export_llm_to(self, path: str | Path) -> Path:
        if self._llm_payload is None:
            raise RuntimeError("There is no structured graph data to export.")
        destination = Path(path)
        if destination.suffix.lower() != ".json":
            destination = destination.with_suffix(".json")
        destination.write_text(
            json.dumps(self._llm_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return destination

    def export_dialog(self, kind: str) -> Path | None:
        if self.scene() is None:
            return None
        suffix = ".svg" if kind == "svg" else ".png"
        path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export {kind.upper()}",
            str(Path.home() / f"agent_analysis{suffix}"),
            f"{kind.upper()} file (*{suffix})",
        )
        if not path:
            return None
        return self.export_to(path)

    def export_to(self, path: str | Path) -> Path:
        if self.scene() is None:
            raise RuntimeError("There is no scene to export.")
        destination = Path(path)
        rect = self.scene().sceneRect()
        if rect.isNull() or rect.isEmpty():
            rect = self.scene().itemsBoundingRect().adjusted(-36, -36, 36, 36)
        scene = self.scene()
        original_background = scene.backgroundBrush()
        scene.setBackgroundBrush(QBrush(Qt.BrushStyle.NoBrush))
        try:
            if destination.suffix.lower() == ".svg":
                generator = QSvgGenerator()
                generator.setFileName(str(destination))
                generator.setSize(rect.size().toSize())
                generator.setViewBox(rect.toRect())
                painter = QPainter(generator)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                scene.render(painter, QRectF(), rect)
                painter.end()
            else:
                if destination.suffix.lower() != ".png":
                    destination = destination.with_suffix(".png")
                longest_side = max(rect.width(), rect.height(), 1.0)
                raster_scale = min(
                    1.0,
                    MAX_RASTER_EXPORT_DIMENSION / longest_side,
                )
                width = max(1, int(round(rect.width() * raster_scale)))
                height = max(1, int(round(rect.height() * raster_scale)))
                image = QImage(width, height, QImage.Format.Format_ARGB32)
                if image.isNull():
                    raise RuntimeError(
                        "The PNG export buffer could not be allocated. "
                        "Use SVG or Export for LLM for this graph."
                    )
                image.fill(Qt.GlobalColor.transparent)
                painter = QPainter(image)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
                scene.render(
                    painter,
                    QRectF(0.0, 0.0, float(width), float(height)),
                    rect,
                )
                painter.end()
                image.save(str(destination))
        finally:
            scene.setBackgroundBrush(original_background)
        return destination


def _translate_layout_below(geometry: Any, minimum_y: float) -> None:
    """Move a complete routed layout below protected header/legend space."""
    values = [placement.rect.top() for placement in geometry.placements.values()]
    values.extend(
        point.y()
        for route in geometry.routes.values()
        for point in route.points
    )
    values.extend(point.y() for point in geometry.group_headers.values())
    if not values:
        return
    delta = minimum_y - min(values)
    if delta <= 0.0:
        return
    for placement in geometry.placements.values():
        placement.rect.translate(0.0, delta)
    for route in geometry.routes.values():
        route.points = [QPointF(point.x(), point.y() + delta) for point in route.points]
        route.label_position = QPointF(
            route.label_position.x(), route.label_position.y() + delta
        )
    geometry.group_headers = {
        group: QPointF(point.x(), point.y() + delta)
        for group, point in geometry.group_headers.items()
    }
    geometry.bounds.translate(0.0, delta)


def _translate_rendered_layout_below(
    geometry: Any,
    routes: dict[str, Any],
    minimum_y: float,
) -> None:
    values = [placement.rect.top() for placement in geometry.placements.values()]
    values.extend(point.y() for route in routes.values() for point in route.points)
    values.extend(point.y() for point in geometry.group_headers.values())
    if not values:
        return
    delta = minimum_y - min(values)
    if delta <= 0.0:
        return
    for placement in geometry.placements.values():
        placement.rect.translate(0.0, delta)
    for route in routes.values():
        route.points = [QPointF(point.x(), point.y() + delta) for point in route.points]
        route.label_position = QPointF(
            route.label_position.x(), route.label_position.y() + delta
        )
    for route in geometry.routes.values():
        route.points = [QPointF(point.x(), point.y() + delta) for point in route.points]
        route.label_position = QPointF(
            route.label_position.x(), route.label_position.y() + delta
        )
    geometry.group_headers = {
        group: QPointF(point.x(), point.y() + delta)
        for group, point in geometry.group_headers.items()
    }
    geometry.bounds.translate(0.0, delta)


def build_state_transition_scene(analysis: AgentStaticAnalysis) -> QGraphicsScene:
    """Render the reachable control graph with compact placement and orthogonal routing."""
    scene = _new_scene()
    _add_scene_title(scene, f"State transitions — {analysis.agent_type}")
    legend_bounds = _add_legend(
        scene,
        [
            ("Initial", QColor("#1d4ed8"), "box"),
            ("Reachable", QColor("#047857"), "box"),
            ("Adapter handoff", QColor("#b45309"), "box"),
            ("Terminal", QColor("#0e7490"), "box"),
            ("Dead end", QColor("#be123c"), "box"),
            ("Loop outline", QColor("#a855f7"), "line"),
            ("Production", QColor("#7dd3fc"), "line"),
            ("Adapter override", QColor("#f0abfc"), "dash"),
        ],
        y=52,
        max_width=1500,
    )

    reachable_states = {
        state_id: state
        for state_id, state in analysis.states.items()
        if state.reachable
    }
    transitions = [
        transition
        for transition in analysis.transitions
        if transition.reachable
        and transition.source_state_id in reachable_states
        and transition.target_state_id in reachable_states
    ]
    if not reachable_states:
        _add_empty_message(scene, "No reachable control states were detected.", y=118)
        return scene

    layout_nodes = [
        LayoutNode(
            node_id=state_id,
            label=state.label,
            group=state.phase,
            width=238.0,
            height=76.0,
            priority=(
                100 if state_id == analysis.initial_state_id else
                80 if state.terminal else
                60 if state.adapter_handoff else
                0
            ),
        )
        for state_id, state in reachable_states.items()
    ]
    # Visually aggregate semantically parallel transitions. The complete
    # transition set remains available in tooltips, the detail catalogue, and
    # Export for LLM, while the overview graph draws one traceable route per
    # source/target/family tuple.
    transition_bundles: dict[tuple[str, str, str], list[StateTransitionAnalysis]] = defaultdict(list)
    for transition in transitions:
        transition_bundles[(
            transition.source_state_id,
            transition.target_state_id,
            transition.kind,
        )].append(transition)
    bundle_transitions: dict[str, list[StateTransitionAnalysis]] = {}
    layout_edges: list[LayoutEdge] = []
    for index, (key, values) in enumerate(sorted(transition_bundles.items())):
        source_id, target_id, kind = key
        bundle_id = f"bundle:{kind}:{index}"
        bundle_transitions[bundle_id] = sorted(
            values, key=lambda item: (item.label.casefold(), item.transition_id)
        )
        layout_edges.append(
            LayoutEdge(
                edge_id=bundle_id,
                source_id=source_id,
                target_id=target_id,
                kind=kind,
                weight=1.0 + min(0.8, 0.12 * (len(values) - 1)),
            )
        )

    geometry = layout_state_graph(
        layout_nodes,
        layout_edges,
        initial_node_id=analysis.initial_state_id,
        offset=QPointF(42.0, legend_bounds.bottom() + 58.0),
    )
    _translate_layout_below(
        geometry, legend_bounds.bottom() + 42.0
    )
    # The layered channel router already assigns an independent route and
    # minimum lane spacing to every transition. Post-routing lane shifts are
    # deliberately avoided because they can turn short paths into artificial
    # perimeter loops.
    display_routes = dict(geometry.routes)
    _translate_rendered_layout_below(
        geometry, display_routes, legend_bounds.bottom() + 42.0
    )

    header_font = QFont("Sans Serif", 10)
    header_font.setBold(True)
    for phase, point in geometry.group_headers.items():
        header = QGraphicsSimpleTextItem(phase.upper())
        header.setFont(header_font)
        header.setBrush(QBrush(QColor("#cbd5e1")))
        header.setPos(point.x(), point.y())
        scene.addItem(header)

    for state_id, placement in geometry.placements.items():
        state = reachable_states[state_id]
        color = (
            QColor("#1d4ed8")
            if state_id == analysis.initial_state_id
            else QColor("#be123c")
            if state.dead_end
            else QColor("#0e7490")
            if state.terminal
            else QColor("#b45309")
            if state.adapter_handoff
            else QColor("#047857")
        )
        border = QColor("#a855f7") if state.loop_member else QColor("#dbe4f0")
        _add_node(
            scene,
            placement.rect,
            state.label,
            color,
            wrap_width=26,
            border_color=border,
            border_width=2.6 if state.loop_member else 1.5,
        )

    label_positions = assign_label_positions(
        display_routes.values(),
        [placement.rect for placement in geometry.placements.values()],
    )

    # Number production and adapter transitions independently in deterministic
    # graph order.  The same order is reused by the detail catalogue below, so
    # P1..Pn and A1..An can be found without scanning a mixed list.
    ordered_transitions = _ordered_transitions_for_codes(transitions, geometry)
    code_by_id: dict[str, str] = {}
    counters = {"production": 0, "adapter": 0}
    for transition in ordered_transitions:
        counters[transition.kind] += 1
        prefix = "A" if transition.kind == "adapter" else "P"
        code_by_id[transition.transition_id] = f"{prefix}{counters[transition.kind]}"
    scene._transition_codes = dict(code_by_id)

    details_by_kind: dict[str, list[tuple[str, str, QColor]]] = {
        "production": [],
        "adapter": [],
    }
    for edge_id, route in display_routes.items():
        bundled = bundle_transitions[edge_id]
        kind = bundled[0].kind
        codes = [code_by_id[item.transition_id] for item in bundled]
        color = QColor("#f0abfc") if kind == "adapter" else QColor("#7dd3fc")

        halo_pen = QPen(SCENE_BACKGROUND, 7.0)
        halo_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        halo_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        halo_item = _add_polyline_path(scene, route.points, halo_pen)
        halo_item.setZValue(0.0)

        pen = QPen(color, 2.4 if kind == "adapter" else 2.25)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if kind == "adapter":
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([7.0, 4.0])
            pen.setDashOffset((_numeric_code(codes[0]) % 4) * 2.0)
        path_item = _add_polyline_path(scene, route.points, pen)
        path_item.setZValue(1.0)

        tooltip_parts = []
        for transition, code in zip(bundled, codes):
            tooltip_parts.append(
                f"{code} · {transition.kind}: {transition.label}\n"
                f"Guard: {transition.guard_label or 'none'}\n"
                f"Actions: {transition.action_label or 'control-state update'}"
            )
        tooltip = "\n\n".join(tooltip_parts)
        path_item.setToolTip(tooltip)
        if len(route.points) >= 2:
            _draw_arrow(scene, route.points[-2], route.points[-1], color)
        code_label = _compact_code_range(codes)
        label = _add_edge_label(scene, code_label, label_positions[edge_id], color)
        label.setToolTip(tooltip)

        for transition, code in zip(bundled, codes):
            source = reachable_states[transition.source_state_id]
            target = reachable_states[transition.target_state_id]
            detail = transition.label
            if transition.guard_label:
                detail += f" | guard: {transition.guard_label.replace(chr(10), '; ')}"
            if transition.action_label:
                detail += f" | action: {transition.action_label.replace(chr(10), '; ')}"
            details_by_kind[transition.kind].append(
                (code, f"{source.label} → {target.label}\n{detail}", color)
            )

    _add_route_bundle_markers(scene, list(display_routes.values()))

    details_y = geometry.bounds.bottom() + 100.0
    details_font = QFont("Sans Serif", 10)
    details_font.setBold(True)
    detail_columns = 3
    detail_width = 600.0
    detail_height = 104.0

    current_y = details_y
    for kind, heading_text in (
        ("production", "Production transitions"),
        ("adapter", "Adapter overrides"),
    ):
        values = sorted(
            details_by_kind[kind],
            key=lambda item: _numeric_code(item[0]),
        )
        if not values:
            continue
        first_code = values[0][0]
        last_code = values[-1][0]
        heading = QGraphicsSimpleTextItem(
            f"{heading_text} · {first_code}–{last_code} · layout: {geometry.orientation}"
        )
        heading.setFont(details_font)
        heading.setBrush(QBrush(QColor("#f8fafc")))
        heading.setPos(42.0, current_y)
        scene.addItem(heading)

        for index, (code, detail, color) in enumerate(values):
            column = index % detail_columns
            row = index // detail_columns
            x = 42.0 + column * (detail_width + 24.0)
            y = current_y + 38.0 + row * (detail_height + 18.0)
            _add_node(
                scene,
                QRectF(x, y, 58.0, detail_height),
                code,
                QColor("#312e81") if code.startswith("P") else QColor("#86198f"),
                wrap_width=6,
                border_color=color,
                border_width=2.0,
            )
            text_item = QGraphicsTextItem(_wrap_label(detail, 70))
            text_item.setDefaultTextColor(QColor("#e2e8f0"))
            text_item.setTextWidth(detail_width - 72.0)
            text_item.setPos(x + 70.0, y + 4.0)
            scene.addItem(text_item)
        rows = (len(values) + detail_columns - 1) // detail_columns
        current_y += 38.0 + rows * (detail_height + 18.0) + 54.0

    unreachable_y = current_y
    if analysis.unreachable_productions:
        unreachable_heading = QGraphicsSimpleTextItem("Statically unreachable productions")
        unreachable_heading.setFont(details_font)
        unreachable_heading.setBrush(QBrush(QColor("#f8fafc")))
        unreachable_heading.setPos(42.0, unreachable_y)
        scene.addItem(unreachable_heading)
        production_by_name = {item.name: item for item in analysis.productions}
        columns = 3
        cell_width = 430.0
        for index, name in enumerate(analysis.unreachable_productions):
            production = production_by_name[name]
            source_state = analysis.states.get(production.source_state_id)
            target_state = analysis.states.get(production.target_state_id)
            value = (
                f"{name}\n"
                f"{source_state.label if source_state else '?'} → "
                f"{target_state.label if target_state else '?'}"
            )
            column = index % columns
            row = index // columns
            _add_node(
                scene,
                QRectF(
                    42.0 + column * (cell_width + 26.0),
                    unreachable_y + 42.0 + row * 92.0,
                    cell_width,
                    70.0,
                ),
                value,
                QColor("#334155"),
                wrap_width=52,
                border_color=QColor("#64748b"),
            )
    return scene


def build_interaction_scene(
    title: str,
    interactions: Iterable[MethodBufferInteraction],
) -> QGraphicsScene:
    """Render interactions as a matrix, eliminating ambiguous crossing edges."""
    scene = _new_scene()
    _add_scene_title(scene, title)
    legend_bounds = _add_legend(
        scene,
        [
            ("Read", QColor("#1d4ed8"), "box"),
            ("Write / request", QColor("#b45309"), "box"),
            ("Read + write", QColor("#6d28d9"), "box"),
            ("Delete / clear", QColor("#be123c"), "box"),
        ],
        y=50,
        max_width=1200,
    )
    rows = list(interactions)
    if not rows:
        _add_empty_message(scene, "No buffer interactions were detected.", y=104)
        return scene

    actors = sorted({row.method_name for row in rows}, key=str.lower)
    buffers = sorted({row.buffer_name for row in rows}, key=str.lower)
    actor_width = 330.0
    cell_width = 132.0
    row_height = 72.0
    header_y = legend_bounds.bottom() + 44.0
    body_y = header_y + 86.0
    left = 36.0

    actor_map: dict[str, list[MethodBufferInteraction]] = defaultdict(list)
    cell_map: dict[tuple[str, str], list[MethodBufferInteraction]] = defaultdict(list)
    for interaction in rows:
        actor_map[interaction.method_name].append(interaction)
        cell_map[(interaction.method_name, interaction.buffer_name)].append(interaction)

    actor_header = QGraphicsSimpleTextItem("Production / adapter handler")
    actor_header.setBrush(QBrush(QColor("#cbd5e1")))
    actor_header.setPos(left, header_y + 22)
    scene.addItem(actor_header)
    for column, buffer_name in enumerate(buffers):
        rect = QRectF(
            left + actor_width + 18 + column * cell_width,
            header_y,
            cell_width - 8,
            64,
        )
        _add_node(
            scene,
            rect,
            buffer_name,
            QColor("#14532d"),
            wrap_width=18,
            border_color=QColor("#86efac"),
        )

    trigger_x = left + actor_width + 18 + len(buffers) * cell_width + 22
    has_triggers = any(item.triggered_by for item in rows)
    if has_triggers:
        trigger_header = QGraphicsSimpleTextItem("Triggered after production")
        trigger_header.setBrush(QBrush(QColor("#cbd5e1")))
        trigger_header.setPos(trigger_x, header_y + 22)
        scene.addItem(trigger_header)

    for row_index, actor in enumerate(actors):
        y = body_y + row_index * row_height
        interactions_for_actor = actor_map[actor]
        actor_label = actor
        actor_rect = QRectF(left, y, actor_width, 54)
        _add_node(
            scene,
            actor_rect,
            actor_label,
            QColor("#1e3a8a"),
            wrap_width=38,
        )
        for column, buffer_name in enumerate(buffers):
            cell = cell_map.get((actor, buffer_name), [])
            rect = QRectF(
                left + actor_width + 18 + column * cell_width,
                y,
                cell_width - 8,
                54,
            )
            if not cell:
                empty = QGraphicsRectItem(rect)
                empty.setPen(QPen(QColor("#334155"), 0.8))
                empty.setBrush(QBrush(QColor("#111827")))
                scene.addItem(empty)
                continue
            modes = {item.mode.lower() for item in cell}
            has_read = bool(modes & {"read", "query"})
            has_write = bool(modes & {"write", "request"})
            has_delete = bool(modes & {"delete", "clear"})
            if has_delete:
                color = QColor("#be123c")
                code = "D"
            elif has_read and has_write:
                color = QColor("#6d28d9")
                code = "R/W"
            elif has_write:
                color = QColor("#b45309")
                code = "W"
            else:
                color = QColor("#1d4ed8")
                code = "R"
            _add_node(
                scene,
                rect,
                code,
                color,
                wrap_width=8,
                border_color=QColor("#e2e8f0"),
            )
            tooltip = "\n\n".join(
                f"{item.mode}: {item.function_name}\n{item.detail or ''}"
                for item in cell
            )
            for graphics_item in scene.items(rect):
                graphics_item.setToolTip(tooltip)
        if has_triggers:
            triggers = sorted(
                {
                    trigger
                    for item in interactions_for_actor
                    for trigger in item.triggered_by
                },
                key=str.lower,
            )
            trigger_text = ", ".join(triggers) if triggers else "—"
            trigger_item = QGraphicsTextItem(_wrap_label(trigger_text, 42))
            trigger_item.setDefaultTextColor(QColor("#e2e8f0"))
            trigger_item.setTextWidth(310)
            trigger_item.setPos(trigger_x, y + 4)
            scene.addItem(trigger_item)
    return scene

def build_buffer_history_scene(
    agent_name: str,
    history: dict[str, list[dict[str, Any]]],
) -> QGraphicsScene:
    scene = _new_scene()
    _add_scene_title(scene, f"Buffer history — {agent_name}")
    if not history:
        _add_empty_message(scene, "No buffer history is available yet.")
        return scene

    max_time = max(
        [
            float(entry.get("timestamp", 0.0))
            for entries in history.values()
            for entry in entries
        ]
        or [1.0]
    )
    max_time = max(max_time, 1.0)
    left = 210.0
    row_height = 84.0
    width = 1040.0
    for index, (buffer_name, entries) in enumerate(sorted(history.items())):
        y = 90.0 + index * row_height
        label = QGraphicsSimpleTextItem(buffer_name)
        label.setBrush(QBrush(TEXT_COLOR))
        label.setPos(24, y - 10)
        scene.addItem(label)
        baseline = QPainterPath(QPointF(left, y + 10))
        baseline.lineTo(left + width, y + 10)
        _add_path(scene, baseline, QPen(QColor("#334155"), 1.3))
        previous: QPointF | None = None
        for entry in entries:
            timestamp = float(entry.get("timestamp", 0.0))
            point = QPointF(left + (timestamp / max_time) * width, y + 10)
            if previous is not None:
                path = QPainterPath(previous)
                path.lineTo(point)
                _add_path(scene, path, QPen(QColor("#64748b"), 1.5))
            change = str(entry.get("change", "content_changed"))
            color = {
                "initial": QColor("#38bdf8"),
                "filled": QColor("#22c55e"),
                "cleared": QColor("#ef4444"),
                "state_changed": QColor("#f59e0b"),
                "content_changed": QColor("#a78bfa"),
                "module_changed": QColor("#e879f9"),
            }.get(change, QColor("#94a3b8"))
            marker = QGraphicsEllipseItem(point.x() - 7, point.y() - 7, 14, 14)
            marker.setPen(QPen(QColor("#e2e8f0"), 1.0))
            marker.setBrush(QBrush(color))
            marker.setToolTip(
                f"t={timestamp:.3f}\nchange={change}\n"
                f"state={entry.get('snapshot', {}).get('state')}"
            )
            scene.addItem(marker)
            previous = point
    return scene


def build_jump_progress_scene(
    analysis: AgentStaticAnalysis,
    target_production: str,
    fired_productions: list[str],
) -> QGraphicsScene:
    """Render a jump path including adapter overrides between productions."""
    scene = _new_scene()
    _add_scene_title(scene, f"Jump path to production: {target_production}")
    path = analysis.transition_path_to_production(target_production)
    if not path:
        warning = QGraphicsTextItem(
            "No statically reachable path could be derived. The target is shown "
            "without claiming that it is reachable."
        )
        warning.setDefaultTextColor(QColor("#fecaca"))
        warning.setTextWidth(760)
        warning.setPos(24, 72)
        scene.addItem(warning)
        target = analysis.production(target_production)
        if target is not None:
            source = analysis.states.get(target.source_state_id)
            destination = analysis.states.get(target.target_state_id)
            _add_node(
                scene,
                QRectF(30, 170, 280, 88),
                source.label if source else target.source_label,
                QColor("#7f1d1d"),
            )
            _add_edge_label(scene, target.name, QPointF(350, 196), QColor("#fecaca"))
            _add_node(
                scene,
                QRectF(590, 170, 280, 88),
                destination.label if destination else target.target_label,
                QColor("#7f1d1d"),
            )
        return scene

    progress = _ordered_transition_progress(path, fired_productions)
    node_width, node_height, spacing = 245.0, 82.0, 150.0
    y = 150.0
    states = analysis.state_sequence_for_transition_path(path)
    for index, state in enumerate(states):
        x = 30 + index * (node_width + spacing)
        color = (
            QColor("#0e7490")
            if index == len(states) - 1 and progress >= len(path)
            else QColor("#047857")
            if index <= progress
            else QColor("#334155")
        )
        _add_node(
            scene,
            QRectF(x, y, node_width, node_height),
            state,
            color,
            wrap_width=28,
        )

    for index, transition in enumerate(path):
        source_x = 30 + index * (node_width + spacing) + node_width
        target_x = 30 + (index + 1) * (node_width + spacing)
        start = QPointF(source_x, y + node_height / 2)
        end = QPointF(target_x, y + node_height / 2)
        completed = index < progress
        active = index == progress and progress < len(path)
        base = QColor("#f0abfc") if transition.kind == "adapter" else QColor("#7dd3fc")
        color = QColor("#22c55e") if completed else base if active else QColor("#64748b")
        points = [start, end]
        halo = QPen(SCENE_BACKGROUND, 8.0)
        halo.setCapStyle(Qt.PenCapStyle.RoundCap)
        _add_polyline_path(scene, points, halo).setZValue(0.0)
        pen = QPen(color, 3.0 if completed or active else 2.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        if transition.kind == "adapter":
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([7.0, 4.0])
        _add_polyline_path(scene, points, pen).setZValue(1.0)
        _draw_arrow(scene, start, end, color)
        label = transition.label
        if transition.guard_label:
            label += "\n[" + transition.guard_label.replace("\n", "; ") + "]"
        _add_edge_label(
            scene,
            label,
            QPointF(source_x + 18, y - 58 - (index % 2) * 34),
            color,
        )

    status = QGraphicsSimpleTextItem(
        "Target production fired."
        if progress >= len(path)
        else f"Reached {progress} of {len(path)} control-flow transitions."
    )
    status.setBrush(
        QBrush(QColor("#86efac") if progress >= len(path) else QColor("#bae6fd"))
    )
    status.setPos(24, 78)
    scene.addItem(status)
    return scene

def build_declarative_memory_scene(
    snapshot: DeclarativeMemorySnapshot,
    *,
    title: str,
) -> QGraphicsScene:
    """Render a semantic memory overview without dense containment spaghetti.

    Memory membership is encoded spatially through chunk-type sections. Only
    explicit chunk references are drawn. Weaker shared-value associations remain
    available in Export for LLM and are summarized rather than rendered as a
    quadratic edge cloud.
    """
    scene = _new_scene()
    _add_scene_title(scene, title)
    legend_bounds = _add_legend(
        scene,
        [
            ("Memory", QColor("#1d4ed8"), "box"),
            ("Runtime chunk", QColor("#0f766e"), "box"),
            ("Explicit static DM chunk", QColor("#6d28d9"), "box"),
            ("Buffer links", QColor("#155e75"), "box"),
            ("Memory-write operation", QColor("#f59e0b"), "box"),
            ("Chunk reference", QColor("#38bdf8"), "line"),
            ("Shared values summarized", QColor("#94a3b8"), "box"),
        ],
        y=52,
        max_width=1500,
    )

    memory_names = snapshot.memories or sorted(
        {chunk.memory_name for chunk in snapshot.chunks}
    )
    if not memory_names:
        _add_empty_message(scene, "No declarative memory was detected.", y=118)
        return scene

    buffer_links = [
        operation for operation in snapshot.operations
        if str(operation.get("mode")) == "buffer_link"
    ]
    memory_ops = [
        operation for operation in snapshot.operations
        if str(operation.get("mode")) != "buffer_link"
    ]
    shared_edges = [edge for edge in snapshot.edges if edge.relation == "shared_value"]
    reference_edges = [edge for edge in snapshot.edges if edge.relation == "reference"]

    node_rects: dict[str, QRectF] = {}
    node_specs: dict[str, tuple[str, QColor, int, QColor | None]] = {}
    edge_specs: list[tuple[LayoutEdge, QColor, Qt.PenStyle, str]] = []

    top = legend_bounds.bottom() + 92.0
    section_width = 350.0
    section_gap = 76.0
    section_columns = 4
    left = 42.0

    # Memory roots form a small, stable header row.
    memory_node_ids: dict[str, str] = {}
    for index, memory_name in enumerate(memory_names):
        node_id = f"memory:{memory_name}"
        memory_node_ids[memory_name] = node_id
        rect = QRectF(left + index * 390.0, top, 330.0, 68.0)
        node_rects[node_id] = rect
        node_specs[node_id] = (
            f"Memory: {memory_name}", QColor("#1d4ed8"), 36, QColor("#bfdbfe")
        )

    # Aggregate all linked buffers into one readable node instead of eight
    # visually identical routes.
    if buffer_links:
        names = sorted({str(item.get("actor", "buffer")) for item in buffer_links})
        buffer_id = "buffer-links"
        buffer_label = "Buffers linked by pyactr\n" + "\n".join(names)
        height = max(76.0, 34.0 + len(names) * 22.0)
        rect = QRectF(left, top + 108.0, 350.0, height)
        node_rects[buffer_id] = rect
        node_specs[buffer_id] = (
            buffer_label, QColor("#155e75"), 42, QColor("#a5f3fc")
        )

    chunks_by_key: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for chunk in snapshot.chunks:
        chunks_by_key[(chunk.memory_name, chunk.chunk_type)].append(chunk)

    preferred_types = [
        "semantic_concept", "knowledge_relation", "strategy_schema",
        "cell_memory", "spatial_relation", "target_memory", "episode_memory",
    ]
    type_order = {name: index for index, name in enumerate(preferred_types)}
    section_keys = sorted(
        chunks_by_key,
        key=lambda key: (
            memory_names.index(key[0]) if key[0] in memory_names else 10**6,
            type_order.get(key[1], 10**5), key[1].casefold(),
        ),
    )

    # Pre-calculate section heights so rows never overlap.
    section_heights: dict[tuple[str, str], float] = {}
    chunk_heights: dict[str, float] = {}
    for key in section_keys:
        total = 58.0
        for chunk in chunks_by_key[key]:
            detail = chunk.label
            if chunk.traces:
                detail += "\ntraces=" + ", ".join(f"{value:.3f}" for value in chunk.traces[-4:])
            if chunk.activation is not None:
                detail += f"\nactivation={chunk.activation:.3f}"
            height = max(
                92.0,
                _label_rect(_wrap_label(detail, 40), QFont("Sans Serif", 9), section_width, 28).height(),
            )
            chunk_heights[chunk.chunk_id] = height
            total += height + 24.0
        section_heights[key] = total + 18.0

    section_top = top + max(
        210.0,
        (node_rects.get("buffer-links") or QRectF()).bottom() - top + 54.0,
    )
    row_tops: list[float] = []
    current_y = section_top
    for row_start in range(0, len(section_keys), section_columns):
        row = section_keys[row_start:row_start + section_columns]
        row_tops.append(current_y)
        current_y += max((section_heights[key] for key in row), default=0.0) + 72.0

    chunk_ids: dict[str, str] = {}
    semantic_column_by_node: dict[str, int] = {}
    for section_index, key in enumerate(section_keys):
        memory_name, chunk_type = key
        row = section_index // section_columns
        column = section_index % section_columns
        x = left + column * (section_width + section_gap)
        y = row_tops[row]
        header_id = f"section:{memory_name}:{chunk_type}"
        header_rect = QRectF(x, y, section_width, 54.0)
        node_rects[header_id] = header_rect
        semantic_column_by_node[header_id] = column
        node_specs[header_id] = (
            f"{chunk_type}\n{len(chunks_by_key[key])} chunk(s)",
            QColor("#334155"), 42, QColor("#94a3b8"),
        )
        chunk_y = header_rect.bottom() + 22.0
        for chunk in chunks_by_key[key]:
            detail = chunk.label
            if chunk.traces:
                detail += "\ntraces=" + ", ".join(f"{value:.3f}" for value in chunk.traces[-4:])
            if chunk.activation is not None:
                detail += f"\nactivation={chunk.activation:.3f}"
            chunk_id = f"chunk:{chunk.chunk_id}"
            chunk_ids[chunk.chunk_id] = chunk_id
            rect = QRectF(x, chunk_y, section_width, chunk_heights[chunk.chunk_id])
            node_rects[chunk_id] = rect
            semantic_column_by_node[chunk_id] = column
            node_specs[chunk_id] = (
                detail,
                QColor("#0f766e") if chunk.source == "runtime" else QColor("#6d28d9"),
                40,
                QColor("#dbeafe"),
            )
            chunk_y = rect.bottom() + 24.0

    # Aggregate repeated memory writes by actor/mode/memory.
    operation_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for operation in memory_ops:
        operation_groups[(
            str(operation.get("actor", "code")),
            str(operation.get("mode", "access")),
            str(operation.get("memory_name", "decmem")),
        )].append(operation)
    operations_y = current_y
    for index, (key, values) in enumerate(sorted(operation_groups.items())):
        actor, mode, memory_name = key
        column = index % 3
        row = index // 3
        node_id = f"operation-group:{index}"
        details = [str(item.get("detail", "")) for item in values if item.get("detail")]
        preview = ", ".join(details[:4])
        if len(details) > 4:
            preview += f", +{len(details) - 4} more"
        label = f"{actor}\n{mode} → {memory_name} · {len(values)} operation(s)"
        if preview:
            label += "\n" + preview
        rect = QRectF(left + column * 470.0, operations_y + row * 116.0, 430.0, 88.0)
        color = QColor("#be123c") if mode in {"delete", "clear"} else QColor("#f59e0b")
        node_rects[node_id] = rect
        node_specs[node_id] = (label, color, 52, QColor("#e2e8f0"))

    # Only semantically explicit references are rendered as graph edges.
    for index, edge in enumerate(reference_edges):
        source = chunk_ids.get(edge.source_id)
        target = chunk_ids.get(edge.target_id)
        if source and target:
            edge_specs.append((
                LayoutEdge(f"chunk-reference:{index}", source, target, "reference"),
                QColor("#38bdf8"), Qt.PenStyle.SolidLine, edge.label,
            ))

    summary_y = operations_y + ((len(operation_groups) + 2) // 3) * 116.0 + 24.0
    summary_id = "shared-value-summary"
    summary_rect = QRectF(left, summary_y, 700.0, 72.0)
    node_rects[summary_id] = summary_rect
    node_specs[summary_id] = (
        f"Shared-value associations summarized: {len(shared_edges)}\n"
        "The complete association set remains available through Export for LLM.",
        QColor("#334155"), 78, QColor("#94a3b8"),
    )

    for node_id, rect in node_rects.items():
        label, color, wrap, border = node_specs[node_id]
        _add_node(scene, rect, label, color, wrap_width=wrap, border_color=border)

    layout_edge_values = [spec[0] for spec in edge_specs]
    display_routes = route_semantic_columns(
        node_rects,
        layout_edge_values,
        column_by_node=semantic_column_by_node,
        section_top=section_top,
        lane_gap=22.0,
    )

    edge_render = {spec[0].edge_id: spec[1:] for spec in edge_specs}
    label_font = QFont("Sans Serif", 9)
    label_metrics = QFontMetrics(label_font)
    label_sizes = {
        edge_id: (
            max(42.0, float(label_metrics.horizontalAdvance(str(values[2]))) + 18.0),
            25.0,
        )
        for edge_id, values in edge_render.items() if values[2]
    }
    label_positions = assign_label_positions(
        display_routes.values(), node_rects.values(),
        label_width=42.0, label_height=25.0, label_sizes=label_sizes,
    )
    for edge_id, route in display_routes.items():
        color, style, label_text = edge_render[edge_id]
        halo = QPen(SCENE_BACKGROUND, 7.5)
        halo.setCapStyle(Qt.PenCapStyle.RoundCap)
        halo.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        _add_polyline_path(scene, route.points, halo).setZValue(0.0)
        pen = QPen(color, 2.2)
        pen.setStyle(style)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        _add_polyline_path(scene, route.points, pen).setZValue(1.0)
        if len(route.points) >= 2:
            _draw_arrow(scene, route.points[-2], route.points[-1], color)
        if label_text:
            _add_edge_label(scene, label_text, label_positions[edge_id], color)
    return scene


def _rect_union_for_scene(rects: Iterable[QRectF], routes: Iterable[Any]) -> QRectF:
    values = [QRectF(rect) for rect in rects]
    for route in routes:
        if route.points:
            xs = [point.x() for point in route.points]
            ys = [point.y() for point in route.points]
            values.append(QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))
    if not values:
        return QRectF()
    result = QRectF(values[0])
    for rect in values[1:]:
        result = result.united(rect)
    return result


def _ordered_transition_progress(
    path: list[StateTransitionAnalysis], fired_productions: list[str]
) -> int:
    """Count transitions reached; adapter edges complete with their trigger rule."""
    fired_index = 0
    transition_index = 0
    while transition_index < len(path):
        transition = path[transition_index]
        if transition.kind == "adapter":
            trigger = transition.trigger_production
            if trigger and any(
                name.casefold() == trigger.casefold()
                for name in fired_productions[:fired_index]
            ):
                transition_index += 1
                continue
            break
        while fired_index < len(fired_productions):
            fired = fired_productions[fired_index]
            fired_index += 1
            if (
                transition.production_name
                and fired.casefold() == transition.production_name.casefold()
            ):
                transition_index += 1
                break
        else:
            break
    return transition_index

def _new_scene() -> QGraphicsScene:
    scene = QGraphicsScene()
    scene.setBackgroundBrush(QBrush(SCENE_BACKGROUND))
    return scene


def _add_scene_title(scene: QGraphicsScene, text: str) -> None:
    title = QGraphicsSimpleTextItem(text)
    font = QFont("Sans Serif", 11)
    font.setBold(True)
    title.setFont(font)
    title.setBrush(QBrush(TEXT_COLOR))
    title.setPos(20, 12)
    scene.addItem(title)


def _add_empty_message(scene: QGraphicsScene, text: str, *, y: float = 82.0) -> None:
    item = QGraphicsTextItem(text)
    item.setDefaultTextColor(MUTED_TEXT)
    item.setTextWidth(760)
    item.setPos(24, y)
    scene.addItem(item)


def _add_legend(
    scene: QGraphicsScene,
    items: list[tuple[str, QColor, str]],
    *,
    y: float,
    max_width: float = 1050,
) -> QRectF:
    """Render a protected legend panel and return its occupied bounds."""
    x = 24.0
    row = 0
    placed: list[tuple[float, float, str, QColor, str]] = []
    for label_text, color, kind in items:
        estimated = 44 + len(label_text) * 7
        if x + estimated > max_width and x > 24:
            row += 1
            x = 24.0
        current_y = y + row * 34
        placed.append((x, current_y, label_text, color, kind))
        x += estimated

    bounds = QRectF(14.0, y - 12.0, max_width + 4.0, (row + 1) * 34.0 + 18.0)
    panel = QGraphicsRectItem(bounds)
    panel.setPen(QPen(QColor("#334155"), 0.8))
    panel.setBrush(QBrush(QColor(15, 23, 42, 248)))
    panel.setZValue(40.0)
    panel.setData(0, "legend-panel")
    scene.addItem(panel)

    for x, current_y, label_text, color, kind in placed:
        if kind == "box":
            swatch = QGraphicsRectItem(QRectF(x, current_y, 20, 20))
            swatch.setPen(QPen(QColor("#cbd5e1"), 1.0))
            swatch.setBrush(QBrush(color))
            swatch.setZValue(41.0)
            scene.addItem(swatch)
        else:
            path = QPainterPath(QPointF(x, current_y + 10))
            path.lineTo(x + 26, current_y + 10)
            pen = QPen(color, 2.2)
            if kind == "dash":
                pen.setStyle(Qt.PenStyle.DashLine)
            item = _add_path(scene, path, pen)
            item.setZValue(41.0)
        label = QGraphicsSimpleTextItem(label_text)
        label.setBrush(QBrush(TEXT_COLOR))
        label.setPos(x + 32, current_y - 2)
        label.setZValue(42.0)
        scene.addItem(label)
    return bounds


def _add_node(
    scene: QGraphicsScene,
    rect: QRectF,
    label: str,
    color: QColor,
    *,
    wrap_width: int = 38,
    border_color: QColor | None = None,
    border_width: float = 1.5,
) -> QGraphicsRectItem:
    node = QGraphicsRectItem(rect)
    node.setPen(QPen(border_color or QColor("#dbe4f0"), border_width))
    node.setBrush(QBrush(color))
    node.setZValue(5.0)
    scene.addItem(node)
    text = QGraphicsTextItem(_wrap_label(label, wrap_width))
    text.setDefaultTextColor(TEXT_COLOR)
    text.setTextWidth(rect.width() - 18)
    text.setPos(rect.x() + 9, rect.y() + 8)
    text.setZValue(6.0)
    scene.addItem(text)
    return node


def _add_route_bundle_markers(scene: QGraphicsScene, routes: list[Any]) -> None:
    """Mark intentional shared trunks so merges and splits remain traceable."""
    segment_routes: dict[tuple[float, float, float, float], set[str]] = defaultdict(set)
    segment_points: dict[tuple[float, float, float, float], tuple[QPointF, QPointF]] = {}
    for route in routes:
        for first, second in zip(route.points, route.points[1:]):
            a = (round(first.x(), 3), round(first.y(), 3))
            b = (round(second.x(), 3), round(second.y(), 3))
            key = (*a, *b) if a <= b else (*b, *a)
            segment_routes[key].add(route.edge.edge_id)
            segment_points[key] = (first, second)
    marked: set[tuple[float, float]] = set()
    for key, edge_ids in segment_routes.items():
        if len(edge_ids) < 2:
            continue
        first, second = segment_points[key]
        for point in (first, second):
            point_key = (round(point.x(), 3), round(point.y(), 3))
            if point_key in marked:
                continue
            marked.add(point_key)
            marker = QGraphicsEllipseItem(point.x() - 4.5, point.y() - 4.5, 9.0, 9.0)
            marker.setPen(QPen(QColor("#f8fafc"), 1.2))
            marker.setBrush(QBrush(QColor("#334155")))
            marker.setToolTip(
                "Shared route bus: " + ", ".join(sorted(edge_ids))
            )
            scene.addItem(marker)


def _add_polyline_path(
    scene: QGraphicsScene, points: list[QPointF], pen: QPen
) -> QGraphicsPathItem:
    if not points:
        return _add_path(scene, QPainterPath(), pen)
    path = QPainterPath(points[0])
    for point in points[1:]:
        path.lineTo(point)
    return _add_path(scene, path, pen)


def _add_path(
    scene: QGraphicsScene, path: QPainterPath, pen: QPen
) -> QGraphicsPathItem:
    item = QGraphicsPathItem(path)
    item.setPen(pen)
    item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
    scene.addItem(item)
    return item


def _numeric_code(code: str) -> int:
    try:
        return int(code[1:])
    except (TypeError, ValueError, IndexError):
        return 10**9


def _ordered_transitions_for_codes(
    transitions: list[StateTransitionAnalysis],
    geometry: Any,
) -> list[StateTransitionAnalysis]:
    """Return stable P/A numbering based on the rendered graph geometry.

    Production and adapter codes are independent.  Within each family, source
    nodes are ordered by rank and screen position, followed by target position
    and the semantic transition label.  The result is deterministic and mirrors
    how a reader scans the graph.
    """
    def key(transition: StateTransitionAnalysis) -> tuple[Any, ...]:
        source = geometry.placements[transition.source_state_id]
        target = geometry.placements[transition.target_state_id]
        family = 0 if transition.kind == "production" else 1
        return (
            family,
            source.rank,
            round(source.rect.top(), 3),
            round(source.rect.left(), 3),
            target.rank,
            round(target.rect.top(), 3),
            round(target.rect.left(), 3),
            transition.label.casefold(),
            transition.transition_id,
        )

    return sorted(transitions, key=key)


def _compact_code_range(codes: list[str]) -> str:
    """Compact a visual edge bundle without hiding its individual transitions."""
    if not codes:
        return ""
    if len(codes) == 1:
        return codes[0]
    prefix = codes[0][0]
    numbers = sorted(_numeric_code(code) for code in codes)
    if all(b == a + 1 for a, b in zip(numbers, numbers[1:])):
        return f"{prefix}{numbers[0]}–{prefix}{numbers[-1]}"
    if len(codes) <= 3:
        return ", ".join(codes)
    return f"{codes[0]} +{len(codes) - 1}"


def _add_edge_label(
    scene: QGraphicsScene,
    text: str,
    position: QPointF,
    color: QColor,
) -> QGraphicsSimpleTextItem:
    label = QGraphicsSimpleTextItem(text)
    label.setBrush(QBrush(color))
    label.setPos(position)
    bounds = label.boundingRect().adjusted(-6, -3, 6, 3)
    background = QGraphicsRectItem(
        QRectF(
            position.x() + bounds.x(),
            position.y() + bounds.y(),
            bounds.width(),
            bounds.height(),
        )
    )
    background.setPen(QPen(QColor("#334155"), 0.8))
    background.setBrush(QBrush(LABEL_BACKGROUND))
    background.setZValue(8.0)
    label.setZValue(9.0)
    scene.addItem(background)
    scene.addItem(label)
    return label


def _draw_arrow(scene: QGraphicsScene, start: QPointF, end: QPointF, color: QColor) -> None:
    angle = math.atan2(end.y() - start.y(), end.x() - start.x())
    arrow_size = 11
    p1 = end - QPointF(
        math.cos(angle - math.pi / 6) * arrow_size,
        math.sin(angle - math.pi / 6) * arrow_size,
    )
    p2 = end - QPointF(
        math.cos(angle + math.pi / 6) * arrow_size,
        math.sin(angle + math.pi / 6) * arrow_size,
    )
    first = scene.addLine(end.x(), end.y(), p1.x(), p1.y(), QPen(color, 2.0))
    second = scene.addLine(end.x(), end.y(), p2.x(), p2.y(), QPen(color, 2.0))
    first.setZValue(4.0)
    second.setZValue(4.0)


def _wrap_label(text: str, width: int) -> str:
    lines: list[str] = []
    for raw in text.splitlines() or [text]:
        lines.extend(textwrap.wrap(raw, width=width) or [raw])
    return "\n".join(lines)


def _label_rect(text: str, font: QFont, width: int, padding: int) -> QRectF:
    metrics = QFontMetrics(font)
    height = 0
    for line in text.splitlines() or [text]:
        height += metrics.boundingRect(line).height() + 3
    return QRectF(0, 0, width, max(60, height + padding))


def _bfs_depths(graph: dict[str, set[str]], start: str) -> dict[str, int]:
    depths = {start: 0}
    queue = [start]
    while queue:
        current = queue.pop(0)
        for nxt in graph.get(current, set()):
            if nxt not in depths:
                depths[nxt] = depths[current] + 1
                queue.append(nxt)
    return depths
