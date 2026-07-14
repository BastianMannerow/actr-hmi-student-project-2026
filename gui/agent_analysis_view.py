"""Static explainability views for discovered ACT-R agent types."""

from __future__ import annotations

from threading import RLock
from typing import Any, Callable

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.agent_tree import AgentTreeSelection, AgentTreeWidget
from gui.analysis_graphs import (
    ZoomableGraphicsView,
    build_declarative_memory_scene,
    build_interaction_scene,
    build_state_transition_scene,
)
from gui.llm_export import (
    declarative_memory_payload,
    interaction_payload,
    state_graph_payload,
)
from simulation.discovery.agent_discovery import AgentDiscovery
from simulation.inspection.source_analysis import (
    AgentSourceAnalyzer,
    AgentStaticAnalysis,
)


class AgentAnalysisView(QFrame):
    """Visualize production flow, buffer access, and declarative memory.

    All source analysis, layout, routing, and scene construction is delegated to
    the shared background task manager. Switching agent or tab immediately
    invalidates the previous visual result instead of blocking the GUI thread.
    """

    def __init__(
        self,
        simulation: Any,
        parent=None,
        *,
        task_manager=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        self.simulation = simulation
        self.task_manager = task_manager
        self.discovery = AgentDiscovery()
        self.analyzer = AgentSourceAnalyzer()
        self._analysis_cache: dict[str, AgentStaticAnalysis] = {}
        self._cache_lock = RLock()
        self._rendered_tabs: set[tuple[str, str]] = set()
        self._render_generation = 0
        self._active_task_id: str | None = None
        self._discovered_infos = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)

        title = QLabel("Agent Analysis")
        title.setObjectName("sectionTitle")
        outer.addWidget(title)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        self.agent_tree = AgentTreeWidget(splitter)
        self.agent_tree.setMinimumWidth(210)
        self.agent_tree.selection_changed.connect(self._selection_changed)

        details = QWidget(splitter)
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(8, 0, 0, 0)
        details_layout.setSpacing(8)

        self.tabs = QTabWidget(details)
        self.tabs.addTab(self._build_state_graph_tab(), "State Graph")
        self.tabs.addTab(self._build_interaction_tab(), "Buffer Interactions")
        self.tabs.addTab(
            self._build_declarative_memory_tab(), "Declarative Memory"
        )
        self.tabs.currentChanged.connect(self._tab_changed)
        details_layout.addWidget(self.tabs, 1)

        splitter.addWidget(self.agent_tree)
        splitter.addWidget(details)
        splitter.setSizes([230, 980])
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, 1)
        self.refresh()

    def analysis_for_agent(self, agent_name: str) -> AgentStaticAnalysis | None:
        agent = self.simulation.get_agent_by_name(agent_name)
        if agent is None:
            return None
        return self.analysis_for_type(
            str(getattr(agent, "actr_agent_type_name", ""))
        )

    def analysis_for_type(self, agent_type: str) -> AgentStaticAnalysis | None:
        """Synchronous API retained for Production Jump validation."""
        with self._cache_lock:
            cached = self._analysis_cache.get(agent_type)
        if cached is not None:
            return cached
        analysis = self._analyze_type(agent_type)
        if analysis is not None:
            with self._cache_lock:
                self._analysis_cache[agent_type] = analysis
        return analysis

    def _analyze_type(self, agent_type: str) -> AgentStaticAnalysis | None:
        info = next(
            (
                item
                for item in self.discovery.discover()
                if item.name == agent_type
            ),
            None,
        )
        if info is None:
            return None
        return self.analyzer.analyze(info)

    def _build_graph_page(
        self,
        *,
        prefix: str,
        findings: bool = False,
    ) -> tuple[QWidget, ZoomableGraphicsView, QTextEdit | None]:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        toolbar = QHBoxLayout()
        png = QPushButton("Export PNG")
        svg = QPushButton("Export SVG")
        llm = QPushButton("Export for LLM")
        fit = QPushButton("Fit View")
        toolbar.addWidget(png)
        toolbar.addWidget(svg)
        toolbar.addWidget(llm)
        toolbar.addWidget(fit)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        view = ZoomableGraphicsView(page)
        png.clicked.connect(lambda: view.export_dialog("png"))
        svg.clicked.connect(lambda: view.export_dialog("svg"))
        llm.clicked.connect(view.export_for_llm_dialog)
        fit.clicked.connect(view.reset_zoom)
        layout.addWidget(view, 1)
        findings_widget = None
        if findings:
            findings_widget = QTextEdit(page)
            findings_widget.setReadOnly(True)
            findings_widget.setMaximumHeight(135)
            layout.addWidget(findings_widget)
        setattr(self, f"{prefix}_png", png)
        setattr(self, f"{prefix}_svg", svg)
        setattr(self, f"{prefix}_llm", llm)
        setattr(self, f"{prefix}_fit", fit)
        return page, view, findings_widget

    def _build_state_graph_tab(self) -> QWidget:
        page, self.state_graph_view, self.state_findings = self._build_graph_page(
            prefix="state_graph", findings=True
        )
        return page

    def _build_interaction_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        self.interaction_tabs = QTabWidget(page)

        production_page, self.production_graph_view, _ = self._build_graph_page(
            prefix="production"
        )
        self.interaction_tabs.addTab(
            production_page, "Productions → Buffers"
        )

        adapter_page, self.adapter_graph_view, _ = self._build_graph_page(
            prefix="adapter"
        )
        self.interaction_tabs.addTab(
            adapter_page, "Adapter Methods → Buffers"
        )
        self.interaction_tabs.currentChanged.connect(self._tab_changed)
        layout.addWidget(self.interaction_tabs, 1)
        return page

    def _build_declarative_memory_tab(self) -> QWidget:
        page, self.memory_graph_view, _ = self._build_graph_page(prefix="memory")
        return page

    def refresh(self, *, force: bool = False) -> None:
        if self._discovered_infos is None or force:
            self._discovered_infos = self.discovery.discover()
        infos = self._discovered_infos
        selected = self.agent_tree.current_selection()
        self.agent_tree.set_agents(
            list(getattr(self.simulation, "agent_list", [])),
            template_types=[info.name for info in infos],
            preserve_runtime_name=(
                selected.runtime_name if selected is not None else None
            ),
        )
        if self.agent_tree.current_selection() is None:
            for index in range(self.agent_tree.topLevelItemCount()):
                item = self.agent_tree.topLevelItem(index)
                if item is not None:
                    self.agent_tree.setCurrentItem(item)
                    break
        self._schedule_current_tab(force=force)

    def _selection_changed(
        self, selection: AgentTreeSelection | None
    ) -> None:
        if selection is not None:
            self._schedule_current_tab(force=True)

    def _tab_changed(self, _index: int) -> None:
        self._schedule_current_tab(force=False)

    def _current_view_key(self) -> str:
        index = self.tabs.currentIndex()
        if index == 0:
            return "state"
        if index == 1:
            return (
                "production-interactions"
                if self.interaction_tabs.currentIndex() == 0
                else "adapter-interactions"
            )
        return "declarative-memory"

    def _schedule_current_tab(self, *, force: bool) -> None:
        self._render_generation += 1
        generation = self._render_generation

        def render() -> None:
            if generation == self._render_generation:
                self._render_current_selection(
                    force=force, generation=generation
                )

        # The selected tab paints before any heavy task is queued.
        QTimer.singleShot(0, render)

    def _render_current_selection(
        self,
        *,
        force: bool = False,
        generation: int,
    ) -> None:
        selection = self.agent_tree.current_selection()
        if selection is None:
            return
        view_key = self._current_view_key()
        cache_key = (selection.agent_type, view_key)
        if not force and cache_key in self._rendered_tabs:
            return
        agent_type = selection.agent_type
        task_id = f"agent-analysis:{agent_type}:{view_key}"
        title = self._task_title(agent_type, view_key)
        if (
            self.task_manager is not None
            and self._active_task_id is not None
            and self._active_task_id != task_id
        ):
            self.task_manager.invalidate(self._active_task_id)
        self._active_task_id = task_id
        if (
            self.task_manager is not None
            and self.task_manager.is_running(task_id)
        ):
            return
        self._show_loading_placeholder(view_key, title)

        def job(progress):
            progress(5, f"Analysing {agent_type}")
            with self._cache_lock:
                analysis = self._analysis_cache.get(agent_type)
            if analysis is None:
                analysis = self._analyze_type(agent_type)
                if analysis is None:
                    raise RuntimeError(f"Agent type '{agent_type}' was not found")
                with self._cache_lock:
                    self._analysis_cache[agent_type] = analysis
            progress(28, "Preparing graph data")
            if view_key == "state":
                scene = build_state_transition_scene(analysis)
                payload = state_graph_payload(
                    analysis,
                    transition_codes=getattr(scene, "_transition_codes", None),
                )
            elif view_key == "production-interactions":
                title_text = "Which productions read or overwrite which buffers"
                scene = build_interaction_scene(
                    title_text, analysis.production_interactions
                )
                payload = interaction_payload(
                    title_text, analysis.production_interactions
                )
            elif view_key == "adapter-interactions":
                title_text = "Which adapter handlers read or overwrite which buffers"
                scene = build_interaction_scene(
                    title_text, analysis.adapter_interactions
                )
                payload = interaction_payload(
                    title_text, analysis.adapter_interactions
                )
            else:
                title_text = (
                    "Declarative Memory from Agent and Adapter Code — "
                    f"{analysis.agent_type}"
                )
                scene = build_declarative_memory_scene(
                    analysis.declarative_memory, title=title_text
                )
                payload = declarative_memory_payload(
                    analysis.declarative_memory, title=title_text
                )
            progress(92, "Finalizing scene")
            return {
                "analysis": analysis,
                "scene": scene,
                "payload": payload,
                "view_key": view_key,
                "agent_type": agent_type,
            }

        def apply(result: dict[str, Any]) -> None:
            current = self.agent_tree.current_selection()
            if (
                generation != self._render_generation
                or current is None
                or current.agent_type != result["agent_type"]
                or self._current_view_key() != result["view_key"]
            ):
                return
            analysis = result["analysis"]
            view = self._view_for_key(view_key)
            view.setScene(result["scene"])
            view.set_llm_export_data(
                result["payload"],
                default_name=f"{agent_type}_{view_key}",
            )
            view.reset_zoom()
            if view_key == "state":
                self.state_findings.setPlainText(
                    self._findings_text(analysis)
                )
            self._rendered_tabs.add(cache_key)

        if self.task_manager is None:
            try:
                apply(job(lambda _value, _stage=None: None))
            except Exception:
                return
        else:
            self.task_manager.submit(task_id, title, job, apply)

    def _view_for_key(self, view_key: str) -> ZoomableGraphicsView:
        return {
            "state": self.state_graph_view,
            "production-interactions": self.production_graph_view,
            "adapter-interactions": self.adapter_graph_view,
            "declarative-memory": self.memory_graph_view,
        }[view_key]

    def _show_loading_placeholder(self, view_key: str, title: str) -> None:
        view = self._view_for_key(view_key)
        from PyQt6.QtGui import QBrush, QColor
        from PyQt6.QtWidgets import QGraphicsScene, QGraphicsTextItem

        scene = QGraphicsScene()
        scene.setBackgroundBrush(QBrush(QColor("#0f172a")))
        item = QGraphicsTextItem(f"{title} is loading in the background…")
        item.setDefaultTextColor(QColor("#cbd5e1"))
        item.setPos(30, 30)
        scene.addItem(item)
        view.setScene(scene)

    @staticmethod
    def _task_title(agent_type: str, view_key: str) -> str:
        names = {
            "state": "State Graph",
            "production-interactions": "Production Buffer Matrix",
            "adapter-interactions": "Adapter Buffer Matrix",
            "declarative-memory": "Declarative Memory Graph",
        }
        return f"{names[view_key]} · {agent_type}"

    @staticmethod
    def _findings_text(analysis: AgentStaticAnalysis) -> str:
        initial = analysis.states.get(analysis.initial_state_id)
        findings = [
            f"Initial control state: {initial.label if initial else analysis.initial_state_label}",
            f"Expanded productions: {len(analysis.productions)}",
            f"Reachable productions: {sum(1 for item in analysis.productions if item.reachable)}",
            "Unreachable productions: "
            + (
                ", ".join(analysis.unreachable_productions)
                if analysis.unreachable_productions
                else "none"
            ),
            "Dead-end states: "
            + (
                ", ".join(analysis.dead_end_states)
                if analysis.dead_end_states
                else "none"
            ),
            "Terminal states: "
            + (
                ", ".join(analysis.terminal_states)
                if analysis.terminal_states
                else "none"
            ),
            f"States participating in loops: {len(analysis.loop_states)}",
        ]
        if analysis.analysis_warnings:
            findings.extend(["", *analysis.analysis_warnings])
        return "\n".join(findings)
