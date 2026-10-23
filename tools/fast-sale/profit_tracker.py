"""Local wallet accounting and editable game-currency conversions; no game input."""
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import math
from pathlib import Path
import time


@dataclass(frozen=True)
class Rates:
    yuanbao_per_rmb: float = 11
    gold_per_lot: float = 1000000
    yuanbao_per_lot: float = 180
    hourly_cost: float = 5
    entry_cost: float = 5

    def validate(self):
        for name, value in asdict(self).items():
            if not math.isfinite(value) or value < 0 or (name not in ('hourly_cost','entry_cost') and value == 0):
                raise ValueError('兑换比例须大于0，费用须不小于0，且必须是有限数字')
        return self


def calculate(rates, gold_delta, yuanbao_delta, seconds, entries,random_cost=0,random_uses=0):
    rates.validate()
    hours=max(0,seconds)/3600
    gold_value=gold_delta/rates.gold_per_lot*rates.yuanbao_per_lot
    estimated_cost=hours*rates.hourly_cost+entries*rates.entry_cost+random_cost
    actual=gold_value+yuanbao_delta  # Already-paid game fees must not be deducted twice.
    estimated=gold_value-estimated_cost
    return {'gold_delta':gold_delta,'yuanbao_delta':yuanbao_delta,'hours':hours,'entries':entries,
            'random_uses':random_uses,'random_estimated_cost':random_cost,
            'gold_value_yuanbao':gold_value,'actual_profit_yuanbao':actual,
            'actual_profit_rmb':actual/rates.yuanbao_per_rmb,
            'estimated_cost_yuanbao':estimated_cost,'estimated_profit_yuanbao':estimated,
            'estimated_profit_rmb':estimated/rates.yuanbao_per_rmb,
            'actual_hourly_rmb':actual/rates.yuanbao_per_rmb/hours if hours else None,
            'break_even_gold':estimated_cost/rates.yuanbao_per_lot*rates.gold_per_lot}


class ProfitTracker:
    def __init__(self, directory):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.rates=Rates();self.state=None
        path=self.directory/'收益计算.json'
        if path.exists():
            value=json.loads(path.read_text(encoding='utf-8'))
            self.rates=Rates(**value.get('rates',{})).validate()
            self.state=value.get('session')

    def save(self):
        path=self.directory/'收益计算.json';temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps({'rates':asdict(self.rates),'session':self.state},ensure_ascii=False,indent=2),encoding='utf-8')
        temp.replace(path)

    def set_rates(self, **values):
        self.rates=Rates(**values).validate();self.save()

    @property
    def running(self):return bool(self.state and self.state.get('running'))

    def start(self, wallet, now=None, pid=None):
        now=time.time() if now is None else now
        if any(not isinstance(wallet.get(k),(int,float)) or not math.isfinite(wallet[k]) for k in ('gold','yuanbao')):
            raise ValueError('需要一份有效的金币、元宝余额才能开始统计')
        self.state={'started_at':now,'baseline':dict(wallet),'wallet':dict(wallet),
                    'active_seconds':0,'active_since':now,'running':True,'entries':[],
                    'last_sample_at':now,'game_pid':pid}
        self.save()

    def seconds(self, now=None):
        if not self.state:return 0
        now=time.time() if now is None else now
        return self.state['active_seconds']+(max(0,now-self.state['active_since']) if self.running else 0)

    def stop(self, now=None):
        if self.running:
            self.state['active_seconds']=self.seconds(now);self.state['running']=False;self.save()

    def resume(self, wallet, now=None, pid=None):
        now=time.time() if now is None else now
        if not self.state:return self.start(wallet,now,pid)
        if self.running:return
        # Exclude trades, purchases or earnings made while accounting was paused.
        for key in ('gold','yuanbao'):
            self.state['baseline'][key]+=wallet[key]-self.state['wallet'][key]
        self.state.update(wallet=dict(wallet),active_since=now,running=True,last_sample_at=now,game_pid=pid)
        self.save()

    def sample(self, wallet, observed_at, pid=None):
        if not self.running or observed_at<self.state['last_sample_at']:return False
        if self.state.get('game_pid') is not None and pid!=self.state['game_pid']:
            self.stop(observed_at)
            raise ValueError('游戏进程变化，收益统计已暂停；核对角色后重新开始统计')
        if any(not isinstance(wallet.get(k),(int,float)) or not math.isfinite(wallet[k]) for k in ('gold','yuanbao')):
            return False
        self.state.update(wallet=dict(wallet),last_sample_at=observed_at)
        return True

    def add_event(self, row):
        if not self.running or row.get('event') not in ('room_entry','random_attempt'):return False
        try:at=float(row['observed_epoch']) if 'observed_epoch' in row else datetime.fromisoformat(row['time']).timestamp()
        except (KeyError,ValueError,TypeError):return False
        if at<max(self.state['started_at'],self.state['active_since']):return False
        identity=row['time']+'|'+str(row.get('position'))
        if row['event']=='random_attempt':
            cost=row.get('estimated_cost_yuanbao',0)
            if not isinstance(cost,(int,float)) or not math.isfinite(cost) or cost<0:return False
            uses=self.state.setdefault('random_uses',[])
            if any(value['identity']==identity for value in uses):return False
            uses.append({'identity':identity,'cost':cost});return True
        if identity in self.state['entries']:return False
        self.state['entries'].append(identity);return True

    def summary(self, now=None):
        if not self.state:return None
        return calculate(self.rates,self.state['wallet']['gold']-self.state['baseline']['gold'],
                         self.state['wallet']['yuanbao']-self.state['baseline']['yuanbao'],
                         self.seconds(now),len(self.state['entries']),
                         random_cost=sum(row['cost'] for row in self.state.get('random_uses',[])),
                         random_uses=len(self.state.get('random_uses',[])))
