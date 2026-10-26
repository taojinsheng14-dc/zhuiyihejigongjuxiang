import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
import current_map_hunt as hunt
from warrior_combat import DungeonMap


class CurrentMapTests(unittest.TestCase):
    def session(self):
        return SimpleNamespace(check=Mock(),login_stage=lambda:'playing',held_item=lambda:'',sale_item=lambda:'',
             inflight_item=lambda:'',visible=lambda k:False,u=SimpleNamespace(IsIconic=lambda h:False),hwnd=1)

    def test_changed_map_and_wrong_character_stop_without_input(self):
        for value,role in ((bytes(52),'厚礼蟹'),(hunt.STONE_HEADER,'微笑')):
            with patch.object(hunt,'header',return_value=value),patch.object(hunt,'read_experience',return_value={'character':role}):
                with self.assertRaises(RuntimeError):hunt.StoneTomb().guard(self.session())

    def test_route_is_bounded_to_starting_area(self):
        m=DungeonMap(100,100,[[0]*100 for _ in range(100)],name='d715.map',center=(50,50),radius=32)
        self.assertTrue(m.free((82,50)));self.assertFalse(m.free((83,50)))
        with self.assertRaises(RuntimeError):m.path((50,50),(83,50))

    def test_profile_uses_exact_stone_map_without_local_radius(self):
        with patch('warrior_combat.patrol_plan',return_value=('map','plan')) as plan:
            s=self.session();self.assertEqual(hunt.StoneTomb().plan(s),('map','plan'))
            plan.assert_called_once_with(s,expected_header=hunt.STONE_HEADER,expected_name='d715.map',radius=None)

    def test_pending_item_stops_before_input(self):
        s=self.session();s.held_item=lambda:'装备'
        with patch.object(hunt,'header',return_value=hunt.STONE_HEADER),patch.object(hunt,'read_experience',return_value={'character':'厚礼蟹'}):
            with self.assertRaisesRegex(RuntimeError,'物品'):hunt.StoneTomb().guard(s)

    def test_known_panel_waits_without_input_and_does_not_override_item_checks(self):
        s=self.session();s.visible=lambda key:key=='bag'
        with patch.object(hunt,'header',return_value=hunt.STONE_HEADER),patch.object(hunt,'read_experience',return_value={'character':'厚礼蟹'}):
            self.assertTrue(hunt.StoneTomb().wait_for_panels(s))
            s.visible=lambda key:False
            self.assertFalse(hunt.StoneTomb().wait_for_panels(s))
            s.held_item=lambda:'物品'
            with self.assertRaisesRegex(RuntimeError,'物品'):hunt.StoneTomb().wait_for_panels(s)

    def test_message_popup_is_not_treated_as_normal_panel_wait(self):
        s=self.session();s.login_stage=lambda:'message'
        with patch.object(hunt,'header',return_value=hunt.STONE_HEADER),patch.object(hunt,'read_experience',return_value={'character':'厚礼蟹'}):
            with self.assertRaisesRegex(RuntimeError,'状态变化'):hunt.StoneTomb().wait_for_panels(s)

    def test_system_activity_window_closes_only_through_verified_close_control(self):
        visible=[True];s=self.session();s.visible=lambda key:key=='merchant' and visible[0]
        s.control_info=Mock(return_value={'visible':True,'bounds':(400,0,16,20)})
        s.bounds=lambda key:(10,20,416,176)
        s.click=Mock(side_effect=lambda point:visible.__setitem__(0,False));s.pause=Mock()
        with patch.object(hunt,'header',return_value=hunt.STONE_HEADER),patch.object(hunt,'read_experience',return_value={'character':'厚礼蟹'}):
            self.assertFalse(hunt.StoneTomb().wait_for_panels(s))
        s.control_info.assert_any_call(0x5e4,'Button_MerchantDlgClose')
        self.assertEqual(sum(call.args[0]==0x5e4 for call in s.control_info.call_args_list),1)
        s.click.assert_called_once_with((418,30))

    def test_activity_close_failure_does_not_spam_click_or_terminate_hunt(self):
        s=self.session();s.visible=lambda key:key=='merchant'
        s.control_info=Mock(return_value={'visible':True,'bounds':(400,0,16,20)})
        s.bounds=lambda key:(0,0,416,176);s.click=Mock();s.pause=Mock()
        with patch.object(hunt,'header',return_value=hunt.STONE_HEADER),patch.object(hunt,'read_experience',return_value={'character':'厚礼蟹'}):
            for _ in range(3):self.assertTrue(hunt.StoneTomb().wait_for_panels(s))
        s.click.assert_called_once()

    def test_normal_map_requests_continuous_holding_and_full_coverage_spacing(self):
        profile=hunt.StoneTomb();options=profile.move_options()
        self.assertTrue(options['allow_hold']);self.assertEqual(options['expected_header'],hunt.STONE_HEADER)
        self.assertEqual(profile.route_spacing,24)
        self.assertEqual(options['hold_guard'],profile.guard)

    def test_near_black_maggot_prevents_leaving_for_patrol_if_local_route_blocked(self):
        profile=hunt.StoneTomb();profile.guard=Mock();profile.tilemap=SimpleNamespace(free=lambda xy:xy==(50,50))
        target={'name':'黑色恶蛆','class':'TCatMon','dead':False,'position':(52,50),'distance':2}
        s=SimpleNamespace(nearby_monsters=lambda **k:{'read_errors':0,'monsters':[target]},player=lambda:(50,50),scene_actor_snapshot=lambda:[])
        with patch('warrior_combat.patrol_move') as move:
            result=profile.approach(s,Mock())
        self.assertTrue(result['nearby_combat']);self.assertFalse(result['movement'])
        self.assertEqual(result['target']['name'],'黑色恶蛆');move.assert_not_called()

    def test_nearby_reposition_does_not_bounce_between_equal_distance_tiles(self):
        profile=hunt.StoneTomb();profile.guard=Mock()
        profile.tilemap=SimpleNamespace(free=lambda xy:True)
        state={'position':(321,189)};target={'address':1,'name':'黑野猪','class':'TCatMon','dead':False,'position':(325,190),'distance':4}
        session=SimpleNamespace(player=lambda:state['position'],scene_actor_snapshot=lambda:[],
            nearby_monsters=lambda **k:{'read_errors':0,'monsters':[target]})
        def move(session,tilemap,goal,**kwargs):
            before=state['position'];state['position']=goal;return {'from':before,'to':goal}
        positions=[state['position']]
        with patch('warrior_combat.patrol_move',side_effect=move),patch('time.monotonic',return_value=100):
            for _ in range(5):
                result=profile.approach(session,Mock())
                if result['movement']:positions.append(state['position'])
        self.assertEqual(len(positions),len(set(positions)));self.assertGreater(len(positions),2)

    def test_nearby_reposition_prefers_interior_and_history_expires(self):
        profile=hunt.StoneTomb();profile.guard=Mock()
        profile.tilemap=SimpleNamespace(free=lambda xy:True,clearance={(11,10):4})
        state={'position':(10,10)};target={'address':1,'name':'黑野猪','class':'TCatMon','dead':False,'position':(14,10),'distance':4}
        session=SimpleNamespace(player=lambda:state['position'],scene_actor_snapshot=lambda:[],
            nearby_monsters=lambda **k:{'read_errors':0,'monsters':[target]})
        with patch('warrior_combat.patrol_move',return_value={'from':(10,10),'to':(11,10)}) as move,patch('time.monotonic',return_value=100):
            profile.approach(session,Mock())
            self.assertEqual(move.call_args.args[2],(11,10))
        with patch('warrior_combat.patrol_move',return_value={'from':(10,10),'to':(11,10)}) as move,patch('time.monotonic',return_value=109):
            profile.approach(session,Mock())
            self.assertEqual(move.call_args.args[2],(11,10))

    def test_player_guard_queries_entire_loaded_scene(self):
        s=self.session();s.nearby_players=Mock(return_value=[{'position':[100,100]}])
        with patch.object(hunt,'header',return_value=hunt.STONE_HEADER),patch.object(hunt,'read_experience',return_value={'character':'厚礼蟹'}):
            with self.assertRaises(hunt.PlayersDetected):hunt.StoneTomb(avoid_players=True).guard(s)
        s.nearby_players.assert_called_once_with(None)

    def random_session(self):
        state={'position':(50,50)}
        s=self.session();s.player=lambda:state['position'];s.stable_player=s.player
        s.nearby_players=lambda radius:[{'position':[70,70]}]
        s.currency_snapshot=lambda:{'gold':100,'yuanbao':10}
        s.shortcut_inventory=lambda:[{'name':'随机传送石','key':1,'raw_98':100}]
        s.clear_background_mouse=Mock();s.write_stats=Mock()
        s.press_named_hotkey=Mock(side_effect=lambda *a:state.update(position=(80,80)))
        s.wait=lambda condition,timeout:self.assertTrue(condition())
        p=hunt.StoneTomb(avoid_players=True);p.check_state=Mock();p.tilemap=SimpleNamespace(free=lambda xy:True)
        return p,s

    def test_player_random_uses_one_named_stone_and_confirms_new_position(self):
        p,s=self.random_session();result=p.avoid_players(s,Mock())
        self.assertTrue(result['random_used']);self.assertEqual(result['after'],(80,80))
        s.press_named_hotkey.assert_called_once_with(('随机传送石',),'random')
        s.clear_background_mouse.assert_called_once()

    def test_uncertain_random_does_not_repeat(self):
        p,s=self.random_session();s.wait=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('timeout'))
        with self.assertRaisesRegex(RuntimeError,'不重复按键'):p.avoid_players(s,Mock())
        self.assertEqual(s.press_named_hotkey.call_count,1)

    def test_missing_random_stone_never_uses_other_item(self):
        p,s=self.random_session();s.shortcut_inventory=lambda:[]
        with self.assertRaisesRegex(RuntimeError,'缺少'):p.avoid_players(s,Mock())
        s.press_named_hotkey.assert_not_called()

    def test_occupied_goal_with_local_exit_is_not_dead_end(self):
        import struct
        from warrior_combat import local_exits
        from dungeon_route import CenterPathMap
        raw=bytearray(0x200);struct.pack_into('<2i',raw,0x68,52,50)
        p,s=self.random_session();s.scene_actor_snapshot=lambda:[(1,raw)]
        p.tilemap=SimpleNamespace(free=lambda xy:48<=xy[0]<=54 and 48<=xy[1]<=54)
        with self.assertRaisesRegex(RuntimeError,'没有可走路径'):
            CenterPathMap(p.tilemap,{}).path((50,50),(52,50),{(52,50)})
        self.assertTrue(local_exits(s,p.tilemap)['exits'])
        p.guard=Mock();self.assertFalse(p.confirm_dead_end(s));s.press_named_hotkey.assert_not_called()

    def test_hero_blocks_only_corridor_exit_and_diagonal_cannot_cut_corner(self):
        import struct
        from warrior_combat import local_exits
        raw=bytearray(0x200);struct.pack_into('<2i',raw,0x68,51,50)
        p,s=self.random_session();s.scene_actor_snapshot=lambda:[(1,raw)]
        p.tilemap=SimpleNamespace(free=lambda xy:xy in {(50,50),(51,50),(51,51)})
        self.assertEqual(local_exits(s,p.tilemap)['exits'],[])

    def test_confirmed_dead_end_random_once_and_reopened_exit_never_random(self):
        p,s=self.random_session();p.guard=Mock();s.pause=Mock()
        empty={'position':(50,50),'exits':[]};opened={'position':(50,50),'exits':[(51,50)]}
        with patch('warrior_combat.local_exits',side_effect=[empty,opened]):
            self.assertFalse(p.escape_dead_end(s,Mock())['random_used'])
        s.press_named_hotkey.assert_not_called()
        with patch('warrior_combat.local_exits',return_value=empty):
            result=p.escape_dead_end(s,Mock())
        self.assertTrue(result['random_used']);self.assertEqual(result['reason'],'dead_end')
        s.press_named_hotkey.assert_called_once()

    def test_dead_end_unknown_state_and_missing_stone_never_input(self):
        p,s=self.random_session();p.guard=Mock(side_effect=RuntimeError('map changed'))
        with self.assertRaisesRegex(RuntimeError,'map changed'):p.escape_dead_end(s,Mock())
        s.press_named_hotkey.assert_not_called()
        p.guard=Mock();s.pause=Mock();s.shortcut_inventory=lambda:[]
        with patch('warrior_combat.local_exits',return_value={'position':(50,50),'exits':[]}):
            with self.assertRaisesRegex(RuntimeError,'缺少'):p.escape_dead_end(s,Mock())
        s.press_named_hotkey.assert_not_called()



