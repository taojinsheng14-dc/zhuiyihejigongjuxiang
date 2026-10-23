import unittest
from unittest.mock import patch
from PIL import Image
from background_sale import BackgroundSession
from fast_sale import grid_center, button_center


class Fake(BackgroundSession):
    def __init__(self):
        self.items = [''] * 40
        self.items[9] = '木剑'
        self.held = self.pending = ''
        self.events = []
        self.wrong_pickup = False
        self.alter_other = False
        self.sales = []
    def check(self): pass
    def inventory(self): return self.items.copy()
    def held_item(self): return self.held
    def sale_item(self): return self.pending
    def visible(self, key): return True
    def hero_covers(self, box): return False
    def inflight_item(self): return ''
    def pause(self, seconds): pass
    def client_size(self): return (1024, 768)
    def bounds(self, key):
        return {'bag': (416, 0, 352, 295), 'grid': (29, 42, 288, 160),
                'sell': (260, 176, 140, 181), 'spot': (28, 67, 61, 52),
                'ok': (85, 150, 24, 13), 'merchant': (0, 0, 416, 176)}[key]
    def wait(self, condition, timeout=1.5):
        if not condition(): raise RuntimeError('状态不匹配')
    def click(self, point):
        self.events.append(point)
        centers = [grid_center(self.bounds('bag'), self.bounds('grid'), i) for i in range(40)]
        if point in centers:
            index = centers.index(point)
            self.held = '裁决之杖' if self.wrong_pickup else self.items[index]
            self.items[index] = ''
        elif point == button_center(self.bounds('sell'), self.bounds('spot')):
            self.pending, self.held = self.held, ''
            if self.alter_other: self.items[1] = '变化的物品'
        elif point == button_center(self.bounds('sell'), self.bounds('ok')):
            self.pending = ''


