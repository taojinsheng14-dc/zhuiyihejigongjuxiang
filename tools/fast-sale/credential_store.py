"""Windows current-user DPAPI storage; credentials never enter result logs."""
import ctypes,json
from ctypes import wintypes as w
from pathlib import Path

class Blob(ctypes.Structure):
    _fields_=[('size',w.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]

def transform(data,protect):
    buffer=ctypes.create_string_buffer(data);source=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));target=Blob()
    api=ctypes.WinDLL('crypt32',use_last_error=True)
    function=api.CryptProtectData if protect else api.CryptUnprotectData
    function.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,w.DWORD,ctypes.POINTER(Blob)]
    function.restype=w.BOOL
    if not function(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target)):
        raise RuntimeError('无法访问本机加密的游戏登录配置')
    kernel=ctypes.WinDLL('kernel32');kernel.LocalFree.argtypes=[ctypes.c_void_p]
    try:return ctypes.string_at(target.data,target.size)
    finally:kernel.LocalFree(target.data)

from instance_context import slot, runtime_root
PATH=(Path(__file__).resolve().parent if slot()=='1' else runtime_root())/'private'/'game-login.dpapi'
def save(username,password):
    if not username or not password:raise ValueError('账号或密码为空')
    raw=json.dumps({'username':username,'password':password},ensure_ascii=False).encode('utf8')
    PATH.parent.mkdir(parents=True,exist_ok=True);PATH.write_bytes(transform(raw,True))

def load():
    if not PATH.exists():raise RuntimeError('尚未配置本机游戏登录信息')
    value=json.loads(transform(PATH.read_bytes(),False))
    if not all(isinstance(value.get(k),str) and 0<len(value[k])<=64 for k in ('username','password')):
        raise RuntimeError('本机登录配置不完整')
    return value

def bind_character(name):
    value=load()
    try:
        value['character']=name
        PATH.write_bytes(transform(json.dumps(value,ensure_ascii=False).encode('utf8'),True))
    finally:value.clear()
