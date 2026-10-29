"""Verified normal-map mage profiles; named random stones only when authorized."""
import json
from instance_context import runtime_root
from combat_metrics import read_experience
from warrior_combat import HEADER as DUNGEON_HEADER

STONE_HEADER=bytes.fromhex('900190010f4c6567656e64206f66206d69720d0a908df227205ce640020b2e2e474d474a582e434f4d0000000000000000000000')
STONE_NAMES={'黑野猪','红野猪','白野猪','蝙蝠','角蝇','蝎蛇','楔蛾','黑色恶蛆'}


def header(session):return session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)


def load_avoid_players():
    path=runtime_root()/'outputs'/'当前地图挂机设置.json'
    if not path.exists():return False
    value=json.loads(path.read_text(encoding='utf8')).get('avoid_loaded_players',False)
    if type(value) is not bool:raise RuntimeError('当前地图避人设置无效')
    return value


def save_avoid_players(enabled):
    if type(enabled) is not bool:raise ValueError('避人随机开关必须是布尔值')
    path=runtime_root()/'outputs'/'当前地图挂机设置.json';path.parent.mkdir(parents=True,exist_ok=True)
    data=json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
    data['avoid_loaded_players']=enabled
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(path)


class PlayersDetected(RuntimeError):pass


class PanelOpen(RuntimeError):pass


class DeadEndDetected(RuntimeError):pass


