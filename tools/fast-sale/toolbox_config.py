"""Machine-local paths; no account data or game files are shipped."""
import json
import os
from pathlib import Path

SOURCE_ROOT=Path(__file__).resolve().parents[2]
CONFIG_PATH=SOURCE_ROOT/'config'/'toolbox.local.json'
LEGACY_GAME_DIRECTORY=Path('D:/传奇/180追忆复古合击')


def game_directory():
    if os.environ.get('MIR_GAME_DIR'):return Path(os.environ['MIR_GAME_DIR']).expanduser().resolve()
    try:
        value=json.loads(CONFIG_PATH.read_text(encoding='utf-8-sig'))
        if value.get('game_directory'):return Path(value['game_directory']).expanduser().resolve()
    except FileNotFoundError:pass
    return LEGACY_GAME_DIRECTORY


def save_game_directory(directory):
    directory=Path(directory).resolve()
    if not (directory/'map').is_dir():raise ValueError('请选择包含 map 子目录的游戏客户端目录')
    CONFIG_PATH.parent.mkdir(parents=True,exist_ok=True)
    temporary=CONFIG_PATH.with_suffix('.tmp')
    temporary.write_text(json.dumps({'game_directory':str(directory)},ensure_ascii=False,indent=2),encoding='utf8')
    temporary.replace(CONFIG_PATH)


def ensure_game_directory():
    if (game_directory()/'map').is_dir():return True
    import tkinter as tk
    from tkinter import filedialog,messagebox
    root=tk.Tk();root.withdraw()
    try:
        while True:
            selected=filedialog.askdirectory(parent=root,title='首次使用：选择游戏客户端目录（里面应有 map 文件夹）')
            if not selected:return False
            try:save_game_directory(selected);return True
            except ValueError as error:messagebox.showerror('游戏目录不正确',str(error),parent=root)
    finally:root.destroy()
