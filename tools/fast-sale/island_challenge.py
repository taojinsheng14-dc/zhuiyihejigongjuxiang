"""Island challenge entry through ordinary mouse messages only."""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path

import instance_context
ROOT=instance_context.runtime_root()
STATE=ROOT/'outputs'/'孤岛挑战状态.json'

def open_npc(session):
    if session.login_stage()!='playing':raise RuntimeError('未进入地图')
    if session.held_item() or session.sale_item() or session.inflight_item():raise RuntimeError('物品状态不空')
    matches=[n for n in session.npcs() if n['name']=='孤岛挑战' and tuple(n['map'])==(317,331)]
    if len(matches)!=1:raise RuntimeError('未找到唯一孤岛挑战NPC')
    npc=matches[0];x,y=npc['draw'];point=(x,y+24)
    width,height=session.client_size()
    if not (80<=point[0]<=width-80 and 80<=point[1]<=height-200):raise RuntimeError('孤岛NPC不在可点击范围')
    session.background_mouse(point,'left',track_movement=False,move_settle=.15,dpi_scaled=True)
    session.pause(.4)
    return {'npc':npc,'click':point,'merchant_visible':session.visible('merchant'),'position':session.player()}


def click_start_link(session):
    # Historical verified link offset, anchored to current merchant control (not screen).
    merchant=session.control_info(0x5e0,'Window_MerchantDlg')
    if not merchant['visible']:raise RuntimeError('孤岛菜单未显示，未点击')
    x,y,width,height=merchant['bounds'];point=(x+64,y+138)
    cw,ch=session.client_size()
    if not (x<point[0]<x+width and y<point[1]<y+height and 0<point[0]<cw and 0<point[1]<ch):
        raise RuntimeError('孤岛菜单入口不在已验证控件内')
    if session.hero_covers((point[0]-5,point[1]-5,point[0]+5,point[1]+5)):raise RuntimeError('英雄面板遮挡孤岛菜单')
    from background_sale import BackgroundSession
    BackgroundSession.background_mouse(session,point,'left',track_movement=False,move_settle=.15,dpi_scaled=True,button_hold=.15)


def confirm_entry_npc(session,verified_npc=None):
    """Dialog opening can transiently change scene-list membership."""
    for attempt in range(3):
        matches=[n for n in session.npcs() if n['name']=='孤岛挑战' and tuple(n['map'])==(317,331)]
        if len(matches)==1:return matches[0]
        if len(matches)>1:raise RuntimeError('孤岛入口NPC不唯一，未点击挑战')
        if attempt<2:session.pause(.15)
    if (verified_npc and verified_npc.get('name')=='孤岛挑战'
            and tuple(verified_npc.get('map',()))==(317,331)
            and getattr(session,'active_merchant',None)=='孤岛挑战'
            and session.visible('merchant') and session.in_mengzhong_return_area()):
        # Re-read the exact actor's type/name/position; a remembered name alone
        # cannot authorize the daily entry link.
        session.verified_npc_draw(verified_npc)
        return verified_npc
    raise RuntimeError('当前未确认孤岛NPC')


def enter_once(session,verified_npc=None):
    import time
    today=datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    actor=session.uint(session.uint(session.base+0x2bac2c));ptr=session.uint(actor+0xc);length=session.uint(ptr-4)
    if not 1<=length<=60:raise RuntimeError('角色标识无效')
    role=session.read(ptr,length).decode('gb18030')
    state=json.loads(STATE.read_text(encoding='utf8')) if STATE.exists() else {}
    key=role+'|'+today
    if key in state:raise RuntimeError('今日已记录挑战进入或尝试，避免重复消耗次数')
    if not session.visible('merchant'):raise RuntimeError('挑战菜单未打开')
    confirm_entry_npc(session,verified_npc)
    if session.held_item() or session.sale_item() or session.inflight_item():raise RuntimeError('物品状态不空')
    header=session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)
    state[key]={'status':'entry_requested','date':today,'time':time.time(),'before':session.player()}
    def save():
        temp=STATE.with_suffix('.tmp');temp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(STATE)
    save()
    click_start_link(session)
    for _ in range(40):
        session.pause(.1)
        after=session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)
        if after!=header:
            state[key].update(status='entered',position=session.player(),map_header=after.hex());save()
            return {'status':'entered','position':session.player(),'daily_limit':1,'path':str(STATE)}
    state[key]['status']='entry_unconfirmed';save()
    return {'status':'entry_unconfirmed','position':session.player(),'retry':False}


