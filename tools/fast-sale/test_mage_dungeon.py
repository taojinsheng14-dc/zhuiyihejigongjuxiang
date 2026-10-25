import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock
from mage_dungeon import probe_once
from warrior_combat import HEADER


class MageDungeonTests(unittest.TestCase):
    def session(self, hover=True):
        messages=[];actor=bytearray(0x184)
        struct.pack_into('<I',actor,0,0x12345)
        struct.pack_into('<2i',actor,0x68,201,224)
        struct.pack_into('<2i',actor,0x17c,590,160)
        target={'address':0x90000,'name':'蜈蚣','class':'TCatMon','position':[201,224],
                'distance':2,'dead':False,'on_screen':True}
        def send(hwnd,msg,key,lp,*args):messages.append((msg,key,lp));return 1
        s=SimpleNamespace(base=0,hwnd=1,check=lambda:None,login_stage=lambda:'playing',
            held_item=lambda:'',sale_item=lambda:'',inflight_item=lambda:'',visible=lambda k:False,
            u=SimpleNamespace(IsIconic=lambda h:False,SendMessageTimeoutW=send),
            nearby_monsters=lambda **k:{'read_errors':0,'monsters':[target]},
            scene_actor_snapshot=lambda:[(target['address'],bytes(actor))],
            player=lambda:(202,226),client_size=lambda:(1280,800),physical_client_size=lambda:(1920,1200),
            begin_background_input=lambda:None,clear_background_mouse=Mock(),
            wait_shortcut_modifiers_released=lambda:None,pause=lambda seconds:None)
        def uint(a):
            table={0x2ba608:0x20000,0x20000:0x30000,0x2bac2c:0x40000,0x40000:0xa0000,
                   0xa0358:0,0x2bb0a8:0x70000,0x70000:0x80000,0x2ba8fc:0x71000,0x71000:0x81000,0x2ba340:0x72000,0x72000:0x82000}
            if 0x8018c<=a<=0x801c0:return 0x90000 if a==0x801b8 and hover else 0
            return table[a]
        s.uint=uint;s.read=lambda a,n:HEADER if a==0x30004 else bytes(n)
        return s,messages

    def invoke(self,s):
        with patch('mage_dungeon.inspect_current',return_value={'f1_skill':{'name':'雷电术'}}):
            return probe_once(s)

    def test_near_monster_preempts_distant_locked_target_when_enabled(self):
        s,m=self.session();near=s.nearby_monsters()['monsters'][0]
        far=dict(near,address=0xb0000,distance=7,position=[209,226])
        raw=bytearray(s.scene_actor_snapshot()[0][1]);struct.pack_into('<2i',raw,0x68,209,226)
        rows=s.scene_actor_snapshot()+[(far['address'],bytes(raw))]
        s.scene_actor_snapshot=lambda:rows
        s.nearby_monsters=lambda **kwargs:{'read_errors':0,'monsters':[far,near]}
        with patch('mage_dungeon.inspect_current',return_value={'f1_skill':{'name':'雷电术'}}):
            r=probe_once(s,locked=far,prefer_nearby=True)
        self.assertEqual(r['target']['address'],near['address']);self.assertTrue(r['f1_sent'])

    def test_moving_or_dead_candidate_cancels_cast_before_any_input(self):
        for changed in ('position','dead'):
            s,m=self.session();rows=s.scene_actor_snapshot();raw=bytearray(rows[0][1])
            if changed=='position':struct.pack_into('<2i',raw,0x68,202,224)
            else:raw[0xac]=1
            s.scene_actor_snapshot=lambda:[(0x90000,bytes(raw))]
            r=self.invoke(s)
            self.assertEqual(r['status'],'target_changed_before_aim');self.assertFalse(r['f1_sent'])
            self.assertEqual(m,[])

    def test_unconfirmed_hover_never_sends_f1(self):
        s,m=self.session(hover=False);r=self.invoke(s)
        self.assertFalse(r['f1_sent']);self.assertEqual(r['status'],'hover_target_unconfirmed')
        self.assertFalse(any(msg==0x100 for msg,_,_ in m));s.clear_background_mouse.assert_called_once()

    def test_exact_actor_hover_sends_one_key_pair_with_f1_scan_code(self):
        s,m=self.session();r=self.invoke(s)
        self.assertTrue(r['f1_sent']);self.assertFalse(r['effect_verified'])
        self.assertEqual([(a,b,c) for a,b,c in m if a in (0x100,0x101)],
            [(0x100,0x70,0x3b0001),(0x101,0x70,0xc03b0001)])
        self.assertFalse(any(a in (0x201,0x204) for a,_,_ in m))

    def test_horizontal_hover_alternative_still_requires_same_actor(self):
        s,m=self.session();original=s.uint
        def uint(address):
            if address==0x801b8:
                moves=sum(msg==0x200 for msg,_,_ in m)
                return 0x90000 if moves>=5 else 0
            return original(address)
        s.uint=uint;r=self.invoke(s)
        self.assertTrue(r['f1_sent']);self.assertEqual(r['point'],[574,208])
        self.assertEqual(len(r['hover_observations']),5)

    def test_occluded_target_keeps_identity_for_bounded_avoidance(self):
        s,m=self.session();rows=s.scene_actor_snapshot();raw=bytearray(rows[0][1])
        struct.pack_into('<2i',raw,0x17c,590,160)
        s.scene_actor_snapshot=lambda:rows+[(0xa0000,bytes(raw))]
        r=self.invoke(s)
        self.assertEqual(r['status'],'target_occluded');self.assertEqual(r['target']['address'],0x90000)
        self.assertFalse(any(msg==0x100 for msg,_,_ in m))

    def test_wrong_map_stops_before_any_input(self):
        s,m=self.session();s.read=lambda a,n:bytes(n)
        with self.assertRaisesRegex(RuntimeError,'地牢'):self.invoke(s)
        self.assertEqual(m,[])

    def test_key_released_on_post_down_failure(self):
        s,m=self.session()
        def pause(seconds):
            if seconds==.08:raise RuntimeError('sample failed')
        s.pause=pause
        with self.assertRaisesRegex(RuntimeError,'sample failed'):self.invoke(s)
        self.assertTrue(any(a==0x101 for a,_,_ in m));s.clear_background_mouse.assert_called_once()

    def test_wrong_skill_stops_before_hover(self):
        s,m=self.session()
        with patch('mage_dungeon.inspect_current',return_value={'f1_skill':{'name':'火墙'}}):
            with self.assertRaisesRegex(RuntimeError,'雷电术'):probe_once(s)
        self.assertEqual(m,[])


