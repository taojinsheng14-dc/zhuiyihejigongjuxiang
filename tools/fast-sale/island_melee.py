"""Single ordinary background target click for the user's warrior 微笑."""
import ctypes,struct,time
from ctypes import wintypes as w

OFFSETS=((0,32),(0,48),(0,16),(0,56),(-16,48),(16,48),(-24,64),(24,64),(0,72))
CLASSES={'TCatMon','TSculptureMon'}


def guard(session):
    from island_automation import header,ISLAND_HEADER,role_key
    session.check()
    if session.login_stage()!='playing' or header(session)!=ISLAND_HEADER:raise RuntimeError('主体近战仅允许当前孤岛正常游戏状态')
    if role_key(session).rsplit('|',1)[0]!='微笑':raise RuntimeError('主体近战角色不是已授权的微笑')
    if session.held_item() or session.sale_item() or session.inflight_item():raise RuntimeError('主体近战前物品状态不空')
    if any(session.visible(k) for k in ('merchant','sell','bag')):raise RuntimeError('主体近战前操作面板未关闭')
    if session.u.IsIconic(session.hwnd):raise RuntimeError('游戏已最小化，未近战点击')


def same_actor(before,after):
    return after is not None and len(after)>=0x184 and all(before[a:b]==after[a:b] for a,b in ((0,4),(12,16),(64,68)))


def click_target(session,target,scene_guard=None):
    check_scene=scene_guard or guard
    check_scene(session)
    if target.get('class') not in CLASSES:raise RuntimeError('主体近战目标不是已核对怪物类型')
    raw=dict(session.scene_actor_snapshot()).get(target['address'])
    if raw is None or raw[0xac]!=0:return {'status':'target_unavailable','clicked':False}
    ptr=struct.unpack_from('<I',raw,12)[0];size=session.uint(ptr-4)
    if not 1<=size<=60 or session.read(ptr,size).decode('gb18030')!=target['name']:
        raise RuntimeError('主体近战目标名称不符，未点击')
    controller=session.uint(session.uint(session.base+0x2bb0a8))
    width,height=session.client_size();physical=session.physical_client_size()
    u=session.u;u.SendMessageTimeoutW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM,w.UINT,w.UINT,ctypes.POINTER(ctypes.c_size_t)];u.SendMessageTimeoutW.restype=w.LPARAM
    out=ctypes.c_size_t()
    def send(message,key,lp):
        if not u.SendMessageTimeoutW(session.hwnd,message,key,lp,2,500,ctypes.byref(out)):raise RuntimeError('主体近战后台消息未确认')
    try:
        session.wait_mouse_modifiers_released();session.begin_background_input();send(6,1,0);send(7,0,0)
        for ox,oy in OFFSETS:
            fresh=dict(session.scene_actor_snapshot()).get(target['address'])
            if not same_actor(raw,fresh) or fresh[0xac]!=0:return {'status':'target_changed','clicked':False}
            dx,dy=struct.unpack_from('<2i',fresh,0x17c);point=(dx+ox,dy+oy)
            if not(70<point[0]<width-70 and 60<point[1]<height-180):continue
            mx,my=(round(point[0]*physical[0]/width),round(point[1]*physical[1]/height))
            if getattr(session,'_ui_logical_messages',False):mx,my=point
            check_scene(session);send(0x200,0,(my<<16)|(mx&65535));session.pause(.12)
            if session.uint(controller+0x1b8)!=target['address']:continue
            check_scene(session)
            fresh=dict(session.scene_actor_snapshot()).get(target['address'])
            if not same_actor(raw,fresh) or fresh[0xac]!=0:return {'status':'target_changed','clicked':False}
            if session.uint(controller+0x1b8)!=target['address']:continue
            before=struct.unpack('<HH',session.read(target['address']+0x112,2)+session.read(target['address']+0x11a,2))
            context_before={hex(o):session.uint(controller+o) for o in (0x1b8,0x1bc,0x1c0,0x1c4)}
            player_before=tuple(session.player())
            session.background_mouse(point,'left',track_movement=False,dpi_scaled=True,move_settle=.05,button_hold=.08)
            session.pause(.3)
            return {'status':'single_attack_click','clicked':True,'target':target,'point':point,
                    'health_before':list(before),'context_before':context_before,
                    'context_after':{hex(o):session.uint(controller+o) for o in (0x1b8,0x1bc,0x1c0,0x1c4)},
                    'player_before':player_before,'effect_verified':False,'player_after':session.player(),
                    'actor_identity':[raw[a:b].hex() for a,b in ((0,4),(12,16),(64,68))]}
        return {'status':'hover_unconfirmed','clicked':False}
    finally:session.clear_background_mouse()


class Melee:
    def __init__(self,scene_guard=None):
        self.scene_guard=scene_guard
        self.locked=None;self.retry_at={};self.clicks=0;self.health=None;self.progress_at=0

    def reset(self):self.locked=None;self.health=None

    def step(self,session,sample):
        now=time.monotonic();alive=sample['monsters']
        self.retry_at={a:t for a,t in self.retry_at.items() if t>now}
        current=next((m for m in alive if self.locked and m['address']==self.locked['address'] and m['name']==self.locked['name']),None)
        if current:
            raw=dict(session.scene_actor_snapshot()).get(current['address'])
            identity=[raw[a:b].hex() for a,b in ((0,4),(12,16),(64,68))] if raw else None
            if raw and raw[0xac]==0 and identity==self.locked['actor_identity']:
                hp=struct.unpack('<H',session.read(current['address']+0x112,2))[0]
                moved=tuple(session.player())!=tuple(self.locked['position'])
                changed=hp!=self.health or moved
                if changed:self.health=hp;self.progress_at=now;self.locked['position']=list(session.player())
                if now-self.progress_at<20:return {'status':'native_attack_wait','clicked':False,'engaged':True,'health_progress':changed,'health':hp}
                self.retry_at[current['address']]=now+3
        self.reset()
        choices=[m for m in alive if m.get('class') in CLASSES and m.get('on_screen') and m.get('distance',99)<=8 and m['address'] not in self.retry_at]
        if not choices:return {'status':'no_clickable_target','clicked':False,'engaged':False}
        drop_tiles={(d['x'],d['y']) for d in sample['drops']}
        target=min(choices,key=lambda m:(tuple(m['position']) not in drop_tiles,m.get('distance',99)))
        result=click_target(session,target,scene_guard=self.scene_guard) if self.scene_guard else click_target(session,target)
        if result.get('clicked'):
            self.clicks+=1;self.locked=dict(target,actor_identity=result['actor_identity'],position=list(session.player()))
            self.health=result['health_before'][0];self.progress_at=now;result['engaged']=True
        else:self.retry_at[target['address']]=now+2
        return result
