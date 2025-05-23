"""
Handles automatic updates for the LabSync application
"""
import os
import sys
import json
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
            async with aiohttp.ClientSession() as session:
                async with session.get(self.update_url, headers=self._headers) as response:
                    if response.status == 404:
                        # Repository not found - this is expected in development
                        return False
                    elif response.status != 200:
                        raise Exception(f"GitHub API returned status {response.status}")                    
                    data = await response.json()
                    latest_version = data['tag_name'].lstrip('v')
                    
                    if self._compare_versions(latest_version, self.current_version) > 0:
                        # Look for Windows installer - prioritize direct .exe files
                        windows_asset = None
                        
                        # First, look for direct .exe installer (preferred)
                        for asset in data['assets']:
                            if asset['name'].endswith('.exe') and 'Setup' in asset['name']:
                                windows_asset = asset
                                break
                        
                        # Fallback to zip if no direct .exe found (legacy releases)
                        if not windows_asset:
                            windows_asset = next(
                                (asset for asset in data['assets'] 
                                 if asset['name'].startswith('windows') and asset['name'].endswith('.zip')), None
                            )
                        
                        if not windows_asset:
                            raise Exception("No Windows installer found in the latest release")
                        
                        if await self._prompt_update(latest_version):
                            await self._download_and_install(windows_asset['browser_download_url'])
                            return True  # Update was initiated
                        return None  # Update available but user declined
                    else:
                        return False  # No update available

        except aiohttp.ClientError as e:
            raise Exception(f"Network error: {str(e)}")
        except Exception as e:
            print(f"Update check failed: {e}")
            raise  # Re-raise for manual check error handling

    def _compare_versions(self, version1, version2):
        """Compare two version strings"""
        v1_parts = [int(x) for x in version1.split('.')]
        v2_parts = [int(x) for x in version2.split('.')]
        
        for i in range(max(len(v1_parts), len(v2_parts))):
            v1 = v1_parts[i] if i < len(v1_parts) else 0
            v2 = v2_parts[i] if i < len(v2_parts) else 0
            if v1 > v2:
                return 1
            if v1 < v2:
                return -1
        return 0
        
    async def _prompt_update(self, new_version):
        """Show update prompt to user"""
        return messagebox.askyesno(
            "Update Available",
            f"Version {new_version} is available. Would you like to update now?"
        )
        
    async def _download_and_install(self, download_url):
        """Download and install the new version"""
        try:
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
            except:
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
                        
                        with open(download_path, 'wb') as f:
                            async for chunk in response.content.iter_chunked(chunk_size):
                                f.write(chunk)
                                downloaded += len(chunk)
                                percentage = min(100.0, downloaded * 100 / total_size)
                                
                                # Calculate download speed and ETA
                                mb_downloaded = downloaded / (1024 * 1024)
                                mb_total = total_size / (1024 * 1024)
                                message = f"Downloaded: {mb_downloaded:.1f} MB of {mb_total:.1f} MB ({percentage:.1f}%)"
                                
                                # Update progress every ~20ms to avoid UI freezing
                                update_progress(percentage, message)
                    
            # Update status before extraction
            update_progress(100, "Download complete. Preparing installer...")
            
            # Close progress dialog
            progress_window.destroy()

            # Handle zip extraction if needed
            if is_zip:
                with zipfile.ZipFile(download_path, 'r') as zip_ref:
                    zip_ref.extractall(self.temp_dir)
                
                # Find the .exe file in the extracted contents
                exe_files = list(self.temp_dir.glob("**/*.exe"))
                if not exe_files:
                    raise Exception("No .exe installer found in the downloaded zip")
                
                installer_path = exe_files[0]  # Use the first .exe found
            else:
                installer_path = download_path            # Get the main application process ID
            import psutil
            app_pid = os.getpid()
            app_exe = psutil.Process(app_pid).exe()
            app_name = os.path.basename(app_exe)
            
            # Create update batch script with more robust application termination
            batch_path = self.temp_dir / "update.bat"
            with open(batch_path, 'w') as f:
                f.write('@echo off\n')
                f.write('echo Waiting for application to close...\n')
                
                # Wait for the specific process ID to end
                f.write(f'echo Waiting for process ID {app_pid} to end\n')
                f.write(f'timeout /t 3 /nobreak > nul\n')
                
                # Force kill the process if it's still running (should not be needed)
                f.write(f'taskkill /F /PID {app_pid} /T > nul 2>&1\n')
                
                # Just to be super safe, also close any lingering instances by name
                f.write(f'taskkill /F /IM "{app_name}" /T > nul 2>&1\n')
                
                # Wait a bit more to ensure everything is closed
                f.write('timeout /t 2 /nobreak > nul\n')
                
                # Run the installer with CLOSEAPPLICATIONS flag to make it force-close any running instances 
                f.write(f'echo Installing update from {installer_path}...\n')
                f.write(f'start "" /wait "{installer_path}" /VERYSILENT /NORESTART /CLOSEAPPLICATIONS /FORCECLOSEAPPLICATIONS\n')
                
                # Clean up
                f.write('echo Update completed.\n')
                f.write('del "%~f0"\n')  # Self-delete batch file

            # Display final message to user
            messagebox.showinfo("Update Ready", 
                                "The update has been downloaded and will now be installed. "
                                "The application will close during installation.")
                                  # Close all toplevel windows
            for widget in tk._default_root.winfo_children():
                if isinstance(widget, tk.Toplevel):
                    widget.destroy()
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
                        
            # Launch updater as detached process
            update_process = subprocess.Popen([str(batch_path)], shell=True, 
                               creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS)
                               
            # Try to properly close via app method if available
            if main_app and hasattr(main_app, 'quit_application'):
                main_app.quit_application()
            elif hasattr(tk, '_default_root') and tk._default_root:
                # Fallback to direct quit/destroy
                try:
                    tk._default_root.quit()
                    tk._default_root.destroy()
                except:
                    pass
                    
            # Give a short delay for clean shutdown
            time.sleep(0.5)
                
            # Exit the application forcefully as final resort
            os._exit(0)

        except Exception as e:
            messagebox.showerror("Update Error", f"Failed to update: {e}")

    async def check_updates_periodically(self, interval_hours=24):
        """Check for updates periodically"""
        while True:
            await self.check_for_updates()
            await asyncio.sleep(interval_hours * 3600)  # Convert hours to seconds
