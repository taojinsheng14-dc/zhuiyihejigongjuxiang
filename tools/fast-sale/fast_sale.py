"""Single-process, bounded sale test. Reads game memory; sends ordinary Win32 input.

No memory writes, background clicks, or automatic retry of the final sale click.
"""
import argparse
import ctypes
from ctypes import wintypes as w
import json
from pathlib import Path
import struct
import sys
import time

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'boss-timer'))
from engine import MemoryReader, DEFAULT_GUARD_NAMES

CONTROLS = {
    'bag': (0x488, 'Window_ItemBag'),
    'grid': (0x490, 'Grid_ItemBag'),
    'merchant': (0x5e0, 'Window_MerchantDlg'),
    'sell': (0x638, 'Window_SellDlg'),
    'ok': (0x640, 'Button_SellDlgOk'),
    'spot': (0x644, 'Button_SellDlgSpot'),
}


def grid_center(bag, grid, index):
    if not 0 <= index < 40:
        raise ValueError('背包格子超出范围')
    left, top, width, height = grid
    if width <= 0 or height <= 0 or width % 8 or height % 5:
        raise ValueError('背包网格尺寸不符合8列5行')
    return (bag[0] + left + (index % 8 + .5) * width / 8,
            bag[1] + top + (index // 8 + .5) * height / 5)


def button_center(parent, child):
    return (parent[0] + child[0] + child[2] / 2,
            parent[1] + child[1] + child[3] / 2)


class MI(ctypes.Structure):
    _fields_ = [('dx', w.LONG), ('dy', w.LONG), ('mouseData', w.DWORD),
                ('dwFlags', w.DWORD), ('time', w.DWORD), ('extra', ctypes.c_size_t)]


class KI(ctypes.Structure):
    _fields_ = [('vk', w.WORD), ('scan', w.WORD), ('flags', w.DWORD),
                ('time', w.DWORD), ('extra', ctypes.c_size_t)]


class Union(ctypes.Union):
    _fields_ = [('mi', MI), ('ki', KI)]


class Input(ctypes.Structure):
    _fields_ = [('type', w.DWORD), ('data', Union)]


class Session:
    def __init__(self):
        self.reader = MemoryReader()
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        self.u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        self.u.GetForegroundWindow.restype = w.HWND
        self.u.WindowFromPoint.argtypes = [w.POINT]
        self.u.WindowFromPoint.restype = w.HWND
        self.u.SendInput.argtypes = [w.UINT, ctypes.POINTER(Input), ctypes.c_int]
        self.u.SetForegroundWindow.argtypes = [w.HWND]
        self.last_guard = 0
        try:
            self.check()
            game = self.find_session_game()
            if not game:
                raise RuntimeError('没有找到追忆合击角色')
            self.reader.connect(game[0])
            windows = []
            @self.reader.callback_type
            def visit(hwnd, unused):
                pid = w.DWORD()
                self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                text = ctypes.create_unicode_buffer(512)
                self.u.GetWindowTextW(hwnd, text, 512)
                if pid.value == game[0] and text.value == game[1] and self.u.IsWindowVisible(hwnd):
                    windows.append(hwnd)
                return True
            self.u.EnumWindows(visit, 0)
            if len(windows) != 1:
                raise RuntimeError('无法唯一确定可见游戏窗口')
            self.hwnd = windows[0]
            self.base = self.module_base()
            if self.read(self.base, 2) != b'MZ':
                raise RuntimeError('主程序基址校验失败')
            self.parent = self.uint(self.base + 0x2d4b6c)
            self.controls = {}
            for key, (offset, expected_name) in CONTROLS.items():
                obj = self.uint(self.parent + offset)
                name = self.read(self.uint(obj + 8), 96).split(b'\0')[0].decode('ascii')
                if name != expected_name:
                    raise RuntimeError('客户端布局不兼容：' + expected_name)
                self.controls[key] = obj
            self.inventory()
        except Exception:
            self.close()
            raise

    def find_session_game(self):
        return self.reader.find_game()

    def module_base(self):
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        modules = (w.HMODULE * 1024)()
        needed = w.DWORD()
        psapi.EnumProcessModulesEx.argtypes = [w.HANDLE, ctypes.POINTER(w.HMODULE), w.DWORD,
                                             ctypes.POINTER(w.DWORD), w.DWORD]
        if not psapi.EnumProcessModulesEx(self.reader.handle, modules, ctypes.sizeof(modules),
                                         ctypes.byref(needed), 3) or not modules[0]:
            raise RuntimeError('无法读取游戏主模块')
        return int(modules[0])

    def check(self):
        if self.u.GetAsyncKeyState(0x1b) & 0x8000:
            raise RuntimeError('已按Esc停止；如物品仍在鼠标上，请手动放回背包')
        now = time.monotonic()
        if now - self.last_guard >= .5:
            if self.reader.guard_matches(DEFAULT_GUARD_NAMES):
                raise RuntimeError('其他游戏保护名单触发，停止')
            self.last_guard = now

    def read(self, address, size):
        buf = ctypes.create_string_buffer(size)
        actual = ctypes.c_size_t()
        if not self.reader.k.ReadProcessMemory(self.reader.handle, address, buf, size,
                                              ctypes.byref(actual)) or actual.value != size:
            raise RuntimeError('内存读取失败，停止点击')
        return buf.raw

    def uint(self, address):
        return struct.unpack('<I', self.read(address, 4))[0]

    def bounds(self, key):
        return struct.unpack('<4i', self.read(self.controls[key] + 0x40, 16))

    def inventory(self):
        raw = self.read(self.base + 0x2e1674, 40 * 156)
        result = []
        for index in range(40):
            off = index * 156
            size = raw[off]
            if size > 20:
                raise RuntimeError('背包结构不匹配')
            result.append(raw[off + 1:off + 1 + size].decode('gb18030') if size else '')
        return result

    def activate(self):
        self.u.SetForegroundWindow(self.hwnd)
        time.sleep(.12)
        if self.u.GetForegroundWindow() != self.hwnd:
            raise RuntimeError('无法激活游戏窗口')
        client = w.RECT()
        self.u.GetClientRect(self.hwnd, ctypes.byref(client))
        if (client.right, client.bottom) != (1024, 768):
            raise RuntimeError('本次验证配置仅支持1024×768游戏客户区')

    def click(self, point):
        self.check()
        if self.u.GetForegroundWindow() != self.hwnd:
            raise RuntimeError('游戏失去前台焦点，停止')
        x, y = map(round, point)
        if not (0 <= x < 1024 and 0 <= y < 768):
            raise RuntimeError('目标位置在游戏区域外')
        origin = w.POINT()
        self.u.ClientToScreen(self.hwnd, ctypes.byref(origin))
        x, y = x + origin.x, y + origin.y
        if self.u.WindowFromPoint(w.POINT(x, y)) != self.hwnd:
            raise RuntimeError('目标位置被遮挡或在屏幕外')
        self.u.SetCursorPos(x, y)
        time.sleep(.035)
        event = Input()
        event.data.mi.dwFlags = 2
        if self.u.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input)) != 1:
            raise RuntimeError('发送鼠标按下失败')
        try:
            time.sleep(.055)
        finally:
            event.data.mi.dwFlags = 4
            if self.u.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input)) != 1:
                raise RuntimeError('发送鼠标松开失败')
        time.sleep(.035)

    def wait(self, condition, timeout=1.5):
        deadline = time.monotonic() + timeout
        while True:
            self.check()
            if condition():
                return
            if time.monotonic() >= deadline:
                raise RuntimeError('状态确认超时，停止；不会重复点击确定')
            time.sleep(.02)

    def preview(self, item):
        return [{'slot': i + 1, 'name': name,
                 'client_point': grid_center(self.bounds('bag'), self.bounds('grid'), i)}
                for i, name in enumerate(self.inventory()) if name == item]

    def submit_one(self, item, start='sale', npc=None):
        """One approved item only. Never infer a successful sale from disappearance alone."""
        if item not in ('木剑', '破魂'):
            raise RuntimeError('测试白名单仅包含木剑和破魂')
        candidates = self.preview(item)
        if not candidates:
            raise RuntimeError('背包中没有目标装备')
        started = time.monotonic()
        self.activate()
        if start == 'npc':
            if npc is None:
                raise RuntimeError('请先记录当前场景的NPC点击位置')
            self.click(npc)
            time.sleep(.45)
        if start in ('npc', 'menu'):
            merchant = self.bounds('merchant')
            self.click((merchant[0] + 27, merchant[1] + 64))
            time.sleep(.45)
        before = self.inventory()
        index = before.index(item)
        self.click(grid_center(self.bounds('bag'), self.bounds('grid'), index))
        self.wait(lambda: self.inventory()[index] == '')
        self.click(button_center(self.bounds('sell'), self.bounds('spot')))
        time.sleep(.12)
        placed = self.inventory()
        if placed[index] != '' or any(before[i] != placed[i] for i in range(40) if i != index):
            raise RuntimeError('背包发生非预期变化，停止确认')
        self.click(button_center(self.bounds('sell'), self.bounds('ok')))
        time.sleep(.25)
        return {'item': item, 'slot': index + 1, 'seconds': round(time.monotonic() - started, 3),
                'status': '已提交一次出售，请核对游戏的金币提示；未自动连续出售',
                'remaining_count': self.inventory().count(item)}

    def close(self):
        self.reader.close()


def main():
    parser = argparse.ArgumentParser(description='固定控件＋内存格子的快速出售验证程序')
    parser.add_argument('--item', choices=['木剑', '破魂'], default='木剑')
    parser.add_argument('--execute', action='store_true', help='实际提交一件出售；默认只预览')
    parser.add_argument('--start', choices=['sale', 'menu', 'npc'], default='sale')
    parser.add_argument('--npc-point', type=int, nargs=2)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    session = None
    try:
        session = Session()
        result = session.submit_one(args.item, args.start, args.npc_point) if args.execute else {
            'mode': '只读预览，没有点击', 'items': session.preview(args.item),
            'bag': session.bounds('bag'), 'grid': session.bounds('grid'),
            'sale_spot': button_center(session.bounds('sell'), session.bounds('spot')),
            'sale_ok': button_center(session.bounds('sell'), session.bounds('ok'))}
    except Exception as error:
        result = {'error': str(error)}
    finally:
        if session:
            session.close()
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
