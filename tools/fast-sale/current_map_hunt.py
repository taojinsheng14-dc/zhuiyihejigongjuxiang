"""Explicitly verified normal-map mage profiles; no teleport or paid entry."""
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


class StoneTomb:
    player_exception=PlayersDetected

    def __init__(self,avoid_players=None):
        self.avoid_loaded_players=load_avoid_players() if avoid_players is None else avoid_players

    panel_exception=PanelOpen
    header=STONE_HEADER
    names=STONE_NAMES
    route_spacing=24
    post_cast_wait=.05

    def check_state(self,session):
        session.check()
        if session.login_stage()!='playing' or header(session)!=self.header:raise RuntimeError('当前地图挂机地图或角色状态变化，停止')
        if read_experience(session)['character']!='厚礼蟹':raise RuntimeError('当前地图法师仅授权厚礼蟹')
        if session.held_item() or session.sale_item() or session.inflight_item():raise RuntimeError('当前地图挂机物品操作状态不空')
        if session.u.IsIconic(session.hwnd):raise RuntimeError('游戏已最小化，未挂机输入')

    def guard(self,session):
        self.check_state(session)
        if any(session.visible(k) for k in ('merchant','sell','bag')):raise PanelOpen('当前地图挂机面板打开，暂停输入')
        if self.avoid_loaded_players and session.nearby_players(None):raise PlayersDetected('已加载范围内发现其他玩家')

    def wait_for_panels(self,session):
        self.check_state(session)
        if session.visible('merchant'):
            # Hunting never opens NPC transactions: dismiss the ordinary activity
            # window through its verified close control, never a content link.
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
        before=tuple(session.player());wallet_before=session.currency_snapshot()
        # A failed/uncertain attempt ends this command; never press another key blindly.
        if not any(row['name']=='随机传送石' and row.get('raw_98',1)>0 for row in session.shortcut_inventory()):raise RuntimeError('避人随机缺少可用随机传送石，未购买或使用随机卷')
        session.clear_background_mouse();self.check_state(session)
        session.write_stats({'event':'random_attempt','reason':'loaded_players','scope':'client_loaded','position':before,'player_count':len(players)})
        progress('已加载范围发现其他玩家，使用随机传送石避开；不要求无怪')
        session.press_named_hotkey(('随机传送石',),'random')
        try:
            session.wait(lambda:tuple(session.player())!=before,timeout=5)
            self.check_state(session)
            after=tuple(session.stable_player())
            if not self.tilemap.free(after):raise RuntimeError('随机落点不在已核对可走路网')
        except RuntimeError as error:
            session.write_stats({'event':'random_result','confirmed':False,'reason':'loaded_players','error':str(error)})
            raise RuntimeError('避人随机落点未确认，停止且不重复按键：'+str(error)) from error
        wallet_after=session.currency_snapshot()
        session.write_stats({'event':'random_result','confirmed':True,'reason':'loaded_players','before':before,'position':after})
        return {'random_used':True,'scope':'client_loaded','player_count':len(players),'before':before,'after':after,'wallet_before':wallet_before,'wallet_after':wallet_after}

    def plan(self,session):
        from warrior_combat import patrol_plan
        result=patrol_plan(session,expected_header=self.header,expected_name='d715.map',radius=None)
        self.tilemap=result[0]
        return result

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
        import struct
        from warrior_combat import patrol_move
        self.guard(session)
        scene=session.nearby_monsters(radius=8)
        if scene['read_errors']:raise RuntimeError('近怪站位采样不完整')
        targets=[m for m in scene['monsters'] if not m['dead'] and m['class']=='TCatMon' and m['name'] in self.names and m['distance']<=8]
        if not targets:return {'movement':False,'nearby_combat':False}
        target=min(targets,key=lambda m:m['distance']);current=tuple(session.player())
        blocked={struct.unpack_from('<2i',raw,0x68) for address,raw in session.scene_actor_snapshot() if raw[0xac]==0}
        blocked.discard(current);options=[]
        for dx,dy in ((0,-1),(1,0),(0,1),(-1,0),(-1,-1),(1,-1),(1,1),(-1,1)):
            goal=(current[0]+dx,current[1]+dy)
            distance=max(abs(goal[i]-target['position'][i]) for i in (0,1))
            if goal in blocked or not self.tilemap.free(goal) or not 2<=distance<=8:continue
            if dx and dy and (not self.tilemap.free((goal[0],current[1])) or not self.tilemap.free((current[0],goal[1]))):continue
            options.append((abs(distance-4),goal))
        if not options:return {'movement':False,'nearby_combat':True,'target':target}
        goal=min(options)[1]
        moved=patrol_move(session,self.tilemap,goal,allow_hold=False)
        self.guard(session)
        return dict(moved,movement=tuple(moved['to'])!=current,nearby_combat=True,target=target)



def run(session,progress=lambda message:None):
    import importlib,mage_skills,mage_dungeon,dungeon_route,warrior_combat,ground_item_probe
    for module in (mage_skills,dungeon_route,warrior_combat,ground_item_probe,mage_dungeon):importlib.reload(module)
    current=header(session)
    if current==DUNGEON_HEADER:return mage_dungeon.run_bounded(session,progress,continuous=True)
    if current!=STONE_HEADER:raise RuntimeError('当前地图尚未核对，未启动挂机')
    profile=StoneTomb();profile.check_state(session)
    skills=mage_skills.inspect_current(session,'厚礼蟹')
    if not skills.get('f1_skill') or skills['f1_skill']['name']!='雷电术':raise RuntimeError('F1不是唯一雷电术，未挂机')
    progress('石墓五层：核对路网后在整张可达地图循环巡逻，无怪直路按住右键连续跑，F1雷电术与名单拾取；不主动跨图')
    def report(message):progress(message.replace('地牢持续清怪拾取','石墓五层清怪拾取'))
    return mage_dungeon.run_bounded(session,report,continuous=True,profile=profile)


def inspect(session):
    import importlib,mage_skills,warrior_combat
    importlib.reload(mage_skills);importlib.reload(warrior_combat)
    profile=StoneTomb();profile.check_state(session)
    tilemap,plan=profile.plan(session)
    skills=mage_skills.inspect_current(session,'厚礼蟹')
    return {'map':tilemap.name,'plan':plan,'f1_skill':skills['f1_skill'],'game_input_sent':False}
