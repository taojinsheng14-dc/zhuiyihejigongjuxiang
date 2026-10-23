from pathlib import Path
import unittest
from unittest.mock import Mock,patch

import dual_role_gui as dual


class DualRoleTests(unittest.TestCase):
    def test_commands_pin_distinct_instances_without_starting_gameplay(self):
        for slot in ('1','2'):
            args=dual.child_command(slot)
            self.assertEqual(args[-2:],['--instance',slot])
            self.assertNotIn('--start-hunt',args)
            self.assertEqual(Path(args[1]).name,'mixed_sale_gui.py')

    def test_host_uses_distinct_containers_and_graceful_shutdown(self):
        with patch.object(dual.subprocess,'Popen') as launch:
            launch.side_effect=[Mock(poll=Mock(return_value=None)) for _ in range(3)]
            app=dual.DualRoleApp();app.withdraw()
            try:
                calls=launch.call_args_list
                self.assertEqual(len(calls),3)
                environments=[c.kwargs['env'] for c in calls]
                self.assertEqual([e['MIR_TOOL_INSTANCE'] for e in environments],['1','2','1'])
                self.assertEqual(Path(calls[2].args[0][1]).name,'app.py')
                self.assertIn('MIR_BOSS_TIMER_DATA',environments[2])
                self.assertNotEqual(environments[0]['MIR_TOOL_EMBED_PARENT'],environments[1]['MIR_TOOL_EMBED_PARENT'])
                self.assertNotEqual(environments[0]['MIR_TOOL_EMBED_READY'],environments[1]['MIR_TOOL_EMBED_READY'])
                app.tabs.select(1);app.update_idletasks()
                for process in app.processes.values():process.terminate.assert_not_called()
                app.close_window()
                self.assertTrue((app.directory/'shutdown').exists())
                for process in app.processes.values():
                    process.terminate.assert_not_called();process.kill.assert_not_called()
            finally:
                for callback in app.tk.call('after','info'):app.after_cancel(callback)
                app.workspace.cleanup();app.destroy()


if __name__=='__main__':unittest.main()
