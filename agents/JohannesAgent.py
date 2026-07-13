"""Navigation agent adapted from the repository's ``johannes_branch``."""

from __future__ import annotations

import pyactr as actr


class JohannesAgent:
    """ACT-R TurtleBot agent with locate, pathfinding, movement and memory phases."""

    def __init__(self, environ):
        self.environ = environ
        self.this_agent_key = None
        self.other_agents_key_list = None
        self.goal_phases = ["locate", "pathfinding", "moving", "eval", "goal", "retrieval"]
        self.actr_agent = actr.ACTRModel(
            environment=environ,
            motor_prepared=True,
            automatic_visual_search=False,
            subsymbolic=False,
        )
        self.initial_goal = None

    def build_agent(self, agent_list):
        self.this_agent_key = agent_list[0]
        self.other_agents_key_list = agent_list[1:]
        model = self.actr_agent
        model.model_parameters["utility_noise"] = 0
        model.model_parameters["baselevel_learning"] = True

        actr.chunktype("goal", "phase state prev_phase")
        actr.chunktype(
            "agent",
            "current_pos_x current_pos_y goal_pos_x goal_pos_y start_pos_x start_pos_y",
        )
        actr.chunktype(
            "path_and_obs",
            "check_obstacle_pos_x check_obstacle_pos_y next_pos_x next_pos_y "
            "next_pos_might_be_obstacle bumped direction",
        )
        actr.chunktype("obstacle", "obstacle_pos_x obstacle_pos_y status")
        actr.chunktype("retrieval", "pos_x pos_y status state")

        self.initial_goal = actr.chunkstring(
            string="""
                isa goal
                phase init
                state init
                prev_phase init
            """
        )
        model.set_goal(name="imaginal_agent", delay=0)
        model.set_goal(name="path_and_obs_imaginal", delay=0)
        model.set_goal(name="obstacle_update_imaginal", delay=0)

        self.add_init_productions(model, self.goal_phases[0])
        self.add_pathfinding_productions(model, self.goal_phases[1])
        self.add_moving_productions(model, self.goal_phases[2])
        self.add_eval_productions(model, self.goal_phases[3])
        self.add_goal_productions(model, self.goal_phases[4])
        self.add_retrieval_productions(model, self.goal_phases[5])
        return model

    def add_init_productions(self, model, phase):
        self._production(model, "init", "init", "init", "locate", "locate_self")
        self._production(model, "locate_self", "locate", "locate_self", "locate", "locate_wait")
        self._production(model, "locate_obstacles", "locate", "locate_obstacles", "locate", "locate_wait")
        self._production(model, "locate_goal", "locate", "locate_goal", "locate", "locate_wait")
        self._production(model, "locate_finished", "locate", "ready", "pathfinding", "start")

    def add_pathfinding_productions(self, model, phase):
        self._production(model, "pathfinding_start", "pathfinding", "start", "pathfinding", "calculate")
        self._production(model, "pathfinding_fast_path", "pathfinding", "fast_path", "moving", "move")
        self._production(model, "pathfinding_safe_path", "pathfinding", "safe_path", "moving", "move")
        self._production(
            model,
            "pathfinding_check_obstacles_on_path",
            "pathfinding",
            "check_obstacle",
            "retrieval",
            "request",
        )

    def add_moving_productions(self, model, phase):
        self._move_production(model, "moving_simply_moveUp", "moving", "up", "W", "eval", "up")
        self._move_production(model, "moving_simply_moveDown", "moving", "down", "S", "eval", "down")
        self._move_production(model, "moving_simply_moveLeft", "moving", "left", "A", "eval", "left")
        self._move_production(model, "moving_simply_moveRight", "moving", "right", "D", "eval", "right")
        self._production(model, "moving_move_to_goal", "moving", "move_to_goal", "moving", "move")
        self._production(model, "moving_decide_direction", "moving", "decide", "pathfinding", "start")
        for direction in ("Up", "Down", "Left", "Right"):
            self._production(
                model,
                f"moving_eval_after_move{direction}",
                "moving",
                f"eval_{direction.lower()}",
                "eval",
                direction.lower(),
            )

    def add_eval_productions(self, model, phase):
        for direction in ("Up", "Down", "Left", "Right"):
            self._production(
                model,
                f"eval_eval{direction}",
                "eval",
                direction.lower(),
                phase,
                "adapter_check",
            )
        self._production(model, "eval_continue", "eval", "continue", "pathfinding", "start")
        self._production(model, "eval_bumped", "eval", "bumped", "retrieval", "update_obstacle")

    def add_goal_productions(self, model, phase):
        self._production(model, "goal_reached", "goal", "reached", "goal", "finished")

    def add_retrieval_productions(self, model, phase):
        names = (
            "retrieval_obstacle_request",
            "retrieval_obstacle_request_solid_positive",
            "retrieval_obstacle_request_unknown_positive",
            "retrieval_obstacle_request_passable_positive",
            "retrieval_decide_that_obstacle_is_passable",
            "retrieval_decide_that_obstacle_is_solid",
            "retrieval_clear_obstacle_imaginal_passable",
            "retrieval_clear_obstacle_imaginal_solid",
        )
        for name in names:
            source_state = "request" if name == "retrieval_obstacle_request" else name.removeprefix("retrieval_")
            self._production(model, name, "retrieval", source_state, "pathfinding", "start")

    @staticmethod
    def _production(model, name, source_phase, source_state, target_phase, target_state):
        model.productionstring(
            name=name,
            string=f"""
                =g>
                isa goal
                phase {source_phase}
                state {source_state}
                ==>
                =g>
                isa goal
                phase {target_phase}
                state {target_state}
                prev_phase {source_phase}
            """,
        )

    @staticmethod
    def _move_production(model, name, phase, direction, key, target_phase, target_state):
        model.productionstring(
            name=name,
            string=f"""
                =g>
                isa goal
                phase {phase}
                state move
                =path_and_obs_imaginal>
                isa path_and_obs
                direction {direction}
                ?manual>
                state free
                ==>
                +manual>
                isa _manual
                cmd 'press_key'
                key '{key}'
                =g>
                isa goal
                phase {target_phase}
                state {target_state}
                prev_phase {phase}
            """,
        )