class StoneTomb:
    character='厚礼蟹'
    combat_mode='mage'
    player_exception=PlayersDetected
    dead_end_exception=DeadEndDetected

    def __init__(self,avoid_players=None,map_header=STONE_HEADER,map_name='d715.map',map_stride=14):
        self.avoid_loaded_players=load_avoid_players() if avoid_players is None else avoid_players
        self.header=map_header;self.map_name=map_name;self.map_stride=map_stride
        self.label={'d715.map':'石墓五层','d601.map':'地牢东一层','d2010.map':'纵横道','d505.map':'祖玛五层'}.get(map_name,'当前地图')

    panel_exception=PanelOpen
    header=STONE_HEADER
    names=STONE_NAMES
    center_route=True
    route_spacing=24
    post_cast_wait=.05

    def manual_panels(self,session):
        if session.visible('bag'):return True
        if hasattr(session,'control_info'):
            hero=session.control_info(0x7b4,'Window_HeroItemBag')
            return bool(hero.get('object') and hero['visible'])
        return False

    def informational_message(self,session):
        # Exact local OCR allowlist; never confirms the dialog or transmits screenshots.
        if not hasattr(session,'capture_client') or not hasattr(session,'control_info'):return False
        box=session.control_info(0x3d8,'Window_MsgDlg')
        if not box['visible'] or tuple(box['bounds'][2:])!=(452,179):return False
        x,y,w,h=box['bounds'];cw,ch=session.client_size()
        if not (0<=x<x+w<=cw and 0<=y<y+h<=ch):return False
        from stone_hunt_cycle import recognize
        rows=recognize(session.capture_client().crop((x+20,y+34,x+420,y+64)))
        if len(rows)!=1 or rows[0]['score']<.95:return False
        text=''.join(rows[0]['text'].split()).rstrip('!！')
        return text=='您还没有加入行会'

    def manual_waiting(self,session):
        return bool(getattr(self,'_info_message_pause',False) or getattr(self,'_manual_pause',False) and (self.manual_panels(session)
            or session.login_stage()=='message' or session.held_item() or session.sale_item() or session.inflight_item()))

    def check_state(self,session):
        session.check()
        if header(session)!=self.header:raise RuntimeError('当前地图挂机地图或角色状态变化，停止')
        if self.manual_panels(session):self._manual_pause=True
        stage=session.login_stage()
        self._info_message_pause=False
        sample=read_experience(session)
        if sample['character']!=self.character:raise RuntimeError('当前地图角色与授权职业绑定不符')
        if stage!='playing':
            manual_message=stage=='message' and (getattr(self,'_manual_pause',False) or self.informational_message(session))
            self._info_message_pause=manual_message and not getattr(self,'_manual_pause',False)
            if manual_message:
                # A message masks login_stage's actor check: verify life and login windows independently.
                actor=sample['main']['actor']
                manual_message=(session.read(actor+0xac,1)==b'\0' and not any(session.control_info(offset,name)['visible']
                    for offset,name in ((0x3b0,'Window_Login'),(0x3fc,'Window_SelServer'),(0x41c,'Window_SelectChr'))))
            if not manual_message:raise RuntimeError('当前地图挂机地图或角色状态变化，停止')
        if (session.held_item() or session.sale_item() or session.inflight_item()) and not getattr(self,'_manual_pause',False):
            raise RuntimeError('当前地图挂机物品操作状态不空')
        if session.u.IsIconic(session.hwnd):raise RuntimeError('游戏已最小化，未挂机输入')

    def guard(self,session):
        self.check_state(session)
        if self.manual_waiting(session) or any(session.visible(k) for k in ('merchant','sell','bag')):
            raise PanelOpen('当前地图挂机人工面板或物品操作中，暂停输入')
        if self.avoid_loaded_players and session.nearby_players(None):raise PlayersDetected('已加载范围内发现其他玩家')

    def wait_for_panels(self,session):
        self.check_state(session)
        if self.manual_waiting(session):return True
        self._manual_pause=False
        if session.visible('merchant'):
            # Hunting never opens NPC transactions: dismiss only its verified close control.
            if not getattr(session,'_hunt_activity_close_attempted',False) and not session.visible('sell') and not session.visible('bag'):
                from fast_sale import button_center
                close=session.control_info(0x5e4,'Button_MerchantDlgClose')
                if close['visible']:
                    session._hunt_activity_close_attempted=True
                    session.click(button_center(session.bounds('merchant'),close['bounds']))
                    session.pause(.3)
                    self.check_state(session)
        else:session._hunt_activity_close_attempted=False
        return any(session.visible(k) for k in ('merchant','sell','bag'))

    def avoid_players(self,session,progress):
        self.check_state(session)
        if any(session.visible(k) for k in ('merchant','sell','bag')):return {'random_used':False,'reason':'panel_wait'}
        players=session.nearby_players(None)
        if not players:return {'random_used':False,'reason':'players_no_longer_loaded'}
        return self.random_escape(session,progress,'loaded_players',player_count=len(players))

    def confirm_dead_end(self,session):
        from warrior_combat import local_exits
        self.guard(session)
        first=local_exits(session,self.tilemap)
        if first['exits']:return False
        session.clear_background_mouse();session.pause(.3);self.guard(session)
        second=local_exits(session,self.tilemap)
        confirmed=first['position']==second['position'] and not second['exits']
        session.write_stats({'event':'dead_end_check','confirmed':confirmed,'first':first,'second':second})
        return confirmed

    def escape_dead_end(self,session,progress):
        if not self.confirm_dead_end(session):return {'random_used':False,'reason':'exit_reopened'}
        return self.random_escape(session,progress,'dead_end')

    def random_escape(self,session,progress,reason,**details):
        self.guard(session) if reason=='dead_end' else self.check_state(session)
        before=tuple(session.player());wallet_before=session.currency_snapshot()
        # A failed/uncertain attempt ends this command; never press another key blindly.
        if not any(row['name']=='随机传送石' and row.get('raw_98',1)>0 for row in session.shortcut_inventory()):raise RuntimeError('随机脱困缺少可用随机传送石，未购买或使用随机卷')
        session.clear_background_mouse()
        self.guard(session) if reason=='dead_end' else self.check_state(session)
        session.write_stats({'event':'random_attempt','reason':reason,'scope':'client_loaded','position':before,**details})
        progress('确认周围无合法出口，使用随机传送石脱困' if reason=='dead_end' else '已加载范围发现其他玩家，使用随机传送石避开；不要求无怪')
        session.press_named_hotkey(('随机传送石',),'random')
        try:
            session.wait(lambda:tuple(session.player())!=before,timeout=5)
            self.check_state(session)
            after=tuple(session.stable_player())
            if not self.tilemap.free(after):raise RuntimeError('随机落点不在已核对可走路网')
        except RuntimeError as error:
            session.write_stats({'event':'random_result','confirmed':False,'reason':reason,'error':str(error)})
            raise RuntimeError('随机落点未确认，停止且不重复按键：'+str(error)) from error
        wallet_after=session.currency_snapshot()
        session.write_stats({'event':'random_result','confirmed':True,'reason':reason,'before':before,'position':after})
        return {'random_used':True,'scope':'client_loaded','reason':reason,**details,'before':before,'after':after,'wallet_before':wallet_before,'wallet_after':wallet_after}

    def plan(self,session):
        from warrior_combat import patrol_plan
        if self.map_stride==14:
            result=patrol_plan(session,expected_header=self.header,expected_name=self.map_name,radius=None)
        elif self.map_stride==12:
            tilemap=session.navigation_map(self.header);start=tuple(session.player())
            if not tilemap.free(start) or header(session)!=self.header:raise RuntimeError('当前地图起点或身份未核对')
            result=(tilemap,{'map':self.map_name,'file_stride':12,'start':start,'waypoints':[start],'game_input_sent':False})
        else:raise RuntimeError('当前地图格子格式尚未支持')
        self.tilemap=result[0]
        return result

    def combat_classes(self):
        return {'TCatMon','TSculptureMon','TBeeQueen','TGasKuDeGi','TArcherMon'}

    def is_target(self,monster):
        from random_hunt import target_monsters
        kind=monster.get('class')
        if kind=='TArcherMon':
            if (self.map_name,monster.get('name')) not in {('d505.map','祖玛弓箭手'),('64.map','魔龙射手')}:return False
            monster=dict(monster,**{'class':'TCatMon'})
        return kind in self.combat_classes() and bool(target_monsters([monster],8))

    def needs_activation_evidence(self,monster):
        return (monster.get('class')=='TSculptureMon' or
                (self.map_name=='64.map' and monster.get('class') in self.combat_classes()
                 and monster.get('name','').startswith('魔龙')))

    def sculpture_active(self,session,monster,raw):
        import struct,time
        if not self.needs_activation_evidence(monster):return True
        identity=tuple(raw[a:b] for a,b in ((0,4),(12,16),(64,68)))
        position=struct.unpack_from('<2i',raw,0x68)
        hp=struct.unpack('<H',session.read(monster['address']+0x112,2))[0]
        maximum=struct.unpack('<H',session.read(monster['address']+0x11a,2))[0]
        now=time.monotonic();states=getattr(self,'_sculpture_states',{});old=states.get(monster['address'])
        active_until=0
        if old and old['identity']==identity:
            active_until=old['active_until']
            if position!=old['position'] or (hp>0 and old['hp']>0 and maximum>0 and old['maximum']>0 and hp!=old['hp']):active_until=now+5
        states[monster['address']]={'identity':identity,'position':position,'hp':hp,'maximum':maximum,'active_until':active_until}
        self._sculpture_states=states
        return 0<hp<=maximum and active_until>now

    def target_gate(self,session,monster,raw):
        import struct
        from warrior_combat import clear_terrain_line
        active=self.sculpture_active(session,monster,raw)
        return active and clear_terrain_line(self.tilemap,session.player(),struct.unpack_from('<2i',raw,0x68))

    def target_names(self,session):
        scene=session.nearby_monsters(radius=8)
        if scene['read_errors']:raise RuntimeError('当前地图目标采样不完整')
        return {m['name'] for m in scene['monsters'] if self.is_target(m)}

    def has_loot(self,session):
        from ground_item_probe import ground_snapshot
        from island_pickup_policy import filter_drops
        rows=ground_snapshot(session)['ground_maps'][0]
        if rows.get('error') or not rows.get('stable'):raise RuntimeError('连续跑动时掉落采样不完整')
        drops,_=filter_drops(rows['items']);position=session.player()
        return any(max(abs(d['x']-position[0]),abs(d['y']-position[1]))<=6 for d in drops)

    def move_options(self):
        return {'allow_hold':True,'expected_header':self.header,'hold_guard':self.guard,'drop_check':self.has_loot}

    def approach(self,session,progress):
        import struct,time
        from warrior_combat import patrol_move
        self.guard(session)
        scene=session.nearby_monsters(radius=8)
        if scene['read_errors']:raise RuntimeError('近怪站位采样不完整')
        targets=[m for m in scene['monsters'] if self.is_target(m) and getattr(self,'_melee_deferred',{}).get(m.get('address'),0)<=time.monotonic() and getattr(self,'_ranged_deferred',{}).get(m.get('address'),0)<=time.monotonic()]
        if not targets:return {'movement':False,'nearby_combat':False}
        target=min(targets,key=lambda m:m['distance'])
        if self.needs_activation_evidence(target):
            raw=dict(session.scene_actor_snapshot()).get(target['address'])
            if raw is None:return {'movement':False,'nearby_combat':True,'reason':'target_changed'}
            if not self.sculpture_active(session,target,raw):return WarriorMap.approach(self,session,progress)
        current=tuple(session.player())
        from warrior_combat import clear_terrain_line,melee_approach_path
        if not clear_terrain_line(self.tilemap,current,target['position']):
            from dungeon_route import PatrolObstruction,PatrolStalled
            now=time.monotonic()
            if not hasattr(self,'_ranged_obstruction'):self._ranged_obstruction=PatrolObstruction()
            obstruction=self._ranged_obstruction
            deferred={a:t for a,t in getattr(self,'_ranged_deferred',{}).items() if t>now}
            self._ranged_deferred=deferred
            blocked={struct.unpack_from('<2i',row,0x68) for address,row in session.scene_actor_snapshot() if row[0xac]==0}-{current}
            blocked|=obstruction.blocked(now)
            path=melee_approach_path(self.tilemap,current,target['position'],blocked,max_steps=getattr(self.tilemap,'width',256)*getattr(self.tilemap,'height',256),max_radius=max(getattr(self.tilemap,'width',256),getattr(self.tilemap,'height',256)),reach=8,require_line=True)
            if not path or len(path)<2:
                deferred[target['address']]=now+3
                return {'movement':False,'nearby_combat':True,'target':target,'reason':'no_line_of_fire_route'}
            moved=patrol_move(session,self.tilemap,path[1],allow_hold=False,blocked_tiles=blocked)
            self.guard(session)
            try:obstruction.observe(moved,time.monotonic())
            except PatrolStalled:
                deferred[target['address']]=time.monotonic()+20
                obstruction.failures=0;obstruction.repeats.clear()
                return dict(moved,movement=False,nearby_combat=True,target=target,reason='ranged_approach_stalled_target_deferred',approach_style='around_wall')
            return dict(moved,movement=tuple(moved['to'])!=current,nearby_combat=True,target=target,approach_style='around_wall')
        now=time.monotonic();key=(target.get('address'),target['name'])
        previous=getattr(self,'_approach_history',{})
        history=[(p,t) for p,t in previous.get('positions',[]) if now-t<8] if previous.get('target')==key else []
        if not history or history[-1][0]!=current:history.append((current,now))
        self._approach_history={'target':key,'positions':history}
        recent={p for p,t in history}
        blocked={struct.unpack_from('<2i',raw,0x68) for address,raw in session.scene_actor_snapshot() if raw[0xac]==0}
        blocked.discard(current);options=[]
        for dx,dy in ((0,-1),(1,0),(0,1),(-1,0),(-1,-1),(1,-1),(1,1),(-1,1)):
            goal=(current[0]+dx,current[1]+dy)
            distance=max(abs(goal[i]-target['position'][i]) for i in (0,1))
            if goal in recent or goal in blocked or not self.tilemap.free(goal) or not 2<=distance<=8:continue
            if dx and dy and (not self.tilemap.free((goal[0],current[1])) or not self.tilemap.free((current[0],goal[1]))):continue
            clearance=getattr(self.tilemap,'clearance',{}).get(goal,1)
            options.append((max(0,4-clearance),abs(distance-4),goal))
        if not options:return {'movement':False,'nearby_combat':True,'target':target,'reason':'no_unvisited_safe_standing_tile'}
        goal=min(options)[-1]
        moved=patrol_move(session,self.tilemap,goal,allow_hold=False)
        self.guard(session)
        changed=tuple(moved['to'])!=current
        if changed:history.append((tuple(moved['to']),time.monotonic()))
        return dict(moved,movement=changed,nearby_combat=True,target=target)



