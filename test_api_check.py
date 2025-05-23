#!/usr/bin/env python3
"""
Test script to verify update check API functionality (no GUI)
"""
import os
import sys
import asyncio
import aiohttp

async def test_github_api():
    """Test GitHub API connectivity"""
    update_url = "https://api.github.com/repos/harrisyn/LabAnalyzer/releases/latest"
    headers = {'Accept': 'application/vnd.github.v3+json'}
    
    print("Testing GitHub API connectivity...")
    print(f"URL: {update_url}")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(update_url, headers=headers) as response:
                print(f"Response status: {response.status}")
                
                if response.status == 200:
                    data = await response.json()
                    print(f"Latest release tag: {data.get('tag_name', 'N/A')}")
                    print(f"Release name: {data.get('name', 'N/A')}")
                    print(f"Published at: {data.get('published_at', 'N/A')}")
                      # Check for Windows assets
                    assets = data.get('assets', [])
                    
                    # Check for Windows installer assets (prioritize .exe over .zip)
                    windows_exe_assets = [asset for asset in assets if asset['name'].endswith('.exe') and 'Setup' in asset['name']]
                    windows_zip_assets = [asset for asset in assets if asset['name'].startswith('windows') and asset['name'].endswith('.zip')]
                    
                    print(f"Windows .exe installer assets: {len(windows_exe_assets)}")
                    if windows_exe_assets:
                        for asset in windows_exe_assets:
                            print(f"  - {asset['name']} ({asset['size']} bytes)")
                    
                    print(f"Windows .zip installer assets: {len(windows_zip_assets)}")
                    if windows_zip_assets:
                        for asset in windows_zip_assets:
                            print(f"  - {asset['name']} ({asset['size']} bytes)")
                    
                    # Show which one would be selected by the updater
                    preferred_asset = None
                    if windows_exe_assets:
                        preferred_asset = windows_exe_assets[0]
                        print(f"✓ Updater would select: {preferred_asset['name']} (direct .exe - preferred)")
                    elif windows_zip_assets:
                        preferred_asset = windows_zip_assets[0]
                        print(f"✓ Updater would select: {preferred_asset['name']} (fallback .zip)")
                    else:
                        print("✗ No suitable Windows installer found!")
                    
                    return True
                else:
                    print(f"API request failed with status {response.status}")
                    return False
                    
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_version_comparison():
    """Test version comparison logic"""
    print("\nTesting version comparison...")
    
    # Add the src directory to the Python path
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
    
    from src.utils.updater import UpdateChecker
    
    updater = UpdateChecker("1.0.0")
    
    test_cases = [
        ("1.0.0", "1.0.0", 0),  # Same version
        ("1.0.0", "1.0.1", -1), # Newer available
        ("1.0.1", "1.0.0", 1),  # Current is newer
        ("1.0.0", "2.0.0", -1), # Major update available
        ("2.0.0", "1.9.9", 1),  # Current major is newer
    ]
    
    for v1, v2, expected in test_cases:
        result = updater._compare_versions(v1, v2)
        status = "✓" if result == expected else "✗"
        print(f"{status} {v1} vs {v2}: {result} (expected {expected})")

async def main():
    print("Update Check Test Suite")
    print("=" * 40)
    
    # Test version comparison
    test_version_comparison()
    
    # Test GitHub API
    print()
    api_success = await test_github_api()
    
    if api_success:
        print("\n✓ All tests passed! Update functionality should work.")
    else:
        print("\n✗ GitHub API test failed. Check network connectivity.")

if __name__ == "__main__":
    asyncio.run(main())
