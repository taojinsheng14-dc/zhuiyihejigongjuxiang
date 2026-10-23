import json
from pathlib import Path
import tempfile
import unittest

from engine import DEFAULT_RULES, Notice, TimerStore, extract_notices, parse_text, equipment_names, TRACKED_EQUIPMENT, normalize_map


class ParsingTests(unittest.TestCase):
    def test_screenshot_map_fragments(self):
        self.assertEqual(normalize_map('6777215220全民打宝'), '全民打宝')
        self.assertEqual(normalize_map('6777215220石墓七层'), '石墓七层')
        self.assertEqual(normalize_map('层一'), '')
        self.assertEqual(normalize_map('下'), '')
        self.assertEqual(normalize_map('七层一'), '')
        self.assertEqual(normalize_map('庄园'), '庄园')
        self.assertEqual(parse_text('层一的祖玛卫士[精英]掉落：炼狱'), [])
        self.assertEqual(parse_text('6777215220全民打宝的祖玛教主掉落：裁决之杖')[0].map_name, '全民打宝')

    def test_persisted_maps_backup_and_canonical_precedence(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'state.json'
            clean={'map':'全民打宝','monster':'祖玛教主','observed_at':10000,'due_at':17200,'text':'原文'}
            broken=dict(clean,map='6777215220全民打宝',observed_at=20000)
            fragment=dict(clean,map='层一')
            p.write_text(json.dumps({'records':{'a':clean,'b':broken,'c':fragment}}),encoding='utf-8')
            store=TimerStore(folder)
            self.assertEqual(len(store.records),1)
            self.assertEqual(store.records['全民打宝\t祖玛教主']['observed_at'],10000)
            self.assertTrue((Path(folder)/'state.before-map-cleanup.json').exists())
            self.assertTrue((Path(folder)/'无法确认地图的旧记录.json').exists())
    def test_actual_client_messages_and_exact_monster_names(self):
        samples = [
            ('L230416777215220牛魔寺庙4层的牛魔将军[精英]掉落：红宝石戒指', '牛魔寺庙4层', '牛魔将军[精英]', 60),
            ('L230416777215220藏宝天下的藏宝祖玛教主掉落：祝福油', '藏宝天下', '藏宝祖玛教主', 0),
            ('祖玛七层一的祖玛卫士掉落：英雄召唤神兽', '祖玛七层一', '祖玛卫士', 0),
            ('牛魔七层的牛魔王掉落：裁决之杖', '牛魔七层', '牛魔王', 180),
            ('暗之洞穴的暗之魔龙教主掉落：物品', '暗之洞穴', '暗之魔龙教主', 240),
        ]
        for text, map_name, monster, minutes in samples:
            parsed = parse_text(text)
            if map_name is None:
                self.assertEqual(parsed, [])  # A non-elite guard is not on the user's list.
            else:
                self.assertEqual(len(parsed), 1)
                self.assertEqual((parsed[0].map_name, parsed[0].monster), (map_name, monster))
                self.assertEqual(DEFAULT_RULES.get(monster, 0), minutes)

    def test_binary_boundaries_and_address(self):
        text = 'L230416777215220牛魔寺庙4层的牛魔将军[精英]掉落：红宝石戒指'
        raw = b'\xff\x04\x00' + text.encode('gb18030') + b'\x00unrelated'
        notices = extract_notices(raw, 0x1000)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].text, '牛魔寺庙4层的牛魔将军[精英]掉落：红宝石戒指')
        self.assertEqual(notices[0].address, 0x1000 + raw.index('掉落'.encode('gb18030')))