class GenericProfileTests(unittest.TestCase):
    def test_supported_formats_resolve_same_shared_profile(self):
        import struct,tempfile
        from pathlib import Path
        for stride in (12,14):
            with self.subTest(stride=stride),tempfile.TemporaryDirectory() as folder:
                file=Path(folder)/'new-normal.map';file.write_bytes(bytes(52+4*4*stride))
                head=struct.pack('<HH',4,4)+bytes(48)
                with patch.object(hunt,'header',return_value=head),patch('map_navigation.matching_map_file',return_value=file):
                    profile=hunt.profile_for(SimpleNamespace())
                self.assertEqual(profile.map_stride,stride);self.assertEqual(profile.header,head)
                self.assertTrue(profile.center_route);self.assertEqual(profile.post_cast_wait,.05)

    def test_unknown_format_and_town_are_rejected_before_input(self):
        import struct,tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            for name,stride in (('unknown.map',13),('3.map',14)):
                file=Path(folder)/name;file.write_bytes(bytes(52+4*4*stride))
                with patch.object(hunt,'header',return_value=struct.pack('<HH',4,4)+bytes(48)),patch('map_navigation.matching_map_file',return_value=file):
                    with self.assertRaises(RuntimeError):hunt.profile_for(SimpleNamespace())

    def test_new_map_monster_name_supported_but_owned_pet_and_npc_excluded(self):
        profile=hunt.NormalMap()
        monster={'name':'新地图普通怪','class':'TCatMon','distance':3,'dead':False}
        self.assertTrue(profile.is_target(monster))
        self.assertFalse(profile.is_target(dict(monster,name='神兽(其他玩家)')))
        self.assertFalse(profile.is_target(dict(monster,**{'class':'TMerchant'})))
        self.assertFalse(profile.is_target(dict(monster,dead=True)))


