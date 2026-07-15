"""Optional no-op adapter for the production-only counting model."""


class CountingAgentAdapter:
    def __init__(self, _environment=None) -> None:
        self.agent_construct = None

    def extending_actr(self) -> None:
        return None
