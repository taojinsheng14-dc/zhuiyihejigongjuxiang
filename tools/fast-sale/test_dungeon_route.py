import unittest
from dungeon_route import CoverageRoute


class RouteTests(unittest.TestCase):
    def tilemap(self):
        class Map:
            def free(self,p):
                x,y=p
                return (0<=x<=80 and 0<=y<=4) or (x==80 and 4<y<=40) or (100<=x<=104 and 0<=y<=4)
        return Map()

    def test_entire_connected_map_beyond_old_45_tile_window(self):
        route=CoverageRoute(self.tilemap(),(0,2))
        self.assertTrue(any(p[0]>=72 for p in route.points))
        self.assertTrue(any(p[1]>=32 for p in route.points))
        self.assertFalse(any(p[0]>=100 for p in route.points))
        seen=set()
        for i in range(len(route.points)):
            goal=route.next_goal((0,2) if not seen else goal,i)
            self.assertIsNotNone(goal);seen.add(goal)
        self.assertGreater(len(seen),len(route.points)//2)

    def test_stalled_goal_deferred_without_marking_visited(self):
        route=CoverageRoute(self.tilemap(),(0,2));goal=route.next_goal((0,2),0)
        route.defer_goal(0)
        self.assertNotEqual(route.next_goal((0,2),1),goal)
        self.assertNotIn(goal,route.visited)