class WarriorMap(StoneTomb):
    character='微笑'
    combat_mode='warrior'
    native_chase=True
    post_cast_wait=.2

    def melee_classes(self):
        return {'TCatMon','TSculptureMon'}|({'TArcherMon'} if self.map_name=='64.map' else set())

    def is_target(self,monster):
        from random_hunt import target_monsters
        if monster.get('class')=='TArcherMon':
            if self.map_name!='64.map' or monster.get('name')!='魔龙射手':return False
            monster=dict(monster,**{'class':'TCatMon'})
        return monster.get('class') in ('TCatMon','TSculptureMon') and bool(target_monsters([monster],8))

    def select_melee_targets(self,monsters,now):
        deferred=getattr(self,'_melee_deferred',{})
        targets=sorted((m for m in monsters if deferred.get(m['address'],0)<=now),key=lambda m:m['distance'])
        locked=getattr(getattr(self,'_melee',None),'locked',None) or getattr(self,'_approach_target',None)
        if locked:
            same=next((m for m in targets if all(m.get(k)==locked.get(k) for k in ('address','name','class'))),None)
            if same:targets=[same]
        return targets

    def approach(self,session,progress):
        import struct,time
        from dungeon_route import PatrolObstruction,PatrolStalled
        from warrior_combat import melee_approach_path,patrol_move
        self.guard(session);now=time.monotonic();current=tuple(session.player())
        scene=session.nearby_monsters(radius=8)
        if scene['read_errors']:raise RuntimeError('近战靠近目标采样不完整')
        self._melee_deferred={a:t for a,t in getattr(self,'_melee_deferred',{}).items() if t>now}
        targets=WarriorMap.select_melee_targets(self,(m for m in scene['monsters'] if self.is_target(m) and m['address'] not in self._melee_deferred),now)
        if not targets:return {'movement':False,'nearby_combat':False}
        if not hasattr(self,'_melee_obstruction'):self._melee_obstruction=PatrolObstruction()
        obstruction=self._melee_obstruction
        occupied={struct.unpack_from('<2i',raw,0x68) for address,raw in session.scene_actor_snapshot() if raw[0xac]==0}
        occupied.discard(current)
        history=[(t,p) for t,p in getattr(self,'_melee_positions',[]) if now-t<8]
        history.append((now,current));self._melee_positions=history[-64:]
        recent={p for t,p in history if p!=current}
        for target in targets:
            key=(target['address'],target['name'],target['class'])
            budget=getattr(self,'_approach_budget',None)
            if budget is None or budget['key']!=key:
                budget={'key':key,'since':now,'best':float('inf')};self._approach_budget=budget
            self._approach_target=dict(target)
            path=melee_approach_path(self.tilemap,current,target['position'],occupied|obstruction.blocked(now)|recent)
            if path is not None and len(path)<budget['best']:
                budget['best']=len(path);budget['since']=now
            if now-budget['since']>=6:
                self._melee_deferred[target['address']]=now+3;self._approach_target=None
                return {'movement':False,'nearby_combat':True,'target':target,'reason':'bounded_approach_no_progress','approach_style':'melee_adjacent'}

            if path is None:
                return {'movement':False,'nearby_combat':True,'target':target,'reason':'recent_path_or_terrain_blocked','approach_style':'melee_adjacent'}
            if len(path)<2:
                key=(target['address'],current)
                if getattr(self,'_activation_wait_key',None)!=key:self._activation_wait_key=key;self._activation_wait_since=now
                if now-self._activation_wait_since>=3:
                    self._melee_deferred[target['address']]=now+3;continue
                return {'movement':False,'nearby_combat':True,'target':target,'reason':'adjacent_activation_wait'}
            self._activation_wait_key=None
            moved=patrol_move(session,self.tilemap,path[1],allow_hold=False,blocked_tiles=obstruction.blocked(now)|recent)
            self.guard(session)
            try:obstruction.observe(moved,time.monotonic())
            except PatrolStalled:
                self._melee_deferred[target['address']]=time.monotonic()+20
                self._approach_target=None;self._approach_budget=None
                obstruction.failures=0;obstruction.repeats.clear()
                return dict(moved,movement=False,nearby_combat=True,target=target,reason='approach_stalled_target_deferred',approach_style='melee_adjacent')
            return dict(moved,movement=tuple(moved['to'])!=current,nearby_combat=True,target=target,approach_style='melee_adjacent',remaining_path=len(path)-1,avoided_recent_positions=sorted(recent))
        if self.confirm_dead_end(session):raise self.dead_end_exception('近战靠近时重新采样确认周围无合法出口')
        return {'movement':False,'nearby_combat':False,'reason':'nearby_targets_temporarily_deferred'}

    def reset_combat(self):
        if hasattr(self,'_melee'):self._melee.reset()
        if hasattr(self,'_melee_obstruction'):del self._melee_obstruction
        self._melee_deferred={};self._activation_wait_key=None;self._approach_target=None;self._approach_budget=None;self._melee_positions=[]

    def repositioned(self,target):
        if hasattr(self,'_melee'):self._melee.retry_at.pop(target.get('address'),None)

    def probe(self,session,progress=lambda text:None,excluded=None,**options):
        from island_melee import Melee
        import time
        self.guard(session)
        scene=session.nearby_monsters(radius=8)
        if scene['read_errors']:raise RuntimeError('战士目标采样不完整')
        monsters=[m for m in scene['monsters'] if self.is_target(m) and m['address'] not in (excluded or set())]
        if not hasattr(self,'_melee'):self._melee=Melee(scene_guard=self.guard,progress_timeout=2,target_classes=self.melee_classes(),strict_chase=True)
        monsters=WarriorMap.select_melee_targets(self,monsters,time.monotonic())
        result=self._melee.step(session,{'monsters':monsters,'drops':[]})
        if result.get('clicked'):return dict(result,attack_sent=True,f1_sent=False)
        if result.get('engaged'):return dict(result,f1_sent=False)
        return dict(result,status='no_verified_target',f1_sent=False)


