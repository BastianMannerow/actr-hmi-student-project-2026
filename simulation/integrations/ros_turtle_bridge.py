"""Optional ROS 2 bridge for physical TurtleBot/iRobot Create robots."""

from __future__ import annotations

import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable


class RosUnavailableError(RuntimeError):
    pass


@dataclass(slots=True)
class _RobotChannel:
    agent: Any
    namespace: str
    publisher: Any | None = None
    drive_client: Any | None = None
    rotate_client: Any | None = None
    heading: float = 0.0
    busy: bool = False
    bumped: bool = False
    current_goal: Any | None = None


class RosTurtleBridge:
    """Map ACT-R grid commands to the repository's ROS action interface.

    ``irobot_actions`` uses ``DriveDistance`` and ``RotateAngle`` plus
    ``HazardDetectionVector`` and odometry. ``cmd_vel`` is retained as a
    portable alternative for other TurtleBot ROS 2 setups.
    """

    def __init__(
        self,
        *,
        agents: list[Any],
        config: Any,
        on_motion_finished: Callable[[str, bool], None],
        on_bump: Callable[[str], None],
        on_error: Callable[[str, str], None] | None = None,
    ) -> None:
        self.agents = agents
        self.config = config
        self.on_motion_finished = on_motion_finished
        self.on_bump = on_bump
        self.on_error = on_error or (lambda _agent_name, _message: None)
        self._channels: dict[str, _RobotChannel] = {}
        self._node = None
        self._executor = None
        self._spin_thread: threading.Thread | None = None
        self._owns_context = False
        self._lock = threading.RLock()
        self._rclpy = None
        self._Twist = None
        self._DriveDistance = None
        self._RotateAngle = None
        self._GoalStatus = None
        self._motion_executor = ThreadPoolExecutor(
            max_workers=max(1, len(agents)),
            thread_name_prefix="actr-ros-move",
        )
        self._last_odom_update: dict[str, float] = {}

    def start(self) -> None:
        """Initialize ROS 2 resources and clean up partial startup on failure."""
        try:
            try:
                import rclpy
                from nav_msgs.msg import Odometry
            except ImportError as exc:
                raise RosUnavailableError(
                    "ROS Real-life requires ROS 2 with rclpy and nav_msgs in the active Python environment."
                ) from exc

            self._rclpy = rclpy
            if not rclpy.ok():
                rclpy.init(args=None)
                self._owns_context = True
            self._node = rclpy.create_node(self._sanitize(self.config.node_name_prefix))

            if self.config.interface_mode == "irobot_actions":
                self._prepare_action_interface()
            else:
                self._prepare_cmd_vel_interface()

            for index, agent in enumerate(self.agents, start=1):
                name = str(getattr(agent, "name", f"agent_{index}"))
                namespace = self._namespace_for(index, name)
                channel = _RobotChannel(agent=agent, namespace=namespace)
                self._channels[name] = channel
                if self.config.interface_mode == "irobot_actions":
                    self._configure_action_channel(channel)
                else:
                    self._configure_cmd_vel_channel(channel)
                self._node.create_subscription(
                    Odometry,
                    self._join_topic(namespace, self.config.odom_topic),
                    self._odom_callback(name),
                    10,
                )

            from rclpy.executors import MultiThreadedExecutor

            self._executor = MultiThreadedExecutor(
                num_threads=min(8, max(2, len(self.agents) + 1))
            )
            self._executor.add_node(self._node)
            self._spin_thread = threading.Thread(
                target=self._executor.spin,
                name="actr-ros-spin",
                daemon=True,
            )
            self._spin_thread.start()
        except BaseException:
            self.close()
            raise

    def _prepare_action_interface(self) -> None:
        try:
            from action_msgs.msg import GoalStatus
            from irobot_create_msgs.action import DriveDistance, RotateAngle
            from irobot_create_msgs.msg import HazardDetectionVector
            from rclpy.action import ActionClient
            from rclpy.qos import qos_profile_sensor_data
        except ImportError as exc:
            raise RosUnavailableError(
                "The repository-compatible ROS mode requires irobot_create_msgs and action_msgs."
            ) from exc
        self._DriveDistance = DriveDistance
        self._RotateAngle = RotateAngle
        self._GoalStatus = GoalStatus
        self._ActionClient = ActionClient
        self._HazardDetectionVector = HazardDetectionVector
        self._sensor_qos = qos_profile_sensor_data

    def _prepare_cmd_vel_interface(self) -> None:
        try:
            from geometry_msgs.msg import Twist
        except ImportError as exc:
            raise RosUnavailableError("Generic cmd_vel mode requires geometry_msgs.") from exc
        self._Twist = Twist

    def _configure_action_channel(self, channel: _RobotChannel) -> None:
        assert self._node is not None
        channel.drive_client = self._ActionClient(
            self._node,
            self._DriveDistance,
            self._join_topic(channel.namespace, self.config.drive_action_topic),
        )
        channel.rotate_client = self._ActionClient(
            self._node,
            self._RotateAngle,
            self._join_topic(channel.namespace, self.config.rotate_action_topic),
        )
        self._node.create_subscription(
            self._HazardDetectionVector,
            self._join_topic(channel.namespace, self.config.bumper_topic),
            self._hazard_callback(str(getattr(channel.agent, "name", ""))),
            self._sensor_qos,
        )

    def _configure_cmd_vel_channel(self, channel: _RobotChannel) -> None:
        assert self._node is not None and self._Twist is not None
        channel.publisher = self._node.create_publisher(
            self._Twist,
            self._join_topic(channel.namespace, self.config.cmd_vel_topic),
            10,
        )
        self._create_generic_bumper_subscription(
            str(getattr(channel.agent, "name", "")), channel.namespace
        )

    def move_grid(self, agent: Any, dr: int, dc: int) -> bool:
        name = str(getattr(agent, "name", ""))
        with self._lock:
            channel = self._channels.get(name)
            if channel is None or channel.busy:
                return False
            channel.busy = True
            channel.bumped = False
        try:
            self._motion_executor.submit(self._execute_grid_move, channel, dr, dc)
        except RuntimeError:
            with self._lock:
                channel.busy = False
            return False
        return True

    def _execute_grid_move(self, channel: _RobotChannel, dr: int, dc: int) -> None:
        success = False
        try:
            target_heading = {
                (-1, 0): math.pi / 2,
                (1, 0): -math.pi / 2,
                (0, -1): math.pi,
                (0, 1): 0.0,
            }[(dr, dc)]
            angle = self._normalize_angle(target_heading - channel.heading)
            if self.config.interface_mode == "irobot_actions":
                if abs(angle) > 0.02 and not self._action_rotate(channel, angle):
                    return
                channel.heading = target_heading
                success = self._action_drive(channel, self.config.cell_size_m)
            else:
                if abs(angle) > 0.02:
                    self._publish_for(
                        channel,
                        linear=0.0,
                        angular=math.copysign(self.config.angular_speed, angle),
                        duration=min(self.config.command_timeout_s, abs(angle) / self.config.angular_speed),
                    )
                    channel.heading = target_heading
                self._publish_for(
                    channel,
                    linear=self.config.linear_speed,
                    angular=0.0,
                    duration=min(
                        self.config.command_timeout_s,
                        self.config.cell_size_m / self.config.linear_speed,
                    ),
                )
                success = not channel.bumped
        except Exception as exc:
            success = False
            self.on_error(
                str(getattr(channel.agent, "name", "")),
                f"{type(exc).__name__}: {exc}",
            )
        finally:
            self._publish_stop(channel)
            with self._lock:
                channel.busy = False
                channel.current_goal = None
            self.on_motion_finished(str(getattr(channel.agent, "name", "")), success)

    def _action_rotate(self, channel: _RobotChannel, angle: float) -> bool:
        goal = self._RotateAngle.Goal()
        goal.angle = float(angle)
        goal.max_rotation_speed = float(self.config.angular_speed)
        return self._execute_action(channel, channel.rotate_client, goal)

    def _action_drive(self, channel: _RobotChannel, distance: float) -> bool:
        goal = self._DriveDistance.Goal()
        goal.distance = float(distance)
        goal.max_translation_speed = float(self.config.linear_speed)
        return self._execute_action(channel, channel.drive_client, goal)

    def _execute_action(self, channel: _RobotChannel, client: Any, goal: Any) -> bool:
        if client is None or not client.wait_for_server(timeout_sec=self.config.command_timeout_s):
            raise TimeoutError(f"ROS action server unavailable in namespace {channel.namespace}.")
        accepted_event = threading.Event()
        result_event = threading.Event()
        outcome: dict[str, Any] = {"accepted": False, "status": None}

        def goal_response(future: Any) -> None:
            try:
                handle = future.result()
                outcome["accepted"] = bool(handle.accepted)
                channel.current_goal = handle
                accepted_event.set()
                if not handle.accepted:
                    result_event.set()
                    return
                handle.get_result_async().add_done_callback(result_callback)
            except Exception as exc:
                outcome["error"] = exc
                accepted_event.set()
                result_event.set()

        def result_callback(future: Any) -> None:
            try:
                outcome["status"] = future.result().status
            except Exception as exc:
                outcome["error"] = exc
            finally:
                result_event.set()

        client.send_goal_async(goal).add_done_callback(goal_response)
        if not accepted_event.wait(self.config.command_timeout_s):
            raise TimeoutError("ROS action goal was not accepted before the timeout.")
        if not outcome.get("accepted"):
            return False
        if not result_event.wait(self.config.command_timeout_s):
            handle = channel.current_goal
            if handle is not None:
                try:
                    handle.cancel_goal_async()
                except Exception:
                    pass
            raise TimeoutError("ROS action did not finish before the timeout.")
        if channel.bumped:
            return False
        if outcome.get("error") is not None:
            raise outcome["error"]
        return outcome.get("status") == self._GoalStatus.STATUS_SUCCEEDED

    def _hazard_callback(self, agent_name: str):
        def callback(message: Any) -> None:
            for detection in getattr(message, "detections", []):
                frame_id = str(getattr(getattr(detection, "header", None), "frame_id", ""))
                hazard_type = getattr(detection, "type", None)
                if hazard_type == 1 or "bump" in frame_id.casefold():
                    self._mark_bump(agent_name)
                    break

        return callback

    def _create_generic_bumper_subscription(self, agent_name: str, namespace: str) -> None:
        if self._node is None:
            return
        message_type = None
        for module_name, class_name in (
            ("kobuki_ros_interfaces.msg", "BumperEvent"),
            ("kobuki_msgs.msg", "BumperEvent"),
            ("std_msgs.msg", "Bool"),
        ):
            try:
                module = __import__(module_name, fromlist=[class_name])
                message_type = getattr(module, class_name)
                break
            except (ImportError, AttributeError):
                continue
        if message_type is None:
            return

        def callback(message: Any) -> None:
            pressed = getattr(message, "state", getattr(message, "data", True))
            if bool(pressed):
                self._mark_bump(agent_name)

        self._node.create_subscription(
            message_type,
            self._join_topic(namespace, self.config.bumper_topic),
            callback,
            10,
        )

    def _mark_bump(self, agent_name: str) -> None:
        with self._lock:
            channel = self._channels.get(agent_name)
            if channel is not None:
                channel.bumped = True
                handle = channel.current_goal
                if handle is not None:
                    try:
                        handle.cancel_goal_async()
                    except Exception:
                        pass
        self.on_bump(agent_name)

    def _odom_callback(self, agent_name: str):
        def callback(message: Any) -> None:
            now = time.monotonic()
            previous = self._last_odom_update.get(agent_name, 0.0)
            if now - previous < 0.05:
                return
            self._last_odom_update[agent_name] = now
            orientation = message.pose.pose.orientation
            siny = 2.0 * (orientation.w * orientation.z + orientation.x * orientation.y)
            cosy = 1.0 - 2.0 * (orientation.y * orientation.y + orientation.z * orientation.z)
            with self._lock:
                channel = self._channels.get(agent_name)
                if channel is not None:
                    channel.heading = math.atan2(siny, cosy)

        return callback

    def _publish_for(
        self,
        channel: _RobotChannel,
        *,
        linear: float,
        angular: float,
        duration: float,
    ) -> None:
        if self._Twist is None or channel.publisher is None:
            raise RosUnavailableError("The cmd_vel interface has not been initialized.")
        deadline = time.monotonic() + max(0.0, duration)
        while time.monotonic() < deadline and not channel.bumped:
            message = self._Twist()
            message.linear.x = float(linear)
            message.angular.z = float(angular)
            channel.publisher.publish(message)
            time.sleep(0.05)
        self._publish_stop(channel)

    def _publish_stop(self, channel: _RobotChannel) -> None:
        if self._Twist is not None and channel.publisher is not None:
            channel.publisher.publish(self._Twist())

    def close(self) -> None:
        self._motion_executor.shutdown(wait=False, cancel_futures=True)
        with self._lock:
            channels = list(self._channels.values())
        for channel in channels:
            try:
                self._publish_stop(channel)
            except Exception:
                pass
            if channel.current_goal is not None:
                try:
                    channel.current_goal.cancel_goal_async()
                except Exception:
                    pass
        if self._executor is not None:
            try:
                self._executor.shutdown(timeout_sec=1.0)
            except Exception:
                pass
        if self._node is not None:
            try:
                self._node.destroy_node()
            except Exception:
                pass
        if self._owns_context and self._rclpy is not None:
            try:
                self._rclpy.shutdown()
            except Exception:
                pass
        self._channels.clear()

    def _namespace_for(self, index: int, agent_name: str) -> str:
        template = str(self.config.namespace)
        try:
            rendered = template.format(index=index, agent=self._sanitize(agent_name))
        except (KeyError, ValueError):
            rendered = template
        if len(self.agents) > 1 and "{" not in template and rendered.rstrip("/").split("/")[-1] not in {f"tb{index}", self._sanitize(agent_name)}:
            rendered = self._join_topic(rendered, f"tb{index}")
        return self._normalize_namespace(rendered)

    @staticmethod
    def _normalize_namespace(value: str) -> str:
        normalized = "/" + value.strip().strip("/")
        return "" if normalized == "/" else normalized

    @staticmethod
    def _join_topic(namespace: str, topic: str) -> str:
        return "/" + "/".join(part for part in (namespace.strip("/"), topic.strip("/")) if part)

    @staticmethod
    def _sanitize(value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_]", "_", value.strip())
        if not normalized:
            return "agent"
        if normalized[0].isdigit():
            normalized = "n_" + normalized
        return normalized.lower()

    @staticmethod
    def _normalize_angle(value: float) -> float:
        return (value + math.pi) % (2 * math.pi) - math.pi
