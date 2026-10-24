"""Bounded warrior click-to-attack verification; no native calls or memory writes."""
import json
import struct
import time
import ctypes
from ctypes import wintypes as w
from collections import deque
from pathlib import Path

import instance_context
from combat_metrics import read_experience
from map_navigation import TileMap,matching_map_file

HEADER=bytes.fromhex('fa00fa000f4c6567656e64206f66206d69720d0ab7329323205ce640020b2e2e474d474a582e434f4d0000000000000000000000')
NAMES={'蜈蚣','跳跳蜂','巨型蠕虫','钳虫','黑色恶蛆','蠕虫'}


class DungeonMap(TileMap):
    def __init__(self,width,height,flags,name='d601.map',center=None,radius=None):
        self.width=width;self.height=height;self.flags=flags;self.name=name;self.center=center;self.radius=radius
    def free(self,xy):
        x,y=xy
        return (8<=x<self.width-8 and 8<=y<self.height-8 and self.flags[x][y]&255==0
                and (self.center is None or max(abs(x-self.center[0]),abs(y-self.center[1]))<=self.radius))
    def path(self,start,goal,blocked=()):
        start,goal=tuple(start),tuple(goal);blocked=set(blocked)-{start}
        queue=deque([start]);parents={start:None}
        while queue:
            at=queue.popleft()
            if at==goal:break
            for dx,dy in ((0,-1),(1,0),(0,1),(-1,0),(-1,-1),(1,-1),(1,1),(-1,1)):
                nxt=(at[0]+dx,at[1]+dy)
                if nxt in parents or nxt in blocked or not self.free(nxt):continue
                if dx and dy and (not self.free((at[0]+dx,at[1])) or not self.free((at[0],at[1]+dy))):continue
                parents[nxt]=at;queue.append(nxt)
        if goal not in parents:raise RuntimeError('巡逻目标当前没有可走路径')
        result=[goal]
        while parents[result[-1]] is not None:result.append(parents[result[-1]])
        return result[::-1]


def patrol_plan(session,expected_header=HEADER,expected_name='d601.map',radius=None):
    obj=session.uint(session.uint(session.base+0x2ba608))
    if session.read(obj+4,52)!=expected_header:raise RuntimeError('不是已核对的地牢地图')
    width,height=struct.unpack('<HH',expected_header[:4]);start=tuple(session.player())
    file=matching_map_file(expected_header)
    if file.name.lower()!=expected_name:raise RuntimeError('当前地图文件名称与授权地图不符')
    data=file.read_bytes();stride=(len(data)-52)//(width*height)
    if stride!=14:raise RuntimeError('地牢文件格式不符')
    historical=Path(__file__).resolve().parents[1]/'game-chat-inspect'/'sale-runtime-code.bin'
    code=historical.read_bytes()
    for address,size in ((0x52b6e8,41),(0x52bc00,115)):
        if session.read(session.base+address-0x400000,size)!=code[address-0x400000:address-0x400000+size]:
            raise RuntimeError('当前地图读取代码与研究证据不一致')
    # Native loader copies 14 bytes into each 36-byte viewport record.
    # Native passability subtracts origin at +70/+74; x stride=91*36.
    origin=struct.unpack('<2i',session.read(obj+0x70,8));mismatch=compared=0
    for x in range(start[0]-8,start[0]+9):
        for y in range(start[1]-8,start[1]+9):
            lx,ly=x-origin[0],y-origin[1]
            if not (0<=lx<121 and 0<=ly<91 and 0<=x<width and 0<=y<height):continue
            live=session.read(obj+0x9c+lx*3276+ly*36,14)
            disk=data[52+(x*height+y)*14:52+(x*height+y+1)*14]
            compared+=1;mismatch+=live!=disk
    if mismatch or compared<64:raise RuntimeError('地牢文件与客户端场景格子不一致：%d/%d；未移动'%(mismatch,compared))
    flags=[[1]*height for _ in range(width)]
    for x in range(width):
        for y in range(height):
            offset=52+(x*height+y)*14;back,_,front=struct.unpack_from('<HHH',data,offset)
            flags[x][y]=int(bool((back|front)&0x8000) or bool(data[offset+6]&128 and not data[offset+7]&128))
    if session.uint(session.uint(session.base+0x2ba608))!=obj:raise RuntimeError('读取路网时地图变化')
    tilemap=DungeonMap(width,height,flags,name=expected_name,center=start if radius is not None else None,radius=radius)
    if not tilemap.free(start):raise RuntimeError('路网未确认当前位置可走')
    queue=deque([start]);reachable={start}
    while queue:
        x,y=queue.popleft()
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            p=(x+dx,y+dy)
            if p not in reachable and tilemap.free(p):reachable.add(p);queue.append(p)
    # Patrol the connected interior around the current wing, favoring open corridors.
    candidates=[p for p in reachable if max(abs(p[i]-start[i]) for i in (0,1))<=45
                and all(tilemap.free((p[0]+dx,p[1]+dy)) for dx,dy in ((-1,0),(1,0),(0,-1),(0,1)))]
    waypoints=[start]
    for _ in range(5):
        choices=[p for p in candidates if min(max(abs(p[i]-q[i]) for i in (0,1)) for q in waypoints)>=10]
        if not choices:break
        goal=max(choices,key=lambda p:min(max(abs(p[i]-q[i]) for i in (0,1)) for q in waypoints)
                 -.1*(abs(p[0]-width/2)+abs(p[1]-height/2)))
        waypoints.append(goal)
    # Greedy ordering avoids bouncing between opposite ends of the patrol area.
    ordered=[waypoints.pop(0)]
    while waypoints:
        paths=[tilemap.path(ordered[-1],p) for p in waypoints]
        index=min(range(len(paths)),key=lambda i:len(paths[i]));ordered.append(waypoints.pop(index))
    plan={'map':expected_name,'file_stride':stride,'client_grid_compared':compared,'mismatch':mismatch,
          'reachable_tiles':len(reachable),'waypoints':ordered,'start':start,'game_input_sent':False}
    path=instance_context.runtime_root()/'outputs'/('地牢一层东巡逻路线.json' if expected_name=='d601.map' else '当前地图巡逻路线.json')
    path.write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf8')
    return tilemap,plan


