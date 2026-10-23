import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import ground_item_probe as probe

class Session:
    base=0
    def check(self):pass
    def uint(self,address):return 100
    def read(self,address,size):return b'x'*size
    def pause(self,seconds):pass

class PickupLoopTests(unittest.TestCase):
    def run_loop(self,side_effect):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'outputs').mkdir()
            with patch.object(probe,'__file__',str(root/'tools'/'fast-sale'/'ground_item_probe.py')), patch.object(probe,'pickup_current_test',side_effect=side_effect):
                return probe.pickup_loop(Session(),seconds=120)

    def test_blocked_item_does_not_stop_other_items(self):
        seen=[]
        def pickup(session,excluded):
            seen.append(set(excluded))
            if len(seen)==1:return {'status':'blocked','id':7,'verified':False}
            return {'status':'completed','id':len(seen)+10,'verified':True}
        result=self.run_loop(pickup)
        self.assertEqual(result['verified'],9)
        self.assertEqual(result['attempts'],10)
        self.assertEqual(seen[1],{7})

    def test_unverified_disappearance_stops(self):
        result=self.run_loop(lambda session,excluded:{'status':'unverified','verified':False})
        self.assertEqual(result['status'],'stopped_unverified')
        self.assertEqual(result['attempts'],1)

class MoveTests(unittest.TestCase):
    class Map:
        def free(self,point):return True
    def test_left_click_is_exactly_the_planned_tile(self):
        self.assertEqual(probe.pickup_aim((5,5),(6,5),(640,241),self.Map(),set(),(1280,800),button='left'),(688,305))
    def test_occluded_left_step_never_falls_back_to_a_farther_tile(self):
        with self.assertRaisesRegex(RuntimeError,'没有不被遮挡'):
            probe.pickup_aim((5,5),(6,5),(640,241),self.Map(),set(),(1280,800),
                             button='left',avoid_boxes=[(680,290,700,320)])
    def test_ground_aim_skips_npc_body_and_selects_clear_point(self):
        point=probe.pickup_aim((5,5),(6,5),(640,241),self.Map(),set(),(1280,800),avoid_boxes=[(770,280,800,330)])
        self.assertNotEqual(point,(784,305))
    def test_fully_occluded_ground_never_selects_actor_model(self):
        with self.assertRaisesRegex(RuntimeError,'没有不被遮挡'):
            probe.pickup_aim((5,5),(6,5),(640,241),self.Map(),set(),(1280,800),avoid_boxes=[(0,0,1280,800)])
    def test_runs_two_clear_tiles(self):
        self.assertEqual(probe.choose_pickup_move((2,2),[(2,2),(3,2),(4,2)],self.Map(),set()),((4,2),'right'))
    def test_runs_in_all_eight_directions(self):
        for dx,dy in ((-1,-1),(0,-1),(1,-1),(-1,0),(1,0),(-1,1),(0,1),(1,1)):
            with self.subTest(direction=(dx,dy)):
                current=(5,5);middle=(5+dx,5+dy);target=(5+2*dx,5+2*dy)
                self.assertEqual(probe.choose_pickup_move(current,[current,middle,target],self.Map(),set()),(target,'right'))

    def test_walks_last_tile(self):
        self.assertEqual(probe.choose_pickup_move((2,2),[(2,2),(3,2)],self.Map(),set()),((3,2),'left'))
    def test_does_not_run_past_corner(self):
        self.assertEqual(probe.choose_pickup_move((2,2),[(2,2),(3,2),(3,3)],self.Map(),set()),((3,2),'left'))
    def test_does_not_run_through_occupied_middle(self):
        self.assertEqual(probe.choose_pickup_move((2,2),[(2,2),(3,2),(4,2)],self.Map(),{(3,2)}),((3,2),'left'))

if __name__=='__main__':unittest.main()
