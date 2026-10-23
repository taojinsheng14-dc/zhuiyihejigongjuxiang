"""Read-only experience observations; growth events are never exact kill counts."""
import json,struct,time
from pathlib import Path


def read_experience(session):
    main=session.uint(session.uint(session.base+0x2bac2c))
    if main<0x10000:raise RuntimeError('人物对象尚未加载')
    hero=session.uint(main+0x358)
    def actor(address):
        if session.uint(address)!=session.base+0x24991c:raise RuntimeError('经验字段的角色类型未通过核对')
        raw=session.read(address+0xe8,0x42)
        level=struct.unpack_from('<H',raw,0)[0]
        exp,required=struct.unpack_from('<II',raw,0x3a)
        if not 1<=level<=255 or not required or exp>required:raise RuntimeError('经验字段数值尚未通过核对')
        return {'actor':address,'level':level,'experience':exp,'required':required}
    primary=actor(main)
    companion=actor(hero) if hero>=0x10000 else None
    pointer=session.uint(main+0xc);length=session.uint(pointer-4)
    if not 1<=length<=60:raise RuntimeError('经验采样的角色名称未通过核对')
    character=session.read(pointer,length).decode('gb18030')
    if session.uint(session.uint(session.base+0x2bac2c))!=main or session.uint(main+0x358)!=hero:
        raise RuntimeError('采样期间角色对象变化，等待重新建立基线')
    return {'character':character,'game_pid':session.reader.pid,'main':primary,'hero':companion}


class ExperienceTracker:
    def __init__(self,directory):
        self.directory=Path(directory);self.path=self.directory/'统计.json';self.last=None;self.last_write=0
        try:self.state=json.loads(self.path.read_text(encoding='utf8'))
        except (OSError,ValueError):self.state={}
        if self.state.get('schema')!=1:self.state={}

    def reset(self,character,now):
        self.state={'schema':1,'character':character,'started_epoch':now,'main_exp_gain':0,'hero_exp_gain':0,
                    'growth_events':0,'observed_seconds':0.0,'rebaselines':0,'unknown_upgrade_transitions':0,
                    'sampling_gaps':0,'last_growth_epoch':None,'nearby_player_seconds':0.0,'hero_available':False}

    @staticmethod
    def key(sample):
        return (sample['game_pid'],sample['main']['actor'],(sample.get('hero') or {}).get('actor'))

    def update(self,sample,now=None,context=None):
        now=time.time() if now is None else now
        context=context or {};character=sample['character']
        if self.state.get('character')!=character:self.reset(character,now);self.last=None
        previous=self.last;delta=hero_delta=0;reason=None
        if previous is None:reason='开始或重载后的新基线'
        elif self.key(previous['sample'])!=self.key(sample):reason='角色进程或对象变化'
        elif not 0<=now-previous['time']<=3:
            self.state['sampling_gaps']+=1;reason='采样间断，间断内击杀次数未知'
        else:
            before=previous['sample'];elapsed=now-previous['time']
            self.state['observed_seconds']+=elapsed
            if context.get('player_count',0)>0:self.state['nearby_player_seconds']+=elapsed
            if sample['main']['level']!=before['main']['level']:
                self.state['unknown_upgrade_transitions']+=1;reason='升级衔接待核对，重新建立经验基线'
            elif sample['main']['experience']<before['main']['experience']:reason='经验回退，重新建立基线'
            else:delta=sample['main']['experience']-before['main']['experience']
            if sample.get('hero') and before.get('hero') and sample['hero']['level']==before['hero']['level']:
                hero_delta=max(0,sample['hero']['experience']-before['hero']['experience'])
        self.last={'sample':sample,'time':now}
        if reason:self.state['rebaselines']+=1
        self.state['main_exp_gain']+=delta;self.state['hero_exp_gain']+=hero_delta
        if delta:
            self.state['growth_events']+=1;self.state['last_growth_epoch']=now
            self.append({'event':'experience_growth_observed','time':now,'character':character,
                         'game_pid':sample['game_pid'],'main_exp_delta':delta,'hero_exp_delta':hero_delta,
                         'position':context.get('position'),'player_count':context.get('player_count'),
                         'monster_count':context.get('count'),'exact_kill_count':None})
        self.state.update(observed_epoch=now,game_pid=sample['game_pid'],main=sample['main'],hero=sample.get('hero'),
                          hero_available=bool(sample.get('hero')),baseline_reason=reason,available=True,
                          count_basis='经验增长次数（击杀参考），不等于精确击杀数')
        result=self.summary()
        if now-self.last_write>=1:
            self.save();self.last_write=now
        return result

    def summary(self):
        result=dict(self.state);seconds=result.get('observed_seconds',0)
        result['experience_per_hour']=round(result.get('main_exp_gain',0)*3600/seconds) if seconds>0 else 0
        result['growth_events_per_hour']=round(result.get('growth_events',0)*3600/seconds,1) if seconds>0 else 0
        result['nearby_player_observation_percent']=round(result.get('nearby_player_seconds',0)*100/seconds,1) if seconds>0 else 0
        return result

    def append(self,row):
        self.directory.mkdir(parents=True,exist_ok=True)
        with (self.directory/'经验事件.jsonl').open('a',encoding='utf8') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')

    def save(self):
        self.directory.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(self.summary(),ensure_ascii=False,indent=2),encoding='utf8');temp.replace(self.path)