def eligible(monster):
    return (monster['class']=='TCatMon' and monster['name'] in NAMES
            and not monster['dead'] and monster['on_screen'] and monster['distance']<=8)


def continuous_run(session,tilemap,current,direction,point,max_tiles):
    """Ordinary held right mouse, released on monsters, turns or invalid motion."""
    width,height=session.client_size();physical=session.physical_client_size()
    mx,my=point
    if not getattr(session,'_ui_logical_messages',False):
        mx=round(mx*physical[0]/width);my=round(my*physical[1]/height)
    lp=(my<<16)|(mx&0xffff);output=ctypes.c_size_t()
    session.u.SendMessageTimeoutW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM,w.UINT,w.UINT,ctypes.POINTER(ctypes.c_size_t)]
    session.u.SendMessageTimeoutW.restype=w.LPARAM
    def send(message,key):
        if not session.u.SendMessageTimeoutW(session.hwnd,message,key,lp,2,500,ctypes.byref(output)):
            raise RuntimeError('连续跑动鼠标消息未确认')
    before=previous=current;deadline=time.monotonic()+2;reason='segment_time';pressed=False
    try:
        session.begin_background_input();session.wait_mouse_modifiers_released()
        if session.u.IsIconic(session.hwnd):raise RuntimeError('游戏最小化，停止连续跑动')
        send(0x200,0);send(0x204,2);pressed=True
        while time.monotonic()<deadline:
            session.check()
            obj=session.uint(session.uint(session.base+0x2ba608))
            if session.read(obj+4,52)!=HEADER:raise RuntimeError('连续跑动时地图变化')
            at=tuple(session.player())
            if not tilemap.free(at) or max(abs(at[i]-previous[i]) for i in (0,1))>2:
                raise RuntimeError('连续跑动实际坐标偏离')
            previous=at;distance=max(abs(at[i]-before[i]) for i in (0,1))
            if distance>=max_tiles-1:reason='turn_or_segment_end';break
            if any(at[i]!=before[i]+direction[i]*distance for i in (0,1)):
                reason='direction_changed';break
            monsters=session.nearby_monsters()
            if monsters['read_errors']:raise RuntimeError('连续跑动时怪物采样不完整')
            if any(not m['dead'] and (m['on_screen'] or m['distance']<=8) for m in monsters['monsters']):
                reason='monster_detected';break
            if any(session.u.GetAsyncKeyState(vk)&0x8000 for vk in (1,2,16,17,18)):
                reason='physical_input';break
            if not all(tilemap.free((at[0]+direction[0]*n,at[1]+direction[1]*n)) for n in (1,2)):
                reason='terrain_boundary';break
            send(0x200,2);session.pause(.15)
    finally:
        try:
            if pressed:send(0x205,0)
        finally:session.clear_background_mouse()
    session.pause(.15)
    return {'from':current,'to':tuple(session.player()),'button':'right_hold','release_reason':reason}


