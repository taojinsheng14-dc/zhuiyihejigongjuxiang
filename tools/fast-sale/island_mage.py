"""厚礼蟹 island lightning: verified hover plus ordinary background F1 only."""
import time,struct
from island_melee import CLASSES


AUTHORIZED_ROLES={"厚礼蟹","大鱼"}

def guard(session,expected_character="厚礼蟹"):
    from island_automation import header,ISLAND_HEADER,role_key
    session.check()
    if session.login_stage()!='playing' or header(session)!=ISLAND_HEADER:raise RuntimeError('孤岛雷电术仅允许正常孤岛状态')
    if expected_character not in AUTHORIZED_ROLES or role_key(session).rsplit('|',1)[0]!=expected_character:raise RuntimeError('孤岛雷电术角色与授权目标不符')
    if session.held_item() or session.sale_item() or session.inflight_item():raise RuntimeError('孤岛施法前物品状态不空')
    if any(session.visible(k) for k in ('merchant','sell','bag')):raise RuntimeError('孤岛施法前面板未关闭')
    if session.u.IsIconic(session.hwnd):raise RuntimeError('游戏已最小化，未施法')


class Mage:
    def __init__(self,character="厚礼蟹"):
        if character not in AUTHORIZED_ROLES:raise RuntimeError("未授权孤岛F1角色")
        self.character=character
        self.casts=0;self.clicks=0;self.locked=None;self.failures={};self.retry_at={};self.stagnant={}

    def reset(self):self.locked=None

    def step(self,session,sample):
        from mage_dungeon import probe_once
        scene_guard=lambda s:guard(s,self.character)
        scene_guard(session)
        now=time.monotonic();self.retry_at={a:t for a,t in self.retry_at.items() if t>now}
        inactive=set()
        for m in sample['monsters']:
            if m.get('class')=='TSculptureMon' and m.get('distance',99)>2:
                maximum=struct.unpack('<H',session.read(m['address']+0x11a,2))[0]
                if maximum==0:inactive.add(m['address'])
        names={m['name'] for m in sample['monsters'] if m.get('class') in CLASSES and not m.get('dead')}
        if not names:return {'status':'no_verified_target','engaged':False,'f1_sent':False}
        result=probe_once(session,locked=self.locked,excluded=set(self.retry_at)|inactive,scene_guard=scene_guard,
                          target_names=names,target_classes=CLASSES,expected_character=self.character)
        if result.get('f1_sent'):
            self.casts+=1;self.locked=result['target'];self.failures.clear();result['engaged']=True
            uid=self.locked['address']
            before=result.get('target_vitals_before',{});after=result.get('target_vitals_after',{})
            self.stagnant[uid]=self.stagnant.get(uid,0)+1 if before==after else 0
            if self.stagnant[uid]>=4:
                self.retry_at[uid]=time.monotonic()+3;self.locked=None;self.stagnant[uid]=0
                result.update(engaged=False,reposition_required=True)
        else:
            target=self.locked or result.get('target');self.locked=None
            if target:
                uid=target['address'];self.failures[uid]=self.failures.get(uid,0)+1
                if self.failures[uid]>=2:self.retry_at[uid]=now+3;self.failures.pop(uid,None)
            result['engaged']=False
        return result
