import unittest
from bag_input_test import snapshot


class SnapshotTests(unittest.TestCase):
    def test_refreshes_cached_address_and_uses_fullscreen_controls(self):
        class Fake:
            base = 100
            controls = {'bag': 111}
            def uint(self, address): return 900
            def control_info(self, offset, expected):
                return {0x488: {'object': 222, 'visible': True, 'bounds': (10, 20, 350, 300)},
                        0xfa0: {'visible': True, 'bounds': (2200, 1200, 300, 100)},
                        0x650: {'visible': True, 'bounds': (10, 10, 40, 40)}}[offset]
            def client_size(self): return (2560, 1440)
            physical_client_size = client_size
        session = Fake()
        result = snapshot(session)
        self.assertEqual(result['previous_cached_bag'], 111)
        self.assertEqual(session.controls['bag'], 222)
        self.assertEqual(result['button'], (2230, 1230))
        self.assertEqual(result['client'], [2560, 1440])


class EntryTests(unittest.TestCase):
    def test_route_dispatch_reaches_diagnostic_module(self):
        from unittest.mock import patch
        from background_sale import BackgroundSession
        class Fake:
            def check(self): pass
        with patch('importlib.reload', side_effect=lambda module: module), patch('bag_input_test.run', return_value={'ok': True}) as run:
            result = BackgroundSession.run_shop_route(Fake(), ['背包多方式点击测试'])
        self.assertEqual(result, {'ok': True})
        run.assert_called_once()
