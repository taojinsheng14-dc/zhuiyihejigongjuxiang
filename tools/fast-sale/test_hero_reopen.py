import unittest
from background_sale import BackgroundSession


class HeroReopenTests(unittest.TestCase):
    def test_server_slot_reorder_on_open_and_compaction_after_transfer(self):
        class Fake(BackgroundSession):
            def __init__(self):
                self.main=['']*40
                self.hero=['木剑','青铜头盔']+['']*38
                self.taken=[]
            def ensure_hero_available(self): pass
            def hero_covers(self, area): return False
            def inventory(self): return self.main.copy()
            def hero_inventory(self): return self.hero.copy()
            def close_panels(self): pass
            def pause(self, seconds): pass
            def open_hero_bag(self):
                self.hero=['魔血石(大)','木剑','青铜头盔']+['']*37
            def transfer_bag_item(self, source, index):
                name=self.hero[index]
                self.taken.append(name)
                self.main[self.main.index('')]=name
                self.hero.pop(index)
                self.hero.append('')
                return {'verified':True}
            def mixed_sale_route(self, progress):
                count=sum(bool(x) for x in self.main)
                self.main=['']*40
                return {'count':count}
        s=Fake()
        result=s._dual_sale_route()
        self.assertEqual(s.taken,['木剑','青铜头盔'])
        self.assertEqual(result['count'],2)
        self.assertEqual(s.hero[0],'魔血石(大)')


if __name__ == '__main__': unittest.main()
