"""Read-only BlueMir chat observation and local countdown state."""
import ctypes
import csv
from ctypes import wintypes as w
from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import time

GROUPS = {
    60: '祖玛卫士[精英] 牛魔祭司[精英] 白野猪[精英] 祖玛雕像[精英] 祖玛弓箭手[精英] 牛魔将军[精英]'.split(),
    120: '沃玛教主 祖玛教主 石墓尸王 黄泉教主 魔龙巨蛾 魔龙力士 魔龙战将'.split(),
    180: '双头血魔 双头金刚 赤月恶魔 牛魔王 暗之双头血魔 暗之双头金刚 暗之黄泉教主 暗之骷髅精灵 暗之沃玛教主 暗之虹魔教主'.split(),
    240: '地藏王 重装使者 魔龙教主 暗之魔龙教主 烟花恶魔 万年树妖'.split(),
    0: '藏宝卫士 藏宝尸王 藏宝邪恶钳虫 藏宝白野猪 藏宝触龙神 藏宝邪恶毒蛇 藏宝虹魔猪卫 藏宝虹魔蝎卫 藏宝沃玛教主 藏宝祖玛教主 藏宝虹魔教主 藏宝黄泉教主 藏宝石墓尸王 藏宝牛魔王 藏宝双头金刚 藏宝双头血魔 藏宝赤月恶魔 藏宝魔龙战将 藏宝魔龙巨蛾 藏宝魔龙教主 藏宝图金猪 藏宝骷髅精灵 孤岛教主 孤岛白野猪 真假牛魔王 送宝稻草人 激情树妖 分身牛魔王'.split(),
}
DEFAULT_RULES = {name: minutes for minutes, names in GROUPS.items() for name in names}
READY_SECONDS = 120
EXPIRE_SECONDS = 300
ELITE_EARLY_SECONDS = 120
DROP_BATCH_SECONDS = 3
DEFAULT_GUARD_NAMES = ['TslGame.exe', 'PUBG.exe', 'VALORANT-Win64-Shipping.exe', 'cs2.exe',
                       'r5apex.exe', 'FortniteClient-Win64-Shipping.exe', 'cod.exe', 'GTA5.exe']
MONSTER_PATTERN = '|'.join(re.escape(s) for s in sorted(DEFAULT_RULES, key=len, reverse=True))
CHAT_RE = re.compile(r'(?P<map>[\u4e00-\u9fffA-Za-z0-9·（）()_\-]{1,65})的(?P<monster>' + MONSTER_PATTERN + r'|[\u4e00-\u9fffA-Za-z0-9\[\]（）()·_\-]{1,40})掉落[：:]')
TRACKED_EQUIPMENT = '''裁决之杖 骨玉权杖 龙纹剑 血饮 圣战头盔 圣战项链 圣战手镯 圣战戒指
法神头盔 法神项链 法神手镯 法神戒指 天尊头盔 天尊项链 天尊手镯 天尊戒指
天魔神甲 圣战宝甲 法神披风 霓裳羽衣 天尊道袍 天师长袍 赤月斗笠 赤月勋章 赤月靴子 赤月腰带 怒斩 龙牙 逍遥扇
雷霆战甲(男) 雷霆战甲(女) 雷霆项链 雷霆护腕 雷霆战戒 烈焰魔衣(男) 烈焰魔衣(女) 烈焰项链 烈焰护腕 烈焰魔戒
光芒道袍(男) 光芒道袍(女) 光芒项链 光芒护腕 光芒道戒 圣龙盔 魔龙盔 天龙盔 魔龙斗笠 魔龙勋章 魔龙靴子 魔龙腰带 屠龙 嗜魂法杖 指月
凤天魔甲 凰天魔衣 战神项链 战神手镯 战神戒指 圣魔项链 圣魔手镯 圣魔戒指 真魂项链 真魂手镯 真魂戒指 开天 镇天 玄天'''.split()
EQUIPMENT_RE = re.compile(r'(?<![\u4e00-\u9fffA-Za-z0-9])(' + '|'.join(re.escape(x) for x in sorted(TRACKED_EQUIPMENT, key=len, reverse=True)) + r')(?![\u4e00-\u9fffA-Za-z0-9])')


def equipment_names(text):
    tail = re.split(r'掉落[：:]', text, maxsplit=1)
    if len(tail) != 2:
        return []
    return list(dict.fromkeys(EQUIPMENT_RE.findall(tail[1].replace('（', '(').replace('）', ')'))))


