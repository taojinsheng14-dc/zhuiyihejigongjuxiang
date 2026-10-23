import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import instance_context as ctx
from background_sale import BackgroundSession

class InstanceTests(unittest.TestCase):
    def test_manual_binding_can_connect_without_replacing_old_credentials(self):
        s=object.__new__(BackgroundSession);saved={'character':'old-role','username':'local','password':'local'}
        with patch.object(ctx,'binding',return_value={'character':'new-role'}),patch.object(ctx,'slot',return_value='1'),patch('credential_store.load',return_value=saved):
            s.configure_character_identity()
        self.assertEqual(s._expected_character,'new-role')
        self.assertEqual(saved,{})

    def test_mismatched_saved_login_is_blocked_before_any_ui_input(self):
        s=object.__new__(BackgroundSession);s._expected_character='new-role';s.login_stage=Mock(return_value='login');s.control_info=Mock();s.click=Mock()
        saved={'character':'old-role','username':'local','password':'local'}
        with patch('credential_store.load',return_value=saved):
            with self.assertRaisesRegex(RuntimeError,'未输入账号密码'):s.submit_saved_login()
        s.control_info.assert_not_called();s.click.assert_not_called();self.assertEqual(saved,{})

    def test_two_processes_resolve_disjoint_files_and_credentials(self):
        code="import json,instance_context as c,credential_store as s,random_hunt as r;print(json.dumps([str(c.helper_directory()),str(c.runtime_root()),str(s.PATH),str(r.SETTINGS_PATH)]))"
        values=[]
        for n in ('1','2'):
            env=dict(os.environ,PYTHONPATH=str(Path(__file__).parent.resolve()))
            result=subprocess.check_output([sys.executable,'-c',code,'--instance',n],env=env,text=True)
            values.append(json.loads(result))
        self.assertTrue(all(a!=b for a,b in zip(*values)))
        self.assertEqual(values[0][1],str(ctx.SOURCE_ROOT))

    def test_reused_pid_is_rejected_even_for_same_executable(self):
        before={'pid':10,'path':'D:/game.exe','created':1}
        with self.assertRaises(RuntimeError):ctx.validate_identity(before,dict(before,created=2))

    def test_second_slot_does_not_fall_back_to_first_game(self):
        s=object.__new__(BackgroundSession);s.reader=Mock()
        with patch.object(ctx,'binding',return_value=None),patch.object(ctx,'slot',return_value='2'):
            with self.assertRaises(RuntimeError):s.find_session_game()
        s.reader.find_game.assert_not_called()

    def test_explicit_binding_selects_exact_pid(self):
        s=object.__new__(BackgroundSession);s.reader=Mock()
        s.reader.find_game.return_value=(22,'title','game.exe')
        with patch.object(ctx,'binding',return_value={'pid':22}),patch.object(ctx,'verify_binding'):
            self.assertEqual(s.find_session_game()[0],22)
        s.reader.find_game.assert_called_once_with(22)

    def test_same_process_cannot_bind_both_slots(self):
        current={'pid':22,'path':'D:/game.exe','created':4}
        with patch.object(ctx,'process_identity',return_value=current),patch.object(ctx,'binding',return_value=current),patch('map_navigation.MAP_DIRECTORY',Path('D:/map')):
            with self.assertRaisesRegex(RuntimeError,'另一工具箱'):ctx.save_binding(22,'title - character')

    def test_bound_client_exit_never_adopts_other_live_account(self):
        s=object.__new__(BackgroundSession);s.reader=SimpleNamespace(alive=lambda:False)
        with patch.object(ctx,'binding',return_value={'pid':22}):
            with self.assertRaisesRegex(RuntimeError,'未自动改绑'):s.reconnect_running_client()

    def test_second_instance_cannot_send_foreground_action(self):
        sys.path.insert(0,str(ctx.SOURCE_ROOT/'tools'/'game-chat-inspect'))
        import source_driver
        with patch.object(ctx,'foreground_allowed',return_value=False):
            with self.assertRaisesRegex(RuntimeError,'后台输入'):
                source_driver._drive_locked([{'action':'shop_route','foreground':True}])

if __name__=='__main__':unittest.main()
