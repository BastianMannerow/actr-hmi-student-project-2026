# ACT-R Multi-Agent Simulation

Desktop application for configuring, running, inspecting, and comparing cognitive multi-agent simulations based on [`pyactr`](https://github.com/jakdot/pyactr). The program uses PyQt6 and starts through `main.py`.

> Detailed installation, configuration, agent-development, and usage instructions are available in the [project wiki](../../wiki).

## Installation and Start

```bash
python -m pip install -r requirements.txt
python main.py
```

The window opens maximized with the standard minimize, maximize/restore, and close controls. The application icon is loaded from `assets/actr_icon.ico` on Windows and `assets/actr_icon.png` on other platforms.

For platform-specific setup and troubleshooting, see the [project wiki](../../wiki).

## Main Areas

Three buttons centered at the bottom switch between:

- **Simulation**
- **Agent Analysis**
- **Multi Simulation Run**

## Simulation

### Runtime Controls

The upper control bar provides:

- start or restart
- pause and resume
- manual Step execution with the button or Space
- Step/Automatic toggle
- speed presets:
  - 1/4 Realtime
  - 1/2 Realtime
  - Realtime
  - 2x Realtime
  - ASAP
- agent-specific production jump
- complete history export as ZIP

Production autocomplete is populated only after a concrete runtime agent has been selected. Before the jump starts, the source analysis checks whether a path from the initial state to the production can be derived.

During the jump, a separate graph marks reached states and fired production edges.

### Human-Controlled Agent

Normal interactive simulations can include one additional human-controlled grid agent.

- Enable the agent under **Configuration → Human-Controlled Agent**.
- Enter an individual name.
- Move with **WASD** or the **arrow keys**.
- Movement remains responsive in every speed mode, including ASAP.
- Keyboard movement is ignored while typing in text fields, combo boxes, spin boxes, or code views.
- Human movement is recorded in the event history.

The human entity occupies the same grid as ACT-R agents but does not own an ACT-R model, productions, buffers, or declarative memory.

### Configuration Persistence

The latest interactive simulation configuration is stored with `QSettings` and restored at the next program start.

**Reset to Default Settings** removes the stored values and restores the defaults.

Newly discovered ACT-R types start with one agent per type. The human-controlled agent is disabled by default.

### Environment

The environment is rendered by `gui/environment_canvas.py`.

Agents are placed on a simple matrix, can share cells, and are displayed with stable per-name colors. The human-controlled entity uses a distinct orange marker.

Visual stimuli are rebuilt from the current matrix state before ACT-R processing. Only pyactr-compatible stimulus fields are passed to the visual system:

- `text`
- `position`
- optional `vis_delay`

Additional GUI and entity metadata are stored separately and are not inserted into pyactr visual chunks.

### Agent Inspector

Runtime ACT-R agents are grouped by type in an expandable tree.

Selecting an agent opens:

- Step Timeline
- Declarative Memory graph
- one tab for every buffer found in the running pyactr simulation
- current buffer content and module state
- complete change history for each buffer

Buffer names are obtained from the active pyactr buffer mapping. Custom goal, retrieval, visual, imaginal, or other user-defined buffers therefore appear without fixed naming assumptions.

### History ZIP

The regular export contains:

- manifest and simulation configuration
- global event timeline in JSON, JSONL, and CSV
- per-agent timelines
- separate histories for every ACT-R buffer
- final environment occupancy
- production metadata
- declarative-memory snapshots
- human movement events and human entity metadata when enabled

## Agent Analysis

Agent models and optional adapters are discovered dynamically in `agents/`.

### State Graph

The State Graph is derived from the agent model and optional adapter.

It shows:

- control states derived from relevant buffer conditions
- production transitions
- adapter-driven state changes
- production names on edges
- loops
- terminal states
- dead ends
- statically unreachable productions
- prerequisite paths used by Production Jump

The graph layout uses:

- deterministic production and adapter edge identifiers
- orthogonal edge routing
- separate edge ports
- collision avoidance around nodes
- parallel lanes for otherwise overlapping edges
- separate styling for production and adapter transitions

Simple constants, attributes, lists, indexed expressions, and local f-string expressions defined in the agent file are resolved where possible.

Adapter references through the associated main-agent object are included when the referenced value can be determined safely.

### Buffer Interactions

Separate access matrices show which productions and adapter handlers:

- read a buffer
- write or request a buffer
- read and write a buffer
- clear a buffer

Production accesses and adapter accesses are displayed separately to avoid ambiguous overlapping connection lines.

### Declarative Memory

The analysis reads:

- chunk construction
- named declarative memories
- explicit memory additions
- retrieval relationships
- deletions
- chunk-slot references
- shared values
- pyactr buffer-to-memory relationships

The graph distinguishes between:

- actual declarative-memory chunks
- statically detected memory writes
- runtime chunks
- buffers linked to declarative memory
- explicit chunk references
- inferred shared-value relationships

Runtime memory graphs use the actual `decmems` mappings of the active pyactr model.

All analysis graphs support:

- zooming
- panning
- fit-to-view
- transparent PNG export
- transparent SVG export

For a detailed explanation of the analysis semantics and their limitations, see the [project wiki](../../wiki).

## Multi Simulation Run

Batch execution is limited to ACT-R agents. Human-controlled agents are removed when interactive settings are transferred into a batch scenario and are disabled again inside every worker process.

Each scenario supports:

- individual environment and ACT-R-agent settings
- repetitions
- parallel or sequential scheduling
- independent speed preset
- stop after a simulation-time limit
- stop after a named production fires for any agent
- per-run safety limit for processed events
- configurable aggregate ZIP destination

Parallel runs execute in isolated processes.

The automatic worker count considers:

- logical CPU cores
- available memory
- resources reserved for the GUI

A crashed run is documented without stopping other runs.

The batch view displays:

- completed percentage
- active and completed runs
- estimated remaining time based on measured run durations and effective parallelism
- individual statuses and errors

One aggregate ZIP contains:

- batch configuration
- JSON and CSV summaries
- status and error information for every run
- each run's complete regular history export

Detailed batch configuration examples are provided in the [project wiki](../../wiki).

## Agent Plug-ins

```text
agents/
  Example.py
  ExampleAdapter.py
```

`<Type>.py` contains the ACT-R model.

`<Type>Adapter.py` is optional. Missing adapters use a no-op adapter; invalid adapters are reported in the configuration view.

Adapters can access the active agent wrapper and use helpers from:

```text
simulation/integrations/pyactr_extension.py
```

The helpers cover:

- named-buffer access and replacement
- goal and imaginal operations
- production utilities
- declarative-memory access
- chunk creation
- ACT-R event inspection

See the [project wiki](../../wiki) for the complete agent and adapter development guide.

## Project Structure

```text
main.py
requirements.txt
README.md

assets/
  actr_icon.ico
  actr_icon.png

agents/
  <AgentType>.py
  <AgentType>Adapter.py

gui/
  application.py
  resources.py
  main_window.py
  human_input_controller.py
  simulation_config_view.py
  environment_view.py
  environment_canvas.py
  step_log_view.py
  buffer_view.py
  declarative_memory_view.py
  agent_analysis_view.py
  analysis_graphs.py
  graph_layout.py
  jump_progress_dialog.py
  multi_simulation_view.py
  mode_toggle.py
  agent_tree.py
  timeline_model.py
  styles.py

simulation/
  runtime/
    simulation.py
    agent_construct.py
    agent_type_factory.py
    middleman.py
    tracer.py

  world/
    entities.py
    human_agent.py
    environment.py
    level_builder.py

  config/
    models.py
    settings_store.py

  discovery/
    agent_discovery.py

  inspection/
    buffer_history.py
    declarative_memory.py
    source_analysis.py

  integrations/
    pyactr_extension.py

  export/
    history_export.py

  batch/
    multi_run.py
```

## Scope of Static Analysis

Source-derived graphs describe structures that can be determined from the available Python files.

The analysis can identify common patterns such as:

- `productionstring(...)` declarations
- dynamically generated production families
- goal-state transitions
- adapter-triggered state changes
- buffer reads and writes
- declarative-memory operations
- locally resolvable variables and f-strings

The following may only become visible during an active simulation:

- arbitrary dynamic Python execution
- externally loaded productions
- runtime-only source modifications
- external data-dependent behavior
- side effects outside recognized model or adapter patterns

Static reachability therefore describes the behavior derivable from the available source code. It is an explainability aid rather than a formal verification proof.

## Documentation

The [project wiki](../../wiki) contains detailed instructions for:

- installation and virtual environments
- interactive simulation
- Step and Automatic execution
- Production Jump
- visual stimulus handling
- creating ACT-R agents
- creating adapters
- working with buffers and declarative memory
- understanding Agent Analysis
- configuring Multi Simulation Run
- interpreting history exports
- troubleshooting
