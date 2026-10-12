"""Regression tests for the public DM API and rendering-only rescue state."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from PyQt6.QtGui import QMovie
import pyactr as actr
from pyactr.declarative import DM, DMBuffer
from pyactr_overrides import configure
from gui.environment_canvas import GridCanvas
from gui.environment_assets import source_pixmap
from gui.environment_symbols import symbol_for_terrain
from simulation.world.environment import Environment
from simulation.world.entities import BurningBush, BurningTree, FireTarget, SpatialAgent

class DMTests(unittest.TestCase):
    def tearDown(self):
        configure(False)

    def test_buffer_property_and_copy(self):
        memory = DM(); buffer = DMBuffer(memory)
        self.assertIs(buffer.dm, memory)
        self.assertIs(buffer.copy().dm, memory)
        buffer.finst = 2
        self.assertEqual(buffer.finst, 2)

    def test_retrieval_with_and_without_boost(self):
        for boost in (False, True):
            configure(boost)
            model = actr.ACTRModel()
            actr.chunktype('test_fact', 'value')
            actr.chunktype('test_goal', 'state answer')
            fact = actr.chunkstring(string='isa test_fact value rescued')
            model.set_dm({fact: [0]})
            self.assertIs(model.dms['dm'], model.dm)
            model.goal.add(actr.chunkstring(string='isa test_goal state start'))
            model.productionstring(name='request', string='=g> isa test_goal state start ==> =g> isa test_goal state waiting +retrieval> isa test_fact value rescued')
            model.productionstring(name='finish', string='=g> isa test_goal state waiting =retrieval> isa test_fact value =x ==> =g> isa test_goal state done answer =x')
            sim = model.simulation(gui=False, trace=False)
            sim.run(.5)
            self.assertIn('state= done', str(model.goal))
            self.assertIn('answer= rescued', str(model.goal))

    def test_visual_model_keeps_memory_mapping(self):
        model = actr.ACTRModel(environment=actr.Environment())
        sim = model.simulation(gui=False, trace=False)
        self.assertIsNotNone(sim)
        self.assertIs(model.retrieval.dm, model.dm)

class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.agent = SpatialAgent('Squirtle')
        self.target = FireTarget()
        self.environment = Environment([[[self.agent], [self.target], []],
                                        [[BurningTree()], [BurningBush(passable=True)], []]])
        self.canvas = GridCanvas(); self.canvas.resize(480, 340)
        self.canvas.set_environment(self.environment); self.canvas.show()
        QTest.qWait(30)

    def tearDown(self):
        self.canvas.close(); self.canvas.deleteLater(); self.app.processEvents()

    def test_local_assets_and_gif(self):
        for name in ('squirtle.png', 'scared-person.svg', 'fire.gif'):
            self.assertFalse(source_pixmap(name).isNull())
        self.assertTrue(self.canvas._movie.isValid())
        self.assertEqual(self.canvas._movie.frameCount(), 20)

    def test_coalesced_visit_persists_without_backend_removal(self):
        cache = self.canvas._static_cache
        self.assertTrue(self.environment.move_agent_right(self.agent))
        self.assertTrue(self.environment.move_agent_right(self.agent))
        self.canvas.refresh_from_environment(); self.app.processEvents()
        self.assertIn((0, 1), self.canvas._reached_targets)
        self.assertIn(self.target, self.environment.objects_at(0, 1))
        self.assertEqual(self.environment.target_positions(), [(0, 1)])
        self.assertIs(cache, self.canvas._static_cache)
        self.canvas.resize(500, 350); self.app.processEvents()
        self.assertIn((0, 1), self.canvas._reached_targets)

    def test_target_pixels_are_removed(self):
        before = self.canvas.grab().toImage()
        self.environment.move_agent_right(self.agent); self.environment.move_agent_right(self.agent)
        self.canvas.refresh_from_environment(); self.app.processEvents()
        after = self.canvas.grab().toImage()
        cell = self.canvas._cell_rect((0, 1)).toAlignedRect()
        self.assertNotEqual(before.copy(cell), after.copy(cell))

    def test_new_run_restores_targets(self):
        self.environment.move_agent_right(self.agent); self.canvas.refresh_from_environment()
        other = Environment([[[SpatialAgent('new')], [FireTarget()], []]])
        self.canvas.set_environment(other); self.app.processEvents()
        self.assertEqual(self.canvas._reached_targets, set())

    def test_initial_overlap_is_recorded(self):
        other = Environment([[[SpatialAgent('new'), FireTarget()]]])
        self.canvas.set_environment(other); self.app.processEvents()
        self.assertEqual(self.canvas._reached_targets, {(0, 0)})

    def test_hidden_and_disabled_animation_stops(self):
        self.canvas.hide(); self.app.processEvents()
        self.assertNotEqual(self.canvas._movie.state(), QMovie.MovieState.Running)
        self.canvas.show(); self.app.processEvents()
        self.assertEqual(self.canvas._movie.state(), QMovie.MovieState.Running)
        self.canvas.set_animation_enabled(False)
        self.assertNotEqual(self.canvas._movie.state(), QMovie.MovieState.Running)

    def test_uncertainty_does_not_leak_collision(self):
        self.assertEqual(symbol_for_terrain(BurningBush(passable=True)),
                         symbol_for_terrain(BurningBush(passable=False)))
        before = self.environment.find_agent(self.agent)
        self.assertFalse(self.environment.move_agent_bottom(self.agent))
        self.assertEqual(self.environment.find_agent(self.agent), before)

    def test_fire_repaints_reuse_static_cache(self):
        cache = self.canvas._static_cache
        frame = self.canvas._movie.currentFrameNumber()
        QTest.qWait(220)
        self.assertIs(cache, self.canvas._static_cache)
        self.assertNotEqual(self.canvas._movie.currentFrameNumber(), frame)

if __name__ == '__main__': unittest.main()
