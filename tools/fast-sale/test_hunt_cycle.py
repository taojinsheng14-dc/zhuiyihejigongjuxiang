import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from PIL import Image
from background_sale import BackgroundSession


class HuntTests(unittest.TestCase):
    def test_only_first_two_rows_are_room_candidates(self):
        s=object.__new__(BackgroundSession)
        s.client_size=lambda:(1680,1050);s.visible=lambda key:True
        s.bounds=lambda key:(0,0,432,261)
        image=Image.new('RGB',(1680,1050))
        template=Image.open(s.resource('ordinary-room.png')).convert('RGB')
        for y in (160,188,216):image.paste(template,(14,y))
        self.assertEqual(s.ordinary_room_points(image),[(39,168),(39,196)])

    def test_wrong_dialog_has_no_candidates(self):
        s=object.__new__(BackgroundSession);s.client_size=lambda:(1680,1050)
        s.visible=lambda key:True;s.bounds=lambda key:(0,0,416,176)
        self.assertEqual(s.ordinary_room_points(Image.new('RGB',(1680,1050))),[])

    def keyboard_session(self,slots):
        s=object.__new__(BackgroundSession);s.hwnd=1;s.check=lambda:None
        s.shortcut_inventory=lambda:slots;s.pause=lambda seconds:None;s.events=[]
        s.begin_background_input=Mock();s.clear_background_mouse=Mock()
        s.login_stage=lambda:'playing';s.held_item=lambda:'';s.sale_item=lambda:'';s.inflight_item=lambda:''
        s.wait_shortcut_modifiers_released=Mock()
        s.u=SimpleNamespace(IsIconic=lambda hwnd:False,GetAsyncKeyState=lambda vk:0,PostMessageW=Mock(return_value=True))
        return s

    def test_random_stone_in_one_is_skipped_for_town_stone_in_two(self):
        s=self.keyboard_session([{'key':1,'name':'随机传送石'},{'key':2,'name':'盟重传送石'}])
        s.press_return_hotkey()
        calls=s.u.PostMessageW.call_args_list
        self.assertEqual(len(calls),2)
        self.assertEqual([c.args[2] for c in calls],[0x32,0x32])
        self.assertEqual(s.events[-1]['key'],'2')

    def test_absent_town_stone_never_uses_other_shortcut(self):
        s=self.keyboard_session([{'key':1,'name':'随机传送石'}])
        with self.assertRaisesRegex(RuntimeError,'没有盟重'):s.press_return_hotkey()
        s.u.PostMessageW.assert_not_called()

    def test_random_only_uses_named_stone_and_releases_input(self):
        s=self.keyboard_session([{'key':1,'name':'随机传送卷'},{'key':5,'name':'盟重传送石'},
                                 {'key':6,'name':'随机传送石'}])
        s.press_named_hotkey(('随机传送石',),'random')
        self.assertEqual([call.args[2] for call in s.u.PostMessageW.call_args_list],[0x36,0x36])
        s.begin_background_input.assert_called_once();s.clear_background_mouse.assert_called_once()

    def test_random_does_not_substitute_scroll_or_town_stone(self):
        s=self.keyboard_session([{'key':1,'name':'随机传送卷'},{'key':5,'name':'盟重传送石'}])
        with self.assertRaisesRegex(RuntimeError,'没有随机传送石'):s.press_named_hotkey(('随机传送石',),'random')
        s.u.PostMessageW.assert_not_called()

    def test_missing_stone_blocks_paid_room_entry(self):
        s=object.__new__(BackgroundSession);s.ensure_hero_available=lambda:None
        s.shortcut_inventory=lambda:[];s.open_hunt_menu=Mock()
        with self.assertRaisesRegex(RuntimeError,'未进入挂机房'):s.enter_ordinary_room()
        s.open_hunt_menu.assert_not_called()

    def test_restarting_full_in_town_clears_bags_before_entering_room(self):
        s=object.__new__(BackgroundSession);events=[]
        s.ensure_hero_available=lambda:events.append('hero_ready')
        s.check=lambda:None;s.dismiss_town_hunt_notice=lambda:False
        s.login_stage=lambda:'playing';s.base=0;s.uint=lambda address:0
        s.read=lambda address,size:b'town';s._hunting_header=b'town'
        s.dual_bag_status=lambda:{'main_free':0,'hero_free':0}
        s.inventory=lambda:['木剑']*40;s.hero_inventory=lambda:['木剑']*40;s.npcs=lambda:[]
        s.in_mengzhong_return_area=lambda:True
        s.return_with_hotkey=lambda progress:events.append('verify_town')
        s.dual_sale_route=lambda progress:events.append('sell')
        s.enter_ordinary_room=lambda progress:events.append('enter')
        s.monitor_bags=lambda *args,**kwargs:{'status':'monitor_timeout'}
        s.hunt_cycle(seconds=1)
        self.assertEqual(events,['hero_ready','sell','enter'])

    def test_resume_in_shop_sells_remaining_items_before_reentry(self):
        s=object.__new__(BackgroundSession);events=[]
        s.ensure_hero_available=lambda:events.append('hero_ready')
        s.check=lambda:None;s.dismiss_town_hunt_notice=lambda:False;s.login_stage=lambda:'playing'
        s.base=0;s.uint=lambda address:0;s.read=lambda address,size:b'shop'
        s.dual_bag_status=lambda:{'main_free':39,'hero_free':40}
        s.inventory=lambda:['短剑']+['']*39;s.hero_inventory=lambda:['']*40
        s.npcs=lambda:[{'name':'铁匠铺老板'}]
        s.return_with_hotkey=lambda progress:events.append('unnecessary_stone')
        s.dual_sale_route=lambda progress:events.append('sell')
        s.enter_ordinary_room=lambda progress:events.append('enter')
        s.monitor_bags=lambda *args,**kwargs:{'status':'monitor_timeout'}
        s.hunt_cycle(seconds=1)
        self.assertEqual(events,['hero_ready','sell','enter'])

    def test_resume_existing_room_does_not_enter_again(self):
        s=object.__new__(BackgroundSession)
        s.login_stage=lambda:'playing';s.npcs=lambda:[]
        s.in_mengzhong_return_area=lambda:False
        s.held_item=lambda:'';s.sale_item=lambda:'';s.inflight_item=lambda:''
        s.base=0;s.uint=lambda address:0;s.read=lambda address,size:b'room'
        s.check=lambda:None;s.dismiss_town_hunt_notice=lambda:False
        s.enter_ordinary_room=Mock();s.return_with_hotkey=Mock();s.dual_sale_route=Mock()
        s.monitor_bags=lambda *args,**kwargs:{'status':'monitor_timeout'}
        result=s.hunt_cycle(seconds=1,resume_current_room=True)
        self.assertEqual(result['status'],'monitor_timeout')
        self.assertEqual(s._hunting_header,b'room')
        s.enter_ordinary_room.assert_not_called()
        s.return_with_hotkey.assert_not_called();s.dual_sale_route.assert_not_called()

    def test_resume_rejects_town_before_input(self):
        s=object.__new__(BackgroundSession)
        s.login_stage=lambda:'playing';s.in_mengzhong_return_area=lambda:True
        s.enter_ordinary_room=Mock()
        with self.assertRaisesRegex(RuntimeError,'城内或商店'):
            s.hunt_cycle(seconds=1,resume_current_room=True)
        s.enter_ordinary_room.assert_not_called()


if __name__=='__main__':unittest.main()
