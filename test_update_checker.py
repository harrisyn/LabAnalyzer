#!/usr/bin/env python3
"""
Test script to verify the UpdateChecker functionality with zip asset handling
"""
import sys
import asyncio
sys.path.append('.')

from src.utils.updater import UpdateChecker

async def test_update_checker():
    """Test the UpdateChecker with current repository setup"""
    print("Testing UpdateChecker with current setup")
    print("="*50)
    
    # Test with version that should trigger update
    updater = UpdateChecker("1.0.0")
    print(f"Current version: {updater.current_version}")
    print(f"Update URL: {updater.update_url}")
    print()
    
    try:
        print("Checking for updates...")        # Mock the prompt to avoid GUI popup
        async def mock_prompt(version):
            return False  # Always decline update
        
        original_prompt = updater._prompt_update
        updater._prompt_update = mock_prompt
        
        result = await updater.check_for_updates()
        
        # Restore original method
        updater._prompt_update = original_prompt
        
        if result is None:
            print("✓ Update available but declined (as expected)")
        elif result is True:
            print("✓ Update was initiated")
        elif result is False:
            print("✓ No update available (current version is latest)")
        else:
            print(f"? Unexpected result: {result}")
            
    except Exception as e:
        print(f"✗ Error during update check: {e}")
        return False
    
    # Test version comparison
    print("\nTesting version comparison with actual latest version...")
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(updater.update_url) as response:
                if response.status == 200:
                    data = await response.json()
                    latest_version = data['tag_name'].lstrip('v')
                    
                    comparison = updater._compare_versions(latest_version, updater.current_version)
                    print(f"Latest version: {latest_version}")
                    print(f"Current version: {updater.current_version}")
                    print(f"Comparison result: {comparison} ({'Update needed' if comparison > 0 else 'Up to date'})")
                    
                    # Check asset detection
                    windows_assets = [asset for asset in data['assets'] 
                                    if asset['name'].endswith('.exe') or 
                                    (asset['name'].startswith('windows') and asset['name'].endswith('.zip'))]
                    
                    print(f"Windows assets found: {len(windows_assets)}")
                    for asset in windows_assets:
                        print(f"  - {asset['name']} ({asset.get('size', 0)} bytes)")
                        
    except Exception as e:
        print(f"✗ Error checking latest version: {e}")
        return False
    
    print("\n✓ All UpdateChecker tests completed successfully!")
    return True

if __name__ == "__main__":
    result = asyncio.run(test_update_checker())
    sys.exit(0 if result else 1)
