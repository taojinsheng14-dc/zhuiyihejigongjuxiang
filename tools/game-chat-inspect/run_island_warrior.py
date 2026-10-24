"""Resume the current paid island run; never enter a new one."""
import sys,json,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'fast-sale'))
import instance_context
from source_driver import drive

if __name__=='__main__':
    path=instance_context.runtime_root()/'outputs'/'孤岛战士驱动.log';path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8',buffering=1) as log:
        sys.stdout=sys.stderr=log
        try:
            saved=instance_context.binding()
            if not saved or saved.get('character')!='微笑':raise RuntimeError('当前槽不是微笑，未接续')
            instance_context.verify_binding(saved)
            result=drive([{'action':'shop_route','categories':['接续孤岛自动挑战'],'foreground':False}])
            print(json.dumps(result.get('result'),ensure_ascii=False))
        except Exception:traceback.print_exc();sys.exit(1)
