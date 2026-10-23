"""Launch the combined UI with the same read permission as the game client."""
import ctypes
from pathlib import Path
import runpy
import subprocess
import sys


def launch():
    from toolbox_config import ensure_game_directory
    if not ensure_game_directory():return
    target=Path(__file__).with_name('dual_role_gui.py')
    shell=ctypes.WinDLL('shell32',use_last_error=True)
    if shell.IsUserAnAdmin():
        runpy.run_path(str(target),run_name='__main__');return
    executable=Path(sys.executable).with_name('pythonw.exe')
    if not executable.exists():executable=Path(sys.executable)
    shell.ShellExecuteW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_int]
    shell.ShellExecuteW.restype=ctypes.c_void_p
    result=shell.ShellExecuteW(None,'runas',str(executable),subprocess.list2cmdline([str(target)]),str(target.parents[2]),1)
    if not result or result<=32:
        ctypes.windll.user32.MessageBoxW(None,'未获得管理员读取权限，新工具箱未启动。当前游戏和原有任务未受影响。','追忆助手',0x30)


if __name__=='__main__':launch()
