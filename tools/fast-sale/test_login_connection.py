import ctypes
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from background_sale import BackgroundSession
import map_navigation


class LoginConnectionTests(unittest.TestCase):
    def setUp(self):
        # Fixtures must not inherit the user's live account binding.
        binding=patch('instance_context.binding',return_value=None);binding.start();self.addCleanup(binding.stop)

    def session(self, windows):
        s=object.__new__(BackgroundSession)
        s.reader=SimpleNamespace(find_game=Mock(return_value=None),callback_type=lambda f:f)
        def title(hwnd,buffer,size):buffer.value=windows[hwnd][0]
        def pid(hwnd,pointer):ctypes.cast(pointer,ctypes.POINTER(ctypes.c_ulong)).contents.value=windows[hwnd][1]
        s.u=SimpleNamespace(IsWindowVisible=lambda hwnd:True,GetWindowTextW=title,
                            GetWindowThreadProcessId=pid,
                            EnumWindows=lambda visit,arg:[visit(hwnd,arg) for hwnd in windows])
        s.process_image_path=Mock(return_value=map_navigation.MAP_DIRECTORY.parent/'client.exe')
        return s

    def test_login_window_selected_without_character_title(self):
        s=self.session({1:('BLUEM2',123),2:('传奇登陆器',456)})
        self.assertEqual(s.find_session_game(),(123,'BLUEM2','client.exe'))
        s.process_image_path.assert_called_once_with(123)

    def test_wrong_directory_not_selected(self):
        s=self.session({1:('BLUEM2',123)})
        s.process_image_path.return_value=Path('C:/unrelated/client.exe')
        self.assertIsNone(s.find_session_game())

    def test_ambiguous_login_clients_rejected(self):
        s=self.session({1:('BLUEM2',123),2:('BLUEM2',456)})
        with self.assertRaisesRegex(RuntimeError,'不是唯一'):s.find_session_game()

    def test_existing_character_selection_preserved(self):
        s=self.session({})
        s.reader.find_game.return_value=(123,'character','client.exe')
        self.assertEqual(s.find_session_game(),(123,'character','client.exe'))
        s.process_image_path.assert_not_called()
