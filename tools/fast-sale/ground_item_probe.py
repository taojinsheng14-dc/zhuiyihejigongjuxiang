"""Bounded read-only inspection of current scene list fields. No input helpers."""
import json
from pathlib import Path
import struct
import time


def inspect(session):
    session.check()
    if session.login_stage()!='playing':raise RuntimeError('未进入地图，未读取地面物品')
    scene=session.uint(session.uint(session.base+0x2ba8fc))
    def classname(address):
        vmt=session.uint(address)
        if not session.base<=vmt<session.base+0x300000:return None
        ptr=session.uint(vmt-44);size=session.read(ptr,1)[0]
        if not 1<=size<=80:return None
        name=session.read(ptr+1,size).decode('ascii')
        return name if name.startswith(('T','_')) and name.isprintable() else None
    if classname(scene)!='TPlayScene':raise RuntimeError('场景对象类型不符')
    header=session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)
    blob=session.read(scene,0x300);lists=[];seen=set()
    for offset in range(4,len(blob)-3,4):
        pointer=struct.unpack_from('<I',blob,offset)[0]
        if pointer<0x10000 or pointer in seen:continue
        try:
            if classname(pointer)!='TList':continue
            seen.add(pointer);lh=session.read(pointer,16)
            _,items,count,capacity=struct.unpack('<4I',lh)
            if not 0<=count<=capacity<=20000 or count>2048:continue
            pointers=struct.unpack('<%dI'%count,session.read(items,count*4)) if count else ()
            rows=[]
            for address in pointers[:20]:
                try:
                    data=session.read(address,0x100)
                    row={'address':address,'head':data.hex(),'strings':[]}
                    try:row['class']=classname(address)
                    except (RuntimeError,UnicodeError):pass
                    for pos in range(0,64,4):
                        ptr=struct.unpack_from('<I',data,pos)[0]
                        if not 0x10000<=ptr<0x80000000:continue
                        try:
                            length=session.uint(ptr-4)
                            if not 2<=length<=80:continue
                            text=session.read(ptr,length).decode('gb18030')
                            if any('\u4e00'<=c<='\u9fff' for c in text) and all(c.isprintable() for c in text):
                                row['strings'].append({'offset':pos,'text':text})
                        except (RuntimeError,UnicodeError):pass
                    rows.append(row)
                except RuntimeError:continue
            lists.append({'offset':hex(offset),'count':count,'capacity':capacity,'rows':rows,
                          'stable':session.read(pointer,16)==lh})
        except (RuntimeError,UnicodeError):continue
    if session.uint(session.uint(session.base+0x2ba8fc))!=scene or session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)!=header:
        raise RuntimeError('采样期间地图变化，未确认地面对象')
    fields=[]
    for offset in range(4,0x1b0,4):
        pointer=struct.unpack_from('<I',blob,offset)[0]
        if pointer<0x10000:continue
        try:
            kind=classname(pointer)
            if kind:fields.append({'offset':hex(offset),'address':pointer,'class':kind,'head':session.read(pointer,64).hex()})
        except (RuntimeError,UnicodeError):pass
    extra=[]
    for offset in (0x34,0x38,0x48,0x4c,0x50,0x54,0x58,0x80,0x84,0x88,0x8c,0xb0,0xb4,0xb8,0xd0,0xd4,0xd8,0xdc,0xe0,0xe4,0xe8):
        pointer=struct.unpack_from('<I',blob,offset)[0]
        row={'offset':hex(offset),'address':pointer}
        if pointer>=0x10000:
            try:row['head']=session.read(pointer,128).hex()
            except RuntimeError:pass
        extra.append(row)
    ground_maps=[]
    for rva,indirect in ((0x2babb0,True),(0x2eb4b8,False)):
        info={'rva':hex(rva),'items':[]}
        try:
            root=session.uint(session.base+rva)
            if indirect:root=session.uint(root)
            info.update(address=root,kind=classname(root),head=session.read(root,36).hex())
            tree=session.uint(root+0x1c)
            th=session.read(tree,16);_,_,count,sentinel=struct.unpack('<4I',th)
            info.update(tree=tree,count=count,sentinel=sentinel)
            if not 0<=count<=2048:raise RuntimeError('地面表数量越界')
            stack=[session.uint(sentinel+4)];visited=set()
            while stack:
                node=stack.pop()
                if node in (0,sentinel) or node in visited:continue
                if len(visited)>=2048:raise RuntimeError('地面树遍历超限')
                visited.add(node)
                data=session.read(node,24)
                _,parent,left,right,key,item=struct.unpack('<6I',data)
                stack.extend((left,right))
                record=session.read(item,61)
                x,y,uid,looks,nameptr=struct.unpack_from('<5I',record)
                length=session.uint(nameptr-4)
                if not 1<=length<=120:continue
                name=session.read(nameptr,length).decode('gb18030')
                info['items'].append({'address':item,'x':x,'y':y,'id':uid,'name':name,'key':key,'key_matches':key==x*10000+y})
            info['stable']=session.read(tree,16)==th
        except (RuntimeError,UnicodeError) as exc:info['error']=str(exc)
        ground_maps.append(info)
    output={'time':time.time(),'pid':session.reader.pid,'base':session.base,'scene':scene,'fields':fields,'scene_head':blob[:0x1b0].hex(),'extra':extra,
            'ground_maps':ground_maps,'position':session.player(),'lists':lists,'game_input_sent':False}
    path=Path(__file__).resolve().parents[2]/'outputs'/'地面物品分析.json'
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
    return {'ground_maps':ground_maps,'path':str(path),'position':output['position'],'fields':fields,'lists':[
        {'offset':r['offset'],'count':r['count'],'stable':r['stable'],
         'examples':[{'class':i.get('class'),'strings':i['strings']} for i in r['rows'][:5]]} for r in lists],
            'game_input_sent':False}


