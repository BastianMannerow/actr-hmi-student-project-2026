"""Typed configuration for interactive and multi-run ACT-R simulations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SPEED_PRESETS: tuple[tuple[str, float], ...] = (
    ("1/4 Realtime", 25.0),
    ("1/2 Realtime", 50.0),
    ("Realtime", 100.0),
    ("2x Realtime", 200.0),
    ("ASAP", -1.0),
)

ENVIRONMENT_MODES: tuple[tuple[str, str], ...] = (
    ("Virtual Environment", "virtual"),
    ("ROS Real-life", "ros"),
)

VIRTUAL_LEVELS: tuple[tuple[str, str], ...] = (
    ("Turtle Simulation", "turtle_simulation"),
)



@dataclass(slots=True)
class AgentTypeConfig:
    count: int = 1
    print_agent_actions: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "AgentTypeConfig":
        payload = payload or {}
        return cls(
            count=max(0, int(payload.get("count", 1))),
            print_agent_actions=bool(payload.get("print_agent_actions", True)),
        )


@dataclass(slots=True)
class RosConfig:
    """ROS 2 connection and discrete TurtleBot movement parameters."""

    interface_mode: str = "irobot_actions"
    namespace: str = "/tb{index}"
    cmd_vel_topic: str = "cmd_vel"
    drive_action_topic: str = "drive_distance"
    rotate_action_topic: str = "rotate_angle"
    odom_topic: str = "odom"
    bumper_topic: str = "hazard_detection"
    node_name_prefix: str = "actr_turtle_bridge"
    linear_speed: float = 0.20
    angular_speed: float = 0.65
    cell_size_m: float = 0.30
    command_timeout_s: float = 12.0

    def validate(self) -> None:
        if self.interface_mode not in {"irobot_actions", "cmd_vel"}:
            raise ValueError("Unknown ROS control interface.")
        if self.linear_speed <= 0 or self.angular_speed <= 0:
            raise ValueError("ROS linear and angular speed must be greater than zero.")
        if self.cell_size_m <= 0:
            raise ValueError("ROS grid cell size must be greater than zero.")
        if self.command_timeout_s <= 0:
            raise ValueError("ROS command timeout must be greater than zero.")
        if not self.node_name_prefix.strip():
            raise ValueError("ROS node name prefix cannot be empty.")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "RosConfig":
        payload = payload or {}
        interface_mode = str(payload.get("interface_mode", "irobot_actions"))
        if interface_mode not in {"irobot_actions", "cmd_vel"}:
            interface_mode = "irobot_actions"
        return cls(
            interface_mode=interface_mode,
            namespace=str(payload.get("namespace", "/tb{index}")).strip() or "/tb{index}",
            cmd_vel_topic=str(payload.get("cmd_vel_topic", "cmd_vel")).strip() or "cmd_vel",
            drive_action_topic=str(payload.get("drive_action_topic", "drive_distance")).strip() or "drive_distance",
            rotate_action_topic=str(payload.get("rotate_action_topic", "rotate_angle")).strip() or "rotate_angle",
            odom_topic=str(payload.get("odom_topic", "odom")).strip() or "odom",
            bumper_topic=str(payload.get("bumper_topic", "hazard_detection")).strip() or "hazard_detection",
            node_name_prefix=str(payload.get("node_name_prefix", "actr_turtle_bridge")).strip() or "actr_turtle_bridge",
            linear_speed=max(0.001, float(payload.get("linear_speed", 0.20))),
            angular_speed=max(0.001, float(payload.get("angular_speed", 0.65))),
            cell_size_m=max(0.001, float(payload.get("cell_size_m", 0.30))),
            command_timeout_s=max(0.1, float(payload.get("command_timeout_s", 12.0))),
        )


@dataclass(slots=True)
class SimulationConfig:
    focus_position: tuple[int, int] = (0, 2)
    print_middleman: bool = False
    speed_factor: float = 100.0
    print_agent_actions: bool = True
    los: int = 3
    execution_mode: str = "single"
    environment_mode: str = "virtual"
    virtual_level: str = "turtle_simulation"
    ros: RosConfig = field(default_factory=RosConfig)
    human_agent_enabled: bool = False
    human_agent_name: str = "Human Player"
    agent_type_config: dict[str, AgentTypeConfig] = field(
        default_factory=lambda: {
            "CountingAgent": AgentTypeConfig(count=1, print_agent_actions=True),
            "Squirtle": AgentTypeConfig(count=1, print_agent_actions=True),
        }
    )

    @property
    def height(self) -> int:
        """Matrix height defined by the selected level builder."""
        from simulation.world.level_builder import level_dimensions

        return level_dimensions(self.virtual_level)[0]

    @property
    def width(self) -> int:
        """Matrix width defined by the selected level builder."""
        from simulation.world.level_builder import level_dimensions

        return level_dimensions(self.virtual_level)[1]

    @property
    def stepper(self) -> bool:
        return self.execution_mode == "single"

    @property
    def speed_label(self) -> str:
        for label, value in SPEED_PRESETS:
            if float(self.speed_factor) == float(value):
                return label
        return f"{self.speed_factor:g}%"

    @property
    def environment_label(self) -> str:
        labels = dict((value, label) for label, value in ENVIRONMENT_MODES)
        return labels.get(self.environment_mode, self.environment_mode)

    def validate(self) -> None:
        if float(self.speed_factor) not in {value for _, value in SPEED_PRESETS}:
            raise ValueError("The speed must use one of the predefined presets.")
        if self.los < 0:
            raise ValueError("Line of sight cannot be negative.")
        if self.execution_mode not in {"single", "automatic"}:
            raise ValueError("Unknown execution mode.")
        if self.environment_mode not in {value for _, value in ENVIRONMENT_MODES}:
            raise ValueError("Unknown environment mode.")
        if self.virtual_level not in {value for _, value in VIRTUAL_LEVELS}:
            raise ValueError("Unknown virtual level.")
        self.ros.validate()
        if self.human_agent_enabled and not self.human_agent_name.strip():
            raise ValueError("The human agent needs a name.")
        if self.environment_mode == "ros" and self.human_agent_enabled:
            raise ValueError("The GUI-controlled human agent is available only in the virtual environment.")
        if sum(max(0, item.count) for item in self.agent_type_config.values()) < 1:
            raise ValueError("At least one ACT-R agent must be enabled.")

    def without_human_agent(self) -> "SimulationConfig":
        payload = self.to_dict()
        payload["human_agent_enabled"] = False
        payload["human_agent_name"] = "Human Player"
        return type(self).from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "focus_position": list(self.focus_position),
            "print_middleman": self.print_middleman,
            "width": self.width,
            "height": self.height,
            "speed_factor": self.speed_factor,
            "speed_label": self.speed_label,
            "print_agent_actions": self.print_agent_actions,
            "los": self.los,
            "execution_mode": self.execution_mode,
            "stepper": self.stepper,
            "environment_mode": self.environment_mode,
            "environment_label": self.environment_label,
            "virtual_level": self.virtual_level,
            "ros": self.ros.to_dict(),
            "human_agent_enabled": self.human_agent_enabled,
            "human_agent_name": self.human_agent_name,
            "agent_type_config": {
                name: config.to_dict()
                for name, config in self.agent_type_config.items()
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "SimulationConfig":
        payload = payload or {}
        focus = payload.get("focus_position", [0, 2])
        try:
            focus_position = (int(focus[0]), int(focus[1]))
        except Exception:
            focus_position = (0, 2)

        raw_agents = payload.get("agent_type_config", {})
        legacy_agent_names = {"Example", "Runner", "JohannesAgent"}
        agent_types = {
            str(name): AgentTypeConfig.from_dict(value)
            for name, value in raw_agents.items()
            if isinstance(value, dict) and str(name) not in legacy_agent_names
        }
        if not agent_types:
            agent_types = {
                "CountingAgent": AgentTypeConfig(count=1),
                "Squirtle": AgentTypeConfig(count=1),
            }

        speed = float(payload.get("speed_factor", 100.0))
        if speed not in {value for _, value in SPEED_PRESETS}:
            speed = 100.0
        mode = str(payload.get("environment_mode", "virtual"))
        if mode not in {value for _, value in ENVIRONMENT_MODES}:
            mode = "virtual"
        level = str(payload.get("virtual_level", "turtle_simulation"))
        if level not in {value for _, value in VIRTUAL_LEVELS}:
            level = "turtle_simulation"

        config = cls(
            focus_position=focus_position,
            print_middleman=bool(payload.get("print_middleman", False)),
            speed_factor=speed,
            print_agent_actions=bool(payload.get("print_agent_actions", True)),
            los=max(0, int(payload.get("los", 3))),
            execution_mode=str(payload.get("execution_mode", "single")),
            environment_mode=mode,
            virtual_level=level,
            ros=RosConfig.from_dict(payload.get("ros")),
            human_agent_enabled=bool(payload.get("human_agent_enabled", False)),
            human_agent_name=str(payload.get("human_agent_name", "Human Player")).strip() or "Human Player",
            agent_type_config=agent_types,
        )
        if config.execution_mode not in {"single", "automatic"}:
            config.execution_mode = "single"
        if config.environment_mode == "ros":
            config.human_agent_enabled = False
        return config
