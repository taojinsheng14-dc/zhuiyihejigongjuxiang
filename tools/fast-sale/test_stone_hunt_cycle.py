import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PIL import Image

import stone_hunt_cycle as cycle
from current_map_hunt import STONE_HEADER


def row(text,score=.99):return {'text':text,'score':score,'box':[[10,10],[70,10],[70,28],[10,28]]}


class StoneCycleTests(unittest.TestCase):
    def test_exact_target_wins_and_other_city_or_floor_never_matches(self):
        label,_=cycle.choose_link([row('危险区域'),row('前往石墓五层移动'),row('前往魔龙城移动')],set())
        self.assertEqual(label,'石墓五层')
        for text in ('魔龙城','石墓七层','石墓阵','石墓五层100元宝','石墓五屋'):
            with self.subTest(text=text),self.assertRaises(RuntimeError):cycle.choose_link([row(text)],set())

    def test_low_confidence_duplicate_and_revisited_category_stop(self):
        for rows,visited in (([row('石墓五层',.8)],set()),([row('石墓五层')]*2,set()),([row('危险区域')],{'危险区域'})):
            with self.assertRaises(RuntimeError):cycle.choose_link(rows,visited)

    def test_non_yellow_or_incomplete_link_is_not_clicked(self):
        with self.assertRaises(RuntimeError):cycle.verified_link_point(Image.new('RGB',(100,50),'white'),row('石墓五层'))
        image=Image.new('RGB',(100,50),'black')
        for x in range(20,60):image.putpixel((x,18),(255,255,0))
        self.assertEqual(cycle.verified_link_point(image,row('石墓五层')),(39,18))

    def test_setting_preserves_existing_avoidance_and_defaults_off(self):
        import json
        with tempfile.TemporaryDirectory() as folder,patch('instance_context.runtime_root',return_value=Path(folder)):
            self.assertFalse(cycle.enabled())
            path=cycle.settings_path();path.parent.mkdir();path.write_text('{"avoid_loaded_players":true}',encoding='utf8')
            cycle.save_enabled(True)
            self.assertTrue(cycle.enabled());self.assertTrue(json.loads(path.read_text())['avoid_loaded_players'])

    def session(self,full=True):
        order=[];full_bag=['木剑']*39+[''];empty_bag=['']*40
        s=SimpleNamespace(check=Mock(),clear_background_mouse=Mock(),hero_ready=lambda:True,
            inventory=lambda:full_bag if full else empty_bag,hero_inventory=lambda:full_bag,
            dual_bag_status=lambda:{'main_free':1,'hero_free':1})
        s.return_with_hotkey=Mock(side_effect=lambda *a,**k:order.append('return'))
        def sale(*a,**k):
            order.append('sale');self.assertFalse(k['allow_recovery'])
            s.inventory=lambda:empty_bag;s.hero_inventory=lambda:empty_bag
            return {'count':78}
        s.dual_sale_route=Mock(side_effect=sale)
        s.verify_sale_complete=Mock(side_effect=lambda:order.append('verify_sale'))
        return s,order

    def test_full_bags_return_sell_verify_then_target_map_before_next_hunt(self):
        s,order=self.session()
        def hunt(*a,**k):
            order.append('hunt');self.assertFalse(k['allow_cycle']);self.assertTrue(k['return_when_full'])
            return {'status':'bags_full'} if order.count('hunt')==1 else {'status':'external_position_change'}
        with patch('current_map_hunt.run',side_effect=hunt),patch('current_map_hunt.header',return_value=STONE_HEADER),patch.object(cycle,'settled'),patch.object(cycle,'record'),patch.object(cycle,'enter_stone_five',side_effect=lambda *a:order.append('enter')):
            result=cycle.run(s)
        self.assertEqual(order,['hunt','return','sale','verify_sale','enter','hunt'])
        self.assertEqual(result['cycles'],1);s.clear_background_mouse.assert_called_once()

    def test_false_full_signal_and_sale_failure_never_enter(self):
        for full in (False,True):
            s,order=self.session(full)
            if full:s.verify_sale_complete.side_effect=RuntimeError('pending sale')
            with patch('current_map_hunt.run',return_value={'status':'bags_full'}),patch('current_map_hunt.header',return_value=STONE_HEADER),patch.object(cycle,'settled'),patch.object(cycle,'record'),patch.object(cycle,'enter_stone_five') as enter:
                with self.assertRaises(RuntimeError):cycle.run(s)
                enter.assert_not_called()
            if not full:s.return_with_hotkey.assert_not_called();s.dual_sale_route.assert_not_called()

    def test_other_stop_reason_does_not_trigger_return_or_sale(self):
        s,order=self.session()
        with patch('current_map_hunt.run',return_value={'status':'pickup_unverified'}),patch('current_map_hunt.header',return_value=STONE_HEADER),patch.object(cycle,'settled'),patch.object(cycle,'record'):
            self.assertEqual(cycle.run(s)['status'],'pickup_unverified')
        self.assertEqual(order,[])

    def test_wrong_start_map_never_hunts_or_returns(self):
        s,order=self.session()
        with patch('current_map_hunt.header',return_value=bytes(52)),patch.object(cycle,'settled'),patch.object(cycle,'record'),patch('current_map_hunt.run') as hunt:
            with self.assertRaises(RuntimeError):cycle.run(s)
            hunt.assert_not_called()
        self.assertEqual(order,[])
