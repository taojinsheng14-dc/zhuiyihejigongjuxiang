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


class CenterRouteTests(unittest.TestCase):
    def rectangle(self,width,height):
        class Map:
            def free(self,p):return 0<=p[0]<width and 0<=p[1]<height
        return Map()

    def test_narrow_corridor_waypoints_and_travel_use_middle(self):
        route=CoverageRoute(self.rectangle(100,9),(1,0),spacing=24)
        self.assertTrue(all(y==4 for x,y in route.points if 8<x<92))
        path=route.navigation_map().path((1,0),(98,0))
        middle=[y for x,y in path if 20<x<80]
        self.assertTrue(middle);self.assertTrue(all(y==4 for y in middle))

    def test_single_cell_bottleneck_remains_passable(self):
        class Map:
            def free(self,p):
                x,y=p
                return (0<=x<10 and 0<=y<9) or (10<=x<20 and y==4) or (20<=x<30 and 0<=y<9)
        route=CoverageRoute(Map(),(4,4),spacing=24)
        path=route.navigation_map().path((4,4),(25,4))
        self.assertIn((15,4),path)
        self.assertTrue(all(Map().free(p) for p in path))

    def test_dynamic_blockers_and_diagonal_corners_respected(self):
        route=CoverageRoute(self.rectangle(20,9),(1,4),spacing=24)
        path=route.navigation_map().path((1,4),(18,4),blocked={(9,4),(10,4)})
        self.assertNotIn((9,4),path);self.assertNotIn((10,4),path)
        for a,b in zip(path,path[1:]):
            if a[0]!=b[0] and a[1]!=b[1]:
                self.assertNotIn((a[0],b[1]),{(9,4),(10,4)})
                self.assertNotIn((b[0],a[1]),{(9,4),(10,4)})

    def test_wide_room_has_interior_coverage_lanes(self):
        route=CoverageRoute(self.rectangle(72,72),(35,35),spacing=24)
        self.assertGreater(len(route.points),9)
        self.assertTrue(all(route.clearance[p]>=8 for p in route.points))
