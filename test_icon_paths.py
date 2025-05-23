#!/usr/bin/env python3
"""
Test script to verify icon path resolution
"""
import os
import sys

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_icon_paths():
    """Test the icon path resolution"""
    from src.gui.app_window import ApplicationWindow
    
    # Create a mock logger
    class MockLogger:
        def debug(self, msg):
            print(f"DEBUG: {msg}")
        def info(self, msg):
            print(f"INFO: {msg}")
        def warning(self, msg):
            print(f"WARNING: {msg}")
        def error(self, msg):
            print(f"ERROR: {msg}")
    
    # Create a mock app window to test the icon path method
    class TestAppWindow(ApplicationWindow):
        def __init__(self):
            self.logger = MockLogger()
    
    test_app = TestAppWindow()
    icon_paths = test_app._get_icon_paths()
    
    print("Icon paths being checked:")
    for i, path in enumerate(icon_paths, 1):
        exists = os.path.exists(path)
        print(f"{i:2d}. {path} {'✓' if exists else '✗'}")
        if exists:
            print(f"    -> Found! Size: {os.path.getsize(path)} bytes")
    
    # Find the first existing icon
    for path in icon_paths:
        if os.path.exists(path):
            print(f"\nFirst available icon: {path}")
            return True
    
    print("\nNo icon files found!")
    return False

if __name__ == "__main__":
    print("Testing icon path resolution...")
    print(f"Python executable: {sys.executable}")
    print(f"Frozen: {getattr(sys, 'frozen', False)}")
    if hasattr(sys, '_MEIPASS'):
        print(f"MEIPASS: {sys._MEIPASS}")
    print()
    
    test_icon_paths()
