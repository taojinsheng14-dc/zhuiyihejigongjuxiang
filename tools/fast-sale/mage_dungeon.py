"""Bounded dungeon mage input research. Only ordinary background messages."""
import ctypes
import struct
from ctypes import wintypes as w
from mage_skills import inspect_current
from warrior_combat import HEADER, NAMES

AIM_OFFSETS=((0,32),(0,48),(0,16),(0,56),(-16,48),(16,48),(-24,64),(24,64),(0,72))


def guard(session):
    session.check()
    if session.login_stage() != 'playing':raise RuntimeError('角色状态不是正常游戏')
    if session.read(session.uint(session.uint(session.base+0x2ba608))+4,52) != HEADER:
        raise RuntimeError('不在已核对的地牢东一层，未施法')
    if session.held_item() or session.sale_item() or session.inflight_item():
        raise RuntimeError('物品操作未结束，未施法')
    if any(session.visible(k) for k in ('merchant','sell','bag')):
        raise RuntimeError('操作面板打开，未施法')
    if session.u.IsIconic(session.hwnd):raise RuntimeError('游戏已最小化，未施法')


def same_actor(before, after):
    # Compare explicit identity fields rather than assuming the whole header is immutable.
    return (after is not None and len(after) >= 0x184
            and all(before[a:b] == after[a:b] for a,b in ((0,4),(0xc,0x10),(0x40,0x44))))


