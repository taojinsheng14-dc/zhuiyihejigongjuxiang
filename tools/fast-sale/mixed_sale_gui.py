import json
from pathlib import Path
import sys
import threading
import queue
import time
from dataclasses import asdict
import tkinter as tk
from tkinter import ttk, messagebox

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(Path(__file__).resolve().parent))
import instance_context
import toolbox_theme
SOURCE_HELPER=ROOT/'tools'/'game-chat-inspect'
ROOT=instance_context.runtime_root(ROOT)
HELPER=instance_context.helper_directory()
HELPER.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(SOURCE_HELPER))
from source_driver import drive
from equipment import sale_plan
from profit_tracker import ProfitTracker
from random_hunt import load_settings,save_settings,RandomSettings

BUILD='2026.10.24.11'

def active_task(command,result,sample,now):
    step=command.get('step')
    if not isinstance(step,int) or step<=result.get('step',0):return None
    if command.get('categories') not in (['挂机清包循环'],['接续当前挂机图循环'],['监测并回城出售'],['监测双包'],['孤岛每日自动挑战'],['接续孤岛自动挑战'],['法师地牢持续清怪拾取'],['法师当前地图持续挂机']):return None
    if not sample.get('ok') or not 0<=now-sample.get('observed_epoch',0)<=3:return None
    if sample.get('game_pid')!=result.get('state',{}).get('game_pid'):return None
    return step