def pickup_test(session):
    """Only the two user-dropped, previously verified wooden swords."""
    expected={149184784:(329,297),149144736:(331,299)}
    before=session.inventory()
    if sum(not x for x in before)<2:raise RuntimeError('背包不足两格，未拾取')
    if session.held_item() or session.sale_item() or session.inflight_item():raise RuntimeError('物品传输状态不空，未拾取')
    first=inspect(session)
    maps=first['ground_maps']
    if not maps or not maps[0].get('stable'):raise RuntimeError('地面表不稳定')
    items={r['id']:r for r in maps[0]['items']}
    for uid,xy in expected.items():
        row=items.get(uid)
        if not row or row['name']!='木剑' or (row['x'],row['y'])!=xy or not row['key_matches']:
            raise RuntimeError('测试木剑已变化，未移动')
    session.close_panels()
    results=[]
    for uid in (149144736,149184784):
        rows=inspect(session)['ground_maps'][0]['items']
        if not any(r['id']==uid for r in rows):raise RuntimeError('目标消失，停止测试')
        route=session.walk_tile(expected[uid],max_steps=8,run_enabled=False)
        session.pause(.5)
        remaining=inspect(session)['ground_maps'][0]['items']
        inv=session.inventory()
        result={'id':uid,'target':expected[uid],'route':route,'ground_disappeared':not any(r['id']==uid for r in remaining),
                'wooden_sword_count_before':before.count('木剑'),'wooden_sword_count_after':inv.count('木剑')}
        results.append(result)
        if not result['ground_disappeared'] or inv.count('木剑')<=before.count('木剑'):
            break
        before=inv
    return {'pickup_test':results,'position':session.player(),'game_input_sent':True}


