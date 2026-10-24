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


def probe_once(session, progress=lambda message:None, locked=None, excluded=None, scene_guard=None, target_names=None, target_classes=None,prefer_nearby=False):
    check_scene=scene_guard or guard
    names=NAMES if target_names is None else target_names
    classes={'TCatMon'} if target_classes is None else target_classes
    check_scene(session)
    skills = inspect_current(session,'厚礼蟹')
    if not skills.get('f1_skill') or skills['f1_skill']['name'] != '雷电术':
        raise RuntimeError('F1实际绑定不是唯一雷电术，未施法')
    session.wait_shortcut_modifiers_released()
    check_scene(session)
    sample = session.nearby_monsters(radius=8)
    if sample['read_errors']:raise RuntimeError('怪物列表不完整')
    choices = sorted((m for m in sample['monsters'] if m['name'] in names
        and m['class'] in classes and not m['dead'] and m['on_screen']
        and m['distance'] <= 8 and m['address'] not in (excluded or set())),key=lambda m:m['distance'])
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
        previous=next((m for m in choices if m['address']==locked['address'] and m['name']==locked['name']),None)
        if prefer_nearby:
            if previous and previous['distance']<=choices[0]['distance']:choices=[previous]
        else:
            if previous is None:return {'status':'locked_target_unavailable','f1_sent':False}
            choices=[previous]
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
                return {'status':'target_occluded','f1_sent':False,'target':target}
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
            check_scene(session);send(0x200,0,(my<<16)|(mx&0xffff));session.pause(.12)
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
        check_scene(session)
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


