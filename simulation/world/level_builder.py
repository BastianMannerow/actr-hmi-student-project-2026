"""Randomized firefighter TurtleBot level based on the former Johannes Lab.

The map retains the 22 x 25 geometry and permanent wall layout. Every build:

* places all enabled agents on distinct random free cells;
* places exactly three fire targets on distinct random free cells;
* places burning bushes on strategically relevant shortest-path cells;
* randomly determines whether each bush is passable;
* guarantees that every agent can reach every target even if all bushes turn
  out to be impassable.
"""

from __future__ import annotations

import random
from collections import deque
from itertools import combinations
from typing import Any, Iterable, Optional, Sequence

from simulation.world.entities import BurningBush, BurningTree, FireTarget


LEVEL_DIMENSIONS: dict[str, tuple[int, int]] = {
    "turtle_simulation": (22, 25),  # (height, width)
}


def level_dimensions(level_type: str) -> tuple[int, int]:
    try:
        return LEVEL_DIMENSIONS[level_type]
    except KeyError as exc:
        raise ValueError(f"Unknown virtual level: {level_type!r}") from exc


def build_level(
    level_type: str,
    agents: Sequence[Any],
    rng: Optional[random.Random] = None,
) -> list[list[Any | None]]:
    if level_type != "turtle_simulation":
        raise ValueError(f"Unknown virtual level: {level_type!r}")
    height, width = level_dimensions(level_type)
    return _turtle_simulation(height, width, agents, rng or random.Random())


def _empty(height: int, width: int) -> list[list[Any | None]]:
    return [[None for _ in range(width)] for _ in range(height)]


def _permanent_tree_coordinates(height: int, width: int) -> set[tuple[int, int]]:
    """Return the unchanged permanent-wall geometry of Johannes Lab."""
    trees: set[tuple[int, int]] = set()
    for row in range(height):
        for column in range(width):
            if (
                row in {0, height - 1}
                or column in {0, width - 1}
                or (12 <= column <= 24 and 1 <= row <= 5)
                or (4 <= row <= 17 and 1 <= column <= 3)
                or (4 <= row <= 6 and 4 <= column <= 8)
                or (15 <= row <= 17 and 4 <= column <= 8)
                or (19 <= row <= 20 and 10 <= column <= 16)
                or (14 <= row <= 16 and 17 <= column <= 23)
                or (17 <= row <= 20 and 21 <= column <= 23)
                or (row == 6 and 18 <= column <= 20)
                or (11 <= row <= 14 and 11 <= column <= 14)
            ):
                trees.add((row, column))

    # Retain the former local obstacle geometry around the old Johannes target,
    # but express every definite obstruction as a burning tree.
    trees.update(
        {
            (13, 17),
            (12, 17),
            (12, 18),
            (14, 18),
            (14, 19),
            (14, 20),
        }
    )
    return trees


def _turtle_simulation(
    height: int,
    width: int,
    agents: Sequence[Any],
    rng: random.Random,
) -> list[list[Any | None]]:
    matrix = _empty(height, width)
    trees = _permanent_tree_coordinates(height, width)
    for row, column in trees:
        matrix[row][column] = BurningTree()

    component = _largest_open_component(height, width, trees)
    required = len(agents) + 3
    if len(component) < required:
        raise ValueError("Turtle Simulation has too few reachable cells.")

    # Spread objectives to make navigation and partial observability meaningful.
    selected = _select_spread_coordinates(component, required, rng)
    agent_positions = selected[: len(agents)]
    target_positions = selected[len(agents) :]

    objectives = list(agent_positions) + list(target_positions)
    bush_positions = _select_strategic_bushes(
        height=height,
        width=width,
        permanent_blocks=trees,
        objectives=objectives,
        rng=rng,
        desired_count=6,
    )

    # The all-blocked validation in _select_strategic_bushes guarantees target
    # reachability for every possible random combination of bush passability.
    for row, column in bush_positions:
        matrix[row][column] = BurningBush(passable=rng.random() < 0.50)

    for row, column in target_positions:
        matrix[row][column] = FireTarget()

    for agent, (row, column) in zip(agents, agent_positions):
        if matrix[row][column] is not None:
            raise RuntimeError("Internal level placement collision.")
        matrix[row][column] = agent

    return matrix


def _largest_open_component(
    height: int,
    width: int,
    blocked: set[tuple[int, int]],
) -> list[tuple[int, int]]:
    remaining = {
        (row, column)
        for row in range(height)
        for column in range(width)
        if (row, column) not in blocked
    }
    components: list[list[tuple[int, int]]] = []
    while remaining:
        start = next(iter(remaining))
        component = _reachable_cells(height, width, blocked, start)
        components.append(sorted(component))
        remaining.difference_update(component)
    return max(components, key=len) if components else []


