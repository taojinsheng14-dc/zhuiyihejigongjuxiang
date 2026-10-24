import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import island_automation as island


def snapshot(drops=(),monsters=(),position=(19,18),hero=(18,18),free=20):
    return {'town':False,'position':position,'hero':hero,'free':free,'drops':list(drops),'monsters':list(monsters),'npcs':[]}


def drop(uid,x=20,y=18):return {'id':uid,'x':x,'y':y,'name':'木剑','key_matches':True}
def monster(x=24,y=18):return {'address':7,'name':'祖玛雕像','class':'TSculptureMon','position':(x,y),'dead':False}


class SchedulerTests(unittest.TestCase):
    def test_nearest_eligible_drop_precedes_distant_statue(self):
        s=island.Scheduler();action,target=s.choose(snapshot([drop(1,25),drop(2,20)],[monster()]),0)
        self.assertEqual((action,target['id']),('pickup',2))

    def test_hero_occupied_drop_waits_for_combat_then_becomes_pickable(self):
        s=island.Scheduler();blocked=drop(1,18,16)
        self.assertEqual(s.choose(snapshot([blocked],[monster()],hero=(18,16)),0)[0],'approach')
        self.assertEqual(s.choose(snapshot([blocked],hero=(18,16)),1)[0],'pickup')
        self.assertEqual(s.failures,{})

    def test_unblocked_drop_still_precedes_combat(self):
        s=island.Scheduler();blocked=drop(1,18,16);clear=drop(2,22,18)
        action,target=s.choose(snapshot([blocked,clear],[monster()],hero=(18,16)),0)
        self.assertEqual((action,target['id']),('pickup',2))

    def test_target_remains_sticky_until_done(self):
        s=island.Scheduler();s.choose(snapshot([drop(1,23)]),0)
        self.assertEqual(s.choose(snapshot([drop(1,23),drop(2,20)]),.2)[1]['id'],1)
        s.feedback(drop(1),{'verified':True},.3)
        self.assertEqual(s.choose(snapshot([drop(2)]),.4)[1]['id'],2)

    def test_progressing_pickup_does_not_get_blocked_cooldown(self):
        s=island.Scheduler();s.feedback(drop(1),{'status':'approaching'},1)
        self.assertEqual(s.retry_at,{})
        self.assertEqual(s.choose(snapshot([drop(1)]),1.1)[0],'pickup')

    def test_blocked_item_cooldown_does_not_block_other_drops(self):
        s=island.Scheduler();s.feedback(drop(1),{'status':'blocked'},0)
        self.assertEqual(s.choose(snapshot([drop(1),drop(2,24)]),.2)[1]['id'],2)

    def test_three_failures_never_retry_forever(self):
        s=island.Scheduler()
        for t in (0,2,5):s.feedback(drop(1),{'status':'blocked'},t)
        self.assertEqual(s.choose(snapshot([drop(1)]),9)[0],'stop')

    def test_drop_under_monster_causes_approach_not_pickup(self):
        s=island.Scheduler();self.assertEqual(s.choose(snapshot([drop(1,24)],[monster()]),0)[0],'approach')

    def test_visible_sculpture_nearby_waits_for_hero_without_f1(self):
        s=island.Scheduler();self.assertEqual(s.choose(snapshot(monsters=[monster(20)]),0)[0],'wait')

    def test_empty_requires_multiple_samples_and_one_second(self):
        s=island.Scheduler()
        self.assertEqual([s.choose(snapshot(),t)[0] for t in (0,.2,.4,1.1)],['wait','wait','wait','advance'])

    def test_new_drop_resets_clear_gate(self):
        s=island.Scheduler();s.choose(snapshot(),0);s.choose(snapshot(),.5)
        self.assertEqual(s.choose(snapshot([drop(1)]),1.1)[0],'pickup')
        self.assertEqual(s.choose(snapshot(),1.2)[0],'wait')

    def test_full_bag_stops_before_pickup_or_next_level(self):
        self.assertEqual(island.Scheduler().choose(snapshot([drop(1)],free=0),0)[0],'stop')

    def test_disappearance_is_not_credited_as_pickup(self):
        s=island.Scheduler();s.feedback(drop(1),{'status':'removed_at_target','ground_remaining':False},1)
        self.assertIsNone(s.target)

    def test_unknown_item_state_rejected(self):
        with self.assertRaises(RuntimeError):island.Scheduler().feedback(drop(1),{'error_detail':'拿起物品'},0)

    def test_no_progress_stops_but_moving_monster_is_not_falsely_stalled(self):
        s=island.Scheduler();s.choose(snapshot(monsters=[monster(20)]),0)
        self.assertEqual(s.choose(snapshot(monsters=[monster(20)]),121)[0],'stop')
        self.assertNotEqual(s.choose(snapshot(monsters=[monster(21)]),122)[0],'stop')