def probe_once(session, progress=lambda message:None, locked=None):
    guard(session)
    skills = inspect_current(session,'厚礼蟹')
    if not skills.get('f1_skill') or skills['f1_skill']['name'] != '雷电术':
        raise RuntimeError('F1实际绑定不是唯一雷电术，未施法')
    session.wait_shortcut_modifiers_released()
    guard(session)
    sample = session.nearby_monsters(radius=8)
    if sample['read_errors']:raise RuntimeError('怪物列表不完整')
    choices = sorted((m for m in sample['monsters'] if m['name'] in NAMES
        and m['class']=='TCatMon' and not m['dead'] and m['on_screen']
        and m['distance'] <= 8),key=lambda m:m['distance'])
    if not choices:return {'status':'no_verified_target','f1_sent':False}
    rows = dict(session.scene_actor_snapshot())
    width,height=session.client_size()
    def aimable(m):
        raw=rows.get(m['address'])
        if raw is None:return False
        x,y=struct.unpack_from('<2i',raw,0x17c)
        return 70<x<width-70 and any(70<x+ox<width-70 and 60<y+oy<height-180 for ox,oy in AIM_OFFSETS)
    choices=[m for m in choices if aimable(m)]
    if not choices:return {'status':'target_outside_input_area','f1_sent':False}
    if locked:
        choices=[m for m in choices if m['address']==locked['address'] and m['name']==locked['name']]
        if not choices:return {'status':'locked_target_unavailable','f1_sent':False}
    target=choices[0]
    raw = rows.get(target['address'])
    if raw is None or raw[0xac] != 0 or tuple(struct.unpack_from('<2i',raw,0x68)) != tuple(target['position']):
        raise RuntimeError('施法前怪物身份或位置变化')
    x,y=struct.unpack_from('<2i',raw,0x17c);point=(x,y+32)
    width,height=session.client_size()
    if not (70<point[0]<width-70 and any(70<x+ox<width-70 and 60<y+oy<height-180 for ox,oy in AIM_OFFSETS)):
        return {'status':'target_outside_input_area','f1_sent':False}
    own=session.uint(session.uint(session.base+0x2bac2c));hero=session.uint(own+0x358)
    for address,actor in rows.items():
        if address==target['address']:continue
        if address in (own,hero) or struct.unpack_from('<I',actor)[0]==session.base+0x24991c:
            ax,ay=struct.unpack_from('<2i',actor,0x17c)
            if ax-24<=point[0]<=ax+24 and ay<=point[1]<=ay+64:
                return {'status':'target_occluded','f1_sent':False}
    physical=session.physical_client_size()
    px,py=(round(point[0]*physical[0]/width),round(point[1]*physical[1]/height))
    if getattr(session,'_ui_logical_messages',False):px,py=point
    position=(py<<16)|(px&0xffff)
    u=session.u;u.SendMessageTimeoutW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM,w.UINT,w.UINT,ctypes.POINTER(ctypes.c_size_t)]
    u.SendMessageTimeoutW.restype=w.LPARAM
    output=ctypes.c_size_t()
    def send(message,key,lp):
        if not u.SendMessageTimeoutW(session.hwnd,message,key,lp,2,500,ctypes.byref(output)):
            raise RuntimeError('后台施法消息未完成，停止')
    controller=session.uint(session.uint(session.base+0x2bb0a8))
    def context():
        return {hex(o):session.uint(controller+o) for o in (0x18c,0x194,0x198,0x19c,0x1a0,0x1b8,0x1c0)}
    def vitals(address):
        return {hex(o):struct.unpack('<H',session.read(address+o,2))[0] for o in (0x112,0x116,0x11a,0x11e)}
    before=context();result={'target':target,'point':point,'context_before':before,
        'f1_sent':False,'effect_verified':False,'game_input':'background_hover_only'}
    try:
        session.begin_background_input()
        send(0x6,1,0);send(0x7,0,0)
        result['hover_observations']=[]
        for offset_x,offset_y in AIM_OFFSETS:
            fresh=dict(session.scene_actor_snapshot()).get(target['address'])
            if not same_actor(raw,fresh):
                result['status']='target_changed_during_hover';return result
            result.setdefault('mutable_header_changes',[]).extend(i for i in range(4,12) if fresh[i]!=raw[i] and i not in result.get('mutable_header_changes',[]))
            if fresh[0xac] == 1:
                result['status']='target_death_observed';return result
            target=dict(target,position=list(struct.unpack_from('<2i',fresh,0x68)))
            result['target']=target
            dx,dy=struct.unpack_from('<2i',fresh,0x17c)
            candidate=(dx+offset_x,dy+offset_y)
            if not (70<candidate[0]<width-70 and 60<candidate[1]<height-180):continue
            mx,my=(round(candidate[0]*physical[0]/width),round(candidate[1]*physical[1]/height))
            if getattr(session,'_ui_logical_messages',False):mx,my=candidate
            guard(session);send(0x200,0,(my<<16)|(mx&0xffff));session.pause(.12)
            after=context()
            result['hover_observations'].append({'point':candidate,'hover_actor':after['0x1b8']})
            if after['0x1b8']==target['address']:
                result['point']=list(candidate);break
        else:
            result['status']='hover_target_unconfirmed';return result
        result['context_after_hover']=after
        # Read-only candidate field, never write a target pointer. Prove hover
        # selected this exact actor before sending the spell key.
        if after['0x1b8'] != target['address']:
            result['status']='hover_target_unconfirmed';return result
        guard(session)
        fresh=dict(session.scene_actor_snapshot()).get(target['address'])
        if not same_actor(raw,fresh):
            result['status']='target_changed_before_key';return result
        if fresh[0xac] == 1:
            result['status']='target_death_observed';return result
        target_position=struct.unpack_from('<2i',fresh,0x68)
        if max(abs(target_position[i]-session.player()[i]) for i in (0,1))>8:
            result['status']='target_moved_out_of_range';return result
        if context()['0x1b8'] != target['address']:
            result['status']='hover_changed_before_key';return result
        result['main_vitals_before']=vitals(own)
        result['target_vitals_before']=vitals(target['address'])
        progress('已只读核对后台指向同一怪物，按F1一次；不连按')
        lp=(0x3b<<16)|1
        send(0x100,0x70,lp)
        try:session.pause(.08)
        finally:send(0x101,0x70,lp|0xc0000000)
        result.update(f1_sent=True,status='single_f1_sent',game_input='background_hover_and_single_f1')
        session.pause(.8);result['context_after_key']=context()
        result['main_vitals_after']=vitals(own)
        result['target_vitals_after']=vitals(target['address'])
        return result
    finally:session.clear_background_mouse()