def patrol_move(session,tilemap,waypoint,allow_hold=True):
    current=tuple(session.player());rows=session.scene_actor_snapshot()
    blocked={struct.unpack_from('<2i',raw,0x68) for address,raw in rows if raw[0xac]==0}
    blocked.discard(current);path=tilemap.path(current,waypoint,blocked)
    if len(path)<2:return {'from':current,'to':current,'arrived':True}
    dx,dy=path[1][0]-current[0],path[1][1]-current[1]
    run=len(path)>2 and path[2]==(current[0]+2*dx,current[1]+2*dy)
    own=session.uint(session.uint(session.base+0x2bac2c));draw=struct.unpack('<2i',session.read(own+0x17c,8))
    width,height=session.client_size();point=None
    for reach in (3,2) if run else (1,):
        aim=(current[0]+dx*reach,current[1]+dy*reach)
        if not all(tilemap.free((current[0]+dx*n,current[1]+dy*n)) for n in range(1,reach+1)) or aim in blocked:continue
        p=(draw[0]+dx*48*reach,draw[1]+64+dy*32*reach)
        if not (80<=p[0]<width-80 and 60<=p[1]<height-180):continue
        if any(ax-28<=p[0]<=ax+28 and ay-16<=p[1]<=ay+80
               for address,raw in rows if address!=own for ax,ay in [struct.unpack_from('<2i',raw,0x17c)]):continue
        point=p;break
    if point is None:return {'from':current,'to':current,'occluded':True}
    if run:
        straight=0
        for n,p in enumerate(path[1:9],1):
            if p!=(current[0]+dx*n,current[1]+dy*n):break
            straight=n
        if allow_hold and straight>=4:return continuous_run(session,tilemap,current,(dx,dy),point,straight)
    session.background_mouse(point,'right' if run else 'left',track_movement=False)
    previous=None;stable=0;settle_deadline=time.monotonic()+3
    while time.monotonic()<settle_deadline:
        after=tuple(session.player());stable=stable+1 if after==previous else 0
        if stable>=2:break
        previous=after;session.pause(.12)
    else:raise RuntimeError('巡逻移动未稳定，停止')
    if not tilemap.free(after) or max(abs(after[i]-current[i]) for i in (0,1))>2:
        raise RuntimeError('巡逻实际移动超出已核对步长，停止')
    return {'from':current,'to':after,'waypoint':waypoint,'button':'right' if run else 'left'}


