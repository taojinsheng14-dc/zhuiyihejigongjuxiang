import json,time,shutil,sys
from pathlib import Path
SOURCE=Path(__file__).resolve().parent
sys.path.insert(0,str(SOURCE.parent/'fast-sale'))
import instance_context
ROOT=instance_context.helper_directory()


def drive(actions,cancel=None):
    import ctypes
    from ctypes import wintypes as w
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,w.BOOL,w.LPCWSTR];kernel.CreateMutexW.restype=w.HANDLE
    kernel.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD]
    kernel.ReleaseMutex.argtypes=[w.HANDLE];kernel.CloseHandle.argtypes=[w.HANDLE]
    try:
        saved=json.loads((ROOT/'source-sale-result.json').read_text(encoding='utf8'))
        pid=saved.get('state',{}).get('helper_pid')
        if not pid:
            raise RuntimeError('辅助进程未就绪：'+str(saved.get('error') or '请点“连接游戏”'))
        if pid:
            kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
            kernel.GetExitCodeProcess.argtypes=[w.HANDLE,ctypes.POINTER(w.DWORD)]
            process=kernel.OpenProcess(0x1000,False,pid)
            if not process:raise RuntimeError('辅助进程已退出，请点“连接游戏”')
            code=w.DWORD()
            try:alive=bool(kernel.GetExitCodeProcess(process,ctypes.byref(code))) and code.value==259
            finally:kernel.CloseHandle(process)
            if not alive:raise RuntimeError('辅助进程已退出，请点“连接游戏”')
    except FileNotFoundError:raise RuntimeError('辅助进程尚未启动，请点“连接游戏”')
    mutex=kernel.CreateMutexW(None,False,'Local\\MirSourceSaleCommandClient_'+instance_context.slot())
    if not mutex:raise RuntimeError('无法建立操作锁')
    acquired=kernel.WaitForSingleObject(mutex,0) in (0,0x80)
    try:
        if not acquired:raise RuntimeError('已有工具操作正在执行，请先等待或停止')
        return _drive_locked(actions,cancel)
    finally:
        if acquired:kernel.ReleaseMutex(mutex)
        kernel.CloseHandle(mutex)


def _drive_locked(actions,cancel=None):
    import sys
    sys.path.insert(0,str(SOURCE.parent/'fast-sale'))
    from cycle_stats import append_runtime_event
    log_directory=instance_context.runtime_root()/'outputs'/'挂机统计'
    for action in actions:
        if action.get('foreground') and not instance_context.foreground_allowed():raise RuntimeError('双号实例仅支持后台输入')
        if cancel is not None and cancel.is_set():raise RuntimeError('已停止，未发送新操作')
        previous=json.loads((ROOT/'source-sale-result.json').read_text(encoding='utf8'))
        step=previous.get('step',0)+1
        data=dict(action,step=step)
        action_started=time.monotonic()
        append_runtime_event(log_directory,{'event':'command_start','step':step,'action':action['action'],
            'categories':action.get('categories'),'foreground':action.get('foreground',False),
            'game_pid':previous.get('state',{}).get('game_pid')})
        (ROOT/'source-sale-cancel.json').unlink(missing_ok=True)
        temp=ROOT/'source-sale-command.tmp'
        temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
        for attempt in range(50):
            try:
                temp.replace(ROOT/'source-sale-command.json')
                break
            except PermissionError:
                if attempt==49:raise
                time.sleep(.02)
        monitoring=action.get('categories') in (['监测双包'],['监测并回城出售'],['挂机清包循环'],['接续当前挂机图循环'],['孤岛每日自动挑战'],['接续孤岛自动挑战'])
        deadline=time.monotonic()+(43300 if monitoring else 600 if action['action']=='shop_route' else 50)
        while time.monotonic()<deadline:
            if cancel is not None and cancel.is_set():
                cancel_temp=ROOT/'source-sale-cancel.tmp'
                cancel_temp.write_text(json.dumps({'step':step,'requested_by':'user','reason':'点击工具停止按钮或关闭工具'}),encoding='utf8')
                cancel_temp.replace(ROOT/'source-sale-cancel.json')
            try:result=json.loads((ROOT/'source-sale-result.json').read_text(encoding='utf8'))
            except (OSError,ValueError):time.sleep(.1);continue
            if result.get('step')==step:
                shutil.copy2(ROOT/'source-sale-result.json',ROOT/f'shop-test-step-{step}.json')
                shutil.copy2(ROOT/'source-sale-current.png',ROOT/f'shop-test-step-{step}.png')
                state=result.get('state',{})
                append_runtime_event(log_directory,{'event':'command_stopped' if result.get('error') else 'command_complete',
                    'step':step,'seconds':round(time.monotonic()-action_started,2),'action':action['action'],
                    'categories':action.get('categories'),'error':result.get('error'),
                    'last_stage':(result.get('progress') or [None])[-1],'position':state.get('player'),
                    'held_item':state.get('held'),'sale_item':state.get('sale_item'),
                    'ui_bounds':state.get('bounds'),'visible':state.get('visible'),
                    'wallet':state.get('wallet'),'recent_inputs':state.get('recent_inputs'),
                    'snapshot':str(ROOT/f'shop-test-step-{step}.json')})
                if result.get('error'):raise RuntimeError(result['error'])
                print(json.dumps({'step':step,'action':action['action'],'count':(result.get('result') or {}).get('count') if action['action']=='category' else None},ensure_ascii=True),flush=True)
                break
            time.sleep(.1)
        else:
            cancel_temp=ROOT/'source-sale-cancel.tmp'
            cancel_temp.write_text(json.dumps({'step':step,'requested_by':'driver','reason':'辅助进程响应超时'}),encoding='utf8')
            cancel_temp.replace(ROOT/'source-sale-cancel.json')
            append_runtime_event(log_directory,{'event':'command_timeout','step':step,'action':action['action']})
            raise TimeoutError('辅助进程响应超时，已请求停止当前操作')
    return result
