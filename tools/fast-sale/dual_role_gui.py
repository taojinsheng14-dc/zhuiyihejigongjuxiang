"""One visible window; each embedded Tk account retains its own process context."""
import os
import json
import time
from pathlib import Path
import subprocess
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
sys.path.insert(0,str(Path(__file__).resolve().parent))
import toolbox_theme

SOURCE=Path(__file__).resolve().parent


def child_command(instance):
    executable=Path(sys.executable)
    windowless=executable.with_name('pythonw.exe')
    if windowless.exists():executable=windowless
    if instance=='timer':return [str(executable),str(SOURCE.parent/'boss-timer'/'app.py')]
    return [str(executable),str(SOURCE/'mixed_sale_gui.py'),'--instance',str(instance)]


class DualRoleApp(tk.Tk):
    def __init__(self):
        super().__init__()
        toolbox_theme.apply(self)
        self.title('追忆助手 · 双角色与BOSS计时')
        self.geometry('1180x900');self.minsize(1080,840)
        self.workspace=tempfile.TemporaryDirectory(prefix='mir-dual-ui-')
        self.directory=Path(self.workspace.name)
        self.processes={};self.closing=False;self.loaded=False
        self.status=tk.StringVar(value='正在加载两个角色页面…')
        header=ttk.Frame(self,padding=(20,12,20,6));header.pack(fill='x')
        tk.Label(header,text='追忆助手',font=('Microsoft YaHei UI',18,'bold'),background='#eef2f7',foreground='#16345b').pack(side='left')
        ttk.Label(header,text='双角色管理  /  BOSS刷新计时',style='Subtitle.TLabel').pack(side='left',padx=18)
        ttk.Label(self,textvariable=self.status,style='Subtitle.TLabel',padding=(22,0,20,8)).pack(fill='x')
        self.tabs=ttk.Notebook(self);self.tabs.pack(fill='both',expand=True)
        self.containers={}
        self.pages={};self.last_labels=0
        for instance in ('1','2','timer'):
            page=ttk.Frame(self.tabs)
            self.tabs.add(page,text='BOSS计时' if instance=='timer' else '账号'+instance)
            self.pages[instance]=page
            # Tk's native cross-process embedding preserves each slot's module globals.
            container=tk.Frame(page,container=True)
            container.pack(fill='both',expand=True)
            self.containers[instance]=container
        self.protocol('WM_DELETE_WINDOW',self.close_window)
        self.update_idletasks()
        for instance,container in self.containers.items():
            env=os.environ.copy()
            env.update(MIR_TOOL_INSTANCE=instance if instance!='timer' else '1',MIR_TOOL_EMBED_PARENT=str(container.winfo_id()),
                MIR_TOOL_EMBED_SHUTDOWN=str(self.directory/'shutdown'),
                MIR_TOOL_EMBED_READY=str(self.directory/('ready-'+instance+'.json')))
            if instance=='timer':env['MIR_BOSS_TIMER_DATA']=str(SOURCE.parents[1]/'outputs'/'BOSS计时器')
            # Never inherit an auto-start flag from the host launcher.
            self.processes[instance]=subprocess.Popen(child_command(instance),env=env,cwd=str(SOURCE.parents[1]))
        self.after(300,self.poll_children)

    def poll_children(self):
        if time.monotonic()-self.last_labels>2:
            self.last_labels=time.monotonic()
            for slot in ('1','2'):
                root=SOURCE.parents[1] if slot=='1' else SOURCE.parents[1]/'instances'/'2'
                try:character=json.loads((root/'outputs'/'game-binding.json').read_text(encoding='utf-8-sig')).get('character')
                except (OSError,ValueError):character=None
                self.tabs.tab(self.pages[slot],text='账号'+slot+(' · '+character if character else ''))
        exited=[slot for slot,child in self.processes.items() if child.poll() is not None]
        if self.closing and len(exited)==len(self.processes):
            self.workspace.cleanup();self.destroy();return
        if exited and not self.closing:
            self.status.set('、'.join('BOSS计时' if slot=='timer' else '账号'+slot for slot in exited)+'页面已关闭；其他页面独立运行')
        elif not self.closing and not self.loaded and all((self.directory/('ready-'+slot+'.json')).exists() for slot in self.processes):
            self.loaded=True
            self.status.set('两个角色独立运行；切换页面不会停止另一角色')
        self.after(300,self.poll_children)

    def close_window(self):
        if self.closing:return
        self.closing=True
        self.status.set('正在安全停止两个角色的工具任务，完成后关闭；游戏客户端保持打开')
        (self.directory/'shutdown').write_text('close',encoding='utf8')


if __name__=='__main__':
    from ui_diagnostics import run_logged
    run_logged(SOURCE.parents[1]/'outputs'/'工具箱'/'合并窗口.log',lambda:DualRoleApp().mainloop())
