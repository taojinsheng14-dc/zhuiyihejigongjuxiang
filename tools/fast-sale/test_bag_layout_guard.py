import unittest

from background_sale import BackgroundSession


class BagLayoutGuardTests(unittest.TestCase):
    def test_out_of_bounds_dynamic_button_stops_before_clicking(self):
        class Fake(BackgroundSession):
            def __init__(self):
                pass

            def visible(self, key):
                return False

            def client_size(self):
                return (1680, 1027)

            def control_info(self, *args):
                return {'visible':True,'bounds':(2000,2000,20,20)}

        with self.assertRaisesRegex(RuntimeError, '超出当前客户区'):
            Fake().open_main_bag()
