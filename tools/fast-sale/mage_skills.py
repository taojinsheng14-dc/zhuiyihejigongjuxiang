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


def inspect_current(session, expected_character):
    """One read-only sample via the existing serialized helper command."""
    from combat_metrics import read_experience
    session.check()
    if session.login_stage() != 'playing':
        raise RuntimeError('未进入正常游戏，未读取技能')
    character = read_experience(session)['character']
    if character != expected_character:
        raise RuntimeError('角色与技能研究目标不符')
    # Exact historical code fragments, rebased only for absolute operands.
    fragment = bytes.fromhex('a1b0ad6b008b008bd7e87a98eaff8bf066837e08')
    fragment = fragment[:1] + struct.pack('<I', session.base + 0x2badb0) + fragment[5:]
    if session.read(session.base + 0x172984, len(fragment)) != fragment:
        raise RuntimeError('当前技能记录读取代码与历史证据不符')
    if session.read(session.base + 0x20e5e8, 10) != bytes.fromhex('68940000008b4c24048b'):
        raise RuntimeError('当前技能记录长度代码与历史证据不符')
    if session.read(session.base + 0x1e7e19, 13) != bytes.fromhex('0fb6437c2c700431e882f80300'):
        raise RuntimeError('F1技能键码转换代码不符')
    result = read_skill_records(session)
    matches = [x for x in result['skills'] if x['binding_code_raw'] == 49]
    result['f1_skill'] = matches[0] if len(matches) == 1 else None
    result.update(character=character, live_build_verified=True,
                  binding_basis='当前代码核对：VK_F1 0x70 转为绑定字节 0x31（49）',
                  verification_scope='三个技能记录/键码转换片段；不代表完整施法函数已逆向',
                  position=list(session.player()),
                  monsters=session.nearby_monsters(radius=12),
                  lightning_user_binding='F1（用户明确指定）')
    return result


def inspect_target_context(session):
    result = inspect_current(session, '厚礼蟹')
    controller = session.uint(session.uint(session.base + 0x2bb0a8))
    result['cast_range_candidate'] = session.uint(session.uint(session.base + 0x2bb544))
    result['controller_words_unverified'] = {
        hex(offset): session.uint(controller + offset)
        for offset in (0x18c, 0x194, 0x198, 0x19c, 0x1a0, 0x1b8, 0x1c0)}
    own=session.uint(session.uint(session.base+0x2bac2c))
    selected=session.uint(controller+0x1c0)
    result['actor_vitals']={label:{hex(i):struct.unpack('<H',session.read(a+i,2))[0]
        for i in (0x112,0x116,0x11a,0x11e)}
        for label,a in [('main',own),('selected',selected)] if a>=0x10000}
    return result