@dataclass(frozen=True)
class Notice:
    map_name: str
    monster: str
    text: str
    address: int = 0
    message_at: float | None = None
    tick: int | None = None
    session: str = ''

    @property
    def key(self):
        return self.map_name + '\t' + self.monster

    @property
    def signature(self):
        if self.tick is not None:
            return (self.session, self.tick, self.text)
        return (self.address, self.text)


def normalize_map(name):
    name = re.sub(r'^(?:L\d+|\d{6,})+', '', str(name).strip())
    if len(name) < 2 or re.fullmatch(r'[一二三四五六七八九十0-9]*层[一二三四五六七八九十0-9]*', name):
        return ''
    if not re.search(r'[\u4e00-\u9fffA-Za-z]', name):
        return ''
    return name


def spawn_limit(map_name, monster):
    if map_name in {'牛魔寺庙大厅','牛魔大厅','牛魔七层','牛魔7层'} and monster == '牛魔王':
        return 1
    return 4 if map_name in {'石墓七层', '石墓7层', '石墓7', '石墓七'} and monster == '白野猪[精英]' else 2


def parse_text(text, address=0):
    out = []
    for match in CHAT_RE.finditer(text):
        name = normalize_map(match['map'])
        if not name:
            continue
        tail = re.split(r'[\x00-\x1f]', text[match.end():], maxsplit=1)[0][:100]
        out.append(Notice(name, match['monster'], name + '的' + match['monster'] + '掉落：' + tail, address))
    return out


def extract_notices(data, base=0):
    """Only decode short strings around the server's drop-message marker."""
    result = []
    marker = '掉落'.encode('gb18030')
    position = 0
    while True:
        found = data.find(marker, position)
        if found < 0:
            break
        position = found + len(marker)
        left = max(0, found - 200)
        left = data.rfind(b'\0', left, found) + 1 or left
        right = data.find(b'\0', found, found + 220)
        if right < 0:
            right = min(len(data), found + 220)
        text = data[left:right].decode('gb18030', errors='replace')
        result.extend(parse_text(text, base + found))
    return result


