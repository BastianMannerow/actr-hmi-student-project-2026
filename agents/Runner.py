"""Turtle exercise agent adapted from the upstream Runner model."""

from __future__ import annotations

import pyactr as actr


class Runner:
    def __init__(self, environ):
        self.environ = environ
        self.this_agent_key = None
        self.other_agents_key_list = None
        self.actr_agent = actr.ACTRModel(
            environment=environ,
            motor_prepared=True,
            automatic_visual_search=False,
            subsymbolic=True,
        )
        self.initial_goal = None

    def build_agent(self, agent_list):
        self.this_agent_key = agent_list[0]
        self.other_agents_key_list = agent_list[1:]
        actr.chunktype("runner_goal", "state previous")
        self.initial_goal = actr.chunkstring(
            string="""
                isa runner_goal
                state decide
                previous none
            """
        )
        model = self.actr_agent
        model.model_parameters["utility_noise"] = 1.0
        model.model_parameters["baselevel_learning"] = False
        model.productionstring(
            name="initialDecision",
            string="""
                =g>
                isa runner_goal
                state decide
                ==>
                =g>
                isa runner_goal
                state moveUp
                previous none
            """,
        )
        model.productionstring(
            name="moveUp",
            string="""
                =g>
                isa runner_goal
                state moveUp
                ==>
                +manual>
                isa _manual
                cmd press_key
                key W
                =g>
                isa runner_goal
                state evalUp
                previous up
            """,
        )
        model.productionstring(
            name="moveDown",
            string="""
                =g>
                isa runner_goal
                state moveDown
                ==>
                +manual>
                isa _manual
                cmd press_key
                key S
                =g>
                isa runner_goal
                state evalDown
                previous down
            """,
        )
        model.productionstring(
            name="evalUp",
            string="""
                =g>
                isa runner_goal
                state evalUp
                ==>
                =g>
                isa runner_goal
                state moveUp
                previous up
            """,
        )
        model.productionstring(
            name="evalDown",
            string="""
                =g>
                isa runner_goal
                state evalDown
                ==>
                =g>
                isa runner_goal
                state moveDown
                previous down
            """,
        )
        model.productionstring(
            name="punishUp",
            string="""
                =g>
                isa runner_goal
                state punishedUp
                ==>
                =g>
                isa runner_goal
                state moveDown
                previous up
            """,
        )
        model.productionstring(
            name="punishDown",
            string="""
                =g>
                isa runner_goal
                state punishedDown
                ==>
                =g>
                isa runner_goal
                state moveUp
                previous down
            """,
        )
        model.productionstring(
            name="happy",
            string="""
                =g>
                isa runner_goal
                state happy
                ==>
                =g>
                isa runner_goal
                state decide
                previous none
            """,
        )
        return model
