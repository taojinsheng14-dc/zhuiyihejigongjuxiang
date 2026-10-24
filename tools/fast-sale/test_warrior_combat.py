import unittest
from types import SimpleNamespace

from warrior_combat import DungeonMap,eligible,continuous_run,HEADER


class WarriorCombatTests(unittest.TestCase):
    def test_only_known_visible_live_monsters(self):
        monster={'name':'蜈蚣','class':'TCatMon','dead':False,'on_screen':True,'distance':4}
        self.assertTrue(eligible(monster))
        for change in ({'dead':True},{'on_screen':False},{'distance':9},{'name':'微笑'},{'class':'THumActor'}):
            self.assertFalse(eligible(dict(monster,**change)))

    def test_does_not_cut_diagonally_through_walls(self):
        flags=[[0]*30 for _ in range(30)];flags[11][10]=flags[10][11]=1
        tilemap=DungeonMap(30,30,flags)
        self.assertNotEqual(tilemap.path((10,10),(12,12))[1],(11,11))

    def test_excludes_map_edges_and_occupied_tiles(self):
        tilemap=DungeonMap(30,30,[[0]*30 for _ in range(30)])
        self.assertFalse(tilemap.free((7,15)))
        self.assertFalse(tilemap.free((22,15)))
        self.assertNotIn((11,10),tilemap.path((10,10),(12,10),blocked={(11,10)}))

    def test_unreachable_goal_stops(self):
        flags=[[1]*30 for _ in range(30)];flags[10][10]=flags[15][15]=0
        with self.assertRaises(RuntimeError):DungeonMap(30,30,flags).path((10,10),(15,15))

    def test_short_route_step_does_not_hold_until_monster_interrupt(self):
        import struct
        from unittest.mock import Mock,patch
        from warrior_combat import patrol_move
        raw=bytearray(0x184);struct.pack_into('<2i',raw,0x68,10,10);struct.pack_into('<2i',raw,0x17c,640,300)
        positions=[(10,10),(12,10),(12,10),(12,10)]
        session=SimpleNamespace(scene_actor_snapshot=lambda:[(1,bytes(raw))],
            player=lambda:positions.pop(0) if len(positions)>1 else positions[0],
            uint=lambda a:1,base=0,read=lambda a,n:struct.pack('<2i',640,300),
            client_size=lambda:(1280,800),background_mouse=Mock(),pause=lambda n:None)
        tilemap=DungeonMap(40,40,[[0]*40 for _ in range(40)])
        with patch('warrior_combat.continuous_run') as hold:
            result=patrol_move(session,tilemap,(20,10),allow_hold=False)
        hold.assert_not_called();session.background_mouse.assert_called_once()
        self.assertEqual(result['to'],(12,10))

    def hold_session(self):
        messages=[]
        def send(hwnd,message,*args):messages.append(message);return 1
        session=SimpleNamespace(client_size=lambda:(1280,800),physical_client_size=lambda:(1920,1200),
            u=SimpleNamespace(SendMessageTimeoutW=send,IsIconic=lambda hwnd:False,GetAsyncKeyState=lambda key:0),
            hwnd=1,begin_background_input=lambda:None,wait_mouse_modifiers_released=lambda:None,
            check=lambda:None,uint=lambda address:1,base=0,read=lambda address,size:HEADER,
            player=lambda:(10,10),pause=lambda seconds:None,clear_background_mouse=lambda:messages.append('clear'),
            nearby_monsters=lambda:{'read_errors':0,'monsters':[{'dead':False,'on_screen':True,'distance':4}]})
        return session,messages

    def test_hold_releases_as_soon_as_monster_appears(self):
        session,messages=self.hold_session();tilemap=DungeonMap(30,30,[[0]*30 for _ in range(30)])
        result=continuous_run(session,tilemap,(10,10),(1,0),(780,300),8)
        self.assertEqual(result['release_reason'],'monster_detected')
        self.assertIn(0x204,messages);self.assertIn(0x205,messages)
        self.assertEqual(messages[-1],'clear')

    def test_hold_releases_even_when_sampling_fails(self):
        session,messages=self.hold_session();tilemap=DungeonMap(30,30,[[0]*30 for _ in range(30)])
        def fail():raise RuntimeError('sample failed')
        session.check=fail
        with self.assertRaises(RuntimeError):continuous_run(session,tilemap,(10,10),(1,0),(780,300),8)
        self.assertIn(0x205,messages);self.assertEqual(messages[-1],'clear')


if __name__=='__main__':unittest.main()
