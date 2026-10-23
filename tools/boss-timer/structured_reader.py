"""Validated text-record layout for this client; never falls back to heap text search."""
import ctypes
from collections import OrderedDict, deque
from dataclasses import replace
import re
import struct
import time

from engine import MemoryReader, parse_text

SIGNATURE = re.compile(rb'\xff{4}\x00{4}.{4}\xdc\x00\x00\x00', re.DOTALL)


def decode_record(raw, read, uptime_ms, wall_time, session, address):
    if len(raw) != 64:
        return []
    words = struct.unpack('<16I', raw)
    if words[1] != 0xffffffff or words[2] != 0 or words[4] != 220 or words[11] != 14 or words[14] != 767:
        return []
    if not 8 < words[0] < 0x100000000:
        return []
    header = read(words[0] - 8, 8)
    if len(header) != 8:
        return []
    references, length = struct.unpack('<2I', header)
    if not 0 < references < 1000 or not 1 < length <= 512:
        return []
    value = read(words[0], length + 1)
    if len(value) != length + 1 or value[-1] != 0:
        return []
    try:
        text = value[:-1].decode('gb18030')
    except UnicodeDecodeError:
        return []
    age_ms = ((uptime_ms & 0xffffffff) - words[15]) & 0xffffffff
    if age_ms > 86400000:
        return []
    parsed = parse_text(text, address)
    # A complete text record must start with the actual map, not a suffix match.
    if len(parsed) != 1 or text != parsed[0].text:
        return []
    return [replace(parsed[0], message_at=wall_time - age_ms / 1000,
                    tick=words[15], session=session)]


class StructuredReader(MemoryReader):
    CHUNK_BYTES = 256 * 1024
    PASS_BYTES = 64 * 1024 * 1024
    PASS_SECONDS = 2.0
    CACHE_LIMIT = 12000

    def __init__(self):
        super().__init__()
        self.k.GetTickCount64.restype = ctypes.c_ulonglong
        self.session = ''
        self._reset_scan_state()
        self.last_scan_bytes = 0
        self.last_scan_seconds = 0

    def connect(self, pid):
        super().connect(pid)
        from ctypes import wintypes as w
        self.k.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
        values = [w.FILETIME() for _ in range(4)]
        if not self.k.GetProcessTimes(self.handle, *(ctypes.byref(value) for value in values)):
            raise OSError(ctypes.get_last_error(), '无法确认目标进程会话')
        created = values[0].dwHighDateTime << 32 | values[0].dwLowDateTime
        self.session = f'{pid}:{created}'
        self._reset_scan_state()

    def _reset_scan_state(self):
        self.cache = OrderedDict()
        self.discovery = deque()
        self.hot_pending = deque()
        self.hot_chunks = set()
        self.discovery_total = 0
        self.discovery_done = 0
        self.scan_phase = '等待定位'

    @property
    def discovery_pending(self):
        return bool(self.discovery)

    def read_bytes(self, address, size):
        value = ctypes.create_string_buffer(size)
        count = ctypes.c_size_t()
        if self.k.ReadProcessMemory(self.handle, address, value, size, ctypes.byref(count)):
            return value.raw[:count.value]
        return b''

    def scan(self, full=False, stop=None, guard=None):
        if guard:
            guard()
        if full and not self.discovery:
            self.enumerate_regions()
            for base, size in self.regions:
                for offset in range(0, size, self.CHUNK_BYTES):
                    self.discovery.append((base + offset, min(self.CHUNK_BYTES + 64, size - offset), base))
            self.discovery_total = len(self.discovery)
            self.discovery_done = 0
        if not self.hot_pending:
            self.hot_pending.extend(sorted(self.hot_chunks))
        started = time.monotonic()
        checked = started
        scanned = 0
        attempted = 0
        notices = {}
        deadline = started + self.PASS_SECONDS
        hot_deadline = started + self.PASS_SECONDS / 3
        # Hot chunks are serviced first; discovery keeps its cursor across passes.
        for work, phase_deadline, quota in ((self.hot_pending, hot_deadline, self.PASS_BYTES // 2),
                                             (self.discovery, deadline, self.PASS_BYTES)):
            while work and attempted < quota and time.monotonic() < phase_deadline:
                if stop and stop.is_set():
                    return []
                if guard and time.monotonic() - checked > .75:
                    guard()
                    checked = time.monotonic()
                address_start, length, base = work.popleft()
                data = self.read_bytes(address_start, length)
                attempted += length
                scanned += len(data)
                complete = True
                for match in SIGNATURE.finditer(data):
                    if time.monotonic() >= phase_deadline:
                        # Resume before the unprocessed record, retaining overlap.
                        offset = max(0, match.start() - 4)
                        work.appendleft((address_start + offset, length - offset, base))
                        complete = False
                        break
                    position = match.start() - 4
                    if position < 0 or position + 64 > len(data):
                        continue
                    address = address_start + position
                    raw = data[position:position + 64]
                    fingerprint = raw
                    cached = self.cache.get(address)
                    if cached and cached[0] == fingerprint:
                        self.cache.move_to_end(address)
                        parsed = cached[1]
                    else:
                        parsed = decode_record(raw, self.read_bytes, self.k.GetTickCount64(),
                                               time.time(), self.session, address)
                        if parsed:
                            self.cache[address] = (fingerprint, parsed)
                            while len(self.cache) > self.CACHE_LIMIT:
                                self.cache.popitem(last=False)
                    if parsed:
                        self.chat_regions.add(base)
                        self.hot_chunks.add((address_start, length, base))
                    for notice in parsed:
                        notices[notice.signature] = notice
                if work is self.discovery and complete:
                    self.discovery_done += 1
        self.last_scan_bytes = scanned
        self.last_scan_seconds = round(time.monotonic() - started, 3)
        if self.discovery:
            self.scan_phase = f'分批定位 {self.discovery_done}/{self.discovery_total}'
        else:
            self.scan_phase = '定位完成'
        return sorted(notices.values(), key=lambda n: (n.message_at, n.text))

    def close(self):
        super().close()
        self._reset_scan_state()
