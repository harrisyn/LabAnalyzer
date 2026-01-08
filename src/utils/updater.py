"""
Handles automatic updates for the LabSync application
"""
import os
import sys
import json
import logging
import urllib.request
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk
import asyncio
import aiohttp
import zipfile
import time

class UpdateChecker:
    def _get_last_downloaded_info(self):
        info_path = self.temp_dir / "last_downloaded.json"
        if info_path.exists():
            try:
                with open(info_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error reading last_downloaded.json: {e}")
        return None

    def _set_last_downloaded_info(self, version, path):
        info_path = self.temp_dir / "last_downloaded.json"
        info = {
            "version": version,
            "path": str(path),
            "timestamp": time.strftime("%Y-%m-%d")
        }
        try:
            with open(info_path, "w") as f:
                json.dump(info, f)
        except Exception as e:
            print(f"Error writing last_downloaded.json: {e}")
            
    def __init__(self, current_version="1.0.0", app_window=None):
        self.current_version = current_version
        self.app_window = app_window  # Reference to main application window for clean shutdown
        # GitHub releases API URL - pointing to correct repository
        self.update_url = "https://api.github.com/repos/harrisyn/LabAnalyzer/releases/latest"
        self.temp_dir = Path(os.getenv('LOCALAPPDATA')) / "LabSync" / "Updates"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._headers = {'Accept': 'application/vnd.github.v3+json'}

    async def check_for_updates(self):
        """Check GitHub releases for newer version"""
        try:
            print("Checking for updates...")
            timeout = aiohttp.ClientTimeout(total=10, connect=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                print(f"Requesting update info from: {self.update_url}")
                try:
                    async with session.get(self.update_url, headers=self._headers) as response:
                        print(f"GitHub API response status: {response.status}")
                        if response.status == 404:
                            print("Repository not found (404)")
                            return False
                        elif response.status != 200:
                            print(f"GitHub API returned status {response.status}")
                            raise Exception(f"GitHub API returned status {response.status}")
                        data = await response.json()
                        latest_version = data.get('tag_name', '').lstrip('v')
                        print(f"Latest version from GitHub: {latest_version}")
                        print(f"Current version in app: {self.current_version}")
                        cmp_result = self._compare_versions(latest_version, self.current_version)
                        print(f"Version compare result: {cmp_result}")
                        if cmp_result > 0:
                            print("New version available!")
                            windows_asset = None
                            for asset in data.get('assets', []):
                                print(f"Checking asset: {asset.get('name')}")
                                if asset.get('name', '').endswith('.exe') and 'Setup' in asset.get('name', ''):
                                    windows_asset = asset
                                    print(f"Found Windows installer: {asset['name']}")
                                    break
                            if not windows_asset:
                                windows_asset = next(
                                    (asset for asset in data.get('assets', []) 
                                     if asset.get('name', '').startswith('windows') and asset.get('name', '').endswith('.zip')), None
                                )
                                if windows_asset:
                                    print(f"Found Windows zip installer: {windows_asset['name']}")
                            if not windows_asset:
                                print("No Windows installer found in the latest release")
                                raise Exception("No Windows installer found in the latest release")
                            prompt_result = await self._prompt_update(latest_version)
                            print(f"Prompt result: {prompt_result}")
                            if prompt_result:
                                print("User accepted update")
                                await self._download_and_install(windows_asset['browser_download_url'], latest_version=latest_version)
                                return True  # Update was initiated
                            print("User declined update")
                            return None  # Update available but user declined
                        else:
                            print("No update available")
                            return False  # No update available
                except asyncio.TimeoutError as e:
                    print(f"TimeoutError during update check: {e}")
                    raise Exception(f"TimeoutError: {e}")
                except aiohttp.ClientError as e:
                    print(f"aiohttp ClientError during update check: {e}")
                    raise Exception(f"Network error: {e}")
                except Exception as e:
                    print(f"General exception during update check: {e}")
                    raise
        except Exception as e:
            print(f"Update check failed: {e}")
            raise  # Re-raise for manual check error handling

    def _compare_versions(self, version1, version2):
        """Compare two version strings"""
        print(f"Comparing versions: {version1} vs {version2}")
        try:
            v1_parts = [int(x) for x in version1.split('.')]
            v2_parts = [int(x) for x in version2.split('.')]
        except Exception as e:
            print(f"Error parsing version strings: {e}")
            return 0
        for i in range(max(len(v1_parts), len(v2_parts))):
            v1 = v1_parts[i] if i < len(v1_parts) else 0
            v2 = v2_parts[i] if i < len(v2_parts) else 0
            print(f"Compare part: v1={v1}, v2={v2}")
            if v1 > v2:
                print("v1 > v2")
                return 1
            if v1 < v2:
                print("v1 < v2")
                return -1
        print("Versions are equal")
        return 0
        
    async def _prompt_update(self, new_version):
        """Show update prompt to user in the main Tkinter thread"""
        result = None
        def show_prompt():
            nonlocal result
            result = messagebox.askyesno(
                "Update Available",
                f"Version {new_version} is available. Would you like to update now?"
            )
        # If we have a reference to the main window, use root.after to schedule prompt
        if self.app_window and hasattr(self.app_window, 'root'):
            self.app_window.root.after(0, show_prompt)
            # Wait for the prompt to be answered
            while result is None:
                self.app_window.root.update()
                await asyncio.sleep(0.05)
            return result
        else:
            # Fallback: call directly (may fail if not in main thread)
            return messagebox.askyesno(
                "Update Available",
                f"Version {new_version} is available. Would you like to update now?"
            )
        
    async def _download_and_install(self, download_url, latest_version=None):
        """Download and install the new version"""
        try:
            # Check for existing recent download
            if latest_version:
                last_info = self._get_last_downloaded_info()
                today = time.strftime("%Y-%m-%d")
                if last_info and last_info.get("version") == latest_version and last_info.get("timestamp") == today:
                    installer_path = Path(last_info.get("path"))
                    if installer_path.exists() and installer_path.stat().st_size > 0:
                        print(f"Reusing previously downloaded installer for version {latest_version}: {installer_path}")
                        download_success = True
                    else:
                        print("Last downloaded installer missing or empty, will re-download.")
                        download_success = False
                else:
                    download_success = False
            else:
                download_success = False

            if not download_success:
                print(f"Downloading update from {download_url}")
                # Determine if we're downloading a zip or exe
                is_zip = download_url.endswith('.zip')
                download_path = self.temp_dir / ("installer.zip" if is_zip else "LabSync-Setup.exe")

                # Create progress dialog
                progress_window = tk.Toplevel()
                progress_window.title("Downloading Update")
                progress_window.geometry("400x150")
                progress_window.resizable(False, False)
                progress_window.transient(tk._default_root)  # Make it stay on top of main window
                progress_window.grab_set()  # Make it modal

                # Set window icon
                try:
                    icon_path = os.path.join(os.path.dirname(__file__), "..", "gui", "resources", "icon.ico")
                    if os.path.exists(icon_path):
                        progress_window.iconbitmap(icon_path)
                except Exception as e:
                    print(f"Error setting icon: {e}")
                    pass  # Ignore icon errors

                # Center the window
                progress_window.update_idletasks()
                width = progress_window.winfo_width()
                height = progress_window.winfo_height()
                x = (progress_window.winfo_screenwidth() // 2) - (width // 2)
                y = (progress_window.winfo_screenheight() // 2) - (height // 2)
                progress_window.geometry(f'{width}x{height}+{x}+{y}')

                # Create progress components
                tk.Label(progress_window, text="Downloading update...", font=("Arial", 12)).pack(pady=(15, 5))
                progress_var = tk.DoubleVar()
                progress_bar = ttk.Progressbar(progress_window, variable=progress_var, maximum=100, length=350)
                progress_bar.pack(pady=5, padx=25)
                status_var = tk.StringVar(value="Starting download...")
                status_label = tk.Label(progress_window, textvariable=status_var)
                status_label.pack(pady=5)

                # Update the UI during download
                def update_progress(percentage, message):
                    progress_var.set(percentage)
                    status_var.set(message)
                    progress_window.update()

                # Download with progress tracking
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(download_url) as response:
                            if response.status != 200:
                                progress_window.destroy()
                                raise Exception(f"Download failed with status {response.status}")

                            # Get total size for percentage calculation
                            total_size = int(response.headers.get('Content-Length', 0))
                            if total_size == 0:
                                # If Content-Length is not provided, use indefinite progress
                                update_progress(0, "Downloading... (size unknown)")
                                with open(download_path, 'wb') as f:
                                    f.write(await response.read())
                            else:
                                # Download with progress updates
                                chunk_size = 1024 * 8  # 8KB chunks
                                downloaded = 0
                                start_time = time.time()

                                with open(download_path, 'wb') as f:
                                    async for chunk in response.content.iter_chunked(chunk_size):
                                        f.write(chunk)
                                        downloaded += len(chunk)
                                        percentage = min(100.0, downloaded * 100 / total_size)

                                        # Calculate download speed and ETA
                                        elapsed = time.time() - start_time
                                        mb_downloaded = downloaded / (1024 * 1024)
                                        mb_total = total_size / (1024 * 1024)

                                        speed = mb_downloaded / elapsed if elapsed > 0 else 0
                                        eta = (mb_total - mb_downloaded) / speed if speed > 0 else 0

                                        message = f"Downloaded: {mb_downloaded:.1f} MB of {mb_total:.1f} MB ({percentage:.1f}%)"
                                        if speed > 0:
                                            message += f" | {speed:.1f} MB/s | ETA: {eta:.0f}s"

                                        # Update progress every ~20ms to avoid UI freezing
                                        update_progress(percentage, message)

                    download_success = True

                except aiohttp.ClientError as e:
                    progress_window.destroy()
                    messagebox.showerror("Download Error", f"Failed to download update: {str(e)}")
                    raise
                except Exception as e:
                    progress_window.destroy()
                    messagebox.showerror("Download Error", f"Failed to download update: {str(e)}")
                    raise

                # Update status before extraction
                if download_success:
                    update_progress(100, "Download complete. Preparing installer...")

                # Close progress dialog
                progress_window.destroy()

                # Verify download
                if not os.path.exists(download_path) or os.path.getsize(download_path) == 0:
                    # Open the folder for manual access
                    try:
                        os.startfile(self.temp_dir)
                    except Exception as e:
                        print(f"Failed to open download folder: {e}")
                    messagebox.showerror("Download Error", f"Downloaded file is empty or missing.\nPlease check the folder:\n{self.temp_dir}")
                    return

                # Handle zip extraction if needed
                if is_zip:
                    try:
                        with zipfile.ZipFile(download_path, 'r') as zip_ref:
                            zip_ref.extractall(self.temp_dir)
                    except Exception as e:
                        os.startfile(self.temp_dir)
                        messagebox.showerror("Extraction Error", f"Failed to extract installer zip.\nError: {e}\nPlease check the folder:\n{self.temp_dir}")
                        return
                    # Find the .exe file in the extracted contents
                    exe_files = list(self.temp_dir.glob("**/*.exe"))
                    if not exe_files:
                        os.startfile(self.temp_dir)
                        messagebox.showerror("Installer Error", f"No .exe installer found in the downloaded zip.\nPlease check the folder:\n{self.temp_dir}")
                        return
                    installer_path = exe_files[0]  # Use the first .exe found
                else:
                    installer_path = download_path

                # Verify installer exists
                if not os.path.exists(installer_path):
                    os.startfile(self.temp_dir)
                    messagebox.showerror("Installer Error", f"Installer file missing: {installer_path}\nPlease check the folder:\n{self.temp_dir}")
                    return

                print(f"Installer ready: {installer_path}")
                # Record last downloaded info
                if latest_version:
                    self._set_last_downloaded_info(latest_version, installer_path)
                
            print(f"Installer ready: {installer_path}")
            
            # Record last downloaded info
            if latest_version:
                self._set_last_downloaded_info(latest_version, installer_path)
            
            # Display message to user
            messagebox.showinfo("Update Ready", 
                                "The update has been downloaded. The application will now close and the installer will start.\n\n"
                                "Please follow the installer instructions.")
            
            # Close all toplevel windows
            for widget in tk._default_root.winfo_children():
                if isinstance(widget, tk.Toplevel):
                    widget.destroy()

            # Launch installer directly
            print(f"Launching installer: {installer_path}")
            try:
                # Use os.startfile to launch the installer (handles UAC if needed by the installer itself)
                os.startfile(str(installer_path))
                print("Installer launched successfully.")
            except Exception as e:
                print(f"Failed to launch installer: {e}")
                # Try fallback with subprocess
                try:
                    subprocess.Popen([str(installer_path)], shell=True)
                    print("Installer launched via subprocess.")
                except Exception as e2:
                    messagebox.showerror("Update Error", f"Failed to start installer: {e}\n\nPlease run it manually from:\n{installer_path}")
                    return
            
            # Allow the update process to start properly before exiting the app
            time.sleep(1)
            
            # Display a final message before exiting
            print("Update process launched successfully. Shutting down application...")
            
            # Get main application instance to call clean shutdown
            main_app = self.app_window  # Use direct reference if provided in constructor
            
            # If no direct reference, try to find it
            if not main_app:
                for widget in tk._default_root.winfo_children():
                    # Look for references to the main application window
                    if hasattr(widget, '_nametowidget'):
                        try:
                            for frame in widget.winfo_children():
                                # Try to find the app instance variable in the parent
                                if hasattr(frame, 'master') and hasattr(frame.master, 'master'):
                                    if hasattr(frame.master.master, 'quit_application'):
                                        main_app = frame.master.master
                                        break
                        except:
                            pass
            
            # Try to properly close via app method if available
            if main_app and hasattr(main_app, 'quit_application'):
                print("Closing using application's quit method...")
                try:
                    main_app.quit_application()
                    # Give time for the app's quit method to complete
                    time.sleep(0.5)
                except Exception as e:
                    print(f"Error in quit_application: {e}")
            elif hasattr(tk, '_default_root') and tk._default_root:
                # Fallback to direct quit/destroy
                print("Closing using tk quit/destroy...")
                try:
                    tk._default_root.quit()
                    tk._default_root.destroy()
                    # Give time for Tk to close
                    time.sleep(0.5)
                except Exception as e:
                    print(f"Error in tk quit/destroy: {e}")
            
            # Clean up any remaining resources
            print("Final cleanup before exit...")
            try:
                # Close any open files
                for handler in list(logging.getLogger().handlers):
                    handler.close()
            except Exception as e:
                print(f"Error in final cleanup: {e}")
            
            # Exit in stages to ensure clean shutdown
            try:
                print("Exiting application...")
                # Try sys.exit first for cleaner exit
                sys.exit(0)
            except SystemExit:
                # This is expected
                pass
            except Exception as e:
                print(f"Error during sys.exit: {e}")
                # Fall back to os._exit as last resort
                os._exit(0)

        except Exception as e:
            messagebox.showerror("Update Error", f"Failed to update: {e}")

    async def check_updates_periodically(self, interval_hours=24):
        """Check for updates periodically"""
        while True:
            await self.check_for_updates()
            await asyncio.sleep(interval_hours * 3600)  # Convert hours to seconds