def inspect_inside(session):
    from ground_item_probe import ground_snapshot
    import struct
    own=session.uint(session.uint(session.base+0x2bac2c));hero=session.uint(own+0x358)
    hero_position=struct.unpack('<2i',session.read(hero+0x68,8)) if hero else None
    sample={'position':session.player(),'hero_position':hero_position,'monsters':session.nearby_monsters(radius=25),
            'npcs':session.npcs(),'ground':ground_snapshot(session),'game_input_sent':False}
    path=ROOT/'outputs'/'孤岛挑战现场.json';path.write_text(json.dumps(sample,ensure_ascii=False,indent=2),encoding='utf8')
    return sample


def approach_sculpture(session,target_address=None,max_steps=8):
    import struct
    import ground_item_probe
    __import__('importlib').reload(ground_item_probe)
    from ground_item_probe import choose_pickup_move,wait_pickup_position,pickup_aim
    sample=session.nearby_monsters(radius=25)
    targets=[m for m in sample['monsters'] if m['class']=='TSculptureMon' and not m['dead'] and (target_address is None or m.get('address')==target_address)]
    if not targets:return {'status':'no_sculptures','position':session.player()}
    selected=min(targets,key=lambda m:m['distance']);target_name=selected['name']
    original=tuple(selected['position'])
    header=session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)
    tilemap=session.navigation_map(header);actions=[];failed=set()
    for _ in range(max_steps):
        if session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)!=header:raise RuntimeError('地图变化，停止靠近')
        current=tuple(session.player())
        sample=session.nearby_monsters(radius=25)
        targets=[m for m in sample['monsters'] if m['name']==target_name and not m['dead'] and (target_address is None or m.get('address')==target_address)]
        if len(targets)!=1:break
        target=tuple(targets[0]['position']);distance=max(abs(target[0]-current[0]),abs(target[1]-current[1]))
        if distance<=2 or target!=original:break
        blocked={tuple(m['position']) for m in sample['monsters'] if not m['dead']}|failed
        blocked.update(tuple(n['map']) for n in session.npcs())
        own=session.uint(session.uint(session.base+0x2bac2c));hero=session.uint(own+0x358)
        if hero:blocked.add(struct.unpack('<2i',session.read(hero+0x68,8)))
        choices=[]
        for dx in range(-2,3):
            for dy in range(-2,3):
                goal=(target[0]+dx,target[1]+dy)
                if goal in blocked or not tilemap.free(goal):continue
                try:path=tilemap.path(current,goal,blocked)
                except RuntimeError:continue
                choices.append(path)
        if not choices:raise RuntimeError('雕像附近没有可走站位')
        path=min(choices,key=len)
        if len(path)<2:break
        destination,button=choose_pickup_move(current,path,tilemap,blocked)
        draw=struct.unpack('<2i',session.read(own+0x17c,8))
        point=pickup_aim(current,destination,draw,tilemap,blocked,session.client_size())
        from background_sale import BackgroundSession
        BackgroundSession.background_mouse(session,point,button,track_movement=False,move_settle=.12,dpi_scaled=True,button_hold=.15)
        after=wait_pickup_position(session,destination)
        actions.append({'from':current,'expected':destination,'to':after,'button':button})
        if after==current:
            failed.add(destination);continue
        if after!=destination:
            if not tilemap.free(after) or max(abs(after[0]-current[0]),abs(after[1]-current[1]))>4:raise RuntimeError('靠近雕像移动超出范围，停止')
            actions[-1]['replanned_after_actual_movement']=True
    session.pause(.5)
    result={'position':session.player(),'actions':actions,'monsters':session.nearby_monsters(radius=25)}
    (ROOT/'outputs'/'孤岛雕像靠近.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result


def loot_island(session,combat=False,blocked_ids=None):
    import time
    import ground_item_probe
    __import__('importlib').reload(ground_item_probe)
    from ground_item_probe import pickup_current_test,ground_snapshot
    current_header=session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)
    records=json.loads(STATE.read_text(encoding='utf8')) if STATE.exists() else {}
    if not any(r.get('status')=='entered' and r.get('map_header')==current_header.hex() for r in records.values()):
        raise RuntimeError('未确认当前为已进入的孤岛地图，未拾取')
    if not combat and session.nearby_monsters(radius=50)['loaded_monster_alive']:
        return {'status':'waiting_for_monsters','actions':[]}
    excluded=set(blocked_ids or ());results=[];retry_pass=0;deadline=time.monotonic()+(8 if combat else 180)
    for _ in range(1 if combat else 80):
        if time.monotonic()>deadline:break
        session.check()
        if session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)!=current_header:
            raise RuntimeError('地图变化，停止孤岛拾取')
        result=pickup_current_test(session,excluded=excluded,names=None,cooperative=True,**({'radius':25,'max_steps':8} if combat else {'radius':None}))
        if result.get('status')=='combat_required':return {'status':'waiting_for_monsters','results':results}
        if result.get('status') in ('hero_moved','hero_wait','approaching','actor_occluded'):
            results.append(result);continue
        if result.get('status')=='no_target':
            if excluded and retry_pass<3:
                retry_pass+=1;excluded.clear();session.pause(.6);continue
            break
        results.append(result)
        with (ROOT/'outputs'/'孤岛拾取日志.jsonl').open('a',encoding='utf8') as out:
            out.write(json.dumps({'time':time.time(),'result':result},ensure_ascii=False)+'\n')
        if result.get('status')=='blocked':excluded.add(result['id']);continue
        if not result.get('verified') and result.get('status')!='removed_at_target':return {'status':'stopped_unverified','results':results}
    remaining=ground_snapshot(session)['ground_maps'][0]['items']
    return {'status':'complete' if not remaining else 'remaining_blocked','results':results,'remaining':remaining,'position':session.player(),'retry_passes':retry_pass}