class BackgroundTests(unittest.TestCase):
    def test_overlapping_bag_stops_background_sale_before_any_item_click(self):
        s=Fake();original=s.bounds
        s.bounds=lambda key:(0,60,352,295) if key=='bag' else original(key)
        with self.assertRaisesRegex(RuntimeError,'需要前台'):s.sell_category('武器')
        self.assertEqual(s.events,[])
    def test_overlapping_bag_is_relocated_before_foreground_sale(self):
        from background_sale import ForegroundSession
        s=object.__new__(ForegroundSession);bag=[0,60,352,295]
        s.visible=lambda key:True;s.held_item=lambda:''
        s.bounds=lambda key:tuple(bag) if key=='bag' else {'sell':(260,176,140,181),'spot':(28,67,61,52),'ok':(85,150,24,13)}[key]
        movements=[]
        def drag(start,end):movements.append((start,end));bag[:]=[416,0,352,295]
        s.drag_ui=drag;s.write_stats=lambda event:None
        self.assertTrue(s.arrange_sale_layout());self.assertEqual(len(movements),1)
        self.assertFalse(s.arrange_sale_layout())
    def test_bag_covering_only_ok_is_also_rejected_before_pickup(self):
        s=Fake();original=s.bounds
        s.bounds=lambda key:(80,300,352,295) if key=='bag' else original(key)
        with self.assertRaisesRegex(RuntimeError,'需要前台'):s.sell_category('武器')
        self.assertEqual(s.events,[])
    def test_pending_sale_resume_confirms_once_and_logs_actual_gold(self):
        s=Fake();s.items=['']*40;s.pending='木剑'
        s.unique_npc=lambda *args:{'name':'铁匠铺老板'}
        s.currency_snapshot=lambda:{'gold':100 if s.pending else 150,'yuanbao':109}
        records=[];s.write_stats=records.append
        result=s.resume_pending_sale()
        self.assertTrue(result['resumed']);self.assertEqual(result['gold_change'],50)
        self.assertEqual(len(s.events),1)
        self.assertEqual([row['event'] for row in records],['sale_item','sale_round'])
    def test_pending_rare_equipment_is_never_confirmed(self):
        s=Fake();s.pending='裁决之杖'
        with self.assertRaises(RuntimeError):s.resume_pending_sale()
        self.assertEqual(s.events,[])
    def test_empty_pending_sale_never_clicks_confirmation(self):
        s=Fake();result=s.resume_pending_sale()
        self.assertFalse(result['resumed']);self.assertEqual(s.events,[])
    def test_verified_item_submits_exactly_once(self):
        s = Fake()
        result = s.submit_one('木剑')
        self.assertEqual(len(s.events), 3)
        self.assertIn('服务器成交需核对', result['status'])
    def test_wrong_held_item_stops_before_placing(self):
        s = Fake(); s.wrong_pickup = True
        with self.assertRaises(RuntimeError): s.submit_one('木剑')
        self.assertEqual(len(s.events), 1)
    def test_other_slot_change_prevents_confirmation(self):
        s = Fake(); s.alter_other = True
        with self.assertRaises(RuntimeError): s.submit_one('木剑')
        self.assertEqual(len(s.events), 2)
    def test_existing_pending_item_is_never_overwritten(self):
        s = Fake(); s.pending = '裁决之杖'
        with self.assertRaises(RuntimeError): s.submit_one('木剑')
        self.assertEqual(s.events, [])
    def test_unsupported_resolution_stops_without_clicking(self):
        s = Fake(); s.client_size = lambda: (800, 600)
        with self.assertRaises(RuntimeError): s.teleport_weapon_sale()
        self.assertEqual(s.events, [])
    def test_new_client_size_uses_live_menu_origin_without_scaling_offsets(self):
        s=Fake();s.client_size=lambda:(1707,1067)
        original=s.bounds
        s.bounds=lambda key:(600,400,416,176) if key=='merchant' else original(key)
        profile=s.profile();entry=profile['menus']['sell_weapon']
        self.assertEqual(profile['coordinate_basis'],'live_control_origin_and_verified_size')
        image=Image.new('RGB',(1707,1067))
        image.paste(Image.open(s.resource(entry['template'])),(600+entry['box'][0],400+entry['box'][1]))
        s.capture_client=lambda:image
        self.assertTrue(s.menu_matches('sell_weapon'))
        self.assertFalse(s.menu_matches('weapon_transfer'))

    def test_changed_control_size_is_rejected_on_new_client_size(self):
        s=Fake();s.client_size=lambda:(1707,1067);original=s.bounds
        s.bounds=lambda key:(0,0,500,300) if key=='bag' else original(key)
        with self.assertRaisesRegex(RuntimeError,'网格尺寸'):s.profile()
    def test_missing_item_stops_whole_route_without_clicking(self):
        s = Fake(); s.items[9] = ''
        with self.assertRaises(RuntimeError): s.teleport_weapon_sale()
        self.assertEqual(s.events, [])
    def test_menu_template_accepts_only_matching_link(self):
        s = Fake(); s.hwnd = 123
        profile = s.profile()
        entry = profile['menus']['sell_weapon']
        image = Image.new('RGB', (1024, 768))
        image.paste(Image.open(s.resource(entry['template'])), tuple(entry['box'][:2]))
        with patch('PIL.ImageGrab.grab', return_value=image):
            self.assertTrue(s.menu_matches('sell_weapon'))
            self.assertFalse(s.menu_matches('weapon_transfer'))

    def test_batch_sells_duplicates_and_preserves_nonweapons(self):
        s = Fake()
        s.items = ['破魂', '青铜头盔', '裁决之杖', '凝霜', '破魂', '木剑'] + [''] * 34
        result = s.sell_all_weapons()
        self.assertEqual(result['count'], 4)
        self.assertEqual(s.items[:6], ['', '青铜头盔', '裁决之杖', '', '', ''])
        self.assertEqual(len(s.events), 12)

    def test_batch_stops_after_a_rejected_or_changed_inventory(self):
        s = Fake(); s.items[9] = '破魂'; s.items[10] = '凝霜'; s.alter_other = True
        with self.assertRaises(RuntimeError): s.sell_all_weapons()
        self.assertEqual(len(s.events), 2)
        self.assertEqual(s.items[10], '凝霜')

    def test_inflight_timeout_never_submits_next_weapon(self):
        s = Fake(); s.items[9] = s.items[10] = '破魂'
        s.inflight_item = lambda: '破魂' if s.events else ''
        s.control_info=lambda *args:(_ for _ in ()).throw(RuntimeError('刷新控件未验证'))
        with self.assertRaises(RuntimeError): s.sell_all_weapons()
        self.assertEqual(len(s.events), 3)
        self.assertEqual(s.items[10], '破魂')

    def test_classification_and_projection(self):
        from equipment import CATEGORIES, WEAPONS, project_tile
        self.assertTrue({'木剑','铁剑','短剑','青铜斧'}.issubset(WEAPONS))
        self.assertEqual(CATEGORIES['魔力手镯'], '手镯')
        self.assertNotIn('裁决之杖', CATEGORIES)
        self.assertEqual(project_tile((7,9), (512,241), (5,9)), (416,241))
        self.assertEqual(project_tile((321,321), (512,241), (320,320)), (464,209))

    def test_each_category_sells_only_its_exact_whitelist(self):
        samples={'手镯':'黑檀手镯','戒指':'珊瑚戒指','项链':'竹笛','衣服':'魔法长袍(女)','头盔':'道士头盔'}
        for category,name in samples.items():
            s=Fake();s.items=[name,'裁决之杖','祝福油','木剑']+['']*36
            s.active_merchant='已核对商人'
            result=s.sell_category(category,merchant_name='已核对商人')
            self.assertEqual(result['count'],1)
            self.assertEqual(s.items[:4],['','裁决之杖','祝福油','木剑'])

    def test_wrong_merchant_never_picks_up_item(self):
        s=Fake();s.items[9]='珊瑚戒指';s.active_merchant='手镯店老板'
        with self.assertRaises(RuntimeError):s.sell_category('戒指',merchant_name='戒指店老板')
        self.assertEqual(s.events,[])

    def test_empty_category_selection_does_nothing(self):
        s=Fake()
        result=s.run_shop_route([])
        self.assertEqual(result['count'],0)
        self.assertEqual(s.events,[])

    def test_uncalibrated_helmet_route_stops_before_travel(self):
        s=Fake();s.items[9]='道士头盔'
        with self.assertRaisesRegex(RuntimeError,'尚未校准'):s.run_shop_route(['头盔'])
        self.assertEqual(s.events,[])


