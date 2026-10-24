import unittest
import struct
from types import SimpleNamespace
from unittest.mock import Mock
from background_sale import BackgroundSession


class CangyueAnchorTests(unittest.TestCase):
    def arrival_session(self,blocked=False,moves=True):
        s=object.__new__(BackgroundSession);s.base=0;s.xy=(140,330)
        s.unique_npc=Mock();s.close_panels=Mock()
        s.held_item=s.sale_item=s.inflight_item=lambda:''
        s.uint=lambda address:0
        s.read=lambda address,size:struct.pack('<2i',840,369) if size==8 else b'cangyue'
        s.navigation_map=lambda header:SimpleNamespace(free=lambda xy:True)
        s.npcs=lambda *args:[{'map':(142,330)}] if blocked else []
        s.player=s.stable_player=lambda:s.xy
        def run(*args,**kwargs):
            if moves:s.xy=(s.xy[0]+2,s.xy[1])
        s.background_mouse=Mock(side_effect=run)
        return s

    def test_arrival_runs_right_twice_without_travel(self):
        s=self.arrival_session();actions=s.cangyue_arrival_run_right()
        self.assertEqual(s.xy,(144,330));self.assertEqual(len(actions),2)
        self.assertTrue(all(row['button']=='right' for row in actions))

    def test_occupied_landing_and_failed_run_are_not_blindly_retried(self):
        s=self.arrival_session(blocked=True)
        self.assertEqual(s.cangyue_arrival_run_right(),[]);s.background_mouse.assert_not_called()
        s=self.arrival_session(moves=False)
        self.assertEqual(len(s.cangyue_arrival_run_right()),1)
        s.background_mouse.assert_called_once()

    def test_repositions_before_second_merchant_after_sale_moves_player(self):
        s=object.__new__(BackgroundSession)
        state={'loaded':True,'items':['重盔甲(女)','凤凰明珠']}
        clothes={'name':'服装店老板','map':(147,328)}
        jewelry={'name':'首饰店老板','map':(155,339)}
        s.player=lambda:(140,330);s.client_size=lambda:(1680,1050)
        s.validate_city_ui_layout=Mock()
        s.npcs=lambda:[clothes,jewelry] if state['loaded'] else [clothes]
        s.inventory=lambda:state['items'].copy();s.close_panels=Mock()
        s.cangyue_sale_stand=Mock(side_effect=lambda:state.update(loaded=True))
        s.open_cangyue_fixed_sale=Mock();s.visible=lambda key:True
        s.wait=lambda condition:self.assertTrue(condition())
        def sell(category,progress,merchant_name):
            item='重盔甲(女)' if category=='衣服' else '凤凰明珠'
            state['items'].remove(item)
            if category=='衣服':state['loaded']=False
            return {'count':1}
        s.sell_category=sell
        result=s.sell_cangyue_at_anchor()
        self.assertEqual(result['count'],2)
        self.assertEqual(s.cangyue_sale_stand.call_count,2)
        self.assertEqual(s.open_cangyue_fixed_sale.call_args_list[-1].args[0],'首饰店老板')


if __name__=='__main__':unittest.main()
