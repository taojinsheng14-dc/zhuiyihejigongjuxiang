import ctypes
from ctypes import wintypes as w
import unittest
from background_sale import query_client_size, BackgroundSession


class Win32:
    def __init__(self, scale=1.5):
        self.context = -4
        self.scale = scale
        self.fail = False
    def SetThreadDpiAwarenessContext(self, context):
        old = self.context
        self.context = context.value if isinstance(context, ctypes.c_void_p) else context
        return old
    def GetWindowDpiAwarenessContext(self, hwnd): return -1
    def GetClientRect(self, hwnd, rect):
        if self.fail: return 0
        multiplier = 1 if self.context == -1 else self.scale
        value = ctypes.cast(rect, ctypes.POINTER(w.RECT)).contents
        value.right, value.bottom = int(1024*multiplier), int(768*multiplier)
        return 1


class DpiTests(unittest.TestCase):
    def test_scaled_desktop_uses_receiver_coordinates_and_restores_context(self):
        for scale in (1,1.25,1.5,2):
            user32 = Win32(scale)
            self.assertEqual(query_client_size(user32,123,-1), (1024,768))
            self.assertEqual(user32.context,-4)
    def test_failure_still_restores_context(self):
        user32 = Win32();user32.fail=True
        with self.assertRaises(RuntimeError): query_client_size(user32,123,-1)
        self.assertEqual(user32.context,-4)
    def test_session_distinguishes_logical_and_physical(self):
        session = object.__new__(BackgroundSession)
        session.u = Win32();session.hwnd=123
        self.assertEqual(session.client_size(),(1024,768))
        self.assertEqual(session.physical_client_size(),(1536,1152))
        self.assertEqual(session.u.context,-4)


if __name__ == '__main__': unittest.main()
