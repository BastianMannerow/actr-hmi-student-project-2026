"""Structured, lossless graph exports intended for LLM ingestion."""

from __future__ import annotations

from typing import Any

from simulation.inspection.declarative_memory import DeclarativeMemorySnapshot
from simulation.inspection.source_analysis import (
    AgentStaticAnalysis,
    MethodBufferInteraction,
    StateTransitionAnalysis,
)


def state_graph_payload(
    analysis: AgentStaticAnalysis,
    *,
    transition_codes: dict[str, str] | None = None,
) -> dict[str, Any]:
    reachable_transitions = [
        transition
        for transition in analysis.transitions
        if transition.reachable
    ]
    codes = transition_codes or _transition_codes(reachable_transitions)
    state_nodes = [
        {
            "id": state.state_id,
            "node_type": "control_state",
            "label": state.label,
            "phase": state.phase,
            "state": state.state,
            "chunk_type": state.chunk_type,
            "slots": _json_value(state.slots),
            "reachable": state.reachable,
            "initial": state.state_id == analysis.initial_state_id,
            "terminal": state.terminal,
            "dead_end": state.dead_end,
            "adapter_handoff": state.adapter_handoff,
            "loop_member": state.loop_member,
        }
        for state in analysis.states.values()
    ]
    edges = [
        {
            "id": transition.transition_id,
            "source": transition.source_state_id,
            "target": transition.target_state_id,
            "edge_type": transition.kind,
            **_transition_record(
                transition, codes.get(transition.transition_id)
            ),
        }
        for transition in analysis.transitions
    ]
    return {
        "format": "actr-graph-v1",
        "graph_type": "state_graph",
        "agent_type": analysis.agent_type,
        "initial_state_id": analysis.initial_state_id,
        "nodes": state_nodes,
        "edges": edges,
        "unreachable_productions": list(analysis.unreachable_productions),
        "dead_end_states": list(analysis.dead_end_states),
        "terminal_states": list(analysis.terminal_states),
        "loop_states": list(analysis.loop_states),
        "analysis_warnings": list(analysis.analysis_warnings),
    }
def interaction_payload(
    title: str,
    interactions: list[MethodBufferInteraction],
) -> dict[str, Any]:
    methods = sorted({item.method_name for item in interactions})
    buffers = sorted({item.buffer_name for item in interactions})
    return {
        "format": "actr-graph-v1",
        "graph_type": "buffer_interaction_matrix",
        "title": title,
        "method_nodes": [
            {"id": f"method:{name}", "label": name} for name in methods
        ],
        "buffer_nodes": [
            {"id": f"buffer:{name}", "label": name} for name in buffers
        ],
        "interactions": [
            {
                "source": f"method:{item.method_name}",
                "target": f"buffer:{item.buffer_name}",
                "method_name": item.method_name,
                "function_name": item.function_name,
                "buffer_name": item.buffer_name,
                "mode": item.mode,
                "detail": item.detail,
                "triggered_by": list(item.triggered_by),
            }
            for item in interactions
        ],
    }


def declarative_memory_payload(
    snapshot: DeclarativeMemorySnapshot,
    *,
    title: str,
) -> dict[str, Any]:
    return {
        "format": "actr-graph-v1",
        "graph_type": "declarative_memory",
        "title": title,
        "memories": [
            {"id": f"memory:{name}", "name": name}
            for name in snapshot.memories
        ],
        "chunks": [
            {
                "id": chunk.chunk_id,
                "memory_name": chunk.memory_name,
                "label": chunk.label,
                "slots": _json_value(chunk.slots),
                "source": chunk.source,
                "traces": list(chunk.traces),
                "activation": chunk.activation,
            }
            for chunk in snapshot.chunks
        ],
        "edges": [
            {
                "source": edge.source_id,
                "target": edge.target_id,
                "label": edge.label,
                "relation": edge.relation,
            }
            for edge in snapshot.edges
        ],
        "operations": [_json_value(item) for item in snapshot.operations],
    }


def jump_payload(
    analysis: AgentStaticAnalysis,
    target_production: str,
    fired_productions: list[str],
) -> dict[str, Any]:
    path = analysis.transition_path_to_production(target_production) or []
    codes = _transition_codes(path)
    return {
        "format": "actr-graph-v1",
        "graph_type": "production_jump_progress",
        "agent_type": analysis.agent_type,
        "target_production": target_production,
        "fired_productions": list(fired_productions),
        "transition_path": [
            _transition_record(transition, codes.get(transition.transition_id))
            | {
                "source": transition.source_state_id,
                "target": transition.target_state_id,
            }
            for transition in path
        ],
    }


def _transition_codes(
    transitions: list[StateTransitionAnalysis],
) -> dict[str, str]:
    result: dict[str, str] = {}
    counters = {"production": 0, "adapter": 0}
    ordered = sorted(
        transitions,
        key=lambda item: (
            0 if item.kind == "production" else 1,
            item.source_state_id,
            item.target_state_id,
            item.label.casefold(),
            item.transition_id,
        ),
    )
    for transition in ordered:
        family = "adapter" if transition.kind == "adapter" else "production"
        counters[family] += 1
        prefix = "A" if family == "adapter" else "P"
        result[transition.transition_id] = f"{prefix}{counters[family]}"
    return result


def _transition_record(
    transition: StateTransitionAnalysis,
    code: str | None,
) -> dict[str, Any]:
    return {
        "code": code,
        "transition_id": transition.transition_id,
        "label": transition.label,
        "kind": transition.kind,
        "guard": transition.guard_label or None,
        "actions": transition.action_label or None,
        "reachable": transition.reachable,
        "production_name": transition.production_name,
        "adapter_method": transition.adapter_method,
        "trigger_production": transition.trigger_production,
        "utility": transition.utility,
        "reward": transition.reward,
    }


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    return str(value)
