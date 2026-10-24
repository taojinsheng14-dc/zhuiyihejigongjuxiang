"""Cooperative island automation. Read-only state + ordinary background input only."""
import json
import struct
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import instance_context
import island_challenge as legacy

ROOT=instance_context.runtime_root()
ISLAND_HEADER=bytes.fromhex('280028000d4c6567656e64206f66206d69720000e93c4000e93c40002400880014001900d082cd0300000000287e440000000000')
class TransientScene(RuntimeError):
    pass


CORNERS={(19,11),(26,18),(19,25),(13,18)}


def confirmed_corner_npcs(session,npcs):
    corners=[n for n in npcs if n['name']=='孤岛挑战' and tuple(n['map']) in CORNERS]
    proof=getattr(session,'_island_open_corner',None)
    if (len(corners)<3 and proof and session.visible('merchant')
            and getattr(session,'active_merchant',None)=='孤岛挑战'
            and tuple(session.player())==tuple(proof['position']) and header(session)==ISLAND_HEADER):
        npc=proof['npc']
        session.verified_npc_draw(npc)
        if not any(n['address']==npc['address'] for n in corners):corners.append(npc)
    return corners


def header(session):
    return session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)


def log(event,**fields):
    path=ROOT/'outputs'/'孤岛自动流程.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf8') as out:
        out.write(json.dumps(dict(event=event,time=time.time(),instance=instance_context.slot(),**fields),ensure_ascii=False)+'\n')


def observe(session):
    from ground_item_probe import ground_snapshot
    session.check()
    if session.login_stage()!='playing':raise RuntimeError('孤岛角色死亡、掉线或未知提示，停止；不自动小退')
    before=header(session)
    if before!=ISLAND_HEADER:
        if session.in_mengzhong_return_area():return {'town':True}
        raise RuntimeError('当前地图不是已核对的孤岛或土城，停止')
    if session.held_item() or session.sale_item() or session.inflight_item():raise RuntimeError('物品操作状态不空，停止孤岛输入')
    if not session.hero_ready():raise TransientScene('英雄未就绪，停止孤岛；未发送玩家F1')
    sample=session.nearby_monsters(radius=50)
    if sample.get('read_errors',0):raise TransientScene('怪物列表读取不完整，不能当成已清场')
    try:ground=ground_snapshot(session)['ground_maps'][0]
    except RuntimeError as error:
        if str(error) in ('地面表变化，暂停拾取','采样期间地图变化'):raise TransientScene(str(error)) from error
        raise
    if not ground.get('stable') or ground.get('error'):raise TransientScene('地面列表不完整，不能当成已拾完')
    npcs=session.npcs()
    corners=confirmed_corner_npcs(session,npcs)
    if len({tuple(n['map']) for n in corners})<3:raise TransientScene('孤岛场景尚未完整加载，停止；不误判已返回')
    own=session.uint(session.uint(session.base+0x2bac2c));hero=session.uint(own+0x358)
    hero_xy=struct.unpack('<2i',session.read(hero+0x68,8)) if hero else None
    if header(session)!=before:raise TransientScene('孤岛采样时正在切图，停止本次输入')
    from island_pickup_policy import filter_drops
    drops,ignored=filter_drops(ground['items'])
    return {'town':False,'position':tuple(session.player()),'hero':hero_xy,'npcs':npcs,
            'monsters':[m for m in sample['monsters'] if not m['dead']],
            'drops':drops,'ignored_drop_names':[d['name'] for d in ignored],
            'free':session.inventory().count('')}


