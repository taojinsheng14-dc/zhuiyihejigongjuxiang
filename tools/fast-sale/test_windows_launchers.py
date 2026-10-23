import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.name=='nt','Windows cmd parser regression')
class WindowsLauncherTests(unittest.TestCase):
    def test_zip_distributed_batches_retain_crlf(self):
        for name in ('启动工具箱.bat','START_TOOLBOX.bat','首次安装.bat','导出诊断日志.bat'):
            raw=(ROOT/name).read_bytes()
            self.assertIn(b'\r\n',raw,name)
            self.assertNotIn(b'\n',raw.replace(b'\r\n',b''),name)
        self.assertIn('*.bat -text',(ROOT/'.gitattributes').read_text())

    def test_cmd_parses_launcher_without_starting_ui(self):
        with tempfile.TemporaryDirectory(prefix='toolbox launcher ') as folder:
            root=Path(folder);(root/'.venv/Scripts').mkdir(parents=True)
            (root/'.venv/Scripts/pythonw.exe').touch()
            raw=(ROOT/'START_TOOLBOX.bat').read_bytes().replace(b'start "" ',b'echo LAUNCH ')
            (root/'START_TOOLBOX.bat').write_bytes(raw)
            (root/'entry.bat').write_bytes((ROOT/'启动工具箱.bat').read_bytes())
            result=subprocess.run(['cmd.exe','/d','/c','entry.bat'],cwd=root,capture_output=True,encoding='utf8',timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('LAUNCH',result.stdout)
            self.assertIn('launch_toolbox.py',result.stdout)
            self.assertNotIn('not recognized',result.stderr)


if __name__=='__main__':unittest.main()
