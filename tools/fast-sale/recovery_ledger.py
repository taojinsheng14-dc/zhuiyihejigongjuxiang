"""Recovery allowance belongs to a character and slot, not a transient PID."""
import json
from pathlib import Path
import shutil

def used_for_session(saved,pid,character,instance):
    used=saved.get('used')
    if isinstance(used,bool) or not isinstance(used,int) or not 0<=used<=2:
        raise RuntimeError('恢复额度记录不完整，停止恢复')
    if saved.get('character'):
        if not character or saved['character']!=character or saved.get('instance','1')!=instance:
            raise RuntimeError('恢复额度所属角色或工具实例不符，停止恢复')
        return used
    if saved.get('game_pid')==pid:return used
    raise RuntimeError('旧恢复额度尚未绑定角色，需核对并迁移；不会按新PID清零')


def reconcile_characters(saved,pid,character,instance):
    if not character:raise RuntimeError('当前恢复累计角色未核对，停止恢复')
    if saved and saved.get('instance',instance)!=instance:
        raise RuntimeError('恢复累计文件属于另一工具实例，未改动记录')
    if saved.get('schema') not in (None,2):raise RuntimeError('恢复累计记录版本未知，停止恢复')
    records=saved.get('records',{})
    if not isinstance(records,dict):raise RuntimeError('恢复累计角色索引损坏，停止恢复')
    records={name:dict(row) for name,row in records.items() if isinstance(row,dict)}
    if len(records)!=len(saved.get('records',{})):raise RuntimeError('恢复累计角色记录损坏，停止恢复')
    for name,row in records.items():
        if not name or row.get('character')!=name:raise RuntimeError('恢复累计角色索引不符，停止恢复')
        used_for_session(row,pid,name,instance)
    if saved:
        owner=saved.get('character')
        if not owner:
            used_for_session(saved,pid,character,instance)
            owner=character
        old={key:saved.get(key) for key in ('game_pid','used','reason')}
        old.update(character=owner,instance=instance)
        used_for_session(old,pid,owner,instance)
        previous=records.get(owner)
        if previous and previous['used']>old['used']:old=previous
        records[owner]=old
    current=dict(records.get(character,{'used':0,'character':character,'instance':instance,
        'reason':'首次建立此角色独立累计；未执行恢复'}),game_pid=pid)
    used_for_session(current,pid,character,instance)
    records[character]=current
    return {**current,'schema':2,'records':records}


def _save(path,ledger):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(ledger,ensure_ascii=False,indent=2),encoding='utf8')
    temporary.replace(path)


def load_for_character(path,pid,character,instance):
    path=Path(path)
    try:saved=json.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:saved={}
    if not isinstance(saved,dict):raise RuntimeError('恢复累计文件损坏，停止恢复')
    ledger=reconcile_characters(saved,pid,character,instance)
    if ledger!=saved:
        if saved and saved.get('schema')!=2:
            backup=path.with_name(path.stem+'.before-characters.json')
            if not backup.exists():shutil.copy2(path,backup)
        _save(path,ledger)
    return ledger


def reserve_for_character(path,pid,character,instance,in_memory,reason):
    ledger=load_for_character(path,pid,character,instance)
    used=max(in_memory,ledger['used'])
    if used>=2:raise RuntimeError('本角色累计恢复额度已用完，停止反复重登')
    current={key:ledger[key] for key in ('game_pid','character','instance')}
    current.update(used=used+1,reason=reason)
    ledger.update(current);ledger['records'][character]=current
    _save(path,ledger)
    return used+1