def pickup_one_test(session):
    uid=149275744;target=(302,314)
    snapshot=inspect(session)
    rows=snapshot['ground_maps'][0]
    row=next((r for r in rows['items'] if r['id']==uid),None)
    if not rows.get('stable') or not row or row['name']!='木剑' or (row['x'],row['y'])!=target:
        raise RuntimeError('测试木剑已变化，未点击')
    before=session.inventory()
    if not any(not x for x in before):raise RuntimeError('背包已满')
    if session.held_item() or session.sale_item() or session.inflight_item():raise RuntimeError('物品状态不空')
    current=tuple(session.player())
    if current!=(301,317):raise RuntimeError('人物已移动，未点击')
    actor=session.uint(session.uint(session.base+0x2bac2c))
    draw=struct.unpack('<2i',session.read(actor+0x17c,8))
    point=(draw[0]+48*(target[0]-current[0]),draw[1]+64+32*(target[1]-current[1]))
    if not (850<=point[0]<=930 and 310<=point[1]<=370):raise RuntimeError('投影不匹配已核对画面')
    from fast_sale import button_center
    if session.visible('bag'):
        close=session.control_info(0x48c,'Button_ItemBagClose')
        session.background_mouse(button_center(session.bounds('bag'),close['bounds']),track_movement=False,move_settle=.15)
        session.pause(.2)
        if session.visible('bag'):raise RuntimeError('背包关闭点击未生效，未移动')
    route=session.walk_tile(target,max_steps=6,run_enabled=False)
    session.pause(.5)
    after=session.inventory();last=inspect(session)
    remains=any(r['id']==uid for r in last['ground_maps'][0]['items'])
    result={'target':target,'click':point,'before':current,'after':session.player(),'ground_remaining':remains,
            'swords_before':before.count('木剑'),'swords_after':after.count('木剑'),
            'verified':not remains and after.count('木剑')==before.count('木剑')+1}
    if cooperative and remaining and any(tuple(a['after'])!=tuple(a['before']) for a in actions):result['status']='approaching'
    import instance_context
    output=(instance_context.runtime_root()/'outputs'/'孤岛最后拾取.json') if cooperative else (Path(__file__).resolve().parents[2]/'outputs'/'木剑拾取测试.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result


def ground_snapshot(session):
    """Only the validated ground tree; no scene sweep or analysis file writes."""
    session.check()
    if session.login_stage()!='playing':raise RuntimeError('未进入地图')
    header=session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)
    def classname(address):
        vmt=session.uint(address)
        if not session.base<=vmt<session.base+0x300000:raise RuntimeError('地面表类型不符')
        ptr=session.uint(vmt-44);length=session.read(ptr,1)[0]
        if not 1<=length<=80:raise RuntimeError('地面表类型不符')
        name=session.read(ptr+1,length).decode('ascii')
        if name!='_TMultiMap':raise RuntimeError('地面表类型不符')
        return name
    ground_maps=[]
    for rva,indirect in ((0x2babb0,True),):
        info={'rva':hex(rva),'items':[]}
        try:
            root=session.uint(session.base+rva)
            if indirect:root=session.uint(root)
            info.update(address=root,kind=classname(root),head=session.read(root,36).hex())
            tree=session.uint(root+0x1c)
            th=session.read(tree,16);_,_,count,sentinel=struct.unpack('<4I',th)
            info.update(tree=tree,count=count,sentinel=sentinel)
            if not 0<=count<=2048:raise RuntimeError('地面表数量越界')
            stack=[session.uint(sentinel+4)];visited=set()
            while stack:
                node=stack.pop()
                if node in (0,sentinel) or node in visited:continue
                if len(visited)>=2048:raise RuntimeError('地面树遍历超限')
                visited.add(node)
                data=session.read(node,24)
                _,parent,left,right,key,item=struct.unpack('<6I',data)
                stack.extend((left,right))
                record=session.read(item,61)
                x,y,uid,looks,nameptr=struct.unpack_from('<5I',record)
                length=session.uint(nameptr-4)
                if not 1<=length<=120:continue
                name=session.read(nameptr,length).decode('gb18030')
                info['items'].append({'address':item,'x':x,'y':y,'id':uid,'name':name,'key':key,'key_matches':key==x*10000+y})
            info['stable']=session.read(tree,16)==th
        except (RuntimeError,UnicodeError) as exc:info['error']=str(exc)
        ground_maps.append(info)
    if session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)!=header:
        raise RuntimeError('采样期间地图变化')
    if not ground_maps[0].get('stable'):raise RuntimeError('地面表变化，暂停拾取')
    return {'ground_maps':ground_maps,'position':session.player()}