class TimerStore:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.rules = dict(DEFAULT_RULES)
        self.records = {}
        self.learned_counts = {}
        self.last_deaths = {}
        self.text_seen = {}
        self.seen = set()
        self.ready = False
        self.monitoring_since = None
        self.load_error = None
        self.equipment = []
        self.equipment_seen = {}
        try:
            state = json.loads((self.folder / 'state.json').read_text(encoding='utf-8'))
            self.rules.update({k: int(v) for k, v in state.get('rules', {}).items() if k in self.rules and int(v) >= 0})
            self.records = state.get('records', {})
            self.learned_counts = {k: int(v) for k, v in state.get('learned_counts', {}).items()
                                   if isinstance(v, int) and v > 0}
            self.last_deaths = {key: record['observed_at'] for key, record in self.records.items()}
        except FileNotFoundError:
            pass
        except (ValueError, TypeError, KeyError) as error:
            self.load_error = '已有配置无法读取：' + str(error)
        try:
            with (self.folder / '装备掉落记录.csv').open(encoding='utf-8-sig', newline='') as file:
                self.equipment = list(csv.DictReader(file))
        except FileNotFoundError:
            pass
        cleaned = {}
        invalid = []
        changed = False
        # Process already-valid keys last so damaged copies cannot replace them.
        entries = sorted(self.records.items(), key=lambda pair: normalize_map(pair[1].get('map', '')) == pair[1].get('map'))
        for old_key, record in entries:
            original = record.get('map', '')
            name = normalize_map(original)
            if not name:
                invalid.append({'key': old_key, 'record': record, 'reason': '地图名残片，无法确定完整地图'})
                changed = True
                continue
            new_key = name + '\t' + record['monster']
            if record.get('slot', 1) > 1:
                new_key += '\t' + str(record['slot'])
            updated = dict(record, map=name)
            if new_key not in cleaned or original == name or record['observed_at'] > cleaned[new_key]['observed_at']:
                cleaned[new_key] = updated
            changed |= old_key != new_key or original != name
        if changed:
            backup = self.folder / 'state.before-map-cleanup.json'
            if not backup.exists():
                shutil.copy2(self.folder / 'state.json', backup)
            if invalid:
                (self.folder / '无法确认地图的旧记录.json').write_text(json.dumps(invalid, ensure_ascii=False, indent=2), encoding='utf-8')
            self.records = cleaned
            self.last_deaths = {key: record['observed_at'] for key, record in cleaned.items()}
            self.save()
        # Keep the original CSV untouched; normalize only its displayed rows.
        self.equipment = [dict(row, 地图=normalize_map(row.get('地图', ''))) for row in self.equipment if normalize_map(row.get('地图', ''))]
        self.last_deaths = {}
        for record in self.records.values():
            key = record['map'] + '\t' + record['monster']
            self.last_deaths[key] = max(self.last_deaths.get(key, 0), record['observed_at'])
        self.repair_duplicate_timers()

    def repair_duplicate_timers(self):
        """Archive unproved extra rows; never infer population from chat timestamps."""
        kept={};rejected=[];groups={}
        for key,row in self.records.items():
            groups.setdefault((row['map'],row['monster']),[]).append((key,row))
        for (map_name,monster),rows in groups.items():
            accepted=[]
            for key,row in sorted(rows,key=lambda pair:pair[1]['observed_at']):
                duplicate=next((old for _,old in accepted if
                    old.get('tick') is not None and row.get('tick') is not None and
                    abs(old['observed_at']-row['observed_at'])<=DROP_BATCH_SECONDS),None)
                if duplicate:
                    rejected.append({'key':key,'record':row,'reason':'同批公告，不能证明另一只怪死亡'})
                else:accepted.append((key,row))
            limit=spawn_limit(map_name,monster)
            for key,row in accepted[:-limit]:
                rejected.append({'key':key,'record':row,'reason':'超出计时位数量，保留较新记录待核对'})
            for slot,(_,row) in enumerate(accepted[-limit:],1):
                key=map_name+'\t'+monster+ ('\t'+str(slot) if slot>1 else '')
                kept[key]=dict(row,slot=slot)
        if rejected:
            state=self.folder/'state.json'
            backup=self.folder/'state.before-event-dedup.json'
            if state.exists() and not backup.exists():shutil.copy2(state,backup)
            with (self.folder/'重复与超量计时待核对.jsonl').open('a',encoding='utf8') as f:
                for row in rejected:f.write(json.dumps(row,ensure_ascii=False)+'\n')
            self.records=kept;self.learned_counts={};self.save()
            self.last_deaths={}
            for row in kept.values():
                key=row['map']+'\t'+row['monster']
                self.last_deaths[key]=max(self.last_deaths.get(key,0),row['observed_at'])

    def record_equipment(self, notice, now, source='memory'):
        rows = []
        for item in equipment_names(notice.text):
            key = (notice.signature, item) if notice.tick is not None else (notice.map_name, notice.monster, item)
            if now - self.equipment_seen.get(key, 0) < 120:
                continue
            row = {'发现时间': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now)),
                   '地图': notice.map_name, '怪物': notice.monster, '装备': item,
                   '来源': '手动输入' if source == 'manual' else '内存公告', '公告原文': notice.text}
            path = self.folder / '装备掉落记录.csv'
            header = not path.exists() or path.stat().st_size == 0
            with path.open('a', encoding='utf-8-sig', newline='') as file:
                writer = csv.DictWriter(file, fieldnames=list(row))
                if header:
                    writer.writeheader()
                writer.writerow(row)
            self.equipment_seen[key] = now
            self.equipment.append(row)
            rows.append(row)
        return rows

    def clear_data(self, now=None):
        """Keep rules and cached identities; reject pre-clear queued messages."""
        self.monitoring_since = time.time() if now is None else now
        self.records.clear()
        self.learned_counts.clear()
        self.last_deaths.clear()
        self.equipment.clear()
        self.equipment_seen.clear()
        for name in ('装备掉落记录.csv', '掉落记录.jsonl', '待核对事件.jsonl', '人工死亡记录.jsonl', '消息处理.jsonl',
                     'state.before-map-cleanup.json', '无法确认地图的旧记录.json'):
            (self.folder / name).unlink(missing_ok=True)
        self.save()

    def save(self):
        path = self.folder / 'state.json'
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps({'rules': self.rules, 'records': self.records,
                                   'learned_counts': self.learned_counts}, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)

    def capacity(self, map_name, monster):
        return spawn_limit(map_name, monster)

    def prune_expired(self, now=None):
        """Remove timed rows five minutes after due; keep the historical logs."""
        now = time.time() if now is None else now
        removed = [key for key, row in self.records.items()
                   if row.get('due_at') is not None and now > row['due_at'] + EXPIRE_SECONDS]
        for key in removed:
            del self.records[key]
        if removed:
            self.save()
        return removed

    def audit(self, notice, now, result, **details):
        with (self.folder / '消息处理.jsonl').open('a', encoding='utf-8') as output:
            output.write(json.dumps(dict(text=notice.text, message_at=notice.message_at,
                detected_at=now, tick=notice.tick, session=notice.session,
                result=result, **details), ensure_ascii=False) + '\n')

    def baseline(self, notices, now=None):
        now = time.time() if now is None else now
        self.seen = {notice.signature for notice in notices}
        self.text_seen = {notice.text: now for notice in notices}
        self.ready = True

    def consume(self, notices, now=None):
        if not self.ready:
            self.baseline(notices)
            return []
        now = time.time() if now is None else now
        events = []
        changed = False
        for notice in sorted(notices, key=lambda n: n.message_at if n.message_at is not None else now):
            if notice.tick is not None:
                if notice.signature in self.seen:
                    continue
                self.seen.add(notice.signature)
                event_time = notice.message_at
                if event_time is None or (self.monitoring_since is not None and event_time < self.monitoring_since):
                    continue
                self.record_equipment(notice, event_time)
                if notice.monster not in DEFAULT_RULES:
                    continue
                minutes = self.rules.get(notice.monster, 0)
                if minutes and now > event_time + minutes * 60 + EXPIRE_SECONDS:
                    self.audit(notice, now, '公告计时已过期')
                    continue
                slots = [(key, value) for key, value in self.records.items()
                         if value['map'] == notice.map_name and value['monster'] == notice.monster]
                if any(row.get('tick') == notice.tick and row.get('session') == notice.session
                       for _, row in slots):
                    self.audit(notice, now, '同次死亡掉落合并')
                    continue
                if any(row.get('tick') is not None and abs(row['observed_at']-event_time)<=DROP_BATCH_SECONDS for _,row in slots):
                    self.audit(notice, now, '同批掉落公告合并，不能证明独立死亡')
                    continue
                if event_time < self.last_deaths.get(notice.key, 0) - minutes * 60 and minutes:
                    self.audit(notice, now, '早于已处理的上一轮公告')
                    continue
                available = [(key, value) for key, value in slots if not value.get('due_at') or value['due_at'] <= event_time]
                # A new kill within the first 58 minutes belongs to another spawn.
                # Only when every slot is occupied allow a two-minute early correction.
                early_correction = False
                if not available and len(slots) >= spawn_limit(notice.map_name, notice.monster) and notice.monster.endswith('[精英]'):
                    available = [(key, row) for key, row in slots
                                 if 0 < row.get('due_at', 0) - event_time <= ELITE_EARLY_SECONDS]
                    early_correction = bool(available)
                if available:
                    record_key, old = min(available, key=lambda pair: pair[1].get('due_at') or 0)
                    slot = old.get('slot', 1)
                else:
                    if len(slots)>=self.capacity(notice.map_name,notice.monster):
                        self.audit(notice,now,'计时位已满，额外公告待核对；不增加怪物数量')
                        continue
                    used = {value.get('slot', 1) for _, value in slots}
                    slot = next(i for i in range(1, len(used) + 2) if i not in used)
                    record_key = notice.key if slot == 1 else notice.key + '\t' + str(slot)
                self.last_deaths[notice.key] = max(self.last_deaths.get(notice.key, 0), event_time)
                record = {'map': notice.map_name, 'monster': notice.monster, 'slot': slot,
                          'observed_at': event_time, 'detected_at': now, 'tick': notice.tick,
                          'session': notice.session, 'due_at': event_time + minutes * 60 if minutes else None,
                          'text': notice.text, 'source': '客户端消息时间'}
                self.records[record_key] = record
                self.audit(notice, now, '提前刷新校正' if early_correction else '更新计时', slot=slot)
                events.append(record)
                with (self.folder / '掉落记录.jsonl').open('a', encoding='utf-8') as output:
                    output.write(json.dumps(record, ensure_ascii=False) + '\n')
                changed = True
                continue
            if notice.signature in self.seen:
                continue
            self.seen.add(notice.signature)
            # Identical text appearing at another address soon afterwards is a copy,
            # not reliable evidence of another death. Repeats much later can still
            # be observed, including another kill dropping the same item.
            previous = self.text_seen.get(notice.text)
            self.text_seen[notice.text] = now
            if previous is not None and now - previous < 120:
                continue
            # Equipment entries are independent of the death-event merge window.
            self.record_equipment(notice, now)
            if notice.monster not in DEFAULT_RULES:
                continue
            # Multiple items and duplicate memory copies from one kill form one event.
            if now - self.last_deaths.get(notice.key, 0) < 120:
                continue
            self.last_deaths[notice.key] = now
            minutes = self.rules.get(notice.monster, 0)
            record = {'map': notice.map_name, 'monster': notice.monster, 'observed_at': now,
                      'due_at': now + minutes * 60 if minutes else None, 'text': notice.text}
            self.records[notice.key] = record
            events.append(record)
            with (self.folder / '掉落记录.jsonl').open('a', encoding='utf-8') as output:
                output.write(json.dumps(record, ensure_ascii=False) + '\n')
            changed = True
        if changed:
            self.save()
        return events

    def accept_manual(self, notices, now=None):
        """Explicit user-submitted notices do not require a memory baseline."""
        now = time.time() if now is None else now
        events = []
        for notice in notices:
            self.record_equipment(notice, now, source='manual')
            if notice.monster not in DEFAULT_RULES:
                continue
            if now - self.last_deaths.get(notice.key, 0) < 120:
                continue
            minutes = self.rules.get(notice.monster, 0)
            record = {'map': notice.map_name, 'monster': notice.monster, 'observed_at': now,
                      'due_at': now + minutes * 60 if minutes else None, 'text': notice.text}
            self.records[notice.key] = record
            self.last_deaths[notice.key] = now
            events.append(record)
            with (self.folder / '掉落记录.jsonl').open('a', encoding='utf-8') as output:
                output.write(json.dumps(dict(record, source='manual'), ensure_ascii=False) + '\n')
        if events:
            self.save()
        return events

    def mark_death(self, map_name, monster, slot, died_at=None):
        map_name = normalize_map(map_name)
        if not map_name or monster not in self.rules:
            raise ValueError('请输入完整地图名，并选择名单中的怪物')
        if not 1 <= slot <= self.capacity(map_name, monster):
            raise ValueError('计时位超出该地图怪物数量')
        died_at = time.time() if died_at is None else died_at
        base_key = map_name + '\t' + monster
        key = base_key if slot == 1 else base_key + '\t' + str(slot)
        minutes = self.rules[monster]
        record = {'map': map_name, 'monster': monster, 'slot': slot, 'observed_at': died_at,
                  'detected_at': time.time(), 'due_at': died_at + minutes * 60 if minutes else None,
                  'source': '人工确认死亡', 'text': '人工确认死亡；未据此生成掉落或装备记录'}
        self.records[key] = record
        self.last_deaths[base_key] = max(self.last_deaths.get(base_key, 0), died_at)
        with (self.folder / '人工死亡记录.jsonl').open('a', encoding='utf-8') as file:
            file.write(json.dumps(record, ensure_ascii=False) + '\n')
        self.save()
        return key

    def update_rule(self, monster, minutes):
        self.rules[monster] = minutes
        for record in self.records.values():
            if record['monster'] == monster:
                record['due_at'] = record['observed_at'] + minutes * 60 if minutes else None
        self.save()


