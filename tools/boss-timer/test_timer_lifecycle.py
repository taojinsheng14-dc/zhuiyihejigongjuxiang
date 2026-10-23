import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from engine import Notice, TimerStore, spawn_limit


class LifecycleTests(unittest.TestCase):
    def test_uploaded_zuma_and_bull_events_replay_without_duplicate_rows(self):
        import json
        from pathlib import Path
        rows=json.loads((Path(__file__).parent/'fixtures'/'uploaded-20261024-duplicate-timers.json').read_text(encoding='utf8'))
        with tempfile.TemporaryDirectory() as folder:
            store=TimerStore(folder);store.ready=True
            for row in sorted(rows,key=lambda r:r['observed_at']):
                notice=Notice(row['map'],row['monster'],row['text'],0,row['observed_at'],row['tick'],row['session'])
                store.consume([notice],row['detected_at'])
            self.assertEqual(len([r for r in store.records.values() if r['monster']=='祖玛弓箭手[精英]']),2)
            self.assertEqual(len([r for r in store.records.values() if r['monster']=='牛魔王']),1)
            zuma=sorted(r['observed_at'] for r in store.records.values() if r['monster']=='祖玛弓箭手[精英]')
            self.assertEqual(zuma,[1792773356.2327607,1792773907.932355])

    def notice(self, at, tick, map_name='祖玛七层一', monster='祖玛弓箭手[精英]'):
        return Notice(map_name, monster, map_name+'的'+monster+'掉落：炼狱', 1, at, tick, 'test')

    def test_confirmed_spawn_counts(self):
        for name in ('祖玛七层一', '祖玛七层二', '祖玛七层三'):
            for monster in ('祖玛卫士[精英]', '祖玛雕像[精英]', '祖玛弓箭手[精英]'):
                self.assertEqual(spawn_limit(name, monster), 2)
        self.assertEqual(spawn_limit('石墓七层', '白野猪[精英]'), 4)

    def test_second_spawn_within_58_minutes_and_early_next_round(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TimerStore(folder)
            store.ready = True
            first = store.consume([self.notice(10000, 1)], 10000)[0]
            second = store.consume([self.notice(10180, 2)], 10180)[0]
            self.assertEqual((first['slot'], second['slot']), (1, 2))
            self.assertEqual(store.consume([self.notice(11000, 3)], 11000),[])
            self.assertEqual(TimerStore(folder).capacity(first['map'], first['monster']), 2)
            corrected = store.consume([self.notice(13580, 4)], 13580)[0]
            self.assertEqual(corrected['slot'], 1)
            self.assertEqual(corrected['due_at'], 17180)
            self.assertEqual(store.records[self.notice(0, 0).key+'\t2']['observed_at'], 10180)

    def test_delete_at_five_minutes_restart_and_later_reappearance(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TimerStore(folder)
            store.ready = True
            notice = self.notice(10000, 1)
            store.consume([notice], 10000)
            self.assertEqual(store.prune_expired(13900), [])
            self.assertEqual(store.prune_expired(13901), [notice.key])
            self.assertEqual(TimerStore(folder).records, {})
            self.assertEqual(store.consume([notice], 13902), [])
            self.assertEqual(len(store.consume([self.notice(14000, 2)], 14000)), 1)

    def test_old_delayed_message_does_not_recreate_deleted_timer(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TimerStore(folder)
            store.ready = True
            self.assertEqual(store.consume([self.notice(10000, 1)], 14000), [])
            self.assertFalse(store.records)

    def test_out_of_order_second_spawn_does_not_silently_disappear(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TimerStore(folder)
            store.ready = True
            store.consume([self.notice(10300, 2)], 10400)
            self.assertEqual(len(store.consume([self.notice(10000, 1)], 10401)), 1)
            self.assertEqual(len(store.records), 2)
            self.assertEqual(store.last_deaths[self.notice(0, 0).key], 10300)

    def test_close_ticks_are_one_unproved_death_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TimerStore(folder)
            store.ready = True
            events = [self.notice(10000+i, i+1) for i in range(3)]
            self.assertEqual(len(store.consume(events, 10003)), 1)
            self.assertEqual(sorted(r['due_at'] for r in store.records.values()), [13600])
            self.assertEqual(store.consume(events, 10004), [])
            self.assertEqual(len(store.records), 1)

    def test_bull_lobby_cannot_add_second_king_before_respawn(self):
        with tempfile.TemporaryDirectory() as folder:
            store=TimerStore(folder);store.ready=True
            first=self.notice(10000,1,'牛魔寺庙大厅','牛魔王')
            self.assertEqual(len(store.consume([first],10000)),1)
            self.assertEqual(store.consume([self.notice(10030,2,'牛魔寺庙大厅','牛魔王')],10030),[])
            self.assertEqual(len(store.records),1)
            later=self.notice(20801,3,'牛魔寺庙大厅','牛魔王')
            self.assertEqual(store.consume([later],20801)[0]['slot'],1)

    def test_separate_bosses_and_maps_do_not_merge(self):
        with tempfile.TemporaryDirectory() as folder:
            store=TimerStore(folder);store.ready=True
            self.assertEqual(len(store.consume([self.notice(10000,1),self.notice(10010,2),
                self.notice(10000,3,'祖玛七层三')],10011)),3)

    def test_legacy_duplicate_rows_archived_before_repair(self):
        import json
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            store=TimerStore(folder);store.ready=True
            store.consume([self.notice(10000,1)],10000)
            base=self.notice(0,0).key
            store.records[base+'\t2']=dict(store.records[base],slot=2,tick=2,observed_at=10001,due_at=13601)
            store.records[base+'\t3']=dict(store.records[base],slot=3,tick=3,observed_at=10100,due_at=13700)
            store.learned_counts[base]=3;store.save()
            restored=TimerStore(folder)
            self.assertEqual(len(restored.records),2);self.assertEqual(restored.capacity('祖玛七层一','祖玛弓箭手[精英]'),2)
            self.assertTrue((Path(folder)/'state.before-event-dedup.json').exists())
            self.assertEqual(len(json.loads((Path(folder)/'state.before-event-dedup.json').read_text(encoding='utf8'))['records']),3)

    def test_same_tick_multiple_items_merge_but_equipment_is_recorded(self):
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as folder:
            store = TimerStore(folder)
            store.ready = True
            a = self.notice(10000, 1)
            b = replace(a, text=a.map_name+'的'+a.monster+'掉落：开天')
            self.assertEqual(len(store.consume([a, b], 10001)), 1)
            self.assertEqual(len(store.equipment), 1)

    def test_retry_respects_manual_stop(self):
        from app import App
        import threading
        calls = []
        ui = SimpleNamespace(stop_event=threading.Event(), start=lambda: calls.append(1))
        App.retry_reading(ui)
        self.assertEqual(calls, [1])
        ui.stop_event.set()
        App.retry_reading(ui)
        self.assertEqual(calls, [1])

    def test_multi_client_auto_start_waits_for_explicit_listener_choice(self):
        from app import App
        from unittest.mock import Mock
        ui=SimpleNamespace(status=Mock(),start=Mock())
        with patch('app.MemoryReader') as reader:
            reader.return_value.candidates.return_value=[(1,'one'),(2,'two')]
            App.auto_start(ui)
            ui.start.assert_not_called();reader.return_value.close.assert_called_once()

    def test_display_green_two_minutes_then_timeout_then_delete(self):
        from app import App

        class Tree:
            def __init__(self): self.rows = {}
            def exists(self, key): return key in self.rows
            def item(self, key, **values): self.rows[key] = values
            def insert(self, parent, where, iid, **values): self.rows[iid] = values
            def move(self, *args): pass
            def get_children(self): return list(self.rows)
            def delete(self, key): del self.rows[key]

        with tempfile.TemporaryDirectory() as folder:
            store = TimerStore(folder)
            store.ready = True
            notice = self.notice(10000, 1)
            store.consume([notice], 10000)
            ui = SimpleNamespace(render_equipment=lambda: None, store=store,
                search=SimpleNamespace(get=lambda: ''), waiting={}, notified=set(),
                detail=SimpleNamespace(set=lambda value: None),
                sound=SimpleNamespace(get=lambda: False), tree=Tree())
            for at, tag in ((13600, 'ready'), (13720, 'ready'), (13721, 'unset'), (13900, 'unset')):
                with patch('app.time.time', return_value=at):
                    App.render(ui)
                self.assertEqual(ui.tree.rows[notice.key]['tags'], (tag,))
            with patch('app.time.time', return_value=13901):
                App.render(ui)
            self.assertEqual(ui.tree.rows, {})


if __name__ == '__main__':
    unittest.main()