def open_corner(session):
    if session.visible('merchant'):return {'merchant_visible':True,'position':session.player(),'already_open':True}
    if session.nearby_monsters(radius=50)['loaded_monster_alive']:raise RuntimeError('当前还有怪物，未进入下一关')
    if session.held_item() or session.sale_item() or session.inflight_item():raise RuntimeError('物品状态不空')
    position=tuple(session.player());npcs=[n for n in session.npcs() if n['name']=='孤岛挑战']
    if not 1<=len(npcs)<=4 or any(tuple(n['map']) not in {(19,11),(26,18),(19,25),(13,18)} for n in npcs):raise RuntimeError('未确认岛内角落挑战NPC')
    width,height=session.client_size()
    visible=[n for n in npcs if 50<n['draw'][0]<width-50 and 50<n['draw'][1]+24<height-180]
    if not visible:raise RuntimeError('角落NPC不在可点击范围')
    npc=min(visible,key=lambda n:max(abs(n['map'][0]-position[0]),abs(n['map'][1]-position[1])))
    from background_sale import BackgroundSession
    attempts=[]
    for offset in (40,):
        if tuple(session.player())!=position:raise RuntimeError('点击NPC期间人物移动，停止追加点击')
        fresh=[n for n in session.npcs() if n['address']==npc['address'] and n['name']=='孤岛挑战']
        if len(fresh)!=1:break
        point=(fresh[0]['draw'][0]+12,fresh[0]['draw'][1]+offset)
        BackgroundSession.background_mouse(session,point,'left',track_movement=False,move_settle=.15,dpi_scaled=True,button_hold=.15)
        for _ in range(20):
            if session.visible('merchant'):break
            session.pause(.1)
        attempts.append({'offset':offset,'point':point,'opened':session.visible('merchant')})
        if session.visible('merchant'):break
    return {'npc':npc,'attempts':attempts,'merchant_visible':session.visible('merchant'),'position':session.player()}


