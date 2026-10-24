import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import island_challenge as island

class FakeSession:
    def inventory(self):return ['']*40
    def player(self):return (18,18)
    def check(self):pass
    def login_stage(self):return 'playing'
    def npcs(self):return [{'name':'孤岛挑战','map':p} for p in ((19,11),(26,18),(19,25),(13,18))]
    def visible(self,key):return False
    def nearby_monsters(self,radius):
        return {'monsters':[{'address':7,'name':'祖玛雕像','position':[18,18],'distance':1,'dead':False,'class':'TSculptureMon'}]}
    def pause(self,seconds):raise RuntimeError('test_complete')

class HeroOnlyTests(unittest.TestCase):
    def test_activated_monster_waits_for_hero_without_casting(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'outputs').mkdir()
            with patch.object(island,'ROOT',Path(folder)),patch.object(island,'cast_lightning') as cast,patch.object(island,'approach_sculpture') as approach,patch('ground_item_probe.ground_snapshot',return_value={'ground_maps':[{'items':[]}]}):
                with self.assertRaisesRegex(RuntimeError,'test_complete'):island.run_island(FakeSession(),player_spells=False)
                cast.assert_not_called();approach.assert_not_called()

class LootPriorityTests(unittest.TestCase):
    def test_successful_pickup_precedes_activation_and_spells(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'outputs').mkdir()
            drops={'ground_maps':[{'items':[{'id':3,'name':'木剑','x':19,'y':18}]}]}
            with patch.object(island,'ROOT',Path(folder)),patch('ground_item_probe.ground_snapshot',return_value=drops),patch.object(island,'loot_island',side_effect=[{'status':'remaining_blocked','results':[{'verified':True}]},RuntimeError('test_complete')]),patch.object(island,'cast_lightning') as cast,patch.object(island,'approach_sculpture') as approach:
                with self.assertRaisesRegex(RuntimeError,'test_complete'):island.run_island(FakeSession())
                cast.assert_not_called();approach.assert_not_called()

class CompletionTests(unittest.TestCase):
    def test_background_spell_mode_stops_before_input(self):
        with self.assertRaisesRegex(RuntimeError,'前台模式'):
            island.run_island(FakeSession(),player_spells=True)

    def test_town_return_completes_without_dice_or_floor(self):
        class Town(FakeSession):
            def npcs(self):return []
            def in_mengzhong_return_area(self):return True
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'outputs').mkdir()
            with patch.object(island,'ROOT',Path(folder)):
                result=island.run_island(Town(),player_spells=False)
        self.assertEqual(result['status'],'completed')
        self.assertTrue(result['completion_verified'])

class LootRetryTests(unittest.TestCase):
    def test_blocked_drop_is_retried_after_other_targets(self):
        import json
        import ground_item_probe as ground
        class LootSession:
            base=0
            def uint(self,address):return 100
            def read(self,address,size):return b'x'*size
            def check(self):pass
            def pause(self,seconds):pass
            def player(self):return (21,15)
            def nearby_monsters(self,radius):return {'loaded_monster_alive':0}
        seen=[]
        def pickup(session,excluded,names,radius,cooperative=False):
            self.assertTrue(cooperative)
            seen.append(set(excluded))
            return [ {'status':'blocked','id':7,'verified':False}, {'status':'no_target'},
                     {'status':'completed','id':7,'verified':True}, {'status':'no_target'} ][len(seen)-1]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'outputs').mkdir();state=root/'state.json'
            state.write_text(json.dumps({'role':{'status':'entered','map_header':(b'x'*52).hex()}}),encoding='utf8')
            with patch.object(island,'ROOT',root),patch.object(island,'STATE',state),patch('importlib.reload',side_effect=lambda module:module),patch.object(ground,'pickup_current_test',side_effect=pickup),patch.object(ground,'ground_snapshot',return_value={'ground_maps':[{'items':[]}]}):
                result=island.loot_island(LootSession())
        self.assertEqual(seen,[set(),{7},set(),set()])
        self.assertEqual(result['status'],'complete')
        self.assertEqual(result['retry_passes'],1)

if __name__=='__main__':unittest.main()


class CornerUiExclusionTests(unittest.TestCase):
    def test_legacy_corner_uses_verified_common_npc_open(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        import island_challenge
        npc={'name':'孤岛挑战','map':(13,18),'draw':(64,240),'address':7}
        opened=[False]
        def open_npc(target):
            self.assertIs(target,npc);opened[0]=True
        s=SimpleNamespace(visible=lambda key:opened[0],player=lambda:(17,18),
            nearby_monsters=lambda **k:{'loaded_monster_alive':0},held_item=lambda:'',
            sale_item=lambda:'',inflight_item=lambda:'',npcs=lambda:[npc],open_npc=Mock(side_effect=open_npc))
        r=island_challenge.open_corner(s)
        s.open_npc.assert_called_once_with(npc)
        self.assertTrue(r['merchant_visible'])