class WarriorProfileTests(unittest.TestCase):
    def test_warrior_run_never_inspects_or_sends_f1(self):
        profile=hunt.WarriorMap(avoid_players=False);profile.check_state=Mock()
        with patch.object(hunt,'read_experience',return_value={'character':'微笑'}),patch.object(hunt,'profile_for',return_value=profile),patch('importlib.reload',side_effect=lambda m:m) as reload,patch('mage_skills.inspect_current') as skills,patch('mage_dungeon.run_bounded',return_value={'status':'test'}) as run:
            self.assertEqual(hunt.run(object())['status'],'test')
        skills.assert_not_called();self.assertIs(run.call_args.kwargs['profile'],profile)
        self.assertIn('island_melee',[call.args[0].__name__ for call in reload.call_args_list])

    def test_warrior_probe_uses_scoped_map_guard_and_preserves_native_wait(self):
        profile=hunt.WarriorMap(avoid_players=False);profile.guard=Mock()
        target={'address':1,'class':'TCatMon','name':'黑野猪','dead':False,'distance':3,'on_screen':True}
        session=SimpleNamespace(nearby_monsters=lambda **k:{'read_errors':0,'monsters':[target]})
        with patch('island_melee.Melee') as melee:
            melee.return_value.step.side_effect=[{'clicked':True,'target':target},{'clicked':False,'engaged':True,'status':'native_attack_wait'}]
            first=profile.probe(session);second=profile.probe(session)
            self.assertTrue(first['attack_sent']);self.assertFalse(first['f1_sent'])
            self.assertEqual(second['status'],'native_attack_wait');self.assertFalse(second['f1_sent'])
            melee.assert_called_once_with(scene_guard=profile.guard,progress_timeout=2,target_classes=profile.melee_classes(),strict_chase=True)

    def test_warrior_guard_rejects_other_role_and_pending_items(self):
        profile=hunt.WarriorMap(avoid_players=False);session=CurrentMapTests().session()
        with patch.object(hunt,'header',return_value=profile.header),patch.object(hunt,'read_experience',return_value={'character':'厚礼蟹'}):
            with self.assertRaisesRegex(RuntimeError,'授权'):profile.guard(session)
        session.held_item=lambda:'装备'
        with patch.object(hunt,'header',return_value=profile.header),patch.object(hunt,'read_experience',return_value={'character':'微笑'}):
            with self.assertRaisesRegex(RuntimeError,'物品'):profile.guard(session)