class LoopTests(unittest.TestCase):
    def test_sixtieth_request_does_not_block_final_exit(self):
        s=self.session()
        with patch.object(island,'observe',return_value=snapshot()),patch.object(island,'open_corner',side_effect=lambda session:setattr(s,'merchant',True)),patch.object(island.legacy,'next_level',return_value={'status':'left_island'}) as advance,patch.object(island,'log'),patch.object(island.time,'monotonic',side_effect=lambda:s.now):
            result=island.run_loop(s,transitions=60)
        self.assertTrue(result['completion_verified']);self.assertEqual(result['transitions'],61)
        advance.assert_called_once()
    def session(self):
        s=SimpleNamespace(now=0,merchant=False,check=Mock(),close_panels=Mock(),in_mengzhong_return_area=lambda:True,inventory=lambda:['']*40)
        s.pause=lambda seconds:setattr(s,'now',s.now+seconds)
        s.visible=lambda key:s.merchant if key=='merchant' else False
        return s

    def test_replay_drop_activation_clear_two_transitions_and_town(self):
        s=self.session();state={'drop':True,'approached':False,'level':0};actions=[]
        def observe(session):
            if state['level']>=2:return {'town':True}
            monsters=[monster(24)] if not state['approached'] else ([monster(20)] if s.now<1 else [])
            return snapshot([drop(1)] if state['drop'] else [],monsters)
        def pick(session,target):state['drop']=False;actions.append('pickup');return {'verified':True,'status':'completed'}
        def move(*args):state['approached']=True;actions.append('activate');return {'status':'moved'}
        def opened(session):s.merchant=True;actions.append('open')
        def advance(session):state['level']+=1;s.merchant=False;actions.append('transition');return {'status':'transition_confirmed'}
        with patch.object(island,'observe',side_effect=observe),patch.object(island,'pick_one',side_effect=pick),patch.object(island,'move_one',side_effect=move),patch.object(island,'open_corner',side_effect=opened),patch.object(island.legacy,'next_level',side_effect=advance),patch.object(island,'log'),patch.object(island.time,'monotonic',side_effect=lambda:s.now):
            r=island.run_loop(s,seconds=20)
        self.assertEqual(r['status'],'completed');self.assertEqual(r['picked_verified'],1);self.assertEqual(r['transitions'],2)
        self.assertEqual(actions[:2],['pickup','activate']);self.assertEqual(actions.count('transition'),2)

    def test_hero_blocked_loot_does_not_spend_unblock_budget_during_combat(self):
        s=self.session();blocked=drop(1,18,16)
        samples=[snapshot([blocked],[monster(20)],hero=(18,16)),snapshot([blocked],hero=(22,22)),{'town':True}]
        with patch.object(island,'observe',side_effect=samples),patch.object(island,'pick_one',return_value={'verified':True}) as pick,patch.object(island,'move_one') as move,patch.object(island,'log'),patch.object(island.time,'monotonic',side_effect=lambda:s.now):
            result=island.run_loop(s)
        pick.assert_called_once();move.assert_not_called()
        self.assertEqual(result['picked_verified'],1)

    def test_open_bag_waits_without_input_then_resumes_on_close(self):
        s=self.session();s.bag=True
        s.visible=lambda key:s.bag if key=='bag' else False
        s.held_item=lambda:'';s.sale_item=lambda:'';s.inflight_item=lambda:'';s.login_stage=lambda:'playing'
        def pause(seconds):s.now+=seconds;s.bag=False
        s.pause=pause
        with patch.object(island,'header',return_value=island.ISLAND_HEADER),patch.object(island,'observe',return_value={'town':True}) as observe,patch.object(island,'pick_one') as pick,patch.object(island,'log'),patch.object(island.time,'monotonic',side_effect=lambda:s.now):
            r=island.run_loop(s)
        observe.assert_called_once();pick.assert_not_called();s.close_panels.assert_not_called()
        self.assertTrue(r['completion_verified'])

    def test_new_monster_after_open_cancels_transition(self):
        s=self.session();samples=[snapshot(),snapshot(),snapshot(),snapshot(),snapshot(),snapshot(),snapshot(monsters=[monster(20)])]
        def observe(session):
            if samples:return samples.pop(0)
            raise RuntimeError('test_done')
        with patch.object(island,'observe',side_effect=observe),patch.object(island,'open_corner',side_effect=lambda session:setattr(s,'merchant',True)),patch.object(island.legacy,'next_level') as next_level,patch.object(island.time,'monotonic',side_effect=lambda:s.now):
            with self.assertRaisesRegex(RuntimeError,'test_done'):island.run_loop(s)
            next_level.assert_not_called();s.close_panels.assert_called()

    def test_unconfirmed_transition_has_only_one_dice_request(self):
        s=self.session()
        with patch.object(island,'observe',return_value=snapshot()),patch.object(island,'open_corner',side_effect=lambda session:setattr(s,'merchant',True)),patch.object(island.legacy,'next_level',return_value={'status':'transition_unconfirmed'}) as next_level,patch.object(island,'log'),patch.object(island.time,'monotonic',side_effect=lambda:s.now):
            with self.assertRaisesRegex(RuntimeError,'不重复掷骰'):island.run_loop(s)
            next_level.assert_called_once()

    def test_transient_load_does_not_cause_input_or_false_completion(self):
        s=self.session()
        with patch.object(island,'observe',side_effect=[island.TransientScene('加载'),{'town':True}]),patch.object(island,'pick_one') as pick,patch.object(island.time,'monotonic',side_effect=lambda:s.now):
            result=island.run_loop(s)
            self.assertTrue(result['completion_verified']);pick.assert_not_called()

    def test_persistent_incomplete_scene_stops_without_input(self):
        s=self.session()
        with patch.object(island,'observe',side_effect=island.TransientScene('列表缺失')),patch.object(island,'pick_one') as pick,patch.object(island.time,'monotonic',side_effect=lambda:s.now):
            with self.assertRaisesRegex(RuntimeError,'八秒'):island.run_loop(s)
            pick.assert_not_called()

    def test_user_stop_propagates_without_retry(self):
        s=self.session();s.check.side_effect=RuntimeError('用户已停止')
        with patch.object(island,'observe') as observe:
            with self.assertRaisesRegex(RuntimeError,'用户已停止'):island.run_loop(s)
            observe.assert_not_called()