def wait_pickup_position(session,expected=None,timeout=4.5):
    deadline=time.monotonic()+timeout;previous=None;steady=0
    while time.monotonic()<deadline:
        current=tuple(session.player())
        steady=steady+1 if current==previous else 0
        if steady>=3 and (expected is None or current==expected):return current
        previous=current;session.pause(.08)
    return tuple(session.player())


def choose_pickup_move(current,path,tilemap,occupied):
    """Run only over two verified clear tiles in the same direction."""
    first=path[1]
    dx=first[0]-current[0];dy=first[1]-current[1]
    second=(current[0]+2*dx,current[1]+2*dy)
    run=(len(path)>2 and tuple(path[2])==second
         and first not in occupied and second not in occupied
         and tilemap.free(first) and tilemap.free(second))
    return (second if run else first),'right' if run else 'left'


def ground_actor_boxes(session):
    draws=[tuple(n['draw']) for n in session.npcs()]
    own=session.uint(session.uint(session.base+0x2bac2c));hero=session.uint(own+0x358)
    if hero:draws.append(struct.unpack('<2i',session.read(hero+0x17c,8)))
    sample=session.nearby_monsters(radius=50)
    if sample.get('read_errors',0):raise RuntimeError('怪物模型位置未能完整核对，未点击地面')
    for monster in sample['monsters']:
        if not monster['dead']:
            draws.append(struct.unpack('<2i',session.read(monster['address']+0x17c,8)))
    return [(x-28,y-16,x+28,y+80) for x,y in draws]


def pickup_aim(current,destination,draw,tilemap,blocked,size,avoid_boxes=(),button=None):
    dx=(destination[0]>current[0])-(destination[0]<current[0])
    dy=(destination[1]>current[1])-(destination[1]<current[1])
    # A left click walks to its actual tile, unlike a two-tile right-click run.
    # Never project a one-step left click three/four tiles beyond its path.
    reaches=(max(abs(destination[i]-current[i]) for i in (0,1)),) if button=='left' else (3,4,2,1)
    for reach in reaches:
        tile=(current[0]+dx*reach,current[1]+dy*reach)
        point=(draw[0]+48*dx*reach,draw[1]+64+32*dy*reach)
        if any(a<=point[0]<=c and b<=point[1]<=d for a,b,c,d in avoid_boxes):continue
        if tile in blocked or not tilemap.free(tile):continue
        if 80<=point[0]<=size[0]-80 and 60<=point[1]<=size[1]-180:
            return point
    raise RuntimeError('没有不被遮挡的地面移动点击点')


def stored_item_count(session,name):
    count=session.bag_item_totals().get(name,0)
    count+=sum(max(1,row.get('raw_98',1)) for row in session.shortcut_inventory() if row['name']==name)
    return count


