# ACT-R TurtleBot Multi-Agent Simulation

PyQt6 desktop application for configuring, running, inspecting, and comparing cognitive multi-agent simulations based on `pyactr`. The application supports a virtual TurtleBot grid world and ROS 2 control of physical TurtleBot/iRobot Create robots through the same runtime and GUI.

## Installation

```bash
python -m pip install -r requirements.txt
python main.py
```

The program opens maximized with standard window controls. The application and taskbar icon are loaded from `assets/actr_icon.ico` on Windows and `assets/actr_icon.png` on other platforms.

## Application areas

The centered navigation at the bottom switches between:

- **Simulation**
- **Agent Analysis**
- **Multi Simulation Run**

## Environment backends

The backend is selected under **Simulation → Configuration → Environment** and separately for every Multi Simulation scenario.

### Virtual Environment

The simulation uses the integrated collision-aware grid backend. Available levels are:

- **Open Grid** — 16 × 16 matrix defined by the Level Builder
- **Turtle Exercise 1** — 16 × 16 open exercise grid
- **Turtle Exercise 2** — 5 × 9 bordered exercise with known, solid, and passable obstacles
- **Johannes Lab** — 25 × 22 navigation map with obstacles, passable obstacles, known walls, and a target

The selected Level Builder defines the matrix dimensions; width and height cannot be overridden in the GUI.

The environment supports:

- multiple ACT-R agents
- stable grid positions and collision checks
- `W`, `A`, `S`, and `D` motor actions from pyactr manual-buffer events
- line-of-sight based symbolic perception
- wall, passable-obstacle, known-wall, and target entities
- bump callbacks into the selected agent adapter
- an optional human-controlled agent for interactive virtual simulations

The grid renderer distinguishes known walls, solid walls, passable obstacles, targets, ACT-R agents, and human agents with separate colors and symbols. A legend is displayed below the matrix.

Visual frames sent to pyactr contain only supported stimulus fields (`text`, `position`, and optional `vis_delay`). World-specific metadata is stored separately for inspection. Before every cognitive step, the scheduled agent publishes its current line-of-sight frame, so visual-location and visual-buffer operations use the latest grid values. Empty-schedule resets reuse the same validated frame.

### ROS Real-life

ROS mode maps the same ACT-R motor actions to physical robots while retaining the selected level as a shadow map for the GUI, symbolic perception, collision checks, and exported history.

Two control interfaces are available:

1. **iRobot Create actions**
   - `irobot_create_msgs/action/DriveDistance`
   - `irobot_create_msgs/action/RotateAngle`
   - `irobot_create_msgs/msg/HazardDetectionVector`
   - `nav_msgs/msg/Odometry`
2. **Generic cmd_vel**
   - `geometry_msgs/msg/Twist`
   - odometry through `nav_msgs/msg/Odometry`
   - optional bumper input from a compatible `BumperEvent` or `std_msgs/Bool` topic

The namespace template defaults to `/tb{index}`. For three runtime agents this resolves to `/tb1`, `/tb2`, and `/tb3`. Topic and action names, movement speeds, cell size, node prefix, and timeout are configurable in the GUI.

ROS packages are supplied by the active ROS 2 installation and are intentionally not installed through `requirements.txt`. Start the application from a sourced ROS 2 environment. The iRobot action interface requires at least:

```text
rclpy
nav_msgs
action_msgs
irobot_create_msgs
```

The generic velocity interface additionally requires `geometry_msgs`.

A missing ROS package, action server, or movement timeout is reported in the GUI and recorded in the event timeline. ROS movements run asynchronously; Automatic execution and Production Jump pause until the physical movement has completed or failed.

## Integrated agent models

Agent models and optional adapters are discovered dynamically in `agents/`.

```text
agents/
  Example.py
  ExampleAdapter.py
  Runner.py
  RunnerAdapter.py
  JohannesAgent.py
  JohannesAgentAdapter.py
```

### Runner

The Turtle exercise agent uses ACT-R productions to choose and execute vertical movement. Its adapter receives bump feedback and changes the goal state so the agent reverses direction after a collision.

### JohannesAgent

The Johannes navigation agent uses separate locate, pathfinding, movement, evaluation, goal, and retrieval phases. It defines multiple custom goal/imaginal buffers and declarative-memory chunk types. Its adapter:

- reads the active environment
- identifies the current position and target
- plans grid paths
- writes the next movement into ACT-R buffers
- records encountered obstacles in declarative memory
- reacts to virtual or ROS bumper feedback

## Simulation

### Runtime controls

The upper control bar provides:

