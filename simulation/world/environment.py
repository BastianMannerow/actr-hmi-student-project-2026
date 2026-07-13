"""Grid-world backends for virtual and ROS-connected TurtleBot runs."""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Tuple

from simulation.world.entities import SpatialEntity, Target


class Environment:
    """Collision-aware virtual grid environment."""

    backend_name = "virtual"

    def __init__(
        self,
        level_matrix: List[List[Any]],
        gui: Optional[Any] = None,
        *,
        simulation: Any | None = None,
    ) -> None:
        self.level_matrix: List[List[List[Any]]] = [
            [
                cell
                if isinstance(cell, list)
                else ([] if cell is None else [cell])
                for cell in row
            ]
            for row in level_matrix
        ]
        self.gui = gui
        self.simulation = simulation
        self._update_gui()

    def _update_gui(self) -> None:
        if self.gui is None:
            return
        refresh = getattr(self.gui, "refresh", None)
        if callable(refresh):
            refresh()
            return
        update = getattr(self.gui, "update", None)
        if callable(update):
            update()

    def find_agent(self, agent: Any) -> Optional[Tuple[int, int]]:
        for row_index, row in enumerate(self.level_matrix):
            for column_index, cell in enumerate(row):
                if agent in cell:
                    return row_index, column_index
        return None

    def objects_at(self, row: int, column: int) -> list[Any]:
        if not (
            0 <= row < len(self.level_matrix)
            and self.level_matrix
            and 0 <= column < len(self.level_matrix[0])
        ):
            return []
        return list(self.level_matrix[row][column])

    def is_blocked(self, row: int, column: int) -> bool:
        return any(
            bool(getattr(item, "blocks_movement", False))
            for item in self.objects_at(row, column)
        )

    def target_positions(self) -> list[tuple[int, int]]:
        return [
            (row, column)
            for row, values in enumerate(self.level_matrix)
            for column, cell in enumerate(values)
            if any(isinstance(item, Target) or getattr(item, "is_target", False) for item in cell)
        ]

    def move_agent(self, agent: Any, dr: int, dc: int) -> bool:
        position = self.find_agent(agent)
        if position is None or not self.level_matrix or not self.level_matrix[0]:
            return False
        row, column = position
        next_row, next_column = row + dr, column + dc
        if not (
            0 <= next_row < len(self.level_matrix)
            and 0 <= next_column < len(self.level_matrix[0])
        ):
            self.register_bumping(agent, reason="boundary")
            return False
        if self.is_blocked(next_row, next_column):
            self.register_bumping(agent, reason="obstacle")
            return False
        try:
            self.level_matrix[row][column].remove(agent)
        except ValueError:
            return False
        self.level_matrix[next_row][next_column].append(agent)
        self._update_gui()
        return True

    def move_agent_top(self, agent: Any) -> bool:
        return self.move_agent(agent, -1, 0)

    def move_agent_bottom(self, agent: Any) -> bool:
        return self.move_agent(agent, 1, 0)

    def move_agent_left(self, agent: Any) -> bool:
        return self.move_agent(agent, 0, -1)

    def move_agent_right(self, agent: Any) -> bool:
        return self.move_agent(agent, 0, 1)

    def register_bumping(self, agent: Any, *, reason: str = "obstacle") -> None:
        middleman = getattr(agent, "middleman", None)
        detect = getattr(middleman, "detect_bump", None)
        if callable(detect):
            detect(agent, reason=reason)

    def remove_agent_from_game(self, agent: Any) -> None:
        position = self.find_agent(agent)
        if position is not None:
            row, column = position
            try:
                self.level_matrix[row][column].remove(agent)
            except ValueError:
                pass
        self._update_gui()

    def set_gui(self, gui: Any) -> None:
        self.gui = gui
        self._update_gui()

    def close(self) -> None:
        return None


class RosEnvironment(Environment):
    """ROS-backed environment with a shadow grid for the existing GUI."""

    backend_name = "ros"

    def __init__(
        self,
        level_matrix: List[List[Any]],
        *,
        simulation: Any,
        ros_config: Any,
        gui: Optional[Any] = None,
    ) -> None:
        super().__init__(level_matrix, gui, simulation=simulation)
        from simulation.integrations.ros_turtle_bridge import RosTurtleBridge

        self.bridge = RosTurtleBridge(
            agents=list(getattr(simulation, "agent_list", [])),
            config=ros_config,
            on_motion_finished=self._motion_finished,
            on_bump=self._ros_bump,
            on_error=self._ros_error,
        )
        self.bridge.start()
        self._pending_moves: dict[str, tuple[Any, int, int]] = {}

    def move_agent(self, agent: Any, dr: int, dc: int) -> bool:
        position = self.find_agent(agent)
        if position is None:
            return False
        row, column = position
        target = (row + dr, column + dc)
        if not (
            0 <= target[0] < len(self.level_matrix)
            and 0 <= target[1] < len(self.level_matrix[0])
        ):
            self.register_bumping(agent, reason="shadow-boundary")
            return False
        if self.is_blocked(*target):
            self.register_bumping(agent, reason="shadow-obstacle")
            return False
        name = str(getattr(agent, "name", ""))
        if name in self._pending_moves:
            return False
        # Register the move before starting the asynchronous ROS thread so an
        # exceptionally fast callback cannot outrun the shadow-grid state.
        self._pending_moves[name] = (agent, dr, dc)
        started = getattr(self.simulation, "external_motion_started", None)
        if callable(started):
            started(name)
        accepted = self.bridge.move_grid(agent, dr, dc)
        if not accepted:
            self._pending_moves.pop(name, None)
            finished = getattr(self.simulation, "external_motion_finished", None)
            if callable(finished):
                finished(name, False)
            return False
        return True

    def _motion_finished(self, agent_name: str, success: bool) -> None:
        pending = self._pending_moves.pop(agent_name, None)
        if pending is not None and success:
            agent, dr, dc = pending
            Environment.move_agent(self, agent, dr, dc)
        finished = getattr(self.simulation, "external_motion_finished", None)
        if callable(finished):
            finished(agent_name, success)

    def _ros_error(self, agent_name: str, message: str) -> None:
        callback = getattr(self.simulation, "external_motion_error", None)
        if callable(callback):
            callback(agent_name, message)

    def _ros_bump(self, agent_name: str) -> None:
        agent = next(
            (
                candidate
                for candidate in getattr(self.simulation, "agent_list", [])
                if str(getattr(candidate, "name", "")) == agent_name
            ),
            None,
        )
        if agent is not None:
            self.register_bumping(agent, reason="ros-bumper")

    def close(self) -> None:
        self.bridge.close()