class BoundedMageTests(unittest.TestCase):
    def run_case(self,spell,monsters=None,drops=None,pickup=None,max_casts=1,player=None,continuous=False,profile=None,capacity_error=None,movement_error=None):
        import tempfile
        from pathlib import Path
        from contextlib import ExitStack
        from mage_dungeon import run_bounded
        original=lambda header:'original'
        s=SimpleNamespace(navigation_map=original,player=player or (lambda:(20,20)),pause=lambda n:None,
            nearby_monsters=lambda **k:{'read_errors':0,'monsters':monsters or []},clear_background_mouse=Mock())
        with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
            stack.enter_context(patch('mage_dungeon.guard'))
            stack.enter_context(patch('pickup_strategy.context',return_value={'monsters':monsters or [],'hero':None,'position':(20,20),'npcs':[]}))
            stack.enter_context(patch('dungeon_route.CoverageRoute',return_value=SimpleNamespace(snapshot=lambda:{},next_goal=lambda *a:(30,30),visited=set(),points={(30,30)},defer_goal=lambda now:None)))
            stack.enter_context(patch('mage_dungeon.probe_once',side_effect=spell))
            stack.enter_context(patch('warrior_combat.patrol_plan',return_value=(object(),{'waypoints':[(20,20),(30,30)]})))
            stack.enter_context(patch('inventory_flow.ensure_loot_capacity',side_effect=capacity_error))
            stack.enter_context(patch('warrior_combat.patrol_move',side_effect=movement_error,return_value={'from':(20,20),'to':(20,20)}))
            stack.enter_context(patch('ground_item_probe.ground_snapshot',**({'side_effect':drops} if callable(drops) else {'return_value':{'ground_maps':[{'items':drops or []}]}})))
            stack.enter_context(patch('island_pickup_policy.filter_drops',side_effect=lambda rows:(rows,[])))
            stack.enter_context(patch('ground_item_probe.pickup_current_test',**({'side_effect':pickup} if callable(pickup) else {'return_value':pickup})))
            stack.enter_context(patch('instance_context.runtime_root',return_value=Path(folder)))
            result=run_bounded(s,max_casts=max_casts,continuous=continuous,profile=profile)
        self.assertIs(s.navigation_map,original);s.clear_background_mouse.assert_called_once()
        return result

    def test_warrior_native_attack_wait_does_not_reclick_or_move(self):
        from current_map_hunt import PanelOpen
        probe=Mock(side_effect=[{'attack_sent':True,'target':{'address':1,'name':'蜈蚣'}},
            {'status':'native_attack_wait','engaged':True},RuntimeError('finished warrior wait')])
        profile=SimpleNamespace(combat_mode='warrior',probe=probe,guard=Mock(),check_state=Mock(),header=HEADER,
            names={'蜈蚣'},panel_exception=PanelOpen,wait_for_panels=lambda s:False,
            plan=lambda s:(object(),{'waypoints':[(20,20),(30,30)]}),approach=Mock(),reset_combat=Mock())
        spell=Mock(side_effect=AssertionError('warrior must not use mage F1'))
        with self.assertRaisesRegex(RuntimeError,'finished warrior wait'):
            self.run_case(spell,profile=profile,continuous=True)
        spell.assert_not_called();profile.approach.assert_not_called();self.assertEqual(probe.call_count,3)

    def test_changed_standing_position_retries_deferred_target_before_timeout(self):
        from current_map_hunt import PanelOpen
        target={'address':1,'name':'蜈蚣'};seen=[]
        def spell(*args,**kwargs):
            seen.append(set(kwargs.get('excluded',())))
            index=len(seen)
            if index in (1,5):return {'f1_sent':True,'target':target}
            return {'status':'hover_target_unconfirmed' if index in (2,3) else 'no_verified_target','f1_sent':False,'target':target}
        profile=SimpleNamespace(guard=Mock(),check_state=Mock(),header=HEADER,names={'蜈蚣'},panel_exception=PanelOpen,
            wait_for_panels=lambda s:False,plan=lambda s:(object(),{'waypoints':[(20,20),(30,30)]}),
            approach=Mock(return_value={'movement':True,'nearby_combat':True,'target':target,'from':(20,20),'to':(21,20)}))
        with self.assertRaisesRegex(RuntimeError,'finished'):
            self.run_case(spell,profile=profile,continuous=True,max_casts=2,
                capacity_error=[None,None,None,None,None,RuntimeError('finished')])
        self.assertIn(1,seen[3]);self.assertNotIn(1,seen[4])
        self.assertGreaterEqual(profile.approach.call_count,1)

    def test_blocked_drop_route_defers_and_returns_to_fresh_combat(self):
        reads=[0]
        def drops(*args):
            reads[0]+=1
            return {'ground_maps':[{'items':[{'id':7,'name':'金币','x':20,'y':20}] if reads[0]<=4 else []}]}
        spell=Mock(side_effect=RuntimeError('test cancellation after route deferral'))
        with self.assertRaisesRegex(RuntimeError,'test cancellation after route deferral'):
            self.run_case(spell,drops=drops,pickup={'status':'blocked','verified':False},continuous=True,
                          movement_error=RuntimeError('巡逻目标当前没有可走路径'))
        spell.assert_called_once()
        self.assertEqual(reads[0],5)

    def test_no_route_confirmed_dead_end_dispatches_escape_then_resamples(self):
        from current_map_hunt import DeadEndDetected,PanelOpen
        reads=[0]
        def drops(*args):
            reads[0]+=1
            return {'ground_maps':[{'items':[{'id':7,'name':'金币','x':20,'y':20}] if reads[0]<=4 else []}]}
        profile=SimpleNamespace(guard=Mock(),check_state=Mock(),header=HEADER,names={'蜈蚣'},panel_exception=PanelOpen,
            dead_end_exception=DeadEndDetected,confirm_dead_end=Mock(return_value=True),
            escape_dead_end=Mock(return_value={'random_used':True}),wait_for_panels=lambda s:False,
            plan=lambda s:(object(),{'waypoints':[(20,20),(30,30)]}),approach=Mock())
        spell=Mock(side_effect=RuntimeError('fresh sample after escape'))
        with self.assertRaisesRegex(RuntimeError,'fresh sample after escape'):
            self.run_case(spell,drops=drops,pickup={'status':'blocked','verified':False},continuous=True,
                          profile=profile,movement_error=RuntimeError('巡逻目标当前没有可走路径'))
        profile.escape_dead_end.assert_called_once();spell.assert_called_once()

    def test_blocked_drop_route_does_not_swallow_independent_guard_error(self):
        with self.assertRaisesRegex(RuntimeError,'map identity changed'):
            self.run_case(Mock(),drops=[{'id':7,'name':'金币','x':20,'y':20}],
                          pickup={'status':'blocked','verified':False},continuous=True,
                          movement_error=RuntimeError('map identity changed'))

    def test_activity_panel_opening_between_actions_does_not_end_command(self):
        from current_map_hunt import PanelOpen
        checks=[0]
        def guard(session):
            checks[0]+=1
            if checks[0]==2:raise PanelOpen('system activity')
        profile=SimpleNamespace(guard=guard,check_state=Mock(),header=HEADER,names={'蜈蚣'},panel_exception=PanelOpen,
            wait_for_panels=lambda s:False,plan=lambda s:(object(),{'waypoints':[(20,20),(30,30)]}),approach=lambda *a:{'movement':False})
        r=self.run_case(lambda *a,**k:{'f1_sent':True,'target':{'address':1,'name':'蜈蚣'}},profile=profile)
        self.assertEqual(r['casts_sent'],1);self.assertEqual(r['status'],'bounded_end')
        self.assertGreaterEqual(checks[0],4)

    def test_full_bags_handoff_requires_explicit_profile_authorization(self):
        from inventory_flow import DualBagsFull
        from current_map_hunt import PanelOpen
        profile=SimpleNamespace(guard=Mock(),check_state=Mock(),header=HEADER,names={'蜈蚣'},panel_exception=PanelOpen,
            wait_for_panels=lambda s:False,plan=lambda s:(object(),{'waypoints':[(20,20),(30,30)]}),approach=Mock(),return_when_full=True)
        r=self.run_case(Mock(side_effect=AssertionError('must not attack')),profile=profile,capacity_error=DualBagsFull('both full'))
        self.assertEqual(r['status'],'bags_full');self.assertEqual(r['casts_sent'],0)
        with self.assertRaises(DualBagsFull):self.run_case(Mock(),capacity_error=DualBagsFull('both full'))

    def test_transient_target_changes_resample_without_movement_or_stopping(self):
        calls=[0]
        def spell(*args,**kwargs):
            calls[0]+=1
            if calls[0]<=3:return {'status':'target_changed_before_aim','f1_sent':False,'target':{'address':1,'name':'蜈蚣'}}
            self.assertIsNone(kwargs['locked'])
            return {'f1_sent':True,'target':{'address':2,'name':'蜈蚣'}}
        r=self.run_case(spell)
        self.assertEqual(calls[0],4);self.assertEqual(r['casts_sent'],1)
        self.assertEqual(r['movement_segments'],0);self.assertEqual(r['status'],'bounded_end')

    def test_cast_limit_is_finite_and_not_a_kill_claim(self):
        r=self.run_case(lambda *a,**k:{'f1_sent':True,'target':{'address':1,'name':'蜈蚣'}})
        self.assertEqual(r['casts_sent'],1);self.assertEqual(r['observed_deaths'],0)
        self.assertFalse(r['unattended_acceptance'])

    def test_disappearing_target_is_not_counted_as_dead(self):
        r=self.run_case(lambda *a,**k:{'f1_sent':True,'target':{'address':1,'name':'蜈蚣'}},max_casts=2)
        self.assertEqual(r['status'],'bounded_end');self.assertEqual(r['observed_deaths'],0)
        self.assertEqual(r['unverified_target_losses'],1);self.assertEqual(r['casts_sent'],2)

    def test_removed_drop_without_inventory_evidence_stops(self):
        r=self.run_case(lambda *a,**k:(_ for _ in ()).throw(AssertionError('must not cast')),
            drops=[{'id':7,'name':'金币','x':20,'y':20}],pickup={'status':'removed_at_target','verified':False})
        self.assertEqual(r['status'],'pickup_unverified');self.assertEqual(r['verified_pickups'],0)


    def test_accessible_drop_interrupts_a_live_locked_target(self):
        reads=[0];target={'address':1,'name':'蜈蚣','dead':False,'position':(22,20)}
        def drops(*args):
            reads[0]+=1
            return {'ground_maps':[{'items':[] if reads[0]==1 else [{'id':7,'name':'金币','x':20,'y':20}]}]}
        r=self.run_case(lambda *a,**k:{'f1_sent':True,'target':target},monsters=[target],drops=drops,
                        pickup={'status':'unverified','verified':False},max_casts=2)
        self.assertEqual(r['casts_sent'],1)
        self.assertEqual(r['status'],'pickup_unverified')

    def test_hero_leading_does_not_exhaust_three_pickup_attempts(self):
        attempts=[0]
        def pickup(*args,**kwargs):
            attempts[0]+=1
            return {'status':'hero_moved' if attempts[0]<=4 else 'unverified','verified':False}
        r=self.run_case(lambda *a,**k:(_ for _ in ()).throw(AssertionError('must not cast')),
                        drops=[{'id':7,'name':'金币','x':20,'y':20}],pickup=pickup)
        self.assertEqual(attempts[0],5)
        self.assertEqual(r['status'],'pickup_unverified')

    def test_zero_health_then_removal_is_observation_not_precise_kill(self):
        calls=[0]
        def spell(*args,**kwargs):
            calls[0]+=1
            return {'f1_sent':True,'target':{'address':calls[0],'name':'蜈蚣'},
                    'target_vitals_after':{'0x11a':230,'0x112':0}}
        r=self.run_case(spell,max_casts=2)
        self.assertEqual(r['observed_deaths'],1)
        self.assertNotIn('kills',r)
        self.assertFalse(r['unattended_acceptance'])


    def test_zero_health_transition_without_aimable_target_waits(self):
        calls=[0];target={'address':1,'name':'蜈蚣','dead':False}
        def spell(*args,**kwargs):
            calls[0]+=1
            if calls[0]==2:return {'status':'no_verified_target','f1_sent':False}
            return {'f1_sent':True,'target':target,'target_vitals_after':{'0x11a':230,'0x112':0}}
        r=self.run_case(spell,monsters=[target],max_casts=2)
        self.assertEqual(calls[0],3);self.assertEqual(r['casts_sent'],2)
        self.assertEqual(r['observed_deaths'],0)


    def test_large_position_change_between_actions_stops(self):
        reads=[0]
        def player():
            reads[0]+=1
            return (20,20) if reads[0]<=4 else (100,100)
        r=self.run_case(lambda *a,**k:{'f1_sent':True,'target':{'address':1,'name':'蜈蚣'}},
            monsters=[{'address':1,'name':'蜈蚣','dead':False}],max_casts=3,player=player)
        self.assertEqual(r['status'],'external_position_change')
        self.assertEqual(r['casts_sent'],1)


    def test_continuous_mode_does_not_stop_at_60_casts(self):
        calls=[0];target={'address':1,'name':'蜈蚣','dead':False}
        def spell(*args,**kwargs):
            calls[0]+=1
            if calls[0]==62:raise RuntimeError('test cancellation')
            return {'f1_sent':True,'target':target}
        with self.assertRaisesRegex(RuntimeError,'test cancellation'):
            self.run_case(spell,monsters=[target],continuous=True)
        self.assertEqual(calls[0],62)


    def test_continuous_unconfirmed_target_is_deferred_then_route_resumes(self):
        calls=[0];target={'address':1,'name':'蜈蚣','dead':False}
        def spell(*args,**kwargs):
            calls[0]+=1
            if calls[0]<=2:return {'status':'hover_target_unconfirmed','f1_sent':False,'target':target}
            if calls[0]==3:
                self.assertIn(1,kwargs['excluded'])
                return {'status':'no_verified_target','f1_sent':False}
            raise RuntimeError('test cancellation')
        with patch('mage_dungeon.approach_once',return_value={'movement':False}):
            with self.assertRaisesRegex(RuntimeError,'test cancellation'):
                self.run_case(spell,continuous=True)
        self.assertEqual(calls[0],4)


