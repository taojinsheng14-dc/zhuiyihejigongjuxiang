import struct
import unittest
from unittest.mock import patch
from background_sale import BackgroundSession
from test_background_sale import Fake

class CommandSafetyTests(unittest.TestCase):
    def test_loading_npc_retries_reads_without_clicking(self):
        session=Fake();npc={'name':'盟重老兵','map':(320,320),'address':1,'draw':(360,145)}
        snapshots=iter([[],[],[npc]])
        session.npcs=lambda:next(snapshots)
        self.assertEqual(session.unique_npc('盟重老兵',(320,320)),npc)
        self.assertEqual(session.events,[])

    def test_stale_npc_position_is_not_selected_after_transition(self):
        session=Fake();session.base=0
        session.player=lambda:(330,327);session.uint=lambda address:1
        session.read=lambda address,count:struct.pack('<2i',840,369)
        session.npcs=lambda:[{'name':'盟重老兵','map':(320,320),'address':1,'draw':(360,145)},
                              {'name':'盟重老兵','map':(320,320),'address':2,'draw':(80,49)}]
        self.assertEqual(session.unique_npc('盟重老兵',(320,320))['address'],1)
        self.assertEqual(session.events,[])

    def test_stop_request_prevents_input_before_windows_calls(self):
        session=BackgroundSession.__new__(BackgroundSession)
        session.events=[]
        with patch('background_sale.Path.read_text',side_effect=['{"step":19}','{"step":19}']):
            with self.assertRaisesRegex(RuntimeError,'已停止'):
                session.check()

    def test_manual_recording_prevents_automatic_input(self):
        session=BackgroundSession.__new__(BackgroundSession);session._route_recording=True
        with self.assertRaisesRegex(RuntimeError,'禁用自动输入'):session.check()

    def test_edge_npc_requires_better_standing_position(self):
        session=Fake()
        self.assertIsNone(session.npc_click_point((216,-47)))
        self.assertIsNone(session.npc_click_point((216,-90)))
        self.assertIsNone(session.npc_click_point((24,100)))
        self.assertEqual(session.npc_click_point((216,49)),(216,73))

    def test_npc_hidden_by_hero_panel_has_no_click_target(self):
        session=Fake();session.hero_covers=lambda box:True
        self.assertIsNone(session.npc_click_point((216,145)))

if __name__=='__main__':unittest.main()
