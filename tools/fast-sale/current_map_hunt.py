"""Explicitly verified normal-map mage profiles; no teleport or paid entry."""
from combat_metrics import read_experience
from warrior_combat import HEADER as DUNGEON_HEADER

STONE_HEADER=bytes.fromhex('900190010f4c6567656e64206f66206d69720d0a908df227205ce640020b2e2e474d474a582e434f4d0000000000000000000000')
STONE_NAMES={'黑野猪','红野猪','白野猪','蝙蝠','角蝇','蝎蛇','楔蛾'}


def header(session):return session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)


class StoneTomb:
    header=STONE_HEADER
    names=STONE_NAMES

    def guard(self,session):
        session.check()
        if session.login_stage()!='playing' or header(session)!=self.header:raise RuntimeError('当前地图挂机地图或角色状态变化，停止')
        if read_experience(session)['character']!='厚礼蟹':raise RuntimeError('当前地图法师仅授权厚礼蟹')
        if session.held_item() or session.sale_item() or session.inflight_item():raise RuntimeError('当前地图挂机物品操作状态不空')
        if any(session.visible(k) for k in ('merchant','sell','bag')):raise RuntimeError('当前地图挂机面板打开，停止输入')
        if session.u.IsIconic(session.hwnd):raise RuntimeError('游戏已最小化，未挂机输入')

    def plan(self,session):
        from warrior_combat import patrol_plan
        return patrol_plan(session,expected_header=self.header,expected_name='d715.map',radius=32)

    def approach(self,session,progress):
        # Continuous coverage takes the next validated route when an aim cannot be confirmed.
        return {'movement':False}


def run(session,progress=lambda message:None):
    import importlib,mage_skills,mage_dungeon,dungeon_route,warrior_combat,ground_item_probe
    for module in (mage_skills,dungeon_route,warrior_combat,ground_item_probe,mage_dungeon):importlib.reload(module)
    current=header(session)
    if current==DUNGEON_HEADER:return mage_dungeon.run_bounded(session,progress,continuous=True)
    if current!=STONE_HEADER:raise RuntimeError('当前地图尚未核对，未启动挂机')
    profile=StoneTomb();profile.guard(session)
    skills=mage_skills.inspect_current(session,'厚礼蟹')
    if not skills.get('f1_skill') or skills['f1_skill']['name']!='雷电术':raise RuntimeError('F1不是唯一雷电术，未挂机')
    progress('石墓五层：核对路网后在起点32格范围内巡逻，F1雷电术与名单拾取；不主动跨图')
    def report(message):progress(message.replace('地牢持续清怪拾取','石墓五层清怪拾取'))
    return mage_dungeon.run_bounded(session,report,continuous=True,profile=profile)


def inspect(session):
    import importlib,mage_skills,warrior_combat
    importlib.reload(mage_skills);importlib.reload(warrior_combat)
    profile=StoneTomb();profile.guard(session)
    tilemap,plan=profile.plan(session)
    skills=mage_skills.inspect_current(session,'厚礼蟹')
    return {'map':tilemap.name,'plan':plan,'f1_skill':skills['f1_skill'],'game_input_sent':False}