class ActorIdentityTests(unittest.TestCase):
    def test_animation_fields_can_change_but_identity_cannot(self):
        from mage_dungeon import same_actor
        before=bytearray(0x184);after=bytearray(before)
        after[4:12]=b'animate!'
        after[0x68:0x70]=struct.pack('<2i',20,21)
        self.assertTrue(same_actor(before,after))
        for offset in (0,0xc,0x40):
            changed=bytearray(after);changed[offset]=1
            self.assertFalse(same_actor(before,changed))
        self.assertFalse(same_actor(before,None))


class HuntStateWriteTests(unittest.TestCase):
    def test_temporary_windows_reader_lock_retries_and_preserves_json(self):
        import tempfile,json
        from pathlib import Path
        from mage_dungeon import write_hunt_state
        original=Path.replace;calls=[]
        def replace(source,target):
            calls.append(source)
            if len(calls)<3:raise PermissionError('busy reader')
            return original(source,target)
        with tempfile.TemporaryDirectory() as folder,patch.object(Path,'replace',autospec=True,side_effect=replace),patch('time.sleep'):
            path=Path(folder)/'state.json';write_hunt_state(path,{'phase':'running'})
            self.assertEqual(json.loads(path.read_text()),{'phase':'running'});self.assertEqual(len(calls),3)

    def test_persistent_state_write_failure_is_bounded(self):
        import tempfile
        from pathlib import Path
        from mage_dungeon import write_hunt_state
        with tempfile.TemporaryDirectory() as folder,patch.object(Path,'replace',side_effect=PermissionError('permanent')) as replace,patch('time.sleep'):
            with self.assertRaisesRegex(PermissionError,'permanent'):write_hunt_state(Path(folder)/'state.json',{})
            self.assertEqual(replace.call_count,50)