class FakeWalk(Fake):
    def __init__(self):
        super().__init__()
        self.base = 0
        self.xy = (327,319)
        self.world = False
        self.tabs = 0
        self.blocked = False
    def player(self): return self.xy
    def stable_player(self): return self.xy
    def visible(self, key): return False
    def press_tab(self):
        self.tabs += 1
        self.world = self.tabs == 3
    def control_info(self, offset, name):
        return {'visible': self.world, 'bounds': {
            'Window_TravelMap': (205,99,574,386),
            'Button_TravelMap': (35,82,502,287),
            'BtnCloseTravelMap': (554,35,16,23)}[name]}
    def uint(self, address):
        return {0x2ba608:0x1000, 0x1000:0x2000, 0x2048:0x3000}.get(address,0 if self.blocked else 0x14000)
    def read(self, address, size):
        import struct
        from equipment import project_tile
        if address == 0x2004: return struct.pack('<HH',1000,800)
        if address == 0x517c: return struct.pack('<2i',*project_tile(self.xy,(512,241),(320,320)))
        return b'\1' if self.blocked else b'\0'
    def click(self, point):
        self.events.append(point)
        if point == (767,145.5): self.world = False
        else: self.xy = (round((point[0]-240)*1000/502),round((point[1]-181)*800/287))


class WalkTests(unittest.TestCase):
    def test_legacy_entry_uses_bounded_route_without_world_map(self):
        from unittest.mock import Mock
        s=FakeWalk();npc={'name':'盟重老兵','map':(320,320),'address':0x5000}
        s.close_panels=Mock();s.locate_mengzhong_veteran=Mock(return_value=npc);s.approach_veteran_running=Mock()
        s.walk_near_veteran(npc)
        s.approach_veteran_running.assert_called_once_with(npc,unittest.mock.ANY)
        self.assertEqual(s.tabs,0);self.assertEqual(s.events,[])
    def test_no_walk_outside_nearby_range(self):
        s=FakeWalk();s.xy=(400,400)
        with self.assertRaises(RuntimeError):
            s.walk_near_veteran({'name':'盟重老兵','map':(320,320),'address':0x5000})
        self.assertEqual(s.tabs,0)
        self.assertEqual(s.events,[])
    def test_missing_grid_never_falls_back_to_world_map(self):
        from unittest.mock import Mock
        s=FakeWalk();s.close_panels=Mock();s.locate_mengzhong_veteran=Mock(side_effect=RuntimeError('地图不可用'))
        with self.assertRaisesRegex(RuntimeError,'地图不可用'):
            s.walk_near_veteran({'name':'盟重老兵','map':(320,320),'address':0x5000})
        self.assertEqual(s.tabs,0);self.assertEqual(s.events,[])


if __name__ == '__main__': unittest.main()

class DualBagCategoryTests(unittest.TestCase):
    def test_hero_weapons_are_sold_at_same_merchant_and_rare_items_remain(self):
        class DualFake(Fake):
            def __init__(self):
                super().__init__()
                self.items=['裁决之杖','木剑','木剑','木剑']+['']*36
                self.hero=['木剑','思贝儿手镯','木剑']+['']*37
                self._selling_both_bags=True;self.active_merchant='铁匠铺老板'
            def hero_inventory(self):return self.hero.copy()
            def open_hero_bag(self):pass
            def close_panels(self):pass
            def transfer_bag_item(self,source,index):
                self.items[self.items.index('')]=self.hero[index];self.hero[index]=''
            def unique_npc(self,name):return {'name':name}
            def open_npc(self,npc):self.active_merchant=npc['name']
            def menu_click(self,name):self.last_menu=name
        s=DualFake();result=s.sell_category('武器')
        self.assertEqual(result['count'],5)
        self.assertEqual(len(s.sales),5)
        self.assertEqual([x for x in s.items if x],['裁决之杖'])
        self.assertEqual([x for x in s.hero if x],['思贝儿手镯'])
        self.assertEqual(s.last_menu,'sell_weapon')
