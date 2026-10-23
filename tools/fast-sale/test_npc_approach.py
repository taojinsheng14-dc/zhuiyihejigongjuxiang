import struct,unittest
from unittest.mock import Mock,patch
from background_sale import BackgroundSession
from map_navigation import TileMap,npc_approach_step

class NpcApproachTests(unittest.TestCase):
    def session(self,moves=True,changes_map=False):
        s=object.__new__(BackgroundSession);s.base=0;s.events=[]
        npc={'name':'铁匠铺老板','map':(5,9),'address':1000}
        state={'position':(12,17),'draw':(304,-80),'header':bytes(52),'merchant':False}
        raw=bytearray(52+18*24*12);struct.pack_into('<HH',raw,0,18,24)
        s.navigation_map=lambda h:TileMap(raw,'0159.map')
        s.uint=lambda addr:999;s.read=lambda *args:state['header']
        s.player=s.stable_player=lambda:state['position'];s.check=Mock();s.login_stage=lambda:'playing'
        s.held_item=s.sale_item=s.inflight_item=lambda:''
        s.visible=lambda key:state['merchant'] if key=='merchant' else False
        s.npcs=lambda characters=False:[] if characters else [npc]
        s.unique_npc=lambda name,xy:npc
        s.verified_npc_draw=lambda target:state['draw']
        s.client_size=lambda:(1280,800);s.hero_covers=lambda box:False
        def walk(target,**kwargs):
            if moves:state.update(position=target,draw=(400,100))
            if changes_map:state['header']=b'x'*52
        s.walk_tile=Mock(side_effect=walk)
        def click(target):s.events.append({'point':target});state['merchant']=True
        s.click=Mock(side_effect=click)
        s.wait=lambda condition,timeout:condition() or (_ for _ in ()).throw(RuntimeError('timeout'))
        return s,npc,state

    def test_visible_lower_body_does_not_require_unnecessary_movement(self):
        s,npc,state=self.session();state['draw']=(304,-15)
        with patch('background_sale.time.sleep'):s.open_npc(npc)
        s.walk_tile.assert_not_called();s.click.assert_called_once_with((304,41))
    def test_fully_outside_screen_has_no_click_point(self):
        s,npc,state=self.session()
        self.assertIsNone(s.npc_click_point((304,-80)))
    def test_top_clipped_blacksmith_is_approached_then_opened_once(self):
        s,npc,state=self.session()
        with patch('background_sale.time.sleep'):s.open_npc(npc)
        s.walk_tile.assert_called_once();s.click.assert_called_once()
        self.assertTrue(state['merchant']);self.assertEqual(s.active_merchant,'铁匠铺老板')
        self.assertLessEqual(max(abs(a-b) for a,b in zip((12,17),s.walk_tile.call_args.args[0])),2)
        self.assertFalse(s.walk_tile.call_args.kwargs['allow_transition'])
        self.assertTrue(s.walk_tile.call_args.kwargs['run_only'])
    def test_already_clickable_npc_is_not_moved(self):
        s,npc,state=self.session();state['draw']=(400,100)
        with patch('background_sale.time.sleep'):s.open_npc(npc)
        s.walk_tile.assert_not_called();s.click.assert_called_once()
    def test_failed_lower_hit_retries_body_anchor_not_ground(self):
        s,npc,state=self.session();state['draw']=(1120,465)
        def click(target):
            s.events.append({'point':target})
            if target==(1120,465):state['merchant']=True
        s.click=Mock(side_effect=click)
        with patch('background_sale.time.sleep'):s.open_npc(npc)
        self.assertEqual([call.args[0] for call in s.click.call_args_list],[(1120,489),(1120,465)])
        self.assertTrue(state['merchant']);s.walk_tile.assert_not_called()
    def test_two_failed_npc_hits_stop_without_more_attempts(self):
        s,npc,state=self.session();state['draw']=(1120,465)
        s.click=Mock(side_effect=lambda target:s.events.append({'point':target}))
        with patch('background_sale.time.sleep'):
            with self.assertRaisesRegex(RuntimeError,'timeout'):s.open_npc(npc)
        self.assertEqual(s.click.call_count,2)
    def test_two_nonmoving_attempts_stop_without_npc_click(self):
        s,npc,state=self.session(moves=False)
        with self.assertRaisesRegex(RuntimeError,'连续两次'):s.approach_shop_npc(npc)
        self.assertEqual(s.walk_tile.call_count,2);s.click.assert_not_called()
    def test_map_transition_stops_before_click(self):
        s,npc,state=self.session(changes_map=True)
        with self.assertRaisesRegex(RuntimeError,'地图变化'):s.approach_shop_npc(npc)
        s.click.assert_not_called()
    def test_pending_item_blocks_movement(self):
        s,npc,state=self.session();s.inflight_item=lambda:'木剑'
        with self.assertRaisesRegex(RuntimeError,'物品操作'):s.approach_shop_npc(npc)
        s.walk_tile.assert_not_called();s.click.assert_not_called()
    def test_unknown_npc_never_uses_city_approach(self):
        s,npc,state=self.session();npc=dict(npc,name='未知NPC')
        with self.assertRaisesRegex(RuntimeError,'尚未校准'):s.approach_shop_npc(npc)
        s.walk_tile.assert_not_called()
    def test_no_path_never_blind_clicks_the_ground(self):
        s,npc,state=self.session();s.navigation_map=lambda h:type('Map',(),{'name':'shop','free':lambda self,xy:False})()
        with self.assertRaisesRegex(RuntimeError,'没有已核对'):s.approach_shop_npc(npc)
        s.walk_tile.assert_not_called();s.click.assert_not_called()
    def test_npc_identity_checks_map_coordinate_before_click(self):
        s=object.__new__(BackgroundSession);s.base=0
        s.uint=lambda addr:{100:0x249874,112:200,196:4}[addr]
        s.read=lambda addr,n:'老板'.encode('gb18030') if addr==200 else struct.pack('<2i',9,9)
        with self.assertRaisesRegex(RuntimeError,'地图位置'):s.verified_npc_draw({'address':100,'name':'老板','map':(5,9)})

if __name__=='__main__':unittest.main()
