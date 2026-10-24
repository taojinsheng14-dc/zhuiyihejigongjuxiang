"""Experimental historical skill-list reader. No input or memory writes.

The binding byte is deliberately not labelled as a Windows virtual key.
Historical addresses require current-client byte validation before live use.
"""
import struct

RECORD_SIZE = 0x94
MAX_SKILLS = 256


def read_skill_records(session):
    """Read a stable main-character list; caller must verify role/build first.

    No assumption that a raw binding value means F1, no cast entry point,
    and no native operation calls. Invalid/changed lists fail closed.
    """
    def header():
        slot = session.uint(session.base + 0x2badb0)
        if slot < 0x10000:
            raise RuntimeError('主角技能列表指针无效')
        collection = session.uint(slot)
        if collection < 0x10000:
            raise RuntimeError('主角技能集合无效')
        data, count = struct.unpack('<II', session.read(collection + 4, 8))
        if count > MAX_SKILLS or (count and data < 0x10000):
            raise RuntimeError('主角技能列表长度或数据指针异常')
        return slot, collection, data, count

    before = header()
    data, count = before[2:]
    pointers = session.read(data, count * 4) if count else b''
    if len(pointers) != count * 4:
        raise RuntimeError('技能列表读取不完整')
    records = []
    for index in range(count):
        address = struct.unpack_from('<I', pointers, index * 4)[0]
        if address < 0x10000:
            raise RuntimeError('技能记录指针无效')
        raw = session.read(address, RECORD_SIZE)
        if len(raw) != RECORD_SIZE or not 1 <= raw[0x0a] <= 13:
            raise RuntimeError('技能记录名称或长度异常')
        try:
            name = raw[0x0b:0x0b + raw[0x0a]].decode('gb18030')
        except UnicodeError as exc:
            raise RuntimeError('技能名称编码异常') from exc
        records.append({'skill_id': struct.unpack_from('<H', raw, 8)[0],
                        'name': name, 'binding_code_raw': raw[0]})
    if header() != before or (count and session.read(data, count * 4) != pointers):
        raise RuntimeError('读取期间技能列表变化')
    return {'skills': records, 'count': count,
            'binding_basis': '原始绑定字节，尚未确认与F1虚拟键的对应关系',
            'live_build_verified': False, 'game_input_sent': False}
