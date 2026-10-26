"""Read-only state checks and client-relative Win32 mouse messages."""
import ctypes
from ctypes import wintypes as w
import struct
import sys
import json
from pathlib import Path
import time
import importlib
import instance_context
import credential_store
importlib.reload(credential_store)
import equipment
importlib.reload(equipment)
import inventory_flow
importlib.reload(inventory_flow)
import map_navigation
importlib.reload(map_navigation)
import recovery_ledger
importlib.reload(recovery_ledger)
from fast_sale import Session, Input, button_center, grid_center, DEFAULT_GUARD_NAMES, CONTROLS
from equipment import CATEGORIES, WEAPONS, sale_plan


class GameSessionLost(RuntimeError):
    """A verified death or a login screen interrupted an active sale."""


class NpcDialogNotOpened(RuntimeError):
    """Verified actor clicks completed but no merchant dialog was observed."""


class SaleRouteIncomplete(RuntimeError):
    def __init__(self, message, pending=None):
        super().__init__(message)
        self.pending = pending


class WeaponShopExitBlocked(RuntimeError):
    """The verified shop route is obstructed; other safety failures propagate."""


class SaleConfirmationStalled(RuntimeError):
    def __init__(self,item,context):
        super().__init__('同一件待售装备补确认一次仍未生效：'+item)
        self.item=item;self.context=context


def query_client_size(user32, hwnd, context):
    """Query coordinates in the target window's DPI space, then restore the caller."""
    previous = user32.SetThreadDpiAwarenessContext(context)
    if not previous:
        raise RuntimeError('无法读取游戏的DPI坐标空间')
    try:
        rect = w.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            raise RuntimeError('游戏窗口已失效')
        return rect.right, rect.bottom
    finally:
        user32.SetThreadDpiAwarenessContext(previous)


def text_masks_match(expected,actual,size,coverage=.95):
    """Match known text, allowing at most one pixel of antialiased edge drift."""
    if len(expected)!=len(actual) or sum(expected)<20:return False
    overlap=sum(a and b for a,b in zip(expected,actual))
    if overlap/sum(expected)>=coverage and overlap/max(1,sum(actual))>=coverage:return True
    if not .9<sum(actual)/sum(expected)<1.1:return False
    from PIL import Image,ImageFilter
    def expand(values):
        mask=Image.new('L',size);mask.putdata([255 if v else 0 for v in values])
        return [v>0 for v in mask.filter(ImageFilter.MaxFilter(3)).get_flattened_data()]
    ea,eb=expand(expected),expand(actual)
    return (sum(a and b for a,b in zip(expected,eb))/sum(expected)>.97
            and sum(a and b for a,b in zip(actual,ea))/sum(actual)>.97)


