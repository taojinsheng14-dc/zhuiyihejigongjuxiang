import unittest
from unittest.mock import patch
from fast_sale import Session, grid_center, button_center


class FakeSession(Session):
    def __init__(self):
        self.items = [''] * 40
        self.items[8] = self.items[9] = '木剑'
        self.events = []
        self.confirmations = 0

    def inventory(self): return list(self.items)
    def check(self): pass
    def activate(self): pass
    def bounds(self, key):
        return {'bag': (416, 0, 352, 295), 'grid': (29, 42, 288, 160),
                'sell': (260, 176, 140, 181), 'spot': (28, 67, 61, 52),
                'ok': (85, 150, 24, 13), 'merchant': (0, 0, 416, 176)}[key]

    def click(self, point):
        self.events.append(point)
        if point == grid_center(self.bounds('bag'), self.bounds('grid'), 8):
            self.items[8] = ''
        if point == button_center(self.bounds('sell'), self.bounds('ok')):
            self.confirmations += 1


class FastSaleTests(unittest.TestCase):
    def test_all_forty_grid_centers_use_eight_by_five_and_actual_height(self):
        bag, grid = (416, 0, 352, 295), (29, 42, 288, 160)
        self.assertEqual(grid_center(bag, grid, 0), (463, 58))
        self.assertEqual(grid_center(bag, grid, 8), (463, 90))
        self.assertEqual(grid_center(bag, grid, 39), (715, 186))
        self.assertEqual(grid_center((496, 20, 352, 295), grid, 8), (543, 110))
        with self.assertRaises(ValueError): grid_center(bag, grid, 40)

    def test_multiple_identical_items_only_submit_one_and_keep_other(self):
        session = FakeSession()
        with patch('fast_sale.time.sleep'):
            result = session.submit_one('木剑')
        self.assertEqual(session.confirmations, 1)
        self.assertEqual(result['remaining_count'], 1)
        self.assertEqual(session.items[9], '木剑')
        self.assertEqual(len(session.events), 3)

    def test_preview_never_clicks(self):
        session = FakeSession()
        self.assertEqual([r['slot'] for r in session.preview('木剑')], [9, 10])
        self.assertEqual(session.events, [])

    def test_unapproved_item_never_clicks(self):
        session = FakeSession()
        with self.assertRaises(RuntimeError): session.submit_one('裁决之杖')
        self.assertEqual(session.events, [])

    def test_pickup_failure_never_confirms(self):
        session = FakeSession()
        session.click = lambda point: session.events.append(point)
        def immediate_wait(condition, timeout=1.5):
            if not condition(): raise RuntimeError('timeout')
        session.wait = immediate_wait
        with patch('fast_sale.time.sleep'), self.assertRaises(RuntimeError):
            session.submit_one('木剑')
        self.assertEqual(session.confirmations, 0)
        self.assertEqual(len(session.events), 1)


if __name__ == '__main__': unittest.main()