class App(tk.Tk):
    def __init__(self, use=None):
        super().__init__(use=use)
        toolbox_theme.apply(self)
        self.title('追忆 · 账号'+instance_context.slot()+' · 自动清包 '+BUILD+' 测试版')
        self.geometry('1120x760');self.busy=False;self.cancel=threading.Event()
        self.profit=ProfitTracker(ROOT/'outputs'/'挂机统计')
        self.profit_event_offset=0
        self.profit_auto=False
        self.attached_step=None
        self.messages=queue.Queue()
        self.mode=tk.StringVar(value='盟重武器 → 苍月首饰、衣服、头盔')
        self.foreground=tk.BooleanVar(value=False)
        self.status=tk.StringVar(value='路线及菜单已验证；等待操作')
        self.wallet=tk.StringVar(value='金币/元宝：等待读取')
        self.binding_label=tk.StringVar(value=self.binding_summary())
        self.protocol('WM_DELETE_WINDOW',self.close_window)
        header=ttk.Frame(self,padding=(18,10,18,2));header.pack(fill='x')
        ttk.Label(header,text='账号'+instance_context.slot(),style='Title.TLabel').pack(side='left')
        ttk.Label(header,textvariable=self.binding_label,style='Subtitle.TLabel').pack(side='left',padx=16)
        body=ttk.Frame(self);body.pack(fill='both',expand=True)
        panel=ttk.Frame(body,padding=18);panel.pack(side='left',fill='both',expand=True)
        self.tabs=ttk.Notebook(panel);self.tabs.pack(fill='x',pady=(0,8))
        main_tab=ttk.Frame(self.tabs,padding=10)
        test_tab=ttk.Frame(self.tabs,padding=10)
        self.tabs.add(main_tab,text='日常操作')
        self.tabs.add(test_tab,text='高级测试')
        island_tab=ttk.Frame(self.tabs,padding=10);self.tabs.add(island_tab,text='孤岛挑战')
        self.tabs.insert(1,island_tab)
        settings_tab=ttk.Frame(self.tabs,padding=10);self.tabs.insert(2,settings_tab,text='角色设置')
        dungeon_tab=ttk.Frame(self.tabs,padding=10);self.tabs.insert(2,dungeon_tab,text='地图挂机')
        ttk.Label(dungeon_tab,text='法师主体 · 当前已核对地图',font=('Microsoft YaHei UI',14,'bold')).pack(anchor='w')
        ttk.Label(dungeon_tab,text='厚礼蟹 · F1雷电术 · 后台沿可达路线清怪、按名单拾取。\n支持地牢东一层、石墓五层；需自行到图，启动不会传送或购买。',wraplength=560,style='Subtitle.TLabel').pack(anchor='w',pady=(8,12))
        self.dungeon_start_button=ttk.Button(dungeon_tab,text='启动／接续当前地图挂机',style='Primary.TButton',command=lambda:self.run('mage_dungeon'))
        self.dungeon_start_button.pack(fill='x',pady=(0,10))
        ttk.Label(dungeon_tab,text='持续运行，单次最长12小时；沿图走完一圈继续巡逻。\n打开背包、未知提示或双包满时会安全停止。关闭面板后可重新启动；停止使用下方“停止本号任务”。',wraplength=560).pack(anchor='w',pady=(0,12))
        self.dungeon_status=tk.StringVar(value='尚无地图挂机运行记录')
        ttk.Label(dungeon_tab,textvariable=self.dungeon_status,wraplength=560,style='Status.TLabel').pack(fill='x')
        self.last_dungeon_refresh=0
        self.last_binding_refresh=0
        self.available_roles=tk.StringVar(value='正在读取当前角色…')
        ttk.Label(settings_tab,textvariable=self.available_roles,wraplength=580).pack(anchor='w',pady=(0,8))
        ttk.Label(island_tab,text='手动开始 · 优先拾取\n微笑战士：主体单击近战＋英雄；厚礼蟹法师：F1雷电术＋英雄。\n手动开始不受本机日期记录阻挡；游戏是否允许入场由服务器决定。\n接续挑战不会重新入场，完整无人干预流程仍待验证。',wraplength=560,style='Subtitle.TLabel').pack(anchor='w',pady=10)
        self.island_buttons=[]
        for label,action in [('从土城进入并自动挑战（手动开始）','island_start'),('接续已进入的孤岛','island_resume'),('只读检查孤岛记录','island_status')]:
            button=ttk.Button(island_tab,text=label,command=lambda selected=action:self.run(selected))
            button.pack(fill='x',pady=4);self.island_buttons.append(button)

        ttk.Label(test_tab,text='单项验证：每次执行一项，完成后再进行下一项。').pack(anchor='w',pady=(0,8))
        ttk.Label(test_tab,text='按当前客户区和实时控件定位；固定传送测试不识别菜单截图，到达后核对地图和NPC。',wraplength=650).pack(anchor='w',pady=(0,8))
        ttk.Label(main_tab,text='挂机与清包',font=('Microsoft YaHei UI',14,'bold')).pack(anchor='w')
        ttk.Label(main_tab,text='按白名单出售双包；回城石放快捷栏1—6。',style='Subtitle.TLabel').pack(anchor='w',pady=(4,8))
        ttk.Label(settings_tab,textvariable=self.binding_label,wraplength=580).pack(anchor='w',pady=(0,8))
        ttk.Button(settings_tab,text='选择／更换本号角色',command=self.choose_game).pack(fill='x',pady=(7,0))
        ttk.Button(settings_tab,text='配置本号加密登录信息',command=self.configure_login).pack(fill='x',pady=(7,0))
        self.connect_button=ttk.Button(settings_tab,text='连接游戏（必要时请求管理员权限）',command=self.connect_game,style='Primary.TButton')
        self.connect_button.pack(fill='x',pady=(8,0))
        self.mode_box=ttk.Combobox(main_tab,textvariable=self.mode,state='readonly',values=[
            '盟重武器 → 苍月首饰、衣服、头盔','只在苍月出售首饰、衣服、头盔',
            '只验证路线和菜单，不出售（会产生传送费）'])
        self.mode_box.pack(fill='x',pady=12)
        ttk.Checkbutton(settings_tab,text='前台鼠标操作（双角色运行时使用后台操作）',variable=self.foreground).pack(anchor='w',pady=14)
        self.inspect_button=ttk.Button(test_tab,text='只检查双背包',command=lambda:self.run(False));self.inspect_button.pack(fill='x')
        ttk.Button(settings_tab,text='刷新坐标／怪物监控',command=self.open_live_monitor).pack(fill='x',pady=(7,0))
        ttk.Button(settings_tab,text='无怪随机设置（会消耗随机石）',command=self.random_settings).pack(fill='x',pady=(7,0))
        self.start_button=ttk.Button(main_tab,text='仅出售一轮（需已在城内或商店）',command=lambda:self.run(True));self.start_button.pack(fill='x',pady=7)
        self.recover_button=ttk.Button(test_tab,text='恢复登录（死亡或掉线后）',command=lambda:self.run('recover'));self.recover_button.pack(fill='x',pady=(0,7))
        self.monitor_button=ttk.Button(main_tab,text='监测双包 → 回城 → 出售（会使用回城石）',command=lambda:self.run('monitor'));self.monitor_button.pack(fill='x',pady=(0,7))
        self.hunt_button=ttk.Button(main_tab,text='启动挂机循环  ·  入场 → 满包出售 → 再进图',style='Primary.TButton',command=lambda:self.run('hunt'));self.hunt_button.pack(fill='x',pady=(0,7))
        self.resume_hunt_button=ttk.Button(main_tab,text='接续当前挂机图（不重新下图）',command=lambda:self.run('resume_hunt'));self.resume_hunt_button.pack(fill='x',pady=(0,7))
        self.pickup_button=ttk.Button(test_tab,text='开始拾取测试（2分钟，仅附近6格木剑）',command=lambda:self.run('pickup'));self.pickup_button.pack(fill='x',pady=(0,7))
        self.bag_test_button=ttk.Button(test_tab,text='背包仅后台测试（不切前台／不动鼠标／不按F9）',command=lambda:self.run('bag_background'));self.bag_test_button.pack(fill='x',pady=(0,7))
        self.login_bag_test_button=ttk.Button(test_tab,text='登录后后台打开背包测试（登录页使用）',command=lambda:self.run('login_bag_test'));self.login_bag_test_button.pack(fill='x',pady=(0,7))
        self.jewelry_menu_test_button=ttk.Button(test_tab,text='苍月首饰NPC（固定位置打开出售，不卖装备）',command=lambda:self.run('cangyue_jewelry_menu'))
        self.jewelry_menu_test_button.pack(fill='x',pady=(0,7))
        self.clothes_menu_test_button=ttk.Button(test_tab,text='苍月衣服NPC（固定位置打开出售，不卖装备）',command=lambda:self.run('cangyue_clothes_menu'))
        self.clothes_menu_test_button.pack(fill='x',pady=(0,7))
        self.weapon_transfer_test_button=ttk.Button(test_tab,text='传送到武器店（固定位置测试）',command=lambda:self.run('fixed_weapon_transfer'))
        self.weapon_transfer_test_button.pack(fill='x',pady=(0,7))
        self.cangyue_transfer_test_button=ttk.Button(test_tab,text='传送到苍月（固定位置测试，2000金币）',command=lambda:self.run('fixed_cangyue_transfer'))
        self.cangyue_transfer_test_button.pack(fill='x',pady=(0,7))
        ttk.Label(test_tab,text='从土城开始；只传送、不卖装备、不入场。重复测试请先回土城；已在目标地点时不重复传送。',wraplength=650).pack(anchor='w')
        self.town_test_button=ttk.Button(test_tab,text='土城完整流程测试（实际卖双包 → 打开下图菜单，不入场）',command=lambda:self.run('town_sale_entry_test'))
        self.town_test_button.pack(fill='x',pady=(0,7))
        ttk.Label(test_tab,text='需在土城；实际卖白名单装备，跨城传送仍扣金币。停在普通房间点击前，不扣入场元宝；空包不算验证成交。',wraplength=650).pack(anchor='w')
        self.stop_button=ttk.Button(panel,text='停止本号任务',style='Stop.TButton',command=self.request_stop,state='disabled');self.stop_button.pack(fill='x',pady=(8,0))
        ttk.Label(panel,textvariable=self.status,style='Status.TLabel',wraplength=620).pack(fill='x',pady=(8,2))
        ttk.Label(panel,textvariable=self.wallet).pack(anchor='w')
        ttk.Label(panel,text='本号操作记录',style='Subtitle.TLabel').pack(anchor='w',pady=(8,4))
        self.output=tk.Text(panel,height=7,wrap='word',font=('Microsoft YaHei UI',9),background='#ffffff',foreground='#314760',relief='flat',padx=10,pady=8);self.output.pack(fill='both',expand=True)
        self.output.insert('end','“开始”执行一轮双包出售；“挂机循环”会使用挂机时间和回城石。\n回城按名称选择盟重传送石；随机仅在设置开启后生效。\n请关闭游戏自动施法；停止按钮可中止。\n后台账号登录及服务器自动小退恢复已实测成功，长期完整循环仍待验证。')
        right_panel=ttk.LabelFrame(body,text='实时状态与统计',padding=8)
        right_panel.pack(side='right',fill='y',padx=(0,14),pady=18)
        self.status_tabs=ttk.Notebook(right_panel);self.status_tabs.pack(fill='both',expand=True)
        profit_panel=ttk.Frame(self.status_tabs,padding=6)
        combat_panel=ttk.Frame(self.status_tabs,padding=10)
        self.status_tabs.add(profit_panel,text='状态与收益')
        self.status_tabs.add(combat_panel,text='经验／击杀')
        profit_actions=ttk.Frame(profit_panel);profit_actions.pack(fill='x',pady=(0,8))
        profit_actions.columnconfigure((0,1),weight=1)
        self.profit_start_button=ttk.Button(profit_actions,text='开始／继续统计',command=self.start_profit)
        self.profit_start_button.grid(row=0,column=0,sticky='ew',padx=(0,3),pady=3)
        self.profit_reset_button=ttk.Button(profit_actions,text='重设收益起点',style='Primary.TButton',command=lambda:self.start_profit(reset=True))
        self.profit_reset_button.grid(row=0,column=1,sticky='ew',padx=(3,0),pady=3)
        ttk.Button(profit_actions,text='暂停统计',command=lambda:self.profit.stop()).grid(row=1,column=0,sticky='ew',padx=(0,3),pady=3)
        ttk.Button(profit_actions,text='比例与费用设置',command=self.profit_settings).grid(row=1,column=1,sticky='ew',padx=(3,0),pady=3)
        profit_scroller=ttk.Frame(profit_panel);profit_scroller.pack(fill='both',expand=True)
        self.profit_canvas=tk.Canvas(profit_scroller,width=310,height=1,highlightthickness=0,background='#eef2f7')
        profit_scrollbar=ttk.Scrollbar(profit_scroller,orient='vertical',command=self.profit_canvas.yview)
        self.profit_canvas.configure(yscrollcommand=profit_scrollbar.set)
        profit_scrollbar.pack(side='right',fill='y');self.profit_canvas.pack(side='left',fill='both',expand=True)
        profit_body=ttk.Frame(self.profit_canvas)
        profit_window=self.profit_canvas.create_window((0,0),window=profit_body,anchor='nw')
        profit_body.bind('<Configure>',lambda event:self.profit_canvas.configure(scrollregion=self.profit_canvas.bbox('all')))
        self.profit_canvas.bind('<Configure>',lambda event:self.profit_canvas.itemconfigure(profit_window,width=event.width))
        def scroll_profit(event):
            self.profit_canvas.yview_scroll(-int(event.delta/120),'units');return 'break'
        self.profit_canvas.bind('<MouseWheel>',scroll_profit)
        self.combat_text=tk.StringVar(value='等待本号经验统计')
        ttk.Label(combat_panel,textvariable=self.combat_text,wraplength=330,justify='left',font=('Microsoft YaHei UI',10)).pack(anchor='nw')
        self.status_tabs.select(combat_panel)
        self.live_position=tk.StringVar(value='坐标：等待读取')
        self.live_count=tk.StringVar(value='怪物：等待读取')
        self.live_detail=tk.StringVar(value='')
        self.live_status=tk.StringVar(value='采样复用管理员辅助，不启动独立监控窗口')
        self.random_status=tk.StringVar(value='无怪随机默认关闭')
        ttk.Label(profit_body,textvariable=self.live_position,font=('Microsoft YaHei UI',14)).pack(anchor='w')
        ttk.Label(profit_body,textvariable=self.live_count,font=('Microsoft YaHei UI',11)).pack(anchor='w',pady=3)
        ttk.Label(profit_body,textvariable=self.live_detail,wraplength=290).pack(anchor='w')
        ttk.Label(profit_body,textvariable=self.live_status,wraplength=290).pack(anchor='w',pady=3)
        ttk.Label(profit_body,textvariable=self.random_status,wraplength=290).pack(anchor='w',pady=3)
        ttk.Separator(profit_body).pack(fill='x',pady=6)
        self.profit_text=tk.StringVar(value='点击开始统计建立余额起点\n默认：1元＝11元宝\n100万金币＝180元宝\n时费5元宝，进图5元宝')
        self.profit_status=tk.StringVar(value='等待读取实时金币和元宝')
        ttk.Label(profit_body,textvariable=self.profit_text,justify='left',wraplength=290,font=('Microsoft YaHei UI',11)).pack(anchor='w',pady=8)
        ttk.Label(profit_body,textvariable=self.profit_status,wraplength=290).pack(anchor='w',pady=8)
        ttk.Label(profit_body,text='余额净收益含已扣款，不重复扣费。\n随机石消耗另按设置估值计入估算成本。\n未售装备不估值；人工交易后可重设起点。',wraplength=290,justify='left').pack(anchor='w',pady=8)
        for widget in profit_body.winfo_children():widget.bind('<MouseWheel>',scroll_profit)
        self.after(100,self.receive_results)
        self.after(500,self.refresh_profit)
        self.after(200,self.refresh_live)
        self.last_progress=None
        if '--start-hunt' in sys.argv:self.after(800,lambda:self.run('hunt'))

    def refresh_dungeon_status(self):
        if time.monotonic()-self.last_dungeon_refresh<1:return
        self.last_dungeon_refresh=time.monotonic()
        try:
            paths=[ROOT/'outputs'/name for name in ('法师地牢挂机状态.json','当前地图挂机状态.json')]
            path=max((p for p in paths if p.exists()),key=lambda p:p.stat().st_mtime)
            data=json.loads(path.read_text(encoding='utf8'))
            route=data.get('route',{});position=data.get('position',[])
            phase={'running':'运行中','stopped':'已停止','finished':'已结束'}.get(data.get('phase'),'记录')
            age=time.time()-data.get('observed_epoch',0)
            if age>5:phase=('状态待核对' if phase=='运行中' else phase)+'（最近记录）'
            text='{} · 坐标 {}\n施法 {} 次 · 死亡观察 {} 次 · 确认拾取 {} 件\n路点 {}/{} · 完成 {} 圈'.format(
                phase,position,data.get('casts',0),data.get('observed_deaths',0),data.get('verified_pickups',0),
                route.get('visited',0),route.get('total',0),route.get('laps',0))
            if data.get('reason'):text+='\n停止原因：'+str(data['reason'])
            self.dungeon_status.set(text)
        except FileNotFoundError:pass
        except (OSError,ValueError,TypeError):self.dungeon_status.set('地图状态暂不可读')

    def receive_results(self):
        self.refresh_dungeon_status()
        self.refresh_binding_status()
        self.sync_existing_task()
        if self.busy:
            try:
                saved=json.loads((HELPER/'source-sale-result.json').read_text(encoding='utf8'))
                last=saved.get('progress',[])[-1:] or ['正在处理…']
                wallet=saved.get('state',{}).get('wallet') or {}
                if wallet.get('gold') is not None:self.wallet.set('金币：{:,}　元宝：{}　日志：outputs/挂机统计'.format(wallet['gold'],wallet.get('yuanbao')))
                if last[0]!=self.last_progress:
                    self.last_progress=last[0];self.status.set(last[0])
            except (OSError,ValueError):pass
        try:
            while True:
                result,error=self.messages.get_nowait()
                if result=={'helper_stopped_for_binding':True} and error is None:
                    self.busy=False;self.choose_game();continue
                self.finished(result,error)
        except queue.Empty:pass
        self.after(100,self.receive_results)

    def request_stop(self):
        self.cancel.set()
        if self.attached_step is not None:
            temp=HELPER/'source-sale-cancel-gui.tmp'
            temp.write_text(json.dumps({'step':self.attached_step,'requested_by':'user',
                                        'reason':'工具箱停止已接管的现有循环'}),encoding='utf8')
            temp.replace(HELPER/'source-sale-cancel.json')
            self.status.set('已请求停止当前循环，等待脚本安全结束')

    def sync_existing_task(self):
        if self.busy:return
        try:
            command=json.loads((HELPER/'source-sale-command.json').read_text(encoding='utf8'))
            saved=json.loads((HELPER/'source-sale-result.json').read_text(encoding='utf8'))
            live=json.loads((ROOT/'outputs'/'实时监控.json').read_text(encoding='utf8'))
            step=active_task(command,saved,live,time.time())
        except (OSError,ValueError,TypeError):return
        if step is not None:
            self.attached_step=step
            for button in (self.connect_button,self.start_button,self.inspect_button,self.recover_button,self.monitor_button,self.hunt_button,self.resume_hunt_button,self.pickup_button,self.bag_test_button,self.login_bag_test_button,self.town_test_button,self.weapon_transfer_test_button,self.cangyue_transfer_test_button,self.jewelry_menu_test_button,self.clothes_menu_test_button,self.dungeon_start_button):
                button.configure(state='disabled')
            self.mode_box.configure(state='disabled');self.stop_button.configure(state='normal')
            for button in self.island_buttons:button.configure(state='disabled')
            progress=(saved.get('progress') or ['正在运行'])[-1]
            self.status.set('脚本运行中 · 命令{} · {}'.format(step,progress))
            self.output.delete('1.0','end')
            self.output.insert('end','已同步现有循环，不会重复启动。\n当前进度：'+progress+'\n操作由本机脚本执行，停止按钮控制同一命令。')
        elif self.attached_step is not None and saved.get('step')==self.attached_step:
            self.attached_step=None
            self.finished(saved.get('result'),saved.get('error'))
            self.connect_button.configure(state='normal')

    def open_combat_stats(self):
        import subprocess
        executable=Path(sys.executable).with_name('pythonw.exe')
        subprocess.Popen([str(executable),str(Path(__file__).with_name('combat_stats_gui.py'))],cwd=str(instance_context.SOURCE_ROOT))

    def binding_summary(self):
        selected=instance_context.binding()
        if not selected:return '尚未指定角色；请在角色设置中选择'
        name=selected.get('character') or selected.get('title','未知角色')
        try:instance_context.verify_binding(selected)
        except (OSError,RuntimeError):return '旧绑定：{} · PID {}（已退出或不可核对，请重新选择）'.format(name,selected.get('pid'))
        return '已绑定：{} · PID {}'.format(name,selected['pid'])

    def refresh_binding_status(self):
        if time.monotonic()-self.last_binding_refresh<2:return
        self.last_binding_refresh=time.monotonic()
        try:
            self.binding_label.set(self.binding_summary())
            from fast_sale import MemoryReader
            reader=MemoryReader()
            try:choices=reader.candidates()
            finally:reader.close()
            names=['{}（PID {}）'.format(title.rsplit(' - ',1)[-1],pid) for pid,title,exe in choices]
            selected=instance_context.binding()
            match=next((title.rsplit(' - ',1)[-1] for pid,title,exe in choices if selected and pid==selected.get('pid')),None)
            if match and selected.get('character') and match!=selected['character']:
                self.binding_label.set('当前窗口：{} · 保存绑定：{}（角色已变化，请重新选择）'.format(match,selected['character']))
            self.available_roles.set('当前可选角色：'+('、'.join(names) if names else '未发现已登录客户端'))
        except (OSError,RuntimeError,ValueError):self.available_roles.set('当前角色列表暂不可核对')

    def choose_game(self):
        if self.busy or self.attached_step is not None:
            self.status.set('请先正常停止本实例，再切换绑定');return
        # Never change the target of an already running helper.
        try:
            saved=json.loads((HELPER/'source-sale-result.json').read_text(encoding='utf8'))
            helper_pid=saved.get('state',{}).get('helper_pid')
            if helper_pid:
                try:instance_context.process_identity(helper_pid)
                except RuntimeError:pass
                else:
                    command=json.loads((HELPER/'source-sale-command.json').read_text(encoding='utf8'))
                    if command.get('step',0)>saved.get('step',0):
                        self.status.set('本号命令尚未结束，请先正常停止再更换角色');return
                    self.busy=True;self.cancel.clear()
                    self.status.set('正在正常关闭本号空闲辅助，随后显示当前角色列表…')
                    def stop_idle():
                        try:
                            drive([{'action':'stop','foreground':False}],self.cancel)
                            self.messages.put(({'helper_stopped_for_binding':True},None))
                        except Exception as error:self.messages.put((None,str(error)))
                    threading.Thread(target=stop_idle,daemon=True).start();return
        except (OSError,ValueError):pass
        try:
            from fast_sale import MemoryReader
            reader=MemoryReader()
            try:choices=reader.candidates()
            finally:reader.close()
            if not choices:raise RuntimeError('请先手动打开并登录两个游戏角色，再选择；不会启动登录器')
        except (OSError,RuntimeError) as error:
            self.status.set(str(error));return
        dialog=tk.Toplevel(self);dialog.title('选择账号'+instance_context.slot()+'的角色')
        names=[str(pid)+' · '+title for pid,title,exe in choices]
        selected=tk.StringVar(value=names[0])
        ttk.Combobox(dialog,textvariable=selected,values=names,state='readonly',width=65).pack(padx=16,pady=16)
        def confirm():
            try:
                pid,title,exe=choices[names.index(selected.get())]
                instance_context.save_binding(pid,title)
                self.binding_label.set(self.binding_summary());self.status.set('已绑定，连接游戏时只连接此进程')
                dialog.destroy()
            except (OSError,RuntimeError) as error:self.status.set(str(error))
        ttk.Button(dialog,text='绑定此角色',command=confirm).pack(pady=(0,16))

    def configure_login(self):
        if self.busy or self.attached_step is not None:return
        selected=instance_context.binding()
        if not selected or not selected.get('character'):
            self.status.set('请先选择已登录的对应角色，再保存该号登录配置');return
        dialog=tk.Toplevel(self);dialog.title('账号'+instance_context.slot()+' · 本机加密登录配置')
        values=[]
        for label,masked in [('账号',False),('密码',True)]:
            ttk.Label(dialog,text=label).pack(anchor='w',padx=16,pady=(10,0))
            entry=ttk.Entry(dialog,show='*' if masked else '',width=35);entry.pack(padx=16);values.append(entry)
        def save():
            try:
                import credential_store
                credential_store.save(values[0].get(),values[1].get())
                credential_store.bind_character(selected['character'])
                for entry in values:entry.delete(0,'end')
                dialog.destroy();self.status.set('本号登录配置已加密保存')
            except (OSError,ValueError,RuntimeError):self.status.set('保存失败，请检查输入或本机加密配置')
        ttk.Button(dialog,text='加密保存本号配置',command=save).pack(pady=16)

    def connect_game(self):
        if self.busy or self.attached_step is not None:return
        try:
            saved=json.loads((HELPER/'source-sale-result.json').read_text(encoding='utf8'))
            pid=saved.get('state',{}).get('helper_pid')
            import ctypes
            from ctypes import wintypes as w
            kernel=ctypes.windll.kernel32
            kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
            kernel.GetExitCodeProcess.argtypes=[w.HANDLE,ctypes.POINTER(w.DWORD)];kernel.CloseHandle.argtypes=[w.HANDLE]
            handle=kernel.OpenProcess(0x1000,False,pid) if pid else None
            code=w.DWORD();alive=False
            if handle:
                try:alive=bool(kernel.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
                finally:kernel.CloseHandle(handle)
            if alive:
                self.status.set('辅助进程已连接，无需再次授权');self.open_live_monitor();return
        except (OSError,ValueError):pass
        import ctypes,subprocess
        shell=ctypes.windll.shell32;shell.ShellExecuteW.restype=ctypes.c_void_p
        shell.ShellExecuteW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_wchar_p,
                                     ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_int]
        executable=Path(sys.executable).with_name('python.exe')
        arguments=subprocess.list2cmdline([str(SOURCE_HELPER/'run_source_sale.py'),'--instance',instance_context.slot(),'--login-on-connect'])
        started=time.time()
        result=shell.ShellExecuteW(None,'runas',str(executable),arguments,str(instance_context.SOURCE_ROOT),0)
        self.status.set('辅助进程正在启动，授权后稍候再检查背包' if result and result>32 else '辅助进程未启动')
        if result and result>32:self.after(500,lambda:self.poll_connection(started))

    def poll_connection(self,started):
        path=HELPER/'source-sale-result.json'
        try:
            if path.stat().st_mtime>=started:
                saved=json.loads(path.read_text(encoding='utf8'))
                if saved.get('error'):
                    self.status.set('连接失败：'+str(saved['error']));return
                stage=saved.get('stage')
                if stage=='ready':
                    self.status.set('游戏已连接，角色状态已核对');return
                if stage=='connecting':
                    self.status.set('正在登录：'+(saved.get('progress') or ['识别登录状态'])[-1])
        except (OSError,ValueError):pass
        if time.time()-started<100:self.after(500,lambda:self.poll_connection(started))
        else:self.status.set('连接等待超时，请查看辅助进程或授权提示')

    def wallet_sample(self):
        value=json.loads((ROOT/'outputs'/'实时监控.json').read_text(encoding='utf8'))
        at=value.get('wallet_observed_epoch',0)
        wallet=value.get('wallet') or {}
        if not value.get('ok') or time.time()-at>3 or any(wallet.get(k) is None for k in ('gold','yuanbao')):
            raise ValueError('钱包数据未更新；请打开实时监控，收益会保留上次有效值')
        return wallet,at,value.get('game_pid')

    def refresh_live(self):
        try:
            sample=json.loads((ROOT/'outputs'/'实时监控.json').read_text(encoding='utf8'))
            age=time.time()-sample.get('observed_epoch',0)
            if not sample.get('ok') or not 0<=age<=2:raise ValueError(sample.get('error') or '采样已延迟')
            from combat_stats_gui import render_combat
            self.combat_text.set(render_combat(sample))
            x,y=sample['position'];self.live_position.set('当前坐标：{}，{}'.format(x,y))
            self.live_count.set('{}格内怪{}／候选{}；{}格内其他玩家{}'.format(sample['radius'],sample['count'],sample.get('target_count','—'),sample.get('player_radius','—'),sample.get('player_count','—')))
            details='　'.join('{} {}'.format(name,count) for name,count in sample.get('by_name',{}).items())
            self.live_detail.set(details[:100] or '当前范围没有存活怪物')
            self.live_status.set('读取 {} ms · 延迟 {:.0f} ms · 每200毫秒采样'.format(sample['read_ms'],age*1000))
            status=sample.get('random') or {}
            settings=load_settings()
            self.random_status.set(('随机已开启：' if settings.enabled else '随机已关闭：')+
                                   status.get('reason','等待挂机循环')+
                                   '；本小时已用{}次'.format(status.get('used_hour',0)))
        except (OSError,ValueError,KeyError,TypeError) as error:
            self.live_position.set('当前坐标：等待有效采样');self.live_count.set('怪物：等待有效采样')
            self.live_detail.set('');self.live_status.set(str(error))
            self.combat_text.set('经验／击杀统计：等待有效采样')
        self.after(200,self.refresh_live)

    def random_settings(self):
        window=tk.Toplevel(self);window.title('无怪随机');window.transient(self)
        panel=ttk.Frame(window,padding=16);panel.pack(fill='both',expand=True)
        try:settings=load_settings()
        except (OSError,ValueError,TypeError):settings=RandomSettings()
        enabled=tk.BooleanVar(value=settings.enabled);variables={}
        ttk.Checkbutton(panel,text='开启：仅在挂机图满足条件时使用随机石',variable=enabled).grid(row=0,column=0,columnspan=2,sticky='w',pady=6)
        modes={'有人且无怪（推荐）':'contested_empty','仅持续无怪':'empty','仅持续有人':'players'}
        mode=tk.StringVar(value=next(label for label,value in modes.items() if value==settings.trigger_mode))
        ttk.Label(panel,text='随机条件').grid(row=1,column=0,sticky='w')
        ttk.Combobox(panel,textvariable=mode,values=list(modes),state='readonly',width=22).grid(row=1,column=1,padx=8)
        fields=(('radius','怪物检测半径（格）'),('player_radius','玩家检测半径（格）'),('empty_seconds','条件持续多少秒'),
                ('cooldown_seconds','两次随机至少间隔（秒）'),('max_per_hour','每小时最多几次'),
                ('cost_per_use','每次随机估算费用（元宝）'))
        for i,(key,label) in enumerate(fields,2):
            ttk.Label(panel,text=label).grid(row=i,column=0,sticky='w',pady=4)
            variables[key]=tk.StringVar(value=str(getattr(settings,key)))
            ttk.Entry(panel,textvariable=variables[key],width=14).grid(row=i,column=1,padx=8)
        ttk.Label(panel,text='10元宝／50次＝每次0.2元宝。\n只读客户端已加载的怪物；不是全地图。\n“有人且无怪”：有人有怪仍继续打，无人时等刷新。\n只使用快捷栏“随机传送石”，不使用随机卷。\n缺石头、随机未确认或采样失效时暂停随机。',justify='left').grid(row=8,column=0,columnspan=2,pady=10)
        def save():
            try:
                values={key:(int(value.get()) if key in ('radius','player_radius','max_per_hour') else float(value.get())) for key,value in variables.items()}
                save_settings(RandomSettings(enabled=enabled.get(),trigger_mode=modes[mode.get()],**values))
            except (ValueError,TypeError,OSError) as error:
                messagebox.showerror('设置格式',str(error),parent=window);return
            self.random_status.set('随机已开启' if enabled.get() else '随机已关闭');window.destroy()
        ttk.Button(panel,text='保存（不会立即使用石头）',command=save).grid(row=9,column=1,sticky='e')

    def start_profit(self,reset=False,quiet=False):
        try:
            wallet,at,pid=self.wallet_sample()
            if reset or self.profit.state is None:self.profit.start(wallet,pid=pid)
            else:self.profit.resume(wallet,pid=pid)
            if not quiet:self.profit_auto=False
            self.profit_status.set('统计中；手工交易或充值后可重设起点')
            return True
        except (OSError,ValueError,TypeError) as error:
            self.profit_status.set(str(error))
            if not quiet:messagebox.showinfo('收益统计',str(error),parent=self)
            return False

    def update_profit_sample(self):
        try:
            wallet,at,pid=self.wallet_sample()
            self.wallet.set('金币：{:,}　元宝：{}'.format(wallet['gold'],wallet['yuanbao']))
            self.profit.sample(wallet,at,pid)
            events=ROOT/'outputs'/'挂机统计'/'events.jsonl'
            if events.exists() and self.profit.running:
                if events.stat().st_size<self.profit_event_offset:self.profit_event_offset=0
                with events.open('rb') as source:
                    source.seek(self.profit_event_offset)
                    while True:
                        line=source.readline()
                        if not line or not line.endswith(b'\n'):break
                        self.profit_event_offset=source.tell()
                        try:self.profit.add_event(json.loads(line))
                        except (ValueError,UnicodeError):pass
                self.profit.save()
            self.profit_status.set(('统计中' if self.profit.running else '已暂停')+' · 钱包每秒更新 · '+time.strftime('%H:%M:%S',time.localtime(at)))
        except (OSError,ValueError,TypeError) as error:self.profit_status.set(str(error))

    def refresh_profit(self):
        if getattr(self,'profit_pending_start',False):
            if self.start_profit(quiet=True):self.profit_pending_start=False
        self.update_profit_sample()
        summary=self.profit.summary()
        if summary:
            hourly=summary['actual_hourly_rmb']
            self.profit_text.set('统计时长：{:.2f} 小时\n进图次数：{} 次\n金币净增：{:+,.0f}\n元宝变化：{:+.2f}\n余额净增折算：{:+.2f} 元宝\n折合人民币：{:+.2f} 元\n平均每小时：{}\n估算总成本：{:.2f} 元宝\n估算净收益：{:+.2f} 元\n回本金币门槛：{:,.0f}\n当前比例：1元＝{}元宝\n{:g}金币＝{:g}元宝\n时费{}／进图{}元宝\n随机{}次，消耗估值{:.2f}元宝'.format(
                summary['hours'],summary['entries'],summary['gold_delta'],summary['yuanbao_delta'],
                summary['actual_profit_yuanbao'],summary['actual_profit_rmb'],
                '{:+.2f}元'.format(hourly) if hourly is not None else '—',
                summary['estimated_cost_yuanbao'],summary['estimated_profit_rmb'],summary['break_even_gold'],
                self.profit.rates.yuanbao_per_rmb,self.profit.rates.gold_per_lot,self.profit.rates.yuanbao_per_lot,
                self.profit.rates.hourly_cost,self.profit.rates.entry_cost,
                summary['random_uses'],summary['random_estimated_cost']))
        self.after(1000,self.refresh_profit)

    def profit_settings(self):
        window=tk.Toplevel(self);window.title('收益比例与费用');window.transient(self)
        panel=ttk.Frame(window,padding=18);panel.pack(fill='both',expand=True)
        variables={}
        for i,(key,label) in enumerate((('yuanbao_per_rmb','1元人民币对应元宝'),('gold_per_lot','一组金币数量'),
            ('yuanbao_per_lot','这组金币对应元宝'),('hourly_cost','每小时挂机费（元宝）'),('entry_cost','每次进图费（元宝）'))):
            ttk.Label(panel,text=label).grid(row=i,column=0,sticky='w',pady=5)
            variables[key]=tk.StringVar(value=str(asdict(self.profit.rates)[key]))
            ttk.Entry(panel,textvariable=variables[key],width=18).grid(row=i,column=1,padx=10)
        ttk.Label(panel,text='修改后按新比例重算当前统计，不改变游戏余额。').grid(row=5,column=0,columnspan=2,pady=10)
        def save():
            try:self.profit.set_rates(**{key:float(value.get()) for key,value in variables.items()})
            except (ValueError,TypeError) as error:
                messagebox.showerror('比例格式',str(error),parent=window);return
            window.destroy()
        ttk.Button(panel,text='保存',command=save).grid(row=6,column=1,sticky='e')

    def open_live_monitor(self):
        if self.busy or self.attached_step is not None:
            (HELPER/'live-monitor-request.json').write_text('{}',encoding='utf8')
            self.status.set('已请求打开实时监控，不中断当前清包')
        else:self.run('live')

    def run(self,execute):
        if self.busy or self.attached_step is not None:return
        if execute in ('hunt','resume_hunt') and not self.profit.running:
            self.profit_pending_start=not self.start_profit(quiet=True)
            (HELPER/'live-monitor-request.json').write_text('{}',encoding='utf8')
            self.profit_auto=True
        if execute=='mage_dungeon':
            selected=instance_context.binding()
            if not selected or selected.get('character')!='厚礼蟹':
                self.status.set('地牢法师目前仅支持已绑定的厚礼蟹，请先核对本号角色');return
        self.busy=True;self.cancel.clear()
        self.dungeon_start_button.configure(state='disabled')
        for button in self.island_buttons:button.configure(state='disabled')
        mode=self.mode.get()
        foreground=self.foreground.get()
        self.recover_button.configure(state='disabled')
        self.monitor_button.configure(state='disabled')
        self.hunt_button.configure(state='disabled')
        self.resume_hunt_button.configure(state='disabled')
        self.pickup_button.configure(state='disabled')
        self.bag_test_button.configure(state='disabled')
        self.login_bag_test_button.configure(state='disabled')
        self.town_test_button.configure(state='disabled')
        self.weapon_transfer_test_button.configure(state='disabled')
        self.cangyue_transfer_test_button.configure(state='disabled')
        self.jewelry_menu_test_button.configure(state='disabled')
        self.clothes_menu_test_button.configure(state='disabled')
        self.start_button.configure(state='disabled');self.inspect_button.configure(state='disabled');self.mode_box.configure(state='disabled')
        self.stop_button.configure(state='normal');self.status.set('正在连接辅助进程…')
        def work():
            try:
                if execute=='mage_dungeon':
                    response=drive([{'action':'shop_route','categories':['法师当前地图持续挂机'],'foreground':False}],self.cancel)
                    result=response.get('result',{})
                elif execute in ('island_start','island_resume','island_status'):
                    category={'island_start':'孤岛每日自动挑战','island_resume':'接续孤岛自动挑战','island_status':'孤岛自动状态只读'}[execute]
                    response=drive([{'action':'shop_route','categories':[category],'foreground':False}],self.cancel)
                    result=response.get('result',{})
                elif execute in ('cangyue_jewelry_menu','cangyue_clothes_menu'):
                    category='苍月首饰出售菜单测试（不卖装备）' if execute=='cangyue_jewelry_menu' else '苍月衣服出售菜单测试（不卖装备）'
                    response=drive([{'action':'shop_route','categories':[category],'foreground':False}],self.cancel)
                    result=response.get('result',{})
                elif execute in ('fixed_weapon_transfer','fixed_cangyue_transfer'):
                    category='固定位置传送武器店测试' if execute=='fixed_weapon_transfer' else '固定位置传送苍月测试'
                    response=drive([{'action':'shop_route','categories':[category],'foreground':False}],self.cancel)
                    result=response.get('result',{})
                elif execute=='town_sale_entry_test':
                    response=drive([{'action':'shop_route','categories':['土城完整流程测试（不入场）'],'foreground':foreground}],self.cancel)
                    result=response.get('result',{})
                elif execute=='login_bag_test':
                    response=drive([{'action':'shop_route','categories':['登录后后台打开背包测试'],'foreground':False}],self.cancel)
                    result=response.get('result',{})
                elif execute=='bag_background':
                    response=drive([{'action':'shop_route','categories':['背包仅后台点击测试'],'foreground':False}],self.cancel)
                    result=response.get('result',{})
                elif execute=='bag_test':
                    response=drive([{'action':'shop_route','categories':['背包多方式点击测试'],'foreground':True}],self.cancel)
                    result=response.get('result',{})
                elif execute=='pickup':
                    response=drive([{'action':'shop_route','categories':['木剑自动拾取120秒'],'foreground':False}],self.cancel)
                    result=response.get('result',{})
                elif execute=='live':
                    response=drive([{'action':'shop_route','categories':['打开实时监控'],'foreground':False}],self.cancel)
                    result=response.get('result',{})
                elif execute in ('hunt','resume_hunt'):
                    category='接续当前挂机图循环' if execute=='resume_hunt' else '挂机清包循环'
                    response=drive([{'action':'shop_route','categories':[category],'foreground':foreground}],self.cancel)
                    result=response.get('result',{})
                elif execute=='monitor':
                    response=drive([{'action':'shop_route','categories':['监测并回城出售'],'foreground':foreground}],self.cancel)
                    result=response.get('result',{})
                elif execute=='recover':
                    response=drive([{'action':'shop_route','categories':['死亡重登'],'foreground':foreground}],self.cancel)
                    result=response.get('result',{})
                elif not execute:
                    response=drive([{'action':'shop_route','categories':['读取双背包'],'foreground':False}],self.cancel)
                    state=response['state'];bags=response['result'];items=[]
                    for bag,key in [('人物','main_items'),('英雄','hero_items')]:
                        items.extend({'背包':bag,'格子':row['slot'],'物品':row['name'],'部位':row['category']} for row in sale_plan(bags[key]))
                    result={'分辨率':state['client_size'],'人物坐标':state['player'],
                            '人物空格':bags['main_items'].count(''),'英雄空格':bags['hero_items'].count(''),'待售装备':items}
                else:
                    check=drive([{'action':'observe','foreground':False}],self.cancel)
                    category=('苍月出售' if mode.startswith('只在苍月') else '验证混合路线' if mode.startswith('只验证') else '混合路线')
                    response=drive([{'action':'shop_route','categories':[category],'foreground':foreground}],self.cancel)
                    result=response.get('result',{})
                self.messages.put((result,None))
            except Exception as error:self.messages.put((None,str(error)))
        threading.Thread(target=work,daemon=True).start()

    def finished(self,result,error):
        self.profit_pending_start=False
        if self.profit_auto and self.profit.running:
            self.update_profit_sample()
            try:
                completed=json.loads((HELPER/'source-sale-result.json').read_text(encoding='utf8'))
                command=json.loads((HELPER/'source-sale-command.json').read_text(encoding='utf8'))
                state=completed.get('state',{})
                if completed.get('step')==command.get('step') and state.get('wallet'):
                    self.profit.sample(state['wallet'],time.time(),state.get('game_pid'))
            except (OSError,ValueError,TypeError):pass
            self.profit.stop()
        self.profit_auto=False
        self.busy=False
        self.dungeon_start_button.configure(state='normal')
        for button in self.island_buttons:button.configure(state='normal')
        self.recover_button.configure(state='normal')
        self.monitor_button.configure(state='normal')
        self.hunt_button.configure(state='normal')
        self.resume_hunt_button.configure(state='normal')
        self.pickup_button.configure(state='normal')
        self.bag_test_button.configure(state='normal')
        self.login_bag_test_button.configure(state='normal')
        self.town_test_button.configure(state='normal')
        self.weapon_transfer_test_button.configure(state='normal')
        self.cangyue_transfer_test_button.configure(state='normal')
        self.jewelry_menu_test_button.configure(state='normal')
        self.clothes_menu_test_button.configure(state='normal')
        self.start_button.configure(state='normal');self.inspect_button.configure(state='normal');self.mode_box.configure(state='readonly');self.stop_button.configure(state='disabled')
        self.output.delete('1.0','end')
        self.output.insert('end',error if error else json.dumps(result,ensure_ascii=False,indent=2))
        self.status.set('已停止：'+error if error else '本次操作结束')
        (ROOT/'outputs'/'清包工具最近结果.json').write_text(json.dumps({'result':result,'error':error},ensure_ascii=False,indent=2),encoding='utf8')

    def close_window(self):
        if self.busy or self.attached_step is not None:self.request_stop();self.status.set('正在停止，操作结束后可关闭')
        else:self.profit.stop();self.destroy()

    def destroy(self):
        for callback in self.tk.call('after','info'):self.after_cancel(callback)
        super().destroy()

def main():
    import os
    embedded_parent=os.environ.get('MIR_TOOL_EMBED_PARENT')
    app=App(use=embedded_parent)
    if embedded_parent:
        shutdown=Path(os.environ['MIR_TOOL_EMBED_SHUTDOWN'])
        ready=Path(os.environ['MIR_TOOL_EMBED_READY'])
        app.update_idletasks()
        ready.write_text(json.dumps({'instance':instance_context.slot(),'width':app.winfo_width(),'height':app.winfo_height()}),encoding='utf8')
        def check_host():
            if shutdown.exists():
                if app.busy or app.attached_step is not None:
                    app.request_stop();app.status.set('正在安全停止本号，完成后关闭')
                else:
                    app.close_window();return
            app.after(300,check_host)
        app.after(300,check_host)
    app.mainloop()


if __name__=='__main__':
    from ui_diagnostics import run_logged
    run_logged(ROOT/'outputs'/'工具箱'/('账号'+instance_context.slot()+'界面.log'),main)
