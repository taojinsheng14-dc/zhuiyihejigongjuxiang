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
