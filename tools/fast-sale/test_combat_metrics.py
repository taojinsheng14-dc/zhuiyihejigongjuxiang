import json,tempfile,unittest,struct
from pathlib import Path
from types import SimpleNamespace
from combat_metrics import ExperienceTracker,read_experience
from combat_stats_gui import render_combat

def sample(exp=100,hero=100,pid=10,level=44,character='角色甲'):
    return {'character':character,'game_pid':pid,'main':{'actor':100000,'level':level,'experience':exp,'required':28000000},
            'hero':{'actor':200000,'level':43,'experience':hero,'required':21000000} if hero is not None else None}

class CombatTests(unittest.TestCase):
    def test_main_and_hero_same_growth_count_only_once(self):
        with tempfile.TemporaryDirectory() as folder:
            t=ExperienceTracker(folder);t.update(sample(),100)
            s=t.update(sample(460,460),101)
            self.assertEqual(s['growth_events'],1);self.assertEqual(s['main_exp_gain'],360);self.assertEqual(s['hero_exp_gain'],360)
            self.assertEqual(s['experience_per_hour'],1296000)
    def test_unchanged_samples_do_not_increase_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            t=ExperienceTracker(folder);t.update(sample(),100)
            s=t.update(sample(),101);self.assertEqual(s['growth_events'],0)
    def test_sampling_gap_never_backfills_one_fake_kill(self):
        with tempfile.TemporaryDirectory() as folder:
            t=ExperienceTracker(folder);t.update(sample(),100)
            s=t.update(sample(10000,10000),110)
            self.assertEqual(s['growth_events'],0);self.assertEqual(s['main_exp_gain'],0);self.assertEqual(s['sampling_gaps'],1)
    def test_new_pid_rebaselines_without_counting_old_experience(self):
        with tempfile.TemporaryDirectory() as folder:
            t=ExperienceTracker(folder);t.update(sample(),100);t.update(sample(460,460),101)
            s=t.update(sample(9000,9000,pid=22),102)
            self.assertEqual(s['main_exp_gain'],360);self.assertEqual(s['growth_events'],1)
    def test_upgrade_is_explicitly_unverified_instead_of_inventing_gain(self):
        with tempfile.TemporaryDirectory() as folder:
            t=ExperienceTracker(folder);t.update(sample(27999990),100)
            s=t.update(sample(20,level=45),101)
            self.assertEqual(s['main_exp_gain'],0);self.assertEqual(s['growth_events'],0);self.assertEqual(s['unknown_upgrade_transitions'],1)
    def test_experience_rollback_never_counts_negative_kills(self):
        with tempfile.TemporaryDirectory() as folder:
            t=ExperienceTracker(folder);t.update(sample(1000),100)
            self.assertEqual(t.update(sample(10),101)['growth_events'],0)
    def test_switch_character_has_independent_new_baseline(self):
        with tempfile.TemporaryDirectory() as folder:
            t=ExperienceTracker(folder);t.update(sample(),100);t.update(sample(460),101)
            s=t.update(sample(900,character='角色乙'),102)
            self.assertEqual(s['main_exp_gain'],0);self.assertEqual(s['growth_events'],0)
    def test_restart_preserves_totals_but_does_not_fill_unobserved_interval(self):
        with tempfile.TemporaryDirectory() as folder:
            t=ExperienceTracker(folder);t.update(sample(),100);t.update(sample(460),101);t.save()
            s=ExperienceTracker(folder).update(sample(20000),200)
            self.assertEqual(s['growth_events'],1);self.assertEqual(s['main_exp_gain'],360)
    def test_two_accounts_persist_to_independent_files(self):
        with tempfile.TemporaryDirectory() as folder:
            a=ExperienceTracker(Path(folder)/'a');b=ExperienceTracker(Path(folder)/'b')
            for t in [a,b]:t.update(sample(),100)
            a.update(sample(460),101);a.save();b.save()
            self.assertEqual(json.loads(a.path.read_text(encoding='utf8'))['growth_events'],1)
            self.assertEqual(json.loads(b.path.read_text(encoding='utf8'))['growth_events'],0)
    def test_nearby_presence_is_sampled_time_not_asserted_ownership(self):
        with tempfile.TemporaryDirectory() as folder:
            t=ExperienceTracker(folder);t.update(sample(),100)
            s=t.update(sample(460),101,{'player_count':2})
            self.assertEqual(s['nearby_player_observation_percent'],100)
            row=json.loads((Path(folder)/'经验事件.jsonl').read_text(encoding='utf8'))
            self.assertIsNone(row['exact_kill_count'])
    def test_ui_labels_reference_count_and_rejects_stale_sample(self):
        with tempfile.TemporaryDirectory() as folder:
            t=ExperienceTracker(folder);stats=t.update(sample(),100)
            live={'ok':True,'observed_epoch':100,'game_pid':10,'combat':stats}
            self.assertIn('击杀参考',render_combat(live,100))
            self.assertIn('等待有效',render_combat(live,110))
    def test_actor_fields_validate_before_reading_experience(self):
        s=SimpleNamespace(base=0,reader=SimpleNamespace(pid=10))
        ptrs={0x2bac2c:10,10:100000,100000+0x358:0,100000:0x24991c,100000+0xc:400000,400000-4:4}
        s.uint=lambda address:ptrs[address]
        raw=bytearray(0x42);struct.pack_into('<H',raw,0,44);struct.pack_into('<II',raw,0x3a,100,28000000)
        s.read=lambda address,length:bytes(raw) if address==100000+0xe8 else '角色'.encode('gb18030')
        self.assertEqual(read_experience(s)['main']['experience'],100)
        ptrs[100000]=0
        with self.assertRaisesRegex(RuntimeError,'类型'):read_experience(s)

if __name__=='__main__':unittest.main()
