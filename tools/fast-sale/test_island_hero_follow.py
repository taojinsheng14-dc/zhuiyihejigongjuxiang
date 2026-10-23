import unittest
from types import SimpleNamespace
from island_automation import hero_follow_goal,hero_blocks_pickup,clickable_move,checked_movement

class HeroFollowTests(unittest.TestCase):
    def test_recorded_first_floor_detour_is_replanned_without_more_input(self):
        result=checked_movement(self.tile(),(17,22),(17,20),(18,19))
        self.assertEqual(result['status'],'moved');self.assertTrue(result['replanned_after_actual_movement'])
        self.assertEqual(result['to'],(18,19))
    def test_large_jump_or_nonwalkable_endpoint_still_stops(self):
        with self.assertRaises(RuntimeError):checked_movement(self.tile(),(17,22),(17,20),(18,16))
        with self.assertRaises(RuntimeError):checked_movement(self.tile(lambda p:p!=(18,19)),(17,22),(17,20),(18,19))
    def test_short_endpoint_with_long_disconnected_detour_stops(self):
        tile=SimpleNamespace(free=lambda p:True,path=lambda *args:[(17,22)]*9)
        with self.assertRaises(RuntimeError):checked_movement(tile,(17,22),(17,20),(18,19))
    def test_occluded_shortest_step_selects_a_different_clickable_move(self):
        box=(660,289,716,385)
        selected=clickable_move((25,16),[(27,17)],self.tile(),{(26,18)},(640,241),(1280,800),[box])
        self.assertIsNotNone(selected)
        destination,button,point=selected
        self.assertNotEqual(destination,(26,17))
        self.assertFalse(box[0]<=point[0]<=box[2] and box[1]<=point[1]<=box[3])
    def test_no_clickable_detour_never_clicks_through_models(self):
        self.assertIsNone(clickable_move((25,16),[(27,17)],self.tile(),set(),(640,241),(1280,800),[(0,0,1280,800)]))
    def test_blocked_unblock_goal_is_excluded_from_replanning(self):
        s={'position':(19,13),'hero':(20,15),'monsters':[],'npcs':[]};drop={'x':20,'y':15}
        first=hero_follow_goal(s,self.tile(),drop=drop)
        second=hero_follow_goal(s,self.tile(),drop=drop,excluded=[first])
        self.assertNotEqual(first,second)
    def test_hero_below_drop_covers_click_without_occupying_drop(self):
        self.assertTrue(hero_blocks_pickup({'hero':(21,15)},{'x':21,'y':14}))
        self.assertTrue(hero_blocks_pickup({'hero':(21,16)},{'x':21,'y':14}))
    def test_drop_unblock_goal_remains_six_tiles_away_even_after_hero_moves(self):
        s={'position':(19,13),'hero':(20,15),'monsters':[],'npcs':[]};drop={'x':20,'y':15}
        goal=hero_follow_goal(s,self.tile(),drop=drop)
        self.assertIsNotNone(goal)
        self.assertEqual(max(abs(goal[i]-(drop['x'],drop['y'])[i]) for i in (0,1)),6)
        self.assertNotEqual(goal,s['position'])
    def test_sideways_hero_does_not_cover_drop_click(self):
        self.assertFalse(hero_blocks_pickup({'hero':(22,15)},{'x':21,'y':14}))
        self.assertFalse(hero_blocks_pickup({'hero':None},{'x':21,'y':14}))
    def sample(self):return {'position':(20,19),'hero':(20,20),'monsters':[],'npcs':[]}
    def tile(self,free=lambda p:True):
        def path(a,b,blocked):return [a]*max(abs(a[0]-b[0]),abs(a[1]-b[1]))+[b]
        return SimpleNamespace(free=free,path=path)
    def test_goal_is_far_enough_for_follow_instead_of_one_tile_shuffle(self):
        s=self.sample();goal=hero_follow_goal(s,self.tile())
        self.assertGreaterEqual(max(abs(goal[i]-s['hero'][i]) for i in (0,1)),4)
        self.assertLessEqual(max(abs(goal[i]-s['hero'][i]) for i in (0,1)),6)
    def test_already_away_waits_in_place(self):
        s=self.sample();s['position']=(20,15)
        self.assertEqual(hero_follow_goal(s,self.tile()),(20,15))
    def test_no_free_ground_does_not_force_movement(self):
        self.assertIsNone(hero_follow_goal(self.sample(),self.tile(lambda p:False)))
    def test_never_chooses_known_npc_tile(self):
        s=self.sample();first=hero_follow_goal(s,self.tile());s['npcs']=[{'map':first}]
        self.assertNotEqual(hero_follow_goal(s,self.tile()),first)

if __name__=='__main__':unittest.main()
