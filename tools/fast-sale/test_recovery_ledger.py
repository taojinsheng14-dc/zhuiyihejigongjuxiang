import unittest
from recovery_ledger import used_for_session

class RecoveryLedgerTests(unittest.TestCase):
    def test_new_pid_keeps_same_character_allowance(self):
        self.assertEqual(used_for_session({'used':1,'game_pid':10,'character':'a','instance':'1'},22,'a','1'),1)
    def test_legacy_same_pid_keeps_allowance(self):
        self.assertEqual(used_for_session({'used':1,'game_pid':10},10,'a','1'),1)
    def test_legacy_new_pid_never_silently_resets(self):
        with self.assertRaisesRegex(RuntimeError,'不会按新PID清零'):used_for_session({'used':1,'game_pid':10},22,'a','1')
    def test_other_account_and_slot_cannot_inherit_or_reset(self):
        record={'used':2,'character':'a','instance':'1'}
        for character,slot in [('b','1'),('a','2')]:
            with self.assertRaises(RuntimeError):used_for_session(record,22,character,slot)
    def test_bad_count_cannot_reset_allowance(self):
        for count in [True,-1,3,'1',None]:
            with self.assertRaises(RuntimeError):used_for_session({'used':count,'game_pid':10},10,'a','1')
if __name__=='__main__':unittest.main()
