from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch

from random_hunt import RandomSettings,RandomPolicy,target_monsters,save_settings,load_settings,recent_attempts


class RandomHuntTests(unittest.TestCase):
    def sample(self,second,monsters=0,players=1):
        return {'ok':True,'sampler':'helper_thread','observed_epoch':1000+second,
                'target_count':monsters,'player_count':players}

    def observe(self,policy,settings,second,**values):
        return policy.observe(self.sample(second,**values),settings,True,'room',now=second,wall=1000+second)

    def test_default_is_disabled_and_round_trip_preserves_settings(self):
        self.assertFalse(RandomSettings().enabled)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'settings.json'
            self.assertEqual(load_settings(path),RandomSettings())
            settings=replace(RandomSettings(),enabled=True,radius=20)
            save_settings(settings,path);self.assertEqual(load_settings(path),settings)

    def test_contested_empty_requires_continuous_duration(self):
        policy=RandomPolicy();settings=replace(RandomSettings(),enabled=True)
        for second in range(20):self.assertFalse(self.observe(policy,settings,second)['ready'])
        self.assertTrue(self.observe(policy,settings,20)['ready'])

    def test_players_with_monsters_and_empty_without_players_do_not_trigger(self):
        for monsters,players in ((1,1),(0,0)):
            policy=RandomPolicy();settings=replace(RandomSettings(),enabled=True)
            for second in range(100):
                self.assertFalse(self.observe(policy,settings,second,monsters=monsters,players=players)['ready'])

    def test_new_monster_or_player_departure_resets_timer(self):
        for values in ({'monsters':1},{'players':0}):
            policy=RandomPolicy();settings=replace(RandomSettings(),enabled=True,empty_seconds=5)
            for second in range(5):self.observe(policy,settings,second)
            self.assertFalse(self.observe(policy,settings,5,**values)['ready'])
            for second in range(6,11):self.assertFalse(self.observe(policy,settings,second)['ready'])
            self.assertTrue(self.observe(policy,settings,11)['ready'])

    def test_explicit_players_mode_can_trigger_even_with_monsters(self):
        policy=RandomPolicy();settings=replace(RandomSettings(),enabled=True,trigger_mode='players',empty_seconds=5)
        for second in range(5):self.assertFalse(self.observe(policy,settings,second,monsters=5)['ready'])
        self.assertTrue(self.observe(policy,settings,5,monsters=5)['ready'])

    def test_cooldown_and_hourly_budget_survive_reservation(self):
        policy=RandomPolicy();settings=replace(RandomSettings(),enabled=True,empty_seconds=5,max_per_hour=1)
        for second in range(6):decision=self.observe(policy,settings,second)
        self.assertTrue(decision['ready']);policy.reserve(wall=1005)
        for second in range(6,100):self.assertFalse(self.observe(policy,settings,second)['ready'])
        self.assertIn('次数上限',self.observe(policy,settings,100)['reason'])

    def test_stale_error_unknown_and_non_hunt_states_never_trigger(self):
        settings=replace(RandomSettings(),enabled=True);policy=RandomPolicy()
        for sample in (None,{'ok':False},dict(self.sample(0),target_count=None),dict(self.sample(0),player_count=None),dict(self.sample(0),read_errors=1)):
            self.assertFalse(policy.observe(sample,settings,True,'room',now=99,wall=1099)['ready'])
        self.assertFalse(policy.observe(self.sample(1),settings,False,'town',now=1,wall=1001)['ready'])

    def test_sampling_gap_and_room_change_reset_empty_duration(self):
        policy=RandomPolicy();settings=replace(RandomSettings(),enabled=True,empty_seconds=5)
        for second in range(5):self.observe(policy,settings,second)
        self.assertFalse(self.observe(policy,settings,8)['ready'])
        self.assertFalse(policy.observe(self.sample(9),settings,True,'other_room',now=9,wall=1009)['ready'])

    def test_known_owned_summons_and_guards_excluded_unknowns_retained(self):
        rows=[{'name':name,'class':kind,'distance':distance,'dead':dead} for name,kind,distance,dead in
              [('神兽(玩家)','TActor',1,False),('白野猪','TActor',2,False),
               ('未知怪物(名称)','TActor',3,False),('弓箭护卫','TArcherMon',2,False),
               ('尸王','TActor',2,True),('远处怪','TActor',20,False)]]
        self.assertEqual([r['name'] for r in target_monsters(rows,12)],['白野猪','未知怪物(名称)'])

    def test_attempt_history_retains_only_current_hour(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'events.jsonl'
            path.write_text('\n'.join(json.dumps({'event':'random_attempt','observed_epoch':at}) for at in (1000,5000)),encoding='utf8')
            self.assertEqual(recent_attempts(path,now=5100),[5000])

    def test_invalid_settings_are_rejected(self):
        for values in ({'radius':100},{'player_radius':0},{'empty_seconds':float('nan')},
                       {'max_per_hour':0},{'cost_per_use':-1},{'trigger_mode':'unknown'}):
            with self.assertRaises(ValueError):replace(RandomSettings(),**values).validate()

    def test_disabled_and_town_context_never_send_a_hotkey(self):
        from background_sale import BackgroundSession
        s=object.__new__(BackgroundSession);s.press_named_hotkey=Mock()
        with patch('random_hunt.load_settings',return_value=RandomSettings()):
            self.assertFalse(s.maybe_random_hunt())
        s._random_policy=RandomPolicy();s.reader=SimpleNamespace(pid=1)
        s._live_sampler=SimpleNamespace(latest=None)
        with patch('random_hunt.load_settings',return_value=replace(RandomSettings(),enabled=True)):
            self.assertFalse(s.maybe_random_hunt())
        s.press_named_hotkey.assert_not_called()

    def test_unconfirmed_random_is_not_retried_on_next_iteration(self):
        from background_sale import BackgroundSession
        import time
        s=object.__new__(BackgroundSession);s._hunting_header=b'room'
        s.reader=SimpleNamespace(pid=1);s.u=SimpleNamespace(IsIconic=lambda hwnd:False);s.hwnd=1;s.base=0
        s.login_stage=lambda:'playing';s.uint=lambda address:0;s.read=lambda address,size:b'room'
        s.visible=lambda key:False;s.held_item=lambda:'';s.sale_item=lambda:'';s.inflight_item=lambda:''
        s.player=lambda:(10,10);s.check=lambda:None;s.write_stats=Mock();s.press_named_hotkey=Mock()
        s.wait=Mock(side_effect=RuntimeError('not confirmed'))
        s._live_sampler=SimpleNamespace(latest={'game_pid':1,'radius':12,'player_radius':8})
        policy=Mock();policy.attempts=[]
        policy.observe.side_effect=lambda *args,**kwargs:{'ready':True,'reason':'test','used_hour':len(policy.attempts)}
        policy.reserve.side_effect=lambda:policy.attempts.append(time.time())
        s._random_policy=policy;s.shortcut_inventory=lambda:[{'name':'随机传送石','key':1,'raw_98':1}]
        with patch('random_hunt.load_settings',return_value=replace(RandomSettings(),enabled=True)):
            self.assertFalse(s.maybe_random_hunt());self.assertFalse(s.maybe_random_hunt())
        s.press_named_hotkey.assert_called_once_with(('随机传送石',),'random')
        self.assertEqual(policy.reserve.call_count,1)


if __name__=='__main__':unittest.main()