class ManualBagPauseTests(unittest.TestCase):
    def setup_case(self):
        state={'bag':True,'hero':False,'message':False,'held':'','dead':False,'login':False}
        session=CurrentMapTests().session();session.visible=lambda key:key=='bag' and state['bag']
        session.login_stage=lambda:'message' if state['message'] else 'playing'
        session.held_item=lambda:state['held'];session.read=lambda address,size:b'\1' if state['dead'] else b'\0'
        session.control_info=lambda offset,name:{'object':1,'visible':state['hero'] if name=='Window_HeroItemBag' else state['login'] if name=='Window_Login' else False}
        session.click=Mock();session.background_mouse=Mock()
        return hunt.StoneTomb(avoid_players=False),session,state

    def test_bag_message_held_item_pause_until_all_settled_then_resume_without_click(self):
        profile,session,state=self.setup_case()
        with patch.object(hunt,'header',return_value=hunt.STONE_HEADER),patch.object(hunt,'read_experience',return_value={'character':'厚礼蟹','main':{'actor':0x10000}}):
            self.assertTrue(profile.wait_for_panels(session))
            state.update(message=True,held='装备')
            self.assertTrue(profile.wait_for_panels(session))
            with self.assertRaises(hunt.PanelOpen):profile.guard(session)
            state['bag']=False;self.assertTrue(profile.wait_for_panels(session))
            state['message']=False;self.assertTrue(profile.wait_for_panels(session))
            state['held']='';self.assertFalse(profile.wait_for_panels(session));profile.guard(session)
        session.click.assert_not_called();session.background_mouse.assert_not_called()

    def test_hero_bag_alone_pauses(self):
        profile,session,state=self.setup_case();state.update(bag=False,hero=True)
        with patch.object(hunt,'header',return_value=hunt.STONE_HEADER),patch.object(hunt,'read_experience',return_value={'character':'厚礼蟹'}):
            self.assertTrue(profile.wait_for_panels(session))
            state['hero']=False;self.assertFalse(profile.wait_for_panels(session))

    def test_manual_message_never_masks_death_login_or_map_change(self):
        for kind in ('dead','login','map'):
            profile,session,state=self.setup_case();state.update(message=True)
            if kind!='map':state[kind]=True
            with patch.object(hunt,'header',return_value=bytes(52) if kind=='map' else hunt.STONE_HEADER),patch.object(hunt,'read_experience',return_value={'character':'厚礼蟹','main':{'actor':0x10000}}):
                with self.assertRaisesRegex(RuntimeError,'状态变化'):profile.wait_for_panels(session)
            session.click.assert_not_called()

    def test_pending_item_without_manual_panel_still_stops(self):
        profile,session,state=self.setup_case();state.update(bag=False,held='装备')
        with patch.object(hunt,'header',return_value=hunt.STONE_HEADER),patch.object(hunt,'read_experience',return_value={'character':'厚礼蟹'}):
            with self.assertRaisesRegex(RuntimeError,'物品'):profile.wait_for_panels(session)


