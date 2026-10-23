import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from inventory_flow import ensure_loot_capacity


class CapacityTests(unittest.TestCase):
    def session(self,free=1):
        state={'main':['木剑']*(40-free)+['']*free}
        s=SimpleNamespace(inventory=lambda:state['main'],check=Mock(),login_stage=lambda:'playing',
            held_item=lambda:'',sale_item=lambda:'',inflight_item=lambda:'',hero_ready=lambda:True,
            ensure_hero_available=Mock(),read=lambda a,n:b'map',uint=lambda a:100,base=0,
            close_panels=Mock())
        def transfer():
            state['main']=['魔血石(大)']+['']*39
            return {'return_required':False,'transfers':[{'verified':True}]}
        s.handle_full_bags=Mock(side_effect=transfer)
        return s,state
    def test_at_39_slots_transfers_then_closes_panels_and_resamples(self):
        s,state=self.session();r=ensure_loot_capacity(s)
        self.assertTrue(r['transferred']);self.assertEqual(r['main_free'],39)
        s.handle_full_bags.assert_called_once();self.assertEqual(s.close_panels.call_count,2)
    def test_spare_space_does_not_send_any_transfer_input(self):
        s,state=self.session(free=2);self.assertFalse(ensure_loot_capacity(s)['transferred'])
        s.handle_full_bags.assert_not_called();s.close_panels.assert_not_called()
    def test_pending_item_blocks_all_transfer_input(self):
        s,state=self.session();s.held_item=lambda:'木剑'
        with self.assertRaisesRegex(RuntimeError,'物品状态不空'):ensure_loot_capacity(s)
        s.handle_full_bags.assert_not_called();s.close_panels.assert_not_called()
    def test_both_full_stop_locally_without_exiting_challenge(self):
        s,state=self.session(free=0);s.handle_full_bags=Mock(return_value={'return_required':True})
        with self.assertRaisesRegex(RuntimeError,'不自动退出挑战'):ensure_loot_capacity(s)
    def test_changed_map_blocks_continuation_after_transfer(self):
        s,state=self.session();s.read=Mock(side_effect=[b'map1',b'map2'])
        with self.assertRaisesRegex(RuntimeError,'地图变化'):ensure_loot_capacity(s)


if __name__=='__main__':unittest.main()