class StateTests(unittest.TestCase):
    def test_equipment_all_items_and_exact_names(self):
        for item in TRACKED_EQUIPMENT:
            self.assertEqual(equipment_names('测试地图的测试怪物掉落：' + item), [item])
        self.assertEqual(equipment_names('测试怪物掉落：雷霆战甲（男）、开天'), ['雷霆战甲(男)', '开天'])
        self.assertEqual(equipment_names('测试怪物掉落：超级裁决之杖、开天碎片'), [])

    def test_equipment_independent_of_death_merge_and_persistent(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TimerStore(folder)
            store.baseline([], now=10000)
            first = parse_text('牛魔七层的牛魔王掉落：裁决之杖', 1)[0]
            second = parse_text('牛魔七层的牛魔王掉落：圣战戒指', 2)[0]
            self.assertEqual(len(store.consume([first], 10001)), 1)
            self.assertEqual(store.consume([second], 10002), [])
            self.assertEqual([r['装备'] for r in store.equipment], ['裁决之杖', '圣战戒指'])
            copy = Notice(first.map_name, first.monster, first.text, 99)
            store.consume([copy], 10003)
            self.assertEqual(len(store.equipment), 2)
            self.assertEqual(len(TimerStore(folder).equipment), 2)

    def test_equipment_unknown_monster_and_baseline(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TimerStore(folder)
            old = parse_text('未知地图的未知怪物掉落：屠龙', 1)[0]
            store.baseline([old], now=10000)
            store.consume([old], 10001)
            self.assertEqual(store.equipment, [])
            new = parse_text('未知地图的未知怪物掉落：开天', 2)[0]
            self.assertEqual(store.consume([new], 10002), [])
            self.assertEqual(store.equipment[0]['装备'], '开天')
            self.assertEqual(store.records, {})

    def test_copied_old_text_does_not_create_timer(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TimerStore(folder)
            store.baseline([Notice('牛魔七层', '牛魔王', '同一条公告', 1)], now=10000)
            self.assertEqual(store.consume([Notice('牛魔七层', '牛魔王', '同一条公告', 99)], 10010), [])
            self.assertEqual(store.records, {})
            self.assertEqual(len(store.consume([Notice('牛魔七层', '牛魔王', '同一条公告', 100)], 21000)), 1)

    def test_manual_input_needs_no_memory_baseline(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TimerStore(folder)
            self.assertFalse(store.ready)
            notice = Notice('牛魔七层', '牛魔王', '公告')
            self.assertEqual(len(store.accept_manual([notice], 10000)), 1)
            self.assertEqual(store.records[notice.key]['due_at'], 20800)
            self.assertEqual(store.accept_manual([notice], 10001), [])
            self.assertFalse(store.ready)

    def test_baseline_new_event_debounce_and_later_death(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TimerStore(folder)
            old = Notice('牛魔七层', '牛魔王', '旧公告', 1)
            new = Notice('牛魔七层', '牛魔王', '新公告', 2)
            item2 = Notice('牛魔七层', '牛魔王', '第二件物品', 3)
            self.assertEqual(store.consume([old], 10000), [])
            self.assertEqual(store.records, {})
            self.assertEqual(len(store.consume([old, new], 10001)), 1)
            self.assertEqual(store.records[new.key]['due_at'], 10001 + 3 * 3600)
            self.assertEqual(store.consume([item2], 10003), [])
            later = Notice('牛魔七层', '牛魔王', '新公告', 99)
            self.assertEqual(len(store.consume([later], 21000)), 1)
            restored = TimerStore(folder)
            self.assertEqual(restored.records[new.key]['observed_at'], 21000)
            self.assertEqual(len((Path(folder) / '掉落记录.jsonl').read_text(encoding='utf-8').splitlines()), 2)

    def test_maps_independent_unknown_rule_and_rule_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            store = TimerStore(folder)
            store.baseline([])
            notices = [Notice('地图一', '牛魔王', 'a', 1), Notice('地图二', '牛魔王', 'b', 2),
                       Notice('藏宝天下', '藏宝祖玛教主', 'c', 3)]
            self.assertEqual(len(store.consume(notices, 10000)), 3)
            self.assertIsNone(store.records[notices[2].key]['due_at'])
            store.update_rule('藏宝祖玛教主', 90)
            self.assertEqual(store.records[notices[2].key]['due_at'], 15400)
            self.assertEqual(TimerStore(folder).rules['藏宝祖玛教主'], 90)


if __name__ == '__main__':
    unittest.main()
