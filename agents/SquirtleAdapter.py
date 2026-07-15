"""Semantic-memory and dynamic-decision adapter for Squirtle."""

from __future__ import annotations

import heapq
from collections import deque
from typing import Any, Iterable

import pyactr as actr

from simulation.integrations import pyactr_extension


class SquirtleAdapter:
    """Maintain Squirtle's semantic-spatial mental model.

    The adapter is deliberately limited to operations that are cumbersome in
    production rules: projection of the visual-stimulus matrix into world
    coordinates, arithmetic, graph updates, route search and numeric utility
    updates.  ACT-R productions perform semantic retrieval, imaginal
    integration, policy conflict resolution, manual action and feedback choice.
    """

    TOTAL_TARGETS = 3
    TRAVERSABLE = {"free", "target", "bush_passable"}
    UNKNOWN_TERRAIN = {"bush_unknown", "unknown"}

    BRAVERY_GENERALIZATION_MARGIN = 0.10
    BRAVERY_TIME_GAIN_PER_SECOND = 0.018
    BRAVERY_UTILITY_CEILING = 2.0
    IMAGINAL_DELAYS = {
        "situation_model_imaginal": 0.20,
        "mission_context_imaginal": 0.20,
        "decision_workspace_imaginal": 0.25,
        "semantic_appraisal_imaginal": 0.20,
        "route_workspace_imaginal": 0.15,
        "episode_workspace_imaginal": 0.20,
    }

    TERRAIN_SEMANTICS = {
        "free": ("terrain_free_ground", "passability_passable", "danger_none"),
        "target": ("mission_rescue_target", "passability_passable", "danger_urgent"),
        "tree": ("hazard_fire_tree", "passability_blocked", "danger_critical"),
        "bush_unknown": ("hazard_fire_bush", "passability_unknown", "danger_high"),
        "bush_passable": ("hazard_fire_bush", "passability_passable", "danger_high"),
        "bush_blocked": ("hazard_fire_bush", "passability_blocked", "danger_high"),
        "unknown": ("terrain_unknown", "passability_unknown", "danger_unknown"),
    }

    def __init__(self, _environment=None):
        self.agent_construct = None
        self.known_map: dict[tuple[int, int], str] = {}
        self.visited_targets: set[tuple[int, int]] = set()
        self.cell_records: dict[tuple[int, int], dict[str, int]] = {}
        self.map_revision = 0

        self.active_target: tuple[int, int] | None = None
        self.pending_safe_path: list[tuple[int, int]] = []
        self.pending_brave_path: list[tuple[int, int]] = []
        self.pending_clear_path: list[tuple[int, int]] = []
        self.pending_risk_cell: tuple[int, int] | None = None
        self.committed_brave_risk_cell: tuple[int, int] | None = None

        self.last_attempt: tuple[int, int] | None = None
        self.last_start: tuple[int, int] | None = None
        self.last_route_kind = "none"
        self.last_policy = "none"
        self.bumped = False
        self.bump_reason = "none"

        self.episode_counter = 0
        self.last_episode_id = "episode_none"
        self.pending_episode: dict[str, Any] | None = None
        self._pending_production_handoff: str | None = None
        self._last_courage_update_time = 0.0
        self._last_brave_choice_production: str | None = None
        self._pending_imaginal_delay = 0.0

    @staticmethod
    def _production(phase: str, action: str) -> str:
        return f"{phase}_{action}"

    def extending_actr(self) -> None:
        agent = self.agent_construct
        if agent is None:
            return

        fired_production = pyactr_extension.get_production_fired(agent)
        if fired_production:
            if fired_production in {
                self._production("DECIDE", "bravery_probe_unknown_fire"),
                self._production("DECIDE", "emergency_bravery_without_detour"),
            }:
                self._last_brave_choice_production = fired_production
            # pyactr reports RULE FIRED before all scheduled buffer writes have
            # completed.  Execute the adapter handoff on the following event so
            # its goal and imaginal updates cannot be overwritten by the rule.
            self._pending_production_handoff = fired_production
            return

        production = self._pending_production_handoff
        self._pending_production_handoff = None
        if not production:
            return

        if production == "SENSE_refresh_context":
            self._refresh_situational_awareness()
        elif production == "TARGET_register_visit":
            self._register_target_visit()
        elif production == "EXPLORE_plan_frontier":
            self._plan_exploration()
        elif production == "PLAN_accept_clear_route":
            self._commit_clear_route()
        elif production == "RISK_known_passable_cell":
            self._commit_brave_route()
        elif production == "RISK_known_blocked_cell":
            self._commit_cautious_route()
        elif production == "DECIDE_apply_brave_policy":
            self._commit_brave_route()
        elif production == "DECIDE_apply_cautious_policy":
            self._commit_cautious_route()
        elif production == "OUTCOME_inspect_motion":
            self._evaluate_motion()
        elif production == "EVALUATE_punish_failed_bravery":
            self._consolidate_failed_bravery()
        elif production == "EVALUATE_reward_successful_bravery":
            self._consolidate_successful_bravery()
        elif production == "EVALUATE_reward_cautious_progress":
            self._consolidate_cautious_progress()
        elif production == "EVALUATE_record_clear_progress":
            self._consolidate_clear_progress()
        elif production == "EVALUATE_record_unexpected_blockage":
            self._consolidate_blockage()

    def on_bump_detected(self, *, reason: str = "obstacle", **_kwargs) -> None:
        self.bumped = True
        self.bump_reason = str(reason)

    # ------------------------------------------------------------------
    # Situational awareness and semantic-spatial memory
    # ------------------------------------------------------------------
    def _refresh_situational_awareness(self) -> None:
        current = self._current_position()
        if current is None:
            return

        self._apply_time_pressure_to_bravery()
        self._observe_visual_stimuli(current)
        known_targets = self._known_targets()
        current_terrain = self.known_map.get(current, "free")

        if current in known_targets and current not in self.visited_targets:
            self.committed_brave_risk_cell = None
            self.active_target = current
            self._write_situation_model(current, status="target_reached")
            self._write_mission_context(current, status="target_reached")
            self._write_episode_workspace(
                strategy_id=self.last_policy,
                position=current,
                terrain_id="mission_rescue_target",
                outcome_id="outcome_target_reached",
                reward_signal="positive",
            )
            self._set_goal("EVALUATE", "classify_feedback", self.last_policy, "target_reached")
            return

        if len(self.visited_targets) >= self.TOTAL_TARGETS:
            self.committed_brave_risk_cell = None
            self._write_situation_model(current, status="complete")
            self._write_mission_context(None, status="complete")
            self._set_goal("MISSION", "complete", "none", "all_targets_secured")
            return

        if self._continue_brave_commitment(current):
            return

        targets = sorted(known_targets - self.visited_targets)
        if targets:
            self.active_target = min(
                targets,
                key=lambda point: self._estimated_distance(current, point),
            )
            self._write_situation_model(current, status="active")
            self._write_mission_context(self.active_target, status="active")
            self._prepare_route_options(current, self.active_target)
            return

        self.active_target = None
        self._write_situation_model(current, status="exploring")
        self._write_mission_context(None, status="searching")
        self._set_goal("EXPLORE", "plan_frontier", "none", "none")

    def _observe_visual_stimuli(self, current: tuple[int, int]) -> None:
        """Update the mental map exclusively from ``visual_stimuli``."""
        agent = self.agent_construct
        frame = list(getattr(agent, "visual_stimuli", []) or [])
        origin = getattr(agent, "visual_frame_origin", None)
        valid = set(getattr(agent, "visual_frame_valid_positions", set()) or set())
        if not frame or origin is None:
            return

        origin_row, origin_column = origin
        changed: list[tuple[tuple[int, int], str, str]] = []
        for view_row, values in enumerate(frame):
            for view_column, symbols in enumerate(values):
                world = (origin_row + view_row, origin_column + view_column)
                if valid and world not in valid:
                    continue
                previous = self.known_map.get(world)
                observed = self._classify_symbols(str(symbols), previous)
                if observed != previous:
                    self.known_map[world] = observed
                    changed.append((world, observed, "observed"))

        if current not in self._known_targets() and self.known_map.get(current) != "free":
            self.known_map[current] = "free"
            changed.append((current, "free", "proprioceptive"))

        if not changed:
            return

        self.map_revision += 1
        unique_changed: dict[tuple[int, int], tuple[str, str]] = {}
        for position, terrain, confidence in changed:
            unique_changed[position] = (terrain, confidence)
        for position, (terrain, confidence) in unique_changed.items():
            self._upsert_cell_knowledge(position, terrain, confidence=confidence)
        for position in unique_changed:
            self._upsert_spatial_relations(position)

    @staticmethod
    def _classify_symbols(symbols: str, previous: str | None) -> str:
        if "F" in symbols:
            return "target"
        if "X" in symbols:
            return "tree"
        if "b" in symbols:
            if previous in {"bush_passable", "bush_blocked"}:
                return previous
            return "bush_unknown"
        return "free"

    def _upsert_cell_knowledge(
        self,
        position: tuple[int, int],
        terrain: str,
        *,
        confidence: str,
    ) -> None:
        terrain_id, passability_id, danger_id = self._terrain_semantics(terrain)
        record = self.cell_records.setdefault(position, {"attempts": 0, "successes": 0})
        cell_id = self._cell_id(position)
        cell_chunk = actr.chunkstring(
            string=f"""
                isa cell_memory
                cell_id {cell_id}
                pos_x {position[1]}
                pos_y {position[0]}
                terrain_id {terrain_id}
                passability_id {passability_id}
                danger_id {danger_id}
                confidence {confidence}
                attempts {record['attempts']}
                successes {record['successes']}
                map_revision {self.map_revision}
            """
        )
        self._upsert_memory_chunk("cell_memory", "cell_id", cell_id, cell_chunk)

        self._upsert_relation(
            relation_id=f"{cell_id}_has_terrain",
            subject_id=cell_id,
            predicate="has_terrain",
            object_id=terrain_id,
            strength=1.0,
            provenance=confidence,
        )
        self._upsert_relation(
            relation_id=f"{cell_id}_has_passability",
            subject_id=cell_id,
            predicate="has_passability",
            object_id=passability_id,
            strength=1.0,
            provenance=confidence,
        )
        self._upsert_relation(
            relation_id=f"{cell_id}_has_danger",
            subject_id=cell_id,
            predicate="has_danger",
            object_id=danger_id,
            strength=1.0,
            provenance=confidence,
        )

        if terrain == "target":
            target_id = self._target_id(position)
            status = "secured" if position in self.visited_targets else "known"
            target_chunk = actr.chunkstring(
                string=f"""
                    isa target_memory
                    target_id {target_id}
                    cell_id {cell_id}
                    status {status}
                    urgency_id urgency_critical
                    visit_count {1 if position in self.visited_targets else 0}
                    map_revision {self.map_revision}
                """
            )
            self._upsert_memory_chunk("target_memory", "target_id", target_id, target_chunk)
            self._upsert_relation(
                relation_id=f"{target_id}_located_at",
                subject_id=target_id,
                predicate="located_at",
                object_id=cell_id,
                strength=1.0,
                provenance="observation",
            )

    def _upsert_spatial_relations(self, position: tuple[int, int]) -> None:
        directions = {
            "north_of": (-1, 0),
            "south_of": (1, 0),
            "west_of": (0, -1),
            "east_of": (0, 1),
        }
        source_id = self._cell_id(position)
        for direction, (dr, dc) in directions.items():
            target = (position[0] + dr, position[1] + dc)
            terrain = self.known_map.get(target)
            if terrain is None:
                continue
            _, passability_id, _ = self._terrain_semantics(terrain)
            target_id = self._cell_id(target)
            relation_id = f"{source_id}_{direction}_{target_id}"
            chunk = actr.chunkstring(
                string=f"""
                    isa spatial_relation
                    relation_id {relation_id}
                    source_cell {source_id}
                    direction {direction}
                    target_cell {target_id}
                    passability_id {passability_id}
                    confidence observed
                    map_revision {self.map_revision}
                """
            )
            self._upsert_memory_chunk(
                "spatial_relation",
                "relation_id",
                relation_id,
                chunk,
            )

    # ------------------------------------------------------------------
    # Mission and route-option construction
    # ------------------------------------------------------------------
    def _register_target_visit(self) -> None:
        current = self._current_position()
        if current is None:
            return
        if current in self._known_targets():
            self.visited_targets.add(current)
            self._upsert_cell_knowledge(current, "target", confidence="secured")
        self._store_pending_episode()

        status = "complete" if len(self.visited_targets) >= self.TOTAL_TARGETS else "active"
        self._write_mission_context(None, status=status)
        if status == "complete":
            self._write_situation_model(current, status="complete")
            self._set_goal("MISSION", "complete", "none", "all_targets_secured")
        else:
            self._set_goal("SENSE", "refresh_context", "none", "target_secured")

    def _prepare_route_options(
        self,
        current: tuple[int, int],
        target: tuple[int, int],
    ) -> None:
        safe_path = self._route(current, target, allow_unknown=False)
        brave_path = self._route(current, target, allow_unknown=True)

        self.pending_safe_path = safe_path
        self.pending_brave_path = brave_path
        self.pending_clear_path = []
        self.pending_risk_cell = self._first_uncertain_cell(brave_path)

        safe_length = max(0, len(safe_path) - 1) if safe_path else -1
        brave_length = max(0, len(brave_path) - 1) if brave_path else -1
        risk_is_relevant = bool(
            self.pending_risk_cell
            and brave_path
            and (not safe_path or brave_length < safe_length)
        )

        if safe_path and not risk_is_relevant:
            self.pending_clear_path = safe_path
            self._write_decision_workspace(
                safe_path=safe_path,
                brave_path=brave_path or safe_path,
                risk_cell=None,
                appraisal_required=False,
            )
            self._write_semantic_appraisal("terrain_free_ground", source="route_clear")
            self._set_goal("PLAN", "evaluate_options", "none", "none")
            return

        if brave_path and risk_is_relevant:
            risk_cell = self.pending_risk_cell
            terrain = self.known_map.get(risk_cell, "unknown") if risk_cell else "unknown"
            terrain_id, _, _ = self._terrain_semantics(terrain)
            self._write_decision_workspace(
                safe_path=safe_path,
                brave_path=brave_path,
                risk_cell=risk_cell,
                appraisal_required=True,
            )
            self._write_semantic_appraisal(terrain_id, source="pending")
            self._set_goal("PLAN", "evaluate_options", "none", "none")
            return

        self._write_decision_workspace(
            safe_path=[],
            brave_path=[],
            risk_cell=None,
            appraisal_required=False,
        )
        self._write_semantic_appraisal("terrain_unknown", source="no_route")
        self._set_goal("PLAN", "evaluate_options", "none", "none")

    def _continue_brave_commitment(self, current: tuple[int, int]) -> bool:
        """Continue toward a previously chosen uncertain fire cell.

        Without this commitment, the agent can select the brave policy, take a
        harmless approach step and then reconsider before ever testing the
        bush.  The commitment persists until the uncertain cell is either
        crossed or produces a bump.
        """

        risk_cell = self.committed_brave_risk_cell
        if risk_cell is None:
            return False
        if current == risk_cell:
            self.committed_brave_risk_cell = None
            return False
        if self.known_map.get(risk_cell) not in self.UNKNOWN_TERRAIN:
            self.committed_brave_risk_cell = None
            return False

        path = self._route(current, risk_cell, allow_unknown=True)
        if len(path) < 2:
            self.committed_brave_risk_cell = None
            return False

        self.pending_safe_path = []
        self.pending_brave_path = path
        self.pending_clear_path = []
        self.pending_risk_cell = risk_cell
        terrain_id, _, _ = self._terrain_semantics(
            self.known_map.get(risk_cell, "unknown")
        )
        self._write_situation_model(current, status="committed_brave_probe")
        self._write_mission_context(self.active_target, status="active")
        self._write_decision_workspace(
            safe_path=[],
            brave_path=path,
            risk_cell=risk_cell,
            appraisal_required=True,
        )
        # Keep the production-facing source value compatible with the normal
        # semantic integration rule; the commitment is represented by the
        # adapter state and route workspace rather than a new chunk literal.
        self._write_semantic_appraisal(terrain_id, source="pending")
        self._set_goal("PLAN", "evaluate_options", "none", "none")
        return True

    def _plan_exploration(self) -> None:
        current = self._current_position()
        if current is None:
            return
        height, width = self._world_size()
        candidates: list[tuple[int, tuple[int, int]]] = []

        for cell, terrain in self.known_map.items():
            if terrain not in self.TRAVERSABLE:
                continue
            unknown_neighbors = [
                point
                for point in self._neighbors(*cell)
                if self._in_bounds(point, height, width) and point not in self.known_map
            ]
            if not unknown_neighbors:
                continue
            target = (
                min(unknown_neighbors, key=lambda point: self._estimated_distance(point, current))
                if cell == current
                else cell
            )
            safe_path = self._route(current, target, allow_unknown=False)
            brave_path = self._route(current, target, allow_unknown=True)
            lengths = [len(path) for path in (safe_path, brave_path) if path]
            if lengths:
                candidates.append((min(lengths), target))

        if candidates:
            _, target = min(
                candidates,
                key=lambda item: (item[0], self._estimated_distance(current, item[1])),
            )
            self._prepare_route_options(current, target)
            return

        unknown = [
            (row, column)
            for row in range(height)
            for column in range(width)
            if (row, column) not in self.known_map
        ]
        if not unknown:
            self._set_goal("SENSE", "refresh_context", "none", "map_review")
            return
        target = min(unknown, key=lambda point: self._estimated_distance(current, point))
        self._prepare_route_options(current, target)

    def _commit_clear_route(self) -> None:
        self._commit_pending_route("clear")

    def _commit_brave_route(self) -> None:
        risk_cell = self.pending_risk_cell
        if risk_cell is not None and self.known_map.get(risk_cell) in self.UNKNOWN_TERRAIN:
            self.committed_brave_risk_cell = risk_cell
        self._commit_pending_route("brave")

    def _commit_cautious_route(self) -> None:
        self._commit_pending_route("cautious")

    def _commit_pending_route(self, choice: str) -> None:
        if choice == "brave":
            path = self.pending_brave_path
            policy = "policy_brave_probe"
            route_kind = "brave_probe"
            risk_cell = self.committed_brave_risk_cell or self.pending_risk_cell
            if risk_cell in path:
                path = path[: path.index(risk_cell) + 1]
        elif choice == "cautious":
            path = self.pending_safe_path
            policy = "policy_cautious_detour"
            route_kind = "cautious_detour"
            if not path:
                self._set_goal("REPLAN", "avoid_learned_hazard", policy, "no_safe_route")
                return
        else:
            path = self.pending_clear_path or self.pending_safe_path or self.pending_brave_path
            policy = "policy_clear_traverse"
            route_kind = "clear_route"

        current = self._current_position()
        if current is None or len(path) < 2:
            self._set_goal("SENSE", "refresh_context", "none", "route_expired")
            return
        if path[0] != current:
            target = path[-1]
            path = self._route(current, target, allow_unknown=(choice == "brave"))
            if len(path) < 2:
                self._set_goal("SENSE", "refresh_context", "none", "route_expired")
                return

        self._commit_route_step(
            current=current,
            next_position=path[1],
            policy=policy,
            route_kind=route_kind,
            route_length=len(path) - 1,
            risk_cell=self.pending_risk_cell,
        )

    def _commit_route_step(
        self,
        *,
        current: tuple[int, int],
        next_position: tuple[int, int],
        policy: str,
        route_kind: str,
        route_length: int,
        risk_cell: tuple[int, int] | None,
    ) -> None:
        delta = (next_position[0] - current[0], next_position[1] - current[1])
        direction = {
            (-1, 0): "up",
            (1, 0): "down",
            (0, -1): "left",
            (0, 1): "right",
        }.get(delta)
        if direction is None:
            raise ValueError(f"Non-adjacent route step: {current} -> {next_position}")

        self.last_start = current
        self.last_attempt = next_position
        self.last_route_kind = route_kind
        self.last_policy = policy
        self.bumped = False
        self.bump_reason = "none"
        self._write_route_workspace(
            next_position=next_position,
            direction=direction,
            route_kind=route_kind,
            route_length=route_length,
            risk_cell=risk_cell,
        )
        self._set_goal("MOVE", "ready", policy, "route_committed")

    # ------------------------------------------------------------------
    # Outcome evaluation, episodic memory and utility adaptation
    # ------------------------------------------------------------------
    def _evaluate_motion(self) -> None:
        current = self._current_position()
        attempted = self.last_attempt
        if current is None or attempted is None:
            self._set_goal("SENSE", "refresh_context", "none", "missing_motion_context")
            return

        previous_terrain = self.known_map.get(attempted, "unknown")
        terrain_id, _, _ = self._terrain_semantics(previous_terrain)

        if self.bumped or current != attempted:
            if attempted == self.committed_brave_risk_cell:
                self.committed_brave_risk_cell = None
            learned = "bush_blocked" if previous_terrain == "bush_unknown" else "tree"
            self._record_attempt(attempted, success=False)
            self.known_map[attempted] = learned
            self.map_revision += 1
            self._upsert_cell_knowledge(attempted, learned, confidence="learned_failure")
            self._upsert_spatial_relations(attempted)
            self._write_episode_workspace(
                strategy_id=self.last_policy,
                position=attempted,
                terrain_id=terrain_id,
                outcome_id="outcome_failure",
                reward_signal="negative",
            )
            self.bumped = False
            outcome = "fire_blocked" if self.last_policy == "policy_brave_probe" else "obstacle_blocked"
            self._set_goal("EVALUATE", "classify_feedback", self.last_policy, outcome)
            return

        if previous_terrain == "bush_unknown":
            if attempted == self.committed_brave_risk_cell:
                self.committed_brave_risk_cell = None
            self._record_attempt(attempted, success=True)
            self.known_map[attempted] = "bush_passable"
            self.map_revision += 1
            self._upsert_cell_knowledge(attempted, "bush_passable", confidence="learned_success")
            self._upsert_spatial_relations(attempted)

        if current in self._known_targets() and current not in self.visited_targets:
            self.committed_brave_risk_cell = None
            self.active_target = current
            self._write_mission_context(current, status="target_reached")
            self._write_episode_workspace(
                strategy_id=self.last_policy,
                position=current,
                terrain_id="mission_rescue_target",
                outcome_id="outcome_target_reached",
                reward_signal="positive",
            )
            self._set_goal("EVALUATE", "classify_feedback", self.last_policy, "target_reached")
            return

        if previous_terrain == "bush_unknown" and self.last_policy == "policy_brave_probe":
            outcome = "fire_passed"
            outcome_id = "outcome_success"
            signal = "positive"
        elif self.last_policy == "policy_cautious_detour":
            outcome = "safe_progress"
            outcome_id = "outcome_progress"
            signal = "small_positive"
        else:
            outcome = "clear_progress"
            outcome_id = "outcome_progress"
            signal = "neutral"

        self._write_episode_workspace(
            strategy_id=self.last_policy,
            position=current,
            terrain_id=terrain_id,
            outcome_id=outcome_id,
            reward_signal=signal,
        )
        self._set_goal("EVALUATE", "classify_feedback", self.last_policy, outcome)

    def _consolidate_failed_bravery(self) -> None:
        self._store_pending_episode()
        self._generalize_bravery_reward(success=False)
        self._set_goal("SENSE", "refresh_context", "none", "failure_learned")

    def _consolidate_successful_bravery(self) -> None:
        self._store_pending_episode()
        self._generalize_bravery_reward(success=True)
        self._set_goal("SENSE", "refresh_context", "none", "success_learned")

    def _consolidate_cautious_progress(self) -> None:
        self._store_pending_episode()
        self._set_goal("SENSE", "refresh_context", "none", "caution_reinforced")

    def _consolidate_clear_progress(self) -> None:
        self._store_pending_episode()
        self._set_goal("SENSE", "refresh_context", "none", "progress_recorded")

    def _consolidate_blockage(self) -> None:
        self._store_pending_episode()
        self._set_goal("SENSE", "refresh_context", "none", "blockage_recorded")

    def _write_episode_workspace(
        self,
        *,
        strategy_id: str,
        position: tuple[int, int],
        terrain_id: str,
        outcome_id: str,
        reward_signal: str,
    ) -> None:
        self.episode_counter += 1
        episode_id = f"episode_{self.episode_counter}"
        self.pending_episode = {
            "episode_id": episode_id,
            "previous_episode": self.last_episode_id,
            "strategy_id": strategy_id or "none",
            "cell_id": self._cell_id(position),
            "terrain_id": terrain_id,
            "outcome_id": outcome_id,
            "reward_signal": reward_signal,
        }
        chunk = actr.chunkstring(
            string=f"""
                isa episode_workspace
                episode_id {episode_id}
                previous_episode {self.last_episode_id}
                strategy_id {strategy_id or 'none'}
                cell_id {self._cell_id(position)}
                terrain_id {terrain_id}
                outcome_id {outcome_id}
                reward_signal {reward_signal}
            """
        )
        self._pending_imaginal_delay = max(
            self._pending_imaginal_delay,
            self.IMAGINAL_DELAYS["episode_workspace_imaginal"],
        )
        pyactr_extension.replace_buffer(
            self.agent_construct,
            "episode_workspace_imaginal",
            chunk,
        )

    def _store_pending_episode(self) -> None:
        episode = self.pending_episode
        if not episode:
            return
        reward = {
            "positive": 9.0,
            "small_positive": 1.5,
            "negative": -14.0,
            "neutral": 0.4,
        }.get(str(episode["reward_signal"]), 0.0)
        chunk = actr.chunkstring(
            string=f"""
                isa episode_memory
                episode_id {episode['episode_id']}
                previous_episode {episode['previous_episode']}
                strategy_id {episode['strategy_id']}
                cell_id {episode['cell_id']}
                terrain_id {episode['terrain_id']}
                outcome_id {episode['outcome_id']}
                reward {reward}
                map_revision {self.map_revision}
            """
        )
        pyactr_extension.add_to_declarative_memory(self.agent_construct, chunk)
        self._upsert_relation(
            relation_id=f"{episode['episode_id']}_used_policy",
            subject_id=episode["episode_id"],
            predicate="used_policy",
            object_id=episode["strategy_id"],
            strength=1.0,
            provenance="experience",
        )
        self._upsert_relation(
            relation_id=f"{episode['episode_id']}_concerned_cell",
            subject_id=episode["episode_id"],
            predicate="concerned_cell",
            object_id=episode["cell_id"],
            strength=1.0,
            provenance="experience",
        )
        self._upsert_relation(
            relation_id=f"{episode['episode_id']}_produced_outcome",
            subject_id=episode["episode_id"],
            predicate="produced_outcome",
            object_id=episode["outcome_id"],
            strength=1.0,
            provenance="experience",
        )
        self.last_episode_id = str(episode["episode_id"])
        self.pending_episode = None

    def _bravery_productions(self) -> tuple[str, str]:
        return (
            self._production("DECIDE", "bravery_probe_unknown_fire"),
            self._production("DECIDE", "emergency_bravery_without_detour"),
        )

    def _generalize_bravery_reward(self, *, success: bool) -> None:
        """Generalize ACT-R's learned reward to both bravery productions.

        pyactr applies the configured production reward before the adapter
        handoff.  A blocked bush therefore lowers the utility of the brave
        choice that actually led to the failure.  This method shares that
        learned courage value with the sibling brave production, without
        applying a second independent reward update.
        """

        chosen = self._last_brave_choice_production
        if chosen is None:
            return
        learned = pyactr_extension.get_production_utility(self.agent_construct, chosen)
        if learned is None:
            return

        for production_name in self._bravery_productions():
            if production_name == chosen:
                continue
            current = pyactr_extension.get_production_utility(
                self.agent_construct,
                production_name,
            )
            if current is None:
                continue
            if success:
                target = float(learned) - self.BRAVERY_GENERALIZATION_MARGIN
                updated = max(float(current), target)
            else:
                target = float(learned) + self.BRAVERY_GENERALIZATION_MARGIN
                updated = min(float(current), target)
            pyactr_extension.update_utility(
                self.agent_construct,
                production_name,
                round(updated, 4),
            )

    def _apply_time_pressure_to_bravery(self) -> None:
        """Raise willingness to test fire gradually as ACT-R time passes."""

        now = max(0.0, float(getattr(self.agent_construct, "actr_time", 0.0)))
        elapsed = max(0.0, now - self._last_courage_update_time)
        self._last_courage_update_time = now
        if elapsed <= 0.0:
            return

        gain = elapsed * self.BRAVERY_TIME_GAIN_PER_SECOND
        for production_name in self._bravery_productions():
            current = pyactr_extension.get_production_utility(
                self.agent_construct,
                production_name,
            )
            if current is None:
                continue
            updated = min(
                self.BRAVERY_UTILITY_CEILING,
                float(current) + gain,
            )
            pyactr_extension.update_utility(
                self.agent_construct,
                production_name,
                round(updated, 4),
            )

    # ------------------------------------------------------------------
    # Imaginal workspaces
    # ------------------------------------------------------------------
    def _write_situation_model(self, current: tuple[int, int], *, status: str) -> None:
        terrain = self.known_map.get(current, "free")
        terrain_id, _, danger_id = self._terrain_semantics(terrain)
        target_id = self._target_id(self.active_target) if self.active_target else "target_none"
        chunk = actr.chunkstring(
            string=f"""
                isa situation_model
                current_cell {self._cell_id(current)}
                current_x {current[1]}
                current_y {current[0]}
                terrain_id {terrain_id}
                danger_id {danger_id}
                target_id {target_id}
                mission_status {status}
                map_revision {self.map_revision}
            """
        )
        self._pending_imaginal_delay = max(
            self._pending_imaginal_delay,
            self.IMAGINAL_DELAYS["situation_model_imaginal"],
        )
        pyactr_extension.replace_buffer(
            self.agent_construct,
            "situation_model_imaginal",
            chunk,
        )

    def _write_mission_context(
        self,
        target: tuple[int, int] | None,
        *,
        status: str,
    ) -> None:
        target_id = self._target_id(target) if target is not None else "target_none"
        target_cell = self._cell_id(target) if target is not None else "cell_none"
        chunk = actr.chunkstring(
            string=f"""
                isa mission_context
                active_target_id {target_id}
                active_target_cell {target_cell}
                visited_count {len(self.visited_targets)}
                total_targets {self.TOTAL_TARGETS}
                mission_status {status}
            """
        )
        self._pending_imaginal_delay = max(
            self._pending_imaginal_delay,
            self.IMAGINAL_DELAYS["mission_context_imaginal"],
        )
        pyactr_extension.replace_buffer(
            self.agent_construct,
            "mission_context_imaginal",
            chunk,
        )

    def _write_decision_workspace(
        self,
        *,
        safe_path: list[tuple[int, int]],
        brave_path: list[tuple[int, int]],
        risk_cell: tuple[int, int] | None,
        appraisal_required: bool,
    ) -> None:
        safe_next = safe_path[1] if len(safe_path) >= 2 else None
        brave_next = brave_path[1] if len(brave_path) >= 2 else None
        terrain = self.known_map.get(risk_cell, "unknown") if risk_cell else "free"
        terrain_id, _, _ = self._terrain_semantics(terrain)
        safe_length = len(safe_path) - 1 if safe_path else -1
        brave_length = len(brave_path) - 1 if brave_path else -1
        route_saving = (
            safe_length - brave_length
            if safe_length >= 0 and brave_length >= 0
            else 0
        )
        route_available = bool(safe_path or brave_path)
        chunk = actr.chunkstring(
            string=f"""
                isa decision_workspace
                safe_next_cell {self._cell_id(safe_next) if safe_next else 'cell_none'}
                brave_next_cell {self._cell_id(brave_next) if brave_next else 'cell_none'}
                risk_cell {self._cell_id(risk_cell) if risk_cell else 'cell_none'}
                candidate_terrain_id {terrain_id}
                safe_length {safe_length}
                brave_length {brave_length}
                route_saving {route_saving}
                safe_available {'yes' if bool(safe_path) or (route_available and not appraisal_required) else 'no'}
                appraisal_required {'yes' if appraisal_required else 'no'}
                selected_policy none
            """
        )
        self._pending_imaginal_delay = max(
            self._pending_imaginal_delay,
            self.IMAGINAL_DELAYS["decision_workspace_imaginal"],
        )
        pyactr_extension.replace_buffer(
            self.agent_construct,
            "decision_workspace_imaginal",
            chunk,
        )

    def _write_semantic_appraisal(self, focus_entity: str, *, source: str) -> None:
        terrain = next(
            (
                values
                for values in self.TERRAIN_SEMANTICS.values()
                if values[0] == focus_entity
            ),
            ("terrain_unknown", "passability_unknown", "danger_unknown"),
        )
        _, passability_id, danger_id = terrain
        uncertainty = "high" if passability_id == "passability_unknown" else "low"
        affordance = {
            "passability_passable": "affordance_traverse",
            "passability_blocked": "affordance_avoid",
            "passability_unknown": "affordance_assess",
        }[passability_id]
        chunk = actr.chunkstring(
            string=f"""
                isa semantic_appraisal
                focus_entity {focus_entity}
                danger_id {danger_id}
                uncertainty {uncertainty}
                passability_id {passability_id}
                affordance_id {affordance}
                source {source}
            """
        )
        self._pending_imaginal_delay = max(
            self._pending_imaginal_delay,
            self.IMAGINAL_DELAYS["semantic_appraisal_imaginal"],
        )
        pyactr_extension.replace_buffer(
            self.agent_construct,
            "semantic_appraisal_imaginal",
            chunk,
        )

    def _write_route_workspace(
        self,
        *,
        next_position: tuple[int, int],
        direction: str,
        route_kind: str,
        route_length: int,
        risk_cell: tuple[int, int] | None,
    ) -> None:
        chunk = actr.chunkstring(
            string=f"""
                isa route_workspace
                next_cell {self._cell_id(next_position)}
                next_x {next_position[1]}
                next_y {next_position[0]}
                direction {direction}
                route_kind {route_kind}
                route_length {route_length}
                risk_cell {self._cell_id(risk_cell) if risk_cell else 'cell_none'}
            """
        )
        self._pending_imaginal_delay = max(
            self._pending_imaginal_delay,
            self.IMAGINAL_DELAYS["route_workspace_imaginal"],
        )
        pyactr_extension.replace_buffer(
            self.agent_construct,
            "route_workspace_imaginal",
            chunk,
        )

    def _set_goal(self, phase: str, state: str, policy: str, outcome: str) -> None:
        chunk = actr.chunkstring(
            string=f"""
                isa firefighting_goal
                phase {phase}
                state {state}
                policy {policy}
                outcome {outcome}
            """
        )
        commit_delay = self._pending_imaginal_delay
        self._pending_imaginal_delay = 0.0
        pyactr_extension.set_goal(
            self.agent_construct,
            chunk,
            delay=commit_delay,
        )

    # ------------------------------------------------------------------
    # Declarative-memory graph operations
    # ------------------------------------------------------------------
    def _upsert_relation(
        self,
        *,
        relation_id: str,
        subject_id: str,
        predicate: str,
        object_id: str,
        strength: float,
        provenance: str,
    ) -> None:
        chunk = actr.chunkstring(
            string=f"""
                isa knowledge_relation
                relation_id {relation_id}
                subject_id {subject_id}
                predicate {predicate}
                object_id {object_id}
                strength {strength}
                provenance {provenance}
            """
        )
        self._upsert_memory_chunk(
            "knowledge_relation",
            "relation_id",
            relation_id,
            chunk,
        )

    def _upsert_memory_chunk(
        self,
        chunk_type: str,
        key_slot: str,
        key_value: str,
        new_chunk,
    ) -> None:
        memory = pyactr_extension.get_declarative_memory(self.agent_construct)
        for existing in list(memory.keys()):
            if getattr(existing, "typename", None) != chunk_type:
                continue
            if self._chunk_slot(existing, key_slot) == str(key_value):
                try:
                    del memory[existing]
                except (KeyError, TypeError):
                    pass
        pyactr_extension.add_to_declarative_memory(self.agent_construct, new_chunk)

    @staticmethod
    def _chunk_slot(chunk, slot: str) -> str | None:
        try:
            value = chunk._asdict().get(slot)
            raw = getattr(value, "values", value)
            return None if raw is None else str(raw)
        except (AttributeError, TypeError):
            return None

    # ------------------------------------------------------------------
    # Path search and small helpers
    # ------------------------------------------------------------------
    def _route(
        self,
        start: tuple[int, int],
        target: tuple[int, int],
        *,
        allow_unknown: bool,
    ) -> list[tuple[int, int]]:
        height, width = self._world_size()

        def cost(point: tuple[int, int]) -> float | None:
            terrain = self.known_map.get(point)
            if terrain in {"tree", "bush_blocked"}:
                return None
            if terrain in self.TRAVERSABLE:
                return 1.0
            if terrain == "bush_unknown":
                return 1.15 if allow_unknown else None
            if terrain is None:
                return 1.75 if allow_unknown else None
            return 1.0

        return self._astar(start, target, height, width, cost)

    @staticmethod
    def _astar(
        start: tuple[int, int],
        target: tuple[int, int],
        height: int,
        width: int,
        cost_function,
    ) -> list[tuple[int, int]]:
        queue: list[tuple[float, int, tuple[int, int]]] = [(0.0, 0, start)]
        parents: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        costs: dict[tuple[int, int], float] = {start: 0.0}
        sequence = 0
        while queue:
            _, _, current = heapq.heappop(queue)
            if current == target:
                break
            for nxt in SquirtleAdapter._neighbors(*current):
                if not SquirtleAdapter._in_bounds(nxt, height, width):
                    continue
                step_cost = cost_function(nxt)
                if step_cost is None:
                    continue
                new_cost = costs[current] + float(step_cost)
                if new_cost >= costs.get(nxt, float("inf")):
                    continue
                costs[nxt] = new_cost
                parents[nxt] = current
                sequence += 1
                priority = new_cost + SquirtleAdapter._estimated_distance(nxt, target)
                heapq.heappush(queue, (priority, sequence, nxt))
        if target not in parents:
            return []
        path = [target]
        while path[-1] != start:
            parent = parents[path[-1]]
            if parent is None:
                break
            path.append(parent)
        path.reverse()
        return path

    def _first_uncertain_cell(
        self,
        path: list[tuple[int, int]],
    ) -> tuple[int, int] | None:
        for point in path[1:]:
            if self.known_map.get(point, "unknown") in self.UNKNOWN_TERRAIN:
                return point
        return None

    def _record_attempt(self, position: tuple[int, int], *, success: bool) -> None:
        record = self.cell_records.setdefault(position, {"attempts": 0, "successes": 0})
        record["attempts"] += 1
        if success:
            record["successes"] += 1

    def _current_position(self) -> tuple[int, int] | None:
        environment = getattr(self.agent_construct.middleman, "experiment_environment", None)
        return environment.find_agent(self.agent_construct) if environment is not None else None

    def _world_size(self) -> tuple[int, int]:
        matrix = self.agent_construct.middleman.experiment_environment.level_matrix
        return len(matrix), len(matrix[0])

    def _known_targets(self) -> set[tuple[int, int]]:
        return {position for position, terrain in self.known_map.items() if terrain == "target"}

    @classmethod
    def _terrain_semantics(cls, terrain: str) -> tuple[str, str, str]:
        return cls.TERRAIN_SEMANTICS.get(terrain, cls.TERRAIN_SEMANTICS["unknown"])

    @staticmethod
    def _cell_id(position: tuple[int, int] | None) -> str:
        return "cell_none" if position is None else f"cell_{position[0]}_{position[1]}"

    @staticmethod
    def _target_id(position: tuple[int, int] | None) -> str:
        return "target_none" if position is None else f"target_{position[0]}_{position[1]}"

    @staticmethod
    def _neighbors(row: int, column: int) -> Iterable[tuple[int, int]]:
        return (
            (row - 1, column),
            (row + 1, column),
            (row, column - 1),
            (row, column + 1),
        )

    @staticmethod
    def _in_bounds(point: tuple[int, int], height: int, width: int) -> bool:
        return 0 <= point[0] < height and 0 <= point[1] < width

    @staticmethod
    def _estimated_distance(left: tuple[int, int], right: tuple[int, int]) -> int:
        return abs(left[0] - right[0]) + abs(left[1] - right[1])
