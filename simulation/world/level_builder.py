"""Level builders adapted from the ACT-R TurtleBot repository.

Each level owns its matrix dimensions. GUI and configuration code may select a
level, but cannot override the level geometry.
"""

from __future__ import annotations

import random
from typing import Any, Optional, Sequence

from simulation.world.entities import DefinitelyAWall, FakeWall, Target, Wall


LEVEL_DIMENSIONS: dict[str, tuple[int, int]] = {
    # (height, width)
    "open_grid": (16, 16),
    "turtle_exercise_1": (16, 16),
    "turtle_exercise_2": (9, 5),
    "johannes_lab": (22, 25),
    "ros_shadow": (22, 25),
}


def level_dimensions(level_type: str) -> tuple[int, int]:
    """Return ``(height, width)`` defined by the selected level builder."""
    try:
        return LEVEL_DIMENSIONS[level_type]
    except KeyError as exc:
        raise ValueError(f"Unknown virtual level: {level_type!r}") from exc


def build_level(
    level_type: str,
    agents: Sequence[Any],
    rng: Optional[random.Random] = None,
) -> list[list[Any | None]]:
    """Build a matrix using the dimensions owned by ``level_type``."""
    builders = {
        "open_grid": _open_grid,
        "turtle_exercise_1": _open_grid,
        "turtle_exercise_2": _exercise_two,
        "johannes_lab": _johannes_lab,
        "ros_shadow": _johannes_lab,
    }
    try:
        builder = builders[level_type]
    except KeyError as exc:
        raise ValueError(f"Unknown virtual level: {level_type!r}") from exc
    height, width = level_dimensions(level_type)
    return builder(height, width, agents, rng or random.Random())


def _empty(height: int, width: int) -> list[list[Any | None]]:
    return [[None for _ in range(width)] for _ in range(height)]


def _free_coordinates(matrix: list[list[Any | None]]) -> list[tuple[int, int]]:
    return [
        (row, column)
        for row, values in enumerate(matrix)
        for column, value in enumerate(values)
        if value is None
    ]


def _place_agents(
    matrix: list[list[Any | None]],
    agents: Sequence[Any],
    rng: random.Random,
    preferred: Sequence[tuple[int, int]] = (),
) -> None:
    free = _free_coordinates(matrix)
    ordered: list[tuple[int, int]] = []
    for coordinate in preferred:
        row, column = coordinate
        if (
            0 <= row < len(matrix)
            and 0 <= column < len(matrix[0])
            and matrix[row][column] is None
            and coordinate not in ordered
        ):
            ordered.append(coordinate)
    remaining = [item for item in free if item not in ordered]
    rng.shuffle(remaining)
    ordered.extend(remaining)
    if len(agents) > len(ordered):
        raise ValueError("The selected level has too few free cells for all agents.")
    for agent, (row, column) in zip(agents, ordered):
        matrix[row][column] = agent


def _open_grid(
    height: int,
    width: int,
    agents: Sequence[Any],
    rng: random.Random,
) -> list[list[Any | None]]:
    matrix = _empty(height, width)
    _place_agents(matrix, agents, rng)
    return matrix


def _exercise_two(
    height: int,
    width: int,
    agents: Sequence[Any],
    rng: random.Random,
) -> list[list[Any | None]]:
    matrix = _empty(height, width)
    for row in range(height):
        for column in range(width):
            if row in {0, height - 1} or column in {0, width - 1}:
                matrix[row][column] = DefinitelyAWall()
    center_row, center_column = height // 2, width // 2
    upper_row, lower_row = center_row - 2, center_row + 2
    upper_type, lower_type = (
        (FakeWall, Wall) if rng.random() < 0.75 else (Wall, FakeWall)
    )
    for column in range(1, width - 1):
        matrix[upper_row][column] = upper_type()
        matrix[lower_row][column] = lower_type()
    preferred = [(center_row, center_column), (center_row, 1), (center_row, 3)]
    _place_agents(matrix, agents, rng, preferred)
    return matrix


def _johannes_lab(
    height: int,
    width: int,
    agents: Sequence[Any],
    rng: random.Random,
) -> list[list[Any | None]]:
    """22×25 laboratory map from the Johannes development branch."""
    matrix = _empty(height, width)
    for row in range(height):
        for column in range(width):
            if (
                row in {0, height - 1}
                or column in {0, width - 1}
                or (12 <= column <= 24 and 1 <= row <= 5)
            ):
                matrix[row][column] = DefinitelyAWall()

            if (
                (4 <= row <= 17 and 1 <= column <= 3)
                or (4 <= row <= 6 and 4 <= column <= 8)
                or (15 <= row <= 17 and 4 <= column <= 8)
                or (19 <= row <= 20 and 10 <= column <= 16)
                or (14 <= row <= 16 and 17 <= column <= 23)
                or (17 <= row <= 20 and 21 <= column <= 23)
                or (row == 6 and 18 <= column <= 20)
                or (11 <= row <= 14 and 11 <= column <= 14)
            ):
                matrix[row][column] = Wall()

    matrix[13][18] = Target()
    matrix[13][17] = Wall()
    matrix[12][17] = Wall()
    matrix[12][18] = Wall()
    matrix[12][19] = FakeWall()
    matrix[11][18] = FakeWall()
    matrix[14][18] = DefinitelyAWall()
    matrix[14][19] = DefinitelyAWall()
    matrix[14][20] = DefinitelyAWall()
    _place_agents(matrix, agents, rng, [(13, 16), (10, 16), (10, 17)])
    return matrix
