"""User supplied island pickup rules; independent of the sale whitelist."""
import json,re
from pathlib import Path

POLICY=Path(__file__).with_name('island-pickup-policy.json')

def parse_list(text):
    rows={}
    for raw in text.splitlines():
        value=raw.strip()
        if not value or value.startswith('-'):continue
        marked=bool(re.search(r'\s+1$',value))
        name=re.sub(r'\s+1$','',value).strip()
        rows[name]={'name':name,'marked':marked,'raw':value}
    return list(rows.values())

def filter_drops(drops,policy=None):
    if policy is None:
        if not POLICY.exists():return list(drops),[]
        policy=json.loads(POLICY.read_text(encoding='utf8'))
    mode=policy.get('mode')
    if mode not in ('all_listed','marked_only'):raise RuntimeError('孤岛拾取名单标记含义待用户确认，未继续拾取或换关')
    allowed={row['name'] for row in policy['items'] if mode=='all_listed' or row['marked']}
    return ([d for d in drops if d['name'] in allowed],[d for d in drops if d['name'] not in allowed])
