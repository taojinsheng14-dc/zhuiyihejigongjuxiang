import unittest
from recovery_ledger import used_for_session,load_for_character,reserve_for_character
import json
from pathlib import Path
import tempfile

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

    def test_switching_roles_keeps_old_budget_and_restores_it_when_switching_back(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'ledger.json';old={'game_pid':48776,'used':2,'character':'微笑','instance':'1'}
            p.write_text(json.dumps(old),encoding='utf8')
            new=load_for_character(p,30196,'大鱼','1')
            self.assertEqual(new['used'],0);self.assertEqual(new['records']['微笑']['used'],2)
            self.assertEqual(json.loads(p.with_name('ledger.before-characters.json').read_text()),old)
            self.assertEqual(reserve_for_character(p,30196,'大鱼','1',0,'test'),1)
            self.assertEqual(load_for_character(p,999,'大鱼','1')['used'],1)
            self.assertEqual(load_for_character(p,1000,'微笑','1')['used'],2)
            with self.assertRaisesRegex(RuntimeError,'额度已用完'):reserve_for_character(p,1000,'微笑','1',0,'test')
            self.assertEqual(load_for_character(p,1001,'大鱼','1')['used'],1)

    def test_switching_slots_or_corrupt_count_still_blocks(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'ledger.json';p.write_text(json.dumps({'used':1,'character':'大鱼','instance':'2'}))
            before=p.read_bytes()
            with self.assertRaises(RuntimeError):load_for_character(p,3,'大鱼','1')
            self.assertEqual(p.read_bytes(),before)

    def test_index_cannot_lower_current_snapshot_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'ledger.json'
            old={'game_pid':2,'used':2,'character':'大鱼','instance':'1'}
            p.write_text(json.dumps(dict(old,schema=2,records={'大鱼':dict(old,used=1)})))
            self.assertEqual(load_for_character(p,4,'大鱼','1')['used'],2)
if __name__=='__main__':unittest.main()