def pickup_current_test(session,excluded=None,names=('木剑',),radius=6,max_steps=None,cooperative=False,target_id=None):
    from fast_sale import button_center
    from background_sale import BackgroundSession
    from inventory_flow import ensure_loot_capacity
    ensure_loot_capacity(session)
    before=session.inventory();actions=[]
    first=ground_snapshot(session);rows=first['ground_maps'][0]
    candidates=[r for r in rows['items'] if (names is None or r['name'] in names) and r['id'] not in (excluded or set()) and (target_id is None or r['id']==target_id) and r['key_matches'] and (radius is None or max(abs(r['x']-first['position'][0]),abs(r['y']-first['position'][1]))<=radius)]
    if not candidates:return {'status':'no_target','game_input_sent':False}
    chosen=min(candidates,key=lambda r:max(abs(r['x']-first['position'][0]),abs(r['y']-first['position'][1])))
    uid=chosen['id'];target=(chosen['x'],chosen['y']);item_name=chosen['name']
    gold_before=session.currency_snapshot()['gold'] if item_name=='金币' else None
    stored_before=stored_item_count(session,item_name)
    row=next((r for r in rows['items'] if r['id']==uid and r['name']==item_name),None)
    if not rows.get('stable') or not row or (row['x'],row['y'])!=target:raise RuntimeError('测试木剑已消失，未输入')
    if session.held_item() or session.sale_item() or session.inflight_item() or not any(not x for x in before):raise RuntimeError('物品状态不适合拾取')
    if session.visible('bag'):
        close=session.control_info(0x48c,'Button_ItemBagClose')
        BackgroundSession.background_mouse(session,button_center(session.bounds('bag'),close['bounds']),track_movement=False,move_settle=.15,dpi_scaled=True,button_hold=.15)
        session.pause(.3)
        if session.visible('bag'):return {'error_detail':'关闭背包未生效，未移动','position':session.player()}
    map_obj=session.uint(session.uint(session.base+0x2ba608));map_header=session.read(map_obj+4,52)
    tilemap=session.navigation_map(map_header);blocked=set();stuck=0;actor_occluded=False
    for _ in range(min(64 if radius is None else 16,max_steps) if max_steps is not None else (64 if radius is None else 16)):
        current=tuple(session.player())
        if current==target:
            if cooperative:
                # Standing on a drop is not a pickup. The old early break sent
                # no input and then incorrectly accumulated obstruction failures.
                own=session.uint(session.uint(session.base+0x2bac2c))
                draw=struct.unpack('<2i',session.read(own+0x17c,8))
                point=(draw[0],draw[1]+64);width,height=session.client_size()
                if any(a<=point[0]<=c and b<=point[1]<=d for a,b,c,d in ground_actor_boxes(session)):
                    actor_occluded=True;break
                if not(20<point[0]<width-20 and 20<point[1]<height-180):raise RuntimeError('脚下拾取点超出地面范围')
                if session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)!=map_header:raise RuntimeError('脚下拾取前地图变化')
                BackgroundSession.background_mouse(session,point,'left',track_movement=False,move_settle=.12,dpi_scaled=True,button_hold=.15)
                session.pause(.3)
                actions.append({'before':current,'after':tuple(session.player()),'point':point,'button':'left','action':'pickup_underfoot'})
            break
        if radius is not None and max(abs(current[0]-target[0]),abs(current[1]-target[1]))>radius:raise RuntimeError('超出测试范围')
        rows=ground_snapshot(session)['ground_maps'][0]
        if not rows.get('stable') or not any(r['id']==uid for r in rows['items']):break
        if session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)!=map_header:
            raise RuntimeError('拾取期间地图变化，停止')
        occupied={tuple(n['map']) for n in session.npcs()+session.npcs(True) if tuple(n['map'])!=current}
        own=session.uint(session.uint(session.base+0x2bac2c));hero=session.uint(own+0x358)
        if hero:
            hero_xy=struct.unpack('<2i',session.read(hero+0x68,8))
            if hero_xy!=current:occupied.add(hero_xy)
        try:path=tilemap.path(current,target,blocked|occupied)
        except RuntimeError:break
        if len(path)<2:break
        destination,button=choose_pickup_move(current,path,tilemap,blocked|occupied)
        dx=destination[0]-current[0];dy=destination[1]-current[1]
        own=session.uint(session.uint(session.base+0x2bac2c));draw=struct.unpack('<2i',session.read(own+0x17c,8))
        try:
            if cooperative:
                from island_automation import clickable_move
                selected=clickable_move(current,[target],tilemap,blocked|occupied,draw,session.client_size(),ground_actor_boxes(session))
                if selected is None:raise RuntimeError('没有不被遮挡的地面移动点击点')
                destination,button,point=selected
            else:point=pickup_aim(current,destination,draw,tilemap,blocked|occupied,session.client_size(),button=button)
        except RuntimeError as error:
            if not cooperative or '没有不被遮挡' not in str(error):raise
            actor_occluded=True;break
        BackgroundSession.background_mouse(session,point,button,track_movement=False,move_settle=.12,dpi_scaled=True,button_hold=.15)
        after=wait_pickup_position(session,destination);actions.append({'before':current,'point':point,'button':button,'after':after,'expected':destination})
        if after==current:
            stuck+=1;blocked.add(destination)
            if stuck>=3:break
            session.pause(.3);continue
        if after!=destination:
            if not tilemap.free(after) or max(abs(after[0]-current[0]),abs(after[1]-current[1]))>4:
                raise RuntimeError('拾取移动超出短距离范围，停止：%s'%actions[-1])
            actions[-1]['replanned_after_actual_movement']=True
    session.pause(.15)
    last=ground_snapshot(session);after=session.inventory()
    remaining=any(r['id']==uid for r in last['ground_maps'][0]['items'])
    gold_after=session.currency_snapshot()['gold'] if item_name=='金币' else None
    stored_after=stored_item_count(session,item_name)
    gained=(isinstance(gold_after,int) and isinstance(gold_before,int) and gold_after>gold_before) if item_name=='金币' else stored_after>stored_before
    removed_at_target=not remaining and tuple(session.player())==target
    result={'name':item_name,'gold_before':gold_before,'gold_after':gold_after,'id':uid,'target':target,'actions':actions,'position':session.player(),'ground_remaining':remaining,
            'item_count_before':before.count(item_name),'item_count_after':after.count(item_name),'all_storage_before':stored_before,'all_storage_after':stored_after,
            'verified':not remaining and gained,
            'status':'blocked' if remaining else 'completed' if gained else 'removed_at_target' if removed_at_target else 'unverified'}
    if cooperative and remaining and any(tuple(a['after'])!=tuple(a['before']) for a in actions):result['status']='approaching'
    if cooperative and remaining and actor_occluded:result['status']='actor_occluded'
    import instance_context
    output=(instance_context.runtime_root()/'outputs'/'孤岛最后拾取.json') if cooperative else (Path(__file__).resolve().parents[2]/'outputs'/'木剑拾取测试.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result


def pickup_loop(session,seconds=120):
    """Bounded autonomous validation: wooden swords within six tiles only."""
    log=Path(__file__).resolve().parents[2]/'outputs'/'自动拾取日志.jsonl'
    deadline=time.monotonic()+seconds;verified=0;attempts=0;excluded=set()
    map_obj=session.uint(session.uint(session.base+0x2ba608));header=session.read(map_obj+4,52)
    def record(event):
        event['time']=time.time()
        with log.open('a',encoding='utf8') as out:out.write(json.dumps(event,ensure_ascii=False)+'\n')
    record({'event':'start','seconds':seconds,'names':['木剑'],'radius':6})
    while time.monotonic()<deadline and attempts<10:
        session.check()
        obj=session.uint(session.uint(session.base+0x2ba608))
        if session.read(obj+4,52)!=header:
            record({'event':'stop','reason':'map_changed'});return {'status':'map_changed','verified':verified}
        result=pickup_current_test(session,excluded=excluded)
        if result.get('status')=='no_target':
            session.pause(.5);continue
        attempts+=1;record({'event':'attempt','result':result})
        if result.get('status')=='blocked':
            excluded.add(result['id']);session.pause(.3);continue
        if not result.get('verified'):
            return {'status':'stopped_unverified','verified':verified,'attempts':attempts,'last':result}
        verified+=1;session.pause(.4)
    record({'event':'complete','verified':verified,'attempts':attempts})
    return {'status':'complete','verified':verified,'attempts':attempts,'log':str(log)}
