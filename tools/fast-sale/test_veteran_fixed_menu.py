import unittest
from unittest.mock import Mock
from test_background_sale import Fake


class VeteranFixedMenuTests(unittest.TestCase):
    def session(self):
        s = Fake(); s.login_stage = lambda: 'playing'
        s.state = lambda: {'map_identity': {'name': '3.map'}, 'player': [327, 327]}
        s.player = lambda: [327, 327]
        s.active_merchant = None
        def opened(progress): s.active_merchant = '盟重老兵'
        s.open_mengzhong_veteran = Mock(side_effect=opened)
        s.click = Mock(); s.write_stats = Mock()
        def match(name):
            s.click.assert_called_once()
            return True
        s.menu_matches = Mock(side_effect=match)
        return s

    def test_click_precedes_image_check_and_never_selects_destination(self):
        s = self.session(); result = s.test_veteran_fixed_menu()
        self.assertFalse(result['preclick_image_matching'])
        self.assertEqual(result['menu_clicks'], 1)
        self.assertEqual(result['destination_clicks'], 0)
        s.open_mengzhong_veteran.assert_called_once()

    def test_wrong_map_stops_before_open_or_click(self):
        s = self.session(); s.state = lambda: {'map_identity': {'name': '5.map'}}
        with self.assertRaisesRegex(RuntimeError, '土城'): s.test_veteran_fixed_menu()
        s.open_mengzhong_veteran.assert_not_called(); s.click.assert_not_called()

    def test_postclick_mismatch_does_not_repeat_click(self):
        s = self.session(); s.menu_matches = Mock(return_value=False)
        with self.assertRaisesRegex(RuntimeError, '不重复点击'): s.test_veteran_fixed_menu()
        s.click.assert_called_once()


if __name__ == '__main__': unittest.main()
