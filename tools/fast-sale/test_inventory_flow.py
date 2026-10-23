import unittest
from inventory_flow import validate_transfer,bag_decision

class InventoryFlowTests(unittest.TestCase):
    def test_both_full_required_for_return(self):
        full=['木剑']*40;empty=['']*40
        self.assertEqual(bag_decision(full,empty,True),'transfer')
        self.assertEqual(bag_decision(empty,full,True),'continue')
        self.assertEqual(bag_decision(full,full,True),'return_town')
    def test_both_bags_must_reach_39_before_return(self):
        almost=['木剑']*39+[''];space=['木剑']*38+['']*2
        self.assertEqual(bag_decision(almost,almost,True),'return_town')
        self.assertEqual(bag_decision(['']*40,almost,True),'continue')
        self.assertEqual(bag_decision(space,almost,True),'continue')
        self.assertEqual(bag_decision(almost,space,True),'transfer')

    def test_unsummoned_hero_is_not_an_empty_bag(self):
        self.assertEqual(bag_decision(['木剑']*40,['']*40,False),'hero_unavailable')
    def test_duplicate_names_do_not_hide_changed_source_slot(self):
        m=['木剑','木剑']+['']*38;h=['']*40
        after=m.copy();after[1]='';dest=h.copy();dest[21]='木剑'
        with self.assertRaises(RuntimeError):validate_transfer(m,h,after,dest,'main',0)
        self.assertEqual(validate_transfer(m,h,after,dest,'main',1),21)
    def test_protected_items_must_stay_unchanged(self):
        m=['木剑','裁决之杖']+['']*38;h=['祝福油']+['']*39
        after=m.copy();after[0]='';after[1]='';dest=h.copy();dest[1]='木剑'
        with self.assertRaises(RuntimeError):validate_transfer(m,h,after,dest,'main',0)
    def test_hero_to_main_roundtrip(self):
        m=['祝福油']+['']*39;h=['木剑']+['']*39
        dest=m.copy();dest[39]='木剑';after=h.copy();after[0]=''
        self.assertEqual(validate_transfer(m,h,dest,after,'hero',0),39)
    def test_overwriting_an_existing_item_is_rejected(self):
        m=['木剑']+['']*39;h=['裁决之杖']+['']*39
        after=['']*40;dest=h.copy();dest[0]='木剑'
        with self.assertRaises(RuntimeError):validate_transfer(m,h,after,dest,'main',0)

class HeroAvailabilityTests(unittest.TestCase):
    def test_no_right_click_without_a_summoned_hero(self):
        from background_sale import BackgroundSession
        class Unavailable(BackgroundSession):
            def __init__(self):pass
            def hero_ready(self):return False
            def ui_right_click(self,point):raise AssertionError('不应发送输入')
        with self.assertRaisesRegex(RuntimeError,'未召唤'):
            Unavailable().transfer_bag_item('main',0)


class MonitorTests(unittest.TestCase):
    def test_both_full_reports_return_without_consuming_any_item(self):
        from background_sale import BackgroundSession
        class Full(BackgroundSession):
            def __init__(self):self.inputs=[]
            def ensure_hero_available(self):pass
            def hero_ready(self):return True
            def check(self):pass
            def login_stage(self):return 'playing'
            def inventory(self):return ['木剑']*40
            def hero_inventory(self):return ['木剑']*40
            def click(self,point):self.inputs.append(point)
        s=Full();r=s.monitor_bags(seconds=1)
        self.assertEqual(r['status'],'return_required')
        self.assertEqual(s.inputs,[])
        self.assertFalse(r['return_stone_used'])

    def test_unavailable_hero_does_not_look_like_an_empty_bag(self):
        from background_sale import BackgroundSession
        class Missing(BackgroundSession):
            def __init__(self):pass
            def ensure_hero_available(self):pass
            def check(self):pass
            def login_stage(self):return 'playing'
            def hero_ready(self):return False
            def hero_inventory(self):raise AssertionError('must not read unloaded bag')
        with self.assertRaisesRegex(RuntimeError,'英雄不可用'):Missing().monitor_bags(seconds=1)


class LiveTransferTests(unittest.TestCase):
    def state(self):
        return {key:[{'name':'','uid':''} for _ in range(40)] for key in ('main','hero')}
    def test_concurrent_loot_can_fill_vacated_slot(self):
        from inventory_flow import validate_live_transfer
        before=self.state();after=self.state()
        before['main'][0]={'name':'木剑','uid':'1234'}
        after['hero'][3]=before['main'][0].copy()
        after['main'][0]={'name':'青铜头盔','uid':'5678'}
        self.assertEqual(validate_live_transfer(before,after,'main',0),3)
    def test_same_name_different_identity_does_not_prove_transfer(self):
        from inventory_flow import validate_live_transfer
        before=self.state();after=self.state();before['main'][0]={'name':'木剑','uid':'1234'}
        after['hero'][0]={'name':'木剑','uid':'5678'}
        with self.assertRaises(RuntimeError):validate_live_transfer(before,after,'main',0)
    def test_hero_can_consume_potion_while_receiving_equipment(self):
        from inventory_flow import validate_live_transfer
        before=self.state();after=self.state();before['main'][0]={'name':'木剑','uid':'1234'}
        before['hero'][1]={'name':'强效太阳水','uid':'5678'};after['hero'][0]=before['main'][0].copy()
        self.assertEqual(validate_live_transfer(before,after,'main',0),0)
    def test_protected_existing_equipment_cannot_be_overwritten(self):
        from inventory_flow import validate_live_transfer
        before=self.state();after=self.state();before['main'][0]={'name':'木剑','uid':'1234'}
        before['hero'][1]={'name':'裁决之杖','uid':'5678'};after['hero'][0]=before['main'][0].copy()
        with self.assertRaisesRegex(RuntimeError,'非消耗品'):validate_live_transfer(before,after,'main',0)