class Scheduler:
    """Sticky nearest eligible target, per-item backoff, and stable empty-scene gate."""
    def __init__(self):
        self.target=None;self.failures={};self.retry_at={};self.empty_since=None
        self.empty_samples=0;self.progress_at=None;self.last_fingerprint=None

    def choose(self,sample,now):
        if sample.get('town'):return ('completed',None)
        alive=sample['monsters'];drops=sample['drops'];position=sample['position']
        fingerprint=(tuple(sorted((m.get('address'),m.get('name'),tuple(m['position'])) for m in alive)),
                     tuple(sorted(d['id'] for d in drops)),position)
        if fingerprint!=self.last_fingerprint or self.progress_at is None:
            self.progress_at=now;self.last_fingerprint=fingerprint
        if now-self.progress_at>120:return ('stop','两分钟未观察到怪物、掉落或坐标推进')
        if alive or drops:self.empty_since=None;self.empty_samples=0
        if drops and sample['free']<1:return ('stop','人物背包已满，保留现场；未自动出售或回城')
        occupied={tuple(m['position']) for m in alive}
        eligible=[d for d in drops if d.get('key_matches') and (d['x'],d['y']) not in occupied
                  and self.failures.get(d['id'],0)<3 and now>=self.retry_at.get(d['id'],0)]
        from pickup_strategy import choose
        loot_action,selected=choose(eligible,alive,sample.get('hero'),position,preferred=self.target)
        if loot_action in ('pickup','lead_hero'):
            self.target=selected['id'];return ('pickup',selected)
        if alive:
            # Drop blockers first, then unactivated sculpture, then a distant live monster.
            drop_tiles={(d['x'],d['y']) for d in drops}
            candidates=[m for m in alive if max(abs(m['position'][i]-position[i]) for i in (0,1))>2]
            if candidates:
                target=min(candidates,key=lambda m:(tuple(m['position']) not in drop_tiles,
                    m.get('class')!='TSculptureMon',max(abs(m['position'][i]-position[i]) for i in (0,1))))
                return ('approach',target)
            return ('wait',None)
        if drops:
            if any(self.failures.get(d['id'],0)>=3 for d in drops):return ('stop','同一掉落三次受阻，保留现场，不盲目换关')
            return ('wait',None)
        self.target=None
        self.empty_samples+=1
        if self.empty_since is None:self.empty_since=now
        return ('advance',None) if self.empty_samples>=3 and now-self.empty_since>=1 else ('wait',None)

    def feedback(self,drop,result,now):
        uid=drop['id'];status=result.get('status')
        if result.get('verified'):
            self.target=None;self.progress_at=now;self.failures.pop(uid,None);self.retry_at.pop(uid,None)
        elif status in ('approaching','hero_moved'):
            self.progress_at=now
        elif status=='blocked':
            self.target=None;count=self.failures.get(uid,0)+1;self.failures[uid]=count
            self.retry_at[uid]=now+min(3,count)
        elif status in ('hero_occupied','actor_occluded','hero_wait','combat_required'):
            self.target=None;self.retry_at[uid]=now+1
        elif status in ('removed_at_target','unverified') and not result.get('ground_remaining',True):
            # Gone without inventory proof may be another player/expiry. Never count as picked.
            self.target=None
        elif status=='no_target':self.target=None
        else:raise RuntimeError('拾取结果未核对，停止：'+str(status or result.get('error_detail')))


from pickup_strategy import hero_blocks_pickup,hero_follow_goal


def clickable_move(current,goals,tilemap,blocked,draw,size,boxes):
    """Choose an actual clickable first move, including a short terrain detour."""
    from ground_item_probe import pickup_aim
    baseline=[]
    for goal in goals:
        try:baseline.append(len(tilemap.path(current,goal,blocked))-1)
        except RuntimeError:pass
    if not baseline:return None
    max_cost=min(baseline)+4;options=[]
    for dx,dy in ((0,-1),(1,0),(0,1),(-1,0),(-1,-1),(1,-1),(1,1),(-1,1)):
        for reach,button in ((2,'right'),(1,'left')):
            destination=(current[0]+dx*reach,current[1]+dy*reach)
            tiles=[(current[0]+dx*n,current[1]+dy*n) for n in range(1,reach+1)]
            if any(p in blocked or not tilemap.free(p) for p in tiles):continue
            if dx and dy and any(not tilemap.free((current[0]+dx*n,current[1]+dy*(n-1)))
                                 or not tilemap.free((current[0]+dx*(n-1),current[1]+dy*n)) for n in range(1,reach+1)):continue
            try:point=pickup_aim(current,destination,draw,tilemap,blocked,size,avoid_boxes=boxes,button=button)
            except RuntimeError:continue
            for goal in goals:
                try:remaining=len(tilemap.path(destination,goal,blocked))-1
                except RuntimeError:continue
                cost=reach+remaining
                if cost<=max_cost:options.append((cost,remaining,-reach,destination,button,point))
    if not options:return None
    best=min(options)
    return best[3:]


