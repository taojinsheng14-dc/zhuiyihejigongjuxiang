import struct
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from background_sale import BackgroundSession


class MissingVeteranTests(unittest.TestCase):
    def test_visible_body_at_top_edge_does_not_require_extra_movement(self):
        s=object.__new__(BackgroundSession)
        s.client_size=lambda:(1680,1050);s.hero_covers=lambda box:False
        self.assertEqual(s.veteran_click_point((408,81)),(408,105))
        self.assertEqual(s.veteran_click_point((408,145)),(408,169))

    def session(self,name='3.map',moves=True):
        s=object.__new__(BackgroundSession);s.base=0
        state={'position':(334,338),'loaded':False}
        npc={'name':'盟重老兵','map':(320,320),'address':123}
        s.check=Mock();s.pause=Mock();s.login_stage=lambda:'playing';s.close_panels=Mock()
        s.npcs=lambda characters=False:[] if characters or not state['loaded'] else [npc]
        s.unique_npc=Mock(return_value=npc)
        s.uint=lambda address:0
        s.read=lambda address,size:struct.pack('<2i',840,369) if size==8 else b'map'
        s.player=s.stable_player=lambda:state['position']
        tilemap=SimpleNamespace(name=name,free=lambda xy:True,
                                run_path=lambda current,goals,blocked:[current,(332,336)])
        s.navigation_map=lambda header:tilemap;s.client_size=lambda:(1680,1050)
        def run(point,button,**kwargs):
            if moves:state.update(position=(332,336),loaded=True)
        s.background_mouse=Mock(side_effect=run)
        return s

    def test_npc_outside_loaded_scene_is_approached_before_object_lookup(self):
        s=self.session();found=s.locate_mengzhong_veteran()
        self.assertEqual(found['name'],'盟重老兵')
        s.background_mouse.assert_called_once()
        self.assertEqual(s.background_mouse.call_args.args[1],'right')
        s.unique_npc.assert_called_once()

    def test_same_coordinates_on_wrong_map_never_trigger_movement(self):
        s=self.session('5.map')
        with self.assertRaisesRegex(RuntimeError,'未确认盟重'):s.locate_mengzhong_veteran()
        s.background_mouse.assert_not_called();s.unique_npc.assert_not_called()

    def test_continuous_obstruction_stops_after_three_run_attempts(self):
        s=self.session(moves=False)
        s.recover_stalled_route=Mock(side_effect=RuntimeError('连续三次未移动且恢复额度不足'))
        with self.assertRaisesRegex(RuntimeError,'连续三次'):s.locate_mengzhong_veteran()
        self.assertEqual(s.background_mouse.call_count,6)
        s.recover_stalled_route.assert_called_once()

    def test_exit_walks_exactly_the_next_tile_with_no_run_or_blind_ground_click(self):
        s=object.__new__(BackgroundSession);s.base=0;state={'header':b'shop'}
        s.close_panels=Mock();s.unique_npc=Mock();s.weapon_exit_players=lambda:[]
        s.uint=lambda address:0;s.read=lambda address,size:state['header']
        def walk(target,**kwargs):
            if target==(4,16):state['header']=b'town'
        s.walk_tile=Mock(side_effect=walk)
        s.stable_player=s.player=lambda:(329,315)
        s.locate_mengzhong_veteran=Mock();s.background_mouse=Mock()
        result=s._leave_weapon_shop_by_door()
        self.assertFalse(result['return_stone_used'])
        self.assertEqual(s.walk_tile.call_args_list[1].args,((4,16),))
        self.assertFalse(s.walk_tile.call_args_list[1].kwargs['run_enabled'])
        self.assertTrue(s.walk_tile.call_args_list[1].kwargs['allow_transition'])
        s.background_mouse.assert_not_called()
