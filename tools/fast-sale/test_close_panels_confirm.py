import unittest
from unittest.mock import Mock
from background_sale import BackgroundSession

class ClosePanelsConfirmTests(unittest.TestCase):
    def session(self,close_after):
        s=object.__new__(BackgroundSession);state={'bag':True,'clicks':0}
        s.held_item=lambda:'';s.sale_item=lambda:'';s.inflight_item=lambda:''
        s.visible=lambda key:state.get(key,False)
        s.control_info=lambda offset,name:{'visible':False,'bounds':(0,0,16,16)}
        s.bounds=lambda key:(0,0,300,300);s.pause=Mock()
        def click(point):
            state['clicks']+=1
            if state['clicks']>=close_after:state['bag']=False
        s.click=Mock(side_effect=click)
        return s,state
    def test_one_unaccepted_close_gets_one_verified_retry(self):
        s,state=self.session(2);s.close_panels();self.assertFalse(state['bag']);self.assertEqual(s.click.call_count,2)
    def test_persistent_open_window_stops_instead_of_moving(self):
        s,_=self.session(3)
        with self.assertRaisesRegex(RuntimeError,'仍未确认'):s.close_panels()
        self.assertEqual(s.click.call_count,2)
    def test_inflight_item_never_closes_any_window(self):
        s,_=self.session(1);s.inflight_item=lambda:'物品'
        with self.assertRaises(RuntimeError):s.close_panels()
        s.click.assert_not_called()

if __name__=='__main__':unittest.main()
