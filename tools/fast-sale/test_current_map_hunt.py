import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
import current_map_hunt as hunt
from warrior_combat import DungeonMap


class CurrentMapTests(unittest.TestCase):
    def session(self):
        return SimpleNamespace(check=Mock(),login_stage=lambda:'playing',held_item=lambda:'',sale_item=lambda:'',
             inflight_item=lambda:'',visible=lambda k:False,u=SimpleNamespace(IsIconic=lambda h:False),hwnd=1)

    def test_changed_map_and_wrong_character_stop_without_input(self):
        for value,role in ((bytes(52),'厚礼蟹'),(hunt.STONE_HEADER,'微笑')):
            with patch.object(hunt,'header',return_value=value),patch.object(hunt,'read_experience',return_value={'character':role}):
                with self.assertRaises(RuntimeError):hunt.StoneTomb().guard(self.session())

    def test_route_is_bounded_to_starting_area(self):
        m=DungeonMap(100,100,[[0]*100 for _ in range(100)],name='d715.map',center=(50,50),radius=32)
        self.assertTrue(m.free((82,50)));self.assertFalse(m.free((83,50)))
        with self.assertRaises(RuntimeError):m.path((50,50),(83,50))

    def test_profile_uses_exact_stone_map_and_bounded_radius(self):
        with patch('warrior_combat.patrol_plan',return_value=('map','plan')) as plan:
            s=self.session();self.assertEqual(hunt.StoneTomb().plan(s),('map','plan'))
            plan.assert_called_once_with(s,expected_header=hunt.STONE_HEADER,expected_name='d715.map',radius=32)

    def test_pending_item_stops_before_input(self):
        s=self.session();s.held_item=lambda:'装备'
        with patch.object(hunt,'header',return_value=hunt.STONE_HEADER),patch.object(hunt,'read_experience',return_value={'character':'厚礼蟹'}):
            with self.assertRaisesRegex(RuntimeError,'物品'):hunt.StoneTomb().guard(s)