def next_level(session):
    import time
    from ground_item_probe import ground_snapshot
    if not session.visible('merchant'):raise RuntimeError('孤岛菜单未打开')
    if session.nearby_monsters(radius=50)['loaded_monster_alive']:raise RuntimeError('仍有怪物，未换关')
    from island_pickup_policy import filter_drops
    ground=ground_snapshot(session)['ground_maps'][0]
    if not ground.get('stable') or ground.get('error'):raise RuntimeError('地面列表不稳定，未换关')
    wanted,ignored=filter_drops(ground['items'])
    if wanted:raise RuntimeError('还有名单内地面掉落，先拾取再换关')
    npcs=session.npcs()
    from island_automation import confirmed_corner_npcs
    corners=confirmed_corner_npcs(session,npcs)
    if len(corners)<3:raise RuntimeError('未确认岛内场景，未点击开始')
    if session.held_item() or session.sale_item() or session.inflight_item():raise RuntimeError('物品状态不空')
    header=session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)
    before=session.player();before_corner_addresses={n['address'] for n in corners}
    event={'time':time.time(),'event':'next_level_requested','before':before,'before_header':header.hex()}
    log=ROOT/'outputs'/'孤岛换关日志.jsonl'
    def record(value):
        with log.open('a',encoding='utf8') as out:out.write(json.dumps(value,ensure_ascii=False)+'\n')
    record(event)
    from background_sale import BackgroundSession
    click_start_link(session)
    for _ in range(50):
        session.pause(.1)
        after=session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)
        current_corners=[n for n in session.npcs() if n['name']=='孤岛挑战' and tuple(n['map']) in {(19,11),(26,18),(19,25),(13,18)}]
        recreated=(len(current_corners)>=3 and not before_corner_addresses.intersection(n['address'] for n in current_corners) and not session.visible('merchant'))
        if after!=header and max(session.player())>40:
            result={'status':'left_island','position':session.player(),'completion_verified':False}
            record(dict(result,time=time.time()));return result
        if after!=header or recreated:
            result={'status':'transition_confirmed','evidence':'map_header' if after!=header else 'corner_objects_recreated','position':session.player(),'after_header':after.hex()}
            record(dict(result,time=time.time()))
            # Keep the same paid entry record; island map changes are levels, not new daily entries.
            state=json.loads(STATE.read_text(encoding='utf8')) if STATE.exists() else {}
            for entry in state.values():
                if entry.get('status')=='entered' and entry.get('map_header')==header.hex():entry['map_header']=after.hex()
            temp=STATE.with_suffix('.tmp');temp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(STATE)
            return result
    result={'status':'transition_unconfirmed','position':session.player(),'retry':False};record(dict(result,time=time.time()));return result