def checked_movement(tilemap,current,destination,after,static_blocked=()):
    current,destination,after=tuple(current),tuple(destination),tuple(after)
    if not tilemap.free(after) or max(abs(after[i]-current[i]) for i in (0,1))>4:
        raise RuntimeError('孤岛实际移动超出可核对的本地范围')
    if after==current:return {'status':'blocked','from':current,'to':after,'expected':destination}
    # Accept a bounded client detour only if the actual endpoint is connected
    # by a short walkable route that avoids the fixed NPC tiles.
    route=tilemap.path(current,after,set(static_blocked))
    if len(route)>7:raise RuntimeError('孤岛实际位置无法通过已核对的短路网连接')
    return {'status':'moved','from':current,'to':after,'expected':destination,
            'replanned_after_actual_movement':after!=destination,'verified_local_path':route}


def move_one(session,sample,target,stand_radius=2):
    """At most one one/two-tile mouse action; then yield to a new drop scan."""
    from ground_item_probe import choose_pickup_move,pickup_aim,wait_pickup_position,ground_actor_boxes
    from background_sale import BackgroundSession
    if header(session)!=ISLAND_HEADER:raise RuntimeError('移动前孤岛地图变化')
    if session.held_item() or session.sale_item() or session.inflight_item():raise RuntimeError('物品状态不明，禁止移动')
    tilemap=session.navigation_map(ISLAND_HEADER);current=tuple(session.stable_player());target=tuple(target)
    if current!=tuple(sample['position']):
        return {'status':'resample','from':sample['position'],'to':current,'game_input_sent':False}
    blocked={tuple(m['position']) for m in sample['monsters']}|{tuple(n['map']) for n in sample['npcs']}
    if sample['hero'] and sample['hero']!=current:blocked.add(tuple(sample['hero']))
    choices=[]
    for x in range(target[0]-stand_radius,target[0]+stand_radius+1):
        for y in range(target[1]-stand_radius,target[1]+stand_radius+1):
            goal=(x,y)
            if goal in blocked or not tilemap.free(goal) or goal==current:continue
            try:path=tilemap.path(current,goal,blocked)
            except RuntimeError:continue
            if len(path)>1:choices.append(path)
    if not choices:return {'status':'blocked'}
    own=session.uint(session.uint(session.base+0x2bac2c));draw=struct.unpack('<2i',session.read(own+0x17c,8))
    selected=clickable_move(current,[p[-1] for p in choices],tilemap,blocked,draw,session.client_size(),ground_actor_boxes(session))
    if selected is None:
        return {'status':'blocked','reason':'NPC或怪物模型遮挡，等待新采样'}
    destination,button,point=selected
    session.check()
    BackgroundSession.background_mouse(session,point,button,track_movement=False)
    after=tuple(session.stable_player())
    if header(session)!=ISLAND_HEADER:raise RuntimeError('移动期间地图变化')
    if session.login_stage()!='playing':raise RuntimeError('移动后角色状态不明，停止核对')
    if session.held_item() or session.sale_item() or session.inflight_item():raise RuntimeError('移动后物品状态不空，停止核对')
    try:result=checked_movement(tilemap,current,destination,after,{tuple(n['map']) for n in sample['npcs']})
    except RuntimeError:
        log('movement_deviation',before=current,after=after,expected=destination,point=point,button=button)
        raise
    if result.get('replanned_after_actual_movement'):
        log('movement_resampled',point=point,button=button,**result)
    return result


def pick_one(session,drop):
    from ground_item_probe import pickup_current_test
    return pickup_current_test(session,names=None,radius=25,max_steps=1,cooperative=True,target_id=drop['id'])


