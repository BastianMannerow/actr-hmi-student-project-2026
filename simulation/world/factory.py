"""Create the configured TurtleBot world backend."""

from __future__ import annotations

from typing import Any

from simulation.world.environment import Environment, RosEnvironment
from simulation.world.level_builder import build_level


def create_environment(config: Any, agents: list[Any], simulation: Any) -> Environment:
    # In ROS mode the same selected level is retained as a deterministic
    # shadow map for perception, collision checks, inspection, and history.
    matrix = build_level(config.virtual_level, agents)
    if config.environment_mode == "ros":
        environment = RosEnvironment(
            matrix,
            simulation=simulation,
            ros_config=config.ros,
        )
    else:
        environment = Environment(matrix, simulation=simulation)
    level_labels = {
        "turtle_simulation": "Turtle Simulation",
    }
    environment.level_type = config.virtual_level
    environment.level_name = level_labels.get(config.virtual_level, config.virtual_level)
    return environment
