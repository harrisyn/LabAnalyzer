import socket
import sys
import logging
import time

class SingleInstanceChecker:
    """
    Ensures only one instance of the application is running by binding to a specific socket port.
    If the port is already bound, it assumes another instance is running and tries to bring it to focus.
    """
    
    def __init__(self, port=44444, app_name="LabSync"):
        self.port = port
        self.app_name = app_name
        self.socket = None
        self.logger = logging.getLogger("SingleInstance")

    def is_another_instance_running(self):
        """
        Check if another instance is running by trying to bind to a local port.
        Returns True if another instance is detected, False otherwise.
        """
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # Check for Windows behavior regarding SO_REUSEADDR - strict binding desired
            # We explicitly do NOT set SO_REUSEADDR so that the bind fails if occupied
            self.socket.bind(('127.0.0.1', self.port))
            # Just keeping the socket open holds the port
            return False
        except socket.error:
            # Port is busy, so another instance is likely running
            return True
            
    def focus_existing_window(self):
        """
        Attempt to bring the existing application window to the foreground.
        Platform specific implementation.
        """
        if sys.platform == 'win32':
            self._focus_window_windows()
        elif sys.platform == 'darwin':
            self._focus_window_mac()
            
    def _focus_window_windows(self):
        """Windows implementation to focus existing window"""
        try:
            import ctypes
            
            # Define buffer type for window title
            EnumWindows = ctypes.windll.user32.EnumWindows
            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            GetWindowText = ctypes.windll.user32.GetWindowTextW
            GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
            IsWindowVisible = ctypes.windll.user32.IsWindowVisible
            SetForegroundWindow = ctypes.windll.user32.SetForegroundWindow
            ShowWindow = ctypes.windll.user32.ShowWindow
            IsIconic = ctypes.windll.user32.IsIconic
            
            SW_RESTORE = 9
            
            found_window = [False]
            
            def foreach_window(hwnd, lParam):
                if IsWindowVisible(hwnd):
                    length = GetWindowTextLength(hwnd)
                    if length > 0:
                        buff = ctypes.create_unicode_buffer(length + 1)
                        GetWindowText(hwnd, buff, length + 1)
                        title = buff.value
                        
                        # Match window title (contains app name)
                        if self.app_name in title:
                            # If minimized, restore it
                            if IsIconic(hwnd):
                                ShowWindow(hwnd, SW_RESTORE)
                            else:
                                ShowWindow(hwnd, SW_RESTORE) # Also ensures it's shown if hidden
                                
                            # Bring to front
                            SetForegroundWindow(hwnd)
                            found_window[0] = True
                            return False # Stop enumerating
                return True
            
            EnumWindows(EnumWindowsProc(foreach_window), 0)
            
            if not found_window[0]:
                self.logger.warning(f"Could not find window with title '{self.app_name}' to focus")
                
        except Exception as e:
            self.logger.error(f"Failed to focus existing window: {e}")

    def _focus_window_mac(self):
        """Mac implementation to focus existing window"""
        # This is trickier on Mac dealing with potentially different process names
        # Attempt simple AppleScript
        try:
            import subprocess
            # This assumes the app name matches what the OS sees
            script = f'tell application "{self.app_name}" to activate'
            subprocess.run(['osascript', '-e', script], capture_output=True)
            
            # If running from python source, it might be "Python" or "Python3"
            if not getattr(sys, 'frozen', False):
                 script = 'tell application "Python" to activate'
                 subprocess.run(['osascript', '-e', script], capture_output=True)
                 
        except Exception as e:
            self.logger.error(f"Failed to focus Mac window: {e}")
