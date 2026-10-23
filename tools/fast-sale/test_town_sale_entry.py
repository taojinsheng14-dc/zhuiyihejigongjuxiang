import unittest
from unittest.mock import Mock, patch
from background_sale import BackgroundSession, GameSessionLost


class TownSaleEntryTests(unittest.TestCase):
    def session(self,count=2):
        s=object.__new__(BackgroundSession)
        s.check=Mock();s.login_stage=lambda:'playing';s.client_size=lambda:(1680,1050)
        s.bounds=lambda key:(0,0,352,295) if key=='bag' else (0,0,288,160)
        s.in_mengzhong_return_area=lambda:True
        s.held_item=lambda:'';s.sale_item=lambda:'';s.inflight_item=lambda:''
        s.currency_snapshot=Mock(side_effect=[{'gold':10000,'yuanbao':100},{'gold':12000,'yuanbao':100}])
        s.dual_sale_route=Mock(return_value={'count':count})
        s.inventory=lambda:['']*40;s.hero_inventory=lambda:['']*40
        s.base=0;s.uint=lambda address:0;s.read=Mock(return_value=b'town')
        s.prepare_ordinary_room_entry=Mock(return_value={'points':[(200,200)]})
        s.enter_ordinary_room=Mock(side_effect=AssertionError('must never enter'))
        return s

    def test_sells_then_prepares_menu_without_entering_or_mouse_entry(self):
        s=self.session();calls=[]
        s.dual_sale_route.side_effect=lambda *a,**kw:calls.append('sale') or {'count':2}
        s.prepare_ordinary_room_entry.side_effect=lambda:calls.append('menu') or {'points':[(200,200)]}
        with patch.object(BackgroundSession,'background_mouse',side_effect=AssertionError('no entry click')):
            result=s.town_sale_entry_test()
        self.assertEqual(calls,['sale','menu'])
        self.assertEqual(result['status'],'complete');self.assertEqual(result['entry_clicks'],0)
        self.assertFalse(result['entered']);self.assertEqual(result['yuanbao_change'],0)
        s.dual_sale_route.assert_called_once_with(unittest.mock.ANY,allow_recovery=False)
        s.enter_ordinary_room.assert_not_called()

    def test_empty_bags_do_not_claim_sale_verified(self):
        result=self.session(count=0).town_sale_entry_test()
        self.assertEqual(result['status'],'complete_without_sale');self.assertFalse(result['sale_verified'])

    def test_1280_window_and_twelve_equivalent_room_links_are_supported(self):
        s=self.session();s.client_size=lambda:(1280,800)
        s.shortcut_inventory=lambda:[{'name':'盟重传送石'}]
        s.hero_ready=lambda:True;s.dual_bag_status=lambda:{'main_free':39,'hero_free':36}
        s.open_hunt_menu=lambda:{'points':[(20+66*i,168) for i in range(6)]+[(20+66*i,196) for i in range(6)]}
        s.prepare_ordinary_room_entry=lambda:BackgroundSession.prepare_ordinary_room_entry(s)
        result=s.town_sale_entry_test()
        self.assertEqual(result['status'],'complete');self.assertEqual(len(result['menu']['points']),12)
        s.enter_ordinary_room.assert_not_called()

    def test_not_town_or_unsupported_size_does_not_sell(self):
        for invalid in ('town','size'):
            s=self.session()
            if invalid=='town':s.in_mengzhong_return_area=lambda:False
            else:s.client_size=lambda:(800,600)
            with self.assertRaises(RuntimeError):s.town_sale_entry_test()
            s.dual_sale_route.assert_not_called();s.prepare_ordinary_room_entry.assert_not_called()

    def test_pending_equipment_after_sale_blocks_menu(self):
        s=self.session();s.inventory=lambda:['木剑']+['']*39
        with self.assertRaisesRegex(RuntimeError,'仍有白名单'):s.town_sale_entry_test()
        s.prepare_ordinary_room_entry.assert_not_called()

    def test_sale_failure_stops_before_menu(self):
        s=self.session();s.dual_sale_route.side_effect=RuntimeError('sale failed')
        with self.assertRaisesRegex(RuntimeError,'sale failed'):s.town_sale_entry_test()
        s.prepare_ordinary_room_entry.assert_not_called()

    def test_unexpected_map_change_or_yuanbao_change_is_not_passed(self):
        s=self.session();s.read.side_effect=[b'town',b'room']
        with self.assertRaisesRegex(RuntimeError,'地图意外变化'):s.town_sale_entry_test()
        s=self.session();s.currency_snapshot.side_effect=[{'gold':10000,'yuanbao':100},{'gold':12000,'yuanbao':95}]
        with self.assertRaisesRegex(RuntimeError,'元宝有变化'):s.town_sale_entry_test()

    def test_test_sale_never_relogs_after_disconnect(self):
        s=object.__new__(BackgroundSession);s.sales=[];s.check=lambda:None
        s._dual_sale_route=Mock(side_effect=GameSessionLost('disconnected'))
        s.recover_session=Mock()
        with self.assertRaises(GameSessionLost):s.dual_sale_route(allow_recovery=False)
        s.recover_session.assert_not_called();self.assertFalse(s._sale_recovery_enabled)
