import struct
import unittest
from unittest.mock import Mock

from background_sale import BackgroundSession


class SceneNpcTests(unittest.TestCase):
    def session(self,characters=False,dead=0):
        s=object.__new__(BackgroundSession);s.base=0x400000;s.player=lambda:(140,330)
        raw=bytearray(0x184)
        struct.pack_into('<I',raw,0,s.base+(0x24991c if characters else 0x249874))
        struct.pack_into('<I',raw,0xc,0x8000)
        struct.pack_into('<2i',raw,0x68,147,328)
        struct.pack_into('<2i',raw,0x17c,1176,305);raw[0xac]=dead
        s.scene_actor_snapshot=Mock(return_value=[(0x10000,bytes(raw))])
        s.uint=lambda address:len(b'NPC') if address==0x7ffc else 0
        s.read=lambda address,size:b'NPC' if address==0x8000 else b''
        s.heap_npcs=Mock(side_effect=AssertionError('heap scan must not run'))
        return s

    def test_live_npc_list_preserves_identity_position_and_draw(self):
        s=self.session();rows=s.npcs()
        self.assertEqual(rows,[{'address':0x10000,'name':'NPC','map':(147,328),'draw':(1176,305)}])
        s.scene_actor_snapshot.assert_called_once_with(0x3c)
        s.heap_npcs.assert_not_called()

    def test_players_use_separate_list_and_exclude_dead(self):
        s=self.session(characters=True);self.assertEqual(len(s.npcs(True)),1)
        s.scene_actor_snapshot.assert_called_once_with(0x98)
        self.assertEqual(self.session(characters=True,dead=1).npcs(True),[])
        with self.assertRaisesRegex(RuntimeError,'死亡状态不符'):
            self.session(characters=True,dead=2).npcs(True)

    def test_empty_list_does_not_fall_back_to_stale_heap_objects(self):
        s=self.session();s.scene_actor_snapshot.return_value=[]
        self.assertEqual(s.npcs(),[]);s.heap_npcs.assert_not_called()

    def test_wrong_actor_type_and_invalid_name_are_not_click_candidates(self):
        self.assertEqual(self.session(characters=True).npcs(),[])
        s=self.session();s.uint=lambda address:0
        with self.assertRaisesRegex(RuntimeError,'名称结构不符'):s.npcs()

    def snapshot_session(self,unstable=False):
        s=object.__new__(BackgroundSession);s.base=0x400000;s.check=Mock();s.pause=Mock()
        integers={s.base+0x2ba8fc:0x9000,0x9000:0x10000,0x10000:s.base+0x1000,
                  s.base+0x1000-44:0x8000,0x10000+0x3c:0x11000,
                  0x11000:s.base+0x2000,s.base+0x2000-44:0x8100,
                  s.base+0x2ba608:0x9008,0x9008:0x14000}
        s.uint=lambda address:integers[address]
        first=struct.pack('<4I',s.base+0x2000,0x15000,0,0)
        changed=struct.pack('<4I',s.base+0x2000,0x15000,1,1)
        headers=iter(([first,changed]*3) if unstable else [first,changed,first,first])
        def read(address,size):
            if address==0x11000:return next(headers)
            return {(0x8000,1):b'\x0a',(0x8001,10):b'TPlayScene',
                    (0x8100,1):b'\x05',(0x8101,5):b'TList',
                    (0x14004,52):b'M'*52}[(address,size)]
        s.read=read
        return s

    def test_scene_changes_are_retried_before_returning_members(self):
        s=self.snapshot_session();self.assertEqual(s.scene_actor_snapshot(0x3c),[])
        s.pause.assert_called_once_with(.05)

    def test_continuous_scene_changes_stop_with_bounded_retries(self):
        s=self.snapshot_session(unstable=True)
        with self.assertRaisesRegex(RuntimeError,'持续变化'):s.scene_actor_snapshot(0x3c)
        self.assertEqual(s.pause.call_count,2)

    def test_player_count_excludes_self_both_heroes_dead_and_far_players(self):
        s=object.__new__(BackgroundSession);s.base=0x400000;s.player=lambda:(140,330)
        rows=[]
        for address,x,y,dead in [(0x10000,140,330,0),(0x11000,141,330,0),
                                 (0x12000,142,330,0),(0x13000,143,330,0),
                                 (0x14000,144,330,1),(0x15000,170,330,0)]:
            raw=bytearray(0x184);struct.pack_into('<I',raw,0,s.base+0x24991c)
            struct.pack_into('<2i',raw,0x68,x,y);raw[0xac]=dead;rows.append((address,bytes(raw)))
        mapping={s.base+0x2bac2c:0x9000,0x9000:0x10000,
                 **{address+0x358:0 for address,_ in rows}}
        mapping[0x10000+0x358]=0x11000;mapping[0x12000+0x358]=0x13000
        s.uint=lambda address:mapping[address];s.scene_actor_snapshot=lambda:rows
        self.assertEqual(s.nearby_players(8),[{'address':0x12000,'position':[142,330]}])


if __name__=='__main__':unittest.main()