def cast_lightning(session,locked=None,priority_positions=()):
    import ctypes,struct
    from ctypes import wintypes as w
    from fast_sale import Input
    from background_sale import ForegroundSession
    if not isinstance(session,ForegroundSession):raise RuntimeError('雷电术首次测试使用前台模式')
    if session.login_stage()!='playing':raise RuntimeError('角色不在游戏内')
    if session.visible('merchant'):raise RuntimeError('菜单未关闭，未施法')
    sample=session.nearby_monsters(radius=50)
    targets=[m for m in sample['monsters'] if not m['dead'] and m['on_screen']]
    if not targets:return {'status':'no_monsters'}
    blockers=[m for m in targets if tuple(m['position']) in priority_positions]
    target=min(blockers,key=lambda m:m['distance']) if blockers else None
    target=target or next((m for m in targets if locked and m.get('address')==locked.get('address') and m['name']==locked.get('name')),None)
    target=target or min(targets,key=lambda m:m['distance']);matches=[]
    for address,raw in session.scene_actor_snapshot():
        ptr=struct.unpack_from('<I',raw,0xc)[0];length=session.uint(ptr-4)
        if not 1<=length<=60:continue
        name=session.read(ptr,length).decode('gb18030')
        xy=struct.unpack_from('<2i',raw,0x68)
        if name==target['name'] and tuple(target['position'])==xy and raw[0xac]==0:
            matches.append((address,struct.unpack_from('<2i',raw,0x17c)))
    if len(matches)!=1:raise RuntimeError('施法目标不唯一，未按F1')
    address,draw=matches[0];point=(draw[0],draw[1]+32)
    width,height=session.client_size()
    if not (70<point[0]<width-70 and 60<point[1]<height-180):raise RuntimeError('施法目标不在有效区域')
    session.wait_shortcut_modifiers_released();session.focus_game()
    previous=session.u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    try:
        rect=w.RECT();origin=w.POINT();session.u.GetClientRect(session.hwnd,ctypes.byref(rect));session.u.ClientToScreen(session.hwnd,ctypes.byref(origin))
        screen=(origin.x+round(point[0]*rect.right/width),origin.y+round(point[1]*rect.bottom/height))
        if session.u.WindowFromPoint(w.POINT(*screen))!=session.hwnd:raise RuntimeError('怪物位置被其他窗口遮挡')
        identity={'address':address,'name':target['name']}
        # Hover only when selecting a different target. Never click to cast.
        same_lock=locked==identity
        if not same_lock:session.u.SetCursorPos(*screen);session.pause(.12)
        if session.read(address+0xac,1)!=b'\0':return {'status':'target_dead'}
        key=Input();key.type=1;key.data.ki.vk=0x70
        if session.u.SendInput(1,ctypes.byref(key),ctypes.sizeof(Input))!=1:raise RuntimeError('F1按下失败')
        try:session.pause(.15)
        finally:
            key.data.ki.flags=2;session.u.SendInput(1,ctypes.byref(key),ctypes.sizeof(Input))
        session.pause(.65)
        return {'status':'cast_sent','target':target,'point':point,'key':'F1','position':session.player(),'lock_candidate':identity,'aimed':not same_lock,'effect_verified':False}
    finally:session.u.SetThreadDpiAwarenessContext(previous)


