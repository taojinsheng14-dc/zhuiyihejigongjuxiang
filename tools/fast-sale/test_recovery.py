import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock,patch
from background_sale import BackgroundSession, GameSessionLost


class RecoveryFake(BackgroundSession):
    def __init__(self):
        self.stage='character';self.message=None;self.hwnd=1;self.base=0
        self.clicks=[];self.cleared=False
        self.u=SimpleNamespace(PostMessageW=lambda *args:True)
    def login_stage(self):return self.stage
    def enter_saved_character(self):self.stage='message';self.message='welcome'
    def recovery_message_matches(self,kind):return self.message==kind
    def control_info(self,offset,name):
        return {'bounds':(712,345,256,359) if offset==0x3d8 else (89,305,80,34)}
    def click(self,point):self.clicks.append(point);self.stage='loading'
    def press_login_confirm(self):self.clicks.append('Enter');self.stage='loading'
    def wait(self,condition,timeout):
        if not condition():raise RuntimeError('unexpected wait')
    def pause(self,seconds):self.stage='playing'
    def stable_player(self):return self.player()
    def player(self):return (331,332)
    def uint(self,address):return 4 if address==96 else 100
    def read(self,address,size):return '大鱼'.encode('gb18030')
    def held_item(self):return ''
    def sale_item(self):return ''
    def inflight_item(self):return ''
    def clear_background_mouse(self):self.cleared=True


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        # Fixtures must not inherit the user's live account binding.
        binding=patch('instance_context.binding',return_value=None);binding.start();self.addCleanup(binding.stop)

    def test_recovery_budget_is_shared_and_never_resets_between_stages(self):
        s=object.__new__(BackgroundSession);s._hunt_recoveries=1
        self.assertEqual(s.reserve_hunt_recovery('hunt'),2)
        with self.assertRaisesRegex(RuntimeError,'额度已用完'):s.reserve_hunt_recovery('sale')
        self.assertEqual(s._hunt_recoveries,2)

    def test_sale_cannot_bypass_exhausted_shared_budget(self):
        s=object.__new__(BackgroundSession);s._hunt_recoveries=2;s.sales=[]
        s.check=Mock();s._dual_sale_route=Mock(side_effect=GameSessionLost('disconnect'))
        s.recover_session=Mock()
        with self.assertRaisesRegex(RuntimeError,'额度已用完'):s.dual_sale_route()
        s.recover_session.assert_not_called()

    def test_fullscreen_disconnect_glyph_edges_are_recognized(self):
        from PIL import Image
        import background_sale
        s=object.__new__(BackgroundSession)
        s.control_info=lambda offset,name:{'bounds':(0,0,452,179),'visible':True}
        picture=Image.new('RGB',(452,179))
        directory=Path(background_sale.__file__).with_name('shop-layout')
        picture.paste(Image.open(directory/'recovery-disconnected-fullscreen-test.png'),(20,34))
        s.capture_client=lambda:picture
        self.assertTrue(s.recovery_message_matches('disconnected'))
        for name in ('recovery-logout.png','recovery-town_hunt_forbidden.png'):
            picture=Image.new('RGB',(452,179))
            picture.paste(Image.open(directory/name),(20,34))
            self.assertFalse(s.recovery_message_matches('disconnected'))

    def test_reconnect_does_nothing_to_a_live_client(self):
        s=object.__new__(BackgroundSession);s.reader=Mock();s.reader.alive.return_value=True
        s.check=Mock()
        self.assertFalse(s.reconnect_running_client());s.check.assert_not_called()

    def test_reconnect_without_trusted_directory_never_opens_another_process(self):
        s=object.__new__(BackgroundSession);s.reader=Mock();s.reader.alive.return_value=False
        s.check=Mock(side_effect=RuntimeError('目标游戏已关闭或重启，停止操作'))
        with self.assertRaisesRegex(RuntimeError,'缺少已验证'):s.reconnect_running_client()
        s.reader.connect.assert_not_called()

    def test_reconnect_preserves_user_stop_and_guard_errors(self):
        for message in ('已停止','其他游戏保护名单触发，停止'):
            s=object.__new__(BackgroundSession);s.reader=Mock();s.reader.alive.return_value=False
            s._game_install_directory=Path('C:/Game');s.check=Mock(side_effect=RuntimeError(message))
            with self.assertRaisesRegex(RuntimeError,message):s.reconnect_running_client()
            s.reader.connect.assert_not_called()

    def test_second_disconnect_wording_is_recognized_without_accepting_blank_dialog(self):
        from PIL import Image
        import background_sale
        s=object.__new__(BackgroundSession)
        s.control_info=lambda offset,name:{'bounds':(0,0,452,179),'visible':True}
        picture=Image.new('RGB',(452,179))
        template=Image.open(Path(background_sale.__file__).with_name('shop-layout')/'recovery-disconnected-login.png')
        picture.paste(template,(20,34));s.capture_client=lambda:picture
        self.assertTrue(s.recovery_message_matches('disconnected'))
        s.capture_client=lambda:Image.new('RGB',(452,179))
        self.assertFalse(s.recovery_message_matches('disconnected'))

    def test_server_automatic_relogin_gets_grace_and_one_more_start(self):
        class Forced(RecoveryFake):
            def __init__(self):super().__init__();self.starts=0;self.play_polls=0
            def enter_saved_character(self):
                self.starts+=1;self.stage='message';self.message='welcome'
            def pause(self,seconds):
                if self.stage=='loading':self.stage='playing'
                elif self.stage=='playing':
                    self.play_polls+=1
                    if self.starts==1 and self.play_polls==8:self.stage='character'
        s=Forced();messages=[];result=s.recover_session(messages.append)
        self.assertTrue(result['recovered']);self.assertEqual(s.starts,2)
        self.assertEqual(s.clicks,['Enter','Enter'])
        self.assertGreaterEqual(s.play_polls,28)
        self.assertTrue(any('自动重登' in line for line in messages))

    def test_welcome_enter_falls_back_to_verified_ok_once(self):
        class Welcome(BackgroundSession):
            def __init__(self):
                self.hwnd=1;self.stage='message';self.clicks=[]
                self.u=SimpleNamespace(PostMessageW=lambda *args:True)
            def check(self):pass
            def pause(self,seconds):pass
            def login_stage(self):return self.stage
            def recovery_message_matches(self,kind):return kind=='welcome'
            def control_info(self,offset,name):
                return {'bounds':(712,345,256,359) if name=='Window_MsgDlg' else (89,305,80,34)}
            def click(self,point):self.clicks.append(point);self.stage='playing'
        s=Welcome();s.press_login_confirm()
        self.assertEqual(s.stage,'playing');self.assertEqual(len(s.clicks),1)

    def test_missing_hero_actor_can_be_recalled_despite_stale_flag(self):
        class Hero(BackgroundSession):
            def __init__(self):self.base=0;self.ready=False;self.clicks=[]
            def hero_ready(self):return self.ready
            def uint(self,address):return {0x2bac2c:1000,1000:2000,2000+0x358:0}[address]
            def control_info(self,offset,name):return {'bounds':(0,0,20,20),'visible':True}
            def click(self,point):self.clicks.append(point);self.ready=True
            def wait(self,condition,timeout):assert condition()
        s=Hero();s.ensure_hero_available();self.assertTrue(s.ready)
        self.assertEqual(len(s.clicks),1)

    def test_selected_character_starts_without_reselecting(self):
        class Selected(BackgroundSession):
            def __init__(self):self.stage='character';self.clicks=[]
            def login_stage(self):return self.stage
            def control_info(self,offset,name):
                if name=='Button_scSelect1':raise AssertionError('must not reselect existing character')
                return {'bounds':(0,0,800,600) if name=='Window_SelectChr' else (370,460,60,30)}
            def click(self,point):self.clicks.append(point);self.stage='message'
            def wait(self,condition,timeout):self.assert_condition=condition();assert self.assert_condition
        s=Selected();self.assertEqual(s.enter_saved_character()['stage'],'message')
        self.assertEqual(len(s.clicks),1)

    def test_second_confirmation_is_handled_before_waiting_for_game(self):
        s=RecoveryFake();r=s.recover_session()
        self.assertEqual(s.clicks,['Enter'])
        self.assertEqual(r['transitions'],['character','message','loading','playing'])
        self.assertTrue(r['recovered']);self.assertTrue(s.cleared)
        self.assertFalse(s._recovering)

    def test_unknown_message_never_clicked(self):
        s=RecoveryFake();s.stage='message';s.message='unknown'
        with self.assertRaisesRegex(RuntimeError,'未识别'):s.recover_session()
        self.assertEqual(s.clicks,[]);self.assertTrue(s.cleared)

    def test_pending_item_prevents_resuming_sales(self):
        s=RecoveryFake();s.stage='playing';s.held_item=lambda:'木剑'
        with self.assertRaisesRegex(RuntimeError,'物品操作'):s.recover_session()

    def test_verified_death_rescans_bags_and_preserves_sale_count(self):
        s=RecoveryFake();s.sales=[];s.calls=0;s.check=lambda:None
        def route(progress):
            s.calls+=1;s.sales.append({'item':'木剑'})
            if s.calls==1:raise GameSessionLost('dead')
            return {'count':1,'remaining_plan':[]}
        s._dual_sale_route=route
        result=s.dual_sale_route()
        self.assertEqual(s.calls,2);self.assertEqual(result['count'],2)
        self.assertEqual(len(result['recoveries']),1)
        self.assertFalse(s._sale_recovery_enabled)

    def test_ordinary_sale_failure_never_retries_transaction(self):
        s=RecoveryFake();s.sales=[];s.check=lambda:None
        def route(progress):raise RuntimeError('inventory changed')
        s._dual_sale_route=route
        with self.assertRaisesRegex(RuntimeError,'inventory changed'):s.dual_sale_route()
        self.assertEqual(s.clicks,[])


if __name__=='__main__':unittest.main()
