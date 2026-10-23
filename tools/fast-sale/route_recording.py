"""Read-only route recording, restricted to clicks inside the game window."""
import ctypes
from ctypes import wintypes as w
import hashlib
import json
from pathlib import Path
import struct
import threading
import time

def start_recording(session):
    if getattr(session,'_route_recording',False):raise RuntimeError('路线已在录制中')
    session.check()
    directory=Path(__file__).resolve().parents[2]/'outputs'/'route-recordings'/time.strftime('%Y%m%d-%H%M%S')
    directory.mkdir(parents=True,exist_ok=False)
    session._route_stop=threading.Event()
    session._route_recording=True
    session._route_record_directory=directory
    session._route_record_count=0
    def worker():
        started=time.monotonic();last_sample=0;previous={1:False,2:False};active=set();pending=[];sample_count=0;previous_ui=None
        try:
            with (directory/'route.jsonl').open('w',encoding='utf8',buffering=1) as stream:
                def emit(kind,**fields):
                    stream.write(json.dumps(dict(kind=kind,seconds=round(time.monotonic()-started,3),**fields),ensure_ascii=False)+'\n')
                emit('start',game_pid=session.reader.pid,hwnd=int(session.hwnd),client_size=session.client_size())
                while not session._route_stop.wait(.02):
                    now=time.monotonic()
                    try:
                        if not session.reader.alive():
                            emit('game_closed');break
                        xy=session.player()
                        if now-last_sample>=.1:
                            obj=session.uint(session.uint(session.base+0x2ba608));header=session.read(obj+4,52)
                            ui={key:session.visible(key) for key in ('merchant','sell','bag')}
                            emit('position',xy=xy,map_id=hashlib.sha256(header).hexdigest()[:16],map_header=header.hex(),**ui)
                            if previous_ui is not None and ui!=previous_ui:
                                emit('ui_change',xy=xy,before=previous_ui,after=ui)
                                pending.append(now+.2)
                            previous_ui=ui
                            sample_count+=1;last_sample=now
                        cursor=w.POINT();session.u.GetCursorPos(ctypes.byref(cursor))
                        # The recorder never captures clicks on other applications.
                        hit=session.u.WindowFromPoint(cursor)
                        inside=(hit==session.hwnd)
                        for key,label in ((1,'left'),(2,'right')):
                            pressed=bool(session.u.GetAsyncKeyState(key)&0x8000)
                            if pressed and not previous[key] and inside:
                                active.add(key)
                                prior=session.u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
                                try:
                                    origin=w.POINT();session.u.ClientToScreen(session.hwnd,ctypes.byref(origin))
                                    rect=w.RECT();session.u.GetClientRect(session.hwnd,ctypes.byref(rect))
                                finally:session.u.SetThreadDpiAwarenessContext(prior)
                                lw,lh=session.client_size()
                                if rect.right and rect.bottom:
                                    session._route_record_count+=1
                                    emit('mouse_down',button=label,xy=xy,screen=[cursor.x,cursor.y],
                                         client=[round((cursor.x-origin.x)*lw/rect.right),round((cursor.y-origin.y)*lh/rect.bottom)],
                                         origin=[origin.x,origin.y],physical_size=[rect.right,rect.bottom])
                            elif not pressed and previous[key] and key in active:
                                active.remove(key)
                                emit('mouse_up',button=label,xy=xy)
                                pending.append(now+.35)
                            previous[key]=pressed
                        if pending and now>=pending[0]:
                            pending.pop(0)
                            name=f'click-{session._route_record_count:04d}-{int((now-started)*1000)}.png'
                            try:
                                session.capture_client().save(directory/name)
                                emit('screenshot',file=name,xy=session.player())
                            except (OSError,RuntimeError) as error:emit('capture_failed',error=str(error))
                    except (OSError,RuntimeError,ValueError,struct.error) as error:
                        emit('read_retry',error=str(error));session._route_stop.wait(.2)
                emit('stop',clicks=session._route_record_count,samples=sample_count)
            summary={'directory':str(directory),'clicks':session._route_record_count,'samples':sample_count,
                     'duration_seconds':round(time.monotonic()-started,1),'automatic_inputs_sent':0}
            (directory/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
            session._route_record_summary=summary
        finally:session._route_recording=False
    session._route_thread=threading.Thread(target=worker,name='MirRouteReadOnlyRecorder',daemon=True)
    session._route_thread.start()
    return {'status':'录制中；自动输入已禁用','directory':str(directory)}

def stop_recording(session):
    thread=getattr(session,'_route_thread',None)
    if not thread:raise RuntimeError('没有正在录制的路线')
    session._route_stop.set();thread.join(timeout=8)
    if thread.is_alive():raise RuntimeError('录制正在保存，请稍后再结束')
    result=getattr(session,'_route_record_summary',{'directory':str(session._route_record_directory),'status':'录制已停止'})
    from analyze_route import analyze_directory
    reference=analyze_directory(session._route_record_directory)
    result['interface_changes']=len(reference['changes'])
    (session._route_record_directory/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result
