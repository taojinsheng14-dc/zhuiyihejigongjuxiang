import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch


class ProfitGuiTests(unittest.TestCase):
    def test_reset_stays_visible_above_long_scrollable_statistics(self):
        import mixed_sale_gui as gui
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder,patch.object(gui,'ROOT',Path(folder)),patch.object(gui,'drive') as drive:
            app=gui.App()
            try:
                for callback in app.tk.call('after','info'):app.after_cancel(callback)
                app.geometry('1120x760');app.status_tabs.select(0)
                app.profit_text.set('\n'.join('收益明细 '+str(i) for i in range(70)))
                app.update()
                button=app.profit_reset_button
                self.assertTrue(button.winfo_viewable())
                self.assertGreater(button.winfo_height(),20)
                self.assertLess(button.winfo_rooty()+button.winfo_height(),app.profit_canvas.winfo_rooty())
                self.assertLess(button.winfo_rooty()+button.winfo_height(),app.winfo_rooty()+app.winfo_height())
                self.assertLess(app.profit_canvas.yview()[1],1)
                app.profit_canvas.yview_moveto(1);app.update_idletasks()
                self.assertTrue(button.winfo_viewable())
                app.start_profit=Mock();button.invoke()
                app.start_profit.assert_called_once_with(reset=True)
                drive.assert_not_called()
            finally:app.destroy()

    def test_attaches_current_loop_despite_previous_error_but_not_finished_or_stale(self):
        from mixed_sale_gui import active_task
        command={'step':50,'categories':['挂机清包循环']}
        result={'step':49,'error':'old error','state':{'game_pid':32104}}
        sample={'ok':True,'observed_epoch':100,'game_pid':32104}
        self.assertEqual(active_task(command,result,sample,101),50)
        self.assertIsNone(active_task(command,dict(result,step=50),sample,101))
        self.assertIsNone(active_task(command,result,sample,105))
        self.assertIsNone(active_task(command,result,dict(sample,game_pid=1),101))

    def test_attaches_continuous_mage_command(self):
        from mixed_sale_gui import active_task
        command={'step':72,'categories':['法师地牢持续清怪拾取']}
        result={'step':71,'state':{'game_pid':3528}}
        sample={'ok':True,'observed_epoch':100,'game_pid':3528}
        self.assertEqual(active_task(command,result,sample,101),72)

    def test_attached_stop_writes_current_command_without_game_input(self):
        import mixed_sale_gui as gui
        from types import SimpleNamespace
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder,patch.object(gui,'HELPER',Path(folder)):
            app=SimpleNamespace(cancel=Mock(),attached_step=50,status=Mock())
            gui.App.request_stop(app)
            saved=json.loads((Path(folder)/'source-sale-cancel.json').read_text(encoding='utf8'))
            self.assertEqual(saved['step'],50)
            self.assertEqual(saved['requested_by'],'user')

    def test_coordinates_and_counts_render_in_main_window_and_stale_values_clear(self):
        import mixed_sale_gui as gui
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'outputs').mkdir()
            path=root/'outputs'/'实时监控.json'
            sample={'ok':True,'observed_epoch':time.time(),'position':[140,330],
                    'radius':12,'count':4,'target_count':3,'player_count':2,'player_radius':8,
                    'read_ms':2.5,'by_name':{'白野猪':3}}
            path.write_text(json.dumps(sample),encoding='utf8')
            with patch.object(gui,'ROOT',root):
                app=gui.App();app.withdraw()
                try:
                    app.refresh_live();self.assertIn('140',app.live_position.get())
                    self.assertIn('候选3',app.live_count.get());self.assertIn('其他玩家2',app.live_count.get())
                    self.assertFalse(app.foreground.get())
                    sample['observed_epoch']-=10;path.write_text(json.dumps(sample),encoding='utf8')
                    app.refresh_live();self.assertIn('等待有效',app.live_position.get())
                finally:app.destroy()

    def test_live_wallet_renders_profit_and_settings_without_game_input(self):
        import mixed_sale_gui as gui
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'outputs').mkdir()
            monitor=root/'outputs'/'实时监控.json'
            sample={'ok':True,'game_pid':1,'wallet_observed_epoch':time.time(),
                    'wallet':{'gold':100000,'yuanbao':30}}
            monitor.write_text(json.dumps(sample),encoding='utf-8')
            with patch.object(gui,'ROOT',root):
                app=gui.App();app.withdraw()
                try:
                    self.assertTrue(app.start_profit(reset=True,quiet=True))
                    sample['wallet']={'gold':300000,'yuanbao':15}
                    sample['wallet_observed_epoch']=time.time()
                    monitor.write_text(json.dumps(sample),encoding='utf-8')
                    app.refresh_profit()
                    text=app.profit_text.get()
                    self.assertIn('+200,000',text)
                    self.assertIn('+21.00',text)
                    self.assertIn('+1.91',text)
                    self.assertIn('每秒更新',app.profit_status.get())
                finally:app.destroy()


if __name__=='__main__':unittest.main()
