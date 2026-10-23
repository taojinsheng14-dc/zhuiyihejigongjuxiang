"""Shared visual style for the toolbox's independent account pages."""
from tkinter import ttk


def apply(root):
    root.configure(bg='#eef2f7')
    root.option_add('*Font',('Microsoft YaHei UI',10))
    style=ttk.Style(root);style.theme_use('clam')
    style.configure('.',font=('Microsoft YaHei UI',10))
    style.configure('TFrame',background='#eef2f7')
    style.configure('TLabel',background='#eef2f7',foreground='#182b45')
    style.configure('TButton',padding=(12,7),background='#ffffff',foreground='#223952',bordercolor='#d6dfeb')
    style.map('TButton',background=[('active','#e7effb'),('disabled','#edf0f5')],foreground=[('disabled','#94a0af')])
    style.configure('Primary.TButton',background='#2864d7',foreground='#ffffff',font=('Microsoft YaHei UI',10,'bold'))
    style.map('Primary.TButton',background=[('active','#1c50b3'),('disabled','#dce5f1')],foreground=[('disabled','#8998ac')])
    style.configure('Stop.TButton',foreground='#b42332',background='#fff1f2')
    style.configure('Title.TLabel',font=('Microsoft YaHei UI',18,'bold'),foreground='#16345b')
    style.configure('Subtitle.TLabel',foreground='#697b91')
    style.configure('Status.TLabel',foreground='#245ba5',font=('Microsoft YaHei UI',11,'bold'),padding=(10,8))
    style.configure('TNotebook',background='#eef2f7',borderwidth=0)
    style.configure('TNotebook.Tab',padding=(19,10),background='#e2e9f2',foreground='#506179')
    style.map('TNotebook.Tab',background=[('selected','#ffffff')],foreground=[('selected','#1c58b7')])
    style.configure('TLabelframe',background='#eef2f7',bordercolor='#d5dfeb')
    style.configure('TLabelframe.Label',background='#eef2f7',foreground='#385371',font=('Microsoft YaHei UI',10,'bold'))
    style.configure('TCheckbutton',background='#eef2f7',foreground='#344b66')
    return style
