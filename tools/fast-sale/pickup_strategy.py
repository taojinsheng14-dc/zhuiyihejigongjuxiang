"""Shared scripted-loot priority and bounded hero following; no combat keys."""
import struct


def hero_blocks_pickup(sample,drop):
    if not sample.get('hero'):return False
    hx,hy=sample['hero'];px,py=48*(drop['x']-hx),64+32*(drop['y']-hy)
    return -28<=px<=28 and -16<=py<=80


def choose(drops,monsters,hero,position,preferred=None):
    alive=[m for m in monsters if not m.get('dead')]
    occupied={tuple(m['position']) for m in alive}
    eligible=[d for d in drops if d.get('key_matches',True) and (d['x'],d['y']) not in occupied and not hero_blocks_pickup({'hero':hero},d)]
    def nearest(rows):
        return next((d for d in rows if d['id']==preferred),None) or min(rows,key=lambda d:((d['x']-position[0])**2+(d['y']-position[1])**2,d['id']))
    if eligible:return 'pickup',nearest(eligible)
    if alive:return 'combat',None
    blocked=[d for d in drops if hero_blocks_pickup({'hero':hero},d)]
    if blocked:return 'lead_hero',nearest(blocked)
    return ('wait',None) if drops else ('clear',None)


def context(session):
    session.check()
    if session.login_stage()!='playing':raise RuntimeError('拾取调度时角色状态不明')
    sample=session.nearby_monsters(radius=50)
    if sample.get('read_errors'):raise RuntimeError('拾取调度时怪物列表不完整')
    own=session.uint(session.uint(session.base+0x2bac2c));hero=session.uint(own+0x358)
    hero_xy=struct.unpack('<2i',session.read(hero+0x68,8)) if hero and session.hero_ready() else None
    return {'position':tuple(session.player()),'hero':hero_xy,'monsters':sample['monsters'],'npcs':session.npcs()}


def hero_follow_goal(sample,tilemap,drop=None,excluded=(),radius=6):
    current=tuple(sample['position']);hero=tuple(sample['hero']);anchor=(drop['x'],drop['y']) if drop else hero
    if drop is None and max(abs(current[i]-hero[i]) for i in (0,1))>=4:return current
    blocked={tuple(m['position']) for m in sample['monsters']}|{tuple(n['map']) for n in sample['npcs']}|{hero}
    candidates=[]
    for x in range(anchor[0]-radius,anchor[0]+radius+1):
        for y in range(anchor[1]-radius,anchor[1]+radius+1):
            goal=(x,y);distance=max(abs(x-anchor[0]),abs(y-anchor[1]))
            if not (distance==radius if drop else 4<=distance<=radius) or goal in blocked or goal in excluded or not tilemap.free(goal):continue
            if drop and max(abs(goal[i]-hero[i]) for i in (0,1))<4:continue
            try:path=tilemap.path(current,goal,blocked)
            except RuntimeError:continue
            if 1<len(path)<=radius*2:candidates.append((len(path),distance,goal))
    return min(candidates)[2] if candidates else None


def lead_hero(session,drop,sample):
    from island_automation import clickable_move,checked_movement
    from ground_item_probe import ground_actor_boxes,wait_pickup_position
    from background_sale import BackgroundSession
    if any(not m.get('dead') for m in sample['monsters']):return {'status':'combat_required','verified':False,'id':drop['id']}
    if any(session.visible(k) for k in ('bag','merchant','sell')):return {'status':'hero_wait','verified':False,'id':drop['id'],'game_input_sent':False}
    before=session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)
    tilemap=session.navigation_map(before);current=tuple(session.stable_player())
    states=getattr(session,'_pickup_lead_state',{});session._pickup_lead_state=states
    key=(before,drop['id'],drop['name'],drop['x'],drop['y'])
    # Keep only the current obstruction: reused ground IDs must not inherit old attempts.
    for old_key in list(states):
        if old_key!=key:del states[old_key]
    state=states.setdefault(key,{'moves':0,'waits':0,'excluded':[],'goal':None})
    def result(status,**extra):return dict(status=status,verified=False,id=drop['id'],name=drop['name'],**extra)
    if current!=tuple(sample['position']):return result('hero_wait',game_input_sent=False)
    if state['moves']>=18 or len(state['excluded'])>=3:raise RuntimeError('清场后英雄遮挡经有限引离仍未解除，保留物品现场')
    if state['goal']==current:
        state['waits']+=1
        if state['waits']<3:session.pause(.5);return result('hero_wait',game_input_sent=False)
        state['excluded'].append(state['goal']);state['goal']=None;state['waits']=0
    if state['goal'] is None:
        state['goal']=hero_follow_goal(sample,tilemap,drop,state['excluded'],radius=8)
        if state['goal'] is None:raise RuntimeError('清场后英雄遮挡目标，没有已核对的引离路线')
    blocked={tuple(n['map']) for n in sample['npcs']}|{tuple(sample['hero'])}
    own=session.uint(session.uint(session.base+0x2bac2c));draw=struct.unpack('<2i',session.read(own+0x17c,8))
    selected=clickable_move(current,[state['goal']],tilemap,blocked,draw,session.client_size(),ground_actor_boxes(session))
    if selected is None:
        state['excluded'].append(state['goal']);state['goal']=None
        return result('hero_wait',game_input_sent=False)
    destination,button,point=selected
    session.check()
    if session.login_stage()!='playing' or session.held_item() or session.sale_item() or session.inflight_item():raise RuntimeError('引离英雄前角色或物品状态不明')
    if session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)!=before:raise RuntimeError('引离英雄前地图变化')
    BackgroundSession.background_mouse(session,point,button,track_movement=False,move_settle=.12,dpi_scaled=True,button_hold=.15)
    after=wait_pickup_position(session,destination)
    if session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)!=before:raise RuntimeError('引离英雄期间地图变化')
    movement=checked_movement(tilemap,current,destination,after,{tuple(n['map']) for n in sample['npcs']})
    state['moves']+=1
    if movement['status']=='blocked':state['excluded'].append(state['goal']);state['goal']=None
    session.pause(.5)
    return result('hero_moved' if movement['status']=='moved' else 'hero_wait',game_input_sent=True,movement=movement,goal=state['goal'])