- start or restart
- pause and resume
- manual **Step** through the button or Space
- Step/Automatic toggle
- speed presets: 1/4 Realtime, 1/2 Realtime, Realtime, 2x Realtime, ASAP
- agent-specific Production Jump with autocomplete
- complete history export as ZIP

Production choices are populated after a concrete runtime agent is selected. Static source analysis checks whether the target production is reachable. During the jump, a graph marks reached states and fired production edges.

### Human-controlled agent

One additional human-controlled grid agent can be enabled for interactive **virtual** simulations.

- configurable name
- movement through WASD or arrow keys
- independent of ACT-R timing and speed presets
- recorded in the event history

Human agents are disabled in ROS mode and Multi Simulation Run.

### Configuration persistence

The latest interactive configuration is stored with `QSettings` and restored at the next start. **Reset to Default Settings** removes the stored configuration.

### Agent Inspector

Runtime ACT-R agents are grouped by type in an expandable tree. Selecting an agent opens:

- Step Timeline
- Declarative Memory graph
- one tab for every buffer in the active pyactr simulation
- current buffer content and module state
- complete buffer-change history

Buffer names are read from the running pyactr model; custom goal, retrieval, visual, imaginal, or other named buffers therefore appear without fixed naming assumptions.

### History ZIP

The regular export contains:

- manifest and full simulation configuration, including backend and ROS parameters
- global timeline in JSON, JSONL, and CSV
- per-agent timelines
- separate histories for every ACT-R buffer
- final environment/shadow-map occupancy
- production metadata
- declarative-memory snapshots
- human events when enabled
- ROS movement and error events when ROS mode is active

## Agent Analysis

### State Graph

The graph uses the productions of the fully built pyactr model, including rules created in loops and helper methods. Goal control states are derived from the slots actually read by productions. Production edges and adapter goal-buffer overrides are displayed separately, with branch guards, terminal states, loops, genuine dead ends, and statically unreachable productions. Production Jump uses the same combined production/adapter control-flow model.

### Buffer Interactions

Separate interaction matrices show which productions and production-triggered adapter handlers read, request, clear, or overwrite each dynamically discovered buffer. Matrix cells replace crossing connection lines and adapter rows identify the productions that activate each handler.

### Declarative Memory

The static analysis distinguishes explicit declarative-memory writes from chunks that are only created for a goal or imaginal buffer. It also displays the buffers linked to each declarative memory by pyactr, explicit additions or deletions, chunk references, and weaker shared-value associations. Runtime graphs use the actual memory mappings of the active pyactr model.

All graphs support zooming, panning, and transparent PNG or SVG export.

## Multi Simulation Run

Each scenario can independently select:

- Virtual Environment or ROS Real-life
- level or ROS shadow map
- ACT-R agent types and counts
- ROS interface, namespace, topics/actions, speeds, cell size, and timeout
- repetition count
- speed preset
- simulation-time or production-based termination
- parallel or sequential scheduling

Virtual scenarios can run in isolated parallel worker processes. ROS scenarios are forced to **Sequential** because they control physical hardware and must not compete for the same robot topics or action servers. A crashed run is documented without terminating other runs.

The batch view shows completed percentage, run statuses, errors, and an estimated remaining time based on measured durations. One aggregate ZIP contains the batch configuration, JSON/CSV summaries, each run status, error traces, and every run's complete history archive.

## Project structure

```text
main.py
assets/
  actr_icon.ico
  actr_icon.png
agents/
  Example.py
  ExampleAdapter.py
  Runner.py
  RunnerAdapter.py
  JohannesAgent.py
  JohannesAgentAdapter.py
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
  jump_progress_dialog.py
  human_input_controller.py
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
    factory.py
    level_builder.py
  integrations/
    pyactr_extension.py
    ros_turtle_bridge.py
  config/
    models.py
    settings_store.py
  discovery/
    agent_discovery.py
  inspection/
    buffer_history.py
    declarative_memory.py
    source_analysis.py
  export/
    history_export.py
  batch/
    multi_run.py
```

## Source integration

The virtual TurtleBot entities, exercise environment, Runner model, and movement semantics are integrated from the repository's master branch. The Johannes laboratory map, Johannes agent/adapter concepts, and iRobot Create ROS action interface are integrated from `johannes_branch` and adapted to the current modular PyQt6 runtime.

## Scope of source analysis

Source-derived graphs show structures that can be determined from the available Python model and adapter files. Runtime-generated productions, arbitrary dynamic Python execution, and external side effects may only become visible during an active simulation.

## Regression tests

```bash
python -m unittest discover -s tests -v
```

The included tests cover pyactr stimulus sanitization, safe continuation after an EmptySchedule reset, and the presence of all Johannes Lab terrain entities.
#   a c t r - h m i - s t u d e n t - p r o j e c t - 2 0 2 6  
 