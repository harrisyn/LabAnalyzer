#!/usr/bin/env python3
"""
Test the About dialog functionality
"""
import os
import sys
import tkinter as tk
from tkinter import messagebox

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_about_dialog():
    """Test the about dialog"""
    
    # Create a simple test config
    config = {
        'version': '1.0.0',
        'app_name': 'LabSync'
    }
    
    # Simulate the about dialog
    version = config.get('version', '1.0.0')
    app_name = config.get('app_name', 'LabSync')
    
    about_text = f"""{app_name} v{version}

Laboratory Data Analysis and Synchronization Tool

Features:
• Real-time data processing from multiple analyzer protocols
• ASTM, HL7, and proprietary protocol support
• Data synchronization with external systems
• Result visualization and reporting
• System tray integration

© 2025 LabSync Development Team"""
    
    print("About Dialog Content:")
    print("=" * 50)
    print(about_text)
    print("=" * 50)
    
    # Test with GUI
    root = tk.Tk()
    root.withdraw()  # Hide main window
    
    result = messagebox.showinfo("About", about_text)
    print(f"Dialog result: {result}")
    
    root.destroy()

if __name__ == "__main__":
    print("Testing About Dialog...")
    test_about_dialog()
    print("About dialog test completed.")
