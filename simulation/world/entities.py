"""Spatial entities used by virtual and ROS-backed TurtleBot worlds."""

from __future__ import annotations


class SpatialEntity:
    display_name = "Entity"
    symbol = "?"
    blocks_movement = False
    is_target = False

    def __repr__(self) -> str:
        return type(self).__name__ + "()"


class SpatialAgent(SpatialEntity):
    is_human_controlled = False
    symbol = "A"

    def __init__(self, name: str) -> None:
        normalized = str(name).strip()
        if not normalized:
            raise ValueError("A spatial agent needs a non-empty name.")
        self.name = normalized
        self.name_number = normalized
        self.display_name = normalized

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r})"


class Wall(SpatialEntity):
    display_name = "Wall"
    symbol = "Z"
    blocks_movement = True


class FakeWall(SpatialEntity):
    display_name = "Passable obstacle"
    symbol = "Z"
    blocks_movement = False


class DefinitelyAWall(SpatialEntity):
    display_name = "Known wall"
    symbol = "X"
    blocks_movement = True


class Target(SpatialEntity):
    display_name = "Target"
    symbol = "T"
    blocks_movement = False
    is_target = True
