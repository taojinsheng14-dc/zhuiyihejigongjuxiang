import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from pickup_strategy import choose,lead_hero


def drop(uid,x,y):return {'id':uid,'name':'红包','x':x,'y':y,'key_matches':True}


class PriorityTests(unittest.TestCase):
    def test_clear_drop_precedes_hero_blocked_drop_even_without_monsters(self):
        blocked=drop(1,10,10);clear=drop(2,13,10)
        self.assertEqual(choose([blocked,clear],[],(10,10),(9,10)),('pickup',clear))

    def test_accessible_drop_precedes_combat(self):
        blocked=drop(1,10,10);clear=drop(2,13,10)
        monsters=[{'position':(10,10),'dead':False}]
        self.assertEqual(choose([blocked,clear],monsters,None,(9,10)),('pickup',clear))

    def test_only_monster_occupied_drop_requires_combat_then_pickup(self):
        target=drop(1,10,10)
        self.assertEqual(choose([target],[{'position':(10,10)}],None,(9,10))[0],'combat')
        self.assertEqual(choose([target],[],None,(9,10)),('pickup',target))

    def test_hero_occupied_drop_with_monsters_does_not_lead_hero(self):
        target=drop(1,10,10)
        self.assertEqual(choose([target],[{'position':(15,15)}],(10,10),(9,10))[0],'combat')
        self.assertEqual(choose([target],[],(10,10),(9,10)),('lead_hero',target))

    def test_sticky_target_does_not_preempt_new_accessible_drop(self):
        blocked=drop(1,10,10);clear=drop(2,13,10)
        self.assertEqual(choose([blocked,clear],[],(10,10),(9,10),preferred=1),('pickup',clear))

    def test_leading_never_moves_while_monsters_exist(self):
        s=SimpleNamespace(background_mouse=Mock())
        r=lead_hero(s,drop(1,10,10),{'monsters':[{'position':(15,15)}]})
        self.assertEqual(r['status'],'combat_required');s.background_mouse.assert_not_called()

    def test_empty_scene_is_clear(self):self.assertEqual(choose([],[],None,(9,10)),('clear',None))
