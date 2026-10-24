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
    def run_case(self,spell,monsters=None,drops=None,pickup=None,max_casts=1):
        import tempfile
        from pathlib import Path
        from contextlib import ExitStack
        from mage_dungeon import run_bounded
        original=lambda header:'original'
        s=SimpleNamespace(navigation_map=original,player=lambda:(20,20),pause=lambda n:None,
            nearby_monsters=lambda **k:{'read_errors':0,'monsters':monsters or []},clear_background_mouse=Mock())
        with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
            stack.enter_context(patch('mage_dungeon.guard'))
            stack.enter_context(patch('mage_dungeon.probe_once',side_effect=spell))
            stack.enter_context(patch('warrior_combat.patrol_plan',return_value=(object(),{'waypoints':[(20,20),(30,30)]})))
            stack.enter_context(patch('inventory_flow.ensure_loot_capacity'))
            stack.enter_context(patch('ground_item_probe.ground_snapshot',return_value={'ground_maps':[{'items':drops or []}]}))
            stack.enter_context(patch('island_pickup_policy.filter_drops',side_effect=lambda rows:(rows,[])))
            stack.enter_context(patch('ground_item_probe.pickup_current_test',return_value=pickup))
            stack.enter_context(patch('instance_context.runtime_root',return_value=Path(folder)))
            result=run_bounded(s,max_casts=max_casts)
        self.assertIs(s.navigation_map,original);s.clear_background_mouse.assert_called_once()
        return result

    def test_cast_limit_is_finite_and_not_a_kill_claim(self):
        r=self.run_case(lambda *a,**k:{'f1_sent':True,'target':{'address':1,'name':'蜈蚣'}})
        self.assertEqual(r['casts_sent'],1);self.assertEqual(r['observed_deaths'],0)
        self.assertFalse(r['unattended_acceptance'])

    def test_disappearing_target_is_not_counted_as_dead(self):
        r=self.run_case(lambda *a,**k:{'f1_sent':True,'target':{'address':1,'name':'蜈蚣'}},max_casts=2)
        self.assertEqual(r['status'],'target_disappeared_unverified');self.assertEqual(r['observed_deaths'],0)

    def test_removed_drop_without_inventory_evidence_stops(self):
        r=self.run_case(lambda *a,**k:(_ for _ in ()).throw(AssertionError('must not cast')),
            drops=[{'id':7,'name':'金币','x':20,'y':20}],pickup={'status':'removed_at_target','verified':False})
        self.assertEqual(r['status'],'pickup_unverified');self.assertEqual(r['verified_pickups'],0)


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
