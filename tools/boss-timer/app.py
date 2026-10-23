import os
import json
from pathlib import Path
import queue
import shutil
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
import winsound

from engine import DEFAULT_RULES, DEFAULT_GUARD_NAMES, TRACKED_EQUIPMENT, MemoryReader, TimerStore, parse_text, spawn_limit, READY_SECONDS
from structured_reader import StructuredReader

ROOT = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent


class App(tk.Tk):
    def __init__(self, use=None):
        super().__init__(use=use)
        self.title('追忆 · BOSS 刷新倒计时 3.1')
        self.geometry('1040x700')
        self.minsize(850, 520)
        self.configure(bg='#eef2f7')
        # Import only the clean v3 format. Never import the legacy 2.x records.
        previous = next((ROOT.parent / version / 'data' for version in ('追忆BOSS倒计时3.0.5', '追忆BOSS倒计时3.0.4', '追忆BOSS倒计时3.0.3', '追忆BOSS倒计时3.0.2', '追忆BOSS倒计时3.0.1', '追忆BOSS倒计时3.0')
                         if (ROOT.parent / version / 'data' / 'state.json').exists()), ROOT / 'missing')
        if not (ROOT / 'data' / 'state.json').exists() and previous.parent != ROOT and (previous / 'state.json').exists():
            (ROOT / 'data').mkdir(parents=True, exist_ok=True)
            for name in ('state.json', 'preferences.json', '装备掉落记录.csv', '掉落记录.jsonl', '待核对事件.jsonl', '人工死亡记录.jsonl'):
                if (previous / name).exists():
                    shutil.copy2(previous / name, ROOT / 'data' / name)
        data=Path(os.environ.get('MIR_BOSS_TIMER_DATA',str(ROOT/'data')))
        if not (data/'state.json').exists() and os.environ.get('MIR_BOSS_TIMER_DATA'):
            candidates=list((Path(__file__).resolve().parents[2]/'outputs').glob('追忆BOSS倒计时3*/**/data/state.json'))
            if (ROOT/'data'/'state.json').exists():candidates.append(ROOT/'data'/'state.json')
            if candidates:
                prior=max(candidates,key=lambda p:p.stat().st_mtime).parent
                data.mkdir(parents=True,exist_ok=True)
                for source in prior.iterdir():
                    if source.is_file() and source.suffix in ('.json','.jsonl','.csv') and not (data/source.name).exists():
                        shutil.copy2(source,data/source.name)
        self.store = TimerStore(data)
        self.mail = queue.Queue()
        self.stop_event = threading.Event()
        self.worker = None
        self.notified = set()
        self.waiting = {}
        self.baseline_count = 0
        self.new_event_count = 0
        self.connection_state = None
        self.last_scan_at = None
        self.last_notice_at = None
        self.selected_pid = None
        self.selected_title = None
        self.guard_names = list(DEFAULT_GUARD_NAMES)
        try:
            prefs = json.loads((self.store.folder / 'preferences.json').read_text(encoding='utf-8'))
            self.guard_names = prefs.get('guard_names', self.guard_names)
        except (FileNotFoundError, ValueError):
            pass
        self.status = tk.StringVar(value='尚未连接 · 请保持游戏角色在线')
        self.search = tk.StringVar()
        self.sound = tk.BooleanVar(value=True)
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 10))
        style.configure('TFrame', background='#eef2f7')
        style.configure('TLabel', background='#eef2f7', foreground='#182b45')
        style.configure('Muted.TLabel', foreground='#697b91')
        style.configure('Title.TLabel', font=('Microsoft YaHei UI', 22, 'bold'))
        style.configure('TButton', padding=(13, 8),background='#ffffff',foreground='#223952')
        style.configure('TCheckbutton', background='#eef2f7', foreground='#344b66')
        style.map('TCheckbutton', background=[('active', '#eef2f7')])
        style.configure('Treeview', background='#ffffff', fieldbackground='#ffffff', foreground='#263e59', rowheight=36, borderwidth=0)
        style.configure('Treeview.Heading', background='#e2e9f2', foreground='#385371', padding=9)
        style.map('Treeview', background=[('selected', '#dce9ff')],foreground=[('selected','#173c76')])
        style.configure('TNotebook.Tab',padding=(18,9))
        top = ttk.Frame(self, padding=(24, 22, 24, 10))
        top.pack(fill='x')
        ttk.Label(top, text='BOSS 刷新倒计时', style='Title.TLabel').pack(anchor='w')
        ttk.Label(top, text='新掉落公告 → 按地图分别计时 → 到点显示已刷新', style='Muted.TLabel').pack(anchor='w', pady=(5, 15))
        bar = ttk.Frame(top)
        bar.pack(fill='x')
        self.start_button = ttk.Button(bar, text='开始监听', command=self.start)
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(bar, text='停止', command=self.stop, state='disabled')
        self.stop_button.pack(side='left', padx=8)
        ttk.Button(bar, text='刷新时间设置', command=self.settings).pack(side='left')
        ttk.Button(bar, text='清空数据', command=self.clear_data).pack(side='left', padx=8)
        ttk.Button(bar, text='打开记录目录', command=lambda: os.startfile(str(self.store.folder))).pack(side='left', padx=8)
        ttk.Checkbutton(bar, text='到点声音提示', variable=self.sound).pack(side='right')
        ttk.Label(top, textvariable=self.status, style='Muted.TLabel').pack(anchor='w', pady=(14, 4))
        options = ttk.Frame(top)
        options.pack(fill='x', pady=(5, 0))
        self.pick_button = ttk.Button(options, text='选择角色', command=self.pick_game)
        self.pick_button.pack(side='left')
        self.guard_button = ttk.Button(options, text='其他游戏保护名单', command=self.guard_settings)
        self.guard_button.pack(side='left', padx=8)
        ttk.Button(options, text='粘贴公告计时（不读内存）', command=self.paste_notice).pack(side='left')
        ttk.Button(options, text='手动记死亡', command=self.manual_death).pack(side='left', padx=8)
        self.target_text = tk.StringVar(value='目标：自动识别本服角色窗口；多开时请手动选择')
        ttk.Label(top, textvariable=self.target_text, style='Muted.TLabel').pack(anchor='w', pady=(7, 0))
        search_bar = ttk.Frame(self, padding=(24, 5, 24, 10))
        search_bar.pack(fill='x')
        ttk.Label(search_bar, text='筛选地图 / 怪物 / 装备').pack(side='left', padx=(0, 12))
        ttk.Entry(search_bar, textvariable=self.search, width=32).pack(side='left')
        ttk.Label(search_bar, text='首次连接忽略旧公告', style='Muted.TLabel').pack(side='right')
        notebook = ttk.Notebook(self)
        notebook.pack(fill='both', expand=True, padx=24)
        box = ttk.Frame(notebook)
        notebook.add(box, text='BOSS 倒计时')
        columns = ('map', 'monster', 'slot', 'remaining', 'death', 'due', 'interval', 'source')
        self.tree = ttk.Treeview(box, columns=columns, show='headings', selectmode='browse')
        for key, label, width in zip(columns, ['地图', '怪物', '计时位', '状态 / 倒计时', '记录时间', '预计刷新', '间隔', '依据'], [140, 150, 60, 130, 95, 95, 75, 110]):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=70, anchor='w')
        scroll = ttk.Scrollbar(box, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.tree.tag_configure('ready', foreground='#16754b')
        self.tree.tag_configure('soon', foreground='#a35a10')
        self.tree.tag_configure('unset', foreground='#7c8999')
        self.tree.bind('<Double-1>', self.selected_settings)
        equipment_box = ttk.Frame(notebook, padding=8)
        notebook.add(equipment_box, text='装备掉落记录')
        self.equipment_summary = tk.StringVar()
        ttk.Label(equipment_box, textvariable=self.equipment_summary, style='Muted.TLabel').pack(anchor='w', pady=(2, 8))
        equipment_body = ttk.Frame(equipment_box)
        equipment_body.pack(fill='both', expand=True)
        eq_columns = ('time', 'map', 'monster', 'item', 'source')
        self.equipment_tree = ttk.Treeview(equipment_body, columns=eq_columns, show='headings')
        for key, label, width in zip(eq_columns, ['发现时间', '地图', '怪物', '装备', '来源'], [165, 170, 200, 185, 100]):
            self.equipment_tree.heading(key, text=label)
            self.equipment_tree.column(key, width=width, minwidth=70)
        eq_scroll = ttk.Scrollbar(equipment_body, orient='vertical', command=self.equipment_tree.yview)
        self.equipment_tree.configure(yscrollcommand=eq_scroll.set)
        self.equipment_tree.pack(side='left', fill='both', expand=True)
        eq_scroll.pack(side='right', fill='y')
        self.equipment_cache = None
        self.detail = tk.StringVar(value='全新记录：只接收开始监听之后的完整带时间公告，不导入旧地图。')
        foot = ttk.Frame(self, padding=(24, 12, 24, 18))
        foot.pack(side='bottom',fill='x',before=notebook)
        ttk.Label(foot, textvariable=self.detail, wraplength=940).pack(anchor='w')
        ttk.Label(foot, text='同批掉落合并计时；超量公告保留待核对。计时位不代表已识别怪物个体，刷新时间为估计。', style='Muted.TLabel').pack(anchor='w', pady=(8, 0))
        self.search.trace_add('write', lambda *_: self.render())
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(150, self.pump)
        self.render()
        if self.store.load_error:
            self.after(300, lambda: messagebox.showwarning('配置读取提示', self.store.load_error))
        if '--no-start' not in sys.argv:
            self.after(500, self.auto_start)

    def auto_start(self):
        reader=MemoryReader()
        try:
            if len(reader.candidates())>1:
                self.status.set('双角色在线：先选择一个角色监听，全服公告只需监听一份')
                return
        finally:reader.close()
        self.start()

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.stop_event = threading.Event()
        if self.store.monitoring_since is None:
            self.store.monitoring_since = time.time()
        self.store.ready = True
        self.start_button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        self.pick_button.configure(state='disabled')
        self.guard_button.configure(state='disabled')
        self.status.set('正在寻找游戏进程…')
        self.worker = threading.Thread(target=self.watch, daemon=True)
        self.worker.start()

    def watch(self):
        reader = StructuredReader()
        last_full = 0
        first = True
        chosen = self.selected_pid
        chosen_title = self.selected_title
        guarded = tuple(self.guard_names)
        class GuardStop(Exception):
            pass
        def check_guard():
            matched = reader.guard_matches(guarded)
            if matched:
                raise GuardStop('检测到保护名单进程：' + '、'.join(matched) + '。已停止并释放游戏访问权限；关闭其他游戏后请手动重新开始。')
        try:
            while not self.stop_event.is_set():
                check_guard()
                if not reader.alive():
                    if reader.pid is not None:
                        self.mail.put(('connection', {'state': '进程退出或读取连接失效', 'pid': reader.pid}))
                    reader.close()
                    game = reader.find_game(chosen)
                    if not game and chosen_title:
                        matches = [g for g in reader.candidates() if g[1] == chosen_title]
                        if len(matches) == 1:
                            game = matches[0]
                    if not game:
                        self.mail.put(('connection', {'state': '等待角色窗口', 'selected_pid': chosen}))
                        self.mail.put(('status', '等待游戏登录… 已有倒计时会继续'))
                        self.stop_event.wait(3)
                        continue
                    reader.connect(game[0])
                    chosen_title = self.selected_title = game[1]
                    if chosen is not None:
                        chosen = self.selected_pid = game[0]
                    self.mail.put(('connection', {'state': '已连接', 'pid': game[0]}))
                    first = True
                    last_full = 0
                    self.mail.put(('status', '已连接 PID ' + str(game[0]) + ' · 正在建立旧公告基线…'))
                full = first or (not reader.discovery_pending and time.monotonic() - last_full > (45 if reader.chat_regions else 15))
                notices = reader.scan(full=full, stop=self.stop_event, guard=check_guard)
                if self.stop_event.is_set():
                    break
                if full:
                    last_full = time.monotonic()
                if first:
                    self.mail.put(('initial_count', len(notices)))
                    first = False
                self.mail.put(('notices', (notices, time.time())))
                self.mail.put(('status', f'结构消息监听 · {reader.scan_phase} · PID {reader.pid} · {len(notices)} 条公告 · 本轮 {reader.last_scan_seconds:.2f}秒 / {reader.last_scan_bytes / 1048576:.1f} MiB · ' + time.strftime('%H:%M:%S')))
                self.stop_event.wait(1.5)
        except GuardStop as error:
            self.mail.put(('connection', {'state': '保护名单停止', 'reason': str(error)}))
            self.mail.put(('guarded', str(error)))
        except Exception as error:
            self.mail.put(('connection', {'state': '读取异常停止', 'reason': str(error)}))
            self.mail.put(('error', str(error)))
        finally:
            reader.close()
            self.mail.put(('stopped', None))

    def stop(self):
        self.mail.put(('connection', {'state': '用户停止监听'}))
        self.stop_event.set()
        self.status.set('正在停止读取…')

    def pump(self):
        try:
            while True:
                kind, payload = self.mail.get_nowait()
                if kind == 'connection':
                    if payload != self.connection_state:
                        self.connection_state = payload
                        with (self.store.folder / '连接日志.jsonl').open('a', encoding='utf-8') as output:
                            output.write(json.dumps(dict(at=time.time(), **payload), ensure_ascii=False) + '\n')
                elif kind == 'initial_count':
                    self.baseline_count = payload
                    self.waiting = {}
                    self.detail.set(f'定位到 {payload} 条带时间公告；开始监听之前的消息不会建立地图或计时。')
                elif kind == 'guarded':
                    self.status.set(payload)
                    self.detail.set('保护已触发：停止内存访问，已有倒计时继续。保护名单并不能覆盖所有游戏。')
                elif kind == 'notices':
                    notices, observed = payload
                    self.last_scan_at = observed
                    records = self.store.consume(notices, observed)
                    self.new_event_count += len(records)
                    if records:
                        self.last_notice_at = max(r['observed_at'] for r in records)
                        record = records[-1]
                        self.detail.set(time.strftime('%H:%M:%S', time.localtime(record['observed_at'])) + '  ' + record['text'])
                        for r in records:
                            key = r['map'] + '\t' + r['monster']
                            if r.get('slot', 1) > 1:
                                key += '\t' + str(r['slot'])
                            self.notified.discard(key)
                elif kind == 'status':
                    self.status.set(payload)
                elif kind == 'error':
                    self.status.set('读取异常，5秒后重连：' + payload)
                    self.after(5000, self.retry_reading)
                elif kind == 'stopped':
                    self.start_button.configure(state='normal')
                    self.stop_button.configure(state='disabled')
                    self.pick_button.configure(state='normal')
                    self.guard_button.configure(state='normal')
                    if self.stop_event.is_set():
                        self.status.set('已停止读取 · 已有倒计时继续运行')
                (self.store.folder / '运行状态.json').write_text(json.dumps({
                    'status': self.status.get(), 'updated_at': time.time(),
                    'baseline_count': self.baseline_count, 'new_event_count': self.new_event_count,
                    'timer_count': len(self.store.records),
                    'version': '3.1', 'connection': self.connection_state,
                    'last_scan_at': self.last_scan_at, 'last_notice_at': self.last_notice_at,
                }, ensure_ascii=False, indent=2), encoding='utf-8')
        except queue.Empty:
            pass
        except Exception as error:
            self.stop_event.set()
            self.status.set('保存或处理失败：' + str(error))
        self.render()
        self.after(400, self.pump)

    def retry_reading(self):
        if not self.stop_event.is_set():
            self.start()

    def clear_data(self):
        if not messagebox.askyesno('清空数据', '清空全部计时、装备掉落和人工死亡记录？\n刷新规则和设置会保留，监听可继续。', parent=self):
            return
        self.store.clear_data()
        self.waiting.clear()
        self.notified.clear()
        self.new_event_count = 0
        self.equipment_cache = None
        self.detail.set('数据已清空，从此刻之后的新公告重新记录。')
        self.render()

    def render(self):
        self.render_equipment()
        now = time.time()
        for key in self.store.prune_expired(now):
            self.notified.discard(key)
        query = self.search.get().strip()
        records = dict(self.waiting)
        records.update(self.store.records)
        wanted = set()
        ordered = sorted(records.items(), key=lambda pair: (pair[1].get('due_at') or float('inf'), pair[1]['map'], pair[1]['monster']))
        for index, (key, record) in enumerate(ordered):
            if query and query not in record['map'] and query not in record['monster']:
                continue
            wanted.add(key)
            minutes = self.store.rules.get(record['monster'], 0)
            due = record.get('due_at')
            observed = record.get('observed_at')
            tag = ''
            if observed is None:
                remaining, tag = '等待新掉落', 'unset'
            elif due is None:
                remaining, tag = '刷新时间未设置', 'unset'
            elif now > due + READY_SECONDS:
                remaining, tag = '超时（未收到新掉落）', 'unset'
                self.notified.add(key)
            elif due <= now:
                remaining, tag = '预计已刷新', 'ready'
                if key not in self.notified:
                    self.notified.add(key)
                    self.detail.set(record['map'] + ' · ' + record['monster'] + ' 已到预计刷新时间')
                    if self.sound.get():
                        winsound.MessageBeep(winsound.MB_OK)
            else:
                seconds = max(0, int(due - now + .999))
                remaining = f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'
                if seconds < 300:
                    tag = 'soon'
            clock = lambda value: time.strftime('%H:%M:%S', time.localtime(value)) if value else '—'
            values = (record['map'], record['monster'], record.get('slot', 1), remaining, clock(observed), clock(due), str(minutes) + ' 分钟' if minutes else '未设置', record.get('source', '公告'))
            if self.tree.exists(key):
                self.tree.item(key, values=values, tags=(tag,))
                self.tree.move(key, '', index)
            else:
                self.tree.insert('', 'end', iid=key, values=values, tags=(tag,))
        for key in self.tree.get_children():
            if key not in wanted:
                self.tree.delete(key)

    def render_equipment(self):
        query = self.search.get().strip()
        version = (len(self.store.equipment), query)
        if self.equipment_cache == version:
            return
        self.equipment_cache = version
        rows = [r for r in self.store.equipment if not query or any(query in r.get(k, '') for k in ('地图', '怪物', '装备'))]
        self.equipment_tree.delete(*self.equipment_tree.get_children())
        for row in reversed(rows[-2000:]):
            self.equipment_tree.insert('', 'end', values=tuple(row.get(k, '') for k in ('发现时间', '地图', '怪物', '装备', '来源')))
        self.equipment_summary.set(f'关注 {len(TRACKED_EQUIPMENT)} 种装备 · 已记录 {len(self.store.equipment)} 条 · 筛选 {len(rows)} 条（最多显示最近2000条）· CSV保留全部记录')

    def selected_settings(self, event=None):
        selected = self.tree.selection()
        name = self.tree.item(selected[0], 'values')[1] if selected else None
        self.settings(name)

    def pick_game(self):
        reader = MemoryReader()
        try:
            candidates = reader.candidates()
        finally:
            reader.close()
        if not candidates:
            messagebox.showinfo('未找到角色窗口', '请先登录本服角色。识别窗口标题，不依赖随机程序名。')
            return
        window = tk.Toplevel(self)
        window.title('选择本次监听的角色')
        window.geometry('780x220')
        window.transient(self)
        window.grab_set()
        frame = ttk.Frame(window, padding=20)
        frame.pack(fill='both', expand=True)
        labels = [f'PID {pid} | {exe} | {title}' for pid, title, exe in candidates]
        choice = ttk.Combobox(frame, values=labels, state='readonly', width=92)
        choice.pack(fill='x', pady=12)
        choice.current(0)
        def select():
            pid, title, exe = candidates[choice.current()]
            self.selected_pid = pid
            self.target_text.set(f'目标：{title} · PID {pid} · {exe}')
            window.destroy()
            self.start()
        ttk.Button(frame, text='使用此角色', command=select).pack(anchor='e')
        ttk.Label(frame, text='重新登录后只重连标题完全相同的角色；不会切换其他角色。', style='Muted.TLabel').pack(anchor='w', pady=10)

    def guard_settings(self):
        window = tk.Toplevel(self)
        window.title('其他游戏保护名单')
        window.geometry('610x440')
        window.transient(self)
        window.grab_set()
        frame = ttk.Frame(window, padding=20)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='每行填写一个游戏进程名（包含 .exe），检测到后停止读取。').pack(anchor='w')
        ttk.Label(frame, text='仅按进程名匹配，名单不完整，也不代表能避免反作弊检测。', style='Muted.TLabel').pack(anchor='w', pady=8)
        text = tk.Text(frame, height=12, font=('Consolas', 11))
        text.pack(fill='both', expand=True)
        text.insert('1.0', '\n'.join(self.guard_names))
        def save():
            names = list(dict.fromkeys(line.strip() for line in text.get('1.0', 'end').splitlines() if line.strip()))
            if any(not name.lower().endswith('.exe') or '\\' in name or '/' in name for name in names):
                messagebox.showerror('进程名格式', '请填写进程名，例如 TslGame.exe，不要填写完整路径。', parent=window)
                return
            self.guard_names = names
            (self.store.folder / 'preferences.json').write_text(json.dumps({'guard_names': names}, ensure_ascii=False, indent=2), encoding='utf-8')
            window.destroy()
        ttk.Button(frame, text='保存', command=save).pack(anchor='e', pady=10)

    def paste_notice(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo('先停止监听', '请先点击“停止”，再使用不读内存的公告输入模式。')
            return
        window = tk.Toplevel(self)
        window.title('粘贴新公告 · 不访问游戏内存')
        window.geometry('680x320')
        window.transient(self)
        window.grab_set()
        frame = ttk.Frame(window, padding=20)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='粘贴刚出现的掉落公告，每行一条；以提交时间开始计时。').pack(anchor='w', pady=(0, 10))
        text = tk.Text(frame, height=8, font=('Microsoft YaHei UI', 11))
        text.pack(fill='both', expand=True)
        def submit():
            notices = []
            for line in text.get('1.0', 'end').splitlines():
                notices.extend(parse_text(line))
            if not notices:
                messagebox.showerror('未识别到公告', '格式示例：牛魔七层的牛魔王掉落：裁决之杖', parent=window)
                return
            before_equipment = len(self.store.equipment)
            records = self.store.accept_manual(notices)
            self.new_event_count += len(records)
            self.detail.set(f'已更新 {len(records)} 条计时、记录 {len(self.store.equipment) - before_equipment} 条装备；同次掉落分别记录装备。')
            self.notified.difference_update(r['map'] + '\t' + r['monster'] for r in records)
            self.render()
            window.destroy()
        ttk.Button(frame, text='提交并计时', command=submit).pack(anchor='e', pady=10)

    def manual_death(self):
        selected = self.tree.selection()
        record = self.store.records.get(selected[0], {}) if selected else {}
        window = tk.Toplevel(self)
        window.title('人工确认死亡 · 无需掉落公告')
        window.geometry('530x350')
        window.transient(self)
        window.grab_set()
        frame = ttk.Frame(window, padding=20)
        frame.pack(fill='both', expand=True)
        map_name = tk.StringVar(value=record.get('map', '石墓七层'))
        monster = tk.StringVar(value=record.get('monster', '白野猪[精英]'))
        slot = tk.StringVar(value=str(record.get('slot', 1)))
        elapsed = tk.StringVar(value='0')
        for row, label in enumerate(('地图', '怪物', '计时位', '几分钟前死亡')):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', pady=8)
        ttk.Entry(frame, textvariable=map_name, width=28).grid(row=0, column=1)
        ttk.Combobox(frame, textvariable=monster, values=list(DEFAULT_RULES), state='readonly', width=26).grid(row=1, column=1)
        ttk.Combobox(frame, textvariable=slot, values=(1,2,3,4), state='readonly', width=26).grid(row=2, column=1)
        ttk.Entry(frame, textvariable=elapsed, width=28).grid(row=3, column=1)
        ttk.Label(frame, text='石墓七层精英白野猪4位，牛魔大厅牛魔王1位，其他组合默认2位。\n请依据亲眼确认的死亡填写，0表示刚刚死亡。', style='Muted.TLabel').grid(row=4, column=0, columnspan=2, pady=10)
        def submit():
            try:
                minutes = float(elapsed.get())
                if not 0 <= minutes <= 1440:
                    raise ValueError('死亡时间请输入0至1440分钟')
                key = self.store.mark_death(map_name.get().strip(), monster.get(), int(slot.get()), time.time()-minutes*60)
            except ValueError as error:
                messagebox.showerror('无法记录', str(error), parent=window)
                return
            self.notified.discard(key)
            self.detail.set('已按人工确认的死亡时间计时；没有生成装备掉落记录。')
            self.render()
            window.destroy()
        ttk.Button(frame, text='确认死亡并计时', command=submit).grid(row=5, column=1, sticky='e')

    def settings(self, selected=None):
        window = tk.Toplevel(self)
        window.title('刷新时间设置')
        window.geometry('490x265')
        window.configure(bg='#eef2f7')
        window.transient(self)
        window.grab_set()
        frame = ttk.Frame(window, padding=24)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='怪物').grid(row=0, column=0, sticky='w', pady=8)
        name = tk.StringVar(value=selected or next(iter(DEFAULT_RULES)))
        choice = ttk.Combobox(frame, textvariable=name, values=list(DEFAULT_RULES), state='readonly', width=27)
        choice.grid(row=0, column=1, sticky='w')
        minutes = tk.StringVar(value=str(self.store.rules[name.get()]))
        choice.bind('<<ComboboxSelected>>', lambda _: minutes.set(str(self.store.rules[name.get()])))
        ttk.Label(frame, text='刷新分钟数').grid(row=1, column=0, sticky='w', pady=8)
        ttk.Entry(frame, textvariable=minutes, width=15).grid(row=1, column=1, sticky='w')
        ttk.Label(frame, text='60 = 1小时；120 = 2小时；0 = 未设置', style='Muted.TLabel').grid(row=2, column=0, columnspan=2, sticky='w', pady=10)
        def save():
            try:
                value = int(minutes.get())
                if not 0 <= value <= 10080:
                    raise ValueError()
            except ValueError:
                messagebox.showerror('请输入分钟数', '请输入 0 至 10080 的整数。', parent=window)
                return
            self.store.update_rule(name.get(), value)
            self.notified.clear()
            window.destroy()
            self.render()
        ttk.Button(frame, text='保存', command=save).grid(row=3, column=1, sticky='e', pady=10)

    def close(self):
        self.stop_event.set()
        self.store.save()
        self.destroy()


if __name__ == '__main__':
    app=App(use=os.environ.get('MIR_TOOL_EMBED_PARENT'))
    if os.environ.get('MIR_TOOL_EMBED_PARENT'):
        Path(os.environ['MIR_TOOL_EMBED_READY']).write_text('ready',encoding='utf8')
        def check_host():
            if Path(os.environ['MIR_TOOL_EMBED_SHUTDOWN']).exists():
                app.stop_event.set()
                if not app.worker or not app.worker.is_alive():app.close();return
            app.after(300,check_host)
        app.after(300,check_host)
    app.mainloop()
