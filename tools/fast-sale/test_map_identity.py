import tempfile,unittest
from pathlib import Path
from map_navigation import matching_map_file,load_matching_map
from background_sale import BackgroundSession

class MapIdentityTests(unittest.TestCase):
    def test_known_header_can_identify_unsupported_tile_encoding_without_pathfinding(self):
        header=bytes(range(52))
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'room.map').write_bytes(header+b'unknown-encoding')
            self.assertEqual(matching_map_file(header,directory).name,'room.map')
            with self.assertRaisesRegex(RuntimeError,'12字节'):load_matching_map(header,directory)
    def test_duplicate_headers_still_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ['a.map','b.map']:Path(directory,name).write_bytes(bytes(60))
            with self.assertRaises(RuntimeError):matching_map_file(bytes(52),directory)
    def test_room_near_town_coordinates_is_not_mistaken_for_town(self):
        s=object.__new__(BackgroundSession);s.base=0;s.player=lambda:(320,320);s.uint=lambda addr:100;s.read=lambda *args:bytes(52)
        s.current_map_name=lambda header:'room.map'
        self.assertFalse(s.in_mengzhong_return_area())
        s.current_map_name=lambda header:'3.map'
        self.assertTrue(s.in_mengzhong_return_area())
if __name__=='__main__':unittest.main()
