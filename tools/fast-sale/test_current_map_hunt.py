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

    def test_profile_uses_exact_stone_map_without_local_radius(self):
        with patch('warrior_combat.patrol_plan',return_value=('map','plan')) as plan:
            s=self.session();self.assertEqual(hunt.StoneTomb().plan(s),('map','plan'))
            plan.assert_called_once_with(s,expected_header=hunt.STONE_HEADER,expected_name='d715.map',radius=None)

    def test_pending_item_stops_before_input(self):
        s=self.session();s.held_item=lambda:'装备'
        with patch.object(hunt,'header',return_value=hunt.STONE_HEADER),patch.object(hunt,'read_experience',return_value={'character':'厚礼蟹'}):
            with self.assertRaisesRegex(RuntimeError,'物品'):hunt.StoneTomb().guard(s)

    def test_known_panel_waits_without_input_and_does_not_override_item_checks(self):
        s=self.session();s.visible=lambda key:key=='bag'
        with patch.object(hunt,'header',return_value=hunt.STONE_HEADER),patch.object(hunt,'read_experience',return_value={'character':'厚礼蟹'}):
            self.assertTrue(hunt.StoneTomb().wait_for_panels(s))
            s.visible=lambda key:False
            self.assertFalse(hunt.StoneTomb().wait_for_panels(s))
            s.held_item=lambda:'物品'
            with self.assertRaisesRegex(RuntimeError,'物品'):hunt.StoneTomb().wait_for_panels(s)

    def test_message_popup_is_not_treated_as_normal_panel_wait(self):
        s=self.session();s.login_stage=lambda:'message'
        with self.assertRaisesRegex(RuntimeError,'状态变化'):hunt.StoneTomb().wait_for_panels(s)

    def test_system_activity_window_closes_only_through_verified_close_control(self):
        visible=[True];s=self.session();s.visible=lambda key:key=='merchant' and visible[0]
        s.control_info=Mock(return_value={'visible':True,'bounds':(400,0,16,20)})
        s.bounds=lambda key:(10,20,416,176)
        s.click=Mock(side_effect=lambda point:visible.__setitem__(0,False));s.pause=Mock()
        with patch.object(hunt,'header',return_value=hunt.STONE_HEADER),patch.object(hunt,'read_experience',return_value={'character':'厚礼蟹'}):
            self.assertFalse(hunt.StoneTomb().wait_for_panels(s))
        s.control_info.assert_called_once_with(0x5e4,'Button_MerchantDlgClose')
        s.click.assert_called_once_with((418,30))

    def test_activity_close_failure_does_not_spam_click_or_terminate_hunt(self):
        s=self.session();s.visible=lambda key:key=='merchant'
        s.control_info=Mock(return_value={'visible':True,'bounds':(400,0,16,20)})
        s.bounds=lambda key:(0,0,416,176);s.click=Mock();s.pause=Mock()
        with patch.object(hunt,'header',return_value=hunt.STONE_HEADER),patch.object(hunt,'read_experience',return_value={'character':'厚礼蟹'}):
            for _ in range(3):self.assertTrue(hunt.StoneTomb().wait_for_panels(s))
        s.click.assert_called_once()

    def test_normal_map_requests_continuous_holding_and_full_coverage_spacing(self):
        profile=hunt.StoneTomb();options=profile.move_options()
        self.assertTrue(options['allow_hold']);self.assertEqual(options['expected_header'],hunt.STONE_HEADER)
        self.assertEqual(profile.route_spacing,24)
        self.assertEqual(options['hold_guard'],profile.guard)

    def test_near_black_maggot_prevents_leaving_for_patrol_if_local_route_blocked(self):
        profile=hunt.StoneTomb();profile.guard=Mock();profile.tilemap=SimpleNamespace(free=lambda xy:False)
        target={'name':'黑色恶蛆','class':'TCatMon','dead':False,'position':(52,50),'distance':2}
        s=SimpleNamespace(nearby_monsters=lambda **k:{'read_errors':0,'monsters':[target]},player=lambda:(50,50),scene_actor_snapshot=lambda:[])
        with patch('warrior_combat.patrol_move') as move:
            result=profile.approach(s,Mock())
        self.assertTrue(result['nearby_combat']);self.assertFalse(result['movement'])
        self.assertEqual(result['target']['name'],'黑色恶蛆');move.assert_not_called()
