import struct
import tempfile
import unittest
from pathlib import Path
from map_navigation import TileMap,load_matching_map

def fixture():
    data=bytearray(52+5*5*12)
    struct.pack_into('<HH',data,0,5,5)
    # The direct downward route is obstructed; a valid path goes around it.
    struct.pack_into('<H',data,52+(2*5+2)*12,0x8000)
    return data

class MapNavigationTests(unittest.TestCase):
    def test_running_route_uses_only_two_tile_moves(self):
        tilemap=TileMap(fixture());path=tilemap.run_path((0,0),[(4,4)])
        self.assertEqual(path[-1],(4,4))
        self.assertTrue(all(max(abs(b[0]-a[0]),abs(b[1]-a[1]))==2 for a,b in zip(path,path[1:])))
    def test_running_can_pass_an_occupied_middle_but_not_land_on_player(self):
        tilemap=TileMap(fixture());path=tilemap.run_path((0,0),[(0,4)],[(0,1),(0,2)])
        self.assertNotIn((0,2),path)
        self.assertEqual(path[-1],(0,4))
    def test_running_never_fills_last_odd_tile_with_left_click(self):
        with self.assertRaises(RuntimeError):TileMap(fixture()).run_path((0,0),[(0,1)])
    def test_route_avoids_blocked_cell(self):
        tilemap=TileMap(fixture())
        path=tilemap.path((2,1),(2,3))
        self.assertEqual(path[0],(2,1))
        self.assertEqual(path[-1],(2,3))
        self.assertNotIn((2,2),path)
        self.assertTrue(all(tilemap.free(xy) for xy in path))

    def test_occupied_goal_and_invalid_format_stop(self):
        with self.assertRaises(RuntimeError):TileMap(fixture()[:-1])
        with self.assertRaises(RuntimeError):TileMap(fixture()).path((2,1),(2,3),[(2,3)])

    def test_ambiguous_header_never_selects_arbitrary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ('a.map','b.map'):Path(directory,name).write_bytes(fixture())
            with self.assertRaises(RuntimeError):load_matching_map(bytes(fixture()[:52]),directory)

if __name__=='__main__':unittest.main()
