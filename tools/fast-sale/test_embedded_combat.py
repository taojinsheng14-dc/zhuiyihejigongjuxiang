import json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import mixed_sale_gui as gui

class EmbeddedCombatTests(unittest.TestCase):
    def test_original_toolbox_displays_live_combat_without_extra_window(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'outputs').mkdir()
            sample={'ok':True,'observed_epoch':time.time(),'game_pid':11,'position':[1,2],'radius':12,'count':2,'read_ms':1,
                    'combat':{'available':True,'character':'测试角色','growth_events':12,'main_exp_gain':3600,'experience_per_hour':36000}}
            path=root/'outputs/实时监控.json';path.write_text(json.dumps(sample),encoding='utf8')
            with patch.object(gui,'ROOT',root):
                app=gui.App();app.withdraw()
                try:
                    app.refresh_live()
                    self.assertIn('12',app.combat_text.get());self.assertIn('3,600',app.combat_text.get())
                    self.assertEqual(len(app.status_tabs.tabs()),2)
                    self.assertEqual(app.status_tabs.tab(app.status_tabs.select(),'text'),'经验／击杀')
                    sample['observed_epoch']-=10;path.write_text(json.dumps(sample),encoding='utf8');app.refresh_live()
                    self.assertIn('等待有效采样',app.combat_text.get())
                finally:app.destroy()
if __name__=='__main__':unittest.main()
