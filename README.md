# ACT-R Turtle Simulation

PyQt6 desktop application for configuring, running, inspecting, and comparing ACT-R multi-agent simulations in a firefighter TurtleBot scenario. The same runtime supports a virtual grid world and optional ROS 2 control of physical TurtleBot/iRobot Create robots.

Detailed setup and operating instructions are available in the [project wiki](../../wiki).

## Installation

```bash
python -m pip install -r requirements.txt
python main.py
```

The application opens maximized and uses the ACT-R icon from `assets/` as its program and taskbar symbol.

## Main Areas

The navigation at the bottom switches between:

- **Simulation**
- **Agent Analysis**
- **Multi Simulation Run**

## Environment

The Level Builder contains one level:

- **Turtle Simulation** — 25 × 22 cells

The permanent burning-tree geometry is based on the previous laboratory map. Every new run randomly places:

- all enabled agents
- three fire targets
- multiple burning bushes with unknown passability

Burning bushes are positioned on potentially useful shortcuts. Each bush is randomly passable or blocked, but the Level Builder validates the conservative case in which every bush is blocked. Every agent can therefore still reach every fire target by a detour.

### Terrain Symbols

- `X` — burning tree, always blocked
- `B` — burning bush, passability initially unknown
- `F` — fire target
- circular marker — ACT-R or human-controlled agent

The matrix size is defined entirely by the Level Builder and cannot be changed in the GUI.

## Agent Models

Agent models and optional adapters are discovered dynamically in `agents/`.

```text
agents/
  CountingAgent.py
  Squirtle.py
  SquirtleAdapter.py
```

### CountingAgent

`CountingAgent` is a minimal production-only ACT-R model. It counts from one to ten through an explicit production chain and then remains in a terminal standby state. No adapter is used.

Production names are grouped by cognitive phase, for example:

```text
{COUNT}_one_to_two
{COUNT}_nine_to_ten
{COUNT}_ten_complete
```

### Squirtle

Squirtle is a cautious firefighter TurtleBot agent that develops a semantic-spatial mental model, evaluates uncertain burning bushes, learns from movement outcomes, and visits all three fire targets.

The cognitive architecture uses:

- primary Goal buffer
- Retrieval buffer and declarative memory
- `situation_model_imaginal`
- `mission_context_imaginal`
- `decision_workspace_imaginal`
- `semantic_appraisal_imaginal`
- `route_workspace_imaginal`
- `episode_workspace_imaginal`
- Manual buffer for `W`, `A`, `S`, and `D` movement

Production names are grouped by cognitive phase:

```text
{MISSION}_...
{SENSE}_...
{TARGET}_...
{PLAN}_...
{EXPLORE}_...
{RISK}_...
{DECIDE}_...
{MOVE}_...
{OUTCOME}_...
{EVALUATE}_...
{LEARN}_...
{REPLAN}_...
```

#### Semantic Declarative Memory

Before simulation starts, the model seeds declarative memory with invariant semantic knowledge:

- semantic concepts for free ground, burning trees, uncertain burning bushes, unknown terrain, and rescue targets
- passability and danger concepts
- strategy schemas for a brave probe, a cautious detour, and a clear route
- explicit knowledge relations such as `is_a`, `implies`, `connotes`, `tests`, `avoids`, and `motivates`

During simulation, the adapter updates additional linked chunks:

- `cell_memory` for observed and learned cells
- `spatial_relation` for north/south/east/west adjacency
- `target_memory` for discovered and secured objectives
- `episode_memory` for actions, outcomes, rewards, and predecessor episodes
- `knowledge_relation` edges linking cells and episodes to terrain, danger, passability, strategy, and outcome concepts

The shared symbolic identifiers form a lightweight knowledge graph that is visible in Declarative Memory analysis and in the LLM export.

#### Perception and Imaginal Processing

Squirtle does not use the pyactr Visual Module for orientation. `SquirtleAdapter` reads the current `visual_stimuli` matrix and projects it into the internal map. The configured line of sight can be changed without assuming that the complete map is visible.

The adapter writes bounded intermediate representations to the Imaginal buffers. Productions then read and transform these representations. In particular, the risk process retrieves a semantic terrain concept, copies its danger, uncertainty, passability, and affordance into `semantic_appraisal_imaginal`, and subsequently retrieves cell-specific memory.

