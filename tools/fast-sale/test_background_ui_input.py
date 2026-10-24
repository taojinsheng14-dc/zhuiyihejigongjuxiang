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


class NpcOpeningInputTests(unittest.TestCase):
    def session(self,opens_on_down=True,read_error=False):
        messages=[];state={'merchant':False}
        s=BackgroundSession.__new__(BackgroundSession)
        def send(hwnd,message,flags,position,*args):
            messages.append((message,flags,position))
            if message==0x201 and opens_on_down:state['merchant']=True
            # Simulate the reported overlap: a held move or up at the
            # actor coordinate is also the new menu's paid destination.
            if state['merchant'] and message in (0x200,0x202) and position!=0xffffffff and (flags==1 or message==0x202):
                state['wrong_destination']=True
            return 1
        s.u=SimpleNamespace(IsIconic=lambda hwnd:False,SendMessageTimeoutW=send,
            GetCursorPos=lambda p:True,ClientToScreen=lambda h,p:True,
            SetThreadDpiAwarenessContext=lambda c:0,GetAsyncKeyState=lambda key:0)
        s.hwnd=1;s.events=[];s.check=lambda:None;s.client_size=lambda:(1280,800)
        s.physical_client_size=lambda:(1920,1200);s.player=lambda:(332,324)
        s.begin_background_input=lambda:None;s.clear_background_mouse=lambda:None;s.pause=lambda seconds:None
        def visible(key):
            if read_error:raise RuntimeError('read failed')
            return state['merchant']
        s.visible=visible
        return s,messages,state

    def test_open_on_down_does_not_select_overlapping_menu_on_release(self):
        from unittest.mock import patch
        s,messages,state=self.session()
        with patch('background_sale.time.sleep'):s.click_npc_actor((64,137))
        self.assertTrue(state['merchant']);self.assertNotIn('wrong_destination',state)
        self.assertEqual([m for m in messages if m[0]==0x201],[(0x201,1,(206<<16)|96)])
        self.assertEqual(messages[-2:],[(0x200,0,0xffffffff),(0x202,0,0xffffffff)])
        self.assertFalse(s._opening_npc_actor)

    def test_menu_not_open_yet_preserves_actor_release_without_held_move(self):
        from unittest.mock import patch
        s,messages,state=self.session(opens_on_down=False)
        with patch('background_sale.time.sleep'):s.click_npc_actor((64,137))
        self.assertEqual(messages[-1],(0x202,0,(206<<16)|96))
        self.assertFalse(any(m[0]==0x200 and m[1]==1 for m in messages))

    def test_visibility_read_failure_releases_outside_and_restores_scope(self):
        from unittest.mock import patch
        s,messages,state=self.session(read_error=True)
        with patch('background_sale.time.sleep'):
            with self.assertRaisesRegex(RuntimeError,'read failed'):s.click_npc_actor((64,137))
        self.assertEqual(messages[-1],(0x202,0,0xffffffff));self.assertFalse(s._opening_npc_actor)
