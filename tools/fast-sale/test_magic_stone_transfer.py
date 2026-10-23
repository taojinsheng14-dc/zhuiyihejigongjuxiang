import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from background_sale import BackgroundSession
from inventory_flow import retain_in_main_bag

class MagicStoneTests(unittest.TestCase):
    def test_all_magic_stone_sizes_are_retained(self):
        for name in ('魔血石','魔血石(大)','魔血石(中)','魔血石(小)'):
            self.assertTrue(retain_in_main_bag(name))
        self.assertFalse(retain_in_main_bag('木剑'))

    def test_full_bag_transfers_equipment_but_keeps_magic_stones(self):
        s=object.__new__(BackgroundSession)
        main=['魔血石(大)','魔血石(小)','盟重传送石']+['木剑']*36+['']
        hero=['木剑']*37+['']*3
        s.hero_ready=lambda:True;s.inventory=lambda:main.copy();s.hero_inventory=lambda:hero.copy()
        s.visible=lambda key:False;s.open_main_bag=Mock()
        def transfer(source,index,**kwargs):
            name=main[index];self.assertEqual(name,'木剑')
            hero[hero.index('')]=name;main[index]='';return {'name':name}
        s.transfer_bag_item=Mock(side_effect=transfer)
        result=s.handle_full_bags()
        self.assertEqual(main[:3],['魔血石(大)','魔血石(小)','盟重传送石'])
        self.assertEqual(len(result['transfers']),2)
        self.assertEqual(hero.count(''),1)

if __name__=='__main__':unittest.main()
