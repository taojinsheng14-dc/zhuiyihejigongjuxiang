import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


class TransferButtonTests(unittest.TestCase):
    def test_two_buttons_are_visible_and_dispatch_distinct_tests(self):
        import mixed_sale_gui as gui
        with tempfile.TemporaryDirectory() as folder, patch.object(gui,'ROOT',Path(folder)), patch.object(gui,'HELPER',Path(folder)), patch.object(gui,'drive') as drive:
            app=gui.App()
            try:
                for callback in app.tk.call('after','info'): app.after_cancel(callback)
                app.geometry('1120x760'); app.tabs.select(app.weapon_transfer_test_button.master); app.update()
                app.run=Mock()
                for button, action in [(app.weapon_transfer_test_button,'fixed_weapon_transfer'),(app.cangyue_transfer_test_button,'fixed_cangyue_transfer')]:
                    self.assertTrue(button.winfo_viewable())
                    self.assertGreater(button.winfo_height(),20)
                    self.assertLess(button.winfo_rooty()+button.winfo_height(),app.winfo_rooty()+app.winfo_height())
                    button.invoke(); app.run.assert_called_with(action)
                self.assertIn('2000',app.cangyue_transfer_test_button.cget('text'))
                drive.assert_not_called()
            finally: app.destroy()


if __name__=='__main__': unittest.main()
