import unittest
from unittest.mock import Mock,patch
from PIL import Image
import test_current_map_hunt as fixtures
import current_map_hunt as hunt

class InformationPauseTests(unittest.TestCase):
    def test_exact_guild_notice_pauses_until_closed_without_input(self):
        p,s,state=fixtures.ManualBagPauseTests().setup_case();state.update(bag=False,message=True)
        p.informational_message=Mock(return_value=True)
        with patch.object(hunt,'header',return_value=hunt.STONE_HEADER),patch.object(hunt,'read_experience',return_value={'character':'厚礼蟹','main':{'actor':65536}}):
            self.assertTrue(p.wait_for_panels(s))
            with self.assertRaises(hunt.PanelOpen):p.guard(s)
            state['message']=False
            self.assertFalse(p.wait_for_panels(s));p.guard(s)
        s.click.assert_not_called();s.background_mouse.assert_not_called()
    def test_notice_never_masks_dead_or_login(self):
        for kind in ('dead','login'):
            p,s,state=fixtures.ManualBagPauseTests().setup_case();state.update(bag=False,message=True);state[kind]=True
            p.informational_message=Mock(return_value=True)
            with patch.object(hunt,'header',return_value=hunt.STONE_HEADER),patch.object(hunt,'read_experience',return_value={'character':'厚礼蟹','main':{'actor':65536}}):
                with self.assertRaises(RuntimeError):p.wait_for_panels(s)
    def test_unknown_message_still_stops(self):
        p,s,state=fixtures.ManualBagPauseTests().setup_case();state.update(bag=False,message=True)
        p.informational_message=Mock(return_value=False)
        with patch.object(hunt,'header',return_value=hunt.STONE_HEADER),patch.object(hunt,'read_experience',return_value={'character':'厚礼蟹','main':{'actor':65536}}):
            with self.assertRaises(RuntimeError):p.wait_for_panels(s)
    def test_only_exact_high_confidence_local_ocr_is_accepted(self):
        p,s,state=fixtures.ManualBagPauseTests().setup_case()
        s.control_info=lambda *a:{'visible':True,'bounds':(200,200,452,179)}
        s.capture_client=lambda:Image.new('RGB',(1280,800));s.client_size=lambda:(1280,800)
        for text,score,accepted in [('您还没有加入行会！',.99,True),('是否加入行会？',.99,False),('您还没有加入行会！',.9,False)]:
            with patch('stone_hunt_cycle.recognize',return_value=[{'text':text,'score':score}]):
                self.assertEqual(p.informational_message(s),accepted)

if __name__=='__main__':unittest.main()
