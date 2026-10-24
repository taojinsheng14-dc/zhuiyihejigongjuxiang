"""Explicitly verified normal-map mage profiles; no teleport or paid entry."""
from combat_metrics import read_experience
from warrior_combat import HEADER as DUNGEON_HEADER

STONE_HEADER=bytes.fromhex('900190010f4c6567656e64206f66206d69720d0a908df227205ce640020b2e2e474d474a582e434f4d0000000000000000000000')
STONE_NAMES={'黑野猪','红野猪','白野猪','蝙蝠','角蝇','蝎蛇','楔蛾'}


def header(session):return session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)


class PanelOpen(RuntimeError):pass


class StoneTomb:
    panel_exception=PanelOpen
    header=STONE_HEADER
    names=STONE_NAMES
    route_spacing=24

    def check_state(self,session):
        session.check()
        if session.login_stage()!='playing' or header(session)!=self.header:raise RuntimeError('当前地图挂机地图或角色状态变化，停止')
        if read_experience(session)['character']!='厚礼蟹':raise RuntimeError('当前地图法师仅授权厚礼蟹')
        if session.held_item() or session.sale_item() or session.inflight_item():raise RuntimeError('当前地图挂机物品操作状态不空')
        if session.u.IsIconic(session.hwnd):raise RuntimeError('游戏已最小化，未挂机输入')

    def guard(self,session):
        self.check_state(session)
        if any(session.visible(k) for k in ('merchant','sell','bag')):raise PanelOpen('当前地图挂机面板打开，暂停输入')

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

    def plan(self,session):
        from warrior_combat import patrol_plan
        return patrol_plan(session,expected_header=self.header,expected_name='d715.map',radius=None)

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
        # Continuous coverage takes the next validated route when an aim cannot be confirmed.
        return {'movement':False}


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
