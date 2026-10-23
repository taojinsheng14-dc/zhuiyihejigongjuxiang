"""Append-only local records; no game input and no inferred historic balances."""
import csv
import json
import time
from datetime import datetime
from pathlib import Path


def append_event(directory,event):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    row={'time':datetime.now().astimezone().isoformat(timespec='milliseconds'),'observed_epoch':time.time(),**event}
    with (directory/'events.jsonl').open('a',encoding='utf8') as handle:
        handle.write(json.dumps(row,ensure_ascii=False)+'\n')
    if row['event']=='sale_round':
        fields=['time','round_id','status','hunt_seconds','hunt_duration_basis','sold_count',
                'gold_before','gold_after','gold_net_change','sale_income_gold',
                'other_gold_change','yuanbao_before','yuanbao_after','yuanbao_change','sale_seconds']
        labels=['时间','轮次编号','状态','打怪秒数','时长起点','售出件数','出售前金币','出售后金币',
                '本轮金币净变化','逐件售卖金币合计','其他金币变化','出售前元宝','出售后元宝','元宝变化','清包秒数']
        path=directory/'清包统计.csv';fresh=not path.exists()
        try:
            with path.open('a',newline='',encoding='utf-8-sig') as handle:
                writer=csv.DictWriter(handle,fieldnames=labels,extrasaction='ignore')
                if fresh:writer.writeheader()
                writer.writerow({label:row.get(field) for field,label in zip(fields,labels)})
        except PermissionError as error:
            append_runtime_event(directory,{'event':'csv_export_blocked','round_id':row.get('round_id'),
                                           'error':str(error),'jsonl_preserved':True})
    return row


def append_runtime_event(directory,event):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    row={'time':datetime.now().astimezone().isoformat(timespec='seconds'),**event}
    with (directory/'运行日志.jsonl').open('a',encoding='utf8') as handle:
        handle.write(json.dumps(row,ensure_ascii=False)+'\n')
    return row
