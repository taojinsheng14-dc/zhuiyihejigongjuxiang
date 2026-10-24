import unittest
from unittest.mock import Mock
from test_background_sale import Fake


class FixedTransferTests(unittest.TestCase):
    def session(self, destination):
        s = Fake(); s.login_stage = lambda: 'playing'; s.check = lambda: None
        dest_map = '0159.map' if destination == 'weapon' else '5.map'
        required = 2 if destination == 'weapon' else 1
        clicks = []; s.click = lambda point: clicks.append(point)
        arrived = lambda: len(clicks) == required
        s.state = lambda: {'map_identity': {'name': dest_map if arrived() else '3.map'},
                           'player': [9,16] if arrived() else [327,327]}
        s.player = lambda: s.state()['player']; s.stable_player = s.player
        s.visible = lambda key: not arrived()
        s.currency_snapshot = lambda: {'gold': 8000 if arrived() and destination == 'cangyue' else 10000, 'yuanbao': 45}
        s.active_merchant = None
        def opened(progress): s.active_merchant = '盟重老兵'
        s.open_mengzhong_veteran = Mock(side_effect=opened)
        s.unique_npc = Mock(); s.write_stats = Mock()
        s.menu_matches = Mock(side_effect=AssertionError('must not match screenshots'))
        return s, clicks

    def test_both_destinations_use_bounded_fixed_clicks_and_verify_npc(self):
        for destination, count in [('weapon',2),('cangyue',1)]:
            with self.subTest(destination=destination):
                s, clicks = self.session(destination)
                result = s.test_fixed_veteran_transfer(destination)
                self.assertEqual(len(clicks), count)
                self.assertEqual(result['entry_clicks'], 0)
                self.assertFalse(result['image_matching'])
                self.assertEqual(result['gold_change'], -2000 if destination == 'cangyue' else 0)
                s.unique_npc.assert_called_once(); s.menu_matches.assert_not_called()

    def test_insufficient_funds_stop_before_npc_or_click(self):
        s, clicks = self.session('cangyue'); s.currency_snapshot = lambda: {'gold':1999}
        with self.assertRaisesRegex(RuntimeError,'2000'): s.test_fixed_veteran_transfer('cangyue')
        self.assertEqual(clicks, []); s.open_mengzhong_veteran.assert_not_called()

    def test_already_at_destination_does_not_charge_or_click(self):
        s, clicks = self.session('cangyue'); s.state = lambda: {'map_identity': {'name':'5.map'}}
        result = s.test_fixed_veteran_transfer('cangyue')
        self.assertTrue(result['already_at_destination']); self.assertEqual(clicks, [])
        s.open_mengzhong_veteran.assert_not_called()

    def test_failed_map_change_never_retries_click(self):
        s, clicks = self.session('cangyue')
        s.state = lambda: {'map_identity': {'name':'3.map'}, 'player':[327,327]}
        with self.assertRaises(RuntimeError): s.test_fixed_veteran_transfer('cangyue')
        self.assertEqual(len(clicks),1); s.unique_npc.assert_not_called()

    def test_unknown_map_or_held_item_never_clicks(self):
        for held in (False, True):
            s, clicks = self.session('weapon')
            if held: s.held_item = lambda: '木剑'
            else: s.state = lambda: {'map_identity': {'name':'m001.map'}}
            with self.assertRaises(RuntimeError): s.test_fixed_veteran_transfer('weapon')
            self.assertEqual(clicks,[])


if __name__ == '__main__': unittest.main()
