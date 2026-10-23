import json
from pathlib import Path
import sys
import threading
import tkinter as tk
from tkinter import ttk

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'/'game-chat-inspect'))
from source_driver import drive

class Recorder(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('追忆 · 手动路线录制')
        self.geometry('620x330')
        self.recording=False;self.busy=False;self.directory=None
        self.protocol('WM_DELETE_WINDOW',self.close_window)
        panel=ttk.Frame(self,padding=18);panel.pack(fill='both',expand=True)
        ttk.Label(panel,text='你操作游戏，工具只记录',font=('Microsoft YaHei UI',14)).pack(anchor='w')
        ttk.Label(panel,text='仅记录游戏内的左右键、人物坐标和关键画面；不录键盘。').pack(anchor='w',pady=(8,3))
        ttk.Label(panel,text='录制期间自动点击禁用。可停顿、绕开玩家，不必真的出售装备。').pack(anchor='w')
        self.start=ttk.Button(panel,text='开始录制',command=lambda:self.command(True));self.start.pack(fill='x',pady=(14,7))
        self.stop=ttk.Button(panel,text='结束并保存',command=lambda:self.command(False),state='disabled');self.stop.pack(fill='x')
        self.status=tk.StringVar(value='等待开始；复用现有辅助进程，不需要再弹UAC')
        ttk.Label(panel,textvariable=self.status,wraplength=580).pack(anchor='w',pady=12)
        self.open_button=ttk.Button(panel,text='打开录制文件夹',command=self.open_folder,state='disabled');self.open_button.pack(anchor='w')

    def command(self,start):
        if self.busy:return
        self.busy=True;self.start.configure(state='disabled');self.stop.configure(state='disabled')
        self.status.set('正在开始…' if start else '正在停止并保存…')
        def worker():
            try:
                result=drive([{'action':'shop_route','categories':['开始录制路线' if start else '停止录制路线'],'foreground':False}])['result']
                self.after(0,self.finished,start,result,None)
            except Exception as error:self.after(0,self.finished,start,None,str(error))
        threading.Thread(target=worker,daemon=True).start()

    def finished(self,start,result,error):
        self.busy=False
        if error:self.status.set('未完成：'+error)
        else:
            self.recording=start;self.directory=result['directory']
            if start:self.status.set('正在录制。现在切到游戏按你的路线操作，完成后点“结束并保存”。')
            else:self.status.set('已保存：%s 次点击，%s 秒。\n%s' % (result.get('clicks',0),result.get('duration_seconds',0),self.directory))
            self.open_button.configure(state='normal')
        self.start.configure(state='disabled' if self.recording else 'normal')
        self.stop.configure(state='normal' if self.recording else 'disabled')

    def open_folder(self):
        if self.directory:
            import os
            os.startfile(self.directory)

    def close_window(self):
        if self.recording:
            self.status.set('请先结束并保存，再关闭窗口。')
        elif not self.busy:self.destroy()

if __name__=='__main__':Recorder().mainloop()
