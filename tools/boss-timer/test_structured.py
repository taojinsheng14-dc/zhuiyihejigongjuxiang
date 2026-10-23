from dataclasses import replace
import struct
import tempfile
from pathlib import Path
import unittest

from engine import Notice, TimerStore
from structured_reader import decode_record, StructuredReader


class StructuredTests(unittest.TestCase):
    def fake_reader(self, regions):
        reader = object.__new__(StructuredReader)
        reader._reset_scan_state()
        reader.regions = regions
        reader.chat_regions = set()
        reader.enumerate_regions = lambda: reader.regions
        reader.read_bytes = lambda address, size: b''
        return reader

    def test_discovery_larger_than_old_limit_resumes_instead_of_failing(self):
        reader = self.fake_reader([(0x10000, 1100 * 1024 * 1024)])
        reader.scan(full=True)
        self.assertTrue(reader.discovery_pending)
        remaining = len(reader.discovery)
        reader.scan(full=True)  # A repeated request must not restart unfinished work.
        self.assertLess(len(reader.discovery), remaining)
        passes = 2
        while reader.discovery_pending and passes < 40:
            reader.scan()
            passes += 1
        self.assertFalse(reader.discovery_pending)
        self.assertGreater(passes, 10)
        self.assertEqual(reader.discovery_done, reader.discovery_total)

    def test_hot_chunks_read_before_discovery_and_stop_is_respected(self):
        import threading
        reader = self.fake_reader([(0x10000, 2 * 1024 * 1024)])
        reader.hot_chunks.add((0x90000000, 1024, 0x90000000))
        reads = []
        reader.read_bytes = lambda address, size: reads.append(address) or b''
        reader.scan(full=True)
        self.assertEqual(reads[0], 0x90000000)
        stop = threading.Event()
        stop.set()
        reads.clear()
        self.assertEqual(reader.scan(full=True, stop=stop), [])
        self.assertEqual(reads, [])

    def test_stone_four_slots_and_manual_death(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TimerStore(folder)
            store.ready = True
            store.monitoring_since = 9999
            for i in range(4):
                at = 10000 + i * 180
                notice = Notice('石墓七层', '白野猪[精英]', '掉落：红宝石戒指', 1, at, i + 1, 'session')
                self.assertEqual(store.consume([notice], at)[0]['slot'], i + 1)
            fifth = Notice('石墓七层', '白野猪[精英]', '掉落：红宝石戒指', 1, 10900, 5, 'session')
            self.assertEqual(store.consume([fifth], 10900), [])
            self.assertEqual(len(TimerStore(folder).records), 4)
            key = store.mark_death('石墓七层', '白野猪[精英]', 4, 11000)
            self.assertEqual(store.records[key]['due_at'], 14600)
            self.assertEqual(store.records[key]['source'], '人工确认死亡')
            self.assertEqual(store.equipment, [])
            with self.assertRaises(ValueError):
                store.mark_death('祖玛七层一', '祖玛卫士[精英]', 3, 11000)

    def test_clear_keeps_rules_and_rejects_old_queued_notices(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TimerStore(folder)
            store.ready = True
            store.mark_death('石墓七层', '白野猪[精英]', 1, 10000)
            store.update_rule('白野猪[精英]', 65)
            store.clear_data(now=11000)
            old = Notice('石墓七层', '白野猪[精英]', '掉落：开天', 1, 10999, 1, 'session')
            self.assertEqual(store.consume([old], 11001), [])
            self.assertFalse(store.records)
            self.assertFalse(store.equipment)
            self.assertFalse((Path(folder) / '人工死亡记录.jsonl').exists())
            restored = TimerStore(folder)
            self.assertFalse(restored.records)
            self.assertEqual(restored.rules['白野猪[精英]'], 65)
            fresh = replace(old, message_at=11002, tick=2)
            self.assertEqual(len(store.consume([fresh], 11002)), 1)

    def decode(self, text, tick=5000, uptime=6000, wall=10000, references=1, declared=None):
        value = text.encode('gb18030')
        pointer = 0x1000
        memory = {pointer - 8: struct.pack('<II', references, len(value) if declared is None else declared), pointer: value + b'\0'}
        words = [0] * 16
        words[0], words[1], words[4], words[11], words[14], words[15] = pointer, 0xffffffff, 220, 14, 767, tick
        return decode_record(struct.pack('<16I', *words), lambda p, n: memory.get(p, b'')[:n], uptime, wall, 'session1', 0x5000)

    def test_real_message_time_and_copy_identity(self):
        first = self.decode('祖玛七层一的祖玛卫士[精英]掉落：裁决之杖')[0]
        self.assertEqual(first.message_at, 9999)
        self.assertEqual(first.signature, replace(first, address=0x9999).signature)
        self.assertNotEqual(first.signature, replace(first, tick=5500).signature)

    def test_reject_freed_truncated_and_bad_record(self):
        self.assertEqual(self.decode('层一的祖玛卫士[精英]掉落：裁决之杖'), [])
        self.assertEqual(self.decode('祖玛七层一的祖玛卫士[精英]掉落：裁决之杖', references=0), [])
        self.assertEqual(self.decode('祖玛七层一的祖玛卫士[精英]掉落：裁决之杖', declared=9999), [])

    def test_tick_wrap(self):
        result = self.decode('牛魔七层的牛魔王掉落：裁决之杖', tick=0xfffffff0, uptime=0x100000010, wall=10000)
        self.assertAlmostEqual(result[0].message_at, 9999.968)

    def test_baseline_cutoff_real_time_and_two_slots(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TimerStore(folder)
            store.ready = True
            store.monitoring_since = 10000
            def notice(at, tick, item='裁决之杖'):
                return Notice('祖玛七层一','祖玛卫士[精英]','祖玛七层一的祖玛卫士[精英]掉落：'+item,1,at,tick,'session')
            self.assertEqual(store.consume([notice(9999,1)],11000),[])
            self.assertFalse(store.records)
            first = store.consume([notice(10001,2)],11000)[0]
            self.assertEqual(first['due_at'],13601)
            self.assertEqual(store.consume([notice(10001,2)],12000),[])
            self.assertEqual(store.consume([notice(10001.1,2,'圣战戒指')],12000),[])
            second=store.consume([notice(10301,4)],12000)[0]
            self.assertEqual(second['slot'],2)
            self.assertEqual(len(store.records),2)
            self.assertEqual(len(store.equipment),3)
            restored=TimerStore(folder)
            self.assertEqual(len(restored.records),2)
            self.assertEqual(store.consume([notice(10500,5,'开天')],12000),[])
            self.assertEqual(len(store.records),2)
            next_kill=store.consume([notice(13602,6)],14000)[0]
            self.assertEqual(next_kill['slot'],1)


if __name__ == '__main__':
    unittest.main()
