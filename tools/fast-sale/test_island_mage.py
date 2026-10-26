import unittest
from unittest.mock import patch
import island_mage
import island_automation


class IslandMageTests(unittest.TestCase):
    def fixture(self,hover=True):
        from test_mage_dungeon import MageDungeonTests
        return MageDungeonTests().session(hover)

    def invoke(self,s,mage=None,role='厚礼蟹',header=None,skill='雷电术'):
        mage=mage or island_mage.Mage()
        with patch('island_automation.role_key',return_value=role+'|today'),patch('island_automation.header',return_value=island_automation.ISLAND_HEADER if header is None else header),patch('mage_dungeon.inspect_current',return_value={'f1_skill':{'name':skill}}):
            return mage.step(s,{'monsters':s.nearby_monsters()['monsters']})

    def test_verified_island_target_sends_one_f1_pair_without_mouse_click(self):
        s,m=self.fixture();mage=island_mage.Mage();r=self.invoke(s,mage)
        self.assertTrue(r['f1_sent']);self.assertTrue(r['engaged']);self.assertEqual(mage.casts,1)
        self.assertEqual([(msg,key) for msg,key,lp in m if msg in (0x100,0x101)],[(0x100,0x70),(0x101,0x70)])
        self.assertFalse(any(msg in (0x201,0x204) for msg,key,lp in m))

    def test_unconfirmed_hover_sends_no_key(self):
        s,m=self.fixture(False);r=self.invoke(s)
        self.assertFalse(r['f1_sent']);self.assertFalse(any(msg==0x100 for msg,key,lp in m))

    def test_wrong_role_or_map_stops_before_input(self):
        for kwargs in ({'role':'微笑'},{'header':bytes(52)}):
            s,m=self.fixture()
            with self.assertRaises(RuntimeError):self.invoke(s,**kwargs)
            self.assertEqual(m,[])

    def test_wrong_f1_skill_stops_before_input(self):
        s,m=self.fixture()
        with self.assertRaisesRegex(RuntimeError,'雷电术'):self.invoke(s,skill='火墙')
        self.assertEqual(m,[])

    def test_reset_after_loot_releases_locked_target(self):
        s,m=self.fixture();mage=island_mage.Mage();self.invoke(s,mage)
        self.assertIsNotNone(mage.locked);mage.reset();self.assertIsNone(mage.locked)
        self.assertEqual(mage.casts,1)

    def test_four_unchanged_target_samples_yield_to_approach(self):
        s,m=self.fixture();mage=island_mage.Mage()
        for _ in range(4):r=self.invoke(s,mage)
        self.assertTrue(r['reposition_required']);self.assertFalse(r['engaged'])
        self.assertIsNone(mage.locked)

    def test_distant_zero_vitals_statue_is_approached_without_key(self):
        s,m=self.fixture();target=s.nearby_monsters()['monsters'][0]
        target.update(name='祖玛雕像',**{'class':'TSculptureMon','distance':6})
        s.nearby_monsters=lambda **kwargs:{'read_errors':0,'monsters':[target]}
        r=self.invoke(s)
        self.assertFalse(r['f1_sent']);self.assertFalse(r['engaged'])
        self.assertFalse(any(msg==0x100 for msg,key,lp in m))


class FishMageAuthorizationTests(unittest.TestCase):
    fixture=IslandMageTests.fixture
    invoke=IslandMageTests.invoke
    def test_fish_authorization_uses_fish_skill_identity(self):
        s,m=self.fixture();mage=island_mage.Mage('大鱼')
        with patch('island_automation.role_key',return_value='大鱼|today'),patch('island_automation.header',return_value=island_automation.ISLAND_HEADER),patch('mage_dungeon.inspect_current',return_value={'f1_skill':{'name':'雷电术'}}) as skills:
            result=mage.step(s,{'monsters':s.nearby_monsters()['monsters']})
        self.assertTrue(result['f1_sent']);skills.assert_called_once_with(s,'大鱼')

    def test_fish_config_does_not_authorize_another_bound_role(self):
        s,m=self.fixture()
        with self.assertRaises(RuntimeError):self.invoke(s,island_mage.Mage('大鱼'),role='厚礼蟹')
        self.assertEqual(m,[])
