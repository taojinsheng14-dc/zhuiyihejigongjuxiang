import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch


class BindingRefreshTests(unittest.TestCase):
    def test_invalid_binding_does_not_look_connected(self):
        import mixed_sale_gui as gui
        with patch.object(gui.instance_context,'binding',return_value={'pid':1,'character':'大鱼'}),patch.object(gui.instance_context,'verify_binding',side_effect=RuntimeError('old process')):
            self.assertIn('旧绑定：大鱼',gui.App.binding_summary(None))
            self.assertIn('重新选择',gui.App.binding_summary(None))

    def test_live_title_change_is_shown_without_saving_or_guessing_binding(self):
        import mixed_sale_gui as gui
        reader=Mock();reader.candidates.return_value=[(1,'游戏 - 微笑','game.exe'),(2,'游戏 - 厚礼蟹','game.exe')]
        app=SimpleNamespace(last_binding_refresh=0,binding_label=Mock(),available_roles=Mock(),binding_summary=lambda:'old')
        with patch('fast_sale.MemoryReader',return_value=reader),patch.object(gui.instance_context,'binding',return_value={'pid':1,'character':'大鱼'}),patch.object(gui.instance_context,'save_binding') as save:
            gui.App.refresh_binding_status(app)
        self.assertIn('当前窗口：微笑',app.binding_label.set.call_args.args[0])
        self.assertIn('厚礼蟹',app.available_roles.set.call_args.args[0])
        save.assert_not_called();reader.close.assert_called_once()

    def test_active_command_blocks_helper_shutdown_and_rebinding(self):
        import mixed_sale_gui as gui
        with tempfile.TemporaryDirectory() as folder,patch.object(gui,'HELPER',Path(folder)),patch.object(gui.instance_context,'process_identity',return_value={}),patch.object(gui,'drive') as drive:
            (Path(folder)/'source-sale-result.json').write_text(json.dumps({'step':9,'state':{'helper_pid':12}}))
            (Path(folder)/'source-sale-command.json').write_text(json.dumps({'step':10}))
            app=SimpleNamespace(busy=False,attached_step=None,status=Mock())
            gui.App.choose_game(app)
        drive.assert_not_called();self.assertIn('尚未结束',app.status.set.call_args.args[0])

    def test_normal_helper_stop_accepts_exit_without_new_result_step(self):
        import source_driver
        with tempfile.TemporaryDirectory() as folder,patch.object(source_driver,'ROOT',Path(folder)),patch.object(source_driver.instance_context,'runtime_root',return_value=Path(folder)),patch.object(source_driver,'_helper_running',return_value=False):
            (Path(folder)/'source-sale-result.json').write_text(json.dumps({'step':9}))
            result=source_driver._drive_locked([{'action':'stop','foreground':False}],helper_pid=12)
            command=json.loads((Path(folder)/'source-sale-command.json').read_text())
        self.assertEqual(command['action'],'stop');self.assertEqual(command['step'],10)
        self.assertTrue(result['result']['helper_stopped'])
