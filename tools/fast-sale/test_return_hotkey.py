import unittest
from background_sale import BackgroundSession


class ReturnFake(BackgroundSession):
    def __init__(self):
        self.key_presses=0;self.arrives=True;self.in_town=False;self.verified=False
        self.base=0
    def login_stage(self):return 'playing'
    def held_item(self):return ''
    def sale_item(self):return ''
    def inflight_item(self):return ''
    def close_panels(self):pass
    def npcs(self):return [{'name':'盟重老兵','map':(320,320)}] if self.in_town else []
    def unique_npc(self,name,xy):
        if not self.in_town:raise RuntimeError('not in town')
        self.verified=True
    def uint(self,address):return 0
    def read(self,address,size):return b'town' if self.in_town else b'dungeon'
    def press_return_hotkey(self):
        self.key_presses+=1
        if self.arrives:self.in_town=True
    def wait(self,condition,timeout):
        if not condition():raise RuntimeError('return not confirmed')
    def stable_player(self):return self.player()
    def player(self):return (331,332)
    def in_mengzhong_return_area(self):return self.in_town


class ReturnTests(unittest.TestCase):
    def test_intermediate_map_change_waits_for_verified_town_before_notice(self):
        s=ReturnFake()
        s.press_return_hotkey=lambda:setattr(s,'key_presses',s.key_presses+1)
        def wait(condition,timeout):
            self.assertTrue(s._dismissing_town_notice)
            self.assertFalse(condition())
            s.in_town=True
            self.assertTrue(condition())
        s.wait=wait
        s.return_with_hotkey()
        self.assertEqual(s.key_presses,1)
        self.assertTrue(s.verified)
        self.assertFalse(s._dismissing_town_notice)

    def test_return_from_same_map_wilderness(self):
        s=ReturnFake();s.read=lambda address,size:b'mengzhong'
        r=s.return_with_hotkey()
        self.assertEqual(s.key_presses,1)
        self.assertTrue(r['town_verified']);self.assertTrue(s.verified)

    def test_single_use_is_followed_by_verified_town(self):
        s=ReturnFake();r=s.return_with_hotkey()
        self.assertEqual(s.key_presses,1);self.assertTrue(s.verified)
        self.assertTrue(r['town_verified'])

    def test_failed_return_is_never_retried(self):
        s=ReturnFake();s.arrives=False
        with self.assertRaisesRegex(RuntimeError,'not confirmed'):s.return_with_hotkey()
        self.assertEqual(s.key_presses,1);self.assertFalse(s.verified)
        self.assertFalse(s._dismissing_town_notice)

    def test_already_in_town_does_not_consume_stone(self):
        s=ReturnFake();s.in_town=True;r=s.return_with_hotkey()
        self.assertEqual(s.key_presses,0);self.assertFalse(r['hotkey_sent'])

    def test_pending_item_blocks_return_key(self):
        s=ReturnFake();s.held_item=lambda:'裁决之杖'
        with self.assertRaisesRegex(RuntimeError,'物品操作'):s.return_with_hotkey()
        self.assertEqual(s.key_presses,0)

    def test_monitor_never_starts_sales_if_return_failed(self):
        s=ReturnFake();s.arrives=False;s.ensure_hero_available=lambda:None
        s.hero_ready=lambda:True;s.check=lambda:None
        s.dual_bag_status=lambda:{'main_free':0,'hero_free':0,'both_full':True}
        s.handle_full_bags=lambda:{'return_required':True,'transfers':[]}
        s.dual_sale_route=lambda *args:self.fail('must not sell before confirmed return')
        with self.assertRaisesRegex(RuntimeError,'not confirmed'):
            s.monitor_bags(seconds=1,auto_return=True)
        self.assertEqual(s.key_presses,1)

    def test_successful_monitor_stops_after_sales_without_paid_map_entry(self):
        s=ReturnFake();s.ensure_hero_available=lambda:None;s.hero_ready=lambda:True;s.check=lambda:None
        s.dual_bag_status=lambda:{'main_free':0,'hero_free':0,'both_full':True}
        s.handle_full_bags=lambda:{'return_required':True,'transfers':[]}
        s.dual_sale_route=lambda *args:{'count':79,'remaining_plan':[]}
        r=s.monitor_bags(seconds=1,auto_return=True)
        self.assertEqual(r['status'],'sale_complete');self.assertEqual(s.key_presses,1)
        self.assertFalse(r['automatic_map_entry'])


if __name__=='__main__':unittest.main()
