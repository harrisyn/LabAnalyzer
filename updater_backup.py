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
from datetime import datetime, timedelta

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
            print("Checking for updates...")
            async with aiohttp.ClientSession() as session:
                async with session.get(self.update_url, headers=self._headers) as response:
                    if response.status == 404:
                        # Repository not found - this is expected in development
                        print("Repository not found (404)")
                        return False
                    elif response.status != 200:
                        print(f"GitHub API returned status {response.status}")
                        raise Exception(f"GitHub API returned status {response.status}")                    
                    data = await response.json()
                    latest_version = data['tag_name'].lstrip('v')
                    print(f"Latest version: {latest_version}, Current version: self.current_version")
                    
                    if self._compare_versions(latest_version, self.current_version) > 0:
                        print("New version available")
                        # Look for Windows installer - prioritize direct .exe files
                        windows_asset = None
                        
                        # First, look for direct .exe installer (preferred)
                        for asset in data['assets']:
                            if asset['name'].endswith('.exe') and 'Setup' in asset['name']:
                                windows_asset = asset
                                print(f"Found Windows installer: {asset['name']}")
                                break
                        
                        # Fallback to zip if no direct .exe found (legacy releases)
                        if not windows_asset:
                            windows_asset = next(
                                (asset for asset in data['assets'] 
                                 if asset['name'].startswith('windows') and asset['name'].endswith('.zip')), None
                            )
                            if windows_asset:
                                print(f"Found Windows zip installer: {windows_asset['name']}")
                        
                        if not windows_asset:
                            print("No Windows installer found in the latest release")
                            raise Exception("No Windows installer found in the latest release")
                        
                        if await self._prompt_update(latest_version):
                            print("User accepted update")
                            await self._download_and_install(windows_asset['browser_download_url'])
                            return True  # Update was initiated
                        print("User declined update")
                        return None  # Update available but user declined
                    else:
                        print("No update available")
                        return False  # No update available

        except aiohttp.ClientError as e:
            print(f"Network error checking for updates: {str(e)}")
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
            download_success = False
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
                raise Exception("Downloaded file is empty or missing")

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
                installer_path = download_path
                
            # Verify installer exists
            if not os.path.exists(installer_path):
                raise Exception(f"Installer file missing: {installer_path}")
                
            print(f"Installer ready: {installer_path}")
                
            # Get the main application process ID
            import psutil
            app_pid = os.getpid()
            app_exe = psutil.Process(app_pid).exe()
            app_name = os.path.basename(app_exe)
            
            print(f"Application process: PID={app_pid}, EXE={app_name}")            # Create update batch script with more robust application termination
            batch_path = self.temp_dir / "update.bat"
            
            # Make sure installer path is absolute and quoted properly
            installer_path_str = str(installer_path).replace('"', '""')
            
            with open(batch_path, 'w') as f:
                f.write('@echo off\n')
                f.write('setlocal enabledelayedexpansion\n')
                f.write('color 1F\n')  # Blue background, white text for visibility
                f.write('title LabSync Updater\n')
                f.write('echo LabSync Updater\n')
                f.write('echo ============================\n')
                f.write('echo.\n')
                
                # Make sure this window stays visible
                f.write(':: Make sure this window is visible\n')
                f.write('if not "%minimized%"=="" goto :continue\n')
                f.write('set minimized=true\n')
                f.write('start /max cmd /c "%~dpnx0"\n')
                f.write('exit\n')
                f.write(':continue\n')
                f.write('echo.\n')
                
                # Add a small delay to ensure the parent process has time to exit
                f.write('echo Waiting for application to close...\n')
                f.write('timeout /t 5 /nobreak > nul\n')
                
                # Check if the process is still running by PID
                f.write(f'tasklist /FI "PID eq {app_pid}" 2>nul | find "{app_pid}" >nul\n')
                f.write('if !ERRORLEVEL! EQU 0 (\n')
                f.write(f'    echo Process {app_pid} is still running, attempting to close it...\n')
                f.write(f'    taskkill /F /PID {app_pid} /T > nul 2>&1\n')
                f.write('    if !ERRORLEVEL! NEQ 0 echo Failed to terminate process {app_pid}\n')
                f.write('    timeout /t 2 /nobreak > nul\n')
                f.write(')\n')
                
                # Also look for any instances by executable name
                f.write(f'echo Checking for other instances of {app_name}...\n')
                f.write(f'tasklist /FI "IMAGENAME eq {app_name}" 2>nul | find "{app_name}" >nul\n')
                f.write('if !ERRORLEVEL! EQU 0 (\n')
                f.write(f'    echo Found other instances of {app_name}, attempting to close them...\n')
                f.write(f'    taskkill /F /IM "{app_name}" /T > nul 2>&1\n')
                f.write('    if !ERRORLEVEL! NEQ 0 echo Failed to terminate other instances\n')
                f.write('    timeout /t 2 /nobreak > nul\n')                
                f.write(')\n')
                
                # Run the installer with proper error handling
                f.write('echo.\n')
                f.write(f'echo Launching installer from:\n')
                f.write(f'echo {installer_path_str}\n')
                f.write('echo.\n')
                f.write('echo The installer will now open. Please follow the on-screen instructions.\n')
                f.write('echo This window will wait until the installation is complete.\n')
                f.write('echo.\n')                # Use START to ensure the installer is visible in a new window
                f.write('echo Starting installer. This window will wait until installation is complete.\n')
                f.write('echo.\n')
                f.write(f'start "LabSync Installer" /wait "{installer_path_str}" /CLOSEAPPLICATIONS\n')
                f.write('if !ERRORLEVEL! NEQ 0 (\n')
                f.write('    echo.\n')
                f.write('    echo Installation exited with code !ERRORLEVEL!\n')
                f.write('    echo The installation may have been canceled or encountered an error.\n')
                f.write('    echo.\n')
                f.write('    echo You can try running the installer again manually from:\n')
                f.write(f'    echo {installer_path_str}\n')
                f.write('    echo.\n')
                f.write('    pause\n')
                f.write('    exit /b !ERRORLEVEL!\n')
                f.write(')\n')
                  # Success message
                f.write('echo.\n')
                f.write('echo Installation completed successfully!\n')
                f.write('echo The updated application will start automatically after you close this window.\n')
                f.write('echo.\n')
                f.write('pause\n')
                
                # Try to start the updated application
                f.write('echo Starting updated application...\n')
                f.write('start "" "C:\\Program Files\\LabSync\\LabSync.exe" 2>nul\n')
                f.write('if !ERRORLEVEL! NEQ 0 (\n')
                f.write('    echo Unable to automatically start the application.\n')
                f.write('    echo Please start it manually from the Start Menu.\n')
                f.write(')\n')
                
                # Clean up
                f.write('echo.\n')
                f.write('echo Cleaning up temporary files...\n')
                f.write('timeout /t 2 /nobreak > nul\n')
                f.write('del "%~f0" >nul 2>&1\n')  # Self-delete batch file            # Create the direct installer launcher before showing final message
            direct_launcher_created = self._create_direct_launcher(installer_path)
            
            # Display final message to user with interactive installation instructions
            messagebox.showinfo("Update Ready", 
                                "The update has been downloaded and is ready to install.\n\n"
                                "The application will now close and the installer will open.\n"
                                "Please follow the on-screen instructions to complete the installation.")
                                
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
                            pass            # Launch updater using the Windows 'start' command to ensure visibility
            print(f"Launching update script: {batch_path}")
            
            # Create a direct shortcut to the installer as backup
            shortcut_path = os.path.join(os.path.expanduser("~"), "Desktop", "LabSync Installer.bat")
            try:
                with open(shortcut_path, 'w') as f:
                    f.write('@echo off\n')
                    f.write(f'echo Running LabSync installer from: {installer_path}\n')
                    f.write(f'start "" "{installer_path}"\n')
                    f.write('echo Installation started. You can close this window.\n')
                    f.write('pause\n')
                    f.write('del "%~f0"\n')  # Self-delete
                print(f"Created backup installer shortcut at {shortcut_path}")
            except Exception as e:
                print(f"Could not create backup shortcut: {e}")
            
            # Use the Windows START command which is more reliable for launching visible windows
            try:
                # Method 1: Use START command with "cmd /c start" to force a new visible window
                print("Launching batch file using START command")
                update_process = subprocess.Popen(
                    f'cmd /c start "LabSync Updater" "{batch_path}"',
                    shell=True
                )
                print("Batch file launched successfully")
            except Exception as e:
                print(f"Error launching updater with START command: {e}")
                try:
                    # Method 2: Direct execution as visible console
                    print("Trying direct visible execution")
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = 1  # SW_SHOWNORMAL
                    
                    update_process = subprocess.Popen(
                        str(batch_path),
                        shell=True,
                        startupinfo=startupinfo,
                        creationflags=subprocess.CREATE_NEW_CONSOLE
                    )
                    print("Direct execution launched")
                except Exception as e2:
                    print(f"All launch methods failed: {e2}")
                    messagebox.showerror("Update Error", 
                                        f"Failed to launch update process: {e2}\n\n"
                                        f"You can try running the installer manually from:\n{installer_path}\n\n"
                                        f"A shortcut has been created on your desktop.")
                    # Try to open the installer directly as last resort
                    try:
                        subprocess.Popen(f'start "" "{installer_path}"', shell=True)
                    except:
                        pass
                    return
              # Print update process info for debugging
            if update_process:
                print(f"Started update process with PID: {update_process.pid if hasattr(update_process, 'pid') else 'unknown'}")
            
            # Allow the update process to start properly before exiting the app
            time.sleep(1)
            
            # Display a final message before exiting
            print("Update process launched successfully. Shutting down application...")
            
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
                
                # Detach update process to ensure it continues
                if update_process and hasattr(update_process, 'detach'):
                    update_process.detach()
            except Exception as e:
                print(f"Error in final cleanup: {e}")
              # Exit with a direct method that won't block the update process
            print("Exiting application immediately to let updater continue...")            # Create a final VBS script that both kills this process AND launches the installer
            # This is the most reliable method to ensure the installer runs
            vbs_path = self.temp_dir / "exit_and_install.vbs"
            with open(vbs_path, 'w') as vbs:
                vbs.write('Option Explicit\n')
                vbs.write('Dim WshShell\n')
                vbs.write('Set WshShell = CreateObject("WScript.Shell")\n')
                
                # Kill the application process
                vbs.write('WScript.Sleep 1000\n')  # Wait 1 second
                vbs.write(f'WshShell.Run "taskkill /F /PID {os.getpid()} /T", 0, True\n')
                
                # Wait another second for process to fully terminate
                vbs.write('WScript.Sleep 1000\n')
                
                # Launch the installer directly with proper path escaping
                installer_vbs_path = str(installer_path).replace('\\', '\\\\')
                vbs.write(f'WshShell.Run """{installer_vbs_path}""", 1, False\n')
                vbs.write('Set WshShell = Nothing\n')
            
            # Launch the VBS script silently
            subprocess.Popen(['wscript.exe', str(vbs_path)],
                            shell=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)
              # Give the script a chance to run by waiting briefly
            time.sleep(1.5)
            
        except Exception as e:
            print(f"Update process failed with error: {e}")
            messagebox.showerror("Update Error", f"Failed to update: {e}")
    
    def _create_direct_launcher(self, installer_path):
        """Create a VBS script that will directly launch the installer
        This is a reliable method to ensure the installer appears regardless of how the app exits
        """
        direct_launcher_path = self.temp_dir / "launch_installer.vbs"
        
        # Create three different launch mechanisms to ensure at least one works
        
        # 1. VBS script
        with open(direct_launcher_path, 'w') as f:
            f.write('Option Explicit\n')
            f.write('Dim WshShell, installer_path, fso, desktop_path, shortcut_path\n')
            
            # Properly escape the path
            installer_vbs_path = str(installer_path).replace('\\', '\\\\')
            f.write(f'installer_path = "{installer_vbs_path}"\n')
            f.write('Set WshShell = CreateObject("WScript.Shell")\n')
            
            # Wait for application to close
            f.write('WScript.Sleep 3000\n')  # Wait 3 seconds
            
            # Try different methods to launch the installer
            f.write('On Error Resume Next\n')
            
            # Method 1: Direct Run
            f.write('WshShell.Run """" & installer_path & """", 1, False\n')
            f.write('If Err.Number <> 0 Then\n')
            f.write('    Err.Clear\n')
            
            # Method 2: Through cmd
            f.write('    WshShell.Run "cmd.exe /c start """" """ & installer_path & """", 0, False\n')
            f.write('End If\n')
            
            # Method 3: Create desktop shortcut as fallback
            f.write('If Err.Number <> 0 Then\n')
            f.write('    Err.Clear\n')
            f.write('    Set fso = CreateObject("Scripting.FileSystemObject")\n')
            f.write('    desktop_path = WshShell.SpecialFolders("Desktop")\n')
            f.write('    shortcut_path = fso.BuildPath(desktop_path, "LabSync Installer.lnk")\n')
            f.write('    Set shortcut = WshShell.CreateShortcut(shortcut_path)\n')
            f.write('    shortcut.TargetPath = installer_path\n')
            f.write('    shortcut.Save\n')
            f.write('    WshShell.Popup "The installer has been placed on your desktop.", 10, "LabSync Update", 64\n')
            f.write('End If\n')
            
            f.write('Set WshShell = Nothing\n')
        
        # 2. Create a batch file shortcut on desktop as backup
        try:
            desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
            batch_path = os.path.join(desktop, "Install LabSync Update.bat")
            
            with open(batch_path, 'w') as f:
                f.write('@echo off\n')
                f.write('echo Installing LabSync update...\n')
                f.write(f'start "" "{installer_path}"\n')
                f.write('if errorlevel 1 (\n')
                f.write('    echo Failed to start installer.\n')
                f.write('    echo Please run the installer manually from:\n')
                f.write(f'    echo {installer_path}\n')
                f.write('    pause\n')
                f.write(')\n')
        except Exception as e:
            print(f"Failed to create desktop shortcut: {e}")
        
        # Launch the VBS script now while the app is still running
        print(f"Launching direct installer via VBS: {direct_launcher_path}")
        
        try:
            # Launch with all methods
            subprocess.Popen(['wscript.exe', str(direct_launcher_path)], 
                           shell=True, 
                           creationflags=subprocess.CREATE_NO_WINDOW)
            
            # Also schedule the installer to be launched directly via Windows Task Scheduler
            try:
                # Use a short task name without spaces
                task_name = "LabSyncUpdateInstall"
                # Create a task to run in 5 seconds
                subprocess.Popen([
                    'schtasks', '/create', '/tn', task_name, '/tr',
                    f'"{installer_path}"',
                    '/sc', 'once', '/st', (datetime.now() + timedelta(seconds=5)).strftime('%H:%M:%S'),
                    '/f'  # Force creation
                ], shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception as task_err:
                print(f"Could not schedule task: {task_err}")
            
            return True
        except Exception as e:
            print(f"Failed to create direct launcher: {e}")
            return False    
    async def check_updates_periodically(self, interval_hours=24):
        """Check for updates periodically"""
        while True:
            await self.check_for_updates()
            # Convert hours to seconds
            await asyncio.sleep(interval_hours * 3600)