class WarriorApproachTests(unittest.TestCase):
    def case(self):
        target={'address':1,'class':'TCatMon','name':'魔龙刀兵','position':(162,137),'distance':5,'dead':False,'on_screen':True}
        profile=hunt.WarriorMap(avoid_players=False);profile.guard=Mock();profile.tilemap=SimpleNamespace(free=lambda p:True)
        session=SimpleNamespace(player=lambda:(167,140),scene_actor_snapshot=lambda:[],nearby_monsters=lambda **k:{'read_errors':0,'monsters':[target]})
        return profile,session,target

    def test_warrior_approaches_adjacent_instead_of_mage_four_tile_ring(self):
        from warrior_combat import melee_approach_path
        profile,session,target=self.case()
        path=melee_approach_path(profile.tilemap,(167,140),target['position'])
        self.assertNotIn(tuple(target['position']),path)
        self.assertLessEqual(max(abs(path[-1][i]-target['position'][i]) for i in (0,1)),1)
        self.assertNotEqual(path[1],(168,140))
        with patch('warrior_combat.patrol_move',return_value={'from':(167,140),'to':path[1],'planned_step':path[1]}) as move:
            result=profile.approach(session,Mock())
        self.assertTrue(result['movement']);self.assertEqual(move.call_args.args[2],path[1])

    def test_failed_approach_first_step_is_avoided_across_retries(self):
        profile,session,target=self.case();steps=[]
        def move(session,tilemap,goal,**options):
            steps.append(goal);return {'from':(167,140),'to':(167,140),'planned_step':goal}
        with patch('warrior_combat.patrol_move',side_effect=move):
            for _ in range(3):profile.approach(session,Mock())
        self.assertEqual(steps[0],steps[1]);self.assertNotEqual(steps[0],steps[2])

    def test_sculpture_is_live_candidate_and_npc_or_dead_is_not(self):
        profile,session,target=self.case()
        self.assertTrue(profile.is_target(dict(target,**{'class':'TSculptureMon'})))
        self.assertFalse(profile.is_target(dict(target,**{'class':'THumActor'})))
        self.assertFalse(profile.is_target(dict(target,dead=True)))

    def test_melee_local_path_does_not_cross_occupied_diagonal_corner(self):
        from warrior_combat import melee_approach_path
        tilemap=SimpleNamespace(free=lambda p:p in {(10,10),(11,10),(10,11),(11,11),(12,11)})
        path=melee_approach_path(tilemap,(10,10),(12,11),{(11,10)})
        self.assertEqual(path[1],(10,11));self.assertNotIn((11,10),path)

    def test_only_exact_dragon_archer_is_allowed_on_dragon_map(self):
        profile,session,target=self.case();profile.map_name='64.map'
        self.assertTrue(profile.is_target(dict(target,name='魔龙射手',**{'class':'TArcherMon'})))
        self.assertFalse(profile.is_target(dict(target,name='弓箭守卫',**{'class':'TArcherMon'})))
        profile.map_name='d2010.map'
        self.assertFalse(profile.is_target(dict(target,name='魔龙射手',**{'class':'TArcherMon'})))


