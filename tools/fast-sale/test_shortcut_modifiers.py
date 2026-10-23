import unittest
from types import SimpleNamespace
from unittest.mock import patch

from background_sale import BackgroundSession


class ModifierTests(unittest.TestCase):
    def fake(self, held):
        class Fake(BackgroundSession):
            def __init__(self):
                self.clock=0
                self.u=SimpleNamespace(GetAsyncKeyState=lambda key: 0x8000 if held(self.clock,key) else 0)
            def check(self):pass
            def pause(self,seconds):self.clock+=seconds
        return Fake()

    def test_desktop_modifier_is_waited_out_without_synthetic_release(self):
        s=self.fake(lambda now,key: now<1 and key==0x11)
        with patch('background_sale.time.monotonic',side_effect=lambda:s.clock):
            s.wait_shortcut_modifiers_released(timeout=3)
        self.assertGreaterEqual(s.clock,1.25)

    def test_continuously_held_modifier_stops_with_no_game_input(self):
        s=self.fake(lambda now,key: key==0x12)
        with patch('background_sale.time.monotonic',side_effect=lambda:s.clock):
            with self.assertRaisesRegex(RuntimeError,'未发送快捷键'):
                s.wait_shortcut_modifiers_released(timeout=1)

    def test_modifier_repress_resets_stable_release_period(self):
        s=self.fake(lambda now,key: .15<=now<.4 and key==0x10)
        with patch('background_sale.time.monotonic',side_effect=lambda:s.clock):
            s.wait_shortcut_modifiers_released(timeout=2)
        self.assertGreaterEqual(s.clock,.65)

    def test_mouse_waits_for_alt_without_releasing_users_key(self):
        s=self.fake(lambda now,key: now<1 and key==0x12)
        with patch('background_sale.time.monotonic',side_effect=lambda:s.clock):
            s.wait_mouse_modifiers_released()
        self.assertGreaterEqual(s.clock,1.25)

    def test_mouse_without_modifiers_adds_no_wait(self):
        s=self.fake(lambda now,key:False)
        s.wait_mouse_modifiers_released()
        self.assertEqual(s.clock,0)