class LedgerTests(unittest.TestCase):
    def test_same_role_process_can_finish_yesterdays_entry_after_midnight(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'daily.json'
            p.write_text(json.dumps({'role|yesterday':{'status':'entered','map_header':island.ISLAND_HEADER.hex(),'game_pid':42,'instance':'1'}}),encoding='utf8')
            session=SimpleNamespace(reader=SimpleNamespace(pid=42),hero_ready=lambda:True)
            with patch.object(island.legacy,'STATE',p),patch.object(island,'role_key',return_value='role|today'),patch.object(island.instance_context,'slot',return_value='1'),patch.object(island,'header',return_value=island.ISLAND_HEADER),patch.object(island,'run_loop',return_value={'status':'completed','completion_verified':True}),patch.object(island,'log'),patch.object(island.legacy,'enter_once') as enter:
                island.run(session,resume=True)
            saved=json.loads(p.read_text(encoding='utf8'))
            self.assertNotIn('role|today',saved);self.assertEqual(saved['role|yesterday']['status'],'completed')
            enter.assert_not_called()
    def setup_ledger(self,folder,entry):
        p=Path(folder)/'state.json';p.write_text(json.dumps({'role|today':entry} if entry else {}),encoding='utf8');return p

    def test_existing_daily_attempt_cannot_reenter(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.setup_ledger(folder,{'status':'entry_requested'})
            with patch.object(island.legacy,'STATE',p),patch.object(island,'role_key',return_value='role|today'),patch.object(island.legacy,'enter_once') as enter:
                with self.assertRaisesRegex(RuntimeError,'禁止重复进入'):island.run(SimpleNamespace())
                enter.assert_not_called()

    def test_resume_requires_own_confirmed_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.setup_ledger(folder,None)
            with patch.object(island.legacy,'STATE',p),patch.object(island,'role_key',return_value='role|today'):
                with self.assertRaisesRegex(RuntimeError,'没有本角色'):island.run(SimpleNamespace(),resume=True)

    def test_resume_does_not_reenter_and_retains_transition_count(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.setup_ledger(folder,{'status':'entered','map_header':island.ISLAND_HEADER.hex(),'transitions':9,'game_pid':10})
            s=SimpleNamespace(reader=SimpleNamespace(pid=10),_sale_recovery_enabled=True,hero_ready=lambda:True)
            def run_loop(session,progress,transitions,on_transition,melee=None):
                self.assertEqual(transitions,9);self.assertFalse(session._sale_recovery_enabled);on_transition(10)
                return {'status':'completed','completion_verified':True}
            with patch.object(island.legacy,'STATE',p),patch.object(island,'role_key',return_value='role|today'),patch.object(island,'header',return_value=island.ISLAND_HEADER),patch.object(island,'run_loop',side_effect=run_loop),patch.object(island,'log'),patch.object(island.legacy,'enter_once') as enter:
                island.run(s,resume=True);enter.assert_not_called()
            entry=json.loads(p.read_text(encoding='utf8'))['role|today']
            self.assertEqual(entry['transitions'],10);self.assertEqual(entry['status'],'completed');self.assertTrue(s._sale_recovery_enabled)

    def test_old_client_resume_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.setup_ledger(folder,{'status':'entered','map_header':island.ISLAND_HEADER.hex(),'game_pid':10})
            with patch.object(island.legacy,'STATE',p),patch.object(island,'role_key',return_value='role|today'),patch.object(island,'header',return_value=island.ISLAND_HEADER):
                with self.assertRaisesRegex(RuntimeError,'旧客户端'):island.run(SimpleNamespace(reader=SimpleNamespace(pid=11)),resume=True)

    def test_daily_start_does_not_leave_current_hunt_map(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.setup_ledger(folder,None);s=SimpleNamespace(in_mengzhong_return_area=lambda:False,close_panels=Mock())
            with patch.object(island.legacy,'STATE',p),patch.object(island,'role_key',return_value='role|today'):
                with self.assertRaisesRegex(RuntimeError,'不会退出当前挂机图'):island.run(s)
            s.close_panels.assert_not_called()


class EntryAndMenuTests(unittest.TestCase):
    def test_resume_summons_missing_hero_before_loop_without_reentry(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'daily.json';p.write_text(json.dumps({'role|today':{'status':'entered','map_header':island.ISLAND_HEADER.hex(),'game_pid':42}}),encoding='utf8')
            session=SimpleNamespace(reader=SimpleNamespace(pid=42),hero_ready=lambda:False,
                check=Mock(),login_stage=lambda:'playing',held_item=lambda:'',sale_item=lambda:'',inflight_item=lambda:'',ensure_hero_available=Mock())
            with patch.object(island.legacy,'STATE',p),patch.object(island,'role_key',return_value='role|today'),patch.object(island,'header',return_value=island.ISLAND_HEADER),patch.object(island,'run_loop',return_value={'status':'completed','completion_verified':True}),patch.object(island,'log'),patch.object(island.legacy,'enter_once') as enter:
                island.run(session,resume=True)
                session.ensure_hero_available.assert_called_once();enter.assert_not_called()

    def test_daily_start_enters_once_and_completes_with_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'daily.json'
            session=SimpleNamespace(reader=SimpleNamespace(pid=42),in_mengzhong_return_area=lambda:True,
                close_panels=Mock(),unique_npc=Mock(return_value={'name':'孤岛挑战'}),open_npc=Mock(),hero_ready=lambda:True)
            def enter(s,verified_npc=None):
                p.write_text(json.dumps({'role|today':{'status':'entered','map_header':island.ISLAND_HEADER.hex()}}),encoding='utf8')
                return {'status':'entered'}
            with patch.object(island.legacy,'STATE',p),patch.object(island,'role_key',return_value='role|today'),patch.object(island.legacy,'enter_once',side_effect=enter) as entered,patch.object(island,'header',return_value=island.ISLAND_HEADER),patch.object(island,'run_loop',return_value={'status':'completed','completion_verified':True}),patch.object(island,'log'):
                with patch.object(island,'locate_town_entrance',return_value={'name':'孤岛挑战'}):island.run(session)
                entered.assert_called_once()
                with self.assertRaisesRegex(RuntimeError,'禁止重复进入'):island.run(session)
                entered.assert_called_once()
            self.assertEqual(json.loads(p.read_text(encoding='utf8'))['role|today']['status'],'completed')

    def test_stop_keeps_entry_for_resume_without_recovering(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'daily.json';p.write_text(json.dumps({'role|today':{'status':'entered','map_header':island.ISLAND_HEADER.hex(),'game_pid':1}}),encoding='utf8')
            session=SimpleNamespace(reader=SimpleNamespace(pid=1),_sale_recovery_enabled=True,hero_ready=lambda:True)
            with patch.object(island.legacy,'STATE',p),patch.object(island,'role_key',return_value='role|today'),patch.object(island,'header',return_value=island.ISLAND_HEADER),patch.object(island,'run_loop',side_effect=RuntimeError('用户停止')),patch.object(island,'log'):
                with self.assertRaisesRegex(RuntimeError,'用户停止'):island.run(session,resume=True)
            entry=json.loads(p.read_text(encoding='utf8'));self.assertEqual(entry['role|today']['status'],'entered')
            self.assertEqual(entry['role|today']['last_error'],'用户停止');self.assertTrue(session._sale_recovery_enabled)

    def test_menu_click_is_relative_to_current_control_and_dpi(self):
        from background_sale import BackgroundSession
        session=SimpleNamespace(control_info=lambda offset,name:{'visible':True,'bounds':(100,50,432,261)},
            client_size=lambda:(1280,800),hero_covers=lambda box:False)
        with patch.object(BackgroundSession,'background_mouse') as click:
            island.legacy.click_start_link(session)
            self.assertEqual(click.call_args.args[1],(164,188));self.assertTrue(click.call_args.kwargs['dpi_scaled'])

    def test_occluded_menu_link_never_clicked(self):
        from background_sale import BackgroundSession
        session=SimpleNamespace(control_info=lambda offset,name:{'visible':True,'bounds':(0,0,432,261)},
            client_size=lambda:(1280,800),hero_covers=lambda box:True)
        with patch.object(BackgroundSession,'background_mouse') as click:
            with self.assertRaisesRegex(RuntimeError,'遮挡'):island.legacy.click_start_link(session)
            click.assert_not_called()

    def test_runtime_paths_are_independent(self):
        import instance_context
        self.assertNotEqual(instance_context.runtime_root(instance='1'),instance_context.runtime_root(instance='2'))
        self.assertEqual(island.ROOT/'outputs'/'孤岛挑战状态.json',island.legacy.STATE)

    def test_same_map_new_corner_objects_are_transition_not_second_entry(self):
        state={'clicked':False}
        class Session:
            base=0
            def visible(self,key):return not state['clicked']
            def nearby_monsters(self,radius):return {'loaded_monster_alive':0}
            def npcs(self):return [{'name':'孤岛挑战','map':p,'address':i+(100 if state['clicked'] else 0)} for i,p in enumerate(sorted(island.CORNERS))]
            def held_item(self):return ''
            sale_item=held_item;inflight_item=held_item
            def uint(self,address):return 1
            def read(self,address,size):return island.ISLAND_HEADER
            def player(self):return (19,18)
            def pause(self,seconds):pass
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'daily.json';p.write_text(json.dumps({'today':{'status':'entered','map_header':island.ISLAND_HEADER.hex()},'other':{'status':'entered','map_header':'not_this_map'}}),encoding='utf8')
            with patch.object(island.legacy,'ROOT',Path(folder)),patch.object(island.legacy,'STATE',p),patch('ground_item_probe.ground_snapshot',return_value={'ground_maps':[{'stable':True,'items':[{'name':'强效金创药'}]}]}),patch.object(island.legacy,'click_start_link',side_effect=lambda s:state.update(clicked=True)):
                (Path(folder)/'outputs').mkdir();result=island.legacy.next_level(Session())
            self.assertEqual(result['status'],'transition_confirmed');self.assertEqual(result['evidence'],'corner_objects_recreated')
            self.assertEqual(json.loads(p.read_text(encoding='utf8'))['other']['map_header'],'not_this_map')

    def test_gui_exposes_island_actions_without_starting_them(self):
        import mixed_sale_gui as gui
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(gui,'ROOT',Path(folder)),patch.object(gui,'drive') as drive:
                app=gui.App();app.withdraw()
                try:
                    self.assertEqual(len(app.island_buttons),3)
                    self.assertIn('孤岛挑战',[app.tabs.tab(t,'text') for t in app.tabs.tabs()]);drive.assert_not_called()
                finally:app.destroy()



class CornerRetryTests(unittest.TestCase):
    def scene(self):
        s=snapshot()
        s['npcs']=[{'name':'孤岛挑战','map':next(iter(island.CORNERS)),'draw':{'x':1}}]
        return s

    def session(self):
        return SimpleNamespace(check=Mock(),stable_player=Mock(),npc_click_point=Mock(),
            open_npc=Mock(),visible=Mock(return_value=True),player=Mock(return_value=(19,18)),pause=Mock())

    def test_transient_missing_click_point_retries_without_moving(self):
        s=self.session();s.npc_click_point.side_effect=[None,(100,100)]
        with patch.object(island,'observe',return_value=self.scene()),patch.object(island,'log'),patch.object(island,'move_one') as move:
            self.assertTrue(island.open_corner(s));move.assert_not_called()
        s.open_npc.assert_called_once();self.assertEqual(s.pause.call_count,1)

    def test_offscreen_npc_approached_after_three_samples(self):
        s=self.session();s.npc_click_point.side_effect=[None,None,None,(100,100)]
        with patch.object(island,'observe',return_value=self.scene()),patch.object(island,'log'),patch.object(island,'move_one',return_value={'status':'moved'}) as move:
            self.assertTrue(island.open_corner(s));move.assert_called_once()

    def test_new_drop_prevents_npc_click(self):
        s=self.session();scene=self.scene();scene['drops']=[drop(1)]
        with patch.object(island,'observe',return_value=scene):
            self.assertFalse(island.open_corner(s))
        s.open_npc.assert_not_called()

    def test_persistent_missing_click_point_stops_after_six_samples(self):
        s=self.session();s.npc_click_point.return_value=None
        with patch.object(island,'observe',return_value=self.scene()) as observe,patch.object(island,'log'),patch.object(island,'move_one',return_value={'status':'blocked'}):
            with self.assertRaises(RuntimeError):island.open_corner(s)
        self.assertEqual(observe.call_count,6);s.open_npc.assert_not_called()


if __name__=='__main__':unittest.main()
