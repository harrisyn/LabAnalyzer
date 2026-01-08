"""
Main entry point for the analyzer interface application
"""
import asyncio
import sys
import os
import tkinter as tk
from pathlib import Path
import nest_asyncio
import threading
import time

# Handle imports for both direct execution and packaged execution
if __package__ is None:
    # Add parent directory to Python path for direct script execution
    package_root = str(Path(__file__).resolve().parent.parent)
    sys.path.insert(0, package_root)
    from src.utils.config import Config
    from src.utils.logger import Logger
    from src.utils.updater import UpdateChecker
    from src.database.db_manager import DatabaseManager
    from src.network.tcp_server import TCPServer
    from src.network.sync_manager import SyncManager
    from src.gui.app_window import ApplicationWindow
    from src.utils.single_instance import SingleInstanceChecker
else:
    # Use relative imports when running as a package
    from .utils.config import Config
    from .utils.logger import Logger
    from .utils.updater import UpdateChecker
    from .database.db_manager import DatabaseManager
    from .network.tcp_server import TCPServer
    from .network.sync_manager import SyncManager
    from .gui.app_window import ApplicationWindow
    from .utils.single_instance import SingleInstanceChecker

# Enable nested event loops
nest_asyncio.apply()

try:
    from src.version import __version__ as build_version
except ImportError:
    build_version = "1.0.0"
async def setup_application():
    """Initialize application components"""
    config = None
    logger = None
    db_manager = None
    tcp_server = None
    sync_manager = None
    app = None
    root = None
    instance_checker = None
    
    try:
        config = Config()
        # Always update config version to match build version
        config.update(version=build_version)

        # Check for existing instance
        app_name = config.get("app_name", "LabSync")
        instance_checker = SingleInstanceChecker(app_name=app_name)
        
        if instance_checker.is_another_instance_running():
            print(f"Another instance of {app_name} is already running.")
            instance_checker.focus_existing_window()
            sys.exit(0)

        logger = Logger(name=app_name)
        logger.info(f"Initializing core application components... Version: {build_version}")

        # Initialize database manager
        db_manager = DatabaseManager()
        logger.info("Database manager initialized")

        # Create Tkinter root window
        root = tk.Tk()

        # Create event loop for the application
        loop = asyncio.get_event_loop()

        # Initialize network components but don't start them yet
        sync_manager = SyncManager(config, db_manager, logger)
        tcp_server = TCPServer(config, db_manager, logger=logger, sync_manager=sync_manager)

        # Create GUI with all components
        app = ApplicationWindow(
            root=root,
            config=config,
            db_manager=db_manager,
            tcp_server=tcp_server,
            sync_manager=sync_manager,
            logger=logger,
            loop=loop
        )

        # Initialize update checker with reference to app window
        updater = UpdateChecker(
            current_version=build_version,
            app_window=app
        )
        # Start update check in background
        asyncio.create_task(updater.check_updates_periodically())

        # Attach GUI callback to server after creation
        tcp_server.gui_callback = app

        # Return instance_checker to keep it alive (holding the socket)
        return root, config, logger, db_manager, tcp_server, sync_manager, app, loop, instance_checker

    except Exception as e:
        # Clean up any created resources on error
        if logger:
            logger.error(f"Error during application setup: {e}")

        # Clean up in reverse order of creation
        if app and root:
            try:
                root.destroy()
            except:
                pass

        if tcp_server:
            try:
                if loop and loop.is_running():
                    loop.run_until_complete(tcp_server.stop())
            except:
                pass

        if db_manager:
            try:
                db_manager.close()
            except:
                pass

        raise  # Re-raise the exception after cleanup

def periodic_gui_update(app, root):
    """Run periodic GUI updates"""
    try:
        # Prevent updates if shutting down
        if getattr(app, 'is_shutting_down', False):
            return
        app.update_results()
        app.update_ui_status()  # Changed from update_status to update_ui_status
    except Exception as e:
        if hasattr(app, 'logger'):
            app.logger.error(f"Error in GUI update: {e}")
    finally:
        if not getattr(app, 'is_shutting_down', False) and root.winfo_exists():
            root.after(1000, lambda: periodic_gui_update(app, root))

def main():
    """Main application entry point"""
    try:
        # Set event loop policy for Windows
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        # Initialize event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Initialize all components
        root, config, logger, db_manager, tcp_server, sync_manager, app, app_loop, instance_checker = \
            loop.run_until_complete(setup_application())

        # Add watchdog timer to detect freezes
        last_update_time = [time.time()]  # Use list for nonlocal access in nested function

        def check_alive():
            current_time = time.time()
            if current_time - last_update_time[0] > 10:  # Over 10 seconds without update
                logger.warning("Possible UI freeze detected - attempting recovery")
                try:
                    # Attempt to process any pending events
                    root.update_idletasks()
                except Exception as e:
                    logger.error(f"Error during freeze recovery: {e}")
            last_update_time[0] = current_time
            if root.winfo_exists():
                root.after(5000, check_alive)

        # Start watchdog after a short delay
        root.after(5000, check_alive)

        # Update function that resets the watchdog timer
        original_update = app.update_results
        def wrapped_update_results():
            last_update_time[0] = time.time()  # Reset watchdog timer
            return original_update()
        app.update_results = wrapped_update_results

        # Schedule first GUI update
        root.after(1000, lambda: periodic_gui_update(app, root))

        # Start Tkinter main loop
        try:
            root.mainloop()
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
        finally:
            # Ensure proper cleanup
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                    try:
                        loop.run_until_complete(task)
                    except asyncio.CancelledError:
                        pass
            except Exception as cleanup_error:
                logger.error(f"Error during task cleanup: {cleanup_error}")

    except Exception as e:
        print(f"Fatal error: {e}")
        if 'logger' in locals():
            logger.error(f"Application error: {e}")
        sys.exit(1)

    # Final cleanup
    if 'db_manager' in locals():
        db_manager.close()
    if 'loop' in locals():
        try:
            loop.stop()
            loop.close()
        except Exception as e:
            print(f"Error closing event loop: {e}")

if __name__ == "__main__":
    main()