#### Character Disposition

An unresolved burning bush creates a production conflict between:

```text
{DECIDE}_bravery_probe_unknown_fire
{DECIDE}_caution_take_safe_detour
```

Squirtle is cautious by default. The disposition is configured at the top of `agents/Squirtle.py`:

```python
BRAVERY_PRODUCTION_UTILITY = -0.45
CAUTION_PRODUCTION_UTILITY = 0.80
```

Increasing `BRAVERY_PRODUCTION_UTILITY` makes probing unresolved burning bushes more frequent. Lowering it makes the agent more hesitant. Utility noise preserves non-deterministic choices, while experience modifies the utilities during a run.

#### Evaluation and Learning

Movement is followed by explicit evaluation productions. Examples include:

```text
{EVALUATE}_reward_successful_bravery
{EVALUATE}_punish_failed_bravery
{EVALUATE}_reward_cautious_progress
```

The failure production carries a negative reward and is followed by an explicit reduction of the bravery production utility. Successful probing increases bravery utility; cautious progress slightly reinforces caution. Every evaluated action is also consolidated as an episodic chunk linked to its policy, cell, terrain, predecessor episode, and semantic outcome.

The complete representation and transition design is documented in [`SQUIRTLE_SEMANTIC_MEMORY_MODEL.md`](SQUIRTLE_SEMANTIC_MEMORY_MODEL.md).

## Simulation Controls

The upper toolbar provides:

- start or restart
- pause and resume
- Step through the button or Space
- Step/Automatic toggle
- 1/4 Realtime, 1/2 Realtime, Realtime, 2x Realtime, and ASAP
- agent-specific Production Jump
- complete history export as ZIP

The optional human-controlled agent is available in interactive virtual simulations and moves through WASD or the arrow keys. Human agents are excluded from Multi Simulation Run.

## Visual Stimulus Pipeline

The runtime rebuilds every agent's line-of-sight matrix before its next cognitive event. Application metadata and pyactr input are kept separate.

The pyactr-compatible frame contains only:

- `text`
- `position`
- optional `vis_delay`

Squirtle reads `visual_stimuli` directly. Its ACT-R model is created without a pyactr visual environment, preventing unrelated visual-buffer and environment-process events from interfering with manual movement or cognitive timing.

## Agent Inspector

Runtime agents are grouped by type. Selecting an agent displays:

- Step Timeline
- Declarative Memory graph
- a compact **Buffer History** view with a searchable buffer selector
- current buffer contents and module state
- complete buffer-change histories without one tab per buffer

Long runtime histories are virtualized. The Step Timeline keeps only a bounded window of up to 240 timestamps and 1,200 event records in the Qt model. Every buffer-history table keeps at most 500 visible changes. **Previous**, **Next**, and **Latest** navigate chronologically from the currently selected event or buffer change, including across virtualized pages. The Step Timeline includes a chunked full-history search with **Previous Match** and **Next Match**. Buffer changes are selected through one editable combo box; selecting an empty buffer clears the prior table immediately. Declarative Memory and buffer history are loaded only when opened.

Runtime GUI notifications are coalesced instead of rebuilding views after every ACT-R event. During Automatic execution, the main window refreshes at a bounded rate and updates only the visible main page, the visible environment/configuration page, and the currently selected Agent Inspector tab. Hidden state graphs, memory graphs, buffer tables, and batch controls do not perform runtime work. A tab change is deferred by one Qt event-loop turn so the new tab can be painted before its bounded data window is loaded.

All expensive graph preparation runs through one serialized background-task pipeline. Source analysis, relationship inference, layout, orthogonal routing, and `QGraphicsScene` construction no longer run in the GUI thread. A progress indicator in the bottom-left status bar shows the current task, current processing stage, percentage, queued work, and estimated remaining time. Rapid tab changes invalidate stale results and repeated live requests are coalesced instead of creating duplicate graph jobs.

During Automatic execution, the Declarative Memory graph updates adaptively rather than after every cognitive event. A lightweight preflight stops live redraws before memory size, inferred relationships, or measured render time exceed the real-time GUI budget. The last valid graph remains visible and the tab displays: **“Live declarative-memory rendering has been paused because the graph complexity exceeds real-time GUI performance. Pause the simulation to load the current graph.”** When paused, medium-sized memories are displayed in bounded pages. Extremely large memories are summarized instead of synchronously constructing a scene; their complete data remains available through History Export.

