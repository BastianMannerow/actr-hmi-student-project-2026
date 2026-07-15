"""A minimal production-only ACT-R counting demonstration."""

from __future__ import annotations

import pyactr as actr


class CountingAgent:
    """Count from one to ten using only ACT-R productions.

    The agent deliberately has no adapter. It demonstrates a transparent
    production chain and remains in a terminal standby state after reaching ten.
    """

    PHASE_COUNT = "COUNT"
    uses_visual_module = False
    analysis_control_slots = ("value", "state")

    def __init__(self, environ):
        self.environ = environ
        self.this_agent_key = None
        self.other_agents_key_list = None
        self.actr_agent = actr.ACTRModel(
            environment=None,
            motor_prepared=True,
            automatic_visual_search=False,
            subsymbolic=False,
        )
        self.initial_goal = None

    def build_agent(self, agent_list):
        self.this_agent_key = agent_list[0]
        self.other_agents_key_list = agent_list[1:]
        model = self.actr_agent

        actr.chunktype("counting_goal", "value state")

        self.initial_goal = actr.chunkstring(
            string="""
                isa counting_goal
                value one
                state counting
            """
        )

        model.productionstring(
            name=f"{self.PHASE_COUNT}_one_to_two",
            string="""
                =g>
                isa counting_goal
                value one
                state counting
                ==>
                =g>
                isa counting_goal
                value two
                state counting
            """,
        )

        model.productionstring(
            name=f"{self.PHASE_COUNT}_two_to_three",
            string="""
                =g>
                isa counting_goal
                value two
                state counting
                ==>
                =g>
                isa counting_goal
                value three
                state counting
            """,
        )

        model.productionstring(
            name=f"{self.PHASE_COUNT}_three_to_four",
            string="""
                =g>
                isa counting_goal
                value three
                state counting
                ==>
                =g>
                isa counting_goal
                value four
                state counting
            """,
        )

        model.productionstring(
            name=f"{self.PHASE_COUNT}_four_to_five",
            string="""
                =g>
                isa counting_goal
                value four
                state counting
                ==>
                =g>
                isa counting_goal
                value five
                state counting
            """,
        )

        model.productionstring(
            name=f"{self.PHASE_COUNT}_five_to_six",
            string="""
                =g>
                isa counting_goal
                value five
                state counting
                ==>
                =g>
                isa counting_goal
                value six
                state counting
            """,
        )

        model.productionstring(
            name=f"{self.PHASE_COUNT}_six_to_seven",
            string="""
                =g>
                isa counting_goal
                value six
                state counting
                ==>
                =g>
                isa counting_goal
                value seven
                state counting
            """,
        )

        # Intentionally no seven-to-eight production: the counting demo
        # retains a visible functional gap/dead end at seven.

        model.productionstring(
            name=f"{self.PHASE_COUNT}_eight_to_nine",
            string="""
                =g>
                isa counting_goal
                value eight
                state counting
                ==>
                =g>
                isa counting_goal
                value nine
                state counting
            """,
        )

        model.productionstring(
            name=f"{self.PHASE_COUNT}_nine_to_ten",
            string="""
                =g>
                isa counting_goal
                value nine
                state counting
                ==>
                =g>
                isa counting_goal
                value ten
                state counting
            """,
        )

        model.productionstring(
            name=f"{self.PHASE_COUNT}_ten_complete",
            string="""
                =g>
                isa counting_goal
                value ten
                state counting
                ==>
                =g>
                isa counting_goal
                value ten
                state complete
            """,
        )

        model.productionstring(
            name=f"{self.PHASE_COUNT}_standby",
            string="""
                =g>
                isa counting_goal
                value ten
                state complete
                ==>
                =g>
                isa counting_goal
                value ten
                state complete
            """,
            utility=-10,
        )

        return model
