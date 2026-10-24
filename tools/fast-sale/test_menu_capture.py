import unittest
from unittest.mock import Mock
from PIL import Image
from test_background_sale import Fake


class MenuCaptureTests(unittest.TestCase):
    def matching_frame(self, session, name='shop_transfer'):
        entry = session.profile()['menus'][name]
        frame = Image.new('RGB', session.client_size())
        with Image.open(session.resource(entry['template'])) as template:
            frame.paste(template, tuple(entry['box'][:2]))
        return frame

    def test_transient_white_recaptures_then_clicks_once(self):
        s = Fake()
        s.capture_client = Mock(side_effect=[Image.new('RGB', s.client_size(), 'white'),
                                           self.matching_frame(s)])
        s.pause = Mock(); s.click = Mock(); s._stats_enabled = True
        s.write_stats = Mock()
        s.menu_click('shop_transfer')
        self.assertEqual(s.capture_client.call_count, 2)
        s.pause.assert_called_once_with(.25)
        s.click.assert_called_once()
        self.assertEqual([c.args[0]['blank'] for c in s.write_stats.call_args_list], [True, False])

    def test_persistent_blank_stops_without_click_or_relogin(self):
        for color in ('white', 'black', (120, 121, 122)):
            with self.subTest(color=color):
                s = Fake(); s.pause = Mock(); s.click = Mock(); s.recover_session = Mock()
                s.capture_client = Mock(return_value=Image.new('RGB', s.client_size(), color))
                with self.assertRaisesRegex(RuntimeError, '连续3次为空白'):
                    s.menu_click('shop_transfer')
                self.assertEqual(s.capture_client.call_count, 3)
                self.assertEqual(s.pause.call_count, 2)
                s.click.assert_not_called(); s.recover_session.assert_not_called()

    def test_valid_wrong_link_is_not_treated_as_blank(self):
        s = Fake(); s.pause = Mock()
        s.capture_client = Mock(return_value=self.matching_frame(s, 'sell_weapon'))
        self.assertFalse(s.menu_matches('shop_transfer'))
        s.capture_client.assert_called_once(); s.pause.assert_not_called()

    def test_disappearing_merchant_never_clicks_stale_menu(self):
        s = Fake(); s.click = Mock(); s.pause = Mock()
        s.visible = Mock(side_effect=[True, True, True, False])
        s.capture_client = Mock(return_value=Image.new('RGB', s.client_size(), 'white'))
        with self.assertRaises(RuntimeError): s.menu_click('shop_transfer')
        s.capture_client.assert_called_once(); s.click.assert_not_called()


if __name__ == '__main__': unittest.main()
