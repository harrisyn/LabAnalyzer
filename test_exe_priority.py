#!/usr/bin/env python3
"""
Test script to verify .exe file prioritization logic
"""
import json

def test_asset_selection():
    """Test the asset selection logic with mock data"""
    
    # Mock release data with both .exe and .zip assets
    mock_release_data = {
        "tag_name": "v2.2.0",
        "assets": [
            {
                "name": "LabSync-Setup-2.2.0.exe",
                "browser_download_url": "https://github.com/harrisyn/LabAnalyzer/releases/download/v2.2.0/LabSync-Setup-2.2.0.exe",
                "size": 45000000
            },
            {
                "name": "windows-installer.zip",
                "browser_download_url": "https://github.com/harrisyn/LabAnalyzer/releases/download/v2.2.0/windows-installer.zip",
                "size": 35000000
            },
            {
                "name": "LabSync-2.2.0.dmg",
                "browser_download_url": "https://github.com/harrisyn/LabAnalyzer/releases/download/v2.2.0/LabSync-2.2.0.dmg",
                "size": 50000000
            }
        ]
    }
    
    print("Testing asset selection logic with mock release data:")
    print(f"Release: {mock_release_data['tag_name']}")
    print("\nAvailable assets:")
    for asset in mock_release_data['assets']:
        print(f"  - {asset['name']} ({asset['size']} bytes)")
    
    # Apply the same logic as the updater
    assets = mock_release_data['assets']
    
    # First, look for direct .exe installer (preferred)
    windows_asset = None
    for asset in assets:
        if asset['name'].endswith('.exe') and 'Setup' in asset['name']:
            windows_asset = asset
            break
    
    # Fallback to zip if no direct .exe found (legacy releases)
    if not windows_asset:
        for asset in assets:
            if asset['name'].startswith('windows') and asset['name'].endswith('.zip'):
                windows_asset = asset
                break
    
    print(f"\n✓ Selected asset: {windows_asset['name']}")
    print(f"  URL: {windows_asset['browser_download_url']}")
    print(f"  Size: {windows_asset['size']} bytes")
    print(f"  Type: {'Direct .exe (preferred)' if windows_asset['name'].endswith('.exe') else 'Zip fallback'}")
    
    return windows_asset['name'].endswith('.exe')

def test_legacy_only():
    """Test with only zip assets (legacy release scenario)"""
    
    mock_legacy_data = {
        "tag_name": "v2.0.0",
        "assets": [
            {
                "name": "windows-installer.zip",
                "browser_download_url": "https://github.com/harrisyn/LabAnalyzer/releases/download/v2.0.0/windows-installer.zip",
                "size": 35000000
            }
        ]
    }
    
    print("\n" + "="*50)
    print("Testing legacy release scenario (zip only):")
    print(f"Release: {mock_legacy_data['tag_name']}")
    print("\nAvailable assets:")
    for asset in mock_legacy_data['assets']:
        print(f"  - {asset['name']} ({asset['size']} bytes)")
    
    # Apply the same logic
    assets = mock_legacy_data['assets']
    
    windows_asset = None
    for asset in assets:
        if asset['name'].endswith('.exe') and 'Setup' in asset['name']:
            windows_asset = asset
            break
    
    if not windows_asset:
        for asset in assets:
            if asset['name'].startswith('windows') and asset['name'].endswith('.zip'):
                windows_asset = asset
                break
    
    print(f"\n✓ Selected asset: {windows_asset['name']}")
    print(f"  Type: {'Direct .exe (preferred)' if windows_asset['name'].endswith('.exe') else 'Zip fallback'}")
    
    return not windows_asset['name'].endswith('.exe')

if __name__ == "__main__":
    print("Asset Selection Priority Test")
    print("=" * 40)
    
    # Test with both .exe and .zip available
    exe_preferred = test_asset_selection()
    
    # Test with only .zip available
    zip_fallback = test_legacy_only()
    
    print("\n" + "="*50)
    print("SUMMARY:")
    print(f"✓ Direct .exe preferred when available: {exe_preferred}")
    print(f"✓ Zip fallback works for legacy releases: {zip_fallback}")
    
    if exe_preferred and zip_fallback:
        print("\n🎉 Asset selection logic is working correctly!")
        print("   - New releases with .exe files will be preferred")
        print("   - Legacy releases with .zip files will still work")
    else:
        print("\n❌ Asset selection logic needs review")