def run_bounded(session,progress=lambda message:None,seconds=30,max_casts=6,continuous=False,profile=None):
    """Finite field validation, not a claim of unattended farming acceptance."""
    import json,time
    from pathlib import Path
    import instance_context
    from inventory_flow import ensure_loot_capacity
    from ground_item_probe import ground_snapshot,pickup_current_test
    from island_pickup_policy import filter_drops
    from warrior_combat import patrol_plan,patrol_move
    check_scene=profile.guard if profile else guard
    (profile.check_state(session) if profile else check_scene(session))
    tilemap,plan=profile.plan(session) if profile else patrol_plan(session)
    expected_header=profile.header if profile else HEADER
    probe_options={'scene_guard':profile.guard,'target_names':profile.names,'target_classes':{'TCatMon'},'prefer_nearby':True} if profile else {}
    approach=profile.approach if profile else approach_once
    started=time.monotonic();deadline=started+(43200 if continuous else min(120,max(1,seconds)));limit=float('inf') if continuous else min(60,max(1,max_casts))
    from dungeon_route import CoverageRoute
    route=CoverageRoute(tilemap,tuple(session.player()),spacing=getattr(profile,'route_spacing',8)) if continuous else None
    move_options=profile.move_options() if profile and hasattr(profile,'move_options') else {'allow_hold':False}
    excluded={};deferred_drops={};stalled=0;last_progress=0
    original_progress=progress
    def report(message):
        nonlocal last_progress
        if not continuous or time.monotonic()-last_progress>=15:
            last_progress=time.monotonic();original_progress(message)
    progress=report
    path=instance_context.runtime_root()/'outputs'/('当前地图挂机.jsonl' if profile else '法师地牢验证.jsonl')
    path.parent.mkdir(parents=True,exist_ok=True)
    def log(event,**data):
        with path.open('a',encoding='utf-8') as f:f.write(json.dumps(dict(time=time.time(),event=event,**data),ensure_ascii=False)+'\n')
    status_path=path.with_name('当前地图挂机状态.json' if profile else '法师地牢挂机状态.json')
    def state(phase,**extra):
        if not continuous:return
        data=dict(observed_epoch=time.time(),mode='continuous',map=plan.get('map'),phase=phase,position=session.player(),
                  casts=casts,observed_deaths=deaths,verified_pickups=verified_pickups,
                  route=route.snapshot(),**extra)
        temp=status_path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');temp.replace(status_path)
    before_navigation=session.navigation_map
    def navigation(header):
        if header!=expected_header:raise RuntimeError('拾取地图变化')
        return tilemap
    session.navigation_map=navigation
    locked=None;last_zero_health=False;casts=deaths=verified_pickups=unverified_losses=0;status='bounded_end';failed_aims=0;waypoint=1;pickup_attempts={};movement_segments=0;position_anchor=tuple(session.player())
    try:
        log('start',position=session.player(),max_casts=None if continuous else limit,seconds=43200 if continuous else seconds,continuous=continuous,waypoints=plan['waypoints'])
        panel_wait=False
        while time.monotonic()<deadline and casts<limit:
            try:
                if profile and profile.wait_for_panels(session):
                    if not panel_wait:log('panel_open_wait');panel_wait=True
                    state('panel_wait');session.pause(.2);continue
                if panel_wait:
                    position_anchor=tuple(session.player());locked=None;failed_aims=0
                    log('panel_closed_resume');panel_wait=False
                check_scene(session)
                state('running')
                current_position=tuple(session.player())
                if max(abs(current_position[i]-position_anchor[i]) for i in (0,1))>2:
                    status='external_position_change';log(status,previous=position_anchor,current=current_position);break
                ensure_loot_capacity(session,progress);check_scene(session)
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
                nearby=[d for d in drops if deferred_drops.get(d['id'],0)<=time.monotonic() and max(abs(d['x']-session.player()[0]),abs(d['y']-session.player()[1]))<=6]
                from pickup_strategy import choose,context
                loot_action,chosen=('clear',None)
                if nearby:
                    scene=context(session)
                    loot_action,chosen=choose(nearby,scene['monsters'],scene['hero'],scene['position'])
                if loot_action in ('pickup','lead_hero'):
                    if locked:log('target_interrupted_for_loot',target=locked)
                    locked=None;last_zero_health=False;failed_aims=0
                    pickup_attempts[chosen['id']]=pickup_attempts.get(chosen['id'],0)+1
                    if pickup_attempts[chosen['id']]>3:
                        if continuous:
                            deferred_drops[chosen['id']]=time.monotonic()+20;pickup_attempts[chosen['id']]=0
                            log('drop_temporarily_blocked',id=chosen['id']);nearby=[]
                        else:status='pickup_progress_unconfirmed';break
                    if not nearby:
                        goal=route.next_goal(tuple(session.player()),time.monotonic())
                        if goal is not None:patrol_move(session,tilemap,goal,**move_options)
                        position_anchor=tuple(session.player());session.pause(.2);continue
                    check_scene(session)
                    result=pickup_current_test(session,names=(chosen['name'],),radius=6,max_steps=2,cooperative=True,target_id=chosen['id'])
                    log('pickup',result=result)
                    if result.get('verified'):verified_pickups+=1
                    elif result.get('status') not in ('approaching','actor_occluded','blocked','no_target','combat_required','hero_moved','hero_wait'):
                        status='pickup_unverified';break
                    if result.get('status') in ('combat_required','hero_moved','hero_wait'):pickup_attempts[chosen['id']]=0
                    position_anchor=tuple(session.player());session.pause(.2);continue
                excluded={a:t for a,t in excluded.items() if t>time.monotonic()}
                try:result=probe_once(session,progress,locked=locked,**probe_options,**({'excluded':set(excluded)} if continuous else {}))
                except (profile.panel_exception if profile else ()):
                    locked=None;failed_aims=0;continue
                log('spell_probe',result=result)
                if result.get('f1_sent'):
                    casts+=1;locked=result['target'];failed_aims=0
                    hp=result.get('target_vitals_after',{})
                    last_zero_health=hp.get('0x11a',0)>0 and hp.get('0x112')==0
                    session.pause(getattr(profile,'post_cast_wait',.6))
                elif result.get('status') in ('no_verified_target','target_outside_input_area'):
                    if locked:
                        if last_zero_health:
                            session.pause(.15);continue
                        if continuous:
                            excluded[locked['address']]=time.monotonic()+15;locked=None;failed_aims=0
                        else:status='locked_target_not_aimable';break
                    move=approach(session,progress) if profile or not continuous else {'movement':False}
                    if move.get('nearby_combat') and not move.get('movement'):
                        log('nearby_combat_wait',result=move);session.pause(.3);continue
                    if not move.get('movement'):
                        if not continuous and len(plan['waypoints'])<2:status='no_patrol_route';break
                        if continuous:
                            goal=route.next_goal(tuple(session.player()),time.monotonic())
                            if goal is None:session.pause(.3);continue
                            try:move=patrol_move(session,tilemap,goal,**move_options)
                            except RuntimeError as error:
                                if str(error)!='巡逻目标当前没有可走路径':raise
                                route.defer_goal(time.monotonic());log('route_temporarily_blocked',goal=goal);continue
                            moved=tuple(move.get('from',()))!=tuple(move.get('to',()))
                            stalled=0 if moved else stalled+1
                            if stalled>=3:route.defer_goal(time.monotonic());stalled=0
                            progress('地牢持续清怪拾取：沿可达路线前往%s，已走访%d/%d个路点' % (goal,len(route.visited),len(route.points)))
                        else:
                            goal=tuple(plan['waypoints'][waypoint%len(plan['waypoints'])])
                            if max(abs(session.player()[i]-goal[i]) for i in (0,1))<=2:
                                waypoint+=1;goal=tuple(plan['waypoints'][waypoint%len(plan['waypoints'])])
                            check_scene(session);move=patrol_move(session,tilemap,goal)
                    movement_segments+=1;log('movement',result=move)
                elif result.get('status')=='target_death_observed':
                    deaths+=1;log('target_death_observed',target=result['target']);locked=None;last_zero_health=False;failed_aims=0
                    session.pause(.15)
                elif result.get('status')=='locked_target_unavailable':
                    failed_aims+=1
                    if failed_aims>=2:
                        if continuous:
                            excluded[locked['address']]=time.monotonic()+15;locked=None;failed_aims=0
                        else:status='locked_target_not_aimable';break
                    session.pause(.15)
                else:
                    failed_aims+=1
                    if failed_aims>=2:
                        if continuous:
                            failed=locked or result.get('target')
                            if failed:excluded[failed['address']]=time.monotonic()+15
                            locked=None;failed_aims=0
                            log('aim_deferred',target=failed);position_anchor=tuple(session.player());continue
                        status='aim_unconfirmed_twice';break
                    if locked:
                        position_anchor=tuple(session.player());session.pause(.2);continue
                    move=approach(session,progress);movement_segments+=int(bool(move.get('movement')));log('aim_reposition',result=move)
                    session.pause(.3)
                position_anchor=tuple(session.player())
            except (profile.panel_exception if profile else ()):
                locked=None;failed_aims=0;continue
            except (getattr(profile,'player_exception',()) if profile else ()):
                session.clear_background_mouse()
                result=profile.avoid_players(session,progress);log('player_avoidance',result=result)
                locked=None;last_zero_health=False;failed_aims=0;excluded.clear()
                position_anchor=tuple(session.player())
                if result.get('random_used'):
                    route=CoverageRoute(tilemap,position_anchor,spacing=getattr(profile,'route_spacing',8))
                continue
        summary={'status':status,'casts_sent':casts,'observed_deaths':deaths,
                 'verified_pickups':verified_pickups,'unverified_target_losses':unverified_losses,'movement_segments':movement_segments,
                 'elapsed_seconds':round(time.monotonic()-started,2),'unattended_acceptance':False,'position':session.player()}
        state('finished',result=summary)
        log('end',**summary);return summary
    except Exception as error:
        state('stopped',reason=str(error));log('stopped',reason=str(error));raise
    finally:
        session.navigation_map=before_navigation
        session.clear_background_mouse()
