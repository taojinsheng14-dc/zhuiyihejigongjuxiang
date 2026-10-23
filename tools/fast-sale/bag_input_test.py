"""Bounded bag-only UI diagnostics; never transfers or sells items."""
import ctypes
import datetime
import json
import time
from pathlib import Path

from fast_sale import Input, button_center


def snapshot(session):
    parent = session.uint(session.base + 0x2d4b6c)
    session.parent = parent
    bag = session.control_info(0x488, 'Window_ItemBag')
    group = session.control_info(0xfa0, 'UI_Window_StateGroup')
    button = session.control_info(0x650, 'Button_MyBag')
    cached = session.controls.get('bag')
    session.controls['bag'] = bag['object']
    width, height = session.client_size()
    point = button_center(group['bounds'], button['bounds'])
    if not group['visible'] or not button['visible']:
        raise RuntimeError('背包按钮或底栏未显示，停止测试')
    if not (0 <= point[0] < width and 0 <= point[1] < height):
        raise RuntimeError('动态背包按钮坐标超出当前客户区')
    return {'parent': parent, 'bag_object': bag['object'],
            'previous_cached_bag': cached, 'visible': bag['visible'],
            'bag_bounds': bag['bounds'], 'button': point,
            'client': [width, height], 'physical': session.physical_client_size()}


def run(session, progress=lambda message: None, background_only=False):
    from background_sale import BackgroundSession, ForegroundSession
    path = Path(__file__).resolve().parents[2] / 'outputs' / '背包点击测试.jsonl'
    records = []

    def save(row):
        row['time'] = datetime.datetime.now().astimezone().isoformat()
        records.append(row)
        with path.open('a', encoding='utf8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')

    def guard():
        session.check()
        if session.login_stage() != 'playing' or session.u.IsIconic(session.hwnd):
            raise RuntimeError('非游戏中或已最小化，停止背包测试')
        if session.held_item() or session.sale_item() or session.inflight_item():
            raise RuntimeError('存在手持、待售或传输物品，停止背包测试')

    guard()
    initial = snapshot(session)
    save({'event': 'start', 'state': initial, 'items_untouched': True})
    methods=('window_message',) if background_only else ('foreground_mouse', 'window_message', 'F9_scan')
    for method in methods:
        guard()
        before = snapshot(session)
        # Each successful toggle is paired with a verified reverse toggle.
        for action in ('toggle', 'restore'):
            guard()
            state = snapshot(session)
            target = not state['visible']
            event_start=len(session.events)
            if method == 'foreground_mouse':
                ForegroundSession.click(session, state['button'])
            elif method == 'window_message':
                BackgroundSession.background_mouse(session, state['button'], 'left',
                    track_movement=False, move_settle=.15, dpi_scaled=True,
                    button_hold=.15, restore_client_focus=True)
            else:
                session.wait_shortcut_modifiers_released()
                ForegroundSession.focus_game(session)
                key = Input(); key.type = 1
                key.data.ki.scan = 0x43; key.data.ki.flags = 8
                if session.u.SendInput(1, ctypes.byref(key), ctypes.sizeof(Input)) != 1:
                    raise RuntimeError('F9按下发送失败')
                try:
                    session.pause(.15)
                finally:
                    key.data.ki.flags = 10
                    session.u.SendInput(1, ctypes.byref(key), ctypes.sizeof(Input))
            samples = []
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                guard()
                current = snapshot(session)
                if not samples or (current['visible'], current['bag_object']) != (samples[-1]['visible'], samples[-1]['bag_object']):
                    samples.append(current)
                session.pause(.05)
            after = snapshot(session)
            passed = after['visible'] == target
            save({'event': action, 'method': method, 'before': state,
                  'transitions': samples, 'after': after, 'passed': passed,
                  'input_events':session.events[event_start:]})
            progress('%s：%s，背包对象 %s，可见=%s' %
                     (method, '成功' if passed else '失败', hex(after['bag_object']), after['visible']))
            if not passed:
                # A failed/brief toggle must not cause an extra blind toggle.
                if after['visible'] != before['visible']:
                    raise RuntimeError('背包状态未恢复，停止后续方法测试')
                raise RuntimeError('背包开关未通过实际可见性验证，停止；不能把命令结束算作测试成功')
    return {'test': 'bag_input', 'records': records, 'log': str(path),
            'items_untouched': True, 'background_only':background_only, 'final': snapshot(session)}
