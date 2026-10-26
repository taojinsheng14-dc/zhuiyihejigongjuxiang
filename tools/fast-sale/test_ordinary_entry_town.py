import unittest
from unittest.mock import Mock
from background_sale import BackgroundSession

class EntryTownTests(unittest.TestCase):
    def session(self,name='5.map'):
        s=object.__new__(BackgroundSession)
        s.login_stage=lambda:'playing'
        s.held_item=lambda:'';s.sale_item=lambda:'';s.inflight_item=lambda:''
        s.base=0;s.uint=lambda a:0;s.read=lambda a,n:b'map'
        s.current_map_name=lambda h:name
        s.in_mengzhong_return_area=Mock(side_effect=[False,True])
        s.unique_npc=Mock();s.return_with_hotkey=Mock()
        return s
    def test_verified_cangyue_returns_once(self):
        s=self.session();s.ensure_ordinary_entry_town()
        s.unique_npc.assert_called_once_with('苍月老兵',(139,333))
        s.return_with_hotkey.assert_called_once()
    def test_verified_weapon_shop_returns_once(self):
        s=self.session('0159.map');s.ensure_ordinary_entry_town()
        s.unique_npc.assert_called_once_with('铁匠铺老板',(5,9))
        s.return_with_hotkey.assert_called_once()
    def test_town_does_not_consume_return_stone(self):
        s=self.session();s.in_mengzhong_return_area=Mock(return_value=True)
        s.ensure_ordinary_entry_town();s.return_with_hotkey.assert_not_called()
    def test_unknown_map_or_wrong_npc_blocks_return(self):
        for wrong in ('map','npc'):
            s=self.session('d715.map' if wrong=='map' else '5.map')
            if wrong=='npc':s.unique_npc.side_effect=RuntimeError('身份不符')
            with self.assertRaises(RuntimeError):s.ensure_ordinary_entry_town()
            s.return_with_hotkey.assert_not_called()
    def test_failed_return_does_not_open_entry_menu(self):
        s=self.session();s.in_mengzhong_return_area=Mock(return_value=False)
        s.shortcut_inventory=lambda:[{'name':'盟重传送石'}]
        s.hero_ready=lambda:True;s.dual_bag_status=lambda:{'main_free':38,'hero_free':38}
        s.open_hunt_menu=Mock()
        with self.assertRaisesRegex(RuntimeError,'未确认回到盟重'):s.prepare_ordinary_room_entry()
        s.open_hunt_menu.assert_not_called()
    def test_unsettled_item_blocks_all_return_input(self):
        s=self.session();s.held_item=lambda:'破魂'
        with self.assertRaisesRegex(RuntimeError,'物品操作未结束'):s.ensure_ordinary_entry_town()
        s.return_with_hotkey.assert_not_called()

if __name__=='__main__':unittest.main()
