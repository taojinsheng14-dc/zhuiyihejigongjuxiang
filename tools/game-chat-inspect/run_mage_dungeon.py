"""One serialized continuous command for the explicitly selected local slot."""
import json,sys,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'fast-sale'))
import instance_context
from source_driver import drive


def main():
    saved=instance_context.binding()
    if not saved or saved.get('character')!='厚礼蟹':raise RuntimeError('当前槽未绑定厚礼蟹')
    instance_context.verify_binding(saved)
    return drive([{'action':'shop_route','categories':['法师地牢持续清怪拾取'],'foreground':False}])


if __name__=='__main__':
    path=instance_context.runtime_root()/'outputs'/'法师地牢驱动.log'
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8',buffering=1) as log:
        sys.stdout=sys.stderr=log
        try:print(json.dumps(main().get('result'),ensure_ascii=False))
        except Exception:traceback.print_exc();sys.exit(1)
