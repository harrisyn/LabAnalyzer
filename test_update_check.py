#!/usr/bin/env python3
"""
Test script to verify manual update check functionality
"""
import os
import sys
import asyncio

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

async def test_update_check():
    """Test the update check functionality"""
    from src.utils.updater import UpdateChecker
    
    print("Testing UpdateChecker...")
    
    # Test with current version
    print("\n1. Testing with current version 1.0.0:")
    updater = UpdateChecker("1.0.0")
    try:
        result = await updater.check_for_updates()
        print(f"Result: {result}")
        if result is False:
            print("✓ No update needed (running latest version)")
        elif result is True:
            print("✓ Update was initiated")
        elif result is None:
            print("✓ Update available but user declined")
    except Exception as e:
        print(f"✗ Error: {e}")
    
    # Test with older version
    print("\n2. Testing with older version 0.9.0:")
    updater = UpdateChecker("0.9.0")
    try:
        result = await updater.check_for_updates()
        print(f"Result: {result}")
        if result is False:
            print("✓ No update needed")
        elif result is True:
            print("✓ Update was initiated")
        elif result is None:
            print("✓ Update available but user declined")
    except Exception as e:
        print(f"✗ Error: {e}")

if __name__ == "__main__":
    print("Testing Update Check Functionality...")
    print("=" * 50)
    
    try:
        asyncio.run(test_update_check())
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
    except Exception as e:
        print(f"Test failed: {e}")
    
    print("\nTest completed.")