class BackgroundSession(Session):
    LOGIN_SETTLE_SECONDS=5
    def configure_character_identity(self):
        selected=instance_context.binding()
        try:
            saved_login=credential_store.load()
            try:saved_character=saved_login.get('character')
            finally:saved_login.clear()
        except RuntimeError:saved_character=None
        # A manually selected live role is independent of saved login credentials.
        # Credentials are checked again before any account/password input.
        self._expected_character=(selected or {}).get('character') or saved_character or ('大鱼' if instance_context.slot()=='1' else '')
        if instance_context.slot()=='2' and not self._expected_character:
            raise RuntimeError('账号2尚未绑定角色，请在已登录角色窗口选择绑定')

    def find_session_game(self):
        selected=instance_context.binding()
        if selected:
            instance_context.verify_binding(selected)
            game=self.reader.find_game(selected['pid'])
            if game:return game
        elif instance_context.slot()=='2':
            raise RuntimeError('账号2必须先选择并绑定游戏角色')
        else:
            game=self.reader.find_game()
            if game:return game
        # A logged-out client has no character suffix in its title.
        trusted=map_navigation.MAP_DIRECTORY.parent.resolve()
        candidates=[]
        @self.reader.callback_type
        def visit(hwnd,unused):
            if not self.u.IsWindowVisible(hwnd):return True
            title=ctypes.create_unicode_buffer(512)
            self.u.GetWindowTextW(hwnd,title,512)
            if title.value!='BLUEM2':return True
            if selected:
                bound_pid=w.DWORD();self.u.GetWindowThreadProcessId(hwnd,ctypes.byref(bound_pid))
                if bound_pid.value!=selected['pid']:return True
            pid=w.DWORD();self.u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            try:
                path=self.process_image_path(pid.value)
                if path.parent.resolve()==trusted:
                    candidates.append((pid.value,title.value,path.name))
            except (OSError,RuntimeError):pass
            return True
        self.u.EnumWindows(visit,0)
        if len(candidates)>1:raise RuntimeError('同目录登录客户端不是唯一一个，未自动连接')
        return candidates[0] if candidates else None

    def __init__(self):
        self.mutex = None
        super().__init__()
        self._game_install_directory=self.process_image_path(self.reader.pid).parent
        self.u.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
        self.u.PostMessageW.restype = w.BOOL
        self.u.GetClientRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
        self.u.GetWindowDpiAwarenessContext.argtypes = [w.HWND]
        self.u.GetWindowDpiAwarenessContext.restype = ctypes.c_void_p
        self.u.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        self.u.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        self.events = []
        self.configure_character_identity()
        self.cancelled = lambda: False
        self.sales = []
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, w.BOOL, w.LPCWSTR]
        kernel.CreateMutexW.restype = w.HANDLE
        self.mutex = kernel.CreateMutexW(None, False, 'Local\\MirShopSale_' + str(self.reader.pid))
        if not self.mutex or ctypes.get_last_error() == 183:
            self.close()
            raise RuntimeError('同一游戏已有出售程序正在连接，请先关闭另一实例')

    def close(self):
        if getattr(self, 'mutex', None):
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CloseHandle.argtypes = [w.HANDLE]
            kernel.CloseHandle(self.mutex)
            self.mutex = None
        super().close()

    def process_image_path(self,pid):
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
        kernel.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)]
        kernel.CloseHandle.argtypes=[w.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:raise RuntimeError('无法核对游戏进程路径')
        try:
            buffer=ctypes.create_unicode_buffer(32768);size=w.DWORD(len(buffer))
            if not kernel.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)):
                raise RuntimeError('无法核对游戏进程路径')
            return Path(buffer.value)
        finally:kernel.CloseHandle(handle)

    def reconnect_running_client(self):
        """Rebind only an already-running, uniquely matched client in the same install."""
        if self.reader.alive():return False
        if instance_context.binding():
            raise RuntimeError('绑定角色的客户端已退出，双号模式请重新选择对应角色；未自动改绑')
        try:self.check()
        except RuntimeError as error:
            if not str(error).startswith('目标游戏已关闭或重启'):raise
        trusted=getattr(self,'_game_install_directory',None)
        if trusted is None and getattr(self,'_map_directory',None):trusted=self._map_directory.parent
        if trusted is None:raise RuntimeError('缺少已验证的游戏目录，未重连登录进程')
        candidates=[];u=self.u
        @self.reader.callback_type
        def visit(hwnd,unused):
            if not u.IsWindowVisible(hwnd):return True
            title=ctypes.create_unicode_buffer(512);u.GetWindowTextW(hwnd,title,512)
            if title.value!='BLUEM2' and not(title.value.startswith('追忆') and '合击-' in title.value and ' - ' in title.value):return True
            pid=w.DWORD();u.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            try:
                path=self.process_image_path(pid.value)
                if path.parent.resolve()==Path(trusted).resolve():candidates.append((pid.value,hwnd))
            except (OSError,RuntimeError):pass
            return True
        u.EnumWindows(visit,0)
        if len(candidates)!=1:raise RuntimeError('同目录登录客户端不是唯一一个，未自动重连')
        pid,hwnd=candidates[0];old_pid=self.reader.pid
        self.close();self.reader.connect(pid);self.hwnd=hwnd
        self.base=self.module_base()
        if self.read(self.base,2)!=b'MZ':raise RuntimeError('新客户端主模块校验失败')
        self.parent=self.uint(self.base+0x2d4b6c);self.controls={}
        for key,(offset,name) in CONTROLS.items():
            info=self.control_info(offset,name);self.controls[key]=info['object']
        self.inventory()
        self._game_install_directory=Path(trusted);self.active_merchant=None
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateMutexW.argtypes=[ctypes.c_void_p,w.BOOL,w.LPCWSTR];kernel.CreateMutexW.restype=w.HANDLE
        self.mutex=kernel.CreateMutexW(None,False,'Local\\MirShopSale_'+str(pid))
        if not self.mutex or ctypes.get_last_error()==183:
            self.close();raise RuntimeError('新客户端已有其他出售实例，未继续')
        self.events.append({'event':'client_reconnected','old_pid':old_pid,'game_pid':pid})
        return True

    def activate(self):
        # Intentionally do not activate the window or move the physical cursor.
        self.check()

    def check(self):
        if isinstance(self,ForegroundSession) and not instance_context.foreground_allowed():
            raise RuntimeError('双号实例仅支持后台输入，未发送前台操作')
        if getattr(self,'_route_recording',False):
            raise RuntimeError('正在录制手动路线，已禁用自动输入')
        if hasattr(self,'events') and time.monotonic()-getattr(self,'_last_cancel_check',0)>.1:
            self._last_cancel_check=time.monotonic()
            directory=instance_context.helper_directory()
            try:
                cancellation=json.loads((directory/'source-sale-cancel.json').read_text(encoding='utf8'))
                command=json.loads((directory/'source-sale-command.json').read_text(encoding='utf8'))
                if cancellation.get('step')==command.get('step'):
                    who=str(cancellation.get('requested_by','未注明来源'))[:40]
                    reason=str(cancellation.get('reason','收到停止请求'))[:160]
                    raise RuntimeError('已停止（来源：%s；原因：%s）；保留当前物品状态' % (who,reason))
            except (OSError,ValueError):pass
        if getattr(self, 'cancelled', lambda: False)():
            raise RuntimeError('已停止；如物品仍被拿起，请手动放回')
        if (getattr(self,'hwnd',None) and self.u.GetForegroundWindow()==self.hwnd
                and self.u.GetAsyncKeyState(0x1b)&0x8000):
            raise RuntimeError('已在游戏窗口按Esc停止；如鼠标仍拿着物品，请手动放回')
        now=time.monotonic()
        if now-self.last_guard>=.5:
            if self.reader.guard_matches(DEFAULT_GUARD_NAMES):raise RuntimeError('其他游戏保护名单触发，停止')
            self.last_guard=now
        if getattr(self,'hwnd',None) and getattr(self.reader,'pid',None):
            pid=w.DWORD()
            self.u.GetWindowThreadProcessId(self.hwnd,ctypes.byref(pid))
            if pid.value!=self.reader.pid or not self.reader.alive():
                if getattr(self,'_sale_recovery_enabled',False) and not getattr(self,'_recovering',False):
                    raise GameSessionLost('运行中的客户端已退出或切换进程，暂停当前物品操作并转入恢复')
                raise RuntimeError('目标游戏已关闭或重启，停止操作')
        if hasattr(self,'events') and now-getattr(self,'_last_live_request_check',0)>=.5:
            self._last_live_request_check=now
            request=instance_context.helper_directory()/'live-monitor-request.json'
            if request.exists():
                request.unlink(missing_ok=True)
                self.start_live_monitor()
        if (getattr(self,'_sale_recovery_enabled',False)
                and not getattr(self,'_recovering',False)
                and not getattr(self,'_dismissing_town_notice',False)
                and now-getattr(self,'_last_session_check',0)>.15):
            self._last_session_check=now
            stage=self.login_stage()
            if stage=='message' and self.dismiss_town_hunt_notice():stage=self.login_stage()
            if stage!='playing':
                if stage=='message' and not any(self.recovery_message_matches(kind) for kind in ('disconnected','logout','welcome')):
                    raise RuntimeError('出现普通游戏提示，已停止；不会当作掉线重登')
                raise GameSessionLost('出售过程中角色死亡或连接中断：'+stage)

    def client_size(self):
        context = self.u.GetWindowDpiAwarenessContext(self.hwnd)
        if not context: raise RuntimeError('无法读取游戏窗口DPI信息')
        return query_client_size(self.u, self.hwnd, context)

    def physical_client_size(self):
        return query_client_size(self.u, self.hwnd, ctypes.c_void_p(-4))

    def navigation_map(self,header):
        from map_navigation import load_matching_map
        directory=getattr(self,'_map_directory',None)
        if directory is None:
            psapi=ctypes.WinDLL('psapi',use_last_error=True)
            psapi.GetModuleFileNameExW.argtypes=[w.HANDLE,w.HMODULE,w.LPWSTR,w.DWORD]
            psapi.GetModuleFileNameExW.restype=w.DWORD
            path=ctypes.create_unicode_buffer(32768)
            if not psapi.GetModuleFileNameExW(self.reader.handle,self.base,path,len(path)):
                raise RuntimeError('无法读取游戏安装目录，未执行寻路')
            directory=Path(path.value).parent/'map'
            if not directory.is_dir():raise RuntimeError('游戏安装目录下未找到map文件夹')
            self._map_directory=directory
        return load_matching_map(header,directory)

    def current_map_name(self,header):
        from map_navigation import matching_map_file
        directory=getattr(self,'_map_directory',None)
        if directory is None:
            install=getattr(self,'_game_install_directory',None)
            if install is None:raise RuntimeError('缺少已核对的游戏地图目录')
            directory=Path(install)/'map'
        return matching_map_file(header,directory).name

    def capture_client(self):
        from PIL import ImageGrab, Image
        capture = ImageGrab.grab(window=self.hwnd).convert('RGB')
        logical = self.client_size()
        if capture.size == logical:
            return capture
        if capture.size == self.physical_client_size():
            return capture.resize(logical, Image.Resampling.LANCZOS)
        raise RuntimeError('截图尺寸与游戏客户区不一致，停止菜单识别')

    def begin_background_input(self):
        """Enable message handling briefly without focus or cursor changes."""
        self.check()
        if self.u.IsIconic(self.hwnd):raise RuntimeError('游戏已最小化，未发送后台输入')
        deadline=time.monotonic()+30
        while any(self.u.GetAsyncKeyState(vk)&0x8000 for vk in (1,2)):
            if time.monotonic()>=deadline:raise RuntimeError('鼠标按键持续占用，暂停后台输入')
            self.pause(.05)
        self.wait_mouse_modifiers_released()
        self.u.SendMessageTimeoutW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM,w.UINT,w.UINT,ctypes.POINTER(ctypes.c_size_t)]
        self.u.SendMessageTimeoutW.restype=w.LPARAM
        result=ctypes.c_size_t()
        if not self.u.SendMessageTimeoutW(self.hwnd,0x1c,1,0,2,500,ctypes.byref(result)):
            raise RuntimeError('后台输入准备未确认，停止')

    def click(self, point):
        if isinstance(point,dict):
            return self.background_mouse(point['xy'],point.get('button','left'))
        return self.background_mouse(point,'left',track_movement=False,move_settle=.12,
                                     dpi_scaled=True,button_hold=.15,restore_client_focus=True)

    def ui_right_click(self,point):
        BackgroundSession.background_mouse(self,point,'right',track_movement=False,
            move_settle=.12,dpi_scaled=True,button_hold=.15,restore_client_focus=True)

    def drag_ui(self,start,end):
        if self.held_item() or self.sale_item() or self.inflight_item():raise RuntimeError('物品操作未结束，未拖动界面')
        logical=self.client_size();physical=self.physical_client_size()
        result=ctypes.c_size_t()
        def send(message,key,point):
            self.check();x,y=point
            if not (0<=x<logical[0] and 0<=y<logical[1]):raise RuntimeError('界面拖动超出客户区')
            px=round(x*physical[0]/logical[0]);py=round(y*physical[1]/logical[1])
            if not self.u.SendMessageTimeoutW(self.hwnd,message,key,(py<<16)|(px&0xffff),2,500,ctypes.byref(result)):
                raise RuntimeError('界面拖动消息未确认，停止')
        self.begin_background_input()
        try:
            for message,key in ((0x6,1),(0x7,0)):
                if not self.u.SendMessageTimeoutW(self.hwnd,message,key,0,2,500,ctypes.byref(result)):
                    raise RuntimeError('界面拖动焦点消息未确认')
            send(0x200,0,start);self.pause(.15)
            send(0x201,1,start);self.pause(.15)
            for i in range(1,16):
                send(0x200,1,(start[0]+(end[0]-start[0])*i/15,start[1]+(end[1]-start[1])*i/15))
                self.pause(.06)
            send(0x202,0,end);self.pause(.2)
        finally:self.clear_background_mouse()
        self.events.append({'input':'background_ui_drag','from':list(start),'to':list(end),'logical':logical,'physical':physical})

    def clear_background_mouse(self):
        self.u.SendMessageTimeoutW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM,w.UINT,w.UINT,ctypes.POINTER(ctypes.c_size_t)]
        self.u.SendMessageTimeoutW.restype=w.LPARAM
        result=ctypes.c_size_t()
        # MouseMove sets the game's internal hover/inside state. Explicitly
        # leave after synthetic input so physical clicks in other apps cannot
        # act on that stale inside position.
        foreground=int(self.u.GetForegroundWindow() or 0)
        messages=[(0x202,0,0xffffffff),(0x205,0,0xffffffff),(0x200,0,0xffffffff),(0x2a3,0,0),(0x1f,0,0)]
        if foreground!=self.hwnd and not getattr(self,'_recovering',False):messages.extend([(0x8,foreground,0),(0x6,0,foreground),(0x1c,0,0)])
        for message,key,lp in messages:
            if not self.u.SendMessageTimeoutW(self.hwnd,message,key,lp,2,500,ctypes.byref(result)):
                raise RuntimeError('后台鼠标状态清理未确认，停止')

    def background_mouse(self,point,button='left',track_movement=True,move_settle=0,dpi_scaled=True,button_hold=0,restore_client_focus=False):
        self.check()
        if self.u.IsIconic(self.hwnd):raise RuntimeError('游戏已最小化，暂停后台点击')
        if button not in ('left','right'):raise RuntimeError('未知鼠标按键')
        x,y=map(round,point);width,height=self.client_size()
        if not(0<=x<width and 0<=y<height):raise RuntimeError('点击超出游戏客户区')
        self.u.SendMessageTimeoutW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM,w.UINT,w.UINT,ctypes.POINTER(ctypes.c_size_t)]
        self.u.SendMessageTimeoutW.restype=w.LPARAM
        message_x,message_y=x,y
        logical_messages=getattr(self,'_ui_logical_messages',False)
        if dpi_scaled and not logical_messages:
            physical=self.physical_client_size();logical=self.client_size()
            message_x=round(x*physical[0]/logical[0]);message_y=round(y*physical[1]/logical[1])
        lp=(message_y<<16)|(message_x&0xffff)
        output=ctypes.c_size_t()
        def send(message,flags,position=None):
            if not self.u.SendMessageTimeoutW(self.hwnd,message,flags,lp if position is None else position,2,500,ctypes.byref(output)):
                raise RuntimeError('后台鼠标消息未完成，停止')
        cursor=w.POINT();self.u.GetCursorPos(ctypes.byref(cursor))
        before=[cursor.x,cursor.y]
        # Login/recovery UI exists before a readable player actor exists.
        # Movement clicks must still require a valid player position.
        before_position=None if getattr(self,'_recovering',False) and not track_movement else self.player()
        origin=w.POINT()
        previous=self.u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        try:self.u.ClientToScreen(self.hwnd,ctypes.byref(origin))
        finally:self.u.SetThreadDpiAwarenessContext(previous)
        down,up,key=(0x201,0x202,1) if button=='left' else (0x204,0x205,2)
        try:
            self.begin_background_input()
            if restore_client_focus:
                for message,flags,param in ((0x6,1,0),(0x7,0,0)):
                    if not self.u.SendMessageTimeoutW(self.hwnd,message,flags,param,2,500,ctypes.byref(output)):
                        raise RuntimeError('游戏客户区焦点消息未确认')
            send(0x200,0)
            if move_settle:self.pause(min(.3,max(0,move_settle)))
            # The user's real mouse can update hover while a background click
            # is settling. Reassert this target immediately before both edges.
            self.wait_mouse_modifiers_released()
            send(0x200,0)
            try:
                send(down,key)
                if button_hold:
                    if getattr(self,'_opening_npc_actor',False):
                        # Release before check() can reject a newly opened dialog.
                        time.sleep(min(.3,max(0,button_hold)))
                    else:self.pause(min(.3,max(0,button_hold)))
            finally:
                if button=='left' and getattr(self,'_opening_npc_actor',False):
                    # The down edge may already have opened the NPC menu over
                    # the actor. Never send a held move into that new menu.
                    # If the visibility read fails, release outside as well.
                    release_position=0xffffffff
                    try:
                        if not self.visible('merchant'):release_position=lp
                    finally:
                        send(0x200,0,release_position)
                        send(up,0,release_position)
                else:
                    send(0x200,key)
                    send(up,0)
            self.clear_background_mouse()
            self.events.append({'point':[x,y],'message_point':[message_x,message_y],
                                'message_coordinates':'logical' if logical_messages else 'physical' if dpi_scaled else 'logical',
                                'button':button,'input':'SendMessageTimeout','cursor_before':before,'position_before':before_position,'screen_origin':[origin.x,origin.y],'physical_client':self.physical_client_size()})
            self.pause(.25 if button=='left' else .5)
            if track_movement:
                timeline=[]
                for _ in range(8):
                    timeline.append(self.player())
                    self.pause(.15)
                self.events[-1]['positions']=timeline
        finally:self.clear_background_mouse()

    def pause(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.check()
            time.sleep(min(.05, max(0, deadline-time.monotonic())))

    def right_click(self, point):
        return self.background_mouse(point,'right')

    def _veteran_run_batch(self,tilemap,current,goals,occupied,header,ready,boundary_origin=None):
        from map_navigation import veteran_run_path,veteran_run_batch,validate_veteran_landing
        npc_tiles={tuple(n['map']) for n in self.npcs()}
        # Verified town safe-zone movement can overlap players; only NPCs block it.
        path=veteran_run_path(tilemap,current,goals,npc_tiles)
        destinations=veteran_run_batch(path)
        if not destinations:raise RuntimeError('已经靠近但老兵仍不可点击，停止移动')
        own=self.uint(self.uint(self.base+0x2bac2c));width,height=self.client_size()
        started=time.monotonic();sent=[];previous=current
        for destination in destinations:
            self.check()
            if self.login_stage()!='playing':raise GameSessionLost('靠近老兵时角色死亡或掉线')
            if self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)!=header:
                raise RuntimeError('靠近老兵时地图变化，停止移动')
            if ready():break
            dx=(destination[0]-previous[0])//2;dy=(destination[1]-previous[1])//2
            draw=struct.unpack('<2i',self.read(own+0x17c,8))
            # An upward two-tile aim is exactly on our own sprite. Aim farther
            # along the same run direction when it stays inside the NPC axes.
            point=None
            for reach in (3,2):
                aim=(previous[0]+dx*reach,previous[1]+dy*reach)
                if any(not min(previous[i],320)<=aim[i]<=max(previous[i],320) for i in (0,1)):continue
                if not tilemap.free(aim) or aim in npc_tiles:continue
                candidate=(draw[0]+dx*48*reach,draw[1]+64+dy*32*reach)
                if abs(candidate[0]-draw[0])<=24 and draw[1]-12<=candidate[1]<=draw[1]+72:continue
                point=candidate;break
            if point is None:raise RuntimeError('老兵方向没有避开自身且不越界的跑动点，停止')
            if not(20<point[0]<width-20 and 20<point[1]<height-180):raise RuntimeError('老兵跑动点超出地面范围')
            self.background_mouse(point,'right',track_movement=False);sent.append(destination);previous=destination
            self.pause(.15)
        after=tuple(self.stable_player())
        self.check()
        if self.login_stage()!='playing':raise GameSessionLost('靠近老兵后角色死亡或掉线')
        if self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)!=header:
            raise RuntimeError('靠近老兵后地图变化，停止移动')
        try:landing=validate_veteran_landing(tilemap,current,after,len(sent),origin=boundary_origin)
        except RuntimeError as error:
            if getattr(self,'_stats_enabled',False):
                self.write_stats({'event':'veteran_move_rejected','from':current,'to':after,
                    'expected':sent,'runs':len(sent),'boundary_origin':boundary_origin or current,'reason':str(error)})
            raise
        if getattr(self,'_stats_enabled',False):
            self.write_stats({'event':'veteran_move','from':current,'to':after,'expected':sent,
                              'runs':len(sent),'button':'right','landing':landing,'seconds':round(time.monotonic()-started,3)})
        return after,len(sent)

    def approach_veteran_running(self,npc,progress=lambda message:None):
        if npc['name']!='盟重老兵' or tuple(npc['map'])!=(320,320):raise RuntimeError('老兵目标未核对')
        def ready():return self.veteran_click_point(self.verified_npc_draw(npc)) is not None
        if ready():return {'position':tuple(self.player()),'runs':0}
        current=tuple(self.stable_player())
        if max(abs(current[0]-320),abs(current[1]-320))>50:raise RuntimeError('超出土城老兵附近范围')
        obj=self.uint(self.uint(self.base+0x2ba608));header=self.read(obj+4,52);tilemap=self.navigation_map(header)
        if tilemap.name.lower()!='3.map':raise RuntimeError('未确认土城地图，停止靠近老兵')
        own=self.uint(self.uint(self.base+0x2bac2c));draw=struct.unpack('<2i',self.read(own+0x17c,8))
        occupied={tuple(n['map']) for n in self.npcs() if n['address']!=own}
        goals=[(x,y) for x in range(300,341) for y in range(300,341)
               if self.veteran_click_point((draw[0]+(320-x)*48,draw[1]+(320-y)*32)) is not None]
        progress('同侧靠近老兵；远处连续跑两次后校验，可点击即停')
        actions=[];stuck=0;boundary_origin=current
        for _ in range(16):
            if ready():return {'position':current,'runs':sum(a['runs'] for a in actions),'actions':actions}
            after,count=self._veteran_run_batch(tilemap,current,goals,occupied,header,ready,boundary_origin=boundary_origin)
            actions.append({'from':current,'to':after,'runs':count})
            stuck=stuck+1 if after==current else 0
            if stuck>=3:
                self.recover_stalled_route(progress,'老兵连续三次跑动未移动')
                fresh=self.locate_mengzhong_veteran(progress)
                return self.approach_veteran_running(fresh,progress)
            current=after
        raise RuntimeError('靠近老兵达到有限跑动次数，停止')

    def control_info(self, offset, expected):
        obj = self.uint(self.parent + offset)
        name = self.read(self.uint(obj + 8), 96).split(b'\0')[0].decode('ascii')
        if name != expected: raise RuntimeError('控件不兼容：' + expected)
        return {'object': obj, 'bounds': struct.unpack('<4i', self.read(obj+0x40, 16)),
                'visible': self.read(obj+0x34c, 1) == b'\1'}

    def hero_covers(self, box):
        hero = self.control_info(0x7b0, 'Window_HeroStatus')
        if not hero['visible']: return False
        x, y, w_, h = hero['bounds']
        return box[0] < x+w_ and box[2] > x and box[1] < y+h and box[3] > y

    def visible(self, key):
        return self.read(self.controls[key] + 0x34c, 1) == b'\1'

    def short_item(self, address):
        data = self.read(address, 21)
        if data[0] > 20:
            raise RuntimeError('物品记录不兼容')
        return data[1:1 + data[0]].decode('gb18030')

    def held_item(self):
        return self.short_item(self.uint(self.base + 0x2bb524) + 4)

    def sale_item(self):
        return self.short_item(self.uint(self.base + 0x2baa30))

    def player(self):
        actor = self.uint(self.uint(self.base + 0x2bac2c))
        return struct.unpack('<2i', self.read(actor + 0x68, 8))

    def inflight_item(self):
        address=self.uint(self.base + 0x2ba2b0)+4
        name=self.short_item(address)
        accepted=getattr(self,'_returned_pending_record',None)
        if name and accepted is not None:
            if self.read(address,156)==accepted and self.pending_record_in_bags(accepted)==1 and not(self.held_item() or self.sale_item()):return ''
            self._returned_pending_record=None
        return name

    def pending_record_in_bags(self,record):
        count=0
        for address in (self.base+0x2e1674,self.uint(self.base+0x2ba544)):
            rows=self.read(address,40*156)
            count+=sum(rows[index*156:(index+1)*156]==record for index in range(40))
        return count

    def accept_returned_pending(self,item):
        if self.held_item() or self.sale_item() or self.login_stage()!='playing':return False
        address=self.uint(self.base+0x2ba2b0)+4
        record=self.read(address,156)
        if not 0<record[0]<=20 or record[1:1+record[0]].decode('gb18030')!=item:return False
        if not any(record[0x90:0x98]):return False
        for _ in range(3):
            if self.read(address,156)!=record or self.pending_record_in_bags(record)!=1:return False
            if self.held_item() or self.sale_item():return False
            self.pause(.1)
        self._returned_pending_record=record
        self.log_sale_probe('pending_returned_to_bag_not_sold',item,uid=record[0x90:0x98].hex())
        return True

    def close_panels(self):
        if self.held_item() or self.sale_item() or self.inflight_item():
            raise RuntimeError('物品操作未结束，先停止关闭窗口')
        for attempt in range(2):
            hero=self.control_info(0x7b4,'Window_HeroItemBag')
            if hero['visible']:
                close=self.control_info(0x7b8,'Button_HeroItemBagClose')
                self.click(button_center(hero['bounds'],close['bounds']));self.pause(.2)
            for key,offset,name in [('sell',0x63c,'Button_SellDlgClose'),('bag',0x48c,'Button_ItemBagClose'),('merchant',0x5e4,'Button_MerchantDlgClose')]:
                if self.visible(key):
                    close=self.control_info(offset,name)
                    self.click(button_center(self.bounds(key),close['bounds']));self.pause(.2)
            if not any(self.visible(key) for key in ('sell','bag','merchant')) and not self.control_info(0x7b4,'Window_HeroItemBag')['visible']:
                self.active_merchant=None;return
        raise RuntimeError('关闭窗口两次后仍未确认，停止后续场景读取和行走')

    def walk_tile(self,target,max_steps=50,allow_transition=False,run_enabled=True,run_only=False):
        from map_navigation import load_matching_map
        obj=self.uint(self.uint(self.base+0x2ba608))
        header=self.read(obj+4,52)
        tilemap=self.navigation_map(header)
        start=tuple(self.stable_player());target=tuple(target)
        actors=self.npcs();blocked={tuple(n['map']) for n in actors}
        own_actor=self.uint(self.uint(self.base+0x2bac2c))
        nameptr=self.uint(own_actor+0xc)
        name_length=self.uint(nameptr-4)
        own_name=self.read(nameptr,name_length).decode('gb18030') if 0<name_length<=60 else None
        blocked.update(tuple(n['map']) for n in self.npcs(True)
                       if n['address']!=own_actor and n['name']!=own_name)
        # This tile was observed to enter the neighboring building, even though
        # the local terrain file marks the tile as walkable.
        if tilemap.name.lower()=='5.map':blocked.add((145,327))
        actions=[]
        for step in range(min(max_steps,35)):
            if self.visible('merchant') or self.visible('bag'):
                raise RuntimeError('行走时出现窗口，停止')
            current=start if step==0 else after
            current_obj=self.uint(self.uint(self.base+0x2ba608))
            if self.read(current_obj+4,52)!=header:
                if allow_transition:return {'from':start,'to':current,'transition':True,'actions':actions}
                raise RuntimeError('地图已切换，停止继续移动')
            if current==target:return {'from':start,'to':current,'map_file':tilemap.name,'actions':actions}
            if max(abs(current[0]-start[0]),abs(current[1]-start[1]))>30:
                raise RuntimeError('偏离短距离路线，停止')
            if run_only:
                path=tilemap.run_path(current,[target],blocked)
                destination=path[1];dx=(destination[0]-current[0])//2;dy=(destination[1]-current[1])//2;run=True
            else:
                path=tilemap.path(current,target,blocked)
                dx,dy=path[1][0]-current[0],path[1][1]-current[1]
                run=run_enabled and len(path)>2 and path[2]==(current[0]+2*dx,current[1]+2*dy)
                destination=path[2] if run else path[1]
            actor=self.uint(self.uint(self.base+0x2bac2c))
            draw=struct.unpack('<2i',self.read(actor+0x17c,8))
            point=None
            # A one-tile doorway target must not aim beyond the exit tile.
            reaches=(1,) if not run_enabled else (3,4,2,1)
            for reach in reaches:
                aim=(current[0]+dx*reach,current[1]+dy*reach)
                if not tilemap.free(aim) or aim in blocked:continue
                candidate=(draw[0]+dx*48*reach,draw[1]+64+dy*32*reach)
                if 100<=candidate[0]<=self.client_size()[0]-50 and 80<=candidate[1]<=self.client_size()[1]-200:
                    point=candidate;break
            if point is None:raise RuntimeError('附近没有可用的地面点击点，停止')
            if not(50<=point[0]<=self.client_size()[0]-50 and 50<=point[1]<=self.client_size()[1]-200):
                raise RuntimeError('地图路线点击超出可用区域')
            move_started=time.monotonic()
            self.background_mouse(point,'right' if run else 'left',track_movement=False)
            after=tuple(self.stable_player())
            if getattr(self,'_stats_enabled',False):
                self.write_stats({'event':'route_move','map_file':tilemap.name,'from':current,'to':after,
                                  'expected':destination,'target':target,'button':'right' if run else 'left',
                                  'seconds':round(time.monotonic()-move_started,3)})
            new_obj=self.uint(self.uint(self.base+0x2ba608))
            if self.read(new_obj+4,52)!=header:
                if allow_transition:return {'from':start,'to':after,'transition':True,'actions':actions}
                raise RuntimeError('地图已切换，停止继续移动')
            actions.append({'from':current,'expected':destination,'to':after,'button':'right' if run else 'left'})
            if after!=destination:
                if after==current and destination!=target and sum(a.get('blocked_without_movement',False) for a in actions)<=2:
                    blocked.add(destination)
                    actions[-1]['blocked_without_movement']=True
                    continue
                before_distance=max(abs(current[0]-target[0]),abs(current[1]-target[1]))
                after_distance=max(abs(after[0]-target[0]),abs(after[1]-target[1]))
                if (after!=current and tilemap.free(after) and after_distance<before_distance
                        and max(abs(after[0]-current[0]),abs(after[1]-current[1]))<=2):
                    actions[-1]['replanned_after_obstruction']=True
                    if destination!=target:blocked.add(destination)
                    continue
                raise RuntimeError('实际移动未到规划格子，已停止：%s' % actions[-1])
        raise RuntimeError('短距离路线达到次数上限')

    def return_to_veteran(self):
        self.close_panels()
        npcs=self.npcs()
        veterans=[n for n in npcs if n['name']=='盟重老兵' and tuple(n['map'])==(320,320)]
        if len(veterans)==1:
            self.walk_near_veteran(veterans[0])
            return self.state()
        if any(n['name']=='项链店老板' for n in npcs):
            self.walk_tile((22,13),max_steps=65,allow_transition=True)
            self.pause(.6);self.stable_player()
        current=self.player()
        # Verified exterior landing of this client's Mengzhong jewelry shop.
        if max(abs(current[0]-301),abs(current[1]-294))<=3:
            self.town_verified=True
            self.walk_near_veteran({'name':'盟重老兵','map':(320,320),'address':0})
            return self.state()
        raise RuntimeError('当前商店的出口路线尚未校准')

    def ensure_npc_visible(self,npc):
        self.stable_player()
        self.pause(.5)
        point=struct.unpack('<2i',self.read(npc['address']+0x17c,8))
        if 90<=point[0]<=970 and 90<=point[1]<=550:return
        if npc['name']=='项链店老板' and tuple(npc['map'])==(4,21):
            self.walk_tile((19,14));self.walk_tile((12,14));return
        if npc['name'] in {'戒指店老板','手镯店老板'}:
            self.walk_tile((18,8));return
        x,y=npc['map']
        # Stop as soon as a target becomes visible; do not insist on walking
        # through a counter to a guessed final tile.
        current=self.player()
        gx,gy=x+6,y-4 if y>=6 else y+4
        for _ in range(20):
            point=struct.unpack('<2i',self.read(npc['address']+0x17c,8))
            if 90<=point[0]<=970 and 90<=point[1]<=550:return
            current=self.player()
            dx=(gx>current[0])-(gx<current[0]);dy=(gy>current[1])-(gy<current[1])
            if not(dx or dy):raise RuntimeError('商人在画面外且无法靠近')
            try:self.walk_tile((current[0]+dx,current[1]+dy),max_steps=12)
            except RuntimeError:
                if self.visible('merchant'):
                    self.close_panels()
                else:raise
        self.stable_player()

    def open_mengzhong_veteran(self,progress=lambda message:None):
        """Shared entry for shop and island travel; open_npc handles approach."""
        self.check()
        if self.login_stage()!='playing':raise GameSessionLost('点击老兵前角色死亡或掉线')
        self.close_panels()
        veteran=self.locate_mengzhong_veteran(progress)
        progress('确认盟重老兵，必要时靠近后打开对话')
        self.open_npc(veteran)

    def locate_mengzhong_veteran(self,progress=lambda message:None):
        """Load the known NPC by approaching on a verified town map first."""
        self.dismiss_town_hunt_notice()
        matches=[n for n in self.npcs() if n['name']=='盟重老兵' and tuple(n['map'])==(320,320)]
        if matches:return self.unique_npc('盟重老兵',(320,320))
        self.check()
        if self.login_stage()!='playing':raise GameSessionLost('定位老兵时角色死亡或掉线')
        self.close_panels()
        obj=self.uint(self.uint(self.base+0x2ba608));header=self.read(obj+4,52)
        tilemap=self.navigation_map(header)
        current=tuple(self.stable_player())
        if tilemap.name.lower()!='3.map' or max(abs(current[0]-320),abs(current[1]-320))>50:
            raise RuntimeError('未确认盟重回城区域，不执行寻找老兵的移动')
        progress('老兵尚未加载，按固定坐标右键靠近；对象加载后即停止寻路')
        stuck=0;boundary_origin=current
        for _ in range(16):
            self.check()
            self.dismiss_town_hunt_notice()
            if self.login_stage()!='playing':raise GameSessionLost('靠近老兵时角色死亡或掉线')
            if self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)!=header:
                raise RuntimeError('寻找老兵时地图变化，停止移动')
            matches=[n for n in self.npcs() if n['name']=='盟重老兵' and tuple(n['map'])==(320,320)]
            if matches:return self.unique_npc('盟重老兵',(320,320))
            current=tuple(self.stable_player())
            if max(abs(current[0]-320),abs(current[1]-320))<=8:
                return self.unique_npc('盟重老兵',(320,320))
            own=self.uint(self.uint(self.base+0x2bac2c))
            occupied={tuple(n['map']) for n in self.npcs() if n['address']!=own}
            occupied.add((320,320))
            goals=[(x,y) for x in range(312,329) for y in range(312,329)
                   if tilemap.free((x,y)) and (x,y) not in occupied]
            def ready():
                return any(n['name']=='盟重老兵' and tuple(n['map'])==(320,320) for n in self.npcs())
            after,_=self._veteran_run_batch(tilemap,current,goals,occupied,header,ready,boundary_origin=boundary_origin)
            if after==current:
                stuck+=1
                if stuck>=3:
                    self.recover_stalled_route(progress,'靠近老兵连续三次未移动')
                    return self.locate_mengzhong_veteran(progress)
            else:stuck=0
        raise RuntimeError('寻找老兵达到有限跑动次数，停止')

    def in_mengzhong_return_area(self):
        current=tuple(self.player())
        if max(abs(current[0]-320),abs(current[1]-320))>50:return False
        obj=self.uint(self.uint(self.base+0x2ba608))
        return self.current_map_name(self.read(obj+4,52)).lower()=='3.map'

    def visit_shop(self,store,progress=lambda message:None):
        names={'jewelry':{'项链店老板','戒指店老板','手镯店老板'},
               'clothes':{'张家布衣老板','老张头盔店'},'weapon':{'铁匠铺老板'}}
        self.close_panels()
        actors=self.npcs()
        if any(n['name'] in names[store] for n in actors):return
        if not any(n['name']=='盟重老兵' for n in actors):
            self.return_to_veteran();actors=self.npcs()
        self.open_mengzhong_veteran(progress)
        self.menu_click('shop_transfer')
        before=self.player()
        progress('传送到'+{'jewelry':'首饰店','clothes':'衣服店','weapon':'武器店'}[store])
        self.menu_click({'jewelry':'jewelry_transfer','clothes':'clothes_transfer','weapon':'weapon_transfer'}[store])
        self.wait(lambda:not self.visible('merchant') and self.player()!=before,timeout=8)
        self.pause(.5);self.stable_player()
        actors=self.npcs()
        if not any(n['name'] in names[store] for n in actors):raise RuntimeError('传送后未找到对应商店的商人')

    def sell_cangyue_at_anchor(self, progress=lambda message:None):
        """Revalidate the local standing point between merchants, without travel."""
        position=self.player()
        self.validate_city_ui_layout()
        routes=[('服装店老板',(147,328),'cangyue_sell_clothes',('衣服','头盔')),
                ('首饰店老板',(155,339),'cangyue_sell_jewelry',('戒指','手镯','项链'))]
        actors=self.npcs()
        for name,coordinate,menu,categories in routes:
            matches=[n for n in actors if n['name']==name and tuple(n['map'])==coordinate]
            if len(matches)!=1:
                raise RuntimeError('苍月商人位置未核对成功：'+name)
        results=[]
        for name,coordinate,menu,categories in routes:
            if not any(CATEGORIES.get(item) in categories for item in self.inventory()):continue
            self.close_panels()
            self.cangyue_sale_stand()
            matches=[n for n in self.npcs() if n['name']==name and tuple(n['map'])==coordinate]
            if len(matches)!=1:raise RuntimeError('未唯一找到'+name)
            self.open_cangyue_fixed_sale(name,progress)
            self.wait(lambda:self.visible('sell') and self.visible('bag'))
            for category in categories:
                if any(CATEGORIES.get(item)==category for item in self.inventory()):
                    result=self.sell_category(category,progress,merchant_name=name)
                    results.append(dict(result,category=category,merchant=name))
            self.close_panels()
        return {'categories':results,'count':sum(r['count'] for r in results),
                'remaining_plan':sale_plan(self.inventory())}

    def cangyue_sale_stand(self):
        actors=self.npcs();width,height=self.client_size()
        names={'苍月老兵','首饰店老板','服装店老板'}
        selected=[n for n in actors if n['name'] in names]
        if not any(n['name']=='苍月老兵' and tuple(n['map'])==(139,333) for n in selected):
            raise RuntimeError('未确认苍月地图，停止寻路')
        if len(selected)==3 and all(self.npc_click_point(n['draw']) is not None for n in selected):
            return {'position':self.player(),'moved':False}
        selected=[{'name':name,'map':xy} for name,xy in
                  [('苍月老兵',(139,333)),('服装店老板',(147,328)),('首饰店老板',(155,339))]]
        occupied={tuple(n['map']) for n in self.npcs(True)}|{tuple(n['map']) for n in actors}
        obj=self.uint(self.uint(self.base+0x2ba608));tilemap=self.navigation_map(self.read(obj+4,52))
        own=self.uint(self.uint(self.base+0x2bac2c));draw=struct.unpack('<2i',self.read(own+0x17c,8))
        for goal in ((140,330),(141,330),(140,331),(141,331),(139,329),(142,330),(145,332)):
            if goal in occupied or not tilemap.free(goal):continue
            points=[(draw[0]+(n['map'][0]-goal[0])*48,draw[1]+(n['map'][1]-goal[1])*32+24) for n in selected]
            if not all(self.npc_click_point((x,y-24)) is not None for x,y in points):continue
            if not all(max(abs(n['map'][i]-goal[i]) for i in (0,1))<=12 for n in selected):continue
            return self.walk_tile(goal)
        raise RuntimeError('苍月落点附近暂无可用出售站位，停止等待')

    def unique_npc(self,name,xy=None):
        deadline=time.monotonic()+6
        while True:
            matches=[n for n in self.npcs() if n['name']==name and (xy is None or tuple(n['map'])==tuple(xy))]
            if len(matches)==1:return matches[0]
            if len(matches)>1:
                player=self.player();actor=self.uint(self.uint(self.base+0x2bac2c))
                draw=struct.unpack('<2i',self.read(actor+0x17c,8))
                live=[n for n in matches if abs(n['draw'][0]-(draw[0]+(n['map'][0]-player[0])*48))<=2
                      and abs(n['draw'][1]-(draw[1]+(n['map'][1]-player[1])*32))<=2]
                if len(live)==1:return live[0]
                raise RuntimeError('商人对象仍有歧义：'+name)
            if time.monotonic()>=deadline:raise RuntimeError('等待商人加载超时：'+name)
            self.pause(.25)

    def leave_weapon_shop(self,progress=lambda message:None):
        progress('武器已售完，按用户要求直接使用盟重回城石，不走店门')
        self.close_panels()
        return self.return_from_blocked_weapon_shop(progress,'用户要求武器售完直接回城')

    def leave_weapon_shop_by_door(self,progress=lambda message:None):
        for attempt in range(2):
            self.check()
            if self.login_stage()!='playing':raise GameSessionLost('出武器店时死亡或掉线，转入恢复流程')
            self.close_panels()
            self.unique_npc('铁匠铺老板',(5,9))
            blockers=self.weapon_exit_players()
            if blockers:
                progress('出口附近有其他玩家，直接使用一次盟重回城石')
                return self.return_from_blocked_weapon_shop(progress,'出口附近有其他玩家',blockers)
            try:return self._leave_weapon_shop_by_door(progress)
            except WeaponShopExitBlocked as error:
                if attempt==0:
                    progress('武器店出口受阻，稍等后重新读取路线再试一次')
                    self.pause(2)
                    continue
                progress('武器店两次出门未成功，使用一次盟重回城石兜底')
                return self.return_from_blocked_weapon_shop(progress,str(error))

    def return_from_blocked_weapon_shop(self,progress,reason,blockers=None):
        self.check()
        if self.login_stage()!='playing':raise GameSessionLost('出武器店时死亡或掉线，转入恢复流程')
        self.unique_npc('铁匠铺老板',(5,9))
        returned=self.return_with_hotkey(progress,reason='weapon_shop_exit_blocked')
        return {'town_position':returned['position'],
                'return_stone_used':returned['hotkey_sent'],
                'exit_fallback':reason,'exit_players':blockers or [],'return_result':returned}

    def weapon_exit_players(self):
        """Read only live scene members, not cached heap actor objects."""
        def require_class(address,name):
            vmt=self.uint(address)
            if not self.base<=vmt<self.base+0x300000:raise RuntimeError('出口检查对象类型不符')
            ptr=self.uint(vmt-44);length=self.read(ptr,1)[0]
            if not 1<=length<=80 or self.read(ptr+1,length).decode('ascii')!=name:
                raise RuntimeError('出口检查场景类型不符')
        for attempt in range(3):
            self.check()
            scene=self.uint(self.uint(self.base+0x2ba8fc))
            require_class(scene,'TPlayScene')
            actors=self.uint(scene+0x98);require_class(actors,'TList')
            header=self.read(actors,16);_,items,count,capacity=struct.unpack('<4I',header)
            if not 0<=count<=capacity<=20000:raise RuntimeError('出口检查场景列表容量不符')
            pointers=struct.unpack('<%dI'%count,self.read(items,count*4)) if count else ()
            own=self.uint(self.uint(self.base+0x2bac2c));hero=self.uint(own+0x358)
            map_header=self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)
            blockers=[]
            for address in dict.fromkeys(pointers):
                if address in (own,hero):continue
                raw=self.read(address,0xb0)
                if struct.unpack_from('<I',raw)[0]!=self.base+0x24991c:continue
                x,y=struct.unpack_from('<2i',raw,0x68)
                if raw[0xac] not in (0,1) or not(0<=x<10000 and 0<=y<10000):
                    raise RuntimeError('出口检查人物数据不符')
                if not raw[0xac] and 3<=x<=6 and 15<=y<=17:
                    blockers.append({'address':address,'map':[x,y]})
            if (self.read(actors,16)==header
                    and self.uint(self.uint(self.base+0x2ba8fc))==scene
                    and self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)==map_header):
                return blockers
            if attempt<2:self.pause(.05)
        raise RuntimeError('出口附近人物列表持续变化，停止出门')

    def _leave_weapon_shop_by_door(self,progress=lambda message:None):
        def walk(target,**kwargs):
            try:return self.walk_tile(target,**kwargs)
            except GameSessionLost:raise
            except RuntimeError as error:
                if str(error).startswith(('起点或目标不可用','地图上没有可走路径',
                                          '实际移动未到规划格子','短距离路线达到次数上限')):
                    raise WeaponShopExitBlocked(str(error)) from error
                raise
        self.close_panels()
        self.unique_npc('铁匠铺老板',(5,9))
        progress('沿武器店可走格子到门口')
        obj=self.uint(self.uint(self.base+0x2ba608));header=self.read(obj+4,52)
        occupied={tuple(n['map']) for n in self.weapon_exit_players()}
        if (5,16) in occupied:
            tilemap=self.navigation_map(header)
            if tilemap.free((4,16)) and (4,16) not in occupied:
                progress('门口被玩家占用，尝试旁边的出口格')
                walk((4,16),allow_transition=True)
                if self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)!=header:
                    self.stable_player();self.locate_mengzhong_veteran(progress)
                    return {'town_position':self.player(),'return_stone_used':False,'side_exit':True}
            raise WeaponShopExitBlocked('武器店门口被玩家占用，旁边未触发出口')
        walk((5,16))
        walk((4,16),allow_transition=True,run_enabled=False,max_steps=3)
        deadline=time.monotonic()+6
        while self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)==header:
            self.check()
            if time.monotonic()>=deadline:raise WeaponShopExitBlocked('走到出口后未切换地图')
            self.pause(.1)
        self.stable_player()
        self.locate_mengzhong_veteran(progress)
        return {'town_position':self.player(),'return_stone_used':False}

    def travel_cangyue(self,progress=lambda message:None):
        self.open_mengzhong_veteran(progress)
        progress('传送苍月岛（2000金币）')
        obj=self.uint(self.uint(self.base+0x2ba608));header=self.read(obj+4,52)
        self.menu_click('cangyue_transfer')
        self.wait(lambda:self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)!=header,timeout=8)
        self.stable_player()
        self.unique_npc('苍月老兵',(139,333))
        arrival=self.player()
        moves=self.cangyue_arrival_run_right(progress)
        return {'arrival':arrival,'after_runs':self.player(),'arrival_runs':moves}

    def cangyue_arrival_run_right(self,progress=lambda message:None):
        self.unique_npc('苍月老兵',(139,333))
        if self.held_item() or self.sale_item() or self.inflight_item():raise RuntimeError('物品操作未结束，未离开苍月落点')
        self.close_panels()
        header=self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)
        tilemap=self.navigation_map(header);actions=[]
        progress('苍月传送后向右跑两次，离开拥挤落点')
        for _ in range(2):
            current=tuple(self.stable_player());destination=(current[0]+2,current[1])
            occupied={tuple(n['map']) for n in self.npcs()+self.npcs(True)}
            if not all(tilemap.free((current[0]+i,current[1])) for i in (1,2)) or destination in occupied:
                break
            own=self.uint(self.uint(self.base+0x2bac2c))
            draw=struct.unpack('<2i',self.read(own+0x17c,8))
            self.background_mouse((draw[0]+144,draw[1]+64),'right',track_movement=False,
                                  dpi_scaled=True,button_hold=.15,restore_client_focus=True)
            after=tuple(self.stable_player())
            if self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)!=header:raise RuntimeError('离开苍月落点时地图变化，停止')
            actions.append({'from':current,'to':after,'expected':destination,'button':'right'})
            if getattr(self,'_stats_enabled',False):self.write_stats({'event':'cangyue_arrival_run',**actions[-1]})
            if after!=destination:break
        return actions

    def open_cangyue_fixed_sale(self, merchant, progress=lambda message: None):
        shops = {'服装店老板': ((147,328), 'cangyue_sell_clothes'),
                 '首饰店老板': ((155,339), 'cangyue_sell_jewelry')}
        if merchant not in shops: raise RuntimeError('未校准的苍月商人')
        self.check()
        if self.login_stage() != 'playing': raise RuntimeError('当前状态未确认正常，未打开出售')
        if self.held_item() or self.sale_item() or self.inflight_item():
            raise RuntimeError('手持、待售或传输物品未结束，未点击商人菜单')
        before = self.state()
        if before.get('map_identity', {}).get('name', '').lower() != '5.map':
            raise RuntimeError('请先到苍月；本测试不自动跨城传送')
        coordinate, menu = shops[merchant]
        self.close_panels()
        self.cangyue_sale_stand()
        self.open_npc(self.unique_npc(merchant, coordinate))
        if self.active_merchant != merchant or not self.visible('merchant'):
            raise RuntimeError('未确认新打开的对应商人窗口，未点击')
        entry = self.profile()['menus'][menu]
        bounds = self.bounds('merchant'); standing = tuple(self.player())
        point = (bounds[0]+entry['point'][0], bounds[1]+entry['point'][1])
        if self.hero_covers((point[0]-3,point[1]-3,point[0]+3,point[1]+3)):
            raise RuntimeError('英雄头像遮挡出售菜单，未点击')
        self.check()
        if not self.visible('merchant') or self.bounds('merchant') != bounds or tuple(self.player()) != standing:
            raise RuntimeError('商人窗口或站位变化，未点击')
        progress('内存确认'+merchant+'窗口，固定位置点击出售一次')
        self.click(point)
        self.wait(lambda:self.visible('sell') and self.visible('bag'), timeout=5)
        if self.state().get('map_identity', {}).get('name', '').lower() != '5.map':
            raise RuntimeError('打开出售时地图变化，停止')
        self.unique_npc(merchant, coordinate)
        report = {'merchant': merchant, 'menu': menu, 'point': point, 'menu_clicks': 1,
                  'sell_visible': True, 'bag_visible': True, 'image_matching': False,
                  'items_submitted': 0, 'entry_clicks': 0}
        if getattr(self,'_stats_enabled',False):self.write_stats({'event':'cangyue_fixed_sale_open',**report})
        return report

    def pending_sale_snapshot(self):
        self.check()
        if self.login_stage() != 'playing': raise RuntimeError('状态不明，未确认清包完成')
        if self.held_item() or self.sale_item() or self.inflight_item():
            raise RuntimeError('手持、待售或传输尚未结束，不能重置出售状态')
        if not self.hero_ready(): raise RuntimeError('英雄背包未就绪，不能确认清包完成')
        main, hero = self.inventory(), self.hero_inventory()
        if len(main) != 40 or len(hero) != 40: raise RuntimeError('双包槽位未完整读取')
        return {'main':sale_plan(main), 'hero':sale_plan(hero),
                'count':sum(name in CATEGORIES for name in main+hero)}

    def verify_sale_complete(self):
        first = self.pending_sale_snapshot()
        self.pause(.25)
        second = self.pending_sale_snapshot()
        if first['count'] or second['count']:
            raise SaleRouteIncomplete('流程显示结束但双包仍有白名单装备，需重新规划出售', second if second['count'] else first)
        return second

    def recover_incomplete_sale(self, progress, reason):
        before = self.state(); map_name = before.get('map_identity',{}).get('name','').lower()
        if map_name not in ('3.map','5.map','0159.map'):
            raise RuntimeError('不在已核对的城镇或武器店，禁止清包故障小退')
        self.pending_sale_snapshot()
        result = self.recover_stalled_route(progress, reason)
        after = self.state()
        if (after.get('map_identity',{}).get('name','').lower() != map_name
                or after.get('player') != before.get('player')):
            raise RuntimeError('小退后地图或位置与原现场不符，停止，不猜测接续状态')
        self.active_merchant = None
        return result

    def reconcile_before_reentry(self, progress):
        try:self.verify_sale_complete()
        except SaleRouteIncomplete as error:
            progress('入场前复核仍有待售装备，回到双包清包阶段，不点击入场')
            if getattr(self,'_stats_enabled',False):self.write_stats({'event':'sale_state_reset','phase':'before_reentry','pending':error.pending})
            self.dual_sale_route(progress)
            self.verify_sale_complete()

    def dual_sale_route(self,progress=lambda message:None,allow_recovery=True):
        if isinstance(self,ForegroundSession):self.focus_game()
        previous=getattr(self,'_selling_both_bags',False)
        previous_recovery=getattr(self,'_sale_recovery_enabled',False)
        self._selling_both_bags=True
        self._sale_recovery_enabled=allow_recovery
        self._requires_clean_bags_before_entry=True
        start=len(self.sales);recoveries=[];state_resets=0
        stats_before=self.currency_snapshot() if getattr(self,'_stats_enabled',False) else None
        stats_started=time.monotonic();stats_status='interrupted'
        round_id=__import__('uuid').uuid4().hex[:12]
        if stats_before is not None:self._stats_round_id=round_id
        try:
            for attempt in range(3):
                try:
                    self.check()
                    result=self._dual_sale_route(progress)
                    self.verify_sale_complete()
                    result['count']=len(self.sales)-start
                    result['recoveries']=recoveries
                    result['state_resets']=state_resets
                    result['foreground_used']=isinstance(self,ForegroundSession)
                    stats_status='complete'
                    return result
                except SaleRouteIncomplete as error:
                    if attempt == 2: raise
                    self.pending_sale_snapshot()
                    if attempt == 0:
                        state_resets+=1
                        self.close_panels(); self.active_merchant=None
                        progress('双包仍有白名单装备，重置到当前地图的出售规划；不重复已成交物品')
                        if getattr(self,'_stats_enabled',False):self.write_stats({'event':'sale_state_reset','phase':'sale_complete','pending':error.pending})
                    elif allow_recovery:
                        recoveries.append(self.recover_incomplete_sale(progress,str(error)))
                    else: raise
                except GameSessionLost:
                    if not allow_recovery:raise
                    if attempt==2:raise RuntimeError('本轮两次恢复后再次中断，停止出售')
                    self.reserve_hunt_recovery('出售中死亡或掉线')
                    progress('出售中断，恢复登录后重新读取双包；不重复提交上一件')
                    recoveries.append(self.recover_session(progress))
                except SaleConfirmationStalled as error:
                    if not allow_recovery or attempt==2:raise
                    recoveries.append(self.recover_stalled_route(progress,str(error),pending=error))
        finally:
            self._selling_both_bags=previous
            self._sale_recovery_enabled=previous_recovery
            if stats_before is not None:
                after=self.currency_snapshot();sold=self.sales[start:]
                income=sum(row.get('gold_change',0) or 0 for row in sold)
                net=(after['gold']-stats_before['gold']) if after['gold'] is not None and stats_before['gold'] is not None else None
                self.write_stats({'event':'sale_round','round_id':round_id,'status':stats_status,
                    'state_resets':state_resets,'recovery_count':len(recoveries),
                    'hunt_seconds':getattr(self,'_last_hunt_seconds',None),
                    'hunt_duration_basis':getattr(self,'_hunt_duration_basis','not_recorded'),
                    'sold_count':len(sold),'gold_before':stats_before['gold'],'gold_after':after['gold'],
                    'gold_net_change':net,'sale_income_gold':income,'other_gold_change':net-income if net is not None else None,
                    'yuanbao_before':stats_before['yuanbao'],'yuanbao_after':after['yuanbao'],
                    'yuanbao_change':after['yuanbao']-stats_before['yuanbao'] if None not in (after['yuanbao'],stats_before['yuanbao']) else None,
                    'sale_seconds':round(time.monotonic()-stats_started,1)})

    def _dual_sale_route(self,progress=lambda message:None):
        self.ensure_hero_available()
        self.prepare_hero_avatar()
        completed=[];transfers=[]
        for _ in range(3):
            main=self.inventory();hero=self.hero_inventory()
            pending=sum(name in CATEGORIES for name in main+hero)
            if not pending:
                return {'count':sum(r['count'] for r in completed),'results':completed,
                        'transfers':transfers,'remaining_plan':[],
                        'main_free':main.count(''),'hero_free':hero.count(''),
                        'return_stone_used':any(r.get('return_stone_used',False) for r in completed),
                        'exit_returns':sum(r.get('exit_returns',0) for r in completed),
                        'foreground_used':False}
            candidates=[i for i,name in enumerate(hero) if name in CATEGORIES]
            if candidates and '' in main:
                self.close_panels()
                # Opening the hero bag after relogin can reorder its slot array.
                # Never use indices collected before that first server refresh.
                transfers.extend(self.take_hero_sale_items(set(CATEGORIES),progress))
                self.close_panels()
            if not sale_plan(self.inventory()):raise RuntimeError('人物包没有空格容纳英雄待卖装备，已停止')
            result=self.mixed_sale_route(progress)
            completed.append(result)
            if not result['count']:raise SaleRouteIncomplete('本轮没有成交，需重新核对出售阶段')
            if sum(name in CATEGORIES for name in self.inventory()+self.hero_inventory())>=pending:
                raise SaleRouteIncomplete('待卖装备未减少，需重新核对出售阶段')
        raise SaleRouteIncomplete('双包清理超过三轮，重新核对剩余白名单装备')

    def mixed_sale_route(self,progress=lambda message:None,verify_only=False):
        plan=sale_plan(self.inventory())
        if not plan and not verify_only:return {'count':0,'status':'背包没有白名单装备，未移动或传送','remaining_plan':[]}
        completed=[];exits=[]
        actors=self.npcs()
        at_cangyue=any(n['name']=='苍月老兵' and tuple(n['map'])==(139,333) for n in actors)
        has_weapons=any(item in WEAPONS for item in self.inventory())
        if not has_weapons and any(n['name']=='铁匠铺老板' and tuple(n['map'])==(5,9) for n in actors):
            exits.append(self.leave_weapon_shop(progress))
        if at_cangyue and (has_weapons or verify_only):
            point=next(n['draw'] for n in actors if n['name']=='苍月老兵')
            width,height=self.client_size()
            if not(0<point[0]<width and 0<point[1]+24<height-240):
                self.close_panels();self.cangyue_sale_stand()
            self.close_panels();self.open_npc(self.unique_npc('苍月老兵',(139,333)))
            obj=self.uint(self.uint(self.base+0x2ba608));header=self.read(obj+4,52)
            progress('返回盟重验证武器路线（2000金币）')
            self.menu_click('mengzhong_transfer')
            self.wait(lambda:self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)!=header,timeout=8)
            self.stable_player();at_cangyue=False
        if has_weapons or verify_only:
            if has_weapons:completed.append(self.teleport_weapon_sale(progress=progress))
            else:
                self.visit_shop('weapon',progress)
                self.open_npc(self.unique_npc('铁匠铺老板',(5,9)))
                self.menu_click('sell_weapon')
                self.wait(lambda:self.visible('sell') and self.visible('bag'))
                self.close_panels()
            exits.append(self.leave_weapon_shop(progress))
        remaining=any(CATEGORIES.get(item) not in (None,'武器') for item in self.inventory())
        if remaining or verify_only:
            if not at_cangyue:self.travel_cangyue(progress)
            progress('沿苍月已校准路线到出售站位')
            self.close_panels()
            # The recorded 1680x1050 landing sees both shops without moving.
            self.cangyue_sale_stand()
            if remaining:completed.append(self.sell_cangyue_at_anchor(progress))
            else:
                for name,menu in [('服装店老板','cangyue_sell_clothes'),('首饰店老板','cangyue_sell_jewelry')]:
                    self.open_cangyue_fixed_sale(name,progress)
                    self.wait(lambda:self.visible('sell') and self.visible('bag'))
                    self.close_panels()
        return {'count':sum(r['count'] for r in completed),'results':completed,
                'remaining_plan':sale_plan(self.inventory()),'position':self.player(),
                'verification_only':verify_only,
                'return_stone_used':any(r.get('return_stone_used',False) for r in exits),
                'exit_returns':sum(bool(r.get('return_stone_used',False)) for r in exits),
                'shop_exits':exits,'foreground_used':False}

    def run_shop_route(self,categories=None,progress=lambda message:None):
        # Reload shared policy only at a new command boundary, never inside an active loop.
        import pickup_strategy
        importlib.reload(pickup_strategy)
        self._stalled_route_recoveries=0
        if hasattr(self,'reader'):self._stats_enabled=True
        if categories in (['双包混合路线'],['混合路线'],['苍月出售']):
            self._last_hunt_seconds=None;self._hunt_duration_basis='manual_sale_unknown'
        if categories==['重连当前客户端并开始']:
            self.close();self.__init__();self.active_merchant=None
            stage=self.login_stage()
            if stage=='character':return self.enter_saved_character()
            return {'stage':stage}
        if categories==['苍月木剑补货定位']:
            self.click((298,188));self.pause(.2);self.close_panels()
            self.walk_tile((134,318))
            actors=self.npcs()
            return {'position':self.player(),'shops':[n for n in actors if '武器' in n['name'] or '铁匠' in n['name']]}
        if categories==['准备女布衣采购']:
            self.close_panels()
            self.open_npc(self.unique_npc('服装店老板',(147,328)))
            self.click((27,64));self.wait(lambda:self.visible('bag'))
            self.click((73,227));self.click((235,356));self.pause(.5)
            return {'ready':True}
        if categories==['准备布衣采购']:
            self.click((298,188));self.pause(.2);self.close_panels()
            self.leave_weapon_shop(progress);self.travel_cangyue(progress)
            self.open_npc(self.unique_npc('服装店老板',(147,328)))
            self.click((27,64));self.wait(lambda:self.visible('bag'))
            self.click((73,214));self.click((235,356));self.pause(.5)
            return {'ready':True}
        if categories in (['购买布衣填满人物包'],['购买女布衣填满人物包']):
            expected_name='布衣(女)' if categories==['购买女布衣填满人物包'] else '布衣(男)'
            bought=[]
            for _ in range(40):
                before=self.inventory()
                if '' not in before:break
                self.click((73,214));self.pause(.5);self.click((235,356));self.pause(.6)
                expected=before.copy();slot=expected.index('');expected[slot]=expected_name
                try:self.wait(lambda:self.inventory()==expected,timeout=3)
                except RuntimeError:
                    if self.inventory()==before:return {'count':len(bought),'next_page_required':True,'main_full':False}
                    raise
                bought.append(slot+1)
            return {'count':len(bought),'main_full':'' not in self.inventory()}
        if categories==['购买木剑填满人物包']:
            if not self.visible('bag') or not self.visible('merchant'):raise RuntimeError('木剑购买列表未打开')
            bought=[]
            for _ in range(40):
                before=self.inventory()
                if '' not in before:break
                self.click((73,214));self.pause(.5)
                self.click((235,356));self.pause(.6)
                expected=before.copy();slot=expected.index('');expected[slot]='木剑'
                self.wait(lambda:self.inventory()==expected,timeout=4)
                bought.append(slot+1)
            return {'bought_slots':bought,'count':len(bought),'main_full':'' not in self.inventory()}
        if categories==['满包木剑转英雄']:
            from inventory_flow import bag_decision
            if bag_decision(self.inventory(),self.hero_inventory(),self.hero_ready())!='transfer':raise RuntimeError('尚未满足人物包满、英雄包有空格')
            self.click((298,188));self.pause(.3);self.click((406,12));self.pause(.3)
            result=[]
            while '' in self.hero_inventory() and any(name in ('木剑','布衣(男)') for name in self.inventory()):
                index=next(i for i,name in enumerate(self.inventory()) if name in ('木剑','布衣(男)'))
                result.append(self.transfer_bag_item('main',index))
            return {'transfers':result,'decision':bag_decision(self.inventory(),self.hero_inventory(),self.hero_ready()),'bags':self.dual_bag_status()}
        if categories==['测试分配双包装备']:
            self.click((298,188));self.pause(.3)
            self.click((406,12));self.pause(.3)
            if not self.visible('bag'):raise RuntimeError('人物背包未打开')
            transferred=[]
            for name in ('木剑','木剑','布衣(男)','布衣(男)'):
                index=self.inventory().index(name)
                transferred.append(self.transfer_bag_item('main',index))
            return {'transfers':transferred}
        if categories==['测试双包完整出售']:
            names=('布衣(男)','布衣(女)');old={name:CATEGORIES.get(name) for name in names}
            for name in names:CATEGORIES[name]='衣服'
            try:return self.dual_sale_route(progress)
            finally:
                for name in names:
                    if old[name] is None:CATEGORIES.pop(name,None)
                    else:CATEGORIES[name]=old[name]
        if categories==['双包混合路线']:return self.dual_sale_route(progress)
        if categories==['重新绑定当前客户端（只读）']:
            changed=self.reconnect_running_client()
            return {'reconnected':changed,'stage':self.login_stage(),'client_size':self.client_size()}
        if categories==['窗口输入坐标诊断']:
            self.u.GetWindowLongW.argtypes=[w.HWND,ctypes.c_int]
            self.u.GetWindowLongW.restype=w.LONG
            return {'client':self.client_size(),'physical':self.physical_client_size(),
                    'minimized':bool(self.u.IsIconic(self.hwnd)),
                    'style':hex(self.u.GetWindowLongW(self.hwnd,-16)&0xffffffff),
                    'hero_ready':self.hero_ready(),'flag':self.read(self.uint(self.base+0x2baccc),1).hex()}
        if categories==['土城完整流程测试（不入场）']:return self.town_sale_entry_test(progress)
        if categories==['续跑城内完整流程测试（不入场）']:return self.town_sale_entry_test(progress,resume_known_shop=True)
        if categories==['仅回盟重城']:return self.return_with_hotkey(progress,reason='manual_test')
        if categories==['提前回城清包一轮']:
            returned=self.return_with_hotkey(progress,reason='manual_test')
            sale=self.dual_sale_route(progress)
            result={'return':returned,'sale':sale,'bags':self.dual_bag_status(),'early_return_test':True}
            finished=self.finish_hunt_before_reentry(progress,1)
            if finished is not None:result.update(finished)
            return result
        if categories==['登录后后台打开背包测试']:
            login=self.recover_session(progress)
            import bag_input_test
            importlib.reload(bag_input_test)
            before=bag_input_test.snapshot(self)
            progress('登录完成；重新读取背包对象，开始后台打开验证')
            self.open_main_bag()
            after=bag_input_test.snapshot(self)
            return {'login':login,'bag_before':before,'bag_after':after,
                    'bag_visible':after['visible'],'items_untouched':True}
        if categories==['背包仅后台点击测试']:
            import bag_input_test
            importlib.reload(bag_input_test)
            return bag_input_test.run(self,progress,background_only=True)
        if categories==['背包窗口坐标测试']:
            import bag_input_test
            importlib.reload(bag_input_test)
            previous=getattr(self,'_ui_logical_messages',False)
            self._ui_logical_messages=True
            try:return bag_input_test.run(self,progress,background_only=True)
            finally:self._ui_logical_messages=previous
        if categories==['背包多方式点击测试']:
            import bag_input_test
            importlib.reload(bag_input_test)
            return bag_input_test.run(self,progress)
        if categories==['验证人物背包打开']:
            self.open_main_bag()
            return {'bag_visible':self.visible('bag'),'items_untouched':True}
        if categories==['处理人物满包']:return self.handle_full_bags()
        if categories==['监测双包']:return self.monitor_bags(progress)
        if categories==['监测并回城出售']:return self.monitor_bags(progress,auto_return=True)
        if categories==['老兵路线只读']:
            from map_navigation import veteran_run_path
            obj=self.uint(self.uint(self.base+0x2ba608));tilemap=self.navigation_map(self.read(obj+4,52))
            current=tuple(self.player());own=self.uint(self.uint(self.base+0x2bac2c))
            actors=self.npcs();occupied={tuple(n['map']) for n in actors if n['address']!=own}
            goals=[(x,y) for x in range(312,329) for y in range(312,329) if tilemap.free((x,y)) and (x,y) not in occupied]
            npc_tiles={tuple(n['map']) for n in self.npcs()}
            try:path=veteran_run_path(tilemap,current,goals,npc_tiles)
            except RuntimeError as error:path=str(error)
            return {'position':current,'own':own,'actors':actors,'map':tilemap.name,'path':path,
                    'bags':self.dual_bag_status(),'game_input_sent':False}
        if categories==['NPC靠近方案只读']:
            from map_navigation import npc_approach_step
            npc=self.unique_npc('铁匠铺老板',(5,9))
            obj=self.uint(self.uint(self.base+0x2ba608));tilemap=self.navigation_map(self.read(obj+4,52))
            current=self.player();blocked={tuple(row['map']) for row in self.npcs()+self.npcs(True)}
            return {'npc':npc,'verified_draw':self.verified_npc_draw(npc),'position':current,
                    'map':tilemap.name,'next_tile':npc_approach_step(tilemap,current,npc['map'],blocked),'game_input_sent':False}
        if categories==['重载只读战斗统计']:
            # Only replace the existing sampling thread; no game input.
            result=self.start_live_monitor(restart=True)
            from combat_metrics import read_experience
            return {**result,'experience_sample':read_experience(self),'game_input_sent':False}
        if categories==['出售状态只读核验']:
            # Deliberately bypass check()'s optional UI recovery and issue no input.
            return {'layout':self.sale_handler_layout(),'main':self.sale_bag_identities(),
                    'held':self.sale_item_identity('held'),'sale':self.sale_item_identity('sale'),
                    'inflight':self.inflight_item(),'stage':self.login_stage(),
                    'recovery_used':self.saved_hunt_recovery_used()}
        if categories==['检查双包监测']:return self.monitor_bags(progress,seconds=2)
        if categories==['购买测试木剑8把']:
            if self.client_size()!=(1680,1050) or not self.visible('merchant') or not self.visible('bag'):raise RuntimeError('购买列表未准备好')
            bought=[]
            for _ in range(8):
                before=self.inventory()
                if '' not in before:break
                self.click((73,214));self.pause(.5)
                self.click((235,356));self.pause(.6)
                expected=before.copy();slot=expected.index('');expected[slot]='木剑'
                self.wait(lambda:self.inventory()==expected,timeout=4)
                bought.append(slot+1)
            return {'bought_slots':bought,'count':len(bought)}
        if categories==['头像移到左下']:
            self.close_panels()
            hero=self.control_info(0x7b0,'Window_HeroStatus')
            if not hero['visible']:raise RuntimeError('英雄头像未显示')
            x,y,width,height=hero['bounds'];start=(x+width//2,y+10);end=(88,self.client_size()[1]-300)
            if isinstance(self,ForegroundSession):
                self.drag_ui(start,end)
                after=self.control_info(0x7b0,'Window_HeroStatus')
                if after['bounds'][:2]==hero['bounds'][:2]:raise RuntimeError('头像未移动，未继续点击菜单')
                return {'before':hero,'after':after}
            self.drag_ui(start,end)
            after=self.control_info(0x7b0,'Window_HeroStatus')
            if after['bounds'][:2]==hero['bounds'][:2]:raise RuntimeError('头像未移动，未继续点击菜单')
            return {'before':hero,'after':after}
        if categories==['准备木剑采购']:
            self.close_panels()
            actors=self.npcs()
            if any(n['name']=='苍月老兵' for n in actors):
                self.open_npc(self.unique_npc('苍月老兵',(139,333)))
                obj=self.uint(self.uint(self.base+0x2ba608));header=self.read(obj+4,52)
                self.menu_click('mengzhong_transfer')
                self.wait(lambda:self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)!=header,timeout=8)
                self.stable_player()
            self.visit_shop('weapon',progress)
            self.open_npc(self.unique_npc('铁匠铺老板',(5,9)))
            self.click((27,49));self.pause(.5)
            if not self.visible('bag') and self.visible('merchant'):self.click((27,49))
            self.wait(lambda:self.visible('bag'))
            return {'ready':True,'position':self.player()}
        if categories==['测试布衣取回']:
            main=self.inventory();hero=self.hero_inventory()
            index=hero.index('布衣(男)')
            root=self.control_info(0x7b4,'Window_HeroItemBag')
            grid=self.control_info(0x7bc,'Grid_HeroItemBag')
            cols,rows,pitchx,pitchy=struct.unpack('<4i',self.read(grid['object']+0x398,16))
            scroll=self.uint(self.uint(self.parent+0x1090)+0x3e4)
            if not root['visible'] or scroll or cols*rows!=40:raise RuntimeError('英雄背包网格未就绪')
            point=(root['bounds'][0]+grid['bounds'][0]+(index%cols+.5)*pitchx,
                   root['bounds'][1]+grid['bounds'][1]+(index//cols+.5)*pitchy)
            self.ui_right_click(point)
            expected=hero.copy();expected[index]=''
            self.wait(lambda:self.hero_inventory()==expected and self.inventory().count('布衣(男)')==main.count('布衣(男)')+1)
            after=self.inventory();changed=[i for i in range(40) if main[i]!=after[i]]
            if len(changed)!=1 or main[changed[0]] or after[changed[0]]!='布衣(男)':raise RuntimeError('取回影响了其他格子')
            return {'hero_slot':index+1,'main_slot':changed[0]+1,'verified':True}
        if categories==['测试布衣转英雄']:
            if not self.visible('bag') or self.visible('sell'):raise RuntimeError('人物背包未准备好')
            before=self.inventory();hero=self.hero_inventory()
            if '布衣(男)' not in before or '' not in hero:raise RuntimeError('缺少测试物品或英雄空格')
            index=before.index('布衣(男)')
            self.ui_right_click(grid_center(self.bounds('bag'),self.bounds('grid'),index))
            expected=before.copy();expected[index]=''
            self.wait(lambda:self.inventory()==expected and self.hero_inventory().count('布衣(男)')==hero.count('布衣(男)')+1)
            after=self.hero_inventory()
            changed=[i for i in range(40) if hero[i]!=after[i]]
            if len(changed)!=1 or hero[changed[0]] or after[changed[0]]!='布衣(男)':raise RuntimeError('转包影响了其他物品')
            return {'source_slot':index+1,'hero_slot':changed[0]+1,'verified':True}
        if categories==['购买测试布衣6件']:
            if self.client_size()!=(1680,1050):raise RuntimeError('测试界面尺寸不符')
            if not self.visible('merchant') or not self.visible('bag'):raise RuntimeError('购买列表未打开')
            bought=[]
            for _ in range(6):
                before=self.inventory()
                if '' not in before:break
                self.click((73,214));self.click((235,356))
                expected=before.copy();slot=expected.index('');expected[slot]='布衣(男)'
                self.wait(lambda:self.inventory()==expected)
                bought.append(slot+1)
            return {'bought_slots':bought,'count':len(bought)}
        if categories==['读取背包控件']:
            found=[]
            for offset in range(0x480,0x1200,4):
                try:
                    obj=self.uint(self.parent+offset)
                    name=self.read(self.uint(obj+8),96).split(b'\0')[0].decode('ascii')
                    if not any(word in name.lower() for word in ('hero','buy','merchant','itembag','mybag','stategroup','regetbag')):continue
                    row=dict(self.control_info(offset,name),offset=hex(offset),name=name)
                    if name=='HotKey_HeroBagDefault':row['hotkey_raw']=self.read(obj+0x350,128).hex()
                    row['parent_chain']=[]
                    ancestor=obj
                    for _ in range(5):
                        ancestor=self.uint(ancestor+0x348)
                        if ancestor<0x10000:break
                        try:
                            aname=self.read(self.uint(ancestor+8),96).split(b'\0')[0].decode('ascii')
                            row['parent_chain'].append({'object':ancestor,'name':aname,'bounds':struct.unpack('<4i',self.read(ancestor+0x40,16)),'visible':self.read(ancestor+0x34c,1)==b'\1'})
                        except (RuntimeError,UnicodeError):break
                    if 'Grid' in name or offset==0x1090:
                        row['fields_390']=self.read(obj+0x390,96).hex()
                    found.append(row)
                except (RuntimeError,UnicodeError):continue
            return {'controls':found}
        if categories==['读取双背包']:
            rows=self.hero_inventory()
            capacity=len(rows)
            pointer=self.uint(self.base+0x2ba544)
            controls={}
            for key,offset,name in [('hero_bag',0x7b4,'Window_HeroItemBag'),('hero_grid',0x7bc,'Grid_HeroItemBag')]:
                controls[key]=self.control_info(offset,name)
            return {'main_items':self.inventory(),'hero_items':rows,'hero_capacity':capacity,'hero_pointer':pointer,'controls':controls,'item_totals':dict(self.bag_item_totals()),'held':self.held_item(),'sale_item':self.sale_item(),'inflight':self.inflight_item()}
        if categories==['核对待确认物品身份']:
            pending=self.read(self.uint(self.base+0x2ba2b0)+4,156)
            uid=pending[0x90:0x98].hex();matches=[]
            for bag,address in [('main',self.base+0x2e1674),('hero',self.uint(self.base+0x2ba544))]:
                records=self.read(address,40*156)
                for index in range(40):
                    row=records[index*156:(index+1)*156]
                    if row[0] and row[0x90:0x98]==pending[0x90:0x98]:
                        matches.append({'bag':bag,'slot':index+1,'same_record':row==pending,'name':row[1:1+row[0]].decode('gb18030')})
            return {'pending_name':self.inflight_item(),'uid':uid,'matches':matches,'held':self.held_item(),'sale_item':self.sale_item()}
        if categories==['刷新待确认背包']:
            return self.refresh_pending_sale(self.inflight_item(),progress)
        if categories==['恢复英雄并读取双包']:
            self.ensure_hero_available();return self.dual_bag_status()
        if categories==['测试小退界面']:
            raise RuntimeError('已按用户要求禁用主动小退测试')
        if categories==['confirm_enter']:
            if not self.recovery_message_matches('welcome'):raise RuntimeError('当前不是已记录的二次确认页，未发送回车')
            self.press_login_confirm()
            return {'stage':self.login_stage(),'input':'Enter'}
        if categories==['resume_login']:
            self.u.PostMessageW(self.hwnd,0x1c,1,0)
            self.pause(2)
            return {'stage':self.login_stage()}
        if categories==['confirm_welcome']:
            root=self.control_info(0x3d8,'Window_MsgDlg')
            button=self.control_info(0x3dc,'Button_MsgDlgOk')
            if not root['visible'] or tuple(root['bounds'][2:])!=(256,359):raise RuntimeError('Welcome dialog absent')
            self.u.PostMessageW(self.hwnd,0x1c,1,0)
            self.pause(.15)
            self.click(button_center(root['bounds'],button['bounds']))
            return {'stage':self.login_stage(),'point':button_center(root['bounds'],button['bounds'])}
        if categories==['登录界面诊断']:
            rows=[]
            for offset in range(0x390,0x440,4):
                try:
                    obj=self.uint(self.parent+offset)
                    name=self.read(self.uint(obj+8),80).split(b'\0')[0].decode('ascii')
                    rows.append(dict(self.control_info(offset,name),name=name,offset=hex(offset)))
                except (RuntimeError,UnicodeError):pass
            return {'stage':self.login_stage(),'controls':rows}
        if categories==['死亡重登']:return self.recover_session(progress)
        if categories==['恢复新授权账号']:
            self._expected_character=None
            result=self.recover_session(progress)
            from credential_store import bind_character
            bind_character(self._expected_character)
            return result
        if categories==['保存当前授权角色绑定']:
            from credential_store import bind_character
            bind_character(self._expected_character)
            return {'bound':True}
        if categories==['验证武器店直接回城']:
            self.visit_shop('weapon',progress)
            return self.leave_weapon_shop(progress)
        if categories==['当前角色小退重登（不输入账号）']:
            return self.recover_stalled_route(progress,'用户要求当前角色小退重登')
        if categories==['账号登录']:return self.submit_saved_login()
        if categories==['选择原服务器']:return self.select_login_server()
        if categories==['进入原角色']:return self.enter_saved_character()
        if categories==['死亡恢复只读']:
            actor=self.uint(self.uint(self.base+0x2bac2c))
            controls={}
            for key,offset,name in [('exit_group',0xfb0,'UI_Window_ExitGroup'),('logout',0x618,'Button_BotLogOut'),('select',0x41c,'Window_SelectChr'),('start',0x420,'Button_scStart')]:
                controls[key]=self.control_info(offset,name)
            return {'actor':actor,'dead_byte':self.read(actor+0xac,1).hex(),'controls':controls}
        if categories==['打开人物背包']:
            self.open_main_bag();return {'visible':self.visible('bag'),'position':self.player()}
        if categories==['恢复已校准客户区']:
            before=self.client_size()
            if before!=(1680,1027):raise RuntimeError('窗口尺寸不属于已确认的标题栏高度差，未调整')
            if self.u.IsIconic(self.hwnd) or self.u.IsZoomed(self.hwnd):raise RuntimeError('不自动恢复最小化或最大化窗口')
            rect=w.RECT()
            if not self.u.GetWindowRect(self.hwnd,ctypes.byref(rect)):raise RuntimeError('无法读取窗口边界')
            if not self.u.SetWindowPos(self.hwnd,0,0,0,rect.right-rect.left,rect.bottom-rect.top+23,0x16):
                raise RuntimeError('调整客户区失败，未发送游戏输入')
            self.pause(.5)
            if self.client_size()!=(1680,1050):raise RuntimeError('客户区调整未确认，停止')
            return {'before':before,'after':self.client_size(),'activated':False}
        if categories==['检查后台输入残留']:
            samples=[]
            for _ in range(240):
                state=self.input_state();state['xy']=self.player();state['time']=round(time.monotonic(),3)
                samples.append(state);time.sleep(.1)
            return {'samples':samples,'automatic_inputs_sent':0}
        if categories==['只读静止检查']:
            samples=[]
            for _ in range(16):
                samples.append({'xy':self.player(),'input':self.input_state()})
                time.sleep(.25)
            return {'samples':samples,'automatic_inputs_sent':0}
        if categories==['清除后台鼠标状态']:
            self.clear_background_mouse();return {'cleared':True}
        if categories==['开始录制路线']:
            import route_recording
            if getattr(self,'_route_recording',False):raise RuntimeError('路线已在录制中')
            importlib.reload(route_recording)
            return route_recording.start_recording(self)
        if categories==['停止录制路线']:
            from route_recording import stop_recording
            return stop_recording(self)
        if categories==['混合路线']:return self.dual_sale_route(progress)
        if categories==['验证混合路线']:return self.mixed_sale_route(progress,verify_only=True)
        if categories==['苍月出售站位']:return self.cangyue_sale_stand()
        if categories==['苍月出售']:return self.sell_cangyue_at_anchor(progress)
        if categories==['窗口回屏幕后置']:
            self.check()
            rect=w.RECT()
            if not self.u.SystemParametersInfoW(0x30,0,ctypes.byref(rect),0):raise RuntimeError('无法读取桌面工作区')
            foreground=self.u.GetForegroundWindow()
            self.u.SetWindowPos.argtypes=[w.HWND,w.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.UINT]
            if not self.u.SetWindowPos(self.hwnd,1,rect.left+10,rect.top+10,0,0,0x11):raise RuntimeError('游戏窗口后置失败')
            self.pause(.6)
            return {'foreground_unchanged':self.u.GetForegroundWindow()==foreground,'position':[rect.left+10,rect.top+10]}
        if categories==['门口两格跑动验证']:
            self.close_panels();self.unique_npc('铁匠铺老板',(5,9))
            current=tuple(self.stable_player())
            if current!=(5,15):raise RuntimeError('不在已检查的门边站位')
            obj=self.uint(self.uint(self.base+0x2ba608));header=self.read(obj+4,52)
            tilemap=self.navigation_map(header)
            if not tilemap.free((5,17)):raise RuntimeError('跑动落点不是可走格')
            actor=self.uint(self.uint(self.base+0x2bac2c));draw=struct.unpack('<2i',self.read(actor+0x17c,8))
            self.background_mouse((draw[0],draw[1]+160),'right')
            self.stable_player()
            if self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)!=header:return {'exited':True,'position':self.player()}
            if tuple(self.player())!=(5,17):raise RuntimeError('跑动未到两格落点，停止：'+str(self.player()))
            actor=self.uint(self.uint(self.base+0x2bac2c));draw=struct.unpack('<2i',self.read(actor+0x17c,8))
            self.background_mouse((draw[0]-48,draw[1]+64),'left')
            self.wait(lambda:self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)!=header,timeout=6)
            self.stable_player();self.unique_npc('盟重老兵',(320,320))
            return {'exited':True,'position':self.player(),'return_stone_used':False}
        if categories==['门边绕行出武器店']:
            self.close_panels();self.unique_npc('铁匠铺老板',(5,9))
            obj=self.uint(self.uint(self.base+0x2ba608));header=self.read(obj+4,52)
            tilemap=self.navigation_map(header);steps=[]
            for target in ((4,16),(3,16),(4,17)):
                current=tuple(self.stable_player())
                if max(abs(current[0]-target[0]),abs(current[1]-target[1]))>1 or not tilemap.free(target):continue
                actor=self.uint(self.uint(self.base+0x2bac2c));draw=struct.unpack('<2i',self.read(actor+0x17c,8))
                self.background_mouse((draw[0]+(target[0]-current[0])*48,draw[1]+64+(target[1]-current[1])*32),'left')
                self.pause(.8)
                steps.append({'from':current,'aim':target,'after':self.player()})
                if self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)!=header:
                    self.stable_player();self.unique_npc('盟重老兵',(320,320))
                    return {'exited':True,'position':self.player(),'steps':steps,'return_stone_used':False}
            raise RuntimeError('门边绕行未切换地图，已停止，未使用回城石：'+str(steps))
        if categories==['读取附近角色']:return {'characters':self.npcs(True)}
        if categories==['NPC列表性能核对']:
            started=time.perf_counter();legacy=self.heap_npcs()
            heap_ms=round((time.perf_counter()-started)*1000,2)
            started=time.perf_counter();live=self.scene_npcs()
            return {'heap_ms':heap_ms,'scene_ms':round((time.perf_counter()-started)*1000,2),
                    'heap':legacy,'scene':live,'position':self.player()}
        if categories==['验证苍月出售菜单']:
            layouts=[]
            for name,xy,menu in [('服装店老板',(147,328),'cangyue_sell_clothes'),
                                 ('首饰店老板',(155,339),'cangyue_sell_jewelry')]:
                self.close_panels();self.open_npc(self.unique_npc(name,xy));self.menu_click(menu)
                self.wait(lambda:self.visible('sell') and self.visible('bag'))
                layouts.append({'merchant':name,'bag':self.bounds('bag'),'sell':self.bounds('sell'),
                                'overlap':self.sale_layout_overlaps()})
                self.close_panels()
            return {'layouts':layouts,'position':self.player(),'items_submitted':0}
        if categories==['exit_probe']:
            obj=self.uint(self.uint(self.base+0x2ba608));tilemap=self.navigation_map(self.read(obj+4,52))
            return {'map':tilemap.name,'position':self.player(),'rows':[[tilemap.free((x,y)) for x in range(2,11)] for y in range(12,20)],'actors':self.npcs(True)}
        if categories==['automation_probe']:
            rows=[]
            for offset in range(0x350,0x1200,4):
                try:
                    obj=self.uint(self.parent+offset);name=self.read(self.uint(obj+8),96).split(b'\0')[0].decode('ascii')
                    if any(word in name.lower() for word in ('belt','bottom','auto','hang','hook')):
                        rows.append(dict(self.control_info(offset,name),name=name,offset=hex(offset)))
                except (RuntimeError,UnicodeError):pass
            return {'controls':rows,'belt_render':self.read(self.base+0x19ab90,768).hex(),
                    'belt_click':self.read(self.base+0x19a540,512).hex(),
                    'merchant':self.bounds('merchant'),'merchant_visible':self.visible('merchant')}
        if categories==['读取快捷栏']:return {'slots':self.shortcut_inventory()}
        if categories==['读取金币元宝']:return self.currency_snapshot()
        if categories==['输入状态只读']:
            return {'keys':{str(v):int(self.u.GetAsyncKeyState(v)) for v in (1,2,16,17,18,112)},'foreground':int(self.u.GetForegroundWindow() or 0),'game':int(self.hwnd),'logical':self.client_size(),'physical':self.physical_client_size(),'login_stage':self.login_stage(),'merchant':self.visible('merchant')}
        if categories==['断线提示只读诊断']:
            return {'stage':self.login_stage(),'message':self.control_info(0x3d8,'Window_MsgDlg'),'confirm':self.control_info(0x3dc,'Button_MsgDlgOk')}
        if categories==['核对孤岛入口（不入场）']:
            import island_automation
            importlib.reload(island_automation)
            npc=island_automation.locate_town_entrance(self,progress)
            self.open_npc(npc)
            return {'npc':npc,'menu_open':self.visible('merchant'),'entered':False,'entry_clicks':0,'position':self.player()}
        if categories==['孤岛战士单击验证']:
            import island_automation,island_melee
            importlib.reload(island_automation);importlib.reload(island_melee)
            sample=island_automation.observe(self)
            targets=[m for m in sample.get('monsters',[]) if m.get('class') in island_melee.CLASSES and m.get('on_screen') and m.get('distance',99)<=8]
            if not targets:return {'clicked':False,'status':'no_clickable_target','sample':sample}
            return island_melee.click_target(self,min(targets,key=lambda m:m['distance']))
        if categories in (['孤岛每日自动挑战'],['接续孤岛自动挑战'],['孤岛自动状态只读']):
            import island_challenge
            importlib.reload(island_challenge)
            import island_automation
            importlib.reload(island_automation)
            if categories==['孤岛自动状态只读']:return island_automation.status(self)
            return island_automation.run(self,progress,resume=categories==['接续孤岛自动挑战'],
                                         manual_request=categories==['孤岛每日自动挑战'])
        if categories==['孤岛雷电术单次']:
            import island_challenge
            __import__('importlib').reload(island_challenge)
            return island_challenge.cast_lightning(self)
        if categories in (['孤岛连续挑战'],['孤岛连续挑战（玩家雷电）']):
            import island_challenge
            __import__('importlib').reload(island_challenge)
            return island_challenge.run_island(self,seconds=480,player_spells=categories==['孤岛连续挑战（玩家雷电）'])
        if categories==['孤岛下一关']:
            import island_challenge
            __import__('importlib').reload(island_challenge)
            return island_challenge.next_level(self)
        if categories==['孤岛打开角落NPC']:
            import island_challenge
            __import__('importlib').reload(island_challenge)
            return island_challenge.open_corner(self)
        if categories==['孤岛全图拾取']:
            import island_challenge
            __import__('importlib').reload(island_challenge)
            return island_challenge.loot_island(self)
        if categories==['孤岛靠近雕像']:
            import island_challenge
            __import__('importlib').reload(island_challenge)
            return island_challenge.approach_sculpture(self)
        if categories==['孤岛现场只读']:
            import island_challenge
            __import__('importlib').reload(island_challenge)
            return island_challenge.inspect_inside(self)
        if categories==['孤岛每日进入一次']:
            import island_challenge
            __import__('importlib').reload(island_challenge)
            return island_challenge.enter_once(self)
        if categories==['打开孤岛挑战']:
            import island_challenge
            __import__('importlib').reload(island_challenge)
            return island_challenge.open_npc(self)
        if categories==['木剑自动拾取120秒']:
            import ground_item_probe
            __import__('importlib').reload(ground_item_probe)
            return ground_item_probe.pickup_loop(self,seconds=120)
        if categories==['当前木剑拾取测试']:
            import ground_item_probe
            __import__('importlib').reload(ground_item_probe)
            return ground_item_probe.pickup_current_test(self)
        if categories==['单把木剑拾取测试']:
            import ground_item_probe
            __import__('importlib').reload(ground_item_probe)
            return ground_item_probe.pickup_one_test(self)
        if categories==['两把木剑拾取测试']:
            import ground_item_probe
            __import__('importlib').reload(ground_item_probe)
            return ground_item_probe.pickup_test(self)
        if categories==['当前地图避人只读']:
            return {'scope':'client_loaded','players':self.nearby_players(None),
                    'random_stones':[{k:v for k,v in row.items() if k in ('key','name','raw_98')} for row in self.shortcut_inventory() if row['name']=='随机传送石'],
                    'game_input_sent':False}
        if categories==['当前地图巡逻路网只读']:
            import current_map_hunt
            importlib.reload(current_map_hunt)
            return current_map_hunt.inspect(self)
        if categories in (['法师地牢持续清怪拾取'],['法师当前地图持续挂机'],['当前地图持续挂机'],['战士当前地图持续挂机']):
            import current_map_hunt
            importlib.reload(current_map_hunt)
            return current_map_hunt.run(self,progress)
        if categories==['法师地牢沿图挂机测试']:
            import mage_skills,mage_dungeon
            __import__('importlib').reload(mage_skills)
            __import__('importlib').reload(mage_dungeon)
            return mage_dungeon.run_bounded(self,progress,seconds=120,max_casts=60)
        if categories==['法师地牢短时打怪拾取验证']:
            import mage_skills,mage_dungeon
            __import__('importlib').reload(mage_skills)
            __import__('importlib').reload(mage_dungeon)
            return mage_dungeon.run_bounded(self,progress)
        if categories==['法师地牢有限靠近']:
            import mage_skills,mage_dungeon
            __import__('importlib').reload(mage_skills)
            __import__('importlib').reload(mage_dungeon)
            return mage_dungeon.approach_once(self,progress)
        if categories==['法师地牢单次雷电验证']:
            import mage_skills
            __import__('importlib').reload(mage_skills)
            import mage_dungeon
            __import__('importlib').reload(mage_dungeon)
            return mage_dungeon.probe_once(self,progress)
        if categories==['法师技能只读研究']:
            import mage_skills
            __import__('importlib').reload(mage_skills)
            return mage_skills.inspect_target_context(self)
        if categories==['地面物品只读分析']:
            import ground_item_probe
            __import__('importlib').reload(ground_item_probe)
            return ground_item_probe.inspect(self)
        if categories==['经验字段只读采样']:
            import experience_probe
            __import__('importlib').reload(experience_probe)
            return experience_probe.sample(self,seconds=20)
        if categories==['bag_identities']:return self.bag_identity_records()
        if categories==['currency_probe']:
            actor=self.uint(self.uint(self.base+0x2bac2c))
            return {'fields':{hex(i):self.uint(actor+i) for i in range(0x120,0x174,4)},'hover':self.read(self.base+0x19f41c,512).hex(),'gold':self.read(self.base+0x19f8fc,256).hex()}
        if categories==['actor_classes']:
            begin=self.base+0x248000;data=self.read(begin,0x4000);rows=[]
            for pos in range(0,len(data)-4,4):
                pointer=struct.unpack_from('<I',data,pos)[0]
                if begin<=pointer<begin+len(data)-80:
                    off=pointer-begin;length=data[off]
                    if 3<=length<=60:
                        text=data[off+1:off+1+length]
                        if text.startswith(b'T') and all(32<=c<127 for c in text) and b'Actor' in text:
                            rows.append({'class':text.decode('ascii'),'vmt':begin+pos+44})
            return {'classes':rows}
        if categories==['scene_probe']:
            def classname(obj):
                vmt=self.uint(obj);ptr=self.uint(vmt-44);length=self.read(ptr,1)[0]
                if not 1<=length<=80:raise RuntimeError('invalid class')
                return self.read(ptr+1,length).decode('ascii')
            roots=[]
            for offset in (0x2ba8fc,0x2ba6d8,0x2ba15c,0x2bac2c):
                pointer=self.uint(self.base+offset)
                for depth in range(2):
                    try:
                        name=classname(pointer);entry={'global':hex(offset),'depth':depth,'object':pointer,'class':name,'lists':[]}
                        size=self.uint(self.uint(pointer)-40)
                        if not 4<=size<=0x10000:raise RuntimeError('invalid instance size')
                        entry['instance_size']=size;raw=self.read(pointer,min(size,0x2000))
                        for p in range(4,len(raw),4):
                            candidate=struct.unpack_from('<I',raw,p)[0]
                            if candidate<0x10000:continue
                            try:
                                cname=classname(candidate)
                                if cname in ('TList','TObjectList'):
                                    header=self.read(candidate,16);_,items,count,capacity=struct.unpack('<4I',header)
                                    examples=[]
                                    if 0<count<=capacity<=10000:
                                        for i in range(min(count,8)):
                                            try:
                                                item=self.uint(items+i*4);examples.append({'object':item,'class':classname(item)})
                                            except (RuntimeError,UnicodeError):pass
                                    entry['lists'].append({'field':hex(p),'object':candidate,'class':cname,'header':header.hex(),'examples':examples})
                            except (RuntimeError,UnicodeError):pass
                        roots.append(entry)
                    except (RuntimeError,UnicodeError):pass
                    try:pointer=self.uint(pointer)
                    except RuntimeError:break
            return {'roots':roots}
        if categories==['actor_manager_probe']:
            rows=[];seen=set();blob=self.read(self.base+0x2ba000,0x1b800)
            for offset in range(0,len(blob),4):
                pointer=struct.unpack_from('<I',blob,offset)[0]
                for depth in range(2):
                    if pointer in seen or pointer<0x10000:break
                    try:
                        vmt=self.uint(pointer);nameptr=self.uint(vmt-44);length=self.read(nameptr,1)[0]
                        if 1<=length<=64:
                            name=self.read(nameptr+1,length).decode('ascii')
                            if name.startswith('T') and all(c.isprintable() for c in name):
                                seen.add(pointer)
                                if any(word in name.lower() for word in ('actor','scene','play','game','cret','creat')):
                                    rows.append({'global':hex(0x2ba000+offset),'depth':depth,'object':pointer,'class':name,'head':self.read(pointer,256).hex()})
                    except (RuntimeError,UnicodeError):pass
                    try:pointer=self.uint(pointer)
                    except RuntimeError:break
            return {'objects':rows}
        if categories==['战士单击打怪验证']:
            import warrior_combat
            importlib.reload(warrior_combat)
            return warrior_combat.run(self,progress)
        if categories==['地牢巡逻路网只读']:
            import warrior_combat
            importlib.reload(warrior_combat)
            return warrior_combat.patrol_plan(self)[1]
        if categories==['地牢战士巡逻验证']:
            import warrior_combat
            importlib.reload(warrior_combat)
            return warrior_combat.run(self,progress,seconds=120,patrol=True)
        if categories==['地牢战士巡逻五分钟验证']:
            import warrior_combat
            importlib.reload(warrior_combat)
            return warrior_combat.run(self,progress,seconds=300,patrol=True)
        if categories==['地牢地图对象只读']:
            obj=self.uint(self.uint(self.base+0x2ba608))
            return {'object':obj,'raw':self.read(obj,256).hex(),'probe':self.map_probe()}
        if categories==['周围怪物']:return self.nearby_monsters()
        if categories==['孤岛NPC点击诊断']:
            return {'hero_panel':self.control_info(0x7b0,'Window_HeroStatus'),
                    'npcs':[dict(n,click=self.npc_click_point(n['draw'])) for n in self.npcs() if n['name']=='孤岛挑战'],
                    'game_input_sent':False}
        if categories==['打开实时监控']:return self.start_live_monitor()
        if categories==['重启实时监控']:return self.start_live_monitor(restart=True)
        if categories==['恢复已放入的待售装备']:return self.resume_pending_sale()
        if categories==['整理售卖布局']:
            returned=self.restore_held_to_bag()
            return {'returned':returned,'moved_bag':self.arrange_sale_layout()}
        if categories==['老兵固定菜单点击测试（不传送）']:return self.test_veteran_fixed_menu(progress)
        if categories==['苍月首饰出售菜单测试（不卖装备）']:return self.open_cangyue_fixed_sale('首饰店老板',progress)
        if categories==['苍月衣服出售菜单测试（不卖装备）']:return self.open_cangyue_fixed_sale('服装店老板',progress)
        if categories==['固定位置传送武器店测试']:return self.test_fixed_veteran_transfer('weapon',progress)
        if categories==['固定位置传送苍月测试']:return self.test_fixed_veteran_transfer('cangyue',progress)
        if categories==['打开普通房间菜单']:return self.open_hunt_menu()
        if categories==['进入普通房间']:return self.enter_ordinary_room(progress)
        if categories==['挂机清包循环']:return self.hunt_cycle(progress)
        if categories==['接续当前挂机图循环']:return self.hunt_cycle(progress,resume_current_room=True)
        if categories==['dismiss_town_notice']:return {'dismissed':self.dismiss_town_hunt_notice()}
        if categories==['测试当前建筑出口']:
            from map_navigation import load_matching_map
            obj=self.uint(self.uint(self.base+0x2ba608));header=self.read(obj+4,52)
            tilemap=load_matching_map(header)
            if tilemap.name.lower()!='b353.map':raise RuntimeError('出口核对仅用于当前b353建筑')
            border={(x,y) for x in range(tilemap.width) for y in range(tilemap.height)
                    if tilemap.free((x,y)) and any(not tilemap.free((x+dx,y+dy)) for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)))}
            visited=set();routes=[]
            while border-visited:
                current=tuple(self.stable_player())
                goal=min(border-visited,key=lambda xy:max(abs(xy[0]-current[0]),abs(xy[1]-current[1])))
                progress('核对建筑边缘出口格子：%s' % (goal,))
                result=self.walk_tile(goal,allow_transition=True,run_enabled=False)
                routes.append(result)
                if result.get('transition'):return {'exit_found':True,'routes':routes}
                visited.add(goal)
            return {'exit_found':False,'routes':routes}
        routes=[('手镯','jewelry','手镯店老板','sell_jewelry'),
                ('戒指','jewelry','戒指店老板','sell_jewelry'),
                ('项链','jewelry','项链店老板','sell_jewelry'),
                ('衣服','clothes','张家布衣老板','sell_clothes'),
                ('头盔','clothes','老张头盔店','sell_helmet'),
                ('武器','weapon','铁匠铺老板','sell_weapon')]
        selected=set(CATEGORIES.values() if categories is None else categories)
        if not selected<=set(CATEGORIES.values()):raise RuntimeError('未知出售部位')
        configured=self.profile()['menus']
        for category,store,name,menu in routes:
            if category in selected and any(CATEGORIES.get(item)==category for item in self.inventory()) and menu not in configured:
                raise RuntimeError(category+'商人菜单尚未校准，请先选择已验证的部位')
        started=time.monotonic();results=[]
        for category,store,name,menu in routes:
            if category not in selected or not any(CATEGORIES.get(item)==category for item in self.inventory()):continue
            self.visit_shop(store,progress)
            actors=[n for n in self.npcs() if n['name']==name]
            if len(actors)!=1:raise RuntimeError('未唯一找到'+name)
            self.close_panels();self.ensure_npc_visible(actors[0])
            progress('打开'+name+'的出售窗口')
            self.open_npc(actors[0]);self.menu_click(menu)
            self.wait(lambda:self.visible('sell') and self.visible('bag'))
            result=self.sell_category(category,progress,merchant_name=name)
            results.append(dict(result,category=category,merchant=name))
            self.close_panels()
        return {'categories':results,'count':sum(r['count'] for r in results),
                'seconds':round(time.monotonic()-started,3),'remaining_plan':sale_plan(self.inventory())}

    def press_tab(self):
        self.check()
        if not self.u.PostMessageW(self.hwnd, 0x100, 9, 1):
            raise RuntimeError('地图按键发送失败')
        try:
            self.pause(.1)
        finally:
            self.u.PostMessageW(self.hwnd, 0x101, 9, 0xc0000001)
        self.pause(.4)

    def walk_near_veteran(self,npc,progress=lambda message:None):
        if npc['name']!='盟重老兵' or tuple(npc['map'])!=(320,320):raise RuntimeError('行走目标不是已核对的盟重老兵')
        current=tuple(self.stable_player())
        if max(abs(current[0]-320),abs(current[1]-320))>30:raise RuntimeError('超出老兵附近30格范围，停止行走')
        self.close_panels()
        npc=self.locate_mengzhong_veteran(progress)
        return self.approach_veteran_running(npc,progress)

    def login_stage(self):
        for stage,offset,name in [('message',0x3d8,'Window_MsgDlg'),('login',0x3b0,'Window_Login'),
                                   ('server',0x3fc,'Window_SelServer'),('character',0x41c,'Window_SelectChr')]:
            if self.control_info(offset,name)['visible']:return stage
        try:
            actor=self.uint(self.uint(self.base+0x2bac2c))
            if actor>=0x10000:return 'dead' if self.read(actor+0xac,1)==b'\1' else 'playing'
        except RuntimeError:pass
        return 'loading'

    def recovery_message_matches(self,kind='disconnected'):
        from PIL import Image, ImageFilter
        box=self.control_info(0x3d8,'Window_MsgDlg')
        size=(256,359) if kind=='welcome' else (452,179)
        if not box['visible'] or tuple(box['bounds'][2:])!=size:return False
        if kind=='welcome':
            # Recorded from the live second confirmation, not the normal
            # disconnect dialog. Capture can be black during this transition.
            button=self.control_info(0x3dc,'Button_MsgDlgOk')
            return button['visible'] and tuple(button['bounds'])==(89,305,80,34)
        x,y=box['bounds'][:2]
        area=(x+20,y+60,x+236,y+230) if kind=='welcome' else (x+20,y+34,x+420,y+64)
        actual=self.capture_client().crop(area)
        directory=Path(__file__).with_name('shop-layout')
        templates=[directory/('recovery-'+kind+'.png')]
        if kind=='disconnected':
            templates.extend([directory/'recovery-disconnected-login.png',directory/'recovery-disconnected-ingame.png'])
        def mask(image):return [r>180 and g>180 and b>180 and max(r,g,b)-min(r,g,b)<45 for r,g,b in image.get_flattened_data()]
        b=mask(actual)
        for template in templates:
            if not template.is_file():continue
            a=mask(Image.open(template).convert('RGB'))
            if len(a)!=len(b):continue
            overlap=sum(x and y for x,y in zip(a,b))
            if sum(a)>30 and overlap/max(1,sum(a))>.97 and overlap/max(1,sum(b))>.97:return True
            # Full-screen scaling can shift the antialiased glyph edge by one
            # pixel. Keep both text coverage and ink count checks; never match
            # merely on the dialog frame or a short shared phrase.
            if kind=='disconnected' and sum(a)>30 and .9<sum(b)/sum(a)<1.1:
                def expand(values):
                    binary=Image.new('L',actual.size)
                    binary.putdata([255 if value else 0 for value in values])
                    return [value>0 for value in binary.filter(ImageFilter.MaxFilter(3)).get_flattened_data()]
                ea,eb=expand(a),expand(b)
                if (sum(x and y for x,y in zip(a,eb))/sum(a)>.97
                        and sum(x and y for x,y in zip(b,ea))/sum(b)>.97):return True
        return False

    def recover_stalled_route(self,progress,reason,pending=None):
        self.check()
        if getattr(self,'_stalled_route_recoveries',0)>=1:
            raise RuntimeError('本条命令已小退恢复一次，仍失败则停止，避免循环小退')
        if self.login_stage()!='playing' or self.held_item() or self.inflight_item():
            raise RuntimeError('现场或物品传输不明确，禁止故障小退')
        if self.sale_item():
            if pending is None:raise RuntimeError('有待售装备但没有已核对的失败上下文，未小退')
            self.verify_stalled_sale(pending.item,pending.context)
        actor=self.uint(self.uint(self.base+0x2bac2c));pointer=self.uint(actor+0xc)
        length=self.uint(pointer-4)
        if not 1<=length<=60:raise RuntimeError('当前角色身份未能确认，未小退')
        name=self.read(pointer,length).decode('gb18030')
        if not name or name!=getattr(self,'_expected_character',None):
            raise RuntimeError('故障小退角色与绑定身份不符，未操作')
        group=self.control_info(0xfb0,'UI_Window_ExitGroup')
        button=self.control_info(0x618,'Button_BotLogOut')
        if not group['visible'] or not button['visible']:raise RuntimeError('小退按钮未核对，停止')
        # Preserve the existing allowance across restarts, commands and failures.
        self.reserve_hunt_recovery('脚本故障限次小退：'+reason)
        self._stalled_route_recoveries=getattr(self,'_stalled_route_recoveries',0)+1
        if pending is not None:self.withdraw_verified_sale(pending.item,pending.context)
        if self.held_item() or self.sale_item() or self.inflight_item():
            raise RuntimeError('故障小退前物品未归位，停止')
        self.close_panels()
        progress(reason+'；物品已核对归位，小退一次后续跑当前清包流程')
        previous_recovering=getattr(self,'_recovering',False)
        previous_login=getattr(self,'_no_saved_account_login',False)
        self._recovering=True;self._no_saved_account_login=True
        try:
            # This is an actual logout, unlike recover_session on a living actor,
            # which merely checks that the actor is already playing.
            self.click(button_center(group['bounds'],button['bounds']))
            self.wait(lambda:self.login_stage()!='playing',timeout=12)
            result=self.recover_session(progress)
            return dict(result,reason=reason,script_stall_recovery=True)
        finally:
            self._recovering=previous_recovering;self._no_saved_account_login=previous_login

    def recover_session(self,progress=lambda message:None):
        self._recovering=True
        started=time.monotonic();deadline=started+90
        transitions=[];actions={};playing_samples=0;saw_playing=False;auto_grace_used=False
        try:
            if hasattr(self,'reader') and not self.reader.alive():
                self.reconnect_running_client()
                progress('已核对同目录的新登录进程，重新绑定窗口和控件')
            self.u.PostMessageW(self.hwnd,0x1c,1,0)
            while time.monotonic()<deadline:
                if hasattr(self,'reader') and not self.reader.alive():
                    if actions.get('process_reconnect',0)>=2:raise RuntimeError('客户端连续重启，停止重复恢复')
                    self.reconnect_running_client();actions['process_reconnect']=actions.get('process_reconnect',0)+1
                    progress('客户端切换进程，已重新核对窗口和控件')
                stage=self.login_stage()
                if not transitions or transitions[-1]!=stage:transitions.append(stage)
                if stage!='playing':playing_samples=0
                if saw_playing and not auto_grace_used and stage in ('login','server','character'):
                    auto_grace_used=True
                    progress('服务器返回登录流程，先等待自动重登，不立即重复点击')
                    self.pause(3)
                    continue
                if stage=='loading':
                    self.pause(.1);continue
                if stage=='playing':
                    saw_playing=True
                    if playing_samples*.25<self.LOGIN_SETTLE_SECONDS:
                        if playing_samples==0:progress('已进入游戏，等待5秒确认服务器不会再次自动小退')
                        playing_samples+=1;self.pause(.25);continue
                    self.active_merchant=None;self.stable_player()
                    actor=self.uint(self.uint(self.base+0x2bac2c));nameptr=self.uint(actor+0xc)
                    length=self.uint(nameptr-4)
                    if not 1<=length<=60:raise RuntimeError('角色身份不符，未继续售卖')
                    character=self.read(nameptr,length).decode('gb18030')
                    expected=getattr(self,'_expected_character','大鱼')
                    if expected is not None and character!=expected:raise RuntimeError('角色身份不符，未继续售卖')
                    self._expected_character=character
                    if self.held_item() or self.sale_item() or self.inflight_item():raise RuntimeError('重登后物品操作尚未稳定，停止续卖')
                    self._last_hunt_seconds=None;self._hunt_duration_basis='after_relogin_unknown'
                    return {'recovered':True,'position':self.player(),'seconds':round(time.monotonic()-started,2),'transitions':transitions}
                if stage=='dead':
                    if actions.get('dead'):raise RuntimeError('小退后仍为死亡状态，停止重复点击')
                    actions['dead']=1
                    progress('确认角色死亡，立即小退重登')
                    group=self.control_info(0xfb0,'UI_Window_ExitGroup')['bounds']
                    self.click(button_center(group,self.control_info(0x618,'Button_BotLogOut')['bounds']))
                    self.wait(lambda:self.login_stage()!='dead',timeout=12)
                    continue
                elif stage=='message':
                    kind=next((kind for kind in ('welcome','disconnected','logout') if self.recovery_message_matches(kind)),None)
                    if kind is None:raise RuntimeError('重登遇到未识别的提示，已停止')
                    if actions.get(kind,0)>=2:raise RuntimeError('相同登录提示重复出现，停止重试')
                    actions[kind]=actions.get(kind,0)+1
                    root=self.control_info(0x3d8,'Window_MsgDlg')['bounds']
                    if kind=='welcome':self.press_login_confirm()
                    else:self.click(button_center(root,self.control_info(0x3dc,'Button_MsgDlgOk')['bounds']))
                    self.wait(lambda:self.login_stage()!='message',timeout=5)
                elif stage=='login':
                    if getattr(self,'_no_saved_account_login',False):raise RuntimeError('已退到账号登录页；未输入旧号凭据，请登录当前账号')
                    if actions.get('login',0)>=(2 if saw_playing else 1):raise RuntimeError('账号登录页反复返回，已达到限次恢复上限')
                    actions['login']=actions.get('login',0)+1
                    progress('使用本机加密配置登录（不记录登录信息）')
                    self.submit_saved_login()
                elif stage=='server':
                    if actions.get('server',0)>=(2 if saw_playing else 1):raise RuntimeError('重复返回服务器选择页，停止')
                    actions['server']=actions.get('server',0)+1
                    self.select_login_server()
                elif stage=='character':
                    if actions.get('character',0)>=(2 if saw_playing else 1):raise RuntimeError('角色选择页反复返回，已达到限次恢复上限')
                    actions['character']=actions.get('character',0)+1
                    self.enter_saved_character()
                else:raise RuntimeError('无法识别登录状态：'+stage)
            raise RuntimeError('重登90秒内未稳定进入游戏，停止重试')
        finally:
            self._recovering=False
            if not hasattr(self,'reader') or self.reader.alive():self.clear_background_mouse()

    def press_login_confirm(self):
        self.check()
        if not self.recovery_message_matches('welcome'):raise RuntimeError('二次确认页已变化，未发送回车')
        if isinstance(self,ForegroundSession):
            self.focus_game()
            key=Input();key.type=1;key.data.ki.vk=0x0d
            if self.u.SendInput(1,ctypes.byref(key),ctypes.sizeof(Input))!=1:raise RuntimeError('确认回车发送失败')
            try:self.pause(.08)
            finally:
                key.data.ki.flags=2
                self.u.SendInput(1,ctypes.byref(key),ctypes.sizeof(Input))
        else:
            self.u.PostMessageW(self.hwnd,0x100,0x0d,0x001c0001)
            self.pause(.08)
            self.u.PostMessageW(self.hwnd,0x101,0x0d,0xc01c0001)
        self.pause(.2)

        if self.login_stage()=='message' and self.recovery_message_matches('welcome'):
            root=self.control_info(0x3d8,'Window_MsgDlg')['bounds']
            self.click(button_center(root,self.control_info(0x3dc,'Button_MsgDlgOk')['bounds']))

    def enter_saved_character(self):
        if self.login_stage()!='character':raise RuntimeError('当前不是角色选择页')
        if isinstance(self,ForegroundSession):self.focus_game()
        root=self.control_info(0x41c,'Window_SelectChr')['bounds']
        # The existing character is selected after logout. Selecting it again
        # can reopen the login transition; try the verified Start button first.
        self.click(button_center(root,self.control_info(0x420,'Button_scStart')['bounds']))
        try:self.wait(lambda:self.login_stage()!='character',timeout=2)
        except RuntimeError:
            self.check()
            if self.login_stage()!='character':raise
            # Selection may still be loading when the first Start was sent.
            # Retry only this verified login button, once, never an item action.
            self.click(button_center(root,self.control_info(0x434,'Button_scSelect1')['bounds']))
            self.pause(.5)
            if self.login_stage()=='character':
                self.click(button_center(root,self.control_info(0x420,'Button_scStart')['bounds']))
            self.wait(lambda:self.login_stage()!='character',timeout=8)
        return {'stage':self.login_stage()}

    def select_login_server(self):
        if self.login_stage()!='server':raise RuntimeError('当前不是服务器选择页')
        root=self.control_info(0x3fc,'Window_SelServer')['bounds']
        buttons=[self.control_info(0x400+i*4,'Button_SServer%d'%(i+1)) for i in range(6)]
        available=[b for b in buttons if b['visible']]
        if len(available)!=1:raise RuntimeError('服务器选项不唯一，停止自动登录')
        self.click(button_center(root,available[0]['bounds']))
        self.wait(lambda:self.login_stage()!='server',timeout=15)
        return {'stage':self.login_stage()}

    def submit_saved_login(self):
        from credential_store import load
        if self.login_stage()!='login':raise RuntimeError('当前不是账号登录界面，未输入登录信息')
        credentials=load()
        if not credentials.get('character') or credentials['character']!=getattr(self,'_expected_character',None):
            credentials.clear()
            raise RuntimeError('本号加密登录配置与当前绑定角色不一致，请更新对应账号配置；未输入账号密码')
        root=self.control_info(0x3b0,'Window_Login')['bounds']
        def fill(offset,name,value):
            control=self.control_info(offset,name)
            self.click(button_center(root,control['bounds']))
            self.u.PostMessageW(self.hwnd,0x100,0x23,1);self.pause(.06)
            self.u.PostMessageW(self.hwnd,0x101,0x23,0xc0000001)
            for _ in range(64):
                self.check();self.u.PostMessageW(self.hwnd,0x102,8,1);self.pause(.02)
            for char in value:
                self.check();self.u.PostMessageW(self.hwnd,0x102,ord(char),1);self.pause(.08)
        fill(0x3a4,'Edit_LoginID',credentials['username'])
        fill(0x3a8,'Edit_LoginPwd',credentials['password'])
        credentials.clear()
        self.click(button_center(root,self.control_info(0x3ac,'Button_LoginOK')['bounds']))
        self.wait(lambda:self.login_stage()!='login',timeout=15)
        return {'stage':self.login_stage(),'credentials_logged':False}

    def ensure_hero_available(self):
        if self.hero_ready():return
        actor=self.uint(self.uint(self.base+0x2bac2c))
        hero=self.uint(actor+0x358)
        if hero>=0x10000 and self.read(hero+0xac,1)==b'\1':
            raise RuntimeError('英雄死亡，停止双包操作')
        # After relogin the summon flag can remain set with no hero actor.
        # The visible recall control resynchronizes this state without memory writes.
        group=self.control_info(0xfa4,'UI_Window_HeroGroup')['bounds']
        button=self.control_info(0x7a4,'Button_RecallHero')
        if not button['visible']:raise RuntimeError('英雄召唤按钮未显示，停止双包操作')
        self.click(button_center(group,button['bounds']))
        self.wait(self.hero_ready,timeout=12)

    def prepare_hero_avatar(self):
        if self.hero_covers((10,40,350,450)):
            self.run_shop_route(['头像移到左下'])

    def open_main_bag(self):
        if not self.visible('bag'):
            group=self.control_info(0xfa0,'UI_Window_StateGroup')
            button=self.control_info(0x650,'Button_MyBag')
            point=button_center(group['bounds'],button['bounds'])
            width,height=self.client_size()
            if not group['visible'] or not button['visible']:raise RuntimeError('人物操作栏或背包按钮未显示')
            if not (0<=point[0]<width and 0<=point[1]<height):raise RuntimeError('背包按钮超出当前客户区，未点击')
            # Match the verified scaled UI input used by the hunt entry menu.
            BackgroundSession.background_mouse(self,button_center(group['bounds'],button['bounds']),
                'left',track_movement=False,move_settle=.15,dpi_scaled=True,
                button_hold=.15,restore_client_focus=True)
            self.pause(.6)
            if not self.visible('bag'):
                # F9 is the game's displayed bag shortcut. Toggle only once,
                # after confirming the click left the bag closed.
                self.wait_shortcut_modifiers_released()
                self.check()
                if self.held_item() or self.sale_item() or self.inflight_item():
                    raise RuntimeError('Bag shortcut blocked by pending item')
                if isinstance(self,ForegroundSession):
                    # DirectInput clients may ignore virtual-key-only events.
                    self.focus_game()
                    key=Input();key.type=1;key.data.ki.scan=0x43;key.data.ki.flags=8
                    if self.u.SendInput(1,ctypes.byref(key),ctypes.sizeof(Input))!=1:
                        raise RuntimeError('Bag scan-code keydown failed')
                    try:self.pause(.15)
                    finally:
                        key.data.ki.flags=10
                        self.u.SendInput(1,ctypes.byref(key),ctypes.sizeof(Input))
                else:
                    self.begin_background_input()
                    try:
                        if not self.u.PostMessageW(self.hwnd,0x100,0x78,0x430001):
                            raise RuntimeError('Bag shortcut keydown failed')
                        self.pause(.15)
                    finally:self.u.PostMessageW(self.hwnd,0x101,0x78,0xc0430001)
                self.events.append({'input':'bag_shortcut','key':'F9','retries':0})
            self.wait(lambda:self.visible('bag'))

    def handle_full_bags(self):
        from inventory_flow import bag_decision,retain_in_main_bag
        if not self.hero_ready():raise RuntimeError('英雄未召唤，暂停背包监测')
        decision=bag_decision(self.inventory(),self.hero_inventory(),True)
        moved=[]
        if decision=='transfer':
            if self.visible('merchant') or self.visible('sell'):raise RuntimeError('商人界面打开，未执行挂机转包')
            self.open_main_bag()
            for index,name in enumerate(self.inventory()):
                if self.hero_inventory().count('')<=1:break
                if retain_in_main_bag(name):continue
                if name:moved.append(self.transfer_bag_item('main',index,allow_unchanged=True,allow_new_loot=True))
            decision=bag_decision(self.inventory(),self.hero_inventory(),self.hero_ready())
        return {'decision':decision,'transfers':moved,
                'return_required':decision=='return_town','bags':self.dual_bag_status()}

    def shortcut_inventory(self):
        pointer=self.uint(self.base+0x2ba434)
        if pointer<0x10000:raise RuntimeError('快捷栏未加载，未发送按键')
        raw=self.read(pointer,6*156);slots=[]
        for i in range(6):
            record=raw[i*156:(i+1)*156];length=record[0]
            if length>20:raise RuntimeError('快捷栏名称结构不符，未发送按键')
            name=record[1:1+length].decode('gb18030') if length else ''
            slots.append({'key':i+1,'name':name,'raw_98':struct.unpack_from('<H',record,0x98)[0]})
        return slots

    def currency_snapshot(self):
        try:
            actor=self.uint(self.uint(self.base+0x2bac2c))
            gold,yuanbao=struct.unpack('<2I',self.read(actor+0x138,8))
            return {'gold':gold,'yuanbao':yuanbao}
        except (RuntimeError,OSError,struct.error):return {'gold':None,'yuanbao':None}

    def write_stats(self,event):
        from cycle_stats import append_event
        directory=instance_context.runtime_root()/'outputs'/'挂机统计'
        try:return append_event(directory,event)
        except PermissionError as error:
            # The persistent helper may still hold the older CSV exporter.
            # It appends the authoritative JSONL before opening the CSV.
            if event.get('event')!='sale_round' or not str(getattr(error,'filename','')).endswith('.csv'):raise
            from cycle_stats import append_runtime_event
            append_runtime_event(directory,{'event':'csv_export_blocked','round_id':event.get('round_id'),
                                           'error':str(error),'jsonl_preserved':True})
            return dict(event,csv_export_blocked=True)

    def nearby_monsters(self,radius=8):
        self.check()
        for attempt in range(3):
            try:return self._nearby_monsters_snapshot(radius)
            except RuntimeError as error:
                if not any(text in str(error) for text in ('场景列表读取时发生变化','人物坐标在采样时发生变化')) or attempt==2:raise
                self.pause(.01)

    def nearby_players(self,radius=8):
        def snapshot():
            own=self.uint(self.uint(self.base+0x2bac2c));position=tuple(self.player())
            rows=self.scene_actor_snapshot();humans=[];heroes={self.uint(own+0x358)}
            addresses={address for address,raw in rows}
            for address,raw in rows:
                if struct.unpack_from('<I',raw)[0]!=self.base+0x24991c:continue
                hero=self.uint(address+0x358)
                if hero in addresses:heroes.add(hero)
                humans.append((address,raw))
            players=[]
            for address,raw in humans:
                if address==own or address in heroes or raw[0xac]==1:continue
                x,y=struct.unpack_from('<2i',raw,0x68)
                if raw[0xac] not in (0,1) or not(0<=x<10000 and 0<=y<10000):raise RuntimeError('附近玩家数据不符')
                if radius is None or max(abs(x-position[0]),abs(y-position[1]))<=radius:
                    players.append({'address':address,'position':[x,y]})
            if tuple(self.player())!=position:raise RuntimeError('人物坐标在采样时发生变化，请重读')
            return players

        for attempt in range(3):
            try:return snapshot()
            except RuntimeError as error:
                if not any(text in str(error) for text in ('场景列表读取时发生变化','人物坐标在采样时发生变化')) or attempt==2:raise
                self.pause(.01)

    def start_live_monitor(self,restart=False):
        import live_state
        if restart:importlib.reload(live_state)
        LiveSampler=live_state.LiveSampler
        # Retire only the old, exact monitor window. No game activation.
        @self.reader.callback_type
        def visit(hwnd,unused):
            title=ctypes.create_unicode_buffer(256)
            self.u.GetWindowTextW(hwnd,title,len(title))
            if title.value=='追忆 · 实时坐标与周围怪物':self.u.PostMessageW(hwnd,0x10,0,0)
            return True
        self.u.EnumWindows(visit,0)
        sampler=getattr(self,'_live_sampler',None)
        if sampler is not None and (restart or not sampler.thread.is_alive()):
            sampler.stop();sampler=None
        if sampler is None:
            path=instance_context.runtime_root()/'outputs'/'实时监控.json'
            self._live_sampler=LiveSampler(lambda:{'pid':self.reader.pid,'hwnd':int(self.hwnd)},path,
                                           lambda:getattr(self,'_random_status',{}))
        return {'monitor_pid':__import__('os').getpid(),'sampler':'helper_thread','sample_interval_ms':200}

    def resume_pending_sale(self):
        item=self.sale_item()
        if not item:return {'resumed':False,'reason':'出售框为空，未点击'}
        category=CATEGORIES.get(item)
        merchant={'武器':('铁匠铺老板',(5,9)),
                  '衣服':('服装店老板',(147,328)),'头盔':('服装店老板',(147,328)),
                  '项链':('首饰店老板',(155,339)),'戒指':('首饰店老板',(155,339)),
                  '手镯':('首饰店老板',(155,339))}.get(category)
        if merchant is None:raise RuntimeError('待售物品未匹配已验证的恢复商人，未确认')
        if self.held_item() or self.inflight_item() or not self.visible('sell') or not self.visible('bag'):
            raise RuntimeError('待售状态不稳定，未确认')
        if getattr(self,'active_merchant',None) not in (None,merchant[0]):raise RuntimeError('待售恢复商人不匹配，未确认')
        self.unique_npc(*merchant)
        before=self.inventory();wallet=self.currency_snapshot()
        self.click(button_center(self.bounds('sell'),self.bounds('ok')))
        self.wait(lambda:not self.sale_item() and not self.inflight_item(),timeout=4)
        self.pause(.45)
        if self.inventory()!=before or self.held_item():raise RuntimeError('恢复确认后背包发生变化，停止后续操作')
        after=self.currency_snapshot()
        change=after['gold']-wallet['gold'] if None not in (after['gold'],wallet['gold']) else None
        result={'resumed':True,'item':item,'gold_before':wallet['gold'],'gold_after':after['gold'],
                'gold_change':change,'yuanbao_after':after['yuanbao']}
        self.sales.append(result)
        self.write_stats({'event':'sale_item','round_id':getattr(self,'_stats_round_id',None),**result})
        self.write_stats({'event':'sale_round','round_id':__import__('uuid').uuid4().hex[:12],
            'status':'resumed_pending','sold_count':1,'gold_before':wallet['gold'],'gold_after':after['gold'],
            'gold_net_change':change,'sale_income_gold':change,'other_gold_change':0,
            'yuanbao_before':wallet['yuanbao'],'yuanbao_after':after['yuanbao'],
            'yuanbao_change':after['yuanbao']-wallet['yuanbao'] if None not in (after['yuanbao'],wallet['yuanbao']) else None})
        return result

    def restore_held_to_bag(self):
        item=self.held_item()
        if not item:return False
        if self.sale_item() or self.inflight_item() or not self.visible('bag'):raise RuntimeError('拿起物品状态不稳定，未点击')
        before=self.inventory()
        if '' not in before:raise RuntimeError('背包没有空格，未放回拿起的物品')
        index=before.index('');expected=before.copy();expected[index]=item
        self.click(grid_center(self.bounds('bag'),self.bounds('grid'),index))
        self.wait(lambda:not self.held_item() and self.inventory()==expected,timeout=4)
        return True

    def sale_layout_overlaps(self):
        if not self.visible('sell') or not self.visible('bag'):return False
        bx,by,bw,bh=self.bounds('bag')
        targets=[button_center(self.bounds('sell'),self.bounds(key)) for key in ('spot','ok')]
        return any(bx<=sx<bx+bw and by<=sy<by+bh for sx,sy in targets)

    def arrange_sale_layout(self):
        if not self.sale_layout_overlaps():return False
        bx,by,bw,bh=self.bounds('bag')
        if self.held_item():raise RuntimeError('背包覆盖出售框且鼠标拿着物品，先恢复物品再整理')
        if not isinstance(self,ForegroundSession):raise RuntimeError('背包覆盖出售框，需要前台整理布局')
        self.drag_ui((bx+bw//2,by+10),(416+bw//2,10))
        after=self.bounds('bag')
        if after[:2]!=(416,0):raise RuntimeError('背包未到已校准位置，停止出售')
        self.write_stats({'event':'ui_layout_corrected','bag_before':[bx,by,bw,bh],'bag_after':list(after)})
        return True

    def _nearby_monsters_snapshot(self,radius=8):
        from collections import Counter
        started=time.perf_counter();class_cache={}
        def lineage(vmt):
            if vmt in class_cache:return class_cache[vmt]
            chain=[];seen=set();current=vmt
            for _ in range(12):
                if current in seen or not self.base<=current<self.base+0x300000:break
                seen.add(current);ptr=self.uint(current-44);length=self.read(ptr,1)[0]
                if not 1<=length<=80:break
                chain.append(self.read(ptr+1,length).decode('ascii'))
                parent=self.uint(current-36)
                if parent<0x10000:break
                current=self.uint(parent)
            class_cache[vmt]=chain;return chain
        scene=self.uint(self.uint(self.base+0x2ba8fc))
        if lineage(self.uint(scene))[0]!='TPlayScene':raise RuntimeError('当前场景结构不符，未计数')
        actor_list=self.uint(scene+0x98)
        if lineage(self.uint(actor_list))[0]!='TList':raise RuntimeError('场景列表类型不符，未计数')
        header=self.read(actor_list,16);_,items,count,capacity=struct.unpack('<4I',header)
        if not 0<=count<=capacity<=20000:raise RuntimeError('场景列表容量不符，未计数')
        pointers=struct.unpack('<%dI'%count,self.read(items,count*4)) if count else ()
        own=tuple(self.player());width,height=self.client_size();rows=[];types=Counter();errors=0
        for address in dict.fromkeys(pointers):
            try:
                raw=self.read(address,0x184);chain=lineage(struct.unpack_from('<I',raw)[0]);types[chain[0] if chain else '?']+=1
                if 'TActor' not in chain or 'THumActor' in chain or 'TNpcActor' in chain:continue
                nameptr=struct.unpack_from('<I',raw,0xc)[0];length=self.uint(nameptr-4)
                if not 1<=length<=60:continue
                name=self.read(nameptr,length).decode('gb18030')
                x,y=struct.unpack_from('<2i',raw,0x68);dx,dy=struct.unpack_from('<2i',raw,0x17c)
                if not all(0<=v<10000 for v in (x,y)):continue
                dead=raw[0xac]
                if dead not in (0,1):continue
                rows.append({'address':address,'name':name,'class':chain[0],'position':[x,y],
                             'distance':max(abs(x-own[0]),abs(y-own[1])),
                             'dead':bool(dead),'on_screen':0<=dx<width and 0<=dy+32<height-160})
            except (RuntimeError,UnicodeError,struct.error,IndexError):errors+=1
        if self.read(actor_list,16)!=header:raise RuntimeError('场景列表读取时发生变化，请重新读取')
        if tuple(self.player())!=own:raise RuntimeError('人物坐标在采样时发生变化，请重读')
        alive=[row for row in rows if not row['dead']];near=[row for row in alive if row['distance']<=radius]
        return {'radius':radius,'player':own,'nearby_alive':len(near),'nearby_by_name':dict(Counter(r['name'] for r in near)),
                'loaded_monster_alive':len(alive),'loaded_dead':sum(r['dead'] for r in rows),
                'visible_alive':sum(r['on_screen'] for r in alive),'list_count':count,'classes':dict(types),
                'read_errors':errors,'seconds':round(time.perf_counter()-started,4),'monsters':rows,
                'hostility_verified':False}

    def ordinary_room_points(self,image=None):
        from PIL import Image
        if not self.visible('merchant') or tuple(self.bounds('merchant')[2:])!=(432,261):return []
        image=image if image is not None else self.capture_client()
        template=Image.open(self.resource('ordinary-room.png')).convert('RGB')
        def mask(im):return [r>180 and g>150 and b<100 for r,g,b in im.convert('RGB').getdata()]
        expected=mask(template);count=sum(expected)
        if count<20:raise RuntimeError('普通房间模板无效，未点击')
        x,y=self.bounds('merchant')[:2];points=[]
        for row in range(2):
            for col in range(6):
                left,top=x+14+col*66,y+160+row*28
                actual=mask(image.crop((left,top,left+50,top+16)))
                if text_masks_match(expected,actual,(50,16),.94):points.append((left+25,top+8))
        return points

    def open_hunt_menu(self):
        from PIL import Image,ImageChops,ImageStat
        if self.login_stage()!='playing':raise RuntimeError('角色未进入游戏，未打开挂机菜单')
        points=self.ordinary_room_points()
        if points:return {'points':points,'already_open':True}
        self.close_panels()
        actual=self.capture_client().crop((6,242,80,264)).convert('RGB')
        template=Image.open(self.resource('auto-hunt-button.png')).convert('RGB')
        if max(ImageStat.Stat(ImageChops.difference(actual,template)).mean)>6:
            raise RuntimeError('左侧自动挂机按钮未匹配，停止；未按地面坐标点击')
        BackgroundSession.background_mouse(self,(43,253),'left',track_movement=False,move_settle=.15,dpi_scaled=True,button_hold=.15,restore_client_focus=True)
        self.wait(lambda:bool(self.ordinary_room_points()),timeout=5)
        return {'points':self.ordinary_room_points(),'already_open':False}

    def prepare_ordinary_room_entry(self):
        if not any(s['name'] in ('盟重传送石','盟重回城石') for s in self.shortcut_inventory()):
            raise RuntimeError('快捷栏没有盟重传送石，未进入挂机房')
        if self.hero_ready():
            bags=self.dual_bag_status()
            if bags['main_free']<=1 and bags['hero_free']<=1:raise RuntimeError('双包均已达39格，请先出售再进图')
        elif '' not in self.inventory():
            raise RuntimeError('人物包满且英雄尚未加载，请先清包再进图')
        self.ensure_ordinary_entry_town()
        menu=self.open_hunt_menu()
        if not menu.get('points'):raise RuntimeError('未识别普通房间入口，停止')
        return menu

    def town_sale_entry_test(self,progress=lambda message:None,resume_known_shop=False):
        report={'test':'土城出售到入场前','status':'running','entered':False,'entry_clicks':0,
                'sale_verified':False,'stages':[]}
        def stage(message):
            report['stages'].append(message);progress(message)
        try:
            self.check()
            if self.login_stage()!='playing':raise RuntimeError('请先登录角色并到土城，再运行完整测试')
            self.validate_city_ui_layout()
            if not self.in_mengzhong_return_area():
                known=resume_known_shop and any((n['name'],tuple(n['map'])) in
                    {('铁匠铺老板',(5,9)),('苍月老兵',(139,333))} for n in self.npcs())
                if not known:raise RuntimeError('请先到土城回城点附近；本测试不会自动回城或进图')
                report['resumed_from_verified_shop']=True
            if self.held_item() or self.sale_item() or self.inflight_item():raise RuntimeError('有未结束的物品操作，未启动完整测试')
            report['wallet_before']=self.currency_snapshot()
            stage('1/3 土城检查通过，读取双包并按现有白名单实际出售')
            report['sale']=self.dual_sale_route(progress,allow_recovery=False)
            report['sale_verified']=report['sale']['count']>0
            if sale_plan(self.inventory()) or sale_plan(self.hero_inventory()):raise RuntimeError('双包仍有白名单装备，未继续到入场菜单')
            if self.held_item() or self.sale_item() or self.inflight_item():raise RuntimeError('出售后物品操作未稳定，未打开入场菜单')
            if not report['sale_verified']:stage('双包没有白名单装备：跳过出售，成交环节本次未验证')
            stage('2/3 清包结束，按正式流程检查回城石及背包，打开挂机菜单')
            self.ensure_ordinary_entry_town()
            header=self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)
            menu=self.prepare_ordinary_room_entry()
            if self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)!=header:raise RuntimeError('打开菜单时地图意外变化，测试停止')
            report['menu']=menu
            report['wallet_after']=self.currency_snapshot()
            before=report['wallet_before'];after=report['wallet_after']
            if before['yuanbao'] is None or after['yuanbao'] is None:raise RuntimeError('元宝余额未能核对，测试未通过')
            report['yuanbao_change']=after['yuanbao']-before['yuanbao']
            report['gold_change']=after['gold']-before['gold'] if None not in (after['gold'],before['gold']) else None
            if report['yuanbao_change']!=0:raise RuntimeError('测试期间元宝有变化，需核对原因，未点击入场')
            report['status']='complete' if report['sale_verified'] else 'complete_without_sale'
            stage('3/3 已识别普通房间，测试停在入场点击前；不下图，不计挂机闭环')
            return report
        except Exception as error:
            report['status']='stopped';report['error']=str(error)
            raise
        finally:
            if hasattr(self,'reader'):
                directory=instance_context.runtime_root()/'outputs'/'挂机统计'
                (directory/'城内完整流程测试.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
            if getattr(self,'_stats_enabled',False):self.write_stats({'event':'town_sale_entry_test','report':report})

    def ensure_ordinary_entry_town(self,progress=lambda message:None):
        if self.login_stage()!='playing':raise RuntimeError('角色状态不明，未准备普通房间入场地点')
        if self.held_item() or self.sale_item() or self.inflight_item():
            raise RuntimeError('物品操作未结束，未准备普通房间入场地点')
        if self.in_mengzhong_return_area():return
        header=self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)
        name=self.current_map_name(header).lower()
        expected={'5.map':('苍月老兵',(139,333)), '0159.map':('铁匠铺老板',(5,9))}
        if name not in expected:raise RuntimeError('普通房间入场地点未核对，请先回盟重；未发送回城或入场操作')
        npc,position=expected[name]
        self.unique_npc(npc,position)
        progress('清包后仍在已核对商店城镇，先回盟重再准备普通房间入口')
        self.return_with_hotkey(progress,reason='ordinary_reentry')
        if not self.in_mengzhong_return_area():raise RuntimeError('重新入场前未确认回到盟重，停止')

    def enter_ordinary_room(self,progress=lambda message:None):
        if getattr(self,'_requires_clean_bags_before_entry',False):self.reconcile_before_reentry(progress)
        menu=self.prepare_ordinary_room_entry()
        header=self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)
        progress('已识别普通房间，点击一次进入；不点第三排高级房间')
        BackgroundSession.background_mouse(self,menu['points'][0],'left',track_movement=False,move_settle=.15,dpi_scaled=True,button_hold=.15,restore_client_focus=True)
        self.wait(lambda:self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)!=header,timeout=12)
        self.wait(lambda:self.login_stage()=='playing' and not self.visible('merchant'),timeout=8)
        self._hunting_header=self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)
        self._hunt_started_at=time.monotonic();self._hunt_duration_basis='room_entry'
        self._last_hunt_seconds=None
        if getattr(self,'_stats_enabled',False):self.write_stats({'event':'room_entry','wallet':self.currency_snapshot(),'position':self.player()})
        try:self.wait(self.hero_ready,timeout=5)
        except RuntimeError:
            self.check();self.ensure_hero_available()
        self.prepare_hero_avatar()
        return {'entered':True,'room':'普通房间','position':self.player(),'entry_clicks':1}

    def saved_hunt_recovery_used(self):
        path=instance_context.runtime_root()/'outputs'/'挂机统计'/'当前挂机恢复计数.json'
        return recovery_ledger.load_for_character(path,self.reader.pid,getattr(self,'_expected_character',None),instance_context.slot())['used']

    def reserve_hunt_recovery(self,reason):
        used=getattr(self,'_hunt_recoveries',0)
        path=instance_context.runtime_root()/'outputs'/'挂机统计'/'当前挂机恢复计数.json'
        if hasattr(self,'reader'):
            used=recovery_ledger.reserve_for_character(path,self.reader.pid,getattr(self,'_expected_character',None),instance_context.slot(),used,reason)
        else:
            if used>=2:raise RuntimeError('本角色累计恢复额度已用完，停止反复重登')
            used+=1
        self._hunt_recoveries=used
        return used

    def finish_hunt_before_reentry(self,progress,cycles):
        # A one-shot request belongs to this bound client, independently per slot.
        if not hasattr(self,'reader'):return None
        path=instance_context.runtime_root()/'outputs'/'挂机统计'/'本轮清包后停止.json'
        try:request=json.loads(path.read_text(encoding='utf8'))
        except FileNotFoundError:return None
        if request.get('status')!='pending':return None
        if request.get('game_pid')!=self.reader.pid or request.get('instance')!=instance_context.slot():
            raise RuntimeError('本轮清包停止请求与当前角色进程不一致，未重新入场')
        if sale_plan(self.inventory()) or sale_plan(self.hero_inventory()):
            raise RuntimeError('清包后仍有白名单装备，未继续入场菜单')
        if self.held_item() or self.sale_item() or self.inflight_item():
            raise RuntimeError('清包后物品操作未稳定，未继续入场菜单')
        self.close_panels()
        before=self.currency_snapshot()
        self.ensure_ordinary_entry_town(progress)
        header=self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)
        menu=self.prepare_ordinary_room_entry()
        after=self.currency_snapshot()
        if self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)!=header:
            raise RuntimeError('停在入场前时地图意外变化')
        if before['yuanbao'] is None or after['yuanbao']!=before['yuanbao']:
            raise RuntimeError('入场前元宝核对失败，停止')
        report={'status':'sale_complete_no_reentry','cycles':cycles,'entered':False,'entry_clicks':0,
                'menu':menu,'wallet_before_menu':before,'wallet_after_menu':after,'position':self.player()}
        request.update(status='completed',completed_epoch=time.time(),result=report)
        temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps(request,ensure_ascii=False,indent=2),encoding='utf8');temporary.replace(path)
        if getattr(self,'_stats_enabled',False):self.write_stats({'event':'sale_complete_no_reentry','report':report})
        progress('本轮双包清包完成，已打开普通房间菜单；按用户要求停在入场点击前，不再下图')
        return report

    def hunt_cycle(self,progress=lambda message:None,seconds=43200,resume_current_room=False):
        if isinstance(self,ForegroundSession):self.focus_game()
        started=time.monotonic();cycles=0;recoveries=getattr(self,'_hunt_recoveries',0)
        if hasattr(self,'reader'):recoveries=max(recoveries,self.saved_hunt_recovery_used())
        def reserve_recovery():
            nonlocal recoveries
            self._hunt_recoveries=max(getattr(self,'_hunt_recoveries',0),recoveries)
            recoveries=self.reserve_hunt_recovery('挂机中死亡或掉线')
        if resume_current_room:
            if self.login_stage()!='playing':raise RuntimeError('尚未进入游戏，不能接续当前挂机图')
            if self.in_mengzhong_return_area() or any(n['name'] in {'盟重老兵','苍月老兵','铁匠铺老板','服装店老板','首饰店老板'} for n in self.npcs()):
                raise RuntimeError('当前在城内或商店，请使用普通启动入口')
            if self.held_item() or self.sale_item() or self.inflight_item():raise RuntimeError('物品操作未结束，不能接续挂机')
            self._hunting_header=self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)
            self._hunt_started_at=started;self._hunt_duration_basis='user_confirmed_existing_room'
            progress('按用户选择接续当前挂机图，不点击入场菜单；满包后正常回城出售')
        if not hasattr(self,'_hunt_started_at'):
            self._hunt_started_at=started;self._hunt_duration_basis='monitor_started_mid_room'
        while time.monotonic()-started<seconds:
            self.check()
            self.dismiss_town_hunt_notice()
            if self.login_stage()!='playing':
                if self.login_stage()=='message' and not any(self.recovery_message_matches(kind) for kind in ('disconnected','logout','welcome')):
                    raise RuntimeError('出现未识别的游戏提示，停止；未消耗重登恢复次数')
                reserve_recovery()
                self.recover_session(progress)
                progress('挂机掉线重登完成，先回盟重城，再继续清包入场')
                self.return_with_hotkey(progress,reason='relogin')
                self._hunting_header=None
            current=self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)
            if current!=getattr(self,'_hunting_header',None) or self.in_mengzhong_return_area():
                self.ensure_hero_available()
                bags=self.dual_bag_status()
                pending=sale_plan(self.inventory())+sale_plan(self.hero_inventory())
                anchors={'盟重老兵','苍月老兵','铁匠铺老板','服装店老板','首饰店老板'}
                already_at_shop=bool(pending) and any(n['name'] in anchors for n in self.npcs())
                if pending and not already_at_shop:already_at_shop=self.in_mengzhong_return_area()
                if already_at_shop:
                    self.dual_sale_route(progress);cycles+=1
                elif bags['main_free']<=1 and bags['hero_free']<=1:
                    self.return_with_hotkey(progress)
                    self.dual_sale_route(progress);cycles+=1
                if cycles:
                    finished=self.finish_hunt_before_reentry(progress,cycles)
                    if finished is not None:return finished
                self.enter_ordinary_room(progress)
            try:
                result=self.monitor_bags(progress,seconds=max(1,seconds-(time.monotonic()-started)),auto_return=True)
            except GameSessionLost:
                reserve_recovery()
                self.recover_session(progress)
                progress('挂机掉线重登完成，先回盟重城，再继续清包入场')
                self.return_with_hotkey(progress,reason='relogin')
                self._hunting_header=None
                continue
            if result['status']!='sale_complete':return dict(result,cycles=cycles)
            cycles+=1
            finished=self.finish_hunt_before_reentry(progress,cycles)
            if finished is not None:return finished
            progress('第%d轮清包完成，重新进入普通房间' % cycles)
        return {'status':'monitor_timeout','cycles':cycles}

    def return_with_hotkey(self,progress=lambda message:None,reason='bags_full'):
        if self.login_stage()!='playing':raise RuntimeError('角色未正常进入游戏，未按回城键')
        if self.held_item() or self.sale_item() or self.inflight_item():raise RuntimeError('物品操作未结束，未按回城键')
        self.close_panels()
        actors=self.npcs()
        if any(n['name']=='盟重老兵' and tuple(n['map'])==(320,320) for n in actors):
            self.unique_npc('盟重老兵',(320,320))
            return {'already_in_town':True,'hotkey_sent':False,'position':self.player()}
        header=self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)
        label='重登后回城' if reason=='relogin' else '武器店出口受阻' if reason=='weapon_shop_exit_blocked' else '提前回城测试' if reason=='manual_test' else '双包已满'
        progress(label+'，识别快捷栏中的盟重传送石，使用一次；等待确认土城')
        if reason in ('bags_full','manual_test') and hasattr(self,'_hunt_started_at'):self._last_hunt_seconds=round(time.monotonic()-self._hunt_started_at,1)
        wallet_before=self.currency_snapshot() if getattr(self,'_stats_enabled',False) else None
        self.press_return_hotkey()
        # Map changes can expose an intermediate spawn coordinate before the
        # server supplies the actual town landing point. Defer the notice guard
        # until that verified landing arrives; never click during the transition.
        self._dismissing_town_notice=True
        try:
            self.wait(lambda:self.in_mengzhong_return_area(),timeout=10)
            self.stable_player()
        finally:self._dismissing_town_notice=False
        # A town coordinate can arrive before the UI finishes its transition or
        # dismisses the return notice. It is not evidence of death/disconnection.
        previous_prompt=getattr(self,'_return_prompt_pending',False)
        self._return_prompt_pending=True
        try:
            if self.login_stage()!='playing':self.settle_return_ui(progress)
            self.locate_mengzhong_veteran(progress)
            self.dismiss_town_hunt_notice()
        finally:self._return_prompt_pending=previous_prompt
        if wallet_before is not None:self.write_stats({'event':'return_town','reason':reason,'before':wallet_before,'after':self.currency_snapshot(),'position':self.player()})
        return {'already_in_town':False,'hotkey_sent':True,'position':self.player(),'town_verified':True}

    def settle_return_ui(self,progress=lambda message:None):
        progress('已确认回城坐标，等待切图界面结束；仅处理已识别的挂机限制提示')
        deadline=time.monotonic()+10
        previous=getattr(self,'_dismissing_town_notice',False)
        self._dismissing_town_notice=True
        try:
            while time.monotonic()<deadline:
                self.check()
                stage=self.login_stage()
                if stage=='playing':return
                if stage=='message':
                    self._dismissing_town_notice=False
                    try:self.dismiss_town_hunt_notice()
                    finally:self._dismissing_town_notice=True
                elif stage in ('dead','login','server','character'):
                    raise GameSessionLost('回城后确认角色死亡或进入登录流程：'+stage)
                self.pause(.1)
            raise RuntimeError('回城后界面未就绪或提示内容未识别，未重复回城、未当作死亡重登')
        finally:self._dismissing_town_notice=previous

    def dismiss_town_hunt_notice(self):
        if getattr(self,'_dismissing_town_notice',False):return False
        if self.login_stage()!='message':return False
        matched=self.recovery_message_matches('town_hunt_forbidden')
        root_info=self.control_info(0x3d8,'Window_MsgDlg')
        # The user identified this return prompt; click its verified button only
        # during return handling. Never press Return, which can open game chat.
        button_fallback=(not matched and getattr(self,'_return_prompt_pending',False)
                        and self.in_mengzhong_return_area()
                        and root_info['visible'] and tuple(root_info['bounds'][2:])==(452,179))
        if not matched and not button_fallback:return False
        # This notice can appear before the veteran's actor has loaded.
        if not self.in_mengzhong_return_area():raise RuntimeError('挂机限制提示所在地图未核对，停止')
        if self.held_item() or self.sale_item() or self.inflight_item():raise RuntimeError('物品操作未结束，未关闭挂机限制提示')
        root=root_info['bounds']
        confirm=self.control_info(0x3dc,'Button_MsgDlgOk')
        if not confirm['visible']:raise RuntimeError('挂机限制提示确认按钮未显示')
        self._dismissing_town_notice=True
        try:
            # Re-read immediately before input; a vanished prompt is no action.
            latest=self.control_info(0x3d8,'Window_MsgDlg')
            if not latest['visible'] or self.login_stage()!='message':return False
            if latest['bounds']!=root_info['bounds']:raise RuntimeError('回城提示位置变化，未点击确认')
            self.click(button_center(root,confirm['bounds']))
            self.wait(lambda:self.login_stage()=='playing',timeout=3)
        finally:self._dismissing_town_notice=False
        if getattr(self,'_stats_enabled',False):
            self.write_stats({'event':'town_hunt_notice_dismissed','position':self.player(),'recovery_used':False})
        return True

    def press_return_hotkey(self):
        return self.press_named_hotkey(('盟重传送石','盟重回城石'),'return')

    def wait_mouse_modifiers_released(self):
        if any(self.u.GetAsyncKeyState(key)&0x8000 for key in (0x10,0x11,0x12)):
            try:self.wait_shortcut_modifiers_released()
            except RuntimeError as error:
                if '等待Shift/Ctrl/Alt松开超时' in str(error):
                    raise RuntimeError('等待Shift/Ctrl/Alt松开超时，未发送鼠标按下；请松开后继续') from error
                raise

    def wait_shortcut_modifiers_released(self,timeout=30):
        deadline=time.monotonic()+timeout
        released_at=None
        while time.monotonic()<deadline:
            self.check()
            if any(self.u.GetAsyncKeyState(key)&0x8000 for key in (0x10,0x11,0x12)):
                released_at=None
            else:
                if released_at is None:released_at=time.monotonic()
                if time.monotonic()-released_at>=.25:return
            self.pause(.05)
        raise RuntimeError('等待Shift/Ctrl/Alt松开超时，未发送快捷键；请松开后继续')

    def press_named_hotkey(self,names,purpose):
        self.check()
        choices=[slot for slot in self.shortcut_inventory() if slot['name'] in names and slot.get('raw_98',1)>0]
        if not choices:
            raise RuntimeError('快捷栏1—6没有盟重传送石，停止；不会使用随机传送石' if purpose=='return' else '快捷栏1—6没有随机传送石；不会使用随机卷')
        selected=choices[0];number=selected['key'];vk=0x30+number
        if not 1<=number<=6:raise RuntimeError('回城快捷键超出1—6')
        if self.u.IsIconic(self.hwnd):raise RuntimeError('游戏已最小化，未按回城键')
        self.wait_shortcut_modifiers_released()
        if self.login_stage()!='playing' or self.held_item() or self.sale_item() or self.inflight_item():
            raise RuntimeError('等待快捷键期间游戏状态变化，未发送快捷键')
        if isinstance(self,ForegroundSession):
            self.focus_game()
            key=Input();key.type=1;key.data.ki.vk=vk
            if self.u.SendInput(1,ctypes.byref(key),ctypes.sizeof(Input))!=1:raise RuntimeError('回城按键发送失败，未重试')
            try:self.pause(.08)
            finally:
                key.data.ki.flags=2
                self.u.SendInput(1,ctypes.byref(key),ctypes.sizeof(Input))
        else:
            lp=((number+1)<<16)|1
            try:
                self.begin_background_input()
                if not self.u.PostMessageW(self.hwnd,0x100,vk,lp):raise RuntimeError('后台快捷键发送失败')
                try:self.pause(.08)
                finally:self.u.PostMessageW(self.hwnd,0x101,vk,lp|0xc0000000)
            finally:self.clear_background_mouse()
        self.events.append({'input':'return_hotkey' if purpose=='return' else 'random_hotkey',
                            'key':str(number),'item':selected['name'],'retries':0})

    def maybe_random_hunt(self,progress=lambda message:None):
        from random_hunt import load_settings,RandomPolicy,recent_attempts
        settings=load_settings()
        if not settings.enabled:
            self._random_status={'reason':'无怪随机已关闭','used_hour':0}
            self._random_blocked_reason=None
            if hasattr(self,'_random_policy'):self._random_policy.empty_since=None
            return False
        if not hasattr(self,'_random_policy'):
            path=instance_context.runtime_root()/'outputs'/'挂机统计'/'events.jsonl'
            self._random_policy=RandomPolicy(recent_attempts(path))
        policy=self._random_policy;sampler=getattr(self,'_live_sampler',None)
        sample=sampler.latest if sampler is not None else None
        expected=getattr(self,'_hunting_header',None)
        allowed=bool(expected and self.login_stage()=='playing'
                     and not self.u.IsIconic(self.hwnd)
                     and self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)==expected
                     and not any(self.visible(key) for key in ('merchant','sell','bag'))
                     and not(self.held_item() or self.sale_item() or self.inflight_item()))
        if sample and (sample.get('game_pid')!=self.reader.pid or sample.get('radius')!=settings.radius
                       or sample.get('player_radius')!=settings.player_radius):sample=None
        status=policy.observe(sample,settings,allowed,(self.reader.pid,expected))
        if getattr(self,'_random_blocked_reason',None):
            status.update(ready=False,reason=self._random_blocked_reason)
        self._random_status=status
        if not status['ready']:return False
        # Confirm the stone before reserving a paid attempt. Never use scrolls.
        if not any(s['name']=='随机传送石' and s.get('raw_98',1)>0 for s in self.shortcut_inventory()):
            self._random_blocked_reason='随机石缺失或次数不足，已暂停随机';self._random_status['reason']=self._random_blocked_reason
            progress(self._random_blocked_reason);return False
        self.check();before=tuple(self.player());header=expected
        policy.reserve()
        self.write_stats({'event':'random_attempt','position':before,'radius':settings.radius,
                          'player_radius':settings.player_radius,'trigger_mode':settings.trigger_mode,
                          'trigger_seconds':settings.empty_seconds,'estimated_cost_yuanbao':settings.cost_per_use})
        progress('随机条件持续满足，按名称使用一次随机传送石；本小时第%d次' % len(policy.attempts))
        try:
            self.press_named_hotkey(('随机传送石',),'random')
            self.wait(lambda:tuple(self.player())!=before,timeout=5)
            if self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)!=header:
                raise RuntimeError('随机后地图发生变化')
            self.stable_player()
            self.write_stats({'event':'random_result','confirmed':True,'before':before,'position':self.player()})
            self._random_status={'ready':False,'reason':'随机落点已确认，重新观察怪物','used_hour':len(policy.attempts)}
            return True
        except GameSessionLost:raise
        except RuntimeError as error:
            self._random_blocked_reason='本次随机未确认，暂停随机且不重试：'+str(error)
            self._random_status={'ready':False,'reason':self._random_blocked_reason,'used_hour':len(policy.attempts)}
            self.write_stats({'event':'random_result','confirmed':False,'position':before,'error':str(error)})
            progress(self._random_blocked_reason);return False

    def monitor_bags(self,progress=lambda message:None,seconds=43200,auto_return=False):
        self.ensure_hero_available()
        started=time.monotonic();signature=None;transfers=0
        progress('开始监测双包；人物包达到39格后转英雄包，双包均达到39格（各预留1格）后'+('识别盟重传送石回城出售' if auto_return else '停止提示，不使用回城石'))
        while time.monotonic()-started<seconds:
            self.check()
            stage=self.login_stage()
            if stage!='playing':raise GameSessionLost('背包监测遇到死亡或掉线，已暂停；请恢复登录后继续')
            if not self.hero_ready():raise RuntimeError('英雄不可用，暂停监测；不会把未加载的英雄包当空包')
            bags=self.dual_bag_status()
            current=(bags['main_free'],bags['hero_free'])
            if current!=signature:
                progress('人物包空%d格，英雄包空%d格' % current);signature=current
            if bags['main_free']<=1:
                result=self.handle_full_bags()
                transfers+=sum(not row.get('skipped',False) for row in result['transfers'])
                if result['return_required']:
                    if auto_return:
                        returned=self.return_with_hotkey(progress)
                        sale=self.dual_sale_route(progress)
                        progress('本轮清包完成；自动进挂机地图尚未启用，停在城内')
                        return {'status':'sale_complete','transfers':transfers,'return':returned,'sale':sale,
                                'automatic_map_entry':False}
                    progress('双包均达到39格；当前为不消耗回城石的检查模式，已停止提示')
                    return {'status':'return_required','transfers':transfers,'bags':result['bags'],
                            'return_stone_used':False,'automatic_return_configured':False}
                if not result['bags']['main_free']:
                    raise RuntimeError('人物包已满且未释放空格，停止重复转包')
                self.close_panels()
            if auto_return and getattr(self,'_hunting_header',None):self.maybe_random_hunt(progress)
            self.pause(.5)
        return {'status':'monitor_timeout','seconds':round(time.monotonic()-started,1),'transfers':transfers}

    def hero_ready(self):
        actor=self.uint(self.uint(self.base+0x2bac2c))
        hero=self.uint(actor+0x358)
        return bool(hero and self.read(self.uint(self.base+0x2baccc),1)==b'\1'
                    and self.read(hero+0xac,1)==b'\0')

    def open_hero_bag(self):
        if not self.hero_ready():raise RuntimeError('英雄未召唤或不可用，未执行转包')
        root=self.control_info(0x7b4,'Window_HeroItemBag')
        if not root['visible']:
            group=self.control_info(0xfa4,'UI_Window_HeroGroup')
            button=self.control_info(0x7ac,'Button_HeroBag')
            if not group['visible']:raise RuntimeError('英雄操作栏未显示，无法定位背包按钮')
            self.click(button_center(group['bounds'],button['bounds']))
            self.wait(lambda:self.control_info(0x7b4,'Window_HeroItemBag')['visible'])
        return self.control_info(0x7b4,'Window_HeroItemBag')

    def take_hero_sale_items(self,allowed,progress=lambda message:None):
        if not set(allowed).issubset(CATEGORIES):raise RuntimeError('取回名单包含未授权装备')
        self.open_hero_bag()
        self.pause(.5)
        moved=[]
        for _ in range(40):
            if '' not in self.inventory():break
            current=self.hero_inventory()
            index=next((i for i,name in enumerate(current) if name in allowed),None)
            if index is None:break
            progress('从英雄包取回清单装备：第%d格 %s' % (index+1,current[index]))
            moved.append(self.transfer_bag_item('hero',index))
        return moved

    def bag_item_totals(self):
        from collections import Counter
        total=Counter()
        for raw in (self.read(self.base+0x2e1674,40*156),
                    self.read(self.uint(self.base+0x2ba544),40*156)):
            for index in range(40):
                record=raw[index*156:(index+1)*156];length=record[0]
                if length>20:raise RuntimeError('背包物品结构不符')
                if length:
                    name=record[1:1+length].decode('gb18030')
                    total[name]+=max(1,struct.unpack_from('<H',record,0x98)[0])
        return total

    def bag_identity_records(self):
        bags={}
        for key,pointer in [('main',self.base+0x2e1674),('hero',self.uint(self.base+0x2ba544))]:
            raw=self.read(pointer,40*156);rows=[]
            for i in range(40):
                record=raw[i*156:(i+1)*156];length=record[0]
                if length>20:raise RuntimeError('背包名称结构不符')
                rows.append({'name':record[1:1+length].decode('gb18030') if length else '',
                             'uid':record[0x90:0x98].hex() if length else ''})
            bags[key]=rows
        return bags

    def transfer_bag_item(self,source,index,allow_unchanged=False,allow_new_loot=False):
        from inventory_flow import validate_transfer
        if source not in ('main','hero'):raise RuntimeError('转包来源无效')
        if not self.hero_ready():raise RuntimeError('英雄未召唤或不可用，未执行转包')
        if self.held_item() or self.sale_item() or self.inflight_item():raise RuntimeError('物品操作未结束，未执行转包')
        if source=='hero':
            root=self.open_hero_bag();grid=self.control_info(0x7bc,'Grid_HeroItemBag')
            cols,rows,px,py=struct.unpack('<4i',self.read(grid['object']+0x398,16))
            scroll=self.uint(self.uint(self.parent+0x1090)+0x3e4)
            if not(1<=cols<=8 and 1<=rows<=8 and cols*rows==40 and not scroll):raise RuntimeError('英雄包网格未完整展开')
            point=(root['bounds'][0]+grid['bounds'][0]+(index%cols+.5)*px,
                   root['bounds'][1]+grid['bounds'][1]+(index//cols+.5)*py)
        else:
            if not self.visible('bag'):raise RuntimeError('人物背包未打开')
            point=grid_center(self.bounds('bag'),self.bounds('grid'),index)
        main=self.inventory();hero=self.hero_inventory()
        before=main if source=='main' else hero
        destination=hero if source=='main' else main
        if not 0<=index<40 or not before[index] or '' not in destination:raise RuntimeError('来源为空或目标背包已满')
        if source=='main' and before[index].startswith('魔血石'):
            raise RuntimeError('魔血石必须保留在人物包，未转入英雄包')
        quantities=self.bag_item_totals()
        identities=self.bag_identity_records() if allow_new_loot else None
        if identities is not None and identities[source][index]['name']!=before[index]:raise RuntimeError('来源格子已变化，未点击转包')
        self.ui_right_click(point)
        def confirmed():
            try:
                if identities is not None:
                    from inventory_flow import validate_live_transfer
                    validate_live_transfer(identities,self.bag_identity_records(),source,index)
                    return not self.inflight_item()
                validate_transfer(main,hero,self.inventory(),self.hero_inventory(),source,index)
                return not self.inflight_item() and self.bag_item_totals()==quantities
            except RuntimeError:return False
        try:self.wait(confirmed,timeout=4)
        except RuntimeError:
            self.check()
            if identities is not None and allow_unchanged:
                current=self.bag_identity_records();original=identities[source][index]
                if (current[source][index]==original and not self.held_item() and not self.sale_item() and not self.inflight_item()
                        and not any(row==original for row in current['hero' if source=='main' else 'main'])):
                    return {'name':before[index],'source':source,'source_slot':index+1,'verified':False,'skipped':True,'reason':'该件仍在来源格，未转移；允许其他格新增拾取'}
            if (allow_unchanged and self.hero_ready() and self.inventory()==main and self.hero_inventory()==hero
                    and not self.held_item() and not self.sale_item() and not self.inflight_item()
                    and self.bag_item_totals()==quantities):
                result={'name':before[index],'source':source,'source_slot':index+1,
                        'verified':False,'skipped':True,'reason':'转包后双包未变化，跳过该件且未重试'}
                self.events.append({'transfer':result});return result
            raise
        if identities is not None:
            from inventory_flow import validate_live_transfer
            target=validate_live_transfer(identities,self.bag_identity_records(),source,index)
        else:target=validate_transfer(main,hero,self.inventory(),self.hero_inventory(),source,index)
        result={'name':before[index],'source':source,'source_slot':index+1,'target_slot':target+1,'verified':True}
        self.events.append({'transfer':result})
        return result

    def hero_inventory(self):
        """Read bag slots only; hero worn equipment is a separate structure."""
        if not self.hero_ready():raise RuntimeError('英雄未召唤，背包数据尚未加载')
        pointer=self.uint(self.base+0x2ba544)
        capacity=self.uint(self.uint(self.base+0x2bb1e4))
        if capacity!=40 or pointer<0x10000:
            raise RuntimeError('英雄背包结构或容量发生变化，停止')
        rows=[]
        for index in range(capacity):
            raw=self.read(pointer+index*156,156)
            length=raw[0]
            if length>20:
                raise RuntimeError('英雄背包物品名称结构未验证')
            rows.append(raw[1:1+length].decode('gb18030') if length else '')
        return rows

    def dual_bag_status(self):
        main=self.inventory()
        hero=self.hero_inventory()
        if len(main)!=40:
            raise RuntimeError('主背包容量发生变化，停止')
        return {'main_items':main,'hero_items':hero,
                'main_free':main.count(''),'hero_free':hero.count(''),
                'both_full':all(main) and all(hero)}

    def state(self):
        result={'helper_pid':__import__('os').getpid(),'game_pid':self.reader.pid,
                'in_game':False,'inventory':[],'player':None,'player_draw':None,
                'held':'','sale_item':'','recent_inputs':self.events[-6:]}
        errors={}
        def sample(key,callback):
            try:result[key]=callback()
            except (RuntimeError,OSError,ValueError,struct.error) as error:errors[key]=str(error)
        sample('input_state',self.input_state)
        sample('sale_handler_layout',self.sale_handler_layout)
        sample('client_size',self.client_size)
        def current_map_identity():
            obj=self.uint(self.uint(self.base+0x2ba608))
            header=self.read(obj+4,52)
            return {'name':self.current_map_name(header),'header':header.hex(),'position':self.player()}
        sample('map_identity',current_map_identity)
        sample('visible',lambda:{k:self.visible(k) for k in ('merchant','sell','bag')})
        sample('bounds',lambda:{k:self.bounds(k) for k in ('merchant','sell','bag','grid')})
        try:
            actor=self.uint(self.uint(self.base+0x2bac2c))
            if actor>=0x10000:
                dead=self.read(actor+0xac,1)
                if dead in (b'\0',b'\1'):
                    result['in_game']=True;result['dead']=dead==b'\1'
                    sample('inventory',self.inventory);sample('player',self.player)
                    sample('held',self.held_item);sample('sale_item',self.sale_item)
                    sample('wallet',self.currency_snapshot)
                    def hero_status():
                        hero=self.uint(actor+0x358)
                        return {'ready':self.hero_ready(),'actor':hero,
                            'flag':self.read(self.uint(self.base+0x2baccc),1).hex(),
                            'dead':self.read(hero+0xac,1).hex() if hero>=0x10000 else None,
                            'group':self.control_info(0xfa4,'UI_Window_HeroGroup'),
                            'recall':self.control_info(0x7a4,'Button_RecallHero')}
                    sample('hero_status',hero_status)
                    sample('player_draw',lambda:struct.unpack('<2i',self.read(actor+0x17c,8)))
        except (RuntimeError,OSError,ValueError,struct.error) as error:errors['actor']=str(error)
        if errors:result['read_errors']=errors
        return result

    def input_state(self):
        class GuiInfo(ctypes.Structure):
            _fields_=[('size',w.DWORD),('flags',w.DWORD),('active',w.HWND),('focus',w.HWND),
                      ('capture',w.HWND),('menu',w.HWND),('moving',w.HWND),('caret',w.HWND),('rect',w.RECT)]
        info=GuiInfo();info.size=ctypes.sizeof(info)
        self.u.GetGUIThreadInfo.argtypes=[w.DWORD,ctypes.POINTER(GuiInfo)]
        thread=self.u.GetWindowThreadProcessId(self.hwnd,None)
        ok=self.u.GetGUIThreadInfo(thread,ctypes.byref(info))
        return {'foreground':int(self.u.GetForegroundWindow() or 0),'game_hwnd':int(self.hwnd),
                'capture':int(info.capture or 0) if ok else None,
                'left_pressed':bool(self.u.GetAsyncKeyState(1)&0x8000),'right_pressed':bool(self.u.GetAsyncKeyState(2)&0x8000)}

    def map_probe(self):
        detail={}
        try:
            obj=self.uint(self.uint(self.base+0x2ba608))
            detail={'object':obj,'header':self.read(obj,96).hex()}
            candidate=self.uint(obj+0x40)
            detail['candidate_cells']=self.read(candidate,256).hex() if candidate>0x10000 else None
            width,height=struct.unpack('<HH',self.read(obj+4,4))
            columns=self.uint(obj+0x48);x,y=self.player()
            cells=[]
            for ty in range(max(0,y-5),min(height,y+6)):
                row=[]
                for tx in range(max(0,x-5),min(width,x+6)):
                    row.append(struct.unpack('<H',self.read(self.uint(columns+tx*4)+ty*2,2))[0])
                cells.append(row)
            return {'size':[width,height],'origin':[max(0,x-5),max(0,y-5)],'cells':cells}
        except (RuntimeError,struct.error) as error:return dict(detail,error=str(error))

    def scene_actor_snapshot(self,list_offset=0x98):
        def require_class(address,name):
            vmt=self.uint(address)
            if not self.base<=vmt<self.base+0x300000:raise RuntimeError('场景对象类型不符')
            ptr=self.uint(vmt-44);length=self.read(ptr,1)[0]
            if not 1<=length<=80 or self.read(ptr+1,length).decode('ascii')!=name:
                raise RuntimeError('场景对象类型不符')
        for attempt in range(3):
            self.check()
            scene=self.uint(self.uint(self.base+0x2ba8fc));require_class(scene,'TPlayScene')
            actors=self.uint(scene+list_offset);require_class(actors,'TList')
            header=self.read(actors,16);_,items,count,capacity=struct.unpack('<4I',header)
            if not 0<=count<=capacity<=20000:raise RuntimeError('场景列表容量不符')
            pointers=struct.unpack('<%dI'%count,self.read(items,count*4)) if count else ()
            map_header=self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)
            rows=[]
            for index,address in enumerate(dict.fromkeys(pointers)):
                if index%16==0:self.check()
                rows.append((address,self.read(address,0x184)))
            if (self.read(actors,16)==header and self.uint(self.uint(self.base+0x2ba8fc))==scene
                    and self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)==map_header):
                return rows
            if attempt<2:self.pause(.05)
        raise RuntimeError('场景列表持续变化，停止定位')

    def scene_npcs(self,include_characters=False):
        expected=self.base+(0x24991c if include_characters else 0x249874)
        found=[];own=tuple(self.player())
        for address,raw in self.scene_actor_snapshot(0x98 if include_characters else 0x3c):
            if struct.unpack_from('<I',raw)[0]!=expected:continue
            ptr=struct.unpack_from('<I',raw,0xc)[0];length=self.uint(ptr-4)
            if not 1<=length<=60:raise RuntimeError('场景人物名称结构不符')
            name=self.read(ptr,length).decode('gb18030')
            xy=struct.unpack_from('<2i',raw,0x68);draw=struct.unpack_from('<2i',raw,0x17c)
            if not all(0<=value<10000 for value in xy) or not name or any(not c.isprintable() for c in name):
                raise RuntimeError('场景人物数据不符')
            if max(abs(xy[0]-own[0]),abs(xy[1]-own[1]))>45:continue
            if include_characters:
                if raw[0xac] not in (0,1):raise RuntimeError('场景人物死亡状态不符')
                if raw[0xac]==1:continue
            found.append({'address':address,'name':name,'map':xy,'draw':draw})
        return found

    def npcs(self,include_characters=False):
        return self.scene_npcs(include_characters)

    def heap_npcs(self, include_characters=False):
        """Locate typed NPC objects, never infer actors from rendered text alone."""
        needle = struct.pack('<I', self.base + (0x24991c if include_characters else 0x249874))
        found = []
        player_xy=self.player()
        started = time.monotonic()
        for base, size in self.reader.enumerate_regions():
            for offset in range(0, size, 1024 * 1024):
                self.check()
                if time.monotonic() - started > 20:
                    raise RuntimeError('NPC定位超时，未点击')
                try: data = self.read(base + offset, min(1024 * 1024 + 512, size-offset))
                except RuntimeError: continue
                pos = 0
                while True:
                    pos = data.find(needle, pos)
                    if pos < 0: break
                    address = base + offset + pos
                    pos += 4
                    if address % 4: continue
                    try:
                        nameptr = self.uint(address + 0xc)
                        length = self.uint(nameptr - 4)
                        if not 1 <= length <= 60: continue
                        name = self.read(nameptr, length).decode('gb18030')
                        xy = struct.unpack('<2i', self.read(address + 0x68, 8))
                        if max(abs(xy[0]-player_xy[0]),abs(xy[1]-player_xy[1]))>45:continue
                        draw = struct.unpack('<2i', self.read(address + 0x17c, 8))
                        if not all(0 <= v < 10000 for v in xy): continue
                        if not name or any(not c.isprintable() for c in name): continue
                        if any(n['address'] == address for n in found): continue
                        found.append({'address': address, 'name': name, 'map': xy, 'draw': draw})
                    except (RuntimeError, UnicodeError): pass
        # Reconnects can leave identical cached NPC objects. Collapse only exact
        # name/map/draw matches; conflicting positions remain ambiguous and stop.
        unique={}
        for npc in found:
            key=(npc['name'],tuple(npc['map']),tuple(npc['draw']))
            unique.setdefault(key,npc)
        return list(unique.values())

    def stable_player(self, timeout=8):
        previous = None
        count = 0
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.check()
            current = self.player()
            count = count + 1 if current == previous else 0
            if count >= 5: return current
            previous = current
            time.sleep(.15)
        raise RuntimeError('角色一直在移动，停止点击')

    def verified_npc_draw(self,npc):
        address=npc['address']
        if self.uint(address)!=self.base+0x249874:raise RuntimeError('NPC对象已失效')
        ptr=self.uint(address+0xc);length=self.uint(ptr-4)
        if not 1<=length<=60 or self.read(ptr,length).decode('gb18030')!=npc['name']:
            raise RuntimeError('NPC身份改变')
        if tuple(struct.unpack('<2i',self.read(address+0x68,8)))!=tuple(npc['map']):
            raise RuntimeError('NPC地图位置已改变')
        return struct.unpack('<2i',self.read(address+0x17c,8))

    def approach_shop_npc(self,npc,max_moves=6):
        from map_navigation import npc_approach_step
        allowed={'铁匠铺老板','服装店老板','首饰店老板','苍月老兵','项链店老板','孤岛挑战',
                 '戒指店老板','手镯店老板','张家布衣老板','老张头盔店'}
        if npc['name'] not in allowed:raise RuntimeError('此NPC的自动靠近尚未校准，未移动')
        if self.held_item() or self.sale_item() or self.inflight_item():
            raise RuntimeError('物品操作未结束，未为NPC移动')
        if self.visible('merchant') or self.visible('bag') or self.visible('sell'):
            raise RuntimeError('窗口尚未关闭，未为NPC移动')
        obj=self.uint(self.uint(self.base+0x2ba608));header=self.read(obj+4,52)
        tilemap=self.navigation_map(header);stuck=0
        for attempt in range(max_moves+1):
            self.check()
            if self.login_stage()!='playing':raise GameSessionLost('靠近NPC时角色死亡或掉线')
            if self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)!=header:
                raise RuntimeError('靠近NPC时地图变化，停止移动')
            npc=self.unique_npc(npc['name'],tuple(npc['map']))
            point=self.verified_npc_draw(npc)
            if self.npc_click_point(point) is not None:return npc
            if attempt==max_moves:break
            current=tuple(self.stable_player())
            own=self.uint(self.uint(self.base+0x2bac2c))
            blocked={tuple(row['map']) for row in self.npcs()+self.npcs(True) if row['address']!=own}
            target=npc_approach_step(tilemap,current,npc['map'],blocked)
            self.walk_tile(target,max_steps=6,allow_transition=False,run_enabled=True,run_only=True)
            after=tuple(self.stable_player())
            if getattr(self,'_stats_enabled',False):
                self.write_stats({'event':'npc_approach','npc':npc['name'],'npc_map':npc['map'],
                                  'map_file':tilemap.name,'from':current,'to':after,'expected':target,
                                  'draw_before':point,'attempt':attempt+1})
            stuck=stuck+1 if after==current else 0
            if stuck>=2:raise RuntimeError('靠近NPC连续两次未移动，停止重试')
        raise RuntimeError('靠近NPC达到有限次数后仍不可点击，停止')

    def click_npc_actor(self,point):
        previous=getattr(self,'_opening_npc_actor',False)
        self._opening_npc_actor=True
        try:return self.click(point)
        finally:self._opening_npc_actor=previous

    def open_npc(self, npc):
        veteran=npc['name']=='盟重老兵' and tuple(npc['map'])==(320,320)
        if veteran:self.approach_veteran_running(npc)
        self.stable_player()
        def sample():return self.verified_npc_draw(npc)
        point=sample()
        if not veteran and self.npc_click_point(point) is None:
            npc=self.approach_shop_npc(npc)
            self.stable_player();point=sample()
        time.sleep(.25)
        if sample()!=point:raise RuntimeError('NPC画面位置尚未稳定')
        width, height = self.client_size()
        target=(self.veteran_click_point(point) if npc['name']=='盟重老兵' and tuple(npc['map'])==(320,320)
                else self.npc_click_point(point))
        if target is None:
            raise RuntimeError('NPC靠近后仍不在可点击视野内，停止')
        if self.visible('merchant'):
            raise RuntimeError('已有NPC菜单，请先关闭后重试')
        standing=tuple(self.player())
        if getattr(self,'_stats_enabled',False):
            self.write_stats({'event':'npc_open_attempt','npc':npc['name'],'npc_map':npc['map'],
                              'position':standing,'draw':point,'click':target,'attempt':1})
        self.click_npc_actor(target)
        self.events[-1]['npc']=npc['name']
        try:self.wait(lambda: self.visible('merchant'), timeout=3)
        except RuntimeError:
            self.check()
            if self.visible('merchant'):
                self.active_merchant=npc['name'];return
            if self.login_stage()!='playing' or tuple(self.player())!=standing or sample()!=point:raise
            # Retry the verified actor's body anchor, not the ground below its feet.
            alternate=(point[0],point[1])
            if alternate==target or not self.npc_world_point_clear(alternate):raise
            if self.hero_covers((alternate[0]-8,alternate[1]-8,alternate[0]+8,alternate[1]+8)):raise
            if getattr(self,'_stats_enabled',False):
                self.write_stats({'event':'npc_open_attempt','npc':npc['name'],'npc_map':npc['map'],
                                  'position':standing,'draw':point,'click':alternate,'attempt':2})
            self.click_npc_actor(alternate)
            self.events[-1]['npc']=npc['name']
            self.events[-1]['npc_retry']='same_verified_actor_body_anchor_once'
            try:self.wait(lambda:self.visible('merchant'),timeout=3)
            except RuntimeError as error:
                if str(error)!='状态确认超时，停止；不会重复点击确定':raise
                raise NpcDialogNotOpened('已核对NPC两次点击后菜单仍未打开') from error
        self.active_merchant = npc['name']
        if getattr(self,'_stats_enabled',False):
            self.write_stats({'event':'npc_open_confirmed','npc':npc['name'],'position':self.player()})

    def veteran_click_point(self,draw):
        # A visible, unobstructed body hit point is sufficient, even at the edge.
        return self.npc_click_point(draw)

    def npc_world_point_clear(self,point):
        # Logical client pixels: reserve the whole fixed left-menu column,
        # including a margin. This is a conservative exclusion, not a measured control bound.
        width,height=self.client_size()
        return 128<=point[0]<=width-32 and 40<=point[1]<height-240

    def npc_click_point(self,draw):
        width,height=self.client_size()
        if not(32<=draw[0]<=width-32):return None
        for offset in (24,40,56,64):
            point=(draw[0],draw[1]+offset)
            if not self.npc_world_point_clear(point):continue
            if self.hero_covers((point[0]-8,point[1]-8,point[0]+8,point[1]+8)):continue
            return point
        return None

    def resource(self, name):
        directory = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
        return directory / 'shop-layout' / name

    def profile(self):
        actual=self.client_size()
        path=self.resource('%dx%d.json' % actual)
        fallback=not path.is_file()
        if fallback:
            self.validate_city_ui_layout()
            path=self.resource('1680x1050.json')
        profile = json.loads(path.read_text(encoding='utf8'))
        if fallback:
            profile['reference_client_size']=profile['client_size']
            profile['client_size']=list(actual)
            profile['coordinate_basis']='live_control_origin_and_verified_size'
        if tuple(profile['client_size']) != self.client_size():
            actual = self.client_size()
            raise RuntimeError('游戏逻辑客户区为%d×%d，当前只校准1024×768（已排除Windows缩放影响）' % actual)
        if self.visible('merchant') and tuple(profile['merchant_size']) != self.bounds('merchant')[2:]:
            raise RuntimeError('NPC菜单布局变化，需要重新校准')
        return profile

    def validate_city_ui_layout(self):
        width,height=self.client_size()
        if width<1024 or height<768:raise RuntimeError('当前客户区过小，城内路线未执行')
        # Coordinates inside these controls remain in game UI pixels. Do not
        # scale a recorded screen point when the client window changes size.
        if tuple(self.bounds('bag')[2:])!=(352,295) or tuple(self.bounds('grid')[2:])!=(288,160):
            raise RuntimeError('背包或网格尺寸已变化，需要重新校准；未移动或出售')
        return {'client_size':[width,height],'coordinate_basis':'live_controls'}

    def capture_menu_frame(self, name):
        # A blank window capture is not evidence that a menu link is absent.
        # Retry capture only: never focus the window or click guessed coordinates.
        for attempt in range(1, 4):
            if not self.visible('merchant'): return None
            capture = self.capture_client()
            if not self.visible('merchant'): return None
            extrema = capture.getextrema()
            blank = all(high-low <= 3 for low, high in extrema)
            if getattr(self, '_stats_enabled', False) and (blank or attempt > 1):
                self.write_stats({'event': 'menu_capture', 'menu': name,
                                  'attempt': attempt, 'blank': blank,
                                  'size': list(capture.size), 'extrema': extrema})
            if not blank: return capture
            if attempt < 3: self.pause(.25)
        raise RuntimeError('商人菜单截图连续3次为空白，已安全停止；未点击菜单，请检查游戏窗口渲染后再接续')

    def test_fixed_veteran_transfer(self, destination, progress=lambda message: None):
        """Fresh NPC sequence, fixed relative clicks, then map/NPC confirmation."""
        targets = {'weapon': ('0159.map', '铁匠铺老板', (5,9)),
                   'cangyue': ('5.map', '苍月老兵', (139,333))}
        if destination not in targets: raise RuntimeError('未知传送测试目标')
        if self.login_stage() != 'playing': raise RuntimeError('当前状态未确认正常，未传送')
        if self.held_item() or self.sale_item() or self.inflight_item():
            raise RuntimeError('存在手持、待售或传输物品，未传送')
        target_map, npc_name, npc_tile = targets[destination]
        before = self.state()
        current_map = before.get('map_identity', {}).get('name', '').lower()
        if current_map == target_map:
            self.unique_npc(npc_name, npc_tile)
            return {'destination': destination, 'already_at_destination': True,
                    'menu_clicks': 0, 'entry_clicks': 0, 'fee_gold': 0}
        if current_map != '3.map': raise RuntimeError('本测试从土城开始；请先自行回到土城')
        wallet_before = self.currency_snapshot()
        if destination == 'cangyue' and (wallet_before.get('gold') is None or wallet_before['gold'] < 2000):
            raise RuntimeError('无法确认至少2000金币，未点击苍月传送')
        self.open_mengzhong_veteran(progress)
        self.profile()
        initial_bounds = self.bounds('merchant')
        if self.active_merchant != '盟重老兵' or not self.visible('merchant'):
            raise RuntimeError('未确认新打开的老兵窗口，未点击')
        position = tuple(self.player())
        points = []
        def click_link(name):
            self.check()
            if (self.login_stage() != 'playing' or not self.visible('merchant')
                    or self.bounds('merchant') != initial_bounds or tuple(self.player()) != position):
                raise RuntimeError('老兵窗口或人物状态变化，停止固定点击')
            entry = self.profile()['menus'][name]
            point = (initial_bounds[0]+entry['point'][0], initial_bounds[1]+entry['point'][1])
            if self.hero_covers((point[0]-3,point[1]-3,point[0]+3,point[1]+3)):
                raise RuntimeError('英雄头像遮挡菜单，未点击')
            self.click(point)
            points.append({'menu': name, 'point': point})
        if destination == 'weapon':
            progress('固定位置点击商店传送一次')
            click_link('shop_transfer')
            self.pause(.8)
        progress('固定位置传送'+('武器店' if destination == 'weapon' else '苍月岛（2000金币）'))
        click_link('weapon_transfer' if destination == 'weapon' else 'cangyue_transfer')
        self.wait(lambda: not self.visible('merchant') and
                  self.state().get('map_identity', {}).get('name', '').lower() == target_map, timeout=8)
        self.stable_player()
        after = self.state()
        if after.get('map_identity', {}).get('name', '').lower() != target_map:
            raise RuntimeError('点击后未确认目标地图，保留现场；不重复传送')
        self.unique_npc(npc_name, npc_tile)
        wallet_after = self.currency_snapshot()
        report = {'destination': destination, 'target_map': target_map, 'verified_npc': npc_name,
                  'points': points, 'menu_clicks': len(points), 'image_matching': False,
                  'wallet_before': wallet_before, 'wallet_after': wallet_after,
                  'gold_change': (wallet_after['gold']-wallet_before['gold']
                                  if wallet_after.get('gold') is not None and wallet_before.get('gold') is not None else None),
                  'position': after.get('player'), 'entry_clicks': 0, 'unattended_cycle': False}
        self.write_stats({'event': 'fixed_veteran_transfer_test', **report})
        return report

    def test_veteran_fixed_menu(self, progress=lambda message: None):
        """One fresh veteran link click; no destination, purchase or entry click."""
        if self.login_stage() != 'playing': raise RuntimeError('当前不在正常游戏状态，未测试')
        if self.held_item() or self.sale_item() or self.inflight_item():
            raise RuntimeError('存在手持、待售或传输物品，未测试')
        before = self.state()
        if before.get('map_identity', {}).get('name', '').lower() != '3.map':
            raise RuntimeError('未确认土城地图，未测试')
        self.open_mengzhong_veteran(progress)
        if self.active_merchant != '盟重老兵' or not self.visible('merchant'):
            raise RuntimeError('未确认新打开的老兵窗口，未点击菜单')
        profile = self.profile()
        bounds = self.bounds('merchant')
        point = (bounds[0]+profile['menus']['shop_transfer']['point'][0],
                 bounds[1]+profile['menus']['shop_transfer']['point'][1])
        if self.hero_covers((point[0]-3,point[1]-3,point[0]+3,point[1]+3)):
            raise RuntimeError('英雄头像遮挡菜单，未点击')
        if not self.visible('merchant') or self.bounds('merchant') != bounds:
            raise RuntimeError('老兵窗口已变化，未点击菜单')
        progress('内存确认新打开的老兵窗口；固定位置点击商店传送一次，不预先截图识别')
        self.click(point)
        self.pause(.8)
        # Post-click evidence only; failure must never cause a second click.
        matched = self.menu_matches('weapon_transfer')
        report = {'test': 'veteran_fixed_menu', 'point': point,
                  'preclick_image_matching': False, 'menu_clicks': 1,
                  'postclick_weapon_menu_verified': matched,
                  'position_before': before.get('player'), 'position_after': self.player(),
                  'destination_clicks': 0, 'entry_clicks': 0}
        self.write_stats({'event': 'veteran_fixed_menu_test', **report})
        if not matched: raise RuntimeError('固定菜单已点击一次，但未确认传送子菜单；保留现场，不重复点击')
        return report

    def menu_matches(self, name):
        from PIL import Image
        if not self.visible('merchant'): return False
        entry = self.profile()['menus'][name]
        capture = self.capture_menu_frame(name)
        if capture is None: return False
        left, top = self.bounds('merchant')[:2]
        box = entry['box']
        actual = capture.crop((left+box[0], top+box[1], left+box[2], top+box[3]))
        expected = Image.open(self.resource(entry['template'])).convert('RGB')
        def yellow(pixel):
            r, g, b = pixel
            return r > 175 and g > 150 and b < 115
        a, b = list(map(yellow, actual.get_flattened_data())), list(map(yellow, expected.get_flattened_data()))
        return text_masks_match(b,a,expected.size)

    def menu_click(self, name):
        self.wait(lambda: self.menu_matches(name), timeout=3)
        entry = self.profile()['menus'][name]
        left, top = self.bounds('merchant')[:2]
        point=(left+entry['point'][0],top+entry['point'][1])
        if self.hero_covers((point[0]-3,point[1]-3,point[0]+3,point[1]+3)):
            raise RuntimeError('英雄头像遮挡商人菜单，请将头像移到左下再开始')
        self.click(point)

    def teleport_weapon_sale(self, item=None, progress=lambda message: None):
        started = time.monotonic()
        self.profile()
        candidates = [n for n in self.inventory() if n in WEAPONS] if item is None else [n for n in self.inventory() if n == item]
        if not candidates: raise RuntimeError('背包没有本次清单中的武器，没有执行点击')
        if self.held_item() or self.sale_item(): raise RuntimeError('鼠标或出售框已有物品')
        if self.visible('sell'):
            return self.sell_all_weapons(progress) if item is None else self.submit_one(item)
        progress('正在定位场景NPC…')
        actors = self.npcs()
        shop = [n for n in actors if n['name'] == '铁匠铺老板']
        if not shop:
            veterans = [n for n in actors if n['name'] == '盟重老兵' and tuple(n['map']) == (320, 320)]
            if len(veterans) != 1:self.locate_mengzhong_veteran(progress)
            if not self.visible('merchant'):
                progress('点击盟重老兵…')
                self.open_mengzhong_veteran(progress)
            if not self.menu_matches('weapon_transfer'):
                progress('打开商店传送菜单…')
                self.menu_click('shop_transfer')
            # Some server menus perform the transfer on this first choice.
            # Confirm the live shop NPC before attempting another menu click.
            self.wait(lambda:self.menu_matches('weapon_transfer') or
                      (not self.visible('merchant') and any(n['name']=='铁匠铺老板' for n in self.npcs())),timeout=6)
            shop = [n for n in self.npcs() if n['name']=='铁匠铺老板']
            if not shop:
                progress('传送盟重武器店…')
                before = self.player()
                self.menu_click('weapon_transfer')
                self.wait(lambda: not self.visible('merchant') and self.player() != before, timeout=6)
            self.stable_player()
            shop = [n for n in self.npcs() if n['name'] == '铁匠铺老板']
        if len(shop) != 1: raise RuntimeError('未唯一找到铁匠铺老板，停止')
        if not self.visible('merchant'):
            progress('点击铁匠铺老板…')
            self.open_npc(shop[0])
        progress('检查武器商店菜单…')
        self.menu_click('sell_weapon')
        self.wait(lambda: self.visible('sell') and self.visible('bag'))
        progress('核对物品并提交一件出售…')
        result = self.sell_all_weapons(progress) if item is None else self.submit_one(item)
        result['workflow_seconds'] = round(time.monotonic() - started, 3)
        result['input_method'] = '后台窗口鼠标消息；未激活游戏，未写入内存'
        return result

    def sell_all_weapons(self, progress=lambda message: None):
        return self.sell_category('武器', progress)

    def sell_category(self, category, progress=lambda message: None, merchant_name=None):
        if category not in set(CATEGORIES.values()): raise RuntimeError('未知装备类别')
        if merchant_name is not None and getattr(self,'active_merchant',None)!=merchant_name:
            raise RuntimeError('当前商人身份尚未核对')
        self.arrange_sale_layout()
        allowed={name for name,kind in CATEGORIES.items() if kind==category}
        started = time.monotonic()
        initial = self.inventory()
        count = sum(name in allowed for name in initial)
        if not count: return {'status': '没有清单中的'+category, 'submitted': [], 'count': 0}
        if self.inflight_item(): raise RuntimeError('上一笔操作尚未返回，暂不开始出售')
        sold = []
        expected = initial.copy()
        for _ in range(count):
            self.check()
            current = self.inventory()
            if current != expected: raise RuntimeError('背包在批量出售间发生变化，已停止')
            index = next(i for i, name in enumerate(current) if name in allowed)
            name = current[index]
            wallet_before=self.currency_snapshot() if getattr(self,'_stats_enabled',False) else None
            progress('出售 %d/%d：第%d格 %s' % (len(sold)+1, count, index+1, name))
            result = self.submit_one(name, category=category)
            expected[index] = ''
            try:self.wait(lambda: not self.inflight_item(), timeout=4)
            except GameSessionLost:raise
            except RuntimeError:
                self.check()
                self.refresh_pending_sale(name,progress)
            self.pause(.45)
            if self.inventory() != expected or self.held_item() or self.sale_item():
                raise RuntimeError('出售后物品状态异常，停止后续出售')
            if wallet_before is not None:
                wallet_after=self.currency_snapshot()
                result['gold_before']=wallet_before['gold'];result['gold_after']=wallet_after['gold']
                result['gold_change']=wallet_after['gold']-wallet_before['gold'] if None not in (wallet_after['gold'],wallet_before['gold']) else None
                result['yuanbao_after']=wallet_after['yuanbao']
            sold.append(result)
            self.sales.append(result)
            if wallet_before is not None:self.write_stats({'event':'sale_item','round_id':getattr(self,'_stats_round_id',None),**result})
        if getattr(self,'_selling_both_bags',False) and any(name in allowed for name in self.hero_inventory()):
            merchant=getattr(self,'active_merchant',None)
            menu={'铁匠铺老板':'sell_weapon','服装店老板':'cangyue_sell_clothes',
                  '首饰店老板':'cangyue_sell_jewelry'}.get(merchant)
            if not menu:raise RuntimeError('未校准当前商人的双包续卖菜单')
            self.close_panels()
            self.take_hero_sale_items(allowed,progress)
            self.close_panels()
            if merchant in {'服装店老板','首饰店老板'}:self.cangyue_sale_stand()
            if merchant in {'服装店老板','首饰店老板'}:
                self.open_cangyue_fixed_sale(merchant,progress)
            else:
                self.open_npc(self.unique_npc(merchant));self.menu_click(menu)
            self.wait(lambda:self.visible('sell') and self.visible('bag'))
            extra=self.sell_category(category,progress,merchant_name=merchant)
            if not extra['count']:raise RuntimeError('英雄装备取回后没有完成出售')
            sold.extend(extra['submitted'])
        return {'status': '已逐件提交并检查返回状态，请核对金币提示', 'submitted': sold,
                'count': len(sold), 'seconds': round(time.monotonic()-started, 3),
                'remaining_plan': sale_plan(self.inventory())}

    def refresh_pending_sale(self,item,progress=lambda message:None):
        if item not in CATEGORIES or self.inflight_item()!=item:raise RuntimeError('待确认物品不匹配，未刷新背包')
        if self.held_item() or self.sale_item():raise RuntimeError('手持或待售物品未清空，未刷新背包')
        if self.accept_returned_pending(item):
            return {'refreshed':False,'item':item,'returned_to_bag':True,'resubmitted':False}
        root=self.control_info(0x488,'Window_ItemBag')
        button=self.control_info(0xd0c,'Button_ReGetBagItem')
        if not root['visible'] or not button['visible']:raise RuntimeError('背包刷新按钮未显示，停止')
        x,y,bw,bh=button['bounds'];_,_,rw,rh=root['bounds']
        if not(0<=x<x+bw<=rw and 0<=y<y+bh<=rh):raise RuntimeError('背包刷新按钮位置不符')
        self.log_sale_probe('before_pending_refresh',item)
        progress('成交传输确认超时，按已核对的刷新包裹按钮一次；不重复提交出售')
        BackgroundSession.background_mouse(self,button_center(root['bounds'],button['bounds']),
            'left',track_movement=False,dpi_scaled=True,button_hold=.15,restore_client_focus=True)
        try:self.wait(lambda:not self.inflight_item(),timeout=5)
        except GameSessionLost:raise
        except RuntimeError:
            self.check()
            if not self.accept_returned_pending(item):raise
        if self.held_item() or self.sale_item():raise RuntimeError('刷新后物品状态不稳定，停止')
        self.log_sale_probe('after_pending_refresh',item)
        return {'refreshed':True,'inflight':'','item':item,'resubmitted':False}

    def log_sale_probe(self, phase, item=None, **extra):
        # Diagnostics must never turn a completed sale into a failed command.
        if not hasattr(self,'base'):return  # Unit-test doubles must not pollute live diagnostics.
        try:
            row={'time':__import__('datetime').datetime.now().astimezone().isoformat(),
                 'event':'sale_probe','phase':phase,'item':item,**extra}
            for key,callback in [('position',self.player),('inventory',self.inventory),
                                 ('held',self.held_item),('sale_item',self.sale_item),
                                 ('inflight',self.inflight_item),('wallet',self.currency_snapshot)]:
                try:row[key]=callback()
                except Exception as error:row[key+'_read_error']=str(error)
            row['controls']={}
            for key in ('bag','grid','sell','spot','ok'):
                offset,name=CONTROLS[key]
                try:row['controls'][key]={'cached_object':self.controls.get(key),**self.control_info(offset,name)}
                except Exception as error:row['controls'][key]={'error':str(error)}
            row['recent_inputs']=self.events[-6:]
            path=instance_context.runtime_root()/'outputs'/'挂机统计'/'出售诊断.jsonl'
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('a',encoding='utf8') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
        except Exception as error:
            self.events.append({'sale_diagnostic_error':str(error)})

    def submit_one(self, item, start='sale', npc=None, category='武器'):
        self.log_sale_probe('begin',item,category=category)
        try:
            result=self._submit_one_logged(item,start,npc,category)
        except Exception as error:
            self.log_sale_probe('failed',item,error=str(error))
            raise
        self.log_sale_probe('complete',item,result=result)
        return result

    def sale_handler_layout(self):
        # Compare the relevant historical instructions with this client's code;
        # a historical decompilation is never proof of a current version match.
        signatures={0x170610:bytes.fromhex('a130aa6b0080380075'),
                    0x170843:bytes.fromhex('a130aa6b008b15b0a26b008bf08d7a04b927000000f3a5a130aa6b00c60000')}
        matched={hex(rva):self.read(self.base+rva,len(code))==code for rva,code in signatures.items()}
        return {'verified':all(matched.values()),'signatures':matched,'record_bytes':156,
                'basis':'historical_handler_compared_to_current_code'}

    def sale_item_identity(self,location,index=None):
        from sale_state import item_identity
        if location=='main':
            if not isinstance(index,int) or not 0<=index<40:raise RuntimeError('背包格子无效')
            address=self.base+0x2e1674+index*156
        elif location=='held':address=self.uint(self.base+0x2bb524)+4
        elif location=='sale':address=self.uint(self.base+0x2baa30)
        else:raise RuntimeError('未知物品位置')
        return item_identity(self.read(address,156))

    def sale_bag_identities(self):
        from sale_state import item_identity
        raw=self.read(self.base+0x2e1674,40*156)
        return [item_identity(raw[i*156:(i+1)*156]) for i in range(40)]

    def verify_stalled_sale(self,item,context):
        from sale_state import require_identity
        self.check()
        if (self.login_stage()!='playing' or self.held_item() or self.inflight_item()
                or self.sale_item()!=item or not self.visible('sell') or not self.visible('bag')):
            raise RuntimeError('补确认现场已变化，未重试或小退')
        if not self.sale_handler_layout()['verified']:raise RuntimeError('出售版本校验失败，未补确认')
        require_identity(self.sale_item_identity('sale'),context['identity'],'补确认前')
        if self.inventory()!=context['inventory'] or self.sale_bag_identities()!=context['bag_ids']:
            raise RuntimeError('补确认前背包标识变化，停止')
        wallet=self.currency_snapshot()
        if wallet.get('gold') is None or wallet!=context['wallet']:
            raise RuntimeError('补确认前金币或元宝变化，未重试')
        header=self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)
        if header!=context['header']:raise RuntimeError('补确认前地图变化，停止')
        merchant=context['merchant']
        locations={'铁匠铺老板':(5,9),'服装店老板':(147,328),'首饰店老板':(155,339)}
        if merchant not in locations or getattr(self,'active_merchant',None)!=merchant:
            raise RuntimeError('补确认商人未核对，停止')
        self.unique_npc(merchant,locations[merchant])

    def withdraw_verified_sale(self,item,context):
        from sale_state import require_identity
        self.verify_stalled_sale(item,context)
        before=self.inventory();index=before.index('')
        root=self.control_info(0x638,'Window_SellDlg')
        spot=self.control_info(0x644,'Button_SellDlgSpot')
        if not root['visible'] or not spot['visible']:raise RuntimeError('取回待售装备控件不可用，未小退')
        self.log_sale_probe('withdraw_before_relogin',item)
        self.click(button_center(root['bounds'],spot['bounds']))
        self.wait(lambda:self.held_item()==item and not self.sale_item() and not self.inflight_item(),timeout=4)
        require_identity(self.sale_item_identity('held'),context['identity'],'取回待售装备')
        self.click(grid_center(self.bounds('bag'),self.bounds('grid'),index))
        expected=before.copy();expected[index]=item
        self.wait(lambda:self.inventory()==expected and not(self.held_item() or self.sale_item() or self.inflight_item()),timeout=4)
        ids=context['bag_ids'].copy();ids[index]=context['identity']
        if self.sale_bag_identities()!=ids:raise RuntimeError('待售装备归位标识不符，未小退')
        self.log_sale_probe('withdraw_verified_before_relogin',item,slot=index+1)

    def wait_sale_settled(self,item,expected,retry_context=None):
        # The native handler clears the sale slot after copying it into the
        # pending record. Slot-empty alone never establishes a finished sale.
        try:self.wait(lambda:not self.sale_item() and not self.inflight_item(),timeout=4)
        except GameSessionLost:raise
        except RuntimeError:
            self.check()
            if self.sale_item():
                if retry_context is None:raise
                self.verify_stalled_sale(item,retry_context)
                self.log_sale_probe('retry_confirm_verified_once',item)
                root=self.control_info(0x638,'Window_SellDlg')
                ok=self.control_info(0x640,'Button_SellDlgOk')
                if not root['visible'] or not ok['visible']:raise RuntimeError('补确认按钮未显示，停止')
                self.click(button_center(root['bounds'],ok['bounds']))
                try:self.wait(lambda:not self.sale_item() and not self.inflight_item(),timeout=4)
                except GameSessionLost:raise
                except RuntimeError:
                    self.check()
                    if self.sale_item():
                        self.verify_stalled_sale(item,retry_context)
                        raise SaleConfirmationStalled(item,retry_context)
                    self.refresh_pending_sale(item)
            else:self.refresh_pending_sale(item)
        if self.inventory()!=expected or self.held_item() or self.sale_item() or self.inflight_item():
            raise RuntimeError('出售未确认或物品已退回背包，停止；不会重复提交')

    def _submit_one_logged(self, item, start='sale', npc=None, category='武器'):
        if hasattr(self,'reader') and category in ('项链','手镯','戒指','衣服'):
            policy_path=Path(__file__).with_name('item-protection.json')
            override=instance_context.runtime_root()/'outputs'/'item-protection.json'
            if instance_context.slot()=='2' and override.exists():policy_path=override
            policy=json.loads(policy_path.read_text(encoding='utf8'))
            if policy.get('enabled') and not policy.get('attribute_reader_verified'):
                raise RuntimeError('极品保护已启用，装备属性尚未验证，禁止出售：'+item)
        if CATEGORIES.get(item)!=category:
            raise RuntimeError('装备不在对应部位的出售清单中')
        before = self.inventory()
        if item not in before:
            raise RuntimeError('背包没有指定装备')
        if self.held_item() or self.sale_item() or self.inflight_item():
            raise RuntimeError('鼠标、出售框或传输中已有物品，停止')
        started = time.monotonic()
        if start == 'npc':
            if npc is None: raise RuntimeError('缺少NPC定位')
            self.click(npc)
            self.wait(lambda: self.visible('merchant'))
        if start in ('npc', 'menu'):
            if not self.visible('merchant'): raise RuntimeError('NPC菜单未打开')
            root = self.bounds('merchant')
            self.click((root[0] + 27, root[1] + 64))
            self.wait(lambda: self.visible('sell') and self.visible('bag'))
        if not self.visible('sell') or not self.visible('bag'):
            raise RuntimeError('出售窗口或背包未打开')
        if self.inventory() != before:
            raise RuntimeError('流程开始后背包改变，停止')
        index = before.index(item)
        identities=None
        if hasattr(self,'reader') and hasattr(self,'base'):
            if not self.sale_handler_layout()['verified']:
                raise RuntimeError('当前出售处理代码与已分析版本不符，未拿起或出售')
            identities=self.sale_bag_identities()
            if [row['name'] for row in identities]!=before:raise RuntimeError('拿起前背包快照变化，未点击')
            target=identities[index]
            if sum(row==target for row in identities)!=1:raise RuntimeError('待售装备标识不唯一，未点击')
        self.log_sale_probe('before_pickup',item,slot=index+1)
        self.click(grid_center(self.bounds('bag'), self.bounds('grid'), index))
        self.wait(lambda: self.held_item() == item and self.inventory()[index] == '')
        if identities is not None:
            from sale_state import require_identity
            require_identity(self.sale_item_identity('held'),target,'拿起后')
        self.log_sale_probe('held_confirmed',item,slot=index+1)
        self.click(button_center(self.bounds('sell'), self.bounds('spot')))
        self.wait(lambda: not self.held_item() and self.sale_item() == item)
        self.log_sale_probe('sale_slot_confirmed',item,slot=index+1)
        expected = before.copy()
        expected[index] = ''
        if self.inventory() != expected:
            raise RuntimeError('其他背包格子发生变化，停止确认')
        if identities is not None:
            require_identity(self.sale_item_identity('sale'),target,'确认前')
        self.log_sale_probe('before_submit_once',item,slot=index+1)
        retry_context=None
        if identities is not None and getattr(self,'active_merchant',None) in {'铁匠铺老板','服装店老板','首饰店老板'}:
            retry_context={'identity':target,'inventory':expected.copy(),'bag_ids':self.sale_bag_identities(),
                           'wallet':self.currency_snapshot(),'merchant':self.active_merchant,
                           'header':self.read(self.uint(self.uint(self.base+0x2ba608))+4,52)}
        self.click(button_center(self.bounds('sell'), self.bounds('ok')))
        self.log_sale_probe('submit_sent',item,slot=index+1)
        self.wait_sale_settled(item,expected,retry_context=retry_context)
        if identities is not None:
            from sale_state import validate_sale_removal
            validate_sale_removal(identities,self.sale_bag_identities(),index)
        return {'item': item, 'slot': index + 1,
                'seconds': round(time.monotonic() - started, 3),
                'status': '出售传输已结束；服务器成交需核对金币提示；同UID及余额不变时最多补确认一次',
                'settled':True,
                'remaining_count': self.inventory().count(item)}


