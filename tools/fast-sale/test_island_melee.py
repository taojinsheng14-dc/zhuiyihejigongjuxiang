import struct,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from island_melee import click_target,Melee


class IslandMeleeTests(unittest.TestCase):
    def session(self,hover=True):
        raw=bytearray(0x184);struct.pack_into('<I',raw,0,0x12345);struct.pack_into('<I',raw,12,0x40000)
        struct.pack_into('<2i',raw,0x17c,600,220)
        target={'address':0x90000,'name':'蜈蚣','class':'TCatMon','position':[20,21],'distance':1,'on_screen':True,'dead':False}
        messages=[]
        def send(hwnd,msg,*args):messages.append(msg);return 1
        table={0x3fffc:len('蜈蚣'.encode('gb18030')),0x2bb0a8:0x70000,0x70000:0x80000}
        s=SimpleNamespace(base=0,hwnd=1,player=lambda:(20,20),scene_actor_snapshot=lambda:[(0x90000,bytes(raw))],
            uint=lambda a:table.get(a,0x90000 if a==0x801b8 and hover else 0),
            read=lambda a,n:'蜈蚣'.encode('gb18030') if a==0x40000 else struct.pack('<H',100 if a==0x90112 else 200),
            client_size=lambda:(1280,800),physical_client_size=lambda:(1920,1200),
            u=SimpleNamespace(SendMessageTimeoutW=send),wait_mouse_modifiers_released=lambda:None,
            begin_background_input=lambda:None,pause=lambda n:None,background_mouse=Mock(),clear_background_mouse=Mock())
        return s,target,messages

    def test_exact_hover_sends_single_background_left_click_without_skill_keys(self):
        s,t,m=self.session()
        with patch('island_melee.guard'):r=click_target(s,t)
        self.assertTrue(r['clicked']);self.assertFalse(r['effect_verified'])
        self.assertEqual(s.background_mouse.call_count,1);self.assertEqual(s.background_mouse.call_args.args[1],'left')
        self.assertFalse(any(msg in (0x100,0x101) for msg in m));s.clear_background_mouse.assert_called_once()

    def test_no_hover_proof_never_clicks(self):
        s,t,m=self.session(hover=False)
        with patch('island_melee.guard'):r=click_target(s,t)
        self.assertFalse(r['clicked']);s.background_mouse.assert_not_called()

    def test_player_or_npc_type_never_clicked(self):
        s,t,m=self.session();t['class']='THumActor'
        with patch('island_melee.guard'):
            with self.assertRaisesRegex(RuntimeError,'怪物类型'):click_target(s,t)
        s.background_mouse.assert_not_called()

    def test_same_live_target_is_not_reclicked_each_tick(self):
        s,t,m=self.session();controller=Melee();sample={'monsters':[t],'drops':[]}
        with patch('island_melee.guard'):
            first=controller.step(s,sample);second=controller.step(s,sample)
        self.assertTrue(first['clicked']);self.assertTrue(second['engaged']);self.assertFalse(second['clicked'])
        self.assertEqual(s.background_mouse.call_count,1)

    def test_wrong_map_stops_before_hover(self):
        s,t,m=self.session();s.check=lambda:None;s.login_stage=lambda:'playing'
        with patch('island_automation.header',return_value=b'wrong'):
            with self.assertRaisesRegex(RuntimeError,'孤岛'):click_target(s,t)
        self.assertEqual(m,[])