def run(session,progress,seconds=60,patrol=False):
    path=instance_context.runtime_root()/'outputs'/'战士单击打怪验证.jsonl'
    path.parent.mkdir(parents=True,exist_ok=True)
    def log(event,**fields):
        with path.open('a',encoding='utf8') as out:
            out.write(json.dumps(dict(time=time.time(),event=event,**fields),ensure_ascii=False)+'\n')
    def guard():
        session.check()
        if session.login_stage()!='playing':raise RuntimeError('角色状态不是正常游戏，停止打怪验证')
        header=session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)
        if header!=HEADER:raise RuntimeError('已离开核对的地牢地图，停止打怪验证')
        if read_experience(session)['character']!='微笑':raise RuntimeError('当前角色不是微笑，未点击')
        if session.held_item() or session.sale_item() or session.inflight_item():raise RuntimeError('物品操作未结束，未点击')
        if any(session.visible(name) for name in ('merchant','sell','bag')):raise RuntimeError('操作面板打开，停止打怪验证')
    guard();start=read_experience(session);deadline=time.monotonic()+min(seconds,600)
    tilemap,plan=patrol_plan(session) if patrol else (None,None)
    waypoint_index=1;blocked_moves=0
    target=None;clicks=deaths=0;clicked_at=last_scan=0
    log('start',sample=start,position=session.player())
    progress('战士验证：单击选怪后等待游戏持续攻击；不重复连点')
    while time.monotonic()<deadline:
        from inventory_flow import ensure_loot_capacity
        guard()
        ensure_loot_capacity(session,progress)
        guard();sample=session.nearby_monsters();rows=sample['monsters']
        if time.monotonic()-last_scan>=5:
            log('scene_observation',position=session.player(),monsters=rows,list_count=sample['list_count'])
            last_scan=time.monotonic()
        if sample['read_errors']:raise RuntimeError('怪物列表读取不完整，停止打怪验证')
        if target:
            current=next((m for m in rows if m['address']==target['address'] and m['name']==target['name']),None)
            if current is None:
                log('target_disappeared_unverified',target=target,experience=read_experience(session))
                return {'status':'target_disappeared_unverified','clicks':clicks,'observed_deaths':deaths}
            if current['dead']:
                deaths+=1;log('target_dead_observed',target=current,experience=read_experience(session));target=None
            elif time.monotonic()-clicked_at>45:
                log('target_alive_timeout',target=current,experience=read_experience(session))
                return {'status':'target_alive_timeout','clicks':clicks,'observed_deaths':deaths}
        else:
            choices=sorted((m for m in rows if eligible(m)),key=lambda m:m['distance'])
            if choices:
                candidate=choices[0]
                # Re-read the scene object and its exact identity immediately before input.
                fresh=session.nearby_monsters()['monsters']
                verified=next((m for m in fresh if m['address']==candidate['address'] and m['name']==candidate['name'] and eligible(m)),None)
                if verified:
                    raw=session.read(verified['address'],0x184)
                    if tuple(struct.unpack_from('<2i',raw,0x68))!=tuple(verified['position']) or raw[0xac]!=0:continue
                    x,y=struct.unpack_from('<2i',raw,0x17c);point=(x,y+32)
                    width,height=session.client_size()
                    if not (32<=point[0]<width-32 and 32<=point[1]<height-180):continue
                    own=session.uint(session.uint(session.base+0x2bac2c))
                    hero=session.uint(own+0x358)
                    occluded=False
                    for address,actor_raw in session.scene_actor_snapshot():
                        if address==verified['address']:continue
                        if address in (own,hero) or struct.unpack_from('<I',actor_raw)[0]==session.base+0x24991c:
                            ax,ay=struct.unpack_from('<2i',actor_raw,0x17c)
                            if ax-24<=point[0]<=ax+24 and ay<=point[1]<=ay+64:occluded=True
                    if occluded:continue
                    guard();session.background_mouse(point,button='left',move_settle=.12,button_hold=.15,restore_client_focus=True)
                    target=verified;clicks+=1;clicked_at=time.monotonic()
                    log('single_attack_click',target=target,point=point,position=session.player(),experience=read_experience(session))
            elif patrol:
                waypoints=plan['waypoints']
                if len(waypoints)<2:raise RuntimeError('没有可用的巡逻路线')
                if max(abs(session.player()[i]-waypoints[waypoint_index][i]) for i in (0,1))<=2:
                    waypoint_index=(waypoint_index+1)%len(waypoints)
                guard();movement=patrol_move(session,tilemap,tuple(waypoints[waypoint_index]));guard()
                log('patrol_move',**movement)
                blocked_moves=blocked_moves+1 if movement['from']==movement['to'] else 0
                if blocked_moves>=3:raise RuntimeError('巡逻连续三次受阻，保留现场停止')
        session.pause(.5 if target else .15)
    end=read_experience(session);log('bounded_end',clicks=clicks,observed_deaths=deaths,sample=end)
    return {'status':'bounded_end','clicks':clicks,'observed_deaths':deaths,'start':start,'end':end,
            'kill_attribution':'死亡观察不代表已确认由主号击杀'}