class ForegroundSession(BackgroundSession):
    """Explicit foreground fallback; use real cursor and normal SendInput clicks."""
    def background_mouse(self,point,button='left',track_movement=True,move_settle=0,dpi_scaled=False,button_hold=0,restore_client_focus=False):
        self.click({'xy':point,'button':button})
        self.pause(.45 if button=='right' else .25)

    def ui_right_click(self,point):
        self.click({'xy':point,'button':'right'})
        self.pause(.35)

    def drag_ui(self,start,end):
        self.check();self.focus_game()
        lw,lh=self.client_size()
        previous=self.u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        event=Input()
        try:
            rect=w.RECT();self.u.GetClientRect(self.hwnd,ctypes.byref(rect))
            origin=w.POINT();self.u.ClientToScreen(self.hwnd,ctypes.byref(origin))
            def move(point):
                x,y=point
                if not(0<=x<lw and 0<=y<lh):raise RuntimeError('拖动超出客户区')
                sx,sy=origin.x+round(x*rect.right/lw),origin.y+round(y*rect.bottom/lh)
                if self.u.WindowFromPoint(w.POINT(sx,sy))!=self.hwnd:raise RuntimeError('拖动位置被遮挡')
                self.u.SetCursorPos(sx,sy)
            move(start);self.pause(.15)
            event.data.mi.dwFlags=2
            if self.u.SendInput(1,ctypes.byref(event),ctypes.sizeof(Input))!=1:raise RuntimeError('拖动按下失败')
            self.pause(.15)
            for i in range(1,16):
                move((start[0]+(end[0]-start[0])*i/15,start[1]+(end[1]-start[1])*i/15))
                self.pause(.04)
        finally:
            event.data.mi.dwFlags=4
            self.u.SendInput(1,ctypes.byref(event),ctypes.sizeof(Input))
            self.u.SetThreadDpiAwarenessContext(previous)
        self.pause(.2)

    def focus_game(self):
        self.check()
        if self.u.IsIconic(self.hwnd):
            self.u.ShowWindow.argtypes=[w.HWND,ctypes.c_int]
            self.u.ShowWindow(self.hwnd,9)
            self.pause(.2)
        self.u.SetForegroundWindow(self.hwnd)
        self.pause(.2)
        if self.u.GetForegroundWindow()!=self.hwnd:
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.GetCurrentThreadId.restype=w.DWORD
            self.u.GetWindowThreadProcessId.argtypes=[w.HWND,ctypes.POINTER(w.DWORD)]
            self.u.AttachThreadInput.argtypes=[w.DWORD,w.DWORD,w.BOOL]
            foreground=self.u.GetForegroundWindow()
            foreground_thread=self.u.GetWindowThreadProcessId(foreground,None)
            own_thread=kernel.GetCurrentThreadId()
            attached=self.u.AttachThreadInput(own_thread,foreground_thread,True)
            try:self.u.SetForegroundWindow(self.hwnd)
            finally:
                if attached:self.u.AttachThreadInput(own_thread,foreground_thread,False)
            self.pause(.15)
        if self.u.GetForegroundWindow()!=self.hwnd:
            alt=Input();alt.type=1;alt.data.ki.vk=0x12
            self.u.SendInput(1,ctypes.byref(alt),ctypes.sizeof(Input))
            alt.data.ki.flags=2
            self.u.SendInput(1,ctypes.byref(alt),ctypes.sizeof(Input))
            self.u.SetForegroundWindow(self.hwnd)
            self.pause(.2)
        if self.u.GetForegroundWindow()!=self.hwnd:raise RuntimeError('无法切换到游戏前台，停止')

    def press_tab(self):
        self.check()
        self.focus_game()
        key=Input();key.type=1;key.data.ki.vk=9
        if self.u.SendInput(1,ctypes.byref(key),ctypes.sizeof(Input))!=1:raise RuntimeError('地图按键发送失败')
        try:self.pause(.1)
        finally:
            key.data.ki.flags=2
            self.u.SendInput(1,ctypes.byref(key),ctypes.sizeof(Input))
        self.pause(.45)
    def teleport_weapon_sale(self, item=None, progress=lambda message: None):
        result=super().teleport_weapon_sale(item,progress)
        result['input_method']='前台 Windows SendInput 鼠标点击；未写入内存'
        return result
    def click(self, point):
        self.check()
        button='left'
        if isinstance(point,dict):
            button=point.get('button','left');point=point['xy']
        if button not in ('left','right'):raise RuntimeError('未知鼠标按键')
        x,y=map(round,point)
        lw,lh=self.client_size()
        if not(0<=x<lw and 0<=y<lh):raise RuntimeError('点击位置超出游戏客户区')
        self.focus_game()
        previous=self.u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        try:
            rect=w.RECT();self.u.GetClientRect(self.hwnd,ctypes.byref(rect))
            origin=w.POINT();self.u.ClientToScreen(self.hwnd,ctypes.byref(origin))
            sx,sy=origin.x+round(x*rect.right/lw),origin.y+round(y*rect.bottom/lh)
            if self.u.WindowFromPoint(w.POINT(sx,sy))!=self.hwnd:
                raise RuntimeError('点击位置被其他窗口遮挡，停止')
            self.u.SetCursorPos(sx,sy)
            self.pause(.12)
            if self.u.GetForegroundWindow()!=self.hwnd:
                raise RuntimeError('按下前游戏已失去前台，未发送点击')
            if self.u.WindowFromPoint(w.POINT(sx,sy))!=self.hwnd:
                raise RuntimeError('按下前点击位置被遮挡，未发送点击')
            event=Input();event.data.mi.dwFlags=2 if button=='left' else 8
            ctypes.set_last_error(0)
            down_count=self.u.SendInput(1,ctypes.byref(event),ctypes.sizeof(Input))
            down_error=ctypes.get_last_error()
            if down_count!=1:raise RuntimeError('鼠标按下失败')
            try:self.pause(.1)
            finally:
                event.data.mi.dwFlags=4 if button=='left' else 16
                ctypes.set_last_error(0)
                up_count=self.u.SendInput(1,ctypes.byref(event),ctypes.sizeof(Input))
                up_error=ctypes.get_last_error()
                cursor=w.POINT();self.u.GetCursorPos(ctypes.byref(cursor))
                self.events.append({'point':[x,y],'screen':[sx,sy],'input':'SendInput','button':button,
                    'down_count':down_count,'up_count':up_count,'down_error':down_error,'up_error':up_error,
                    'cursor_after':[cursor.x,cursor.y],'foreground_after':int(self.u.GetForegroundWindow() or 0),
                    'game_hwnd':int(self.hwnd),'button_down_after':bool(self.u.GetAsyncKeyState(1 if button=='left' else 2)&0x8000)})
                if up_count!=1:raise RuntimeError('鼠标松开发送失败，停止后续操作')
            if self.u.GetForegroundWindow()!=self.hwnd:
                raise RuntimeError('点击期间游戏失去前台，停止；请查看输入日志')
            self.pause(.16)
        finally:self.u.SetThreadDpiAwarenessContext(previous)
