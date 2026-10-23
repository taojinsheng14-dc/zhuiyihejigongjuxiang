"""Checks for bag transfers and decisions; no game inputs in this module."""
from collections import Counter


def retain_in_main_bag(name):
    return name in ('盟重回城石','盟重传送石','随机传送石') or name.startswith('魔血石')

def validate_transfer(main_before,hero_before,main_after,hero_after,source,index):
    arrays=(main_before,hero_before,main_after,hero_after)
    if any(len(a)!=40 for a in arrays):raise RuntimeError('背包容量不符')
    before,after,dest_before,dest_after=(main_before,main_after,hero_before,hero_after) if source=='main' else (hero_before,hero_after,main_before,main_after)
    if source not in ('main','hero') or not 0<=index<40:raise RuntimeError('转包来源无效')
    name=before[index]
    if not name:raise RuntimeError('来源格子为空')
    expected=before.copy();expected[index]=''
    if after!=expected:raise RuntimeError('来源背包发生了非预期变化')
    changed=[i for i in range(40) if dest_before[i]!=dest_after[i]]
    if len(changed)!=1 or dest_before[changed[0]] or dest_after[changed[0]]!=name:
        raise RuntimeError('目标背包未确认增加同一件物品')
    if Counter(main_before+hero_before)!=Counter(main_after+hero_after):raise RuntimeError('转包前后物品总数不一致')
    return changed[0]

def bag_decision(main,hero,hero_ready):
    if len(main)!=40 or len(hero)!=40:raise RuntimeError('背包容量不符')
    if not hero_ready:return 'hero_unavailable'
    # Return only when both bags reach 39 occupied slots.
    main_free=main.count('');hero_free=hero.count('')
    if main_free<=1 and hero_free<=1:return 'return_town'
    if main_free>1:return 'continue'
    if hero_free>1:return 'transfer'
    return 'continue'


def ensure_loot_capacity(session,progress=lambda text:None):
    """Shared capacity gate for every scripted combat/pickup mode.

    Ordinary hunting retains its existing town-return policy. Other modes
    transfer with the same verified routine and stop locally if both fill.
    """
    main=session.inventory()
    if len(main)!=40:raise RuntimeError('背包容量不符')
    if main.count('')>1:return {'transferred':False,'main_free':main.count('')}
    session.check()
    if session.login_stage()!='playing':raise RuntimeError('当前角色状态不适合自动转包')
    if session.held_item() or session.sale_item() or session.inflight_item():raise RuntimeError('物品状态不空，禁止自动转包')
    if not session.hero_ready():session.ensure_hero_available()
    if not session.hero_ready():raise RuntimeError('英雄不可用，未自动转包')
    before=session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)
    progress('主包接近满：按现有保留规则转入英雄包，逐件核对后继续')
    session.close_panels()
    try:report=session.handle_full_bags()
    finally:
        if not (session.held_item() or session.sale_item() or session.inflight_item()):session.close_panels()
    if session.read(session.uint(session.uint(session.base+0x2ba608))+4,52)!=before:
        raise RuntimeError('转包期间地图变化，停止后续操作')
    free=session.inventory().count('')
    if free<=1:
        if report.get('return_required'):raise RuntimeError('双包均接近满，已保留现场；当前模式不自动退出挑战')
        raise RuntimeError('主包未能腾出足够空格，保留现场；不重复盲目转包')
    return {'transferred':True,'main_free':free,'report':report}



def validate_live_transfer(before,after,source,index):
    """Allow fresh loot in empty slots, while proving the selected item's move."""
    destination='hero' if source=='main' else 'main'
    if source not in ('main','hero') or not 0<=index<40:raise RuntimeError('转包来源无效')
    if any(len(bags[key])!=40 for bags in (before,after) for key in ('main','hero')):raise RuntimeError('背包容量不符')
    item=before[source][index]
    if not item['name'] or not item['uid'] or set(item['uid'])=={'0'}:raise RuntimeError('来源物品标识无效')
    if sum(row==item for rows in before.values() for row in rows)!=1:raise RuntimeError('来源物品标识不唯一')
    matches=[i for i,row in enumerate(after[destination]) if row==item]
    if len(matches)!=1 or before[destination][matches[0]]['name']:raise RuntimeError('目标背包未确认新增同一标识物品')
    if any(row==item for row in after[source]):raise RuntimeError('来源物品仍在原背包')
    consumables={'太阳水','强效太阳水','金创药(小量)','金创药(中量)','金创药(大量)',
                 '魔法药(小量)','魔法药(中量)','魔法药(大量)','强效金创药','强效魔法药','疗伤药','打捆太阳水','打捆疗伤药'}
    for key in ('main','hero'):
        for i,row in enumerate(before[key]):
            if not row['name'] or (key==source and i==index):continue
            if after[key][i]!=row and row['name'] not in consumables:
                raise RuntimeError('原有非消耗品发生了意外变化')
    return matches[0]
