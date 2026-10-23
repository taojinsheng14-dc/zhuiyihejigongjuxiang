"""Read-only sampling thread hosted by the existing elevated helper."""
import ctypes
from ctypes import wintypes as w
import json
from pathlib import Path
import threading
import time

from fast_sale import Session, DEFAULT_GUARD_NAMES
from engine import MemoryReader


class ReadOnlyProbe(Session):
    def __init__(self,binding):
        from background_sale import BackgroundSession
        self.reader=MemoryReader();self.u=ctypes.WinDLL('user32',use_last_error=True)
        self.hwnd=binding['hwnd'];self.last_guard=0
        self.u.GetWindowDpiAwarenessContext.argtypes=[w.HWND]
        self.u.GetWindowDpiAwarenessContext.restype=ctypes.c_void_p
        self.u.SetThreadDpiAwarenessContext.argtypes=[ctypes.c_void_p]
        self.u.SetThreadDpiAwarenessContext.restype=ctypes.c_void_p
        self.u.GetClientRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
        self.u.GetWindowThreadProcessId.argtypes=[w.HWND,ctypes.POINTER(w.DWORD)]
        self.reader.connect(binding['pid'])
        try:
            self.base=self.module_base()
            if self.read(self.base,2)!=b'MZ':raise RuntimeError('监控目标模块不符')
            self.parent=self.uint(self.base+0x2d4b6c)
            # Reuse only read operations; never Session.__init__ or input helpers.
            for name in ('client_size','player','currency_snapshot','control_info','login_stage',
                         'nearby_monsters','_nearby_monsters_snapshot','scene_actor_snapshot','nearby_players'):
                setattr(self,name,getattr(BackgroundSession,name).__get__(self,type(self)))
        except Exception:
            self.close();raise

    def check(self):
        if not self.reader.alive():raise RuntimeError('游戏已退出，等待重新连接')
        pid=w.DWORD();self.u.GetWindowThreadProcessId(self.hwnd,ctypes.byref(pid))
        if pid.value!=self.reader.pid:raise RuntimeError('游戏窗口已变化，等待重新连接')
        if time.monotonic()-self.last_guard>=2:
            if self.reader.guard_matches(DEFAULT_GUARD_NAMES):raise RuntimeError('其他游戏保护名单触发，暂停读取')
            self.last_guard=time.monotonic()

    def pause(self,seconds):time.sleep(seconds)


def build_sample(data,pid,sequence,wallet,wallet_at,now=None):
    from random_hunt import target_monsters
    targets=target_monsters(data['monsters'],data['radius'])
    return {'ok':True,'sequence':sequence,'observed_epoch':time.time() if now is None else now,
            'position':list(data['player']),'radius':data['radius'],'count':data['nearby_alive'],
            'by_name':data['nearby_by_name'],'target_count':len(targets),
            'read_ms':round(data['seconds']*1000,2),'game_pid':pid,'sample_interval_ms':200,
            'wallet':wallet,'wallet_observed_epoch':wallet_at,'read_errors':data['read_errors'],
            'loaded_count':data['loaded_monster_alive'],
            'loaded_max_distance':max((row.get('distance',0) for row in data['monsters'] if not row.get('dead')),default=0),
            'sampler':'helper_thread'}


class LiveSampler:
    def __init__(self,binding,path,extra=None):
        self.binding=binding;self.path=Path(path);self.stop_event=threading.Event()
        self.extra=extra or (lambda:{})
        self.latest=None;self.thread=threading.Thread(target=self.worker,daemon=True,name='MirLiveReadOnly')
        self.thread.start()

    def stop(self):
        self.stop_event.set();self.thread.join(timeout=2)

    def worker(self):
        from random_hunt import load_settings
        from combat_metrics import ExperienceTracker,read_experience
        metrics=ExperienceTracker(self.path.parent/'战斗统计')
        probe=None;key=None;sequence=0;wallet=None;wallet_at=0;settings_at=0;radius=12
        self.path.parent.mkdir(parents=True,exist_ok=True)
        try:
            while not self.stop_event.is_set():
                started=time.monotonic()
                try:
                    binding=self.binding();current=(binding['pid'],binding['hwnd'])
                    if current!=key or probe is None:
                        if probe is not None:probe.close()
                        probe=ReadOnlyProbe(binding);key=current;wallet=None;wallet_at=0
                    if started-settings_at>=1:
                        settings=load_settings();radius=settings.radius;settings_at=started
                    probe.check();stage=probe.login_stage()
                    if stage!='playing':raise RuntimeError('当前状态：'+stage)
                    data=probe.nearby_monsters(radius)
                    players=probe.nearby_players(settings.player_radius)
                    if data['read_errors']:raise RuntimeError('场景对象变化，等待有效采样')
                    if time.time()-wallet_at>=1:
                        wallet=probe.currency_snapshot();wallet_at=time.time()
                    if self.binding()!=binding:raise RuntimeError('客户端切换，等待重新采样')
                    sequence+=1;sample=build_sample(data,key[0],sequence,wallet,wallet_at)
                    sample.update(player_count=len(players),player_radius=settings.player_radius)
                    sample['random']=dict(self.extra())
                    try:sample['combat']=metrics.update(read_experience(probe),context=sample)
                    except Exception as error:
                        sample['combat']={**metrics.summary(),'available':False,'error':str(error)}
                except Exception as error:
                    sample={'ok':False,'observed_epoch':time.time(),'error':str(error),'sampler':'helper_thread'}
                    if probe is not None and not probe.reader.alive():probe.close();probe=None;key=None
                self.latest=sample
                try:
                    temporary=self.path.with_suffix('.live.tmp')
                    temporary.write_text(json.dumps(sample,ensure_ascii=False),encoding='utf8')
                    temporary.replace(self.path)
                except OSError:pass
                self.stop_event.wait(max(.01,.2-(time.monotonic()-started)))
        finally:
            try:metrics.save()
            except OSError:pass
            if probe is not None:probe.close()
