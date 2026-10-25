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

    def test_player_guard_queries_entire_loaded_scene(self):
        s=self.session();s.nearby_players=Mock(return_value=[{'position':[100,100]}])
        with patch.object(hunt,'header',return_value=hunt.STONE_HEADER),patch.object(hunt,'read_experience',return_value={'character':'厚礼蟹'}):
            with self.assertRaises(hunt.PlayersDetected):hunt.StoneTomb(avoid_players=True).guard(s)
        s.nearby_players.assert_called_once_with(None)

    def random_session(self):
        state={'position':(50,50)}
        s=self.session();s.player=lambda:state['position'];s.stable_player=s.player
        s.nearby_players=lambda radius:[{'position':[70,70]}]
        s.currency_snapshot=lambda:{'gold':100,'yuanbao':10}
        s.shortcut_inventory=lambda:[{'name':'随机传送石','key':1,'raw_98':100}]
        s.clear_background_mouse=Mock();s.write_stats=Mock()
        s.press_named_hotkey=Mock(side_effect=lambda *a:state.update(position=(80,80)))
        s.wait=lambda condition,timeout:self.assertTrue(condition())
        p=hunt.StoneTomb(avoid_players=True);p.check_state=Mock();p.tilemap=SimpleNamespace(free=lambda xy:True)
        return p,s

    def test_player_random_uses_one_named_stone_and_confirms_new_position(self):
        p,s=self.random_session();result=p.avoid_players(s,Mock())
        self.assertTrue(result['random_used']);self.assertEqual(result['after'],(80,80))
        s.press_named_hotkey.assert_called_once_with(('随机传送石',),'random')
        s.clear_background_mouse.assert_called_once()

    def test_uncertain_random_does_not_repeat(self):
        p,s=self.random_session();s.wait=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('timeout'))
        with self.assertRaisesRegex(RuntimeError,'不重复按键'):p.avoid_players(s,Mock())
        self.assertEqual(s.press_named_hotkey.call_count,1)

    def test_missing_random_stone_never_uses_other_item(self):
        p,s=self.random_session();s.shortcut_inventory=lambda:[]
        with self.assertRaisesRegex(RuntimeError,'缺少'):p.avoid_players(s,Mock())
        s.press_named_hotkey.assert_not_called()

    def test_occupied_goal_with_local_exit_is_not_dead_end(self):
        import struct
        from warrior_combat import local_exits
        from dungeon_route import CenterPathMap
        raw=bytearray(0x200);struct.pack_into('<2i',raw,0x68,52,50)
        p,s=self.random_session();s.scene_actor_snapshot=lambda:[(1,raw)]
        p.tilemap=SimpleNamespace(free=lambda xy:48<=xy[0]<=54 and 48<=xy[1]<=54)
        with self.assertRaisesRegex(RuntimeError,'没有可走路径'):
            CenterPathMap(p.tilemap,{}).path((50,50),(52,50),{(52,50)})
        self.assertTrue(local_exits(s,p.tilemap)['exits'])
        p.guard=Mock();self.assertFalse(p.confirm_dead_end(s));s.press_named_hotkey.assert_not_called()

    def test_hero_blocks_only_corridor_exit_and_diagonal_cannot_cut_corner(self):
        import struct
        from warrior_combat import local_exits
        raw=bytearray(0x200);struct.pack_into('<2i',raw,0x68,51,50)
        p,s=self.random_session();s.scene_actor_snapshot=lambda:[(1,raw)]
        p.tilemap=SimpleNamespace(free=lambda xy:xy in {(50,50),(51,50),(51,51)})
        self.assertEqual(local_exits(s,p.tilemap)['exits'],[])

    def test_confirmed_dead_end_random_once_and_reopened_exit_never_random(self):
        p,s=self.random_session();p.guard=Mock();s.pause=Mock()
        empty={'position':(50,50),'exits':[]};opened={'position':(50,50),'exits':[(51,50)]}
        with patch('warrior_combat.local_exits',side_effect=[empty,opened]):
            self.assertFalse(p.escape_dead_end(s,Mock())['random_used'])
        s.press_named_hotkey.assert_not_called()
        with patch('warrior_combat.local_exits',return_value=empty):
            result=p.escape_dead_end(s,Mock())
        self.assertTrue(result['random_used']);self.assertEqual(result['reason'],'dead_end')
        s.press_named_hotkey.assert_called_once()

    def test_dead_end_unknown_state_and_missing_stone_never_input(self):
        p,s=self.random_session();p.guard=Mock(side_effect=RuntimeError('map changed'))
        with self.assertRaisesRegex(RuntimeError,'map changed'):p.escape_dead_end(s,Mock())
        s.press_named_hotkey.assert_not_called()
        p.guard=Mock();s.pause=Mock();s.shortcut_inventory=lambda:[]
        with patch('warrior_combat.local_exits',return_value={'position':(50,50),'exits':[]}):
            with self.assertRaisesRegex(RuntimeError,'缺少'):p.escape_dead_end(s,Mock())
        s.press_named_hotkey.assert_not_called()



class GenericProfileTests(unittest.TestCase):
    def test_supported_formats_resolve_same_shared_profile(self):
        import struct,tempfile
        from pathlib import Path
        for stride in (12,14):
            with self.subTest(stride=stride),tempfile.TemporaryDirectory() as folder:
                file=Path(folder)/'new-normal.map';file.write_bytes(bytes(52+4*4*stride))
                head=struct.pack('<HH',4,4)+bytes(48)
                with patch.object(hunt,'header',return_value=head),patch('map_navigation.matching_map_file',return_value=file):
                    profile=hunt.profile_for(SimpleNamespace())
                self.assertEqual(profile.map_stride,stride);self.assertEqual(profile.header,head)
                self.assertTrue(profile.center_route);self.assertEqual(profile.post_cast_wait,.05)

    def test_unknown_format_and_town_are_rejected_before_input(self):
        import struct,tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            for name,stride in (('unknown.map',13),('3.map',14)):
                file=Path(folder)/name;file.write_bytes(bytes(52+4*4*stride))
                with patch.object(hunt,'header',return_value=struct.pack('<HH',4,4)+bytes(48)),patch('map_navigation.matching_map_file',return_value=file):
                    with self.assertRaises(RuntimeError):hunt.profile_for(SimpleNamespace())

    def test_new_map_monster_name_supported_but_owned_pet_and_npc_excluded(self):
        profile=hunt.NormalMap()
        monster={'name':'新地图普通怪','class':'TCatMon','distance':3,'dead':False}
        self.assertTrue(profile.is_target(monster))
        self.assertFalse(profile.is_target(dict(monster,name='神兽(其他玩家)')))
        self.assertFalse(profile.is_target(dict(monster,**{'class':'TMerchant'})))
        self.assertFalse(profile.is_target(dict(monster,dead=True)))