def run_loop(session,progress=lambda text:None,seconds=7200,transitions=0,on_transition=lambda n:None,melee=None):
    from inventory_flow import ensure_loot_capacity
    scheduler=Scheduler();deadline=time.monotonic()+seconds;picked=0;last_action=None;unstable_since=None;hero_unblocks={};combat_deferred=set();panel_wait=False
    if session.visible('merchant') and not getattr(session,'_island_open_corner',None):session.close_panels()
    while time.monotonic()<deadline:
        session.check()
        if session.visible('bag'):
            if session.held_item() or session.sale_item() or session.inflight_item():raise RuntimeError('背包打开且物品状态不空，停止孤岛输入')
            if session.login_stage()!='playing' or header(session)!=ISLAND_HEADER:raise RuntimeError('背包等待时角色或孤岛地图未核对')
            if not panel_wait:progress('孤岛：背包打开，等待关闭后继续');log('bag_open_wait');panel_wait=True
            session.pause(.2);continue
        if panel_wait:log('bag_closed_resume');panel_wait=False
        try:sample=observe(session)
        except TransientScene as error:
            if unstable_since is None:unstable_since=time.monotonic()
            if time.monotonic()-unstable_since>=8:raise RuntimeError('孤岛加载或采样八秒未稳定：'+str(error)) from error
            session.pause(.2);continue
        unstable_since=None
        if not sample.get('town'):
            capacity=ensure_loot_capacity(session,progress)
            if capacity['transferred']:
                log('bag_transfer',result=capacity);scheduler=Scheduler();hero_unblocks={};last_action=None
                continue
            sample['free']=capacity['main_free']
        if sample.get('monsters'):
            for blocked_drop in sample['drops']:
                if hero_blocks_pickup(sample,blocked_drop):
                    uid=blocked_drop['id'];hero_unblocks.pop(uid,None)
                    if uid not in combat_deferred:
                        log('pickup_deferred_for_combat',drop=blocked_drop,hero=sample['hero']);combat_deferred.add(uid)
        now=time.monotonic();action,target=scheduler.choose(sample,now)
        if melee is not None and action in ('approach','wait') and sample.get('monsters'):
            if session.visible('merchant') or session.visible('bag'):session.close_panels()
            result=melee.step(session,sample)
            if result.get('clicked'):progress('孤岛：微笑主体单击选怪近战，等待游戏持续攻击');log('main_melee_click',result=result)
            if result.get('clicked') or result.get('health_progress'):scheduler.progress_at=now
            if result.get('engaged'):session.pause(.2);continue
        if action!=last_action:
            progress({'pickup':'孤岛：优先拾取掉落','approach':'孤岛：靠近激活或带英雄接敌',
                      'advance':'孤岛：已核对清场，准备换关','wait':'孤岛：等待英雄战斗或现场稳定',
                      'completed':'孤岛：确认返回土城','stop':'孤岛：保留现场停止'}[action]);last_action=action
        if action=='completed':return {'status':'completed','completion_verified':True,'transitions':transitions,'picked_verified':picked,'main_melee_clicks':melee.clicks if melee is not None else 0}
        if action=='stop':raise RuntimeError(str(target))
        if action=='pickup':
            if melee is not None:melee.reset()
            if session.visible('merchant') or session.visible('bag'):session.close_panels()
            hero_unblocks.pop(target['id'],None);combat_deferred.discard(target['id'])
            result=pick_one(session,target);scheduler.feedback(target,result,time.monotonic())
            picked+=int(bool(result.get('verified')));log('pickup',result=result)
        elif action=='approach':
            if melee is not None:melee.reset()
            if session.visible('merchant') or session.visible('bag'):session.close_panels()
            result=move_one(session,sample,target['position']);log('approach',target=target['position'],result=result)
        elif action=='advance':
            if melee is not None:melee.reset()
            # A final NPC request is still needed on floor 60. Request counts
            # are not floor numbers, and completion requires verified town.
            if transitions>=128:raise RuntimeError('已确认128次换关仍未返回土城，停止核对；次数不当作层数')
            if not session.visible('merchant'):
                session.close_panels()
                if open_corner(session) is False:
                    scheduler=Scheduler();last_action=None;continue
            # Re-read everything after opening the dialog; old empty samples are insufficient.
            fresh=observe(session)
            if fresh.get('town'):continue
            if fresh['monsters'] or fresh['drops']:session.close_panels();scheduler=Scheduler();continue
            result=legacy.next_level(session);log('transition',result=result)
            if result['status']=='left_island':
                if not session.in_mengzhong_return_area():raise RuntimeError('退出地图但未确认土城')
                transitions+=1;on_transition(transitions)
                return {'status':'completed','completion_verified':True,'transitions':transitions,'picked_verified':picked,'main_melee_clicks':melee.clicks if melee is not None else 0}
            if result['status']!='transition_confirmed':raise RuntimeError('换关结果不明，停止；不重复掷骰')
            transitions+=1;on_transition(transitions);scheduler=Scheduler();last_action=None
        session.pause(.2)
    raise RuntimeError('孤岛达到两小时运行上限，保留现场，可核对后接续')


