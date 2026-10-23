import struct,unittest
from types import SimpleNamespace
from unittest.mock import Mock
from background_sale import BackgroundSession

class CangyueReloadStandTests(unittest.TestCase):
    def session(self):
        s=object.__new__(BackgroundSession);s.base=0;s.player=lambda:(142,332)
        s.client_size=lambda:(1280,800);s.hero_covers=lambda box:False
        actors=[{'name':'苍月老兵','map':(139,333),'draw':(496,273)},
                {'name':'服装店老板','map':(147,328),'draw':(880,113)}]
        s.npcs=lambda characters=False:[] if characters else actors
        s.uint=lambda addr:0;s.read=lambda addr,size:struct.pack('<2i',640,241) if size==8 else b'map'
        s.navigation_map=lambda header:SimpleNamespace(free=lambda xy:True)
        s.walk_tile=Mock(return_value={'moved':True})
        return s,actors
    def test_missing_edge_merchant_uses_visible_loaded_range_stand(self):
        s,_=self.session();s.cangyue_sale_stand()
        s.walk_tile.assert_called_once_with((145,332))
    def test_all_merchants_clickable_does_not_walk(self):
        s,actors=self.session();actors.append({'name':'首饰店老板','map':(155,339),'draw':(1200,465)})
        self.assertFalse(s.cangyue_sale_stand()['moved']);s.walk_tile.assert_not_called()

if __name__=='__main__':unittest.main()
