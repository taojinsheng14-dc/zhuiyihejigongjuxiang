import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from background_sale import BackgroundSession


class FinishHuntTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.path=self.root/'outputs'/'挂机统计'/'本轮清包后停止.json'
        self.path.parent.mkdir(parents=True)
        self.root_patch=patch('background_sale.instance_context.runtime_root',return_value=self.root)
        self.root_patch.start();self.addCleanup(self.root_patch.stop)
        self.slot_patch=patch('background_sale.instance_context.slot',return_value='1')
        self.slot_patch.start();self.addCleanup(self.slot_patch.stop)
        self.s=object.__new__(BackgroundSession);s=self.s
        s.reader=SimpleNamespace(pid=123)
        s.inventory=lambda:[''];s.hero_inventory=lambda:['']
        s.held_item=lambda:'';s.sale_item=lambda:'';s.inflight_item=lambda:''
        s.close_panels=Mock();s.currency_snapshot=lambda:{'gold':100,'yuanbao':20}
        s.base=0;s.uint=lambda address:0;s.read=lambda address,size:b'town'
        s.player=lambda:(330,330)
        s.prepare_ordinary_room_entry=Mock(return_value={'points':[(10,20)]})
        s.enter_ordinary_room=Mock()

    def request(self,**changes):
        value=dict(status='pending',game_pid=123,instance='1');value.update(changes)
        self.path.write_text(json.dumps(value),encoding='utf8')

    def test_no_request_keeps_normal_cycle(self):
        self.assertIsNone(self.s.finish_hunt_before_reentry(Mock(),1))
        self.s.prepare_ordinary_room_entry.assert_not_called()

    def test_completes_once_without_paid_click(self):
        self.request();result=self.s.finish_hunt_before_reentry(Mock(),1)
        self.assertEqual(result['status'],'sale_complete_no_reentry')
        self.assertEqual(result['entry_clicks'],0)
        self.s.enter_ordinary_room.assert_not_called()
        self.assertEqual(json.loads(self.path.read_text())['status'],'completed')
        self.assertIsNone(self.s.finish_hunt_before_reentry(Mock(),2))
        self.s.prepare_ordinary_room_entry.assert_called_once()

    def test_other_client_cannot_consume_request(self):
        self.request(game_pid=456)
        with self.assertRaisesRegex(RuntimeError,'进程不一致'):self.s.finish_hunt_before_reentry(Mock(),1)
        self.s.prepare_ordinary_room_entry.assert_not_called()

    def test_unsold_items_block_completion(self):
        self.request();self.s.hero_inventory=lambda:['木剑']
        with self.assertRaisesRegex(RuntimeError,'白名单'):self.s.finish_hunt_before_reentry(Mock(),1)
        self.s.prepare_ordinary_room_entry.assert_not_called()

    def test_held_item_blocks_menu(self):
        self.request();self.s.held_item=lambda:'木剑'
        with self.assertRaisesRegex(RuntimeError,'未稳定'):self.s.finish_hunt_before_reentry(Mock(),1)
        self.s.prepare_ordinary_room_entry.assert_not_called()

    def test_yuanbao_change_never_reports_success(self):
        self.request();self.s.currency_snapshot=Mock(side_effect=[{'gold':100,'yuanbao':20},{'gold':100,'yuanbao':15}])
        with self.assertRaisesRegex(RuntimeError,'元宝核对'):self.s.finish_hunt_before_reentry(Mock(),1)
        self.assertEqual(json.loads(self.path.read_text())['status'],'pending')

    def test_running_room_finishes_after_monitor_sale_without_entry(self):
        s=object.__new__(BackgroundSession)
        s.login_stage=lambda:'playing';s.npcs=lambda:[];s.in_mengzhong_return_area=lambda:False
        s.held_item=lambda:'';s.sale_item=lambda:'';s.inflight_item=lambda:''
        s.base=0;s.uint=lambda address:0;s.read=lambda address,size:b'room'
        s.check=lambda:None;s.dismiss_town_hunt_notice=lambda:None
        s.monitor_bags=Mock(return_value={'status':'sale_complete'})
        s.finish_hunt_before_reentry=Mock(return_value={'status':'sale_complete_no_reentry','cycles':1})
        s.enter_ordinary_room=Mock()
        self.assertEqual(s.hunt_cycle(seconds=1,resume_current_room=True)['status'],'sale_complete_no_reentry')
        s.monitor_bags.assert_called_once();s.enter_ordinary_room.assert_not_called()


if __name__=='__main__':unittest.main()