def open_corner(session):
    for attempt in range(6):
        session.check()
        session.stable_player()
        sample=observe(session)
        if sample.get('town') or sample['monsters'] or sample['drops']:return False
        known=[n for n in sample['npcs'] if n['name']=='孤岛挑战' and tuple(n['map']) in CORNERS]
        clickable=[n for n in known if session.npc_click_point(n['draw']) is not None]
        if clickable:
            npc=min(clickable,key=lambda n:max(abs(n['map'][i]-sample['position'][i]) for i in (0,1)))
            session.open_npc(npc)
            if not session.visible('merchant'):raise RuntimeError('角落NPC对话未打开，停止')
            session._island_open_corner={'npc':npc,'position':tuple(session.player())}
            return True
        log('corner_not_clickable',attempt=attempt+1,position=sample['position'],npcs=known)
        if attempt>=2 and known:
            npc=min(known,key=lambda n:max(abs(n['map'][i]-sample['position'][i]) for i in (0,1)))
            moved=move_one(session,sample,npc['map'],stand_radius=3)
            log('corner_approach',npc=npc['map'],result=moved)
        session.pause(.25)
    raise RuntimeError('换关NPC经重采样和有限靠近仍不可点击，保留现场')


def role_key(session):
    actor=session.uint(session.uint(session.base+0x2bac2c));ptr=session.uint(actor+0xc);size=session.uint(ptr-4)
    if not 1<=size<=60:raise RuntimeError('角色名称未核对')
    role=session.read(ptr,size).decode('gb18030')
    today=datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    return role+'|'+today


def locate_town_entrance(session,progress=lambda text:None):
    from map_navigation import veteran_run_path
    import struct
    target=(317,331)
    if not session.in_mengzhong_return_area():raise RuntimeError('孤岛入口靠近仅允许已核对的土城')
    session.close_panels()
    original=header(session);tilemap=session.navigation_map(original)
    if tilemap.name.lower()!='3.map':raise RuntimeError('未核对土城地图，未靠近孤岛入口')
    stuck=0
    for _ in range(16):
        session.check()
        if session.login_stage()!='playing':raise RuntimeError('靠近孤岛入口时界面不在游戏中')
        if header(session)!=original:raise RuntimeError('靠近孤岛入口时地图变化，停止')
        if session.held_item() or session.sale_item() or session.inflight_item():raise RuntimeError('靠近入口前物品状态不空')
        actors=session.npcs()
        if any(n['name']=='孤岛挑战' and tuple(n['map'])==target for n in actors):return session.unique_npc('孤岛挑战',target)
        current=tuple(session.stable_player())
        if max(abs(current[i]-target[i]) for i in (0,1))>30:raise RuntimeError('孤岛入口距离超出短距靠近范围')
        blocked={tuple(n['map']) for n in actors};blocked.add(target)
        goals=[(x,y) for x in range(309,326) for y in range(323,340)
               if 2<=max(abs(x-317),abs(y-331))<=8 and (x,y) not in blocked and tilemap.free((x,y))]
        path=veteran_run_path(tilemap,current,goals,blocked,target=target)
        if len(path)<2:raise RuntimeError('已在孤岛入口加载范围但未读到NPC，停止；未入场')
        destination=path[1];dx=(destination[0]-current[0])//2;dy=(destination[1]-current[1])//2
        actor=session.uint(session.uint(session.base+0x2bac2c))
        draw=struct.unpack('<2i',session.read(actor+0x17c,8));point=None
        for reach in (3,2):
            aim=(current[0]+dx*reach,current[1]+dy*reach)
            if any(not min(current[i],target[i])<=aim[i]<=max(current[i],target[i]) for i in (0,1)):continue
            if not tilemap.free(aim) or aim in blocked:continue
            candidate=(draw[0]+dx*48*reach,draw[1]+64+dy*32*reach)
            if abs(candidate[0]-draw[0])<=24 and draw[1]-12<=candidate[1]<=draw[1]+72:continue
            width,height=session.client_size()
            if 20<candidate[0]<width-20 and 20<candidate[1]<height-180:point=candidate;break
        if point is None:raise RuntimeError('孤岛入口无安全跑动点，未盲点')
        progress('孤岛入口尚未加载，向已知坐标短距靠近；NPC加载后立即停止')
        session.background_mouse(point,'right',track_movement=False)
        after=tuple(session.stable_player())
        if any(not min(current[i],target[i])<=after[i]<=max(current[i],target[i]) for i in (0,1)):
            raise RuntimeError('靠近孤岛入口超出同侧边界，停止')
        stuck=stuck+1 if after==current else 0
        if stuck>=3:raise RuntimeError('孤岛入口连续三次未移动，停止；未入场')
    raise RuntimeError('孤岛入口靠近达到有限次数，未入场')