def approach_once(session,progress=lambda message:None):
    from warrior_combat import patrol_plan,patrol_move
    guard(session)
    skills=inspect_current(session,'厚礼蟹')
    if not skills.get('f1_skill') or skills['f1_skill']['name']!='雷电术':
        raise RuntimeError('F1不是雷电术，未靠近')
    tilemap,_=patrol_plan(session)
    sample=session.nearby_monsters(radius=12)
    if sample['read_errors']:raise RuntimeError('场景读取不完整')
    choices=[m for m in sample['monsters'] if m['name'] in NAMES and m['class']=='TCatMon' and not m['dead']]
    if not choices:return {'status':'no_monsters','movement':False}
    target=min(choices,key=lambda m:m['distance']);current=tuple(session.player())
    if target['distance']<=4:return {'status':'already_close','movement':False}
    occupied={tuple(struct.unpack_from('<2i',raw,0x68)) for a,raw in session.scene_actor_snapshot() if raw[0xac]==0}
    occupied.discard(current);goals=[]
    tx,ty=target['position']
    for x in range(tx-4,tx+5):
        for y in range(ty-4,ty+5):
            if max(abs(x-tx),abs(y-ty))!=4 or (x,y) in occupied or not tilemap.free((x,y)):continue
            try:path=tilemap.path(current,(x,y),occupied)
            except RuntimeError:continue
            goals.append(path)
    if not goals:return {'status':'no_safe_approach_path','movement':False}
    path=min(goals,key=len)
    if len(path)<2:return {'status':'already_close','movement':False}
    guard(session);progress('沿已核对地牢路网靠近一个步段，不攻击')
    return {'status':'single_approach_segment','movement':True,
        'target':target,'result':patrol_move(session,tilemap,path[-1])}