def run(session,progress=lambda message:None,allow_cycle=True,return_when_full=False):
    import importlib,mage_skills,mage_dungeon,dungeon_route,warrior_combat,ground_item_probe,island_melee
    for module in (mage_skills,dungeon_route,warrior_combat,ground_item_probe,island_melee,mage_dungeon):importlib.reload(module)
    character=read_experience(session)['character']
    combat_mode=detect_combat_mode(session,character)
    if allow_cycle and character=='厚礼蟹':
        import stone_hunt_cycle
        importlib.reload(stone_hunt_cycle)
        if stone_hunt_cycle.enabled():return stone_hunt_cycle.run(session,progress)
    profile=profile_for(session,character=character,combat_mode=combat_mode);profile.check_state(session)
    profile.return_when_full=return_when_full
    if profile.combat_mode=='mage':
        skills=mage_skills.inspect_current(session,character)
        if not skills.get('f1_skill') or skills['f1_skill']['name']!='雷电术':raise RuntimeError('F1不是唯一雷电术，未挂机')
    progress(profile.label+'：按通道中线覆盖可达地图，'+('主体单击选怪后由游戏追砍' if profile.combat_mode=='warrior' else 'F1雷电术')+'与名单拾取；不主动跨图')
    def report(message):progress(message.replace('地牢持续清怪拾取',profile.label+'清怪拾取'))
    return mage_dungeon.run_bounded(session,report,continuous=True,profile=profile)


