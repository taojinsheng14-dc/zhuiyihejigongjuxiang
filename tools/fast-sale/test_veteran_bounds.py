import struct,unittest
from types import SimpleNamespace
from unittest.mock import Mock
from map_navigation import veteran_run_path,veteran_run_batch,validate_veteran_landing
from background_sale import BackgroundSession

class VeteranBoundsTests(unittest.TestCase):
    def test_route_never_crosses_either_axis_from_all_four_sides(self):
        tile=SimpleNamespace(free=lambda xy:True)
        for start in ((80,80),(120,80),(80,120),(120,120),(100,120)):
            path=veteran_run_path(tile,start,[(100,98),(100,102),(98,100),(102,100),(98,98),(102,102),(98,102),(102,98)],target=(100,100))
            for a,b in zip(path,path[1:]):
                for i in (0,1):
                    self.assertLessEqual(abs(b[i]-100),abs(a[i]-100))
                    self.assertTrue(min(start[i],100)<=b[i]<=max(start[i],100))
    def test_obstruction_never_causes_detour_beyond_npc(self):
        tile=SimpleNamespace(free=lambda xy:xy==(80,80) or xy[0]>100)
        with self.assertRaisesRegex(RuntimeError,'不越界'):veteran_run_path(tile,(80,80),[(100,98)],target=(100,100))
    def test_batch_is_two_collinear_runs_only_when_far(self):
        self.assertEqual(veteran_run_batch([(340,340),(338,338),(336,336),(334,334)]),[(338,338),(336,336)])
        self.assertEqual(len(veteran_run_batch([(326,326),(324,324),(322,322)])),1)
        self.assertEqual(len(veteran_run_batch([(340,340),(338,338),(336,338)])),1)
    def test_run_can_pass_player_but_never_land_on_player(self):
        tile=SimpleNamespace(free=lambda xy:True)
        # At the town crowd boundary the only safe direction crosses a player.
        blocked=[(327,336),(325,335),(325,337)]
        path=veteran_run_path(tile,(327,337),[(327,333)],blocked,passable_middle=[(327,336)])
        self.assertEqual(path,[(327,337),(327,335),(327,333)])
        self.assertTrue(all(p not in blocked for p in path[1:]))
    def test_npc_middle_and_wall_cannot_be_passed(self):
        tile=SimpleNamespace(free=lambda xy:xy[0]==327)
        with self.assertRaises(RuntimeError):veteran_run_path(tile,(327,337),[(327,333)],[(327,336)])
        tile=SimpleNamespace(free=lambda xy:xy[0]==327 and xy!=(327,336))
        with self.assertRaises(RuntimeError):veteran_run_path(tile,(327,337),[(327,333)],[(327,336)],passable_middle=[(327,336)])
    def session(self,ready):
        s=object.__new__(BackgroundSession);s.base=0;s.check=Mock();s.npcs=lambda characters=False:[];s.login_stage=lambda:'playing'
        s.uint=lambda addr:0;s.read=lambda addr,size:struct.pack('<2i',640,300) if size==8 else b'map'
        s.client_size=lambda:(1280,800);s.pause=Mock();s.stable_player=Mock(return_value=(336,336));s.background_mouse=Mock()
        return s,SimpleNamespace(free=lambda xy:True),ready
    def test_safe_zone_run_does_not_treat_player_landing_as_obstacle(self):
        s,tile,ready=self.session(lambda:False)
        # All first landings are occupied by players, which are passable in town.
        occupied=[(338,338),(338,340),(340,338)]
        _,count=s._veteran_run_batch(tile,(340,340),[(324,324)],occupied,b'map',ready)
        self.assertEqual(count,2)
    def test_safe_zone_run_still_blocks_npc_landing(self):
        s,tile,ready=self.session(lambda:False)
        tile.free=lambda xy:xy[0]==340
        s.npcs=lambda characters=False:[{'map':(340,338)}] if not characters else []
        with self.assertRaises(RuntimeError):s._veteran_run_batch(tile,(340,340),[(340,334)],[],b'map',ready)
        s.background_mouse.assert_not_called()
    def test_two_runs_then_one_coordinate_validation(self):
        s,tile,ready=self.session(lambda:False)
        after,count=s._veteran_run_batch(tile,(340,340),[(324,324)],[],b'map',ready)
        self.assertEqual(count,2);self.assertEqual(s.background_mouse.call_count,2);s.stable_player.assert_called_once()
        self.assertFalse(s.background_mouse.call_args.kwargs['track_movement'])
    def test_visible_after_first_run_skips_second(self):
        ready=Mock(side_effect=[False,True]);s,tile,_=self.session(ready);s.stable_player.return_value=(338,338)
        _,count=s._veteran_run_batch(tile,(340,340),[(324,324)],[],b'map',ready)
        self.assertEqual(count,1);s.background_mouse.assert_called_once()
    def test_already_clickable_sends_no_run_and_does_not_wait_for_coordinate(self):
        s=object.__new__(BackgroundSession);s.verified_npc_draw=lambda npc:(400,81);s.veteran_click_point=lambda draw:(400,105)
        s.player=lambda:(330,332);s.stable_player=Mock();s.background_mouse=Mock()
        self.assertEqual(s.approach_veteran_running({'name':'盟重老兵','map':(320,320)})['runs'],0)
        s.background_mouse.assert_not_called();s.stable_player.assert_not_called()
    def test_unexpected_axis_crossing_stops(self):
        s,tile,ready=self.session(lambda:False);s.stable_player.return_value=(319,336)
        with self.assertRaisesRegex(RuntimeError,'越过目标坐标轴'):s._veteran_run_batch(tile,(340,340),[(324,324)],[],b'map',ready)

    def test_one_tile_lateral_drift_is_accepted_for_replanning(self):
        s,tile,ready=self.session(lambda:False);s.stable_player.return_value=(328,336)
        after,count=s._veteran_run_batch(tile,(327,338),[(327,328)],[],b'map',ready)
        self.assertEqual(after,(328,336));self.assertEqual(count,2)
        path=veteran_run_path(tile,after,[(324,324)])
        self.assertEqual(path[0],after)

    def test_backward_one_tile_still_same_side_can_replan(self):
        tile=SimpleNamespace(free=lambda xy:True)
        result=validate_veteran_landing(tile,(327,338),(328,339),1)
        self.assertTrue(result['replan'])

    def test_drift_tolerance_does_not_accumulate_across_batches(self):
        tile=SimpleNamespace(free=lambda xy:True)
        with self.assertRaisesRegex(RuntimeError,'本次靠近容差'):
            validate_veteran_landing(tile,(329,336),(330,334),1,origin=(327,338))

    def test_same_side_large_jump_and_wall_still_stop(self):
        tile=SimpleNamespace(free=lambda xy:True)
        with self.assertRaisesRegex(RuntimeError,'位移异常'):validate_veteran_landing(tile,(340,340),(329,336),1)
        with self.assertRaisesRegex(RuntimeError,'可走格'):validate_veteran_landing(SimpleNamespace(free=lambda xy:False),(327,338),(328,336),1)

    def test_post_move_map_change_stops_before_accepting_landing(self):
        s,tile,ready=self.session(lambda:False)
        original=s.read;reads=[0]
        def read(addr,size):
            if size==52:
                reads[0]+=1
                if reads[0]>2:return b'other_map'
            return original(addr,size)
        s.read=read
        with self.assertRaisesRegex(RuntimeError,'后地图变化'):
            s._veteran_run_batch(tile,(340,340),[(324,324)],[],b'map',ready)

    def test_north_run_aims_above_own_sprite_without_crossing_npc(self):
        s,tile,ready=self.session(lambda:False);s.stable_player.return_value=(327,334)
        s._veteran_run_batch(tile,(327,338),[(327,328)],[],b'map',ready)
        self.assertEqual(s.background_mouse.call_args_list[0].args[0],(640,268))
        self.assertNotEqual(s.background_mouse.call_args_list[0].args[0],(640,300))

if __name__=='__main__':unittest.main()
