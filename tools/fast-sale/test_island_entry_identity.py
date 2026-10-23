import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from island_challenge import confirm_entry_npc
from island_automation import confirmed_corner_npcs,ISLAND_HEADER


class EntryIdentityTests(unittest.TestCase):
    def test_opened_corner_missing_from_scene_requires_exact_actor_proof(self):
        opened={'name':'孤岛挑战','map':(19,11),'address':123}
        others=[{'name':'孤岛挑战','map':p,'address':i} for i,p in enumerate(((13,18),(26,18)),200)]
        s=SimpleNamespace(_island_open_corner={'npc':opened,'position':(19,13)},
            visible=lambda key:True,active_merchant='孤岛挑战',player=lambda:(19,13),verified_npc_draw=Mock())
        with patch('island_automation.header',return_value=ISLAND_HEADER):
            self.assertEqual(len(confirmed_corner_npcs(s,others)),3)
        s.verified_npc_draw.assert_called_once_with(opened)
    def test_moved_player_cannot_reuse_old_corner_dialog_proof(self):
        s=SimpleNamespace(_island_open_corner={'npc':{'address':123},'position':(19,13)},
            visible=lambda key:True,active_merchant='孤岛挑战',player=lambda:(20,13),verified_npc_draw=Mock())
        self.assertEqual(confirmed_corner_npcs(s,[]),[]);s.verified_npc_draw.assert_not_called()
    def session(self):
        return SimpleNamespace(npcs=Mock(return_value=[]),pause=Mock(),active_merchant='孤岛挑战',
            visible=lambda key:True,in_mengzhong_return_area=lambda:True,verified_npc_draw=Mock(return_value=(64,241)))
    def npc(self):return {'name':'孤岛挑战','map':(317,331),'address':123}
    def test_transient_empty_scene_retries_without_any_mouse_input(self):
        s=self.session();s.npcs.side_effect=[[],[self.npc()]]
        self.assertEqual(confirm_entry_npc(s),self.npc());self.assertEqual(s.npcs.call_count,2)
    def test_empty_scene_uses_exact_opened_actor_after_fresh_validation(self):
        s=self.session();self.assertEqual(confirm_entry_npc(s,self.npc()),self.npc())
        s.verified_npc_draw.assert_called_once_with(self.npc())
    def test_unverified_or_wrong_menu_cannot_authorize_entry(self):
        s=self.session();s.active_merchant='盟重老兵'
        with self.assertRaises(RuntimeError):confirm_entry_npc(s,self.npc())
        s.verified_npc_draw.assert_not_called()
    def test_recreated_or_invalid_actor_is_rejected(self):
        s=self.session();s.verified_npc_draw.side_effect=RuntimeError('NPC对象已失效')
        with self.assertRaises(RuntimeError):confirm_entry_npc(s,self.npc())
    def test_duplicate_scene_actors_are_not_bypassed(self):
        s=self.session();s.npcs.return_value=[self.npc(),self.npc()]
        with self.assertRaises(RuntimeError):confirm_entry_npc(s,self.npc())


if __name__=='__main__':unittest.main()
