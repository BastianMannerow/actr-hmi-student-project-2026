"""Production system for the firefighter TurtleBot agent Squirtle."""

from __future__ import annotations

import pyactr as actr


class Squirtle:
    """ACT-R controller with a semantic-spatial mental model.

    Orientation is based on ``AgentConstruct.visual_stimuli`` rather than the
    pyactr visual module.  The adapter performs arithmetic, map projection and
    route calculation, while productions retrieve semantic knowledge, integrate
    it in imaginal workspaces, resolve uncertain choices and evaluate outcomes.
    """

    uses_visual_module = False
    analysis_control_slots = ("phase", "state")

    PHASE_MISSION = "MISSION"
    PHASE_SENSE = "SENSE"
    PHASE_TARGET = "TARGET"
    PHASE_PLAN = "PLAN"
    PHASE_EXPLORE = "EXPLORE"
    PHASE_RISK = "RISK"
    PHASE_DECIDE = "DECIDE"
    PHASE_MOVE = "MOVE"
    PHASE_OUTCOME = "OUTCOME"
    PHASE_EVALUATE = "EVALUATE"
    PHASE_LEARN = "LEARN"
    PHASE_REPLAN = "REPLAN"

    # Character disposition.  Raising BRAVERY_PRODUCTION_UTILITY above the
    # caution value makes probing unresolved burning bushes increasingly likely.
    BRAVERY_PRODUCTION_UTILITY = -0.45
    CAUTION_PRODUCTION_UTILITY = 0.80
    EMERGENCY_BRAVERY_UTILITY = -0.15
    UTILITY_NOISE = 0.22

    BRAVERY_SUCCESS_REWARD = 9.0
    BRAVERY_FAILURE_REWARD = -14.0
    CAUTIOUS_PROGRESS_REWARD = 1.5
    TARGET_REWARD = 15.0

    def __init__(self, environ):
        self.environ = environ
        self.this_agent_key = None
        self.other_agents_key_list = None
        self.actr_agent = actr.ACTRModel(
            environment=None,
            motor_prepared=True,
            automatic_visual_search=False,
            subsymbolic=True,
        )
        self.initial_goal = None

    @staticmethod
    def _name(phase: str, action: str) -> str:
        return f"{{{phase}}}_{action}"

    def build_agent(self, agent_list):
        self.this_agent_key = agent_list[0]
        self.other_agents_key_list = agent_list[1:]
        model = self.actr_agent
        model.model_parameters.update(
            {
                "utility_learning": True,
                "utility_alpha": 0.25,
                "utility_noise": self.UTILITY_NOISE,
                "baselevel_learning": False,
                "automatic_visual_search": False,
            }
        )

        self._declare_chunk_types()
        self._seed_semantic_memory(model)

        self.initial_goal = actr.chunkstring(
            string=f"""
                isa firefighting_goal
                phase {self.PHASE_MISSION}
                state initialize
                policy none
                outcome none
            """
        )

        model.set_goal(name="situation_model_imaginal", delay=0)
        model.set_goal(name="mission_context_imaginal", delay=0)
        model.set_goal(name="decision_workspace_imaginal", delay=0)
        model.set_goal(name="semantic_appraisal_imaginal", delay=0)
        model.set_goal(name="route_workspace_imaginal", delay=0)
        model.set_goal(name="episode_workspace_imaginal", delay=0)

        self._add_control_productions(model)
        self._add_planning_productions(model)
        self._add_semantic_retrieval_productions(model)
        self._add_disposition_productions(model)
        self._add_movement_productions(model)
        self._add_evaluation_productions(model)
        self._add_terminal_productions(model)
        return model

    @staticmethod
    def _declare_chunk_types() -> None:
        actr.chunktype("firefighting_goal", "phase state policy outcome")

        actr.chunktype(
            "semantic_concept",
            "entity_id category valence danger_id uncertainty passability_id affordance_id",
        )
        actr.chunktype(
            "knowledge_relation",
            "relation_id subject_id predicate object_id strength provenance",
        )
        actr.chunktype(
            "strategy_schema",
            "strategy_id disposition_id action_id attends_to risk_tolerance expected_outcome",
        )
        actr.chunktype(
            "cell_memory",
            "cell_id pos_x pos_y terrain_id passability_id danger_id confidence attempts successes map_revision",
        )
        actr.chunktype(
            "spatial_relation",
            "relation_id source_cell direction target_cell passability_id confidence map_revision",
        )
        actr.chunktype(
            "target_memory",
            "target_id cell_id status urgency_id visit_count map_revision",
        )
        actr.chunktype(
            "episode_memory",
            "episode_id previous_episode strategy_id cell_id terrain_id outcome_id reward map_revision",
        )

        actr.chunktype(
            "situation_model",
            "current_cell current_x current_y terrain_id danger_id target_id mission_status map_revision",
        )
        actr.chunktype(
            "mission_context",
            "active_target_id active_target_cell visited_count total_targets mission_status",
        )
        actr.chunktype(
            "decision_workspace",
            "safe_next_cell brave_next_cell risk_cell candidate_terrain_id safe_length brave_length route_saving safe_available appraisal_required selected_policy",
        )
        actr.chunktype(
            "semantic_appraisal",
            "focus_entity danger_id uncertainty passability_id affordance_id source",
        )
        actr.chunktype(
            "route_workspace",
            "next_cell next_x next_y direction route_kind route_length risk_cell",
        )
        actr.chunktype(
            "episode_workspace",
            "episode_id previous_episode strategy_id cell_id terrain_id outcome_id reward_signal",
        )

    @staticmethod
    def _seed_semantic_memory(model) -> None:
        """Install the invariant semantic knowledge graph before simulation."""

        concept_free_ground = actr.chunkstring(
            string="""
                isa semantic_concept
                entity_id terrain_free_ground
                category terrain
                valence neutral
                danger_id danger_none
                uncertainty low
                passability_id passability_passable
                affordance_id affordance_traverse
            """
        )
        model.decmem.add(concept_free_ground)

        concept_fire_tree = actr.chunkstring(
            string="""
                isa semantic_concept
                entity_id hazard_fire_tree
                category hazard
                valence negative
                danger_id danger_critical
                uncertainty low
                passability_id passability_blocked
                affordance_id affordance_avoid
            """
        )
        model.decmem.add(concept_fire_tree)

        concept_fire_bush = actr.chunkstring(
            string="""
                isa semantic_concept
                entity_id hazard_fire_bush
                category hazard
                valence negative
                danger_id danger_high
                uncertainty high
                passability_id passability_unknown
                affordance_id affordance_assess
            """
        )
        model.decmem.add(concept_fire_bush)

        concept_unknown = actr.chunkstring(
            string="""
                isa semantic_concept
                entity_id terrain_unknown
                category uncertainty
                valence caution
                danger_id danger_unknown
                uncertainty high
                passability_id passability_unknown
                affordance_id affordance_observe
            """
        )
        model.decmem.add(concept_unknown)

        concept_target = actr.chunkstring(
            string="""
                isa semantic_concept
                entity_id mission_rescue_target
                category mission_goal
                valence positive
                danger_id danger_urgent
                uncertainty low
                passability_id passability_passable
                affordance_id affordance_secure
            """
        )
        model.decmem.add(concept_target)

        concept_passable = actr.chunkstring(
            string="""
                isa semantic_concept
                entity_id passability_passable
                category property
                valence positive
                danger_id danger_none
                uncertainty low
                passability_id passability_passable
                affordance_id affordance_traverse
            """
        )
        model.decmem.add(concept_passable)

        concept_blocked = actr.chunkstring(
            string="""
                isa semantic_concept
                entity_id passability_blocked
                category property
                valence negative
                danger_id danger_high
                uncertainty low
                passability_id passability_blocked
                affordance_id affordance_avoid
            """
        )
        model.decmem.add(concept_blocked)

        concept_uncertain = actr.chunkstring(
            string="""
                isa semantic_concept
                entity_id passability_unknown
                category property
                valence caution
                danger_id danger_unknown
                uncertainty high
                passability_id passability_unknown
                affordance_id affordance_test_or_avoid
            """
        )
        model.decmem.add(concept_uncertain)

        brave_policy = actr.chunkstring(
            string=f"""
                isa strategy_schema
                strategy_id policy_brave_probe
                disposition_id disposition_brave
                action_id action_probe_fire_bush
                attends_to hazard_fire_bush
                risk_tolerance high
                expected_outcome outcome_shortcut
            """
        )
        model.decmem.add(brave_policy)

        cautious_policy = actr.chunkstring(
            string="""
                isa strategy_schema
                strategy_id policy_cautious_detour
                disposition_id disposition_cautious
                action_id action_take_safe_detour
                attends_to hazard_fire_bush
                risk_tolerance low
                expected_outcome outcome_safe_progress
            """
        )
        model.decmem.add(cautious_policy)

        normal_policy = actr.chunkstring(
            string="""
                isa strategy_schema
                strategy_id policy_clear_traverse
                disposition_id disposition_neutral
                action_id action_follow_clear_route
                attends_to terrain_free_ground
                risk_tolerance none
                expected_outcome outcome_progress
            """
        )
        model.decmem.add(normal_policy)

        relation_tree_hazard = actr.chunkstring(
            string="""
                isa knowledge_relation
                relation_id relation_tree_is_hazard
                subject_id hazard_fire_tree
                predicate is_a
                object_id danger_critical
                strength 1.0
                provenance prior_knowledge
            """
        )
        model.decmem.add(relation_tree_hazard)

        relation_tree_blocked = actr.chunkstring(
            string="""
                isa knowledge_relation
                relation_id relation_tree_blocks_motion
                subject_id hazard_fire_tree
                predicate implies
                object_id passability_blocked
                strength 1.0
                provenance prior_knowledge
            """
        )
        model.decmem.add(relation_tree_blocked)

        relation_bush_danger = actr.chunkstring(
            string="""
                isa knowledge_relation
                relation_id relation_bush_has_danger
                subject_id hazard_fire_bush
                predicate connotes
                object_id danger_high
                strength 0.9
                provenance prior_knowledge
            """
        )
        model.decmem.add(relation_bush_danger)

        relation_bush_uncertain = actr.chunkstring(
            string="""
                isa knowledge_relation
                relation_id relation_bush_has_unknown_passability
                subject_id hazard_fire_bush
                predicate may_have
                object_id passability_unknown
                strength 1.0
                provenance prior_knowledge
            """
        )
        model.decmem.add(relation_bush_uncertain)

        relation_brave_tests = actr.chunkstring(
            string="""
                isa knowledge_relation
                relation_id relation_brave_policy_tests_bush
                subject_id policy_brave_probe
                predicate tests
                object_id hazard_fire_bush
                strength 1.0
                provenance policy_knowledge
            """
        )
        model.decmem.add(relation_brave_tests)

        relation_caution_avoids = actr.chunkstring(
            string="""
                isa knowledge_relation
                relation_id relation_caution_policy_avoids_bush
                subject_id policy_cautious_detour
                predicate avoids
                object_id hazard_fire_bush
                strength 1.0
                provenance policy_knowledge
            """
        )
        model.decmem.add(relation_caution_avoids)

        relation_target_motivates = actr.chunkstring(
            string="""
                isa knowledge_relation
                relation_id relation_target_motivates_approach
                subject_id mission_rescue_target
                predicate motivates
                object_id affordance_secure
                strength 1.0
                provenance mission_knowledge
            """
        )
        model.decmem.add(relation_target_motivates)

    def _add_control_productions(self, model) -> None:
        self._transition(
            model,
            self._name(self.PHASE_MISSION, "initialize_mental_model"),
            self.PHASE_MISSION,
            "initialize",
            self.PHASE_SENSE,
            "refresh_context",
        )
        self._transition(
            model,
            self._name(self.PHASE_SENSE, "refresh_context"),
            self.PHASE_SENSE,
            "refresh_context",
            self.PHASE_SENSE,
            "adapter_scan",
        )

        model.productionstring(
            name=self._name(self.PHASE_TARGET, "register_visit"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_TARGET}
                state register_visit
                policy =policy
                outcome target_reached
                =mission_context_imaginal>
                isa mission_context
                active_target_id =target
                active_target_cell =cell
                mission_status target_reached
                ==>
                =g>
                isa firefighting_goal
                phase {self.PHASE_TARGET}
                state adapter_register
                policy =policy
                outcome target_reached
            """,
            reward=self.TARGET_REWARD,
        )

        self._transition(
            model,
            self._name(self.PHASE_EXPLORE, "plan_frontier"),
            self.PHASE_EXPLORE,
            "plan_frontier",
            self.PHASE_EXPLORE,
            "adapter_plan",
        )

        model.productionstring(
            name=self._name(self.PHASE_OUTCOME, "inspect_motion"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_OUTCOME}
                state inspect_motion
                policy =policy
                outcome =outcome
                =route_workspace_imaginal>
                isa route_workspace
                next_cell =cell
                route_kind =kind
                risk_cell =risk
                ?manual>
                state free
                ==>
                =g>
                isa firefighting_goal
                phase {self.PHASE_OUTCOME}
                state adapter_check
                policy =policy
                outcome =outcome
            """,
        )

        self._transition(
            model,
            self._name(self.PHASE_REPLAN, "avoid_learned_hazard"),
            self.PHASE_REPLAN,
            "avoid_learned_hazard",
            self.PHASE_SENSE,
            "refresh_context",
        )

    def _add_planning_productions(self, model) -> None:
        model.productionstring(
            name=self._name(self.PHASE_PLAN, "request_semantic_appraisal"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_PLAN}
                state evaluate_options
                policy none
                outcome none
                =decision_workspace_imaginal>
                isa decision_workspace
                candidate_terrain_id =terrain
                safe_available =safe
                appraisal_required yes
                selected_policy none
                =situation_model_imaginal>
                isa situation_model
                current_cell =current
                mission_status =mission
                ==>
                =g>
                isa firefighting_goal
                phase {self.PHASE_RISK}
                state request_semantics
                policy none
                outcome none
            """,
        )

        model.productionstring(
            name=self._name(self.PHASE_PLAN, "accept_clear_route"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_PLAN}
                state evaluate_options
                policy none
                outcome none
                =decision_workspace_imaginal>
                isa decision_workspace
                safe_available yes
                appraisal_required no
                ==>
                =g>
                isa firefighting_goal
                phase {self.PHASE_PLAN}
                state adapter_commit_clear
                policy policy_clear_traverse
                outcome clear_route
            """,
            utility=0.5,
        )

        model.productionstring(
            name=self._name(self.PHASE_PLAN, "no_route_available"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_PLAN}
                state evaluate_options
                policy none
                outcome none
                =decision_workspace_imaginal>
                isa decision_workspace
                safe_available no
                appraisal_required no
                ==>
                =g>
                isa firefighting_goal
                phase {self.PHASE_EXPLORE}
                state plan_frontier
                policy none
                outcome route_unavailable
            """,
        )

    def _add_semantic_retrieval_productions(self, model) -> None:
        model.productionstring(
            name=self._name(self.PHASE_RISK, "request_hazard_semantics"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_RISK}
                state request_semantics
                policy none
                outcome none
                =decision_workspace_imaginal>
                isa decision_workspace
                candidate_terrain_id =terrain
                risk_cell =cell
                appraisal_required yes
                ==>
                =g>
                isa firefighting_goal
                phase {self.PHASE_RISK}
                state await_semantics
                policy none
                outcome none
                +retrieval>
                isa semantic_concept
                entity_id =terrain
            """,
        )

        model.productionstring(
            name=self._name(self.PHASE_RISK, "integrate_semantic_appraisal"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_RISK}
                state await_semantics
                policy none
                outcome none
                =decision_workspace_imaginal>
                isa decision_workspace
                risk_cell =cell
                =semantic_appraisal_imaginal>
                isa semantic_appraisal
                focus_entity =entity
                danger_id =danger
                uncertainty =uncertainty
                passability_id =passability
                affordance_id =affordance
                source pending
                =retrieval>
                isa semantic_concept
                entity_id =entity
                danger_id =danger
                uncertainty =uncertainty
                passability_id =passability
                affordance_id =affordance
                ==>
                +retrieval>
                isa cell_memory
                cell_id =cell
                =g>
                isa firefighting_goal
                phase {self.PHASE_RISK}
                state await_cell_memory
                policy none
                outcome semantics_integrated
            """,
        )

        model.productionstring(
            name=self._name(self.PHASE_RISK, "known_passable_cell"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_RISK}
                state await_cell_memory
                policy none
                outcome semantics_integrated
                =retrieval>
                isa cell_memory
                passability_id passability_passable
                ==>
                =g>
                isa firefighting_goal
                phase {self.PHASE_PLAN}
                state adapter_commit_known_passable
                policy policy_brave_probe
                outcome memory_passable
            """,
        )

        model.productionstring(
            name=self._name(self.PHASE_RISK, "known_blocked_cell"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_RISK}
                state await_cell_memory
                policy none
                outcome semantics_integrated
                =retrieval>
                isa cell_memory
                passability_id passability_blocked
                ==>
                =g>
                isa firefighting_goal
                phase {self.PHASE_PLAN}
                state adapter_commit_known_blocked
                policy policy_cautious_detour
                outcome memory_blocked
            """,
        )

        model.productionstring(
            name=self._name(self.PHASE_RISK, "memory_remains_uncertain"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_RISK}
                state await_cell_memory
                policy none
                outcome semantics_integrated
                =retrieval>
                isa cell_memory
                passability_id passability_unknown
                ==>
                =g>
                isa firefighting_goal
                phase {self.PHASE_DECIDE}
                state choose_disposition
                policy none
                outcome unresolved_fire
            """,
        )

        model.productionstring(
            name=self._name(self.PHASE_RISK, "cell_memory_miss"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_RISK}
                state await_cell_memory
                policy none
                outcome semantics_integrated
                ?retrieval>
                state error
                ==>
                =g>
                isa firefighting_goal
                phase {self.PHASE_DECIDE}
                state choose_disposition
                policy none
                outcome unresolved_fire
            """,
        )

    def _add_disposition_productions(self, model) -> None:
        model.productionstring(
            name=self._name(self.PHASE_DECIDE, "bravery_probe_unknown_fire"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_DECIDE}
                state choose_disposition
                policy none
                outcome unresolved_fire
                =decision_workspace_imaginal>
                isa decision_workspace
                safe_available yes
                risk_cell =cell
                selected_policy none
                =semantic_appraisal_imaginal>
                isa semantic_appraisal
                focus_entity =terrain
                passability_id passability_unknown
                uncertainty high
                ==>
                +retrieval>
                isa strategy_schema
                strategy_id policy_brave_probe
                =g>
                isa firefighting_goal
                phase {self.PHASE_DECIDE}
                state await_brave_policy
                policy policy_brave_probe
                outcome unresolved_fire
            """,
            utility=self.BRAVERY_PRODUCTION_UTILITY,
        )

        model.productionstring(
            name=self._name(self.PHASE_DECIDE, "caution_take_safe_detour"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_DECIDE}
                state choose_disposition
                policy none
                outcome unresolved_fire
                =decision_workspace_imaginal>
                isa decision_workspace
                safe_available yes
                risk_cell =cell
                selected_policy none
                =semantic_appraisal_imaginal>
                isa semantic_appraisal
                focus_entity =terrain
                passability_id passability_unknown
                uncertainty high
                ==>
                +retrieval>
                isa strategy_schema
                strategy_id policy_cautious_detour
                =g>
                isa firefighting_goal
                phase {self.PHASE_DECIDE}
                state await_cautious_policy
                policy policy_cautious_detour
                outcome unresolved_fire
            """,
            utility=self.CAUTION_PRODUCTION_UTILITY,
        )

        model.productionstring(
            name=self._name(self.PHASE_DECIDE, "emergency_bravery_without_detour"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_DECIDE}
                state choose_disposition
                policy none
                outcome unresolved_fire
                =decision_workspace_imaginal>
                isa decision_workspace
                safe_available no
                selected_policy none
                ==>
                +retrieval>
                isa strategy_schema
                strategy_id policy_brave_probe
                =g>
                isa firefighting_goal
                phase {self.PHASE_DECIDE}
                state await_brave_policy
                policy policy_brave_probe
                outcome forced_probe
            """,
            utility=self.EMERGENCY_BRAVERY_UTILITY,
        )

        model.productionstring(
            name=self._name(self.PHASE_DECIDE, "apply_brave_policy"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_DECIDE}
                state await_brave_policy
                policy policy_brave_probe
                outcome =outcome
                =retrieval>
                isa strategy_schema
                strategy_id policy_brave_probe
                disposition_id disposition_brave
                action_id =action
                =decision_workspace_imaginal>
                isa decision_workspace
                safe_next_cell =safe_next
                brave_next_cell =brave_next
                risk_cell =risk
                candidate_terrain_id =terrain
                safe_length =safe_length
                brave_length =brave_length
                route_saving =saving
                safe_available =safe_available
                appraisal_required yes
                selected_policy none
                ==>
                =decision_workspace_imaginal>
                isa decision_workspace
                safe_next_cell =safe_next
                brave_next_cell =brave_next
                risk_cell =risk
                candidate_terrain_id =terrain
                safe_length =safe_length
                brave_length =brave_length
                route_saving =saving
                safe_available =safe_available
                appraisal_required yes
                selected_policy policy_brave_probe
                =g>
                isa firefighting_goal
                phase {self.PHASE_PLAN}
                state adapter_commit_brave
                policy policy_brave_probe
                outcome =outcome
            """,
        )

        model.productionstring(
            name=self._name(self.PHASE_DECIDE, "apply_cautious_policy"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_DECIDE}
                state await_cautious_policy
                policy policy_cautious_detour
                outcome =outcome
                =retrieval>
                isa strategy_schema
                strategy_id policy_cautious_detour
                disposition_id disposition_cautious
                action_id =action
                =decision_workspace_imaginal>
                isa decision_workspace
                safe_next_cell =safe_next
                brave_next_cell =brave_next
                risk_cell =risk
                candidate_terrain_id =terrain
                safe_length =safe_length
                brave_length =brave_length
                route_saving =saving
                safe_available yes
                appraisal_required yes
                selected_policy none
                ==>
                =decision_workspace_imaginal>
                isa decision_workspace
                safe_next_cell =safe_next
                brave_next_cell =brave_next
                risk_cell =risk
                candidate_terrain_id =terrain
                safe_length =safe_length
                brave_length =brave_length
                route_saving =saving
                safe_available yes
                appraisal_required yes
                selected_policy policy_cautious_detour
                =g>
                isa firefighting_goal
                phase {self.PHASE_PLAN}
                state adapter_commit_cautious
                policy policy_cautious_detour
                outcome safe_detour
            """,
        )

    def _add_movement_productions(self, model) -> None:
        for direction, key in {
            "up": "W",
            "down": "S",
            "left": "A",
            "right": "D",
        }.items():
            model.productionstring(
                name=self._name(self.PHASE_MOVE, f"execute_{direction}"),
                string=f"""
                    =g>
                    isa firefighting_goal
                    phase {self.PHASE_MOVE}
                    state ready
                    policy =policy
                    outcome =outcome
                    =route_workspace_imaginal>
                    isa route_workspace
                    direction {direction}
                    next_cell =cell
                    route_kind =kind
                    ?manual>
                    state free
                    ==>
                    +manual>
                    isa _manual
                    cmd 'press_key'
                    key '{key}'
                    =g>
                    isa firefighting_goal
                    phase {self.PHASE_OUTCOME}
                    state inspect_motion
                    policy =policy
                    outcome =outcome
                """,
            )

    def _add_evaluation_productions(self, model) -> None:
        model.productionstring(
            name=self._name(self.PHASE_EVALUATE, "punish_failed_bravery"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_EVALUATE}
                state classify_feedback
                policy policy_brave_probe
                outcome fire_blocked
                =episode_workspace_imaginal>
                isa episode_workspace
                strategy_id policy_brave_probe
                outcome_id outcome_failure
                reward_signal negative
                ==>
                =g>
                isa firefighting_goal
                phase {self.PHASE_LEARN}
                state adapter_consolidate_failure
                policy policy_brave_probe
                outcome fire_blocked
            """,
            reward=self.BRAVERY_FAILURE_REWARD,
        )

        model.productionstring(
            name=self._name(self.PHASE_EVALUATE, "reward_successful_bravery"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_EVALUATE}
                state classify_feedback
                policy policy_brave_probe
                outcome fire_passed
                =episode_workspace_imaginal>
                isa episode_workspace
                strategy_id policy_brave_probe
                outcome_id outcome_success
                reward_signal positive
                ==>
                =g>
                isa firefighting_goal
                phase {self.PHASE_LEARN}
                state adapter_consolidate_success
                policy policy_brave_probe
                outcome fire_passed
            """,
            reward=self.BRAVERY_SUCCESS_REWARD,
        )

        model.productionstring(
            name=self._name(self.PHASE_EVALUATE, "reward_cautious_progress"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_EVALUATE}
                state classify_feedback
                policy policy_cautious_detour
                outcome safe_progress
                =episode_workspace_imaginal>
                isa episode_workspace
                strategy_id policy_cautious_detour
                outcome_id outcome_progress
                reward_signal small_positive
                ==>
                =g>
                isa firefighting_goal
                phase {self.PHASE_LEARN}
                state adapter_consolidate_caution
                policy policy_cautious_detour
                outcome safe_progress
            """,
            reward=self.CAUTIOUS_PROGRESS_REWARD,
        )

        model.productionstring(
            name=self._name(self.PHASE_EVALUATE, "record_clear_progress"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_EVALUATE}
                state classify_feedback
                policy =policy
                outcome clear_progress
                =episode_workspace_imaginal>
                isa episode_workspace
                strategy_id =strategy
                outcome_id outcome_progress
                ==>
                =g>
                isa firefighting_goal
                phase {self.PHASE_LEARN}
                state adapter_consolidate_progress
                policy =policy
                outcome clear_progress
            """,
            reward=0.4,
        )

        model.productionstring(
            name=self._name(self.PHASE_EVALUATE, "record_unexpected_blockage"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_EVALUATE}
                state classify_feedback
                policy =policy
                outcome obstacle_blocked
                =episode_workspace_imaginal>
                isa episode_workspace
                outcome_id outcome_failure
                ==>
                =g>
                isa firefighting_goal
                phase {self.PHASE_LEARN}
                state adapter_consolidate_blockage
                policy =policy
                outcome obstacle_blocked
            """,
            reward=-4.0,
        )

        model.productionstring(
            name=self._name(self.PHASE_EVALUATE, "recognize_target_reached"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_EVALUATE}
                state classify_feedback
                policy =policy
                outcome target_reached
                =mission_context_imaginal>
                isa mission_context
                active_target_id =target
                active_target_cell =cell
                mission_status target_reached
                ==>
                =g>
                isa firefighting_goal
                phase {self.PHASE_TARGET}
                state register_visit
                policy =policy
                outcome target_reached
            """,
        )

    def _add_terminal_productions(self, model) -> None:
        model.productionstring(
            name=self._name(self.PHASE_MISSION, "complete"),
            string=f"""
                =g>
                isa firefighting_goal
                phase {self.PHASE_MISSION}
                state complete
                policy =policy
                outcome all_targets_secured
                =mission_context_imaginal>
                isa mission_context
                mission_status complete
                ==>
                =g>
                isa firefighting_goal
                phase {self.PHASE_MISSION}
                state standby
                policy none
                outcome all_targets_secured
            """,
            reward=30.0,
        )

        self._transition(
            model,
            self._name(self.PHASE_MISSION, "standby"),
            self.PHASE_MISSION,
            "standby",
            self.PHASE_MISSION,
            "standby",
            source_policy="none",
            target_policy="none",
            utility=-20.0,
        )

    @staticmethod
    def _transition(
        model,
        name: str,
        source_phase: str,
        source_state: str,
        target_phase: str,
        target_state: str,
        *,
        source_policy: str = "=policy",
        target_policy: str = "=policy",
        utility: float = 0.0,
        reward: float | None = None,
    ) -> None:
        model.productionstring(
            name=name,
            string=f"""
                =g>
                isa firefighting_goal
                phase {source_phase}
                state {source_state}
                policy {source_policy}
                outcome =outcome
                ==>
                =g>
                isa firefighting_goal
                phase {target_phase}
                state {target_state}
                policy {target_policy}
                outcome none
            """,
            utility=utility,
            reward=reward,
        )
