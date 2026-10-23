import json
from pathlib import Path
import sys
import threading
import tkinter as tk
from tkinter import ttk
from background_sale import BackgroundSession
from equipment import WEAPONS, sale_plan


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('追忆 · 武器批量出售 v3.1')
        self.geometry('710x540')
        self.item = tk.StringVar(value='清单内全部武器')
        self.mode = tk.StringVar(value='老兵传送到武器店，再出售')
        self.cancel = threading.Event()
        self.busy = False
        self.protocol('WM_DELETE_WINDOW', self.close_app)
        frame = ttk.Frame(self, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='靠近老兵 → 商店传送 → 卖完清单内武器', font=('Microsoft YaHei UI', 13)).pack(anchor='w')
        ttk.Label(frame, text='后台窗口消息，不抢前台或移动鼠标。游戏保持打开，避免同时操作游戏。').pack(anchor='w', pady=8)
        ttk.Label(frame, text='支持1024×768游戏逻辑客户区及Windows缩放；不同游戏分辨率会停止。').pack(anchor='w')
        self.item_box = ttk.Combobox(frame, textvariable=self.item, values=['清单内全部武器'] + sorted(WEAPONS), state='readonly')
        self.item_box.pack(fill='x', pady=8)
        self.mode_box = ttk.Combobox(frame, textvariable=self.mode, values=[
            '老兵传送到武器店，再出售', '武器商人菜单已打开', '出售窗口已打开'], state='readonly')
        self.mode_box.pack(fill='x')
        self.preview = ttk.Button(frame, text='只读检查背包、NPC及布局', command=lambda: self.run(False))
        self.preview.pack(fill='x', pady=8)
        self.start = ttk.Button(frame, text='开始出售', command=lambda: self.run(True))
        self.start.pack(fill='x')
        self.stop = ttk.Button(frame, text='停止 / 也可按 Esc', command=self.cancel.set, state='disabled')
        self.stop.pack(fill='x', pady=8)
        self.status = tk.StringVar(value='等待操作')
        ttk.Label(frame, textvariable=self.status).pack(anchor='w')
        self.output = tk.Text(frame, height=13, wrap='word')
        self.output.pack(fill='both', expand=True, pady=8)
        self.write('默认卖完清单内12种武器（含木剑），其他部位保留；也可选一种武器只卖一件。\n老兵显示不全时，自动打开世界地图寻路；需在老兵附近30格内。\n点击已适度放慢。英雄头像挡住菜单时提示，不拖动头像。\n没有加入自动回城及其他商店出售。')

    def write(self, value):
        self.output.delete('1.0', 'end')
        self.output.insert('end', value)

    def close_app(self):
        if self.busy:
            self.cancel.set()
            self.status.set('正在停止，待当前点击松开后可关闭窗口')
        else: self.destroy()

    def run(self, execute):
        if self.busy: return
        item, mode = self.item.get(), self.mode.get()
        if item == '清单内全部武器': item = None
        self.busy = True
        self.cancel.clear()
        for widget in (self.start, self.preview, self.item_box, self.mode_box): widget.configure(state='disabled')
        self.stop.configure(state='normal')
        self.status.set('正在连接游戏…')
        def progress(message): self.after(0, self.status.set, message)
        def work():
            session = None
            try:
                session = BackgroundSession()
                session.cancelled = self.cancel.is_set
                if not execute:
                    result = {'mode': '只读检查，没有点击', 'state': session.state(),
                              'plan': sale_plan(session.inventory()), 'npcs': session.npcs(), 'layout': session.profile()}
                elif mode == '老兵传送到武器店，再出售':
                    result = session.teleport_weapon_sale(item, progress)
                else:
                    session.profile()
                    if mode == '武器商人菜单已打开' and not session.menu_matches('sell_weapon'):
                        raise RuntimeError('当前菜单不是已校准的武器商人菜单')
                    if item is None:
                        if mode == '武器商人菜单已打开':
                            session.menu_click('sell_weapon')
                            session.wait(lambda: session.visible('sell') and session.visible('bag'))
                        result = session.sell_all_weapons(progress)
                    else:
                        result = session.submit_one(item, 'menu' if mode == '武器商人菜单已打开' else 'sale')
            except Exception as error:
                result = {'error': str(error), 'completed': getattr(session, 'sales', [])}
            finally:
                if session: session.close()
            directory = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
            try: (directory / '快速出售最近结果.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
            except OSError: pass
            self.after(0, finish, result)
        def finish(result):
            self.busy = False
            self.write(json.dumps(result, ensure_ascii=False, indent=2))
            self.status.set('已停止：' + result['error'] if 'error' in result else '本次流程结束，请核对游戏金币提示')
            for widget in (self.start, self.preview): widget.configure(state='normal')
            for widget in (self.item_box, self.mode_box): widget.configure(state='readonly')
            self.stop.configure(state='disabled')
        threading.Thread(target=work, daemon=True).start()


if __name__ == '__main__': App().mainloop()
