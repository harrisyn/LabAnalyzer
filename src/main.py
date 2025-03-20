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

# Add src directory to Python path for module imports
sys.path.append(str(Path(os.path.dirname(os.path.abspath(__file__))).parent))

from src.utils.config import Config
from src.utils.logger import Logger
from src.database.db_manager import DatabaseManager
from src.network.tcp_server import TCPServer
from src.network.sync_manager import SyncManager
from src.gui.app_window import ApplicationWindow

# Enable nested event loops
nest_asyncio.apply()

async def setup_application():
    """Initialize application components"""
    config = None
    logger = None
    db_manager = None
    tcp_server = None
    sync_manager = None
    app = None
    root = None
    
    try:
        config = Config()
        logger = Logger(name=config.get("app_name", "XN-L Interface"))
        db_manager = DatabaseManager()
        
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
        
        # Attach GUI callback to server after creation
        tcp_server.gui_callback = app
        
        return root, config, logger, db_manager, tcp_server, sync_manager, app, loop
        
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
        app.update_results()
        app.update_ui_status()  # Changed from update_status to update_ui_status
    except Exception as e:
        app.logger.error(f"Error in GUI update: {e}")
    finally:
        if root.winfo_exists():
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
        root, config, logger, db_manager, tcp_server, sync_manager, app, app_loop = \
            loop.run_until_complete(setup_application())
        
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
    finally:
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