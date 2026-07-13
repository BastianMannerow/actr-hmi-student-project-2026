"""External path planning and memory adapter for :class:`JohannesAgent`."""

from __future__ import annotations

import heapq
from typing import Any

import pyactr as actr

from simulation.integrations import pyactr_extension


class JohannesAgentAdapter:
    """Read the world, maintain obstacle memory and guide ACT-R movement rules."""

    def __init__(self, _environment=None):
        self.agent_construct = None
        self.bumped = False
        self.bump_reason = "obstacle"
        self.last_direction = "none"
        self.known_obstacles: dict[tuple[int, int], str] = {}

    def extending_actr(self):
        agent = self.agent_construct
        if agent is None:
            return
        production = pyactr_extension.get_production_fired(agent)
        if not production:
            return
        if production in {"locate_self", "locate_obstacles", "locate_goal"}:
            self._locate_world()
        elif production == "pathfinding_start":
            self._prepare_next_move()
        elif production.startswith("eval_eval"):
            self._evaluate_move()
        elif production == "eval_bumped":
            self._handle_bump()

    def on_bump_detected(self, *, reason: str = "obstacle", **_kwargs):
        self.bumped = True
        self.bump_reason = reason

    def _locate_world(self) -> None:
        agent = self.agent_construct
        environment = agent.middleman.experiment_environment
        current = environment.find_agent(agent)
        targets = environment.target_positions()
        if current is None:
            return
        target = targets[0] if targets else current
        self._write_agent_buffer(current, target)
        self._scan_obstacles(environment)
        self._set_goal("locate", "ready", "locate")

    def _prepare_next_move(self) -> None:
        agent = self.agent_construct
        environment = agent.middleman.experiment_environment
        current = environment.find_agent(agent)
        targets = environment.target_positions()
        if current is None or not targets:
            self._set_goal("goal", "finished", "pathfinding")
            return
        target = min(targets, key=lambda point: abs(point[0] - current[0]) + abs(point[1] - current[1]))
        if current == target:
            self._set_goal("goal", "reached", "pathfinding")
            return
        path = self._astar(environment, current, target)
        if len(path) < 2:
            self._set_goal("goal", "finished", "pathfinding")
            return
        next_position = path[1]
        delta = (next_position[0] - current[0], next_position[1] - current[1])
        direction = {(-1, 0): "up", (1, 0): "down", (0, -1): "left", (0, 1): "right"}[delta]
        self.last_direction = direction
        chunk = actr.chunkstring(
            string=f"""
                isa path_and_obs
                check_obstacle_pos_x {next_position[1]}
                check_obstacle_pos_y {next_position[0]}
                next_pos_x {next_position[1]}
                next_pos_y {next_position[0]}
                next_pos_might_be_obstacle False
                bumped False
                direction {direction}
            """
        )
        pyactr_extension.replace_buffer(agent, "path_and_obs_imaginal", chunk)
        self._set_goal("moving", "move", "pathfinding")

    def _evaluate_move(self) -> None:
        agent = self.agent_construct
        environment = agent.middleman.experiment_environment
        current = environment.find_agent(agent)
        targets = environment.target_positions()
        if self.bumped:
            # The ACT-R production ``eval_bumped`` owns the memory update.
            # Keeping the write there avoids recording the same obstacle twice.
            self._set_goal("eval", "bumped", "moving")
            return
        if current is None:
            return
        target = targets[0] if targets else current
        self._write_agent_buffer(current, target)
        if current in targets:
            self._set_goal("goal", "reached", "eval")
        else:
            self._set_goal("pathfinding", "start", "eval")


    def _handle_bump(self) -> None:
        """Persist the obstacle and return ACT-R to the retrieval phase."""
        self._remember_bump()
        self._set_goal("retrieval", "request", "eval")

    def _remember_bump(self) -> None:
        agent = self.agent_construct
        environment = agent.middleman.experiment_environment
        current = environment.find_agent(agent)
        if current is None:
            return
        delta = {
            "up": (-1, 0),
            "down": (1, 0),
            "left": (0, -1),
            "right": (0, 1),
        }.get(self.last_direction, (0, 0))
        obstacle = (current[0] + delta[0], current[1] + delta[1])
        self.known_obstacles[obstacle] = "solid"
        chunk = actr.chunkstring(
            string=f"""
                isa obstacle
                obstacle_pos_x {obstacle[1]}
                obstacle_pos_y {obstacle[0]}
                status solid
            """
        )
        pyactr_extension.add_to_declarative_memory(agent, chunk)
        pyactr_extension.replace_buffer(agent, "obstacle_update_imaginal", chunk)
        self.bumped = False

    def _write_agent_buffer(self, current: tuple[int, int], target: tuple[int, int]) -> None:
        chunk = actr.chunkstring(
            string=f"""
                isa agent
                current_pos_x {current[1]}
                current_pos_y {current[0]}
                goal_pos_x {target[1]}
                goal_pos_y {target[0]}
                start_pos_x {current[1]}
                start_pos_y {current[0]}
            """
        )
        pyactr_extension.replace_buffer(self.agent_construct, "imaginal_agent", chunk)

    def _scan_obstacles(self, environment: Any) -> None:
        for row, values in enumerate(environment.level_matrix):
            for column, cell in enumerate(values):
                if environment.is_blocked(row, column):
                    self.known_obstacles[(row, column)] = "solid"

    def _set_goal(self, phase: str, state: str, previous: str) -> None:
        chunk = actr.chunkstring(
            string=f"""
                isa goal
                phase {phase}
                state {state}
                prev_phase {previous}
            """
        )
        pyactr_extension.set_goal(self.agent_construct, chunk)

    def _astar(
        self,
        environment: Any,
        start: tuple[int, int],
        target: tuple[int, int],
    ) -> list[tuple[int, int]]:
        queue: list[tuple[int, int, tuple[int, int]]] = [(0, 0, start)]
        came_from: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        costs = {start: 0}
        sequence = 0
        while queue:
            _, _, current = heapq.heappop(queue)
            if current == target:
                break
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nxt = (current[0] + dr, current[1] + dc)
                if not (
                    0 <= nxt[0] < len(environment.level_matrix)
                    and 0 <= nxt[1] < len(environment.level_matrix[0])
                ):
                    continue
                if environment.is_blocked(*nxt) or self.known_obstacles.get(nxt) == "solid":
                    continue
                new_cost = costs[current] + 1
                if new_cost >= costs.get(nxt, 10**9):
                    continue
                costs[nxt] = new_cost
                priority = new_cost + abs(target[0] - nxt[0]) + abs(target[1] - nxt[1])
                sequence += 1
                heapq.heappush(queue, (priority, sequence, nxt))
                came_from[nxt] = current
        if target not in came_from:
            return [start]
        path = [target]
        while path[-1] != start:
            parent = came_from[path[-1]]
            if parent is None:
                break
            path.append(parent)
        path.reverse()
        return path
