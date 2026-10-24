"""Explicit stone-five return/sale loop; ordinary background input only."""
import json
import re
import time
from pathlib import Path

import instance_context


def settings_path():return instance_context.runtime_root()/'outputs'/'当前地图挂机设置.json'


def enabled():
    path=settings_path()
    value=json.loads(path.read_text(encoding='utf8')).get('stone_five_sale_cycle',False) if path.exists() else False
    if type(value) is not bool:raise RuntimeError('石墓五层回城循环设置无效')
    return value


def save_enabled(value):
    if type(value) is not bool:raise ValueError('石墓循环开关必须为布尔值')
    path=settings_path();path.parent.mkdir(parents=True,exist_ok=True)
    data=json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
    data['stone_five_sale_cycle']=value
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(path)


def record(phase,**data):
    root=instance_context.runtime_root()/'outputs';root.mkdir(parents=True,exist_ok=True)
    row=dict(time=time.time(),phase=phase,**data)
    with (root/'石墓五层循环.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    path=root/'石墓五层循环状态.json';temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(path)


def settled(session):
    session.check()
    if session.login_stage()!='playing':raise RuntimeError('石墓循环角色未正常游戏，未自动重登')
    if session.held_item() or session.sale_item() or session.inflight_item():raise RuntimeError('石墓循环物品操作未结束')
    from combat_metrics import read_experience
    if read_experience(session)['character']!='厚礼蟹':raise RuntimeError('石墓循环角色不符')


def choose_link(rows,visited):
    """Only exact destinations/categories; never fuzzy-match another city."""
    choices=[]
    for row in rows:
        text=re.sub(r'\s+','',row['text'])
        if row['score']<.90:continue
        if re.fullmatch(r'(?:前往)?石墓(?:五|5)层(?:移动)?',text):label='石墓五层';priority=0
        elif text in ('危险区域','石墓','石墓洞穴'):label=text;priority=1
        else:continue
        if label not in visited:choices.append((priority,label,row))
    if not choices:raise RuntimeError('未唯一识别石墓五层或已核对分类入口，保留菜单且不猜点')
    priority=min(r[0] for r in choices);choices=[r for r in choices if r[0]==priority]
    if len(choices)!=1:raise RuntimeError('石墓传送菜单目标不唯一，未点击')
    return choices[0][1],choices[0][2]


def recognize(image):
    # Local models only; no screenshots are transmitted to an OCR service.
    from rapidocr import RapidOCR
    if not hasattr(recognize,'engine'):recognize.engine=RapidOCR()
    result=recognize.engine(image.resize((image.width*4,image.height*4)))
    if result.boxes is None:return []
    return [{'text':text,'score':float(score),'box':[[float(x)/4,float(y)/4] for x,y in box]}
            for box,text,score in zip(result.boxes,result.txts,result.scores)]


def menu_snapshot(session):
    settled(session)
    if not session.visible('merchant') or getattr(session,'active_merchant',None)!='盟重老兵':
        raise RuntimeError('不是新核对的盟重老兵菜单，未传送')
    bounds=tuple(session.bounds('merchant'));x,y,w,h=bounds
    cw,ch=session.client_size()
    if not (0<=x<x+w<=cw and 0<=y<y+h<=ch and 100<=w<=600 and 60<=h<=500):
        raise RuntimeError('老兵菜单边界不符')
    frame=session.capture_menu_frame('stone_five_transfer')
    if frame is None:raise RuntimeError('老兵菜单未保持显示')
    crop=frame.crop((x,y,x+w,y+h))
    rows=recognize(crop)
    root=instance_context.runtime_root()/'outputs'
    crop.save(root/'石墓传送菜单.png')
    (root/'石墓传送菜单识别.json').write_text(json.dumps({'bounds':bounds,'rows':rows,'time':time.time()},ensure_ascii=False,indent=2),encoding='utf8')
    return bounds,crop,rows


def verified_link_point(crop,row):
    box=row['box'];left=max(0,int(min(p[0] for p in box)));right=min(crop.width,int(max(p[0] for p in box))+1)
    top=max(0,int(min(p[1] for p in box)));bottom=min(crop.height,int(max(p[1] for p in box))+1)
    if right-left<10 or bottom-top<6:raise RuntimeError('传送文字边界不完整')
    yellow=[(x,y) for y in range(top,bottom) for x in range(left,right)
            if (lambda c:c[0]>175 and c[1]>150 and c[2]<115)(crop.getpixel((x,y)))]
    if len(yellow)<20:raise RuntimeError('目标不是已确认黄色可点文字，未点击')
    return ((min(p[0] for p in yellow)+max(p[0] for p in yellow))//2,
            (min(p[1] for p in yellow)+max(p[1] for p in yellow))//2)


def enter_stone_five(session,progress):
    from current_map_hunt import header,STONE_HEADER,profile_for
    settled(session);session.verify_sale_complete()
    if not session.in_mengzhong_return_area():session.return_with_hotkey(progress,reason='stone_sale_complete')
    settled(session);session.open_mengzhong_veteran(progress)
    town_header=header(session);visited=set();wallet_before=session.currency_snapshot()
    if wallet_before.get('gold') is None or wallet_before.get('yuanbao') is None:raise RuntimeError('传送前余额未核对')
    for _ in range(4):
        bounds,crop,rows=menu_snapshot(session)
        label,row=choose_link(rows,visited);point=verified_link_point(crop,row)
        # Re-observe after OCR: an asynchronous menu must not inherit old coordinates.
        session.pause(.15);settled(session)
        if header(session)!=town_header or tuple(session.bounds('merchant'))!=bounds or not session.visible('merchant'):
            raise RuntimeError('识别后老兵菜单或地图变化，未点击')
        frame=session.capture_menu_frame('stone_five_transfer')
        if frame is None:raise RuntimeError('老兵菜单已关闭')
        x,y,w,h=bounds;fresh=frame.crop((x,y,x+w,y+h))
        def yellow_mask(image):return [r>175 and g>150 and b<115 for r,g,b in image.convert('RGB').get_flattened_data()]
        if yellow_mask(crop)!=yellow_mask(fresh):raise RuntimeError('识别后菜单黄字变化，未使用旧坐标')
        target=(x+point[0],y+point[1])
        if session.hero_covers((target[0]-4,target[1]-4,target[0]+4,target[1]+4)):raise RuntimeError('英雄面板遮挡传送文字')
        visited.add(label);record('transfer_click',label=label,point=target,wallet=session.currency_snapshot())
        progress('按实际菜单文字选择：'+label)
        session.background_mouse(target,'left',track_movement=False,move_settle=.15,dpi_scaled=True,button_hold=.15)
        if label=='石墓五层':
            session.wait(lambda:header(session)!=town_header,timeout=12)
            session.wait(lambda:session.login_stage()=='playing' and not session.visible('merchant'),timeout=8)
            settled(session);session.stable_player()
            if header(session)!=STONE_HEADER:raise RuntimeError('传送后不是石墓五层，未继续打怪')
            profile=profile_for(session);profile.plan(session)
            after=session.currency_snapshot()
            if after.get('yuanbao')!=wallet_before['yuanbao']:raise RuntimeError('石墓传送元宝余额变化，停止核对')
            record('map_return_confirmed',map='d715.map',position=session.player(),wallet_before=wallet_before,wallet_after=after)
            return
        session.pause(.5)
        if header(session)!=town_header:raise RuntimeError('分类点击后意外切图，停止')
    raise RuntimeError('石墓传送分类超过有限层数，未继续点击')


def run(session,progress=lambda message:None):
    from current_map_hunt import header,STONE_HEADER,run as hunt
    from inventory_flow import bag_decision
    cycles=0
    try:
        settled(session)
        if header(session)!=STONE_HEADER:raise RuntimeError('石墓循环需从石墓五层启动，未猜测城内接续')
        # Check dependency before any future return; failure leaves this task local.
        from rapidocr import RapidOCR
        while True:
            settled(session);record('hunting',cycles=cycles,map='d715.map')
            result=hunt(session,progress,allow_cycle=False,return_when_full=True)
            if result['status']=='bounded_end' and result.get('elapsed_seconds',0)>=43190:continue
            if result['status']!='bags_full':return dict(result,cycles=cycles)
            settled(session)
            if header(session)!=STONE_HEADER:raise RuntimeError('双包满后地图变化，未回城')
            if bag_decision(session.inventory(),session.hero_inventory(),session.hero_ready())!='return_town':
                raise RuntimeError('双包满信号与实际背包不符，未回城')
            record('returning',cycles=cycles,bags=session.dual_bag_status())
            session.return_with_hotkey(progress)
            record('selling',cycles=cycles)
            sale=session.dual_sale_route(progress,allow_recovery=False)
            session.verify_sale_complete();settled(session)
            if session.inventory().count('')<=1 or session.hero_inventory().count('')<=1:
                raise RuntimeError('清包后仍缺少空间，保留非白名单且不重新下图')
            record('sale_verified',cycles=cycles,sold_count=sale['count'],bags=session.dual_bag_status())
            enter_stone_five(session,progress)
            cycles+=1;record('cycle_complete',cycles=cycles,unattended_acceptance=False)
    except Exception as error:
        record('stopped',cycles=cycles,reason=str(error));raise
    finally:session.clear_background_mouse()
