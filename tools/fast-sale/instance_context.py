"""Two independent runtime slots sharing source code, never credentials."""
import os, sys, json, ctypes
from pathlib import Path
from ctypes import wintypes as w

SOURCE_ROOT=Path(__file__).resolve().parents[2]

def slot():
    value=os.environ.get('MIR_TOOL_INSTANCE','1')
    if '--instance' in sys.argv:
        value=sys.argv[sys.argv.index('--instance')+1]
    if value not in ('1','2'):raise RuntimeError('工具实例只能是1或2')
    return value

def runtime_root(root=None, instance=None):
    root=Path(root or SOURCE_ROOT)
    return root if (instance or slot())=='1' else root/'instances'/'2'

def helper_directory():
    return runtime_root()/'tools'/'game-chat-inspect'

def binding_path(instance=None):
    return runtime_root(instance=instance)/'outputs'/'game-binding.json'

def binding(instance=None):
    try:return json.loads(binding_path(instance).read_text(encoding='utf8'))
    except FileNotFoundError:return None

def process_identity(pid):
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
    k.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)]
    k.GetProcessTimes.argtypes=[w.HANDLE]+[ctypes.POINTER(w.FILETIME)]*4
    k.CloseHandle.argtypes=[w.HANDLE]
    h=k.OpenProcess(0x1000,False,pid)
    if not h:raise RuntimeError('目标游戏进程不存在或无法核对')
    try:
        name=ctypes.create_unicode_buffer(32768);size=w.DWORD(len(name))
        a,b,c,d=(w.FILETIME() for _ in range(4))
        if not k.QueryFullProcessImageNameW(h,0,name,ctypes.byref(size)) or not k.GetProcessTimes(h,*[ctypes.byref(x) for x in (a,b,c,d)]):
            raise RuntimeError('无法核对目标游戏路径和创建时间')
        return {'pid':pid,'path':str(Path(name.value).resolve()),'created':(a.dwHighDateTime<<32)|a.dwLowDateTime}
    finally:k.CloseHandle(h)

def validate_identity(saved,current):
    if any(saved.get(k)!=current.get(k) for k in ('pid','created')) or str(saved.get('path','')).casefold()!=str(current.get('path','')).casefold():
        raise RuntimeError('所选游戏已退出或PID被复用，请重新选择角色')

def verify_binding(saved):
    validate_identity(saved,process_identity(saved['pid']))

def save_binding(pid,title):
    from map_navigation import MAP_DIRECTORY
    value=process_identity(pid)
    if Path(value['path']).parent.resolve()!=MAP_DIRECTORY.parent.resolve():
        raise RuntimeError('目标进程不在已验证的游戏目录')
    other=binding('2' if slot()=='1' else '1')
    if other and other.get('pid')==pid and other.get('created')==value['created']:
        raise RuntimeError('此角色已绑定另一工具箱，请选择另一个角色')
    value.update(title=title,character=title.rsplit(' - ',1)[-1] if ' - ' in title else None,instance=slot())
    path=binding_path();path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    return value

def foreground_allowed():
    return not binding('2') and slot()=='1'


def helper_lease():
    """One helper per slot; reject duplicates before touching command/result files."""
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.CreateMutexW.argtypes=[ctypes.c_void_p,w.BOOL,w.LPCWSTR];k.CreateMutexW.restype=w.HANDLE
    k.CloseHandle.argtypes=[w.HANDLE]
    handle=k.CreateMutexW(None,False,'Local\\MirToolHelperSlot_'+slot())
    if not handle:raise RuntimeError('无法建立本实例辅助锁')
    if ctypes.get_last_error()==183:
        k.CloseHandle(handle);raise RuntimeError('本工具箱辅助已运行，未重复启动')
    return k,handle
