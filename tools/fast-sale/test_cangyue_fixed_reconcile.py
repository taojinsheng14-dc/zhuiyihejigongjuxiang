import unittest
from unittest.mock import Mock
from background_sale import BackgroundSession, SaleRouteIncomplete
from test_background_sale import Fake


class CangyueFixedMenuTests(unittest.TestCase):
    def session(self):
        s=Fake(); clicked=[]; s.check=lambda:None; s.login_stage=lambda:'playing'
        s.state=lambda:{'map_identity':{'name':'5.map'}}; s.player=lambda:[144,330]
        s.close_panels=Mock();s.cangyue_sale_stand=Mock();s.unique_npc=Mock(return_value={})
        def open_npc(npc):s.active_merchant=s.unique_npc.call_args.args[0]
        s.open_npc=Mock(side_effect=open_npc)
        s.click=lambda point:clicked.append(point)
        s.visible=lambda key:True if key=='merchant' else bool(clicked)
        s.menu_matches=Mock(side_effect=AssertionError('must not inspect screenshots'))
        s.submit_one=Mock()
        return s,clicked

    def test_each_shop_opens_sell_and_bag_without_image_or_submission(self):
        for name in ['服装店老板','首饰店老板']:
            s,clicks=self.session();result=s.open_cangyue_fixed_sale(name)
            self.assertEqual(len(clicks),1);self.assertTrue(result['sell_visible'])
            self.assertTrue(result['bag_visible']);self.assertFalse(result['image_matching'])
            s.submit_one.assert_not_called();s.menu_matches.assert_not_called()

    def test_wrong_map_or_pending_item_stops_before_input(self):
        for pending in (False,True):
            s,clicks=self.session()
            if pending:s.inflight_item=lambda:'木剑'
            else:s.state=lambda:{'map_identity':{'name':'3.map'}}
            with self.assertRaises(RuntimeError):s.open_cangyue_fixed_sale('首饰店老板')
            self.assertEqual(clicks,[]);s.open_npc.assert_not_called()

    def test_no_sell_window_never_retries_menu_click(self):
        s,clicks=self.session();s.visible=lambda key:key=='merchant'
        with self.assertRaises(RuntimeError):s.open_cangyue_fixed_sale('首饰店老板')
        self.assertEqual(len(clicks),1)


class SaleStateReconcileTests(unittest.TestCase):
    def session(self):
        s=object.__new__(BackgroundSession);s.sales=[];s.check=lambda:None
        s.pause=lambda seconds:None;s.login_stage=lambda:'playing'
        s.held_item=s.sale_item=s.inflight_item=lambda:'';s.hero_ready=lambda:True
        s.inventory=s.hero_inventory=lambda:['']*40
        s.close_panels=Mock();s.recover_incomplete_sale=Mock(return_value={'recovered':True})
        return s

    def test_hero_leftovers_prevent_false_complete(self):
        s=self.session();s.hero_inventory=lambda:['木剑']+['']*39
        with self.assertRaises(SaleRouteIncomplete):s.verify_sale_complete()

    def test_late_inventory_update_is_caught_by_second_sample(self):
        s=self.session();s.inventory=Mock(side_effect=[['']*40,['木剑']+['']*39])
        with self.assertRaises(SaleRouteIncomplete):s.verify_sale_complete()

    def test_residual_resets_route_without_logout_first(self):
        s=self.session();s.main=['木剑']+['']*39;s.inventory=lambda:s.main
        def route(progress):
            if s._dual_sale_route.call_count==2:s.main=['']*40
            return {'count':0}
        s._dual_sale_route=Mock(side_effect=route)
        result=s.dual_sale_route()
        self.assertEqual(s._dual_sale_route.call_count,2)
        s.close_panels.assert_called_once();s.recover_incomplete_sale.assert_not_called()
        self.assertEqual(result['recoveries'],[])

    def test_still_incomplete_only_gets_one_relogin_then_stops(self):
        s=self.session();s.inventory=lambda:['木剑']+['']*39
        s._dual_sale_route=Mock(return_value={'count':0})
        with self.assertRaises(SaleRouteIncomplete):s.dual_sale_route()
        self.assertEqual(s._dual_sale_route.call_count,3)
        s.recover_incomplete_sale.assert_called_once()

    def test_tests_with_recovery_disabled_never_relogin(self):
        s=self.session();s.inventory=lambda:['木剑']+['']*39
        s._dual_sale_route=Mock(return_value={'count':0})
        with self.assertRaises(SaleRouteIncomplete):s.dual_sale_route(allow_recovery=False)
        s.recover_incomplete_sale.assert_not_called()

    def test_unknown_inflight_state_never_resets_or_logs_out(self):
        s=self.session();s.inflight_item=lambda:'木剑';s._dual_sale_route=Mock(return_value={})
        with self.assertRaisesRegex(RuntimeError,'传输'):s.dual_sale_route()
        s.close_panels.assert_not_called();s.recover_incomplete_sale.assert_not_called()

    def test_preentry_residual_goes_back_to_sale_and_rechecks(self):
        s=self.session();s.main=['木剑']+['']*39;s.inventory=lambda:s.main
        s.dual_sale_route=Mock(side_effect=lambda progress:setattr(s,'main',['']*40))
        s.reconcile_before_reentry(Mock());s.dual_sale_route.assert_called_once()

    def test_hunt_map_forbids_reconcile_logout(self):
        s=self.session();s.state=lambda:{'map_identity':{'name':'m001.map'},'player':[20,20]}
        s.recover_stalled_route=Mock()
        s.recover_incomplete_sale=BackgroundSession.recover_incomplete_sale.__get__(s)
        with self.assertRaisesRegex(RuntimeError,'禁止'):s.recover_incomplete_sale(Mock(),'incomplete')
        s.recover_stalled_route.assert_not_called()

    def test_logout_preserves_map_and_position_or_stops(self):
        for moved in (False,True):
            s=self.session();s.recover_stalled_route=Mock(return_value={'recovered':True})
            s.recover_incomplete_sale=BackgroundSession.recover_incomplete_sale.__get__(s)
            before={'map_identity':{'name':'5.map'},'player':[144,330]}
            after={'map_identity':{'name':'5.map'},'player':[145,330] if moved else [144,330]}
            s.state=Mock(side_effect=[before,after])
            if moved:
                with self.assertRaisesRegex(RuntimeError,'位置'):s.recover_incomplete_sale(Mock(),'incomplete')
            else:self.assertTrue(s.recover_incomplete_sale(Mock(),'incomplete')['recovered'])

    def test_exhausted_ledger_failure_propagates_without_new_attempt(self):
        s=self.session();s.recover_stalled_route=Mock(side_effect=RuntimeError('恢复额度已用完'))
        s.recover_incomplete_sale=BackgroundSession.recover_incomplete_sale.__get__(s)
        s.state=lambda:{'map_identity':{'name':'5.map'},'player':[144,330]}
        with self.assertRaisesRegex(RuntimeError,'额度已用完'):s.recover_incomplete_sale(Mock(),'incomplete')
        s.recover_stalled_route.assert_called_once()


if __name__=='__main__':unittest.main()