class BackgroundReleaseTests(unittest.TestCase):
    def make_session(self,foreground):
        from unittest.mock import MagicMock
        from background_sale import BackgroundSession
        session=object.__new__(BackgroundSession);session.hwnd=100;session.u=MagicMock()
        session.u.GetForegroundWindow.return_value=foreground
        session.u.SendMessageTimeoutW.return_value=1
        return session
    def test_background_input_ends_with_capture_cancel_and_inactive_notice(self):
        s=self.make_session(999);s.clear_background_mouse()
        messages=[call.args[1] for call in s.u.SendMessageTimeoutW.call_args_list]
        self.assertIn(0x1f,messages);self.assertEqual(messages[-3:],[8,6,0x1c])
        s.u.SetForegroundWindow.assert_not_called()
    def test_actual_foreground_game_is_not_given_a_false_focus_loss(self):
        s=self.make_session(100);s.clear_background_mouse()
        messages=[call.args[1] for call in s.u.SendMessageTimeoutW.call_args_list]
        self.assertNotIn(8,messages);self.assertNotIn(6,messages);self.assertNotIn(0x1c,messages)

    def input_session(self):
        from unittest.mock import Mock
        s=self.make_session(999);s.check=Mock();s.pause=Mock()
        s.u.IsIconic.return_value=False;s.u.GetAsyncKeyState.return_value=0
        s.u.PostMessageW.return_value=1;s.client_size=lambda:(1680,1050);s.events=[]
        s.physical_client_size=s.client_size;s.player=lambda:(3,11)
        return s

    def test_background_click_brackets_activation_without_focus_or_cursor(self):
        s=self.input_session();s.click((100,100))
        calls=s.u.SendMessageTimeoutW.call_args_list
        self.assertEqual(calls[0].args[1:3],(0x1c,1))
        self.assertEqual(calls[-1].args[1:3],(0x1c,0))
        s.u.SetForegroundWindow.assert_not_called();s.u.SetCursorPos.assert_not_called()

    def test_click_failure_still_releases_and_clears_activation(self):
        s=self.input_session();s.u.SendMessageTimeoutW.side_effect=lambda hwnd,msg,*args:0 if msg==0x201 else 1
        with self.assertRaisesRegex(RuntimeError,'后台鼠标消息未完成'):s.click((100,100))
        calls=s.u.SendMessageTimeoutW.call_args_list
        self.assertEqual(calls[-1].args[1:3],(0x1c,0))
        self.assertIn(0x202,[call.args[1] for call in calls])

    def test_physical_mouse_use_blocks_activation_and_click(self):
        from unittest.mock import patch
        s=self.input_session();s.u.GetAsyncKeyState.return_value=0x8000
        with patch('background_sale.time.monotonic',side_effect=[0,31]):
            with self.assertRaisesRegex(RuntimeError,'鼠标按键持续占用'):s.begin_background_input()
        s.u.SendMessageTimeoutW.assert_not_called();s.u.PostMessageW.assert_not_called()

    def test_brief_work_click_waits_for_release_before_message_activation(self):
        s=self.input_session();s.u.GetAsyncKeyState.return_value=0x8000
        def release(seconds):s.u.GetAsyncKeyState.return_value=0
        s.pause.side_effect=release
        s.begin_background_input()
        s.pause.assert_called_once_with(.05)
        self.assertEqual(s.u.SendMessageTimeoutW.call_args.args[1:3],(0x1c,1))

class EscapeScopeTests(unittest.TestCase):
    def session(self,foreground):
        import time
        from unittest.mock import MagicMock
        from background_sale import BackgroundSession
        s=object.__new__(BackgroundSession);s.hwnd=100;s.u=MagicMock();s.reader=MagicMock()
        s.reader.pid=None;s.u.GetForegroundWindow.return_value=foreground
        s.u.GetAsyncKeyState.return_value=0x8000;s.last_guard=time.monotonic()
        return s
    def test_escape_in_work_window_does_not_stop_game_task(self):
        self.session(999).check()
    def test_escape_in_game_still_stops(self):
        with self.assertRaisesRegex(RuntimeError,'Esc停止'):self.session(100).check()
