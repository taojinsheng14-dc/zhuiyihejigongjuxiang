"""Bounded read-only actor/scene sampling through the authorized helper."""
import gzip
import json
from pathlib import Path
import struct
import time


def sample(session,seconds=45,interval=.02):
    if session.login_stage()!='playing' or not session.hero_ready():
        raise RuntimeError('人物或英雄未加载，未进行经验采样')
    if session.held_item() or session.sale_item() or session.inflight_item():
        raise RuntimeError('物品操作未结束，未进行经验采样')
    main=session.uint(session.uint(session.base+0x2bac2c))
    hero=session.uint(main+0x358)
    for address in (main,hero):
        if session.uint(address)!=session.base+0x24991c:raise RuntimeError('角色对象类型不符')
    folder=Path(__file__).resolve().parents[2]/'outputs'/'经验分析'
    folder.mkdir(parents=True,exist_ok=True)
    stamp=time.strftime('%Y%m%d-%H%M%S')
    binary=folder/(stamp+'.bin.gz');scene=folder/(stamp+'-scene.jsonl')
    size=0x600;count=0;scene_count=0;last_scene=0
    started=time.monotonic();first={};last={}
    with gzip.open(binary,'wb') as file,scene.open('w',encoding='utf8') as events:
        while time.monotonic()-started<seconds:
            tick=time.monotonic();session.check()
            current=session.uint(session.uint(session.base+0x2bac2c))
            if current!=main or session.uint(main+0x358)!=hero:raise RuntimeError('角色对象变化，结束采样')
            values=[session.read(address,size) for address in (main,hero)]
            file.write(struct.pack('<d',time.time())+b''.join(values))
            if not count:first={key:value.hex() for key,value in zip(('main','hero'),values)}
            last={key:value.hex() for key,value in zip(('main','hero'),values)}
            count+=1
            if tick-last_scene>=.1:
                last_scene=tick
                try:
                    actors=session.scene_actor_snapshot()
                    rows=[{'address':address,'vmt':struct.unpack_from('<I',raw)[0],
                           'dead':raw[0xac],'position':list(struct.unpack_from('<2i',raw,0x68))}
                          for address,raw in actors]
                    events.write(json.dumps({'at':time.time(),'actors':rows})+'\n');scene_count+=1
                except RuntimeError as error:
                    events.write(json.dumps({'at':time.time(),'error':str(error)})+'\n')
            session.pause(max(.001,interval-(time.monotonic()-tick)))
    metadata={'pid':session.reader.pid,'main':main,'hero':hero,'base':session.base,
              'record_size':8+size*2,'actor_bytes':size,'samples':count,'scene_samples':scene_count,
              'seconds':round(time.monotonic()-started,3),'binary':str(binary),'scene':str(scene),
              'first':first,'last':last,'game_input_sent':False}
    (folder/(stamp+'.json')).write_text(json.dumps(metadata,ensure_ascii=False),encoding='utf8')
    return {key:value for key,value in metadata.items() if key not in ('first','last')}
