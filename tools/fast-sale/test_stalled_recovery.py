import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from background_sale import BackgroundSession,SaleConfirmationStalled


class StalledSaleTests(unittest.TestCase):
    def session(self):
        s=object.__new__(BackgroundSession);state={'sale':'木剑','gold':100}
        empty={'name':'','uid':''};identity={'name':'木剑','uid':'0100000002000000'}
        context={'identity':identity,'inventory':['']*40,'bag_ids':[empty]*40,
                 'wallet':{'gold':100,'yuanbao':20},'header':b'map','merchant':'铁匠铺老板'}
        s.check=Mock();s.login_stage=lambda:'playing';s.held_item=lambda:'';s.inflight_item=lambda:''
        s.sale_item=lambda:state['sale'];s.inventory=lambda:['']*40;s.sale_bag_identities=lambda:[empty]*40
        s.currency_snapshot=lambda:{'gold':state['gold'],'yuanbao':20}
        s.sale_handler_layout=lambda:{'verified':True};s.sale_item_identity=lambda location:identity
        s.visible=lambda key:True;s.base=0;s.uint=lambda addr:0;s.read=lambda addr,size:b'map'
        s.active_merchant='铁匠铺老板';s.unique_npc=Mock();s.log_sale_probe=Mock()
        s.control_info=lambda offset,name:{'visible':True,'bounds':(260,176,140,181) if offset==0x638 else (85,150,24,13)}
        def wait(condition,timeout=4):
            if not condition():raise RuntimeError('timeout')
        s.wait=wait;s.click=Mock();s.refresh_pending_sale=Mock()
        return s,state,context

    def test_same_uid_and_unchanged_wallet_allows_one_confirmation(self):
        s,state,c=self.session()
        s.click.side_effect=lambda point:state.update(sale='',gold=150)
        s.wait_sale_settled('木剑',c['inventory'],retry_context=c)
        s.click.assert_called_once();s.unique_npc.assert_called_once_with('铁匠铺老板',(5,9))

    def test_second_failure_raises_typed_stall_without_third_click(self):
        s,state,c=self.session()
        with self.assertRaises(SaleConfirmationStalled):s.wait_sale_settled('木剑',c['inventory'],retry_context=c)
        s.click.assert_called_once()

    def test_changed_wallet_blocks_retry(self):
        s,state,c=self.session();state['gold']=150
        with self.assertRaisesRegex(RuntimeError,'金币或元宝变化'):s.wait_sale_settled('木剑',c['inventory'],retry_context=c)
        s.click.assert_not_called()

    def test_changed_uid_blocks_retry(self):
        s,state,c=self.session();s.sale_item_identity=lambda location:{'name':'木剑','uid':'other'}
        with self.assertRaisesRegex(RuntimeError,'唯一标识变化'):s.wait_sale_settled('木剑',c['inventory'],retry_context=c)
        s.click.assert_not_called()

    def test_inflight_never_retries_confirmation(self):
        s,state,c=self.session();state['sale']='';s.inflight_item=lambda:'木剑'
        s.refresh_pending_sale.side_effect=RuntimeError('传输未确认')
        with self.assertRaisesRegex(RuntimeError,'传输未确认'):s.wait_sale_settled('木剑',c['inventory'],retry_context=c)
        s.click.assert_not_called()

    def test_cancel_never_retries_or_logs_out(self):
        s,state,c=self.session();s.check.side_effect=RuntimeError('已停止')
        with self.assertRaisesRegex(RuntimeError,'已停止'):s.wait_sale_settled('木剑',c['inventory'],retry_context=c)
        s.click.assert_not_called()

    def test_withdraw_checks_held_uid_then_exact_bag_identity_before_logout(self):
        s,state,c=self.session();state.update(held='',stored=False)
        s.verify_stalled_sale=Mock();s.held_item=lambda:state['held']
        original=c['bag_ids'].copy();stored=original.copy();stored[0]=c['identity']
        s.sale_bag_identities=lambda:stored if state['stored'] else original
        s.inventory=lambda:['木剑']+['']*39 if state['stored'] else ['']*40
        s.bounds=lambda key:(416,0,352,295) if key=='bag' else (29,42,288,160)
        def click(point):
            if state['sale']:state.update(sale='',held='木剑')
            else:state.update(held='',stored=True)
        s.click.side_effect=click
        s.withdraw_verified_sale('木剑',c)
        self.assertEqual(s.click.call_count,2);self.assertTrue(state['stored']);self.assertEqual(state['held'],'')


class SafeRelogTests(unittest.TestCase):
    def session(self):
        s=object.__new__(BackgroundSession);state={'stage':'playing'}
        s.check=Mock();s.login_stage=lambda:state['stage'];s.held_item=lambda:''
        s.sale_item=lambda:'';s.inflight_item=lambda:'';s.base=0;s._expected_character='微笑'
        s.uint=lambda addr:4 if addr==96 else 100
        s.read=lambda addr,size:'微笑'.encode('gb18030')
        s.control_info=lambda offset,name:{'visible':True,'bounds':(0,0,30,30)}
        s.reserve_hunt_recovery=Mock();s.close_panels=Mock()
        s.click=Mock(side_effect=lambda point:state.update(stage='character'))
        s.wait=lambda condition,timeout:self.assertTrue(condition())
        s.recover_session=Mock(return_value={'recovered':True})
        return s,state

    def test_living_actor_is_actually_logged_out_once_then_recovered(self):
        s,state=self.session();result=s.recover_stalled_route(Mock(),'移动卡住')
        self.assertTrue(result['recovered']);s.click.assert_called_once();s.recover_session.assert_called_once()
        s.reserve_hunt_recovery.assert_called_once()
        with self.assertRaisesRegex(RuntimeError,'已小退恢复一次'):s.recover_stalled_route(Mock(),'再次卡住')
        s.click.assert_called_once()

    def test_exhausted_shared_allowance_blocks_all_inputs(self):
        s,state=self.session();s.reserve_hunt_recovery.side_effect=RuntimeError('恢复额度已用完')
        with self.assertRaisesRegex(RuntimeError,'额度已用完'):s.recover_stalled_route(Mock(),'卡住')
        s.click.assert_not_called();s.close_panels.assert_not_called()

    def test_unknown_pending_item_never_logs_out(self):
        s,state=self.session();s.sale_item=lambda:'木剑'
        with self.assertRaisesRegex(RuntimeError,'没有已核对'):s.recover_stalled_route(Mock(),'卡住')
        s.click.assert_not_called();s.reserve_hunt_recovery.assert_not_called()

    def test_wrong_character_blocks_logout_before_reserving_allowance(self):
        s,state=self.session();s._expected_character='另一角色'
        with self.assertRaisesRegex(RuntimeError,'身份不符'):s.recover_stalled_route(Mock(),'卡住')
        s.click.assert_not_called();s.reserve_hunt_recovery.assert_not_called()


if __name__=='__main__':unittest.main()
