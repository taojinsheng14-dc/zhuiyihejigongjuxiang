import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import export_diagnostics as diagnostics
from ui_diagnostics import run_logged


class DiagnosticsTests(unittest.TestCase):
    def test_export_keeps_slots_separate_and_excludes_credentials_bindings_images(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            files={'outputs/实时监控.json':'one','instances/2/outputs/实时监控.json':'two',
                'outputs/BOSS计时器/消息处理.jsonl':'timer','tools/game-chat-inspect/source-sale-result.json':'result',
                'tools/fast-sale/private/game-login.dpapi':'secret','instances/2/private/game-login.dpapi':'secret2',
                'outputs/game-binding.json':'binding','tools/game-chat-inspect/source-sale-current.png':'image',
                'config/toolbox.local.json':'localconfig','outputs/工具箱/账号1界面.log':'gui'}
            for relative,text in files.items():
                path=root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf8')
            with patch.object(diagnostics.socket,'gethostname',return_value='PC-A'):
                target=diagnostics.export(root)
            with zipfile.ZipFile(target) as archive:
                names=archive.namelist()
                self.assertEqual(archive.read('outputs/实时监控.json'),b'one')
                self.assertEqual(archive.read('instances/2/outputs/实时监控.json'),b'two')
                self.assertFalse(any('private' in n or 'game-binding' in n or n.endswith(('.png','.dpapi')) or n.startswith('config/') for n in names))
                metadata=json.loads(archive.read('metadata.json'))
                self.assertEqual(metadata['machine'],'PC-A');self.assertEqual(len(metadata['files']),5)
                self.assertEqual(metadata['snapshot'],'best_effort_while_running')

    def test_ui_failure_is_logged_and_streams_restored(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'logs'/'ui.log';before=(sys.stdout,sys.stderr)
            def fail():print('diagnostic output');raise RuntimeError('sample UI failure')
            with self.assertRaisesRegex(RuntimeError,'sample UI failure'):run_logged(path,fail)
            self.assertEqual((sys.stdout,sys.stderr),before)
            text=path.read_text(encoding='utf8')
            self.assertIn('diagnostic output',text);self.assertIn('sample UI failure',text)


if __name__=='__main__':unittest.main()