def run_island(session,seconds=600,player_spells=False):
    import time
    from background_sale import ForegroundSession
    if player_spells and not isinstance(session,ForegroundSession):raise RuntimeError('玩家雷电术需要前台模式；后台只允许英雄战斗')
    locked=None;combat_loot_after=0;first_seen={}
    log=ROOT/'outputs'/'孤岛循环日志.jsonl';deadline=time.monotonic()+seconds;levels=0;casts=0;observed={};activated=set()
    def record(event):
        with log.open('a',encoding='utf8') as out:out.write(json.dumps(dict(event,time=time.time()),ensure_ascii=False)+'\n')
    record({'event':'start','seconds':seconds,'combat':'lightning_and_hero' if player_spells else 'hero_only','player_spell_input':player_spells})
    while time.monotonic()<deadline and levels<60:
        session.check()
        if session.login_stage()!='playing':raise RuntimeError('死亡或掉线，停止孤岛循环')
        npcs=[n for n in session.npcs() if n['name']=='孤岛挑战' and tuple(n['map']) in {(19,11),(26,18),(19,25),(13,18)}]
        if len(npcs)<3:
            town=session.in_mengzhong_return_area()
            return {'status':'completed' if town else 'left_island_unconfirmed','transitions':levels,'casts':casts,'completion_verified':town}
        from inventory_flow import ensure_loot_capacity
        ensure_loot_capacity(session)
        sample=session.nearby_monsters(radius=50)
        alive=[m for m in sample['monsters'] if not m['dead']]
        if alive:
            from ground_item_probe import ground_snapshot
            drops=ground_snapshot(session)['ground_maps'][0]['items']
            now=time.monotonic()
            for drop in drops:
                if drop['id'] not in first_seen:
                    first_seen[drop['id']]=now
                    record({'event':'drop_seen','id':drop['id'],'name':drop['name'],'position':[drop['x'],drop['y']]})
            occupied={tuple(m['position']) for m in alive}
            blocked_ids={r['id'] for r in drops if (r['x'],r['y']) in occupied}
            if time.monotonic()>=combat_loot_after and any(r['id'] not in blocked_ids for r in drops):
                if session.visible('merchant'):session.close_panels()
                result=loot_island(session,combat=True,blocked_ids=blocked_ids);record({'event':'combat_loot','result':result})
                gained=any(r.get('verified') for r in result.get('results',[]))
                combat_loot_after=time.monotonic()+(0 if gained else 3)
                if result['status']=='stopped_unverified':return {'status':'loot_incomplete','result':result}
                if gained:continue  # Drain accessible drops before activation or player casting.
                # Re-sample actors after pickup movements.
                sample=session.nearby_monsters(radius=50);alive=[m for m in sample['monsters'] if not m['dead']]
                if not alive:continue
            if session.visible('merchant'):session.close_panels()
            for monster in alive:
                identity=monster.get('address');xy=tuple(monster['position'])
                if identity in observed and observed[identity]!=xy:activated.add(identity)
                observed[identity]=xy
                if monster['distance']<=2:activated.add(identity)
            sculptures=[m for m in alive if m['class']=='TSculptureMon' and m.get('address') not in activated]
            if sculptures:
                drop_tiles={(r['x'],r['y']) for r in drops}
                target=min(sculptures,key=lambda m:(tuple(m['position']) not in drop_tiles,m['distance']))
                result=approach_sculpture(session,target_address=target['address'],max_steps=1);record({'event':'activate','target':target,'result':result})
            elif player_spells:
                result=cast_lightning(session,locked=locked,priority_positions={(r['x'],r['y']) for r in drops});record({'event':'cast','result':result})
                if result['status']=='cast_sent':casts+=1
                locked=result.get('lock_candidate')
            else:
                session.pause(.6)
            continue
        # Confirm an empty scene again before looting/changing level.
        session.pause(.3)
        if session.nearby_monsters(radius=50)['loaded_monster_alive']:continue
        from ground_item_probe import ground_snapshot
        if session.visible('merchant') and ground_snapshot(session)['ground_maps'][0]['items']:session.close_panels()
        result=loot_island(session);record({'event':'loot','result':result})
        if result['status']=='waiting_for_monsters':continue
        if result['status']!='complete':return {'status':'loot_incomplete','levels':levels,'casts':casts,'result':result}
        result=open_corner(session);record({'event':'npc','result':result})
        if not result['merchant_visible']:return {'status':'npc_not_open','levels':levels,'casts':casts}
        result=next_level(session);record({'event':'next_level','result':result})
        if result['status']=='left_island':
            town=session.in_mengzhong_return_area()
            return {'status':'completed' if town else 'left_island_unconfirmed','transitions':levels+1,'casts':casts,'completion_verified':town}
        if result['status']!='transition_confirmed':return {'status':'transition_unconfirmed','levels':levels,'casts':casts}
        levels+=1;locked=None;first_seen.clear();observed.clear();activated.clear();session.pause(.8)
    return {'status':'test_complete','levels':levels,'casts':casts}
