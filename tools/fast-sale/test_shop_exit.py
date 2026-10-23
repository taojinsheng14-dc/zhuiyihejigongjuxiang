import unittest
import struct
from unittest.mock import Mock

from background_sale import BackgroundSession, GameSessionLost, WeaponShopExitBlocked


class ShopExitTests(unittest.TestCase):
    def test_default_exit_returns_directly_without_door_movement(self):
        session=object.__new__(BackgroundSession);order=[]
        session.close_panels=Mock(side_effect=lambda:order.append('close'))
        session.return_from_blocked_weapon_shop=Mock(side_effect=lambda *args:order.append('return') or {'return_stone_used':True})
        session._leave_weapon_shop_by_door=Mock()
        self.assertTrue(session.leave_weapon_shop()['return_stone_used'])
        self.assertEqual(order,['close','return'])
        session._leave_weapon_shop_by_door.assert_not_called()

    def session(self, outcomes):
        session=object.__new__(BackgroundSession)
        session.check=Mock()
        session.close_panels=Mock()
        session.login_stage=Mock(return_value='playing')
        session.pause=Mock()
        session.unique_npc=Mock()
        session.weapon_exit_players=Mock(return_value=[])
        session._leave_weapon_shop_by_door=Mock(side_effect=outcomes)
        session.return_with_hotkey=Mock(return_value={
            'position':(328,324),'hotkey_sent':True})
        return session

    def test_normal_exit_and_temporary_block_do_not_spend_stone(self):
        result={'return_stone_used':False}
        for outcomes in ([result],[WeaponShopExitBlocked('blocked'),result]):
            with self.subTest(outcomes=outcomes):
                session=self.session(outcomes)
                self.assertEqual(session.leave_weapon_shop_by_door(),result)
                session.return_with_hotkey.assert_not_called()

    def test_closes_sale_panels_before_requiring_rendered_merchant(self):
        session=self.session([{'return_stone_used':False}]);order=[]
        session.close_panels.side_effect=lambda:order.append('close')
        session.unique_npc.side_effect=lambda *args:order.append('npc')
        session.leave_weapon_shop_by_door()
        self.assertEqual(order[:2],['close','npc'])

    def test_persistent_block_uses_one_verified_return(self):
        session=self.session([WeaponShopExitBlocked('blocked')]*2)
        result=session.leave_weapon_shop_by_door()
        self.assertTrue(result['return_stone_used'])
        session.return_with_hotkey.assert_called_once()
        self.assertEqual(session.return_with_hotkey.call_args.kwargs['reason'],
                         'weapon_shop_exit_blocked')
        self.assertTrue(all(call.args==('铁匠铺老板',(5,9)) for call in session.unique_npc.call_args_list))

    def test_death_cancel_and_unsafe_item_failures_never_use_stone(self):
        for error in (GameSessionLost('dead'),RuntimeError('已停止'),
                      RuntimeError('鼠标或出售框仍有物品')):
            with self.subTest(error=error):
                session=self.session([error])
                with self.assertRaises(type(error)):session.leave_weapon_shop_by_door()
                session.return_with_hotkey.assert_not_called()

    def test_death_after_block_and_unknown_location_stop_fallback(self):
        session=self.session([WeaponShopExitBlocked('blocked')]*2)
        session.login_stage.side_effect=['playing','playing','dead']
        with self.assertRaises(GameSessionLost):session.leave_weapon_shop_by_door()
        session.return_with_hotkey.assert_not_called()
        session=self.session([WeaponShopExitBlocked('blocked')]*2)
        session.unique_npc.side_effect=RuntimeError('unknown shop')
        with self.assertRaisesRegex(RuntimeError,'unknown shop'):session.leave_weapon_shop_by_door()
        session.return_with_hotkey.assert_not_called()

    def test_failed_stone_is_not_retried(self):
        session=self.session([WeaponShopExitBlocked('blocked')]*2)
        session.return_with_hotkey.side_effect=RuntimeError('return unconfirmed')
        with self.assertRaisesRegex(RuntimeError,'return unconfirmed'):session.leave_weapon_shop_by_door()
        session.return_with_hotkey.assert_called_once()

    def test_detected_player_skips_walk_and_uses_shared_return(self):
        session=self.session([])
        session.weapon_exit_players.return_value=[{'address':123,'map':[5,16]}]
        result=session.leave_weapon_shop_by_door()
        session._leave_weapon_shop_by_door.assert_not_called()
        session.return_with_hotkey.assert_called_once()
        self.assertEqual(result['exit_players'],[{'address':123,'map':[5,16]}])

    def scene_session(self,characters):
        session=object.__new__(BackgroundSession);session.base=0x400000
        session.check=Mock();session.pause=Mock();memory={}
        def put(address,data):
            memory.update({address+i:byte for i,byte in enumerate(data)})
        def integer(address,value):put(address,struct.pack('<I',value))
        def typed(address,vmt,name,text):
            integer(address,vmt);integer(vmt-44,text)
            put(text,bytes([len(name)])+name.encode('ascii'))
        typed(0x10000,session.base+0x1000,'TPlayScene',0x8000)
        typed(0x11000,session.base+0x2000,'TList',0x8100)
        integer(session.base+0x2ba8fc,0x9000);integer(0x9000,0x10000)
        integer(0x10000+0x98,0x11000)
        integer(session.base+0x2bac2c,0x9004);integer(0x9004,0x12000)
        integer(0x12000+0x358,0x13000)
        integer(session.base+0x2ba608,0x9008);integer(0x9008,0x14000)
        put(0x14004,b'M'*52)
        pointers=[]
        for address,x,y,dead,vmt in characters:
            raw=bytearray(0xb0);struct.pack_into('<I',raw,0,vmt or session.base+0x24991c)
            struct.pack_into('<2i',raw,0x68,x,y);raw[0xac]=dead
            put(address,raw);pointers.append(address)
        put(0x11000,struct.pack('<4I',session.base+0x2000,0x15000,len(pointers),len(pointers)))
        put(0x15000,struct.pack('<%dI'%len(pointers),*pointers))
        session.read=lambda address,size:bytes(memory[address+i] for i in range(size))
        session.uint=lambda address:struct.unpack('<I',session.read(address,4))[0]
        return session

    def test_scene_check_excludes_self_hero_distant_dead_and_other_types(self):
        characters=[(0x12000,5,16,0,0),(0x13000,4,16,0,0),
                    (0x16000,5,16,0,0),(0x17000,5,9,0,0),
                    (0x18000,5,16,1,0),(0x19000,5,16,0,0x401234)]
        session=self.scene_session(characters)
        # Writing the own actor fixture overwrites its hero field only if the
        # fixture grows beyond 0xb0, so the separate hero pointer stays intact.
        self.assertEqual(session.weapon_exit_players(),[{'address':0x16000,'map':[5,16]}])

    def test_empty_live_scene_is_clear_and_invalid_data_stops(self):
        self.assertEqual(self.scene_session([]).weapon_exit_players(),[])
        session=self.scene_session([(0x16000,5,16,2,0)])
        with self.assertRaisesRegex(RuntimeError,'人物数据不符'):session.weapon_exit_players()

    def test_fallback_exit_continues_to_island_sales_and_reports_charge(self):
        session=object.__new__(BackgroundSession)
        bag=['木剑','小手镯'];steps=[]
        session.inventory=lambda:list(bag)
        session.npcs=lambda:[]
        def weapons(**kwargs):
            steps.append('weapons');bag.remove('木剑');return {'count':1}
        def exit_shop(progress):
            steps.append('exit_return');return {'return_stone_used':True}
        def jewelry(progress):
            steps.append('jewelry');bag.clear();return {'count':1}
        session.teleport_weapon_sale=weapons
        session.leave_weapon_shop=exit_shop
        session.travel_cangyue=lambda progress:steps.append('island')
        session.close_panels=lambda:None
        session.cangyue_sale_stand=lambda:None
        session.sell_cangyue_at_anchor=jewelry
        session.player=lambda:(140,330)
        result=session.mixed_sale_route()
        self.assertEqual(steps,['weapons','exit_return','island','jewelry'])
        self.assertEqual(result['count'],2)
        self.assertEqual(result['remaining_plan'],[])
        self.assertEqual(result['exit_returns'],1)
        self.assertTrue(result['return_stone_used'])

    def test_shared_veteran_entry_validates_before_clicking(self):
        session=object.__new__(BackgroundSession)
        session.check=Mock();session.login_stage=Mock(return_value='playing')
        session.close_panels=Mock();session.unique_npc=Mock(return_value={'name':'盟重老兵'})
        session.locate_mengzhong_veteran=Mock(return_value={'name':'盟重老兵'})
        session.open_npc=Mock()
        session.open_mengzhong_veteran()
        session.locate_mengzhong_veteran.assert_called_once()
        session.open_npc.assert_called_once_with({'name':'盟重老兵'})
        session.open_npc.reset_mock();session.login_stage.return_value='dead'
        with self.assertRaises(GameSessionLost):session.open_mengzhong_veteran()
        session.open_npc.assert_not_called()


if __name__=='__main__':unittest.main()
