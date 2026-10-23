import unittest
from island_pickup_policy import parse_list,filter_drops

class PolicyTests(unittest.TestCase):
    def test_headers_markers_and_parentheses_are_preserved(self):
        rows=parse_list('---装备---\n-\n英雄烈火剑法\n战神盔甲(男) 1\n10万金币 1')
        self.assertEqual([r['name'] for r in rows],['英雄烈火剑法','战神盔甲(男)','10万金币'])
        self.assertEqual([r['marked'] for r in rows],[False,True,True])
    def test_unlisted_potions_are_ignored_and_never_block_clear_gate(self):
        drops=[{'name':'强效金创药'},{'name':'太阳水'},{'name':'金币'},{'name':'木剑'}]
        kept,ignored=filter_drops(drops,{'mode':'all_listed','items':parse_list('金币 1\n木剑')})
        self.assertEqual([d['name'] for d in kept],['金币','木剑'])
        self.assertEqual(len(ignored),2)
    def test_marked_only_does_not_guess_plain_names(self):
        kept,_=filter_drops([{'name':'金币'},{'name':'木剑'}],{'mode':'marked_only','items':parse_list('金币 1\n木剑')})
        self.assertEqual(kept,[{'name':'金币'}])
    def test_unknown_mode_stops_before_any_actions(self):
        with self.assertRaisesRegex(RuntimeError,'待用户确认'):filter_drops([],{'mode':'pending','items':[]})

if __name__=='__main__':unittest.main()
