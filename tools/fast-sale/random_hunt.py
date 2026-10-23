"""Conservative, testable no-monster random-teleport policy; no game input."""
from dataclasses import asdict,dataclass
import json
from pathlib import Path
import re
import time

from instance_context import runtime_root
SETTINGS_PATH=runtime_root()/'outputs'/'随机挂机设置.json'


@dataclass(frozen=True)
class RandomSettings:
    enabled:bool=False
    trigger_mode:str='contested_empty'
    radius:int=12
    player_radius:int=8
    empty_seconds:float=20
    cooldown_seconds:float=60
    max_per_hour:int=6
    cost_per_use:float=.2

    def validate(self):
        import math
        if type(self.enabled) is not bool:raise ValueError('随机开关必须为布尔值')
        if self.trigger_mode not in ('contested_empty','empty','players'):raise ValueError('未知随机条件')
        if not 4<=self.radius<=30 or int(self.radius)!=self.radius:raise ValueError('检测范围应为4—30格整数')
        if not 2<=self.player_radius<=30 or int(self.player_radius)!=self.player_radius:raise ValueError('玩家范围应为2—30格整数')
        if not math.isfinite(self.empty_seconds) or not 5<=self.empty_seconds<=300:raise ValueError('无怪等待应为5—300秒')
        if not math.isfinite(self.cooldown_seconds) or not 10<=self.cooldown_seconds<=3600:raise ValueError('随机间隔应为10—3600秒')
        if not 1<=self.max_per_hour<=60 or int(self.max_per_hour)!=self.max_per_hour:raise ValueError('每小时最多1—60次')
        if not math.isfinite(self.cost_per_use) or self.cost_per_use<0:raise ValueError('每次费用不能为负数')
        return self


def load_settings(path=None):
    path=Path(path or SETTINGS_PATH)
    if not path.exists():return RandomSettings()
    return RandomSettings(**json.loads(path.read_text(encoding='utf8'))).validate()


def save_settings(settings,path=None):
    settings.validate();path=Path(path or SETTINGS_PATH);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.settings.tmp')
    temporary.write_text(json.dumps(asdict(settings),ensure_ascii=False,indent=2),encoding='utf8')
    temporary.replace(path)


def target_monsters(rows,radius):
    targets=[]
    for row in rows:
        if row.get('dead') or row.get('distance',9999)>radius:continue
        if row.get('class')=='TArcherMon':continue
        # Exclude only known summons carrying an owner suffix. Unknown actors
        # remain candidates, so uncertainty cannot trigger more paid teleports.
        if re.match(r'^(神兽|变异骷髅|强化骷髅|月灵|虎卫|鹰卫|道灵|火灵)[(（].+[)）]$',row.get('name','')):continue
        targets.append(row)
    return targets


class RandomPolicy:
    def __init__(self,attempts=None):
        self.attempts=list(attempts or []);self.empty_since=None;self.last_observed=None
        self.context=None;self.last_use=None

    def observe(self,sample,settings,allowed,context,now=None,wall=None):
        now=time.monotonic() if now is None else now;wall=time.time() if wall is None else wall
        self.attempts=[at for at in self.attempts if 0<=wall-at<3600]
        def reset(reason):
            self.empty_since=None;self.last_observed=None
            return {'ready':False,'reason':reason,'used_hour':len(self.attempts)}
        if not settings.enabled:return reset('无怪随机已关闭')
        if not allowed:return reset('当前不在允许随机的挂机状态')
        if (not sample or not sample.get('ok') or sample.get('read_errors',0)
                or sample.get('sampler')!='helper_thread'
                or not 0<=wall-sample.get('observed_epoch',0)<=2):return reset('等待新鲜、有效的怪物采样')
        if settings.trigger_mode!='players':
            if sample.get('target_count') is None:return reset('候选怪物数尚未确认')
            if sample['target_count']>0:return reset('范围内仍有怪物')
        if settings.trigger_mode!='empty':
            if sample.get('player_count') is None:return reset('附近玩家数尚未确认')
            if sample['player_count']<=0:return reset('附近无其他玩家，原地等待刷新')
        stamp=sample['observed_epoch']
        context=(context,settings.trigger_mode,settings.radius,settings.player_radius)
        if self.context!=context:
            self.context=context;self.empty_since=None;self.last_observed=None
        if self.last_observed is not None and (stamp<self.last_observed or stamp-self.last_observed>1.5):
            self.empty_since=None
        if self.empty_since is None:self.empty_since=now
        self.last_observed=stamp
        elapsed=max(0,now-self.empty_since)
        if len(self.attempts)>=settings.max_per_hour:return {'ready':False,'reason':'已达到每小时随机次数上限','used_hour':len(self.attempts)}
        last_wall=max(self.attempts) if self.attempts else None
        cooldown=max(0,settings.cooldown_seconds-(wall-last_wall)) if last_wall is not None else 0
        remaining=max(0,settings.empty_seconds-elapsed,cooldown)
        label={'contested_empty':'有人且无怪','empty':'无怪','players':'有人'}[settings.trigger_mode]
        return {'ready':remaining<=0,'reason':'持续{} {:.0f}秒，等待 {:.0f}秒'.format(label,elapsed,remaining),
                'used_hour':len(self.attempts),'wait_seconds':remaining}

    def reserve(self,wall=None):
        self.attempts.append(time.time() if wall is None else wall)
        self.empty_since=None;self.last_observed=None


def recent_attempts(path,now=None):
    now=time.time() if now is None else now;attempts=[];path=Path(path)
    if path.exists():
        for line in path.read_text(encoding='utf8').splitlines():
            try:
                row=json.loads(line)
                if row.get('event')=='random_attempt' and 0<=now-row.get('observed_epoch',0)<3600:
                    attempts.append(row['observed_epoch'])
            except (ValueError,TypeError):continue
    return attempts