def run(session,progress=lambda text:None,resume=False,manual_request=False):
    import importlib,ground_item_probe,island_pickup_policy
    importlib.reload(ground_item_probe);importlib.reload(island_pickup_policy)
    key=role_key(session);state=json.loads(legacy.STATE.read_text(encoding='utf8')) if legacy.STATE.exists() else {}
    old=state.get(key)
    if resume:
        if not old:
            role=key.rsplit('|',1)[0]
            previous=[(k,v) for k,v in state.items() if k.rsplit('|',1)[0]==role
                      and v.get('status')=='entered' and v.get('game_pid')==session.reader.pid
                      and v.get('instance',instance_context.slot())==instance_context.slot()
                      and v.get('map_header')==ISLAND_HEADER.hex()]
            if len(previous)==1:key,old=previous[0]
        if not old or old.get('status')!='entered' or old.get('map_header')!=ISLAND_HEADER.hex():raise RuntimeError('没有本角色今日已确认的孤岛进入记录，禁止猜测接续')
        if header(session)!=ISLAND_HEADER:raise RuntimeError('当前不在孤岛，未输入')
        if old.get('game_pid') not in (None,session.reader.pid):raise RuntimeError('进入记录属于旧客户端，先核对身份；未自动改绑')
    else:
        if old and not manual_request:raise RuntimeError('本角色今日已记录进入或尝试，禁止重复进入')
        if not session.in_mengzhong_return_area():raise RuntimeError('每日孤岛请从土城开始，不会退出当前挂机图')
        session.close_panels()
        npc=locate_town_entrance(session,progress);session.open_npc(npc)
        entry=legacy.enter_once(session,verified_npc=npc,**({'manual_request':True} if manual_request else {}))
        if entry['status']!='entered' or header(session)!=ISLAND_HEADER:raise RuntimeError('孤岛进入未确认；已保留每日记录，不重复点击')
        state=json.loads(legacy.STATE.read_text(encoding='utf8'));old=state[key]
    old.update(game_pid=session.reader.pid,instance=instance_context.slot())
    def save():
        legacy.STATE.parent.mkdir(parents=True,exist_ok=True)
        temp=legacy.STATE.with_suffix('.tmp');temp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(legacy.STATE)
    def transitioned(n):old['transitions']=n;old['updated']=time.time();save()
    save();guard=getattr(session,'_sale_recovery_enabled',False);session._sale_recovery_enabled=False
    try:
        if not session.hero_ready():
            progress('孤岛进图后英雄未就绪，使用已验证召唤按钮确认一次；不发送玩家F1')
            session.check()
            if header(session)!=ISLAND_HEADER or session.login_stage()!='playing':raise RuntimeError('召唤英雄前孤岛现场未核对')
            if session.held_item() or session.sale_item() or session.inflight_item():raise RuntimeError('召唤英雄前物品状态不空')
            session.ensure_hero_available()
        melee=None
        if key.rsplit('|',1)[0]=='微笑':
            import island_melee
            importlib.reload(island_melee)
            melee=island_melee.Melee()
            progress('孤岛微笑战士：主体后台单击选怪近战＋英雄，沿用本轮入场与拾取换关记录')
        result=run_loop(session,progress,transitions=old.get('transitions',0),on_transition=transitioned,melee=melee)
        old.update(status='completed',completion_verified=True,updated=time.time());save();log('completed',result=result);return result
    except Exception as error:
        old.update(last_error=str(error),updated=time.time());save();log('stopped',reason=str(error));raise
    finally:session._sale_recovery_enabled=guard


def status(session):
    current=header(session);key=role_key(session)
    saved=json.loads(legacy.STATE.read_text(encoding='utf8')) if legacy.STATE.exists() else {}
    return {'game_input_sent':False,'instance':instance_context.slot(),'in_island':current==ISLAND_HEADER,
            'today_entry':saved.get(key),'native_autoplay_in_island_verified':False,
            'scripted_main_melee_enabled':key.rsplit('|',1)[0]=='微笑',
            'mode':('微笑主体后台单击近战＋英雄＋掉落优先，不发送玩家F1' if key.rsplit('|',1)[0]=='微笑' else '英雄战斗＋掉落优先分步调度，未发送玩家F1')}
