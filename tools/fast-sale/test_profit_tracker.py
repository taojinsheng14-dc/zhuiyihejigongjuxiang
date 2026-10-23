import math
from pathlib import Path
import tempfile
import unittest
from profit_tracker import Rates, ProfitTracker, calculate


class ProfitTests(unittest.TestCase):
    def test_user_two_hour_example_and_no_double_fee_deduction(self):
        r=calculate(Rates(),200000,-15,7200,1)
        self.assertAlmostEqual(r['gold_value_yuanbao'],36)
        self.assertAlmostEqual(r['estimated_cost_yuanbao'],15)
        self.assertAlmostEqual(r['actual_profit_yuanbao'],21)
        self.assertAlmostEqual(r['actual_profit_rmb'],21/11)
        self.assertAlmostEqual(r['estimated_profit_yuanbao'],21)
        self.assertAlmostEqual(r['break_even_gold'],1000000/180*15)

    def test_actual_paid_cost_separate_from_prorated_estimate(self):
        r=calculate(Rates(),100000,-10,1800,1)
        self.assertAlmostEqual(r['actual_profit_yuanbao'],8)
        self.assertAlmostEqual(r['estimated_profit_yuanbao'],10.5)
        self.assertIsNone(calculate(Rates(),0,0,0,0)['actual_hourly_rmb'])

    def test_rates_recalculate_without_changing_wallet(self):
        with tempfile.TemporaryDirectory() as d:
            t=ProfitTracker(d);t.start({'gold':100,'yuanbao':20},now=100,pid=1)
            t.sample({'gold':100100,'yuanbao':10},200,1)
            t.set_rates(yuanbao_per_rmb=10,gold_per_lot=1000000,yuanbao_per_lot=200,hourly_cost=6,entry_cost=4)
            self.assertEqual(t.state['wallet'],{'gold':100100,'yuanbao':10})
            self.assertEqual(t.summary(200)['actual_profit_rmb'],1)
            self.assertEqual(ProfitTracker(d).rates.hourly_cost,6)

    def test_pause_resume_excludes_idle_time_and_outside_transactions(self):
        with tempfile.TemporaryDirectory() as d:
            t=ProfitTracker(d);t.start({'gold':0,'yuanbao':30},100,1)
            t.sample({'gold':100000,'yuanbao':25},200,1);t.stop(200)
            self.assertEqual(t.seconds(1000),100)
            t.resume({'gold':900000,'yuanbao':100},1000,1)
            t.sample({'gold':1000000,'yuanbao':95},1100,1)
            r=t.summary(1100)
            self.assertEqual(r['gold_delta'],200000)
            self.assertEqual(r['yuanbao_delta'],-10)
            self.assertEqual(t.seconds(1100),200)

    def test_room_events_deduplicate_and_persist(self):
        with tempfile.TemporaryDirectory() as d:
            t=ProfitTracker(d);t.start({'gold':0,'yuanbao':30},100,1)
            event={'event':'room_entry','time':'1970-01-01T00:01:41+00:00','position':[1,2]}
            self.assertTrue(t.add_event(event));self.assertFalse(t.add_event(event))
            self.assertFalse(t.add_event(dict(event,time='1970-01-01T00:00:01+00:00')))
            t.save();t=ProfitTracker(d)
            self.assertFalse(t.add_event(event));self.assertEqual(t.summary(200)['entries'],1)

    def test_stale_sample_does_not_roll_back_balance_and_pid_change_pauses(self):
        with tempfile.TemporaryDirectory() as d:
            t=ProfitTracker(d);t.start({'gold':0,'yuanbao':30},100,1)
            t.sample({'gold':100,'yuanbao':29},200,1)
            self.assertFalse(t.sample({'gold':1,'yuanbao':30},150,1))
            with self.assertRaises(ValueError):t.sample({'gold':999,'yuanbao':99},201,2)
            self.assertFalse(t.running);self.assertEqual(t.state['wallet']['gold'],100)

    def test_invalid_rates_rejected(self):
        for value in (0,-1,math.nan,math.inf):
            with self.assertRaises(ValueError):Rates(yuanbao_per_rmb=value).validate()

    def test_random_consumption_is_counted_once_as_estimated_resource_cost(self):
        with tempfile.TemporaryDirectory() as d:
            t=ProfitTracker(d);t.start({'gold':0,'yuanbao':30},100,1)
            event={'event':'random_attempt','time':'1970-01-01T00:01:41+00:00',
                   'position':[1,2],'estimated_cost_yuanbao':.2}
            self.assertTrue(t.add_event(event));self.assertFalse(t.add_event(event))
            summary=t.summary(100)
            self.assertEqual(summary['random_uses'],1);self.assertAlmostEqual(summary['estimated_cost_yuanbao'],.2)
            self.assertEqual(summary['actual_profit_yuanbao'],0)
            t.save();t=ProfitTracker(d);self.assertFalse(t.add_event(event))


if __name__=='__main__':unittest.main()
