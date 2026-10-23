import unittest
from unittest.mock import Mock
from test_background_sale import Fake
from sale_state import item_identity,require_identity,validate_sale_removal
from fast_sale import button_center,grid_center

class IdentityFake(Fake):
    def __init__(self):
        super().__init__();self.reader=object();self.base=0;self.bad_held=False;self.bad_sale=False;self.changed_other=False
        self.sale_handler_layout=lambda:{'verified':True}
    def row(self,name,uid='0100000002000000'):
        return {'name':name,'uid':uid if name else ''}
    def sale_bag_identities(self):
        rows=[self.row(name) for name in self.items]
        if self.changed_other:rows[1]=self.row('木剑','0300000004000000')
        return rows
    def sale_item_identity(self,location,index=None):
        name=self.held if location=='held' else self.pending
        return self.row(name,'0300000004000000' if (self.bad_held if location=='held' else self.bad_sale) else '0100000002000000')

class SaleStateTests(unittest.TestCase):
    def test_record_uid_is_two_dwords_not_name(self):
        raw=bytearray(156);name='木剑'.encode('gb18030');raw[0]=len(name);raw[1:1+len(name)]=name;raw[144:152]=bytes.fromhex('0100000002000000')
        self.assertEqual(item_identity(raw),{'name':'木剑','uid':'0100000002000000'})
        raw[144:152]=bytes(8)
        with self.assertRaisesRegex(RuntimeError,'标识为空'):item_identity(raw)

    def test_same_name_wrong_held_uid_stops_before_placing(self):
        s=IdentityFake();s.bad_held=True
        with self.assertRaisesRegex(RuntimeError,'唯一标识变化'):s.submit_one('木剑')
        self.assertEqual(len(s.events),1)

    def test_same_name_wrong_sale_uid_stops_before_confirming(self):
        s=IdentityFake();s.bad_sale=True
        with self.assertRaisesRegex(RuntimeError,'唯一标识变化'):s.submit_one('木剑')
        self.assertEqual(len(s.events),2)

    def test_verified_uid_sale_settles_once(self):
        s=IdentityFake();result=s.submit_one('木剑')
        self.assertTrue(result['settled']);self.assertEqual(len(s.events),3)

    def test_different_client_code_blocks_before_any_item_click(self):
        s=IdentityFake();s.sale_handler_layout=lambda:{'verified':False}
        with self.assertRaisesRegex(RuntimeError,'版本不符'):s.submit_one('木剑')
        self.assertEqual(s.events,[])

    def test_existing_inflight_blocks_before_pickup(self):
        s=Fake();s.inflight_item=lambda:'木剑'
        with self.assertRaisesRegex(RuntimeError,'传输中'):s.submit_one('木剑')
        self.assertEqual(s.events,[])

    def test_empty_sale_slot_with_pending_is_not_success_and_never_resubmits(self):
        s=Fake();s.inflight_item=lambda:'木剑' if len(s.events)==3 else ''
        s.refresh_pending_sale=Mock(side_effect=RuntimeError('传输未确认'))
        with self.assertRaisesRegex(RuntimeError,'传输未确认'):s.submit_one('木剑')
        self.assertEqual(len(s.events),3);s.refresh_pending_sale.assert_called_once()

    def test_returned_item_is_not_counted_as_completed(self):
        s=Fake();expected=s.items.copy();expected[9]='';s.items[9]=''
        s.wait=lambda *args,**kwargs:(_ for _ in ()).throw(RuntimeError('timeout'))
        s.inflight_item=lambda:''
        s.refresh_pending_sale=lambda item:s.items.__setitem__(9,item)
        with self.assertRaisesRegex(RuntimeError,'已退回'):s.wait_sale_settled('木剑',expected)
        self.assertEqual(s.events,[])

    def test_remaining_same_name_item_uid_cannot_change(self):
        before=[{'name':'','uid':''} for _ in range(40)];before[0]={'name':'木剑','uid':'01'};before[1]={'name':'木剑','uid':'02'}
        after=before.copy();after[0]={'name':'','uid':''};after[1]={'name':'木剑','uid':'03'}
        with self.assertRaisesRegex(RuntimeError,'标识未按预期'):validate_sale_removal(before,after,0)

if __name__=='__main__':unittest.main()
