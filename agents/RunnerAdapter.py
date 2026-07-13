"""External bump-feedback adapter for the Runner model."""

from __future__ import annotations

import pyactr as actr

from simulation.integrations import pyactr_extension


class RunnerAdapter:
    def __init__(self, _environment=None):
        self.agent_construct = None
        self.bumped = False

    def extending_actr(self):
        if not self.bumped or self.agent_construct is None:
            return
        goal = pyactr_extension.get_goal(self.agent_construct)
        chunks = list(goal) if goal is not None else []
        previous = "none"
        if chunks:
            try:
                previous = str(chunks[0].previous.values)
            except Exception:
                previous = "none"
        state = "punishedUp" if previous == "up" else "punishedDown"
        chunk = actr.chunkstring(
            string=f"""
                isa runner_goal
                state {state}
                previous {previous}
            """
        )
        pyactr_extension.set_goal(self.agent_construct, chunk)
        self.bumped = False

    def on_bump_detected(self, **_kwargs):
        self.bumped = True