## Agent Analysis

Agent Analysis builds its model from the executable pyactr agent and inspects the optional adapter source.

### State Graph

The State Graph includes:

- production transitions
- adapter-driven Goal-state changes
- terminal states
- loops
- dead ends
- reachability
- Production Jump prerequisite paths

Complex graphs use orthogonal, obstacle-aware routing, separate edge ports, deterministic production/adapter identifiers, and congestion-aware parallel lanes. States within the same cognitive phase are ordered by directed transition continuity before the global layout is scored. A linear production chain is therefore drawn as adjacent states in execution order instead of being scattered alphabetically.

A final geometry-validation pass checks every rendered route. Every edge enters and leaves its incident node through a normal North, East, South, or West stub and may not return through the node interior. Residual collinear overlaps are replaced by local right-angle detours with at least 20 pixels of lane separation. The same spacing rule applies uniformly to production and adapter edges. If a presentation-only lane shift would touch another node, only the affected segment is routed around the complete obstruction band. Solid production edges and dashed adapter edges therefore never occupy the same visible segment. Legend panels reserve protected scene space and cannot overlap nodes, routes, or edge labels.

### Buffer Interactions

Separate matrices show which productions and adapter handlers read, write, request, or clear each buffer.

### Declarative Memory

The memory analysis distinguishes:

- declared memories
- retrieval relationships
- buffer-to-memory links
- explicit terrain-memory writes
- runtime chunks
- static chunk references

All graph views support zooming, panning, fit-to-view, transparent PNG export, transparent SVG export, and **Export for LLM**. The LLM export is lossless UTF-8 JSON using the `actr-graph-v1` schema. It records typed nodes, directed edges, P/A identifiers, guards, actions, buffer-access modes, declarative-memory chunks, relationships, reachability, loops, terminal states, and dead ends without relying on pixels or OCR.

Implementation details and the export schema are documented in [`ASYNC_GRAPH_LOADING_AND_EXPORT.md`](ASYNC_GRAPH_LOADING_AND_EXPORT.md).

## ROS Real-life Backend

ROS mode retains the Turtle Simulation level as a shadow map while translating Manual-buffer movement into physical robot commands.

Supported interfaces:

- iRobot Create `DriveDistance` and `RotateAngle` actions
- generic `cmd_vel`
- odometry
- bumper/hazard feedback

ROS scenarios in Multi Simulation Run execute sequentially. ROS dependencies are supplied by the active ROS 2 installation and are not installed through `requirements.txt`.

## Multi Simulation Run

Each scenario configures:

- virtual or ROS backend
- ACT-R agent counts
- speed preset
- repetitions
- parallel or sequential scheduling
- end by simulation time or fired production
- aggregate ZIP destination

Virtual runs execute in isolated worker processes. A crashed run is recorded without stopping the remaining runs. The batch view reports completion percentage, individual status, and estimated time remaining.

## History Export

The regular history ZIP contains:

- manifest and complete configuration
- global and per-agent event timelines
- separate histories for every ACT-R buffer
- production metadata including utilities and rewards
- final matrix occupancy
- declarative-memory snapshots
- human and ROS events where applicable

## Project Structure

```text
main.py
assets/
  actr_icon.ico
  actr_icon.png
agents/
  CountingAgent.py
  Squirtle.py
  SquirtleAdapter.py
gui/
  application.py
  main_window.py
  simulation_config_view.py
  multi_simulation_view.py
  environment_view.py
  environment_canvas.py
  step_log_view.py
  buffer_view.py
  declarative_memory_view.py
  agent_analysis_view.py
  analysis_graphs.py
  graph_layout.py
simulation/
  runtime/
  world/
  integrations/
  config/
  discovery/
  inspection/
  export/
  batch/
tests/
  test_agents.py
  test_level_builder.py
  test_visual_stimuli.py
```

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests cover randomized level reachability, the explicit counting chain, Squirtle's initial semantic knowledge graph, dynamic cell-memory upserts, Imaginal architecture, rewards and punishments, actual pyactr conflict resolution under different bravery utilities, complete Agent Analysis reachability, GUI performance safeguards, graph routing, and visual-stimulus separation.
