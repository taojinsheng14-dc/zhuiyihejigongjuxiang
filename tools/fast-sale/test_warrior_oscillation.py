import unittest
from unittest.mock import Mock,patch
from island_melee import Melee
import test_island_melee as melee_fixture
import test_current_map_hunt as map_fixture
from current_map_hunt import WarriorMap
from warrior_combat import melee_approach_path
from types import SimpleNamespace

class OscillationTests(unittest.TestCase):
    def test_native_chase_returning_to_same_pair_does_not_extend_budget(self):
        s,t,_=melee_fixture.IslandMeleeTests().session();t['position']=[20,23]
        pos=[(20,20)];s.player=lambda:pos[0]
        c=Melee(scene_guard=Mock(),progress_timeout=2,strict_chase=True)
        sample={'monsters':[t],'drops':[]}
        with patch('island_melee.time.monotonic',return_value=100):c.step(s,sample)
        pos[0]=(20,21)
        with patch('island_melee.time.monotonic',return_value=101):r=c.step(s,sample)
        self.assertTrue(r['chase_progress']);self.assertFalse(r['health_progress'])
        pos[0]=(20,20)
        with patch('island_melee.time.monotonic',return_value=102):r=c.step(s,sample)
        self.assertFalse(r['chase_progress']);self.assertEqual(r['target']['address'],t['address'])
        pos[0]=(20,21)
        with patch('island_melee.time.monotonic',return_value=103.2):r=c.step(s,sample)
        self.assertFalse(r['engaged']);self.assertIsNone(c.locked)
        s.background_mouse.assert_called_once()

    def test_candidate_distance_swap_keeps_target_until_invalid(self):
        p=WarriorMap(avoid_players=False)
        a={'address':1,'name':'A','class':'TCatMon','distance':5}
        b={'address':2,'name':'B','class':'TCatMon','distance':1}
        p._approach_target=a
        self.assertEqual(p.select_melee_targets([b,a],0),[a])
        self.assertEqual(p.select_melee_targets([b],0),[b])

    def test_recent_previous_tile_cannot_be_selected_by_second_path(self):
        p,s,t=map_fixture.WarriorApproachTests().case();pos=[(167,140)];s.player=lambda:pos[0]
        goals=[]
        def move(session,tilemap,goal,**options):
            old=pos[0];pos[0]=goal;goals.append(goal)
            return {'from':old,'to':goal,'planned_step':goal}
        with patch('warrior_combat.patrol_move',side_effect=move),patch('time.monotonic',return_value=100):
            p.approach(s,Mock());r=p.approach(s,Mock())
        self.assertNotEqual(goals[-1],(167,140))
        self.assertIn((167,140),r['avoided_recent_positions'])

    def test_blocked_history_never_falls_back_to_reverse_and_times_out(self):
        p,s,t=map_fixture.WarriorApproachTests().case()
        with patch('warrior_combat.melee_approach_path',return_value=None),patch('warrior_combat.patrol_move') as move:
            with patch('time.monotonic',return_value=100):r=p.approach(s,Mock())
            self.assertTrue(r['nearby_combat']);self.assertFalse(r['movement'])
            with patch('time.monotonic',return_value=107):r=p.approach(s,Mock())
            self.assertEqual(r['reason'],'bounded_approach_no_progress')
            move.assert_not_called()

    def test_stone_blocks_diagonal_corner_and_path_routes_around(self):
        stone=(1,0);tilemap=SimpleNamespace(free=lambda p:0<=p[0]<=5 and 0<=p[1]<=5 and p!=stone)
        path=melee_approach_path(tilemap,(0,0),(3,1))
        self.assertIsNotNone(path);self.assertNotIn(stone,path)
        self.assertEqual(path[1],(0,1))
        for a,b in zip(path,path[1:]):
            dx,dy=b[0]-a[0],b[1]-a[1]
            if dx and dy:self.assertTrue(tilemap.free((a[0]+dx,a[1])) and tilemap.free((a[0],a[1]+dy)))

if __name__=='__main__':unittest.main()
