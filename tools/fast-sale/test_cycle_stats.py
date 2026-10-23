import csv
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from cycle_stats import append_event


class StatsTests(unittest.TestCase):
    def test_locked_csv_preserves_event_without_interrupting_game_work(self):
        with tempfile.TemporaryDirectory() as directory:
            original=Path.open
            def locked(path,*args,**kwargs):
                if path.suffix=='.csv':raise PermissionError(13,'locked',str(path))
                return original(path,*args,**kwargs)
            with patch.object(Path,'open',locked):
                append_event(directory,{'event':'sale_round','round_id':'locked-round'})
            events=[json.loads(x) for x in (Path(directory)/'events.jsonl').read_text(encoding='utf8').splitlines()]
            self.assertEqual(events[0]['round_id'],'locked-round')
            warnings=[json.loads(x) for x in (Path(directory)/'运行日志.jsonl').read_text(encoding='utf8').splitlines()]
            self.assertEqual(warnings[0]['event'],'csv_export_blocked')
            self.assertTrue(warnings[0]['jsonl_preserved'])

    def test_append_keeps_prior_rounds_and_distinguishes_gross_and_net(self):
        with tempfile.TemporaryDirectory() as directory:
            event={'event':'sale_round','round_id':'one','status':'complete','gold_before':10000,
                   'gold_after':13000,'gold_net_change':3000,'sale_income_gold':5000,
                   'other_gold_change':-2000,'yuanbao_before':124,'yuanbao_after':124,
                   'yuanbao_change':0,'sold_count':3,'hunt_seconds':None}
            append_event(directory,event);append_event(directory,dict(event,round_id='two'))
            events=[json.loads(x) for x in (Path(directory)/'events.jsonl').read_text(encoding='utf8').splitlines()]
            self.assertEqual([e['round_id'] for e in events],['one','two'])
            with (Path(directory)/'清包统计.csv').open(encoding='utf-8-sig',newline='') as handle:rows=list(csv.DictReader(handle))
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[0]['其他金币变化'],'-2000')
            self.assertEqual(rows[0]['元宝变化'],'0')
            self.assertEqual(rows[0]['打怪秒数'],'')


if __name__=='__main__':unittest.main()
