import sys, time, json, traceback, importlib
from pathlib import Path
source = Path(__file__).resolve().parent
sys.path.insert(0, str(source.parent/'fast-sale'))
import instance_context
root=instance_context.helper_directory()
root.mkdir(parents=True,exist_ok=True)
import background_sale
lease_kernel,lease_handle=instance_context.helper_lease()
s = None
out = {'progress':[]}
try:
    out['instance']=instance_context.slot()
    s = background_sale.BackgroundSession()
    # A new session must never execute an old step-1 command automatically.
    (root/'source-sale-command.json').unlink(missing_ok=True)
    (root/'source-sale-cancel.json').unlink(missing_ok=True)
    def save():
        try:out['state']=s.state()
        except (RuntimeError,OSError) as error:
            out['state']={'helper_pid':__import__('os').getpid(),'game_pid':s.reader.pid,'in_game':False,'read_error':str(error)}
        try:
            s.capture_client().save(root/'source-sale-current.png')
            out.pop('capture_error',None)
        except (OSError,RuntimeError) as error:
            out['capture_error']=str(error)
        temp=root/'source-sale-result.tmp'
        temp.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
        for attempt in range(50):
            try:
                temp.replace(root/'source-sale-result.json')
                break
            except PermissionError:
                if attempt==49:raise
                time.sleep(.02)
    try:out['npcs']=s.npcs()
    except (RuntimeError,OSError):out['npcs']=[]
    out['stage'] = 'ready'
    save()
    if '--login-on-connect' in sys.argv and s.login_stage()!='playing':
        def connection_progress(message):
            out['progress'].append(message)
            save()
        out['stage']='connecting'
        save()
        try:
            out['result']=s.recover_session(connection_progress)
            out['stage']='ready'
        except Exception as error:
            out['error']=str(error)
            out['trace']=traceback.format_exc()
            out['stage']='connection_failed'
        save()
    s.start_live_monitor()
    deadline = time.monotonic()+43200
    step = 0
    while time.monotonic()<deadline:
        path = root/'source-sale-command.json'
        if not path.exists():time.sleep(.1);continue
        try:command=json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError,ValueError):time.sleep(.05);continue
        if command.get('step')!=step+1:time.sleep(.1);continue
        step+=1
        if command['action']=='stop':break
        importlib.reload(background_sale)
        s.__class__=background_sale.ForegroundSession if command.get('foreground') else background_sale.BackgroundSession
        out.pop('result',None)
        out.pop('trace',None)
        try:
            if command['action']=='run':
                def progress(message):
                    out['progress'].append(message)
                    save()
                out['stage']='running'
                out['result']=s.teleport_weapon_sale(progress=progress)
                out['stage']='finished'
            elif command['action']=='click':
                s.click(command['point']);time.sleep(.8)
            elif command['action']=='npcs':out['npcs']=s.npcs()
            elif command['action']=='open_npc':
                actors=[n for n in s.npcs() if n['name']==command['name']]
                if len(actors)!=1:raise RuntimeError('未唯一找到指定商人')
                s.open_npc(actors[0])
            elif command['action']=='category':
                out['result']=s.sell_category(command['category'],merchant_name=command['merchant'])
            elif command['action']=='walk_to':
                out['result']=s.walk_tile(tuple(command['target']))
            elif command['action']=='shop_route':
                def progress(message):
                    out['progress'].append(message)
                    save()
                out['result']=s.run_shop_route(command.get('categories'),progress)
            elif command['action']=='return_town':
                out['result']=s.return_to_veteran()
            elif command['action']=='close_ui':
                from fast_sale import button_center
                for key,offset,name in [('sell',0x63c,'Button_SellDlgClose'),('bag',0x48c,'Button_ItemBagClose'),('merchant',0x5e4,'Button_MerchantDlgClose')]:
                    if s.visible(key):
                        close=s.control_info(offset,name)
                        s.click(button_center(s.bounds(key),close['bounds']));s.pause(.3)
            elif command['action']=='observe':pass
            else:raise RuntimeError('不支持的动作')
            out.pop('error',None)
        except Exception as e:
            out['error']=str(e);out['trace']=traceback.format_exc();out['stage']='stopped'
        out['completed']=s.sales
        out['step']=step
        save()
except Exception as e:
    out['error']=str(e);out['trace']=traceback.format_exc()
finally:
    if s:
        if getattr(s,'_live_sampler',None):s._live_sampler.stop()
        s.close()
    (root/'source-sale-result.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')

    lease_kernel.CloseHandle(lease_handle)
