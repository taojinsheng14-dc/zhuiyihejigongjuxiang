import struct,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
import island_automation as island

class EntranceTests(unittest.TestCase):
    def session(self,move=True,loaded=False):
        state={'position':(332,329),'loaded':loaded}
        npc={'name':'孤岛挑战','map':(317,331),'address':123}
        s=SimpleNamespace(base=0,in_mengzhong_return_area=lambda:True,close_panels=Mock(),check=Mock(),
            login_stage=lambda:'playing',held_item=lambda:'',sale_item=lambda:'',inflight_item=lambda:'',
            navigation_map=lambda h:SimpleNamespace(name='3.map',free=lambda xy:True),
            npcs=lambda:[npc] if state['loaded'] else [],unique_npc=Mock(return_value=npc),
            stable_player=lambda:state['position'],uint=lambda addr:0,
            read=lambda addr,size:struct.pack('<2i',640,241),client_size=lambda:(1280,800))
        def click(*args,**kwargs):
            if move:state.update(position=(330,329),loaded=True)
        s.background_mouse=Mock(side_effect=click)
        return s
    def test_moves_before_waiting_for_unloaded_actor(self):
        s=self.session()
        with patch.object(island,'header',return_value=b'town'):npc=island.locate_town_entrance(s)
        self.assertEqual(npc['name'],'孤岛挑战');s.background_mouse.assert_called_once();s.unique_npc.assert_called_once()
    def test_loaded_actor_needs_no_walk(self):
        s=self.session(loaded=True)
        with patch.object(island,'header',return_value=b'town'):island.locate_town_entrance(s)
        s.background_mouse.assert_not_called()
    def test_three_failed_moves_stop_without_entry(self):
        s=self.session(move=False)
        with patch.object(island,'header',return_value=b'town'):
            with self.assertRaisesRegex(RuntimeError,'三次未移动'):island.locate_town_entrance(s)
        self.assertEqual(s.background_mouse.call_count,3);s.unique_npc.assert_not_called()
    def test_pending_item_blocks_all_walking(self):
        s=self.session();s.sale_item=lambda:'木剑'
        with patch.object(island,'header',return_value=b'town'):
            with self.assertRaisesRegex(RuntimeError,'物品状态不空'):island.locate_town_entrance(s)
        s.background_mouse.assert_not_called()

if __name__=='__main__':unittest.main()