class ZumaMageTargetsTests(unittest.TestCase):
    def test_zuma_monster_classes_are_not_filtered_down_to_bats(self):
        profile=hunt.StoneTomb(map_name='d505.map',avoid_players=False)
        for name,kind in (('祖玛卫士','TSculptureMon'),('祖玛雕像','TSculptureMon'),('祖玛弓箭手','TArcherMon'),('角蝇','TBeeQueen'),('楔蛾','TGasKuDeGi'),('蝙蝠','TCatMon')):
            monster={'name':name,'class':kind,'distance':3,'dead':False}
            self.assertTrue(profile.is_target(monster),(name,kind))
            self.assertFalse(profile.is_target(dict(monster,dead=True)))
        self.assertFalse(profile.is_target({'name':'弓箭守卫','class':'TArcherMon','distance':1,'dead':False}))
        self.assertFalse(profile.is_target({'name':'祖玛雕像','class':'THumActor','distance':1,'dead':False}))

    def test_mage_sculpture_reposition_uses_adjacent_activation_path(self):
        profile=hunt.StoneTomb(map_name='d505.map',avoid_players=False);profile.guard=Mock()
        target={'address':1,'name':'祖玛雕像','class':'TSculptureMon','distance':4,'position':(14,10),'dead':False}
        session=SimpleNamespace(nearby_monsters=lambda **k:{'read_errors':0,'monsters':[target]},scene_actor_snapshot=lambda:[(1,bytes(0x184))])
        profile.sculpture_active=Mock(return_value=False)
        with patch.object(hunt.WarriorMap,'approach',return_value={'nearby_combat':True}) as approach:
            self.assertTrue(profile.approach(session,Mock())['nearby_combat'])
        self.assertIs(approach.call_args.args[0],profile)


