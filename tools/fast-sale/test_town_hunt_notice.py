import unittest
from unittest.mock import Mock
from background_sale import BackgroundSession


class TownNoticeTests(unittest.TestCase):
    def session(self):
        s=object.__new__(BackgroundSession)
        s.stage='message'
        s.login_stage=lambda:s.stage
        s.recovery_message_matches=lambda kind:kind=='town_hunt_forbidden'
        s.in_mengzhong_return_area=lambda:True
        s.held_item=lambda:'';s.sale_item=lambda:'';s.inflight_item=lambda:''
        s.control_info=lambda offset,name:{'bounds':(614,435,452,179) if offset==0x3d8 else (330,126,80,34),'visible':True}
        s.unique_npc=Mock(side_effect=RuntimeError('NPC not loaded'))
        def click(point):
            self.assertTrue(s._dismissing_town_notice)
            self.assertFalse(s.dismiss_town_hunt_notice())
            s.stage='playing'
        s.click=Mock(side_effect=click)
        s.wait=lambda condition,timeout:self.assertTrue(condition())
        return s

    def test_normal_notice_closes_once_before_npc_load_without_relogin(self):
        s=self.session();s.recover_session=Mock();s._hunt_recoveries=2
        self.assertTrue(s.dismiss_town_hunt_notice())
        s.click.assert_called_once_with((984.0,578.0))
        s.unique_npc.assert_not_called();s.recover_session.assert_not_called()
        self.assertEqual(s._hunt_recoveries,2)
        self.assertFalse(s._dismissing_town_notice)
        self.assertFalse(s.dismiss_town_hunt_notice())

    def test_return_window_fallback_clicks_button_without_any_enter(self):
        s=self.session();s.recovery_message_matches=lambda kind:False;s._return_prompt_pending=True
        s.u=Mock()
        self.assertTrue(s.dismiss_town_hunt_notice())
        s.click.assert_called_once();s.u.PostMessageW.assert_not_called()

    def test_return_settle_defers_session_guard_and_restores_it(self):
        s=self.session();s.stage='loading'
        s.check=lambda:self.assertTrue(s._dismissing_town_notice)
        def pause(seconds):
            self.assertTrue(s._dismissing_town_notice);s.stage='playing'
        s.pause=pause
        s.settle_return_ui()
        self.assertFalse(s._dismissing_town_notice)
        s.click.assert_not_called()

    def test_return_fallback_rejects_other_dialog_dimensions(self):
        s=self.session();s.recovery_message_matches=lambda kind:False;s._return_prompt_pending=True
        s.control_info=lambda offset,name:{'bounds':(0,0,256,359),'visible':True}
        self.assertFalse(s.dismiss_town_hunt_notice());s.click.assert_not_called()

    def test_vanished_prompt_never_sends_input(self):
        s=self.session();s.control_info=lambda offset,name:{'bounds':(0,0,452,179),'visible':False}
        with self.assertRaisesRegex(RuntimeError,'确认按钮未显示'):s.dismiss_town_hunt_notice()
        s.click.assert_not_called()

    def test_unknown_notice_is_not_clicked(self):
        s=self.session();s.recovery_message_matches=lambda kind:False
        self.assertFalse(s.dismiss_town_hunt_notice());s.click.assert_not_called()

    def test_wrong_map_and_pending_item_are_not_clicked(self):
        s=self.session();s.in_mengzhong_return_area=lambda:False
        with self.assertRaisesRegex(RuntimeError,'地图未核对'):s.dismiss_town_hunt_notice()
        s.click.assert_not_called()
        s=self.session();s.held_item=lambda:'凝霜'
        with self.assertRaisesRegex(RuntimeError,'物品操作'):s.dismiss_town_hunt_notice()
        s.click.assert_not_called()

    def test_failed_confirmation_is_not_retried_and_guard_is_restored(self):
        s=self.session();s.wait=Mock(side_effect=RuntimeError('timeout'))
        with self.assertRaisesRegex(RuntimeError,'timeout'):s.dismiss_town_hunt_notice()
        s.click.assert_called_once();self.assertFalse(s._dismissing_town_notice)


if __name__=='__main__':unittest.main()
