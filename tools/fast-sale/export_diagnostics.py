"""Explicit, read-only log export; never includes credentials, bindings or images."""
from datetime import datetime
import json
from pathlib import Path
import platform
import re
import socket
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2]
OUTPUT_FILES=('实时监控.json','孤岛自动流程.jsonl','孤岛挑战状态.json','孤岛最后拾取.json','孤岛修复记录.jsonl','清包工具最近结果.json')
OUTPUT_FOLDERS=('挂机统计','战斗统计','工具箱')
EXTENSIONS={'.json','.jsonl','.csv','.log'}


def candidates(root):
    root=Path(root)
    for slot,base in (('1',root),('2',root/'instances'/'2')):
        outputs=base/'outputs'
        for name in OUTPUT_FILES:
            yield outputs/name
        for directory in OUTPUT_FOLDERS:
            for path in (outputs/directory).glob('*'):
                if path.is_file() and path.suffix in EXTENSIONS:yield path
        helper=base/'tools'/'game-chat-inspect'
        for name in ('source-sale-command.json','source-sale-result.json','source-sale-cancel.json'):
            yield helper/name
    for path in (root/'outputs'/'BOSS计时器').glob('*'):
        if path.is_file() and path.suffix in EXTENSIONS:yield path


def export(root=ROOT):
    root=Path(root).resolve();now=datetime.now().astimezone()
    machine=''.join(c for c in socket.gethostname() if c.isalnum() or c in '-_') or 'computer'
    folder=root/'outputs'/'诊断包';folder.mkdir(parents=True,exist_ok=True)
    target=folder/('工具箱诊断-'+machine+'-'+now.strftime('%Y%m%d-%H%M%S-%f')+'.zip')
    metadata={'machine':machine,'exported_at':now.isoformat(),'python':sys.version.split()[0],
        'platform':platform.platform(),'files':[],'errors':[],
        'snapshot':'best_effort_while_running','excluded':'credentials, DPAPI, bindings, screenshots, config'}
    try:
        build=re.search(r"^BUILD=['\"]([^'\"]+)",(root/'tools'/'fast-sale'/'mixed_sale_gui.py').read_text(encoding='utf-8-sig'),re.M)
        metadata['toolbox_build']=build.group(1) if build else None
    except OSError:metadata['toolbox_build']=None
    try:
        result=subprocess.run(['git','rev-parse','HEAD'],cwd=root,capture_output=True,text=True,timeout=3)
        metadata['git_commit']=result.stdout.strip() if result.returncode==0 else None
    except (OSError,subprocess.TimeoutExpired):metadata['git_commit']=None
    seen=set()
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in candidates(root):
            try:
                if not path.is_file():continue
                resolved=path.resolve()
                if not resolved.is_relative_to(root) or path.is_symlink():continue
                relative=path.relative_to(root).as_posix()
                if relative in seen:continue
                seen.add(relative)
                data=path.read_bytes();archive.writestr(relative,data)
                metadata['files'].append({'path':relative,'bytes':len(data)})
            except OSError as error:metadata['errors'].append({'path':str(path.relative_to(root)),'error':str(error)})
        archive.writestr('metadata.json',json.dumps(metadata,ensure_ascii=False,indent=2))
    return target


if __name__=='__main__':
    print('只读导出，不会停止工具任务或操作游戏。')
    print('诊断包：'+str(export()))
    print('含运行日志，可能有角色名、坐标和余额；上传前请检查。')
