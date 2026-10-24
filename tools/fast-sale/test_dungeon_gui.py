import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch


class DungeonGuiTests(unittest.TestCase):
    def test_start_button_dispatches_background_command_and_shares_stop(self):
        import mixed_sale_gui as gui
        with tempfile.TemporaryDirectory() as folder,patch.object(gui,'ROOT',Path(folder)),patch.object(gui,'HELPER',Path(folder)),patch.object(gui.instance_context,'binding',return_value={'character':'厚礼蟹','pid':1,'title':'厚礼蟹'}),patch.object(gui,'drive',return_value={'result':{'status':'test'}}) as drive:
            app=gui.App()
            try:
                for callback in app.tk.call('after','info'):app.after_cancel(callback)
                dungeon=next(tab for tab in app.tabs.tabs() if app.tabs.tab(tab,'text')=='地牢挂机')
                app.tabs.select(dungeon);app.update()
                self.assertTrue(app.dungeon_start_button.winfo_viewable())
                app.foreground.set(True);app.dungeon_start_button.invoke()
                result,error=app.messages.get(timeout=2)
                self.assertIsNone(error)
                drive.assert_called_once_with([{'action':'shop_route','categories':['法师地牢持续清怪拾取'],'foreground':False}],app.cancel)
                self.assertEqual(str(app.stop_button['state']),'normal')
                self.assertEqual(str(app.dungeon_start_button['state']),'disabled')
                app.finished(result,None)
                self.assertEqual(str(app.dungeon_start_button['state']),'normal')
            finally:app.destroy()

    def test_wrong_character_does_not_dispatch(self):
        import mixed_sale_gui as gui
        app=SimpleNamespace(busy=False,attached_step=None,status=Mock())
        with patch.object(gui.instance_context,'binding',return_value={'character':'大鱼'}),patch.object(gui,'drive') as drive:
            gui.App.run(app,'mage_dungeon')
        drive.assert_not_called();self.assertIn('厚礼蟹',app.status.set.call_args.args[0])

    def test_panel_stop_reason_and_non_kill_counts_are_visible(self):
        import mixed_sale_gui as gui
        with tempfile.TemporaryDirectory() as folder,patch.object(gui,'ROOT',Path(folder)):
            out=Path(folder)/'outputs';out.mkdir()
            (out/'法师地牢挂机状态.json').write_text(json.dumps({'phase':'stopped','position':[197,218],
                'casts':260,'observed_deaths':88,'verified_pickups':4,'route':{'visited':154,'total':285},
                'reason':'操作面板打开，未施法'}),encoding='utf-8')
            app=SimpleNamespace(last_dungeon_refresh=0,dungeon_status=Mock())
            gui.App.refresh_dungeon_status(app)
            text=app.dungeon_status.set.call_args.args[0]
            self.assertIn('死亡观察 88',text);self.assertIn('154/285',text);self.assertIn('操作面板打开',text)
