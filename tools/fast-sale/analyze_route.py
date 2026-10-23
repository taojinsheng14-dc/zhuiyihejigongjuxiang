"""Turn a manual trace into reference waypoints and UI transitions, not replay."""
import json
from pathlib import Path

def summarize(events):
    changes=[];clicks=[];previous=None
    for index,event in enumerate(events):
        kind=event.get('kind')
        if kind=='mouse_down':clicks.append(event)
        if kind!='position':continue
        recent=next((click for click in reversed(clicks) if 0<=event['seconds']-click['seconds']<=3),None)
        if previous:
            if previous['map_id']!=event['map_id']:
                landing=event;repeat=0;last_xy=None
                for candidate in events[index:]:
                    if candidate.get('seconds',0)>event['seconds']+2:break
                    if candidate.get('kind')!='position':continue
                    if candidate['map_id']!=event['map_id']:break
                    repeat=repeat+1 if candidate['xy']==last_xy else 1
                    last_xy=candidate['xy']
                    if repeat>=3:
                        landing=candidate;break
                changes.append({'type':'map_change','seconds':event['seconds'],
                                'from_map':previous['map_id'],'from':previous['xy'],
                                'to_map':event['map_id'],'to':landing['xy'],
                                'stable_landing':repeat>=3})
            for key,label in [('merchant','商人菜单'),('sell','出售窗口'),('bag','背包')]:
                if bool(event.get(key))!=bool(previous.get(key)):
                    changes.append({'type':'ui_change','seconds':event['seconds'],'window':key,
                                    'label':label,'open':bool(event.get(key)),
                                    'map_id':event['map_id'],'xy':event['xy'],
                                    'preceding_click':recent})
        previous=event
    return {'reference_only':True,'click_count':len(clicks),'changes':changes,
            'notes':['开关商人、出售、背包均独立记录，不用单纯的点击时间判断是否完成。',
                     '录制中的停顿和重复点击不直接用于自动回放。']}

def analyze_directory(directory):
    directory=Path(directory)
    events=[json.loads(line) for line in (directory/'route.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
    result=summarize(events)
    (directory/'route-reference.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    lines=['# 手动路线参考','',f"共记录 {result['click_count']} 次游戏内点击。以下为状态变化，不是定时回放脚本。",'']
    for item in result['changes']:
        if item['type']=='map_change':
            lines.append(f"- {item['seconds']:.1f} 秒：地图切换，{item['from']} → {item['to']}。")
        else:
            action='打开' if item['open'] else '关闭'
            lines.append(f"- {item['seconds']:.1f} 秒：{item['xy']} {action}{item['label']}。")
    (directory/'路线参考.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    return result