class CastSafetyGateTests(unittest.TestCase):
    def test_wall_blocks_line_and_ranged_route_goes_around_opening(self):
        from warrior_combat import clear_terrain_line,melee_approach_path
        tilemap=SimpleNamespace(free=lambda p:0<=p[0]<9 and 0<=p[1]<9 and not(p[0]==4 and p[1]<7))
        self.assertFalse(clear_terrain_line(tilemap,(2,2),(6,2)))
        path=melee_approach_path(tilemap,(2,2),(6,2),reach=8,require_line=True,max_steps=81,max_radius=9)
        self.assertIsNotNone(path);self.assertTrue(clear_terrain_line(tilemap,path[-1],(6,2)))
        self.assertTrue(any(p[1]>=7 for p in path))
        self.assertFalse(clear_terrain_line(SimpleNamespace(free=lambda p:p!=(1,0)),(0,0),(2,2)))

    def test_sculpture_proximity_and_positive_health_alone_do_not_allow_cast(self):
        import struct
        profile=hunt.StoneTomb(avoid_players=False);raw=bytearray(0x184);struct.pack_into('<2i',raw,0x68,10,10)
        monster={'class':'TSculptureMon','address':0x10000}
        session=SimpleNamespace(read=lambda address,size:struct.pack('<H',100 if address==0x10112 else 200))
        with patch('time.monotonic',return_value=100):
            self.assertFalse(profile.sculpture_active(session,monster,raw));self.assertFalse(profile.sculpture_active(session,monster,raw))
        struct.pack_into('<2i',raw,0x68,11,10)
        with patch('time.monotonic',return_value=101):self.assertTrue(profile.sculpture_active(session,monster,raw))
        raw[0]=1
        with patch('time.monotonic',return_value=102):self.assertFalse(profile.sculpture_active(session,monster,raw))


class ApproachFailureScopeTests(unittest.TestCase):
    def test_melee_stall_defers_target_instead_of_stopping_shared_loop(self):
        from dungeon_route import PatrolObstruction
        profile,session,target=WarriorApproachTests().case()
        profile._melee_obstruction=PatrolObstruction();profile._melee_obstruction.failures=11
        result={'from':(167,140),'to':(167,140),'planned_step':(166,140)}
        with patch('warrior_combat.patrol_move',return_value=result):
            move=profile.approach(session,Mock())
        self.assertEqual(move['reason'],'approach_stalled_target_deferred')
        self.assertTrue(move['nearby_combat']);self.assertFalse(move['movement'])
        self.assertIn(target['address'],profile._melee_deferred)

    def test_mage_does_not_keep_approaching_deferred_sculpture(self):
        profile=hunt.StoneTomb(avoid_players=False);profile.guard=Mock();profile._melee_deferred={1:200}
        session=SimpleNamespace(nearby_monsters=lambda **k:{'read_errors':0,'monsters':[{'address':1,'class':'TSculptureMon','name':'祖玛雕像','dead':False,'distance':1}]})
        with patch('time.monotonic',return_value=100):
            result=profile.approach(session,Mock())
        self.assertFalse(result['nearby_combat'])