def run_bounded(session,progress=lambda message:None,seconds=30,max_casts=6):
    """Finite field validation, not a claim of unattended farming acceptance."""
    import json,time
    from pathlib import Path
    import instance_context
    from inventory_flow import ensure_loot_capacity
    from ground_item_probe import ground_snapshot,pickup_current_test
    from island_pickup_policy import filter_drops
    from warrior_combat import patrol_plan,patrol_move
    guard(session);tilemap,plan=patrol_plan(session)
    started=time.monotonic();deadline=started+min(120,max(1,seconds));limit=min(60,max(1,max_casts))
    path=instance_context.runtime_root()/'outputs'/'法师地牢验证.jsonl'
    path.parent.mkdir(parents=True,exist_ok=True)
    def log(event,**data):
        with path.open('a',encoding='utf-8') as f:f.write(json.dumps(dict(time=time.time(),event=event,**data),ensure_ascii=False)+'\n')
    before_navigation=session.navigation_map
    def navigation(header):
        if header!=HEADER:raise RuntimeError('拾取地图变化')
        return tilemap
    session.navigation_map=navigation
    locked=None;last_zero_health=False;casts=deaths=verified_pickups=unverified_losses=0;status='bounded_end';failed_aims=0;waypoint=1;pickup_attempts={};movement_segments=0;position_anchor=tuple(session.player())
    try:
        log('start',position=session.player(),max_casts=limit,seconds=seconds,waypoints=plan['waypoints'])
        while time.monotonic()<deadline and casts<limit:
            guard(session)
            current_position=tuple(session.player())
            if max(abs(current_position[i]-position_anchor[i]) for i in (0,1))>2:
                status='external_position_change';log(status,previous=position_anchor,current=current_position);break
            ensure_loot_capacity(session,progress);guard(session)
            if locked:
                sample=session.nearby_monsters(radius=12)
                current=next((m for m in sample['monsters'] if m['address']==locked['address'] and m['name']==locked['name']),None)
                if sample['read_errors']:raise RuntimeError('战斗场景读取不完整')
                if current is None:
                    if last_zero_health:
                        deaths+=1;log('target_removed_after_zero_health',target=locked);locked=None
                    else:
                        unverified_losses+=1;log('target_disappeared_unverified',target=locked);locked=None;last_zero_health=False;failed_aims=0
                elif current['dead']:
                    deaths+=1;log('target_death_observed',target=current);locked=None
            drops,_=filter_drops(ground_snapshot(session)['ground_maps'][0]['items'])
            nearby=[d for d in drops if max(abs(d['x']-session.player()[0]),abs(d['y']-session.player()[1]))<=6]
            if nearby and locked is None:
                chosen=min(nearby,key=lambda d:max(abs(d['x']-session.player()[0]),abs(d['y']-session.player()[1])))
                pickup_attempts[chosen['id']]=pickup_attempts.get(chosen['id'],0)+1
                if pickup_attempts[chosen['id']]>3:status='pickup_progress_unconfirmed';break
                guard(session)
                result=pickup_current_test(session,names=(chosen['name'],),radius=6,max_steps=2,cooperative=True,target_id=chosen['id'])
                log('pickup',result=result)
                if result.get('verified'):verified_pickups+=1
                elif result.get('status') not in ('approaching','actor_occluded','blocked','no_target'):
                    status='pickup_unverified';break
                position_anchor=tuple(session.player());session.pause(.2);continue
            result=probe_once(session,progress,locked=locked);log('spell_probe',result=result)
            if result.get('f1_sent'):
                casts+=1;locked=result['target'];failed_aims=0
                hp=result.get('target_vitals_after',{})
                last_zero_health=hp.get('0x11a',0)>0 and hp.get('0x112')==0
                session.pause(.6)
            elif result.get('status') in ('no_verified_target','target_outside_input_area'):
                if locked:
                    if last_zero_health:
                        session.pause(.15);continue
                    status='locked_target_not_aimable';break
                move=approach_once(session,progress)
                if not move.get('movement'):
                    if len(plan['waypoints'])<2:status='no_patrol_route';break
                    goal=tuple(plan['waypoints'][waypoint%len(plan['waypoints'])])
                    if max(abs(session.player()[i]-goal[i]) for i in (0,1))<=2:
                        waypoint+=1;goal=tuple(plan['waypoints'][waypoint%len(plan['waypoints'])])
                    guard(session);move=patrol_move(session,tilemap,goal)
                movement_segments+=1;log('movement',result=move)
            elif result.get('status')=='target_death_observed':
                deaths+=1;log('target_death_observed',target=result['target']);locked=None;last_zero_health=False;failed_aims=0
                session.pause(.15)
            elif result.get('status')=='locked_target_unavailable':
                failed_aims+=1
                if failed_aims>=2:status='locked_target_not_aimable';break
                session.pause(.15)
            else:
                failed_aims+=1
                if failed_aims>=2:status='aim_unconfirmed_twice';break
                if locked:
                    position_anchor=tuple(session.player());session.pause(.2);continue
                move=approach_once(session,progress);movement_segments+=int(bool(move.get('movement')));log('aim_reposition',result=move)
                session.pause(.3)
            position_anchor=tuple(session.player())
        summary={'status':status,'casts_sent':casts,'observed_deaths':deaths,
                 'verified_pickups':verified_pickups,'unverified_target_losses':unverified_losses,'movement_segments':movement_segments,
                 'elapsed_seconds':round(time.monotonic()-started,2),'unattended_acceptance':False,'position':session.player()}
        log('end',**summary);return summary
    finally:
        session.navigation_map=before_navigation
        session.clear_background_mouse()
