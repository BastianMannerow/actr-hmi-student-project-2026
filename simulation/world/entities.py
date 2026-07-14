"""Spatial entities for the firefighter TurtleBot simulation."""

from __future__ import annotations


class SpatialEntity:
    """Base class for every object that can occupy a grid cell."""

    display_name = "Entity"
    symbol = "?"
    blocks_movement = False
    is_target = False

    def __repr__(self) -> str:
        return type(self).__name__ + "()"


class SpatialAgent(SpatialEntity):
    """Base class for ACT-R and human-controlled agents."""

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


class BurningTree(SpatialEntity):
    """A burning tree: known terrain that can never be crossed."""

    display_name = "Burning tree"
    symbol = "X"
    blocks_movement = True


class BurningBush(SpatialEntity):
    """A burning bush whose traversability is initially unknown to the agent.

    The GUI and visual stimulus expose only the common ``B`` symbol. The actual
    passability is intentionally an environment property and is not leaked into
    the agent's visual frame.
    """

    display_name = "Burning bush (unknown passability)"
    symbol = "b"
    is_uncertain = True

    def __init__(self, *, passable: bool) -> None:
        self.passable = bool(passable)
        self.blocks_movement = not self.passable

    def __repr__(self) -> str:
        return "BurningBush(passable=<hidden>)"


class FireTarget(SpatialEntity):
    """One of the three fire/rescue locations Squirtle must visit."""

    display_name = "Fire target"
    symbol = "F"
    blocks_movement = False
    is_target = True


# Compatibility aliases for older exports and generic inspection code. New
# level construction and GUI rendering use the firefighter-specific names.
Wall = BurningTree
DefinitelyAWall = BurningTree
FakeWall = BurningBush
Target = FireTarget
