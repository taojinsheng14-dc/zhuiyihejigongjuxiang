import struct
import unittest
from types import SimpleNamespace
from mage_skills import read_skill_records


class MageSkillsTests(unittest.TestCase):
    def session(self, count=1, changed=False):
        record = bytearray(0x94)
        name = '雷电术'.encode('gb18030')
        record[0] = 1
        struct.pack_into('<H', record, 8, 11)
        record[10] = len(name);record[11:11+len(name)] = name
        reads = {'headers': 0}
        def read(address, size):
            if address == 0x20004:
                reads['headers'] += 1
                return struct.pack('<II', 0x30000, count + int(changed and reads['headers'] > 1))
            if address == 0x30000:return struct.pack('<I', 0x40000)
            if address == 0x40000:return bytes(record)
            raise AssertionError((address, size))
        return SimpleNamespace(base=0x400000,
            uint=lambda address: {0x6badb0: 0x10000, 0x10000: 0x20000}[address],read=read), record

    def test_preserves_raw_binding_without_calling_it_f1(self):
        s, _ = self.session();result = read_skill_records(s)
        self.assertEqual(result['skills'], [{'skill_id':11,'name':'雷电术','binding_code_raw':1}])
        self.assertFalse(result['live_build_verified']);self.assertFalse(result['game_input_sent'])
        self.assertNotIn('virtual_key', result['skills'][0])

    def test_bad_count_stops_before_reading_records(self):
        s, _ = self.session(count=257)
        with self.assertRaisesRegex(RuntimeError, '长度'):read_skill_records(s)

    def test_list_changed_during_read_is_rejected(self):
        s, _ = self.session(changed=True)
        with self.assertRaisesRegex(RuntimeError, '变化'):read_skill_records(s)

    def test_invalid_name_does_not_guess_a_skill(self):
        s, raw = self.session();raw[10] = 30
        with self.assertRaisesRegex(RuntimeError, '名称'):read_skill_records(s)