def inspect(session):
    character=read_experience(session)['character']
    import importlib,mage_skills,warrior_combat,dungeon_route
    importlib.reload(mage_skills);importlib.reload(warrior_combat);importlib.reload(dungeon_route)
    profile=profile_for(session,character=character,combat_mode=detect_combat_mode(session,character));profile.check_state(session)
    tilemap,plan=profile.plan(session)
    from dungeon_route import CoverageRoute
    import time
    started=time.monotonic();route=CoverageRoute(tilemap,session.player(),spacing=profile.route_spacing)
    goal=route.next_goal(session.player(),time.monotonic())
    path=route.navigation_map().path(session.player(),goal) if goal else []
    center={'reachable_cells':len(route.clearance),'waypoints':sorted(route.points),'snapshot':route.snapshot(),'first_path':path,'planning_seconds':round(time.monotonic()-started,3)}
    skill=mage_skills.inspect_current(session,character)['f1_skill'] if profile.combat_mode=='mage' else None
    return {'map':tilemap.name,'plan':plan,'center_route':center,'combat_mode':profile.combat_mode,'character':profile.character,'f1_skill':skill,'game_input_sent':False}


# Map data changes; combat, pickup, player avoidance and pacing share this profile.
NormalMap=StoneTomb


def profile_for(session,character='厚礼蟹',combat_mode=None):
    import struct
    from map_navigation import matching_map_file
    current=header(session);file=matching_map_file(current,getattr(session,'_map_directory',None))
    name=file.name.lower()
    if name in ('3.map','5.map','0159.map','zlg101.map'):raise RuntimeError('城镇、商店或孤岛请使用对应流程，未启动普通地图挂机')
    width,height=struct.unpack('<HH',current[:4]);size=file.stat().st_size-52
    if not width or not height or size%(width*height):raise RuntimeError('当前地图文件尺寸不符')
    stride=size//(width*height)
    if stride not in (12,14):raise RuntimeError('当前地图格子格式尚未支持')
    if combat_mode is None:
        if character not in ('厚礼蟹','微笑'):raise RuntimeError('当前地图职业尚未核对')
        combat_mode='warrior' if character=='微笑' else 'mage'
    if combat_mode not in ('mage','warrior'):raise RuntimeError('当前地图职业尚未支持')
    cls=WarriorMap if combat_mode=='warrior' else NormalMap
    profile=cls(map_header=current,map_name=name,map_stride=stride);profile.character=character
    return profile


def detect_combat_mode(session,character):
    from mage_skills import inspect_current
    skills=inspect_current(session,character)
    names={r['name'] for r in skills.get('skills',[])}
    f1=skills.get('f1_skill') or {}
    if f1.get('name')=='雷电术':return 'mage'
    if '雷电术' in names:raise RuntimeError('法师F1未绑定唯一雷电术，未挂机')
    if names & {'基本剑术','攻杀剑术','刺杀剑术','半月弯刀','烈火剑法'}:return 'warrior'
    raise RuntimeError('当前技能无法确认受支持职业，未挂机')
