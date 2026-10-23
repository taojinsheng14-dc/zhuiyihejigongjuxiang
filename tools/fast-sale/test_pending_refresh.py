import unittest
from unittest.mock import Mock,patch
from background_sale import BackgroundSession


class PendingRefreshTests(unittest.TestCase):
    def record_session(self):
        s=object.__new__(BackgroundSession);s.base=0
        name='珊瑚戒指'.encode('gb18030');record=bytearray(156)
        record[0]=len(name);record[1:1+len(name)]=name;record[0x90:0x98]=b'12345678'
        s.record=bytes(record);s.main=s.record+bytes(39*156)
        s.uint=lambda address:1000 if address==0x2ba2b0 else 2000
        s.read=lambda address,size:s.record if address==1004 else s.main if address==0x2e1674 else bytes(40*156)
        s.held_item=lambda:'';s.sale_item=lambda:'';s.login_stage=lambda:'playing'
        s.pause=lambda seconds:None;s.log_sale_probe=Mock()
        return s

    def test_exact_returned_record_resolves_cache_without_memory_write(self):
        s=self.record_session();self.assertEqual(s.inflight_item(),'珊瑚戒指')
        self.assertTrue(s.accept_returned_pending('珊瑚戒指'))
        self.assertEqual(s.inflight_item(),'')
        s.main=bytes(40*156)
        self.assertEqual(s.inflight_item(),'珊瑚戒指')

    def test_same_name_different_identity_or_duplicate_record_stays_pending(self):
        s=self.record_session();other=bytearray(s.record);other[0x90]=99
        s.main=bytes(other)+bytes(39*156)
        self.assertFalse(s.accept_returned_pending('珊瑚戒指'))
        s.main=s.record*2+bytes(38*156)
        self.assertFalse(s.accept_returned_pending('珊瑚戒指'))

    def session(self):
        s=object.__new__(BackgroundSession);s.pending='珊瑚戒指'
        s.inflight_item=lambda:s.pending;s.held_item=lambda:'';s.sale_item=lambda:''
        s.accept_returned_pending=lambda item:False;s.check=lambda:None
        s.control_info=lambda offset,name:{'visible':True,'bounds':(416,0,352,295) if offset==0x488 else (228,253,72,23)}
        s.log_sale_probe=Mock()
        def wait(condition,timeout):
            if not condition():raise RuntimeError('timeout')
        s.wait=wait
        return s

    def test_refresh_once_and_never_resubmits_sale(self):
        s=self.session()
        with patch.object(BackgroundSession,'background_mouse',side_effect=lambda *args,**kwargs:setattr(s,'pending','')) as click:
            result=s.refresh_pending_sale('珊瑚戒指')
        self.assertTrue(result['refreshed']);self.assertFalse(result['resubmitted'])
        click.assert_called_once();self.assertEqual(click.call_args.args[1],(680.0,264.5))

    def test_pending_after_refresh_stops_without_second_click(self):
        s=self.session()
        with patch.object(BackgroundSession,'background_mouse') as click:
            with self.assertRaisesRegex(RuntimeError,'timeout'):s.refresh_pending_sale('珊瑚戒指')
        click.assert_called_once()

    def test_held_item_blocks_refresh(self):
        s=self.session();s.held_item=lambda:'凝霜'
        with patch.object(BackgroundSession,'background_mouse') as click:
            with self.assertRaisesRegex(RuntimeError,'手持'):s.refresh_pending_sale('珊瑚戒指')
        click.assert_not_called()


if __name__=='__main__':unittest.main()