def _select_spread_coordinates(
    candidates: Sequence[tuple[int, int]],
    count: int,
    rng: random.Random,
) -> list[tuple[int, int]]:
    """Farthest-point sampling with randomized first point and tie-breaking."""
    pool = list(candidates)
    rng.shuffle(pool)
    selected = [pool.pop()]
    while len(selected) < count:
        best_distance = -1
        best: list[tuple[int, int]] = []
        for candidate in pool:
            distance = min(_manhattan(candidate, existing) for existing in selected)
            if distance > best_distance:
                best_distance = distance
                best = [candidate]
            elif distance == best_distance:
                best.append(candidate)
        choice = rng.choice(best)
        selected.append(choice)
        pool.remove(choice)
    rng.shuffle(selected)
    return selected


def _select_strategic_bushes(
    *,
    height: int,
    width: int,
    permanent_blocks: set[tuple[int, int]],
    objectives: Sequence[tuple[int, int]],
    rng: random.Random,
    desired_count: int,
) -> list[tuple[int, int]]:
    """Place uncertain bushes on shortcuts without ever disconnecting goals.

    A candidate is accepted only when blocking it preserves connectivity among
    every agent start and every fire target. Preference is given to cells whose
    removal lengthens a shortest path, so a passable bush offers a genuine
    shortcut while an impassable one still has a safe detour.
    """
    selected: list[tuple[int, int]] = []
    objective_set = set(objectives)
    pairs = list(combinations(objectives, 2))
    rng.shuffle(pairs)

    for start, target in pairs:
        if len(selected) >= desired_count:
            break
        current_blocks = permanent_blocks | set(selected)
        path = _shortest_path(height, width, current_blocks, start, target)
        if len(path) < 5:
            continue
        candidates = [
            cell
            for cell in path[2:-2]
            if cell not in objective_set and cell not in selected
        ]
        rng.shuffle(candidates)
        ranked: list[tuple[int, tuple[int, int]]] = []
        baseline = len(path) - 1
        for candidate in candidates:
            blocked = current_blocks | {candidate}
            if not _all_connected(height, width, blocked, objectives):
                continue
            detour = _shortest_path(height, width, blocked, start, target)
            if not detour:
                continue
            increase = (len(detour) - 1) - baseline
            if increase >= 1:
                ranked.append((increase, candidate))
        if ranked:
            max_increase = max(value for value, _ in ranked)
            choices = [cell for value, cell in ranked if value == max_increase]
            selected.append(rng.choice(choices))

    # If path pairs did not provide enough strong candidates, accept further
    # non-disconnecting path cells. This preserves the reachability guarantee.
    if len(selected) < desired_count:
        fallback: list[tuple[int, int]] = []
        for start, target in pairs:
            path = _shortest_path(
                height,
                width,
                permanent_blocks | set(selected),
                start,
                target,
            )
            fallback.extend(path[2:-2])
        rng.shuffle(fallback)
        for candidate in fallback:
            if len(selected) >= desired_count:
                break
            if candidate in objective_set or candidate in selected:
                continue
            blocked = permanent_blocks | set(selected) | {candidate}
            if _all_connected(height, width, blocked, objectives):
                selected.append(candidate)

    return selected


def _all_connected(
    height: int,
    width: int,
    blocked: set[tuple[int, int]],
    objectives: Sequence[tuple[int, int]],
) -> bool:
    if not objectives:
        return True
    reached = _reachable_cells(height, width, blocked, objectives[0])
    return all(point in reached for point in objectives)


def _reachable_cells(
    height: int,
    width: int,
    blocked: set[tuple[int, int]],
    start: tuple[int, int],
) -> set[tuple[int, int]]:
    if start in blocked:
        return set()
    reached = {start}
    queue = deque([start])
    while queue:
        row, column = queue.popleft()
        for nxt in _neighbors(row, column):
            if (
                0 <= nxt[0] < height
                and 0 <= nxt[1] < width
                and nxt not in blocked
                and nxt not in reached
            ):
                reached.add(nxt)
                queue.append(nxt)
    return reached


def _shortest_path(
    height: int,
    width: int,
    blocked: set[tuple[int, int]],
    start: tuple[int, int],
    target: tuple[int, int],
) -> list[tuple[int, int]]:
    if start in blocked or target in blocked:
        return []
    queue = deque([start])
    parent: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    while queue:
        current = queue.popleft()
        if current == target:
            break
        for nxt in _neighbors(*current):
            if (
                0 <= nxt[0] < height
                and 0 <= nxt[1] < width
                and nxt not in blocked
                and nxt not in parent
            ):
                parent[nxt] = current
                queue.append(nxt)
    if target not in parent:
        return []
    path = [target]
    while path[-1] != start:
        previous = parent[path[-1]]
        if previous is None:
            break
        path.append(previous)
    path.reverse()
    return path


def _neighbors(row: int, column: int) -> Iterable[tuple[int, int]]:
    return (
        (row - 1, column),
        (row + 1, column),
        (row, column - 1),
        (row, column + 1),
    )


def _manhattan(left: tuple[int, int], right: tuple[int, int]) -> int:
    return abs(left[0] - right[0]) + abs(left[1] - right[1])
