import unittest
from types import SimpleNamespace

from background_sale import BackgroundSession


class BackgroundUIInputTests(unittest.TestCase):
    def test_ui_click_waits_for_each_message_before_clearing_without_movement_poll(self):
        order=[]
        s=BackgroundSession.__new__(BackgroundSession)
        def send(hwnd,message,flags,*args):
            order.append(message)
            return 1
        s.u=SimpleNamespace(IsIconic=lambda hwnd:False,SendMessageTimeoutW=send,
                            GetCursorPos=lambda p:True,ClientToScreen=lambda h,p:True,
                            SetThreadDpiAwarenessContext=lambda c:0,GetAsyncKeyState=lambda key:0)
        s.hwnd=1;s.events=[]
        s.check=lambda:None;s.client_size=lambda:(1680,1050)
        s.physical_client_size=s.client_size;s.player=lambda:(3,11)
        s.begin_background_input=lambda:order.append('begin')
        s.clear_background_mouse=lambda:order.append('clear')
        s.pause=lambda seconds:None
        s.click((463,58))
        self.assertEqual(order[:9],['begin',0x6,0x7,0x200,0x200,0x201,0x200,0x202,'clear'])
        self.assertEqual(s.events[0]['input'],'SendMessageTimeout')
        self.assertNotIn('positions',s.events[0])

    def test_recovery_ui_click_does_not_require_player_actor(self):
        s=BackgroundSession.__new__(BackgroundSession)
        def send(*args):return 1
        s.u=SimpleNamespace(IsIconic=lambda hwnd:False,SendMessageTimeoutW=send,
                            GetCursorPos=lambda p:True,ClientToScreen=lambda h,p:True,
                            SetThreadDpiAwarenessContext=lambda c:0,GetAsyncKeyState=lambda key:0)
        s.hwnd=1;s.events=[];s._recovering=True
        s.check=lambda:None;s.client_size=lambda:(1680,1050)
        s.physical_client_size=s.client_size
        def unavailable():raise RuntimeError('no actor')
        s.player=unavailable
        s.begin_background_input=lambda:None;s.clear_background_mouse=lambda:None
        s.pause=lambda seconds:None
        s.click((100,100))
        self.assertIsNone(s.events[-1]['position_before'])
        with self.assertRaisesRegex(RuntimeError,'no actor'):
            s.background_mouse((100,100),track_movement=True)