class MBI(ctypes.Structure):
    _fields_ = [('BaseAddress', ctypes.c_void_p), ('AllocationBase', ctypes.c_void_p),
                ('AllocationProtect', w.DWORD), ('RegionSize', ctypes.c_size_t),
                ('State', w.DWORD), ('Protect', w.DWORD), ('Type', w.DWORD)]


class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [('dwSize', w.DWORD), ('cntUsage', w.DWORD), ('th32ProcessID', w.DWORD),
                ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', w.DWORD),
                ('cntThreads', w.DWORD), ('th32ParentProcessID', w.DWORD),
                ('pcPriClassBase', w.LONG), ('dwFlags', w.DWORD), ('szExeFile', w.WCHAR * 260)]


class MemoryReader:
    def __init__(self):
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        k = self.k
        k.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
        k.CreateToolhelp32Snapshot.restype = w.HANDLE
        for name in ('Process32FirstW', 'Process32NextW'):
            getattr(k, name).argtypes = [w.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
            getattr(k, name).restype = w.BOOL
        k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        k.OpenProcess.restype = w.HANDLE
        k.CloseHandle.argtypes = [w.HANDLE]
        k.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        k.VirtualQueryEx.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
        k.VirtualQueryEx.restype = ctypes.c_size_t
        k.ReadProcessMemory.argtypes = [w.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        k.ReadProcessMemory.restype = w.BOOL
        self.callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        self.u.EnumWindows.argtypes = [self.callback_type, w.LPARAM]
        self.u.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        self.u.GetWindowTextW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
        self.handle = None
        self.pid = None
        self.regions = []
        self.chat_regions = set()

    def processes(self):
        snapshot = self.k.CreateToolhelp32Snapshot(2, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise OSError(ctypes.get_last_error(), '无法读取进程列表')
        processes = {}
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(entry)
        try:
            ok = self.k.Process32FirstW(snapshot, ctypes.byref(entry))
            while ok:
                processes[entry.th32ProcessID] = entry.szExeFile
                ok = self.k.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            self.k.CloseHandle(snapshot)
        return processes

    def candidates(self):
        processes = self.processes()
        found = []
        @self.callback_type
        def visit(hwnd, unused):
            pid = w.DWORD()
            self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in processes:
                title = ctypes.create_unicode_buffer(512)
                self.u.GetWindowTextW(hwnd, title, 512)
                # Recognize the server/character window, independent of random exe names.
                if (re.match(r'^追忆[^\\/:]*合击-[^\\/:]+ - [^\\/:]+$', title.value)
                        and processes[pid.value].lower() not in ('chrome.exe', 'msedge.exe', 'firefox.exe')):
                    found.append((pid.value, title.value, processes[pid.value]))
            return True
        self.u.EnumWindows(visit, 0)
        return list(dict.fromkeys(found))

    def find_game(self, selected_pid=None):
        found = self.candidates()
        if selected_pid is not None:
            return next((item for item in found if item[0] == selected_pid), None)
        if len(found) > 1:
            raise RuntimeError('发现多个游戏角色，请先点击“选择角色”指定目标')
        return found[0] if found else None

    def guard_matches(self, names):
        requested = {name.strip().lower() for name in names if name.strip()}
        return sorted({name for name in self.processes().values() if name.lower() in requested})

    def connect(self, pid):
        self.close()
        self.handle = self.k.OpenProcess(0x410, False, pid)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), '无法读取游戏；请以管理员身份运行，或客户端已限制访问')
        self.pid = pid

    def alive(self):
        code = w.DWORD()
        return bool(self.handle and self.k.GetExitCodeProcess(self.handle, ctypes.byref(code)) and code.value == 259)

    def enumerate_regions(self):
        regions = []
        address = 0
        while address < 0x100000000:
            info = MBI()
            if not self.k.VirtualQueryEx(self.handle, address, ctypes.byref(info), ctypes.sizeof(info)):
                break
            base = info.BaseAddress or 0
            end = base + info.RegionSize
            if end <= address:
                break
            # The observed live chat strings are private heap data, not executable images.
            if info.State == 0x1000 and info.Type == 0x20000 and not info.Protect & 0x101:
                regions.append((base, info.RegionSize))
            address = end
        self.regions = regions
        return regions

    def scan(self, full=False, stop=None, guard=None):
        if guard:
            guard()
        regions = self.enumerate_regions() if full else [r for r in self.regions if r[0] in self.chat_regions]
        notices = {}
        scanned = 0
        started = time.monotonic()
        checked = started
        for base, size in regions:
            for offset in range(0, size, 1024 * 1024):
                if stop and stop.is_set():
                    return list(notices.values())
                if guard and time.monotonic() - checked >= .75:
                    guard()
                    checked = time.monotonic()
                if scanned > 900 * 1024 * 1024 or time.monotonic() - started > 25:
                    raise RuntimeError('本次扫描超过范围或时间限制，请停止后重新连接')
                length = min(1024 * 1024 + 512, size - offset)
                buffer = ctypes.create_string_buffer(length)
                actual = ctypes.c_size_t()
                if not self.k.ReadProcessMemory(self.handle, base + offset, buffer, length, ctypes.byref(actual)):
                    continue
                scanned += actual.value
                parsed = extract_notices(buffer.raw[:actual.value], base + offset)
                if parsed:
                    self.chat_regions.add(base)
                for notice in parsed:
                    notices[notice.signature] = notice
        return list(notices.values())

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
        self.handle = self.pid = None
        self.regions = []
        self.chat_regions.clear()
