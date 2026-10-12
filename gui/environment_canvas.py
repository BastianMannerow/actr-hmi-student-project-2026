"""Cached terrain, one shared GIF decoder and cell-local dynamic repaints."""
from __future__ import annotations
from typing import Any
from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QMovie, QPainter, QPen, QPixmap, QRegion
from PyQt6.QtWidgets import QSizePolicy, QToolTip, QWidget
from gui.environment_assets import ASSET_DIR
from gui.environment_symbols import EnvironmentSymbol, draw_environment_symbol, symbol_for_agent, symbol_for_terrain

class GridCanvas(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.environment: Any | None = None
        self._grid_rect = QRectF()
        self._cell_size = 0.
        self._static_cache: QPixmap | None = None
        self._static_cache_key = None
        self._fire_cells: set[tuple[int, int]] = set()
        self._target_cells: set[tuple[int, int]] = set()
        self._reached_targets: set[tuple[int, int]] = set()
        self._scaled_frames: dict[tuple[int, int], QPixmap] = {}
        self._animation_enabled = True
        self._movie = QMovie(str(ASSET_DIR / 'fire.gif'), parent=self)
        self._movie.setCacheMode(QMovie.CacheMode.CacheAll)
        self._movie.jumpToFrame(0)
        self._movie.frameChanged.connect(self._fire_frame_changed)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName('Rescue environment: walls, uncertain fire, people and Squirtle')

    def sizeHint(self) -> QSize:
        return QSize(560, 560)

    def set_environment(self, environment: Any) -> None:
        if environment is not self.environment:
            self._reached_targets.clear()
        self.environment = environment
        self._fire_cells.clear(); self._target_cells.clear()
        self.invalidate_static_cache()
        self._sync_reached_targets()
        consume = getattr(environment, 'consume_render_changes', None)
        if callable(consume): consume()
        self.update()

    def _occupants(self) -> dict[tuple[int, int], list[Any]]:
        indexed = getattr(self.environment, 'positioned_agents', None)
        cells: dict[tuple[int, int], list[Any]] = {}
        if callable(indexed):
            for occupant, position in indexed(): cells.setdefault(position, []).append(occupant)
        else:
            for row, values in enumerate(getattr(self.environment, 'level_matrix', ())):
                for column, cell in enumerate(values):
                    occupants = [obj for obj in cell if getattr(obj, 'name', None)]
                    if occupants: cells[(row, column)] = occupants
        return cells

    def _sync_reached_targets(self, occupants=None) -> set[tuple[int, int]]:
        previous = set(self._reached_targets)
        reached = getattr(self.environment, 'render_reached_targets', None)
        if callable(reached): self._reached_targets.update(reached())
        # Fallback for external backends with no render history.
        positions = self._occupants() if occupants is None else occupants
        self._reached_targets.update(self._target_cells.intersection(positions))
        return self._reached_targets - previous

    def refresh_from_environment(self) -> None:
        reached = self._sync_reached_targets()
        consume = getattr(self.environment, 'consume_render_changes', None)
        dirty = consume() if callable(consume) else None
        if dirty is None:
            self.invalidate_static_cache(); self.update()
        elif dirty or reached:
            self._update_cells(set(dirty) | reached)

    def _cell_rect(self, position: tuple[int, int]) -> QRectF:
        row, column = position
        return QRectF(self._grid_rect.left() + column * self._cell_size,
                      self._grid_rect.top() + row * self._cell_size,
                      self._cell_size, self._cell_size)

    def _update_cells(self, positions) -> None:
        if self._cell_size <= 0:
            self.update(); return
        region = QRegion()
        for position in positions:
            region |= QRegion(self._cell_rect(position).adjusted(-2, -2, 2, 2).toAlignedRect())
        if not region.isEmpty(): self.update(region)

    def invalidate_static_cache(self) -> None:
        self._static_cache = None; self._static_cache_key = None

    def resizeEvent(self, event) -> None:
        self.invalidate_static_cache(); self._scaled_frames.clear()
        super().resizeEvent(event)

    def set_animation_enabled(self, enabled: bool) -> None:
        self._animation_enabled = bool(enabled)
        self._sync_animation()

    def _sync_animation(self) -> None:
        active = self._animation_enabled and self.isVisible() and bool(self._fire_cells)
        if active and self._movie.state() == QMovie.MovieState.NotRunning:
            self._movie.start()
        elif self._movie.state() != QMovie.MovieState.NotRunning:
            self._movie.setPaused(not active)

    def showEvent(self, event) -> None:
        super().showEvent(event); self._sync_animation()

    def hideEvent(self, event) -> None:
        self._movie.setPaused(True); super().hideEvent(event)

    def _fire_frame_changed(self, frame: int) -> None:
        if self.isVisible(): self._update_cells(self._fire_cells)

    def _fire_pixmap(self) -> QPixmap:
        size = max(1, round(self._cell_size))
        key = (self._movie.currentFrameNumber(), size)
        if key not in self._scaled_frames:
            if len(self._scaled_frames) >= 40: self._scaled_frames.clear()
            self._scaled_frames[key] = self._movie.currentPixmap().scaled(
                size, size, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation)
        return self._scaled_frames[key]

    def _geometry(self, rows: int, columns: int) -> None:
        size = min(max(1., self.width() - 36.) / columns, max(1., self.height() - 36.) / rows)
        self._cell_size = size
        self._grid_rect = QRectF((self.width() - size * columns) / 2,
                                 (self.height() - size * rows) / 2, size * columns, size * rows)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        matrix = getattr(self.environment, 'level_matrix', None)
        if not matrix or not matrix[0]:
            painter.fillRect(self.rect(), QColor('#0b141b'))
            painter.setPen(QColor('#8d98aa')); painter.setFont(QFont(self.font().family(), 11))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'Environment is initializing…')
            return
        rows, columns = len(matrix), len(matrix[0])
        self._geometry(rows, columns)
        key = (self.width(), self.height(), rows, columns, int(getattr(self.environment, 'static_revision', 0)))
        if self._static_cache is None or self._static_cache_key != key:
            self._static_cache = self._build_static_cache(matrix)
            self._static_cache_key = key
            self._sync_animation()
        painter.drawPixmap(0, 0, self._static_cache)
        occupants = self._occupants()
        self._sync_reached_targets(occupants)
        region = event.region()
        frame = self._fire_pixmap() if self._fire_cells else None
        for cell in self._fire_cells:
            rect = self._cell_rect(cell)
            if region.intersects(rect.toAlignedRect()):
                draw_environment_symbol(painter, rect, EnvironmentSymbol.BURNING_BUSH, fire_frame=frame)
        for cell in self._target_cells - self._reached_targets:
            rect = self._cell_rect(cell)
            if region.intersects(rect.toAlignedRect()):
                draw_environment_symbol(painter, rect, EnvironmentSymbol.FIRE_TARGET)
        for cell, agents in occupants.items():
            rect = self._cell_rect(cell)
            if region.intersects(rect.toAlignedRect()): self._draw_occupants(painter, rect, agents)

    def _build_static_cache(self, matrix) -> QPixmap:
        pixmap = QPixmap(self.size()); pixmap.fill(QColor('#0b141b'))
        painter = QPainter(pixmap)
        self._fire_cells.clear(); self._target_cells.clear()
        for row, values in enumerate(matrix):
            for column, items in enumerate(values):
                cell = (row, column); rect = self._cell_rect(cell)
                painter.fillRect(rect, QColor('#1e3037') if (row + column) % 2 else QColor('#21363c'))
                painter.setPen(QPen(QColor('#2d434a'), .6)); painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(rect)
                for item in items:
                    if getattr(item, 'name', None) or not getattr(item, 'symbol', None): continue
                    symbol = symbol_for_terrain(item)
                    if symbol == EnvironmentSymbol.FIRE_TARGET: self._target_cells.add(cell)
                    elif symbol in {EnvironmentSymbol.BURNING_BUSH, EnvironmentSymbol.UNKNOWN_TERRAIN}:
                        self._fire_cells.add(cell)
                    else: draw_environment_symbol(painter, rect, symbol)
        painter.setPen(QPen(QColor('#68828b'), 1.4)); painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self._grid_rect); painter.end()
        return pixmap

    def _draw_occupants(self, painter, rect, occupants) -> None:
        visible = occupants[:4]
        for index, agent in enumerate(visible):
            if len(visible) == 1:
                tile = rect.adjusted(1, 1, -1, -1)
            else:
                tile = QRectF(rect.left() + (index % 2) * rect.width() / 2,
                              rect.top() + (index // 2) * rect.height() / 2,
                              rect.width() / 2, rect.height() / 2)
            draw_environment_symbol(painter, tile, symbol_for_agent(agent))
        if len(occupants) > 4:
            painter.setPen(QColor('#ffffff')); painter.drawText(rect, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight, f'+{len(occupants)-4}')

    def mouseMoveEvent(self, event) -> None:
        matrix = getattr(self.environment, 'level_matrix', None)
        if not matrix or self._cell_size <= 0 or not self._grid_rect.contains(event.position()):
            QToolTip.hideText(); return
        column = int((event.position().x() - self._grid_rect.left()) / self._cell_size)
        row = int((event.position().y() - self._grid_rect.top()) / self._cell_size)
        if not (0 <= row < len(matrix) and 0 <= column < len(matrix[0])): return
        names = []
        for obj in matrix[row][column]:
            if getattr(obj, 'name', None): names.append(str(obj.name)); continue
            symbol = symbol_for_terrain(obj)
            names.append({EnvironmentSymbol.BURNING_TREE: 'Wall (blocked)',
                          EnvironmentSymbol.BURNING_BUSH: 'Fire (passability unknown)',
                          EnvironmentSymbol.FIRE_TARGET: 'Rescued (display)' if (row, column) in self._reached_targets else 'Person awaiting rescue',
                          EnvironmentSymbol.UNKNOWN_TERRAIN: 'Unknown terrain'}.get(symbol, ''))
        QToolTip.showText(event.globalPosition().toPoint(), f'Row {row+1}, column {column+1}\n' + '\n'.join(names), self)
