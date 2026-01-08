"""
Base parser class for handling analyzer protocols
"""
import logging
import queue
import asyncio
from typing import Optional, Dict, Any

class BaseParser:
    """Base class for all protocol parsers"""
    
    def __init__(self, db_manager, logger=None):
        """Initialize the base parser"""
        self.db_manager = db_manager
        self.logger = logger or logging.getLogger(__name__)
        self.buffer = bytearray()
        self.current_raw_record = None
        self.gui_callback = None
        self.gui_queue = queue.Queue()
        self._gui_worker_scheduled = False
        
    def set_gui_callback(self, callback):
        """Set the GUI callback object"""
        self.gui_callback = callback
        if callback and hasattr(callback, 'root'):
            # Start GUI queue processing
            self._schedule_gui_worker()
            
    def _schedule_gui_worker(self):
        """Schedule the GUI worker if not already scheduled"""
        if not self._gui_worker_scheduled and self.gui_callback and hasattr(self.gui_callback, 'root'):
            self.gui_callback.root.after(100, self._process_gui_queue)
            self._gui_worker_scheduled = True
            
    def _process_gui_queue(self):
        """Process pending GUI updates"""
        try:
            while True:
                try:
                    action, *args = self.gui_queue.get_nowait()
                    if hasattr(self.gui_callback, action):
                        method = getattr(self.gui_callback, action)
                        method(*args)
                    self.gui_queue.task_done()
                except queue.Empty:
                    break
        except Exception as e:
            self.log_error(f"Error processing GUI queue: {e}")
        finally:
            if self.gui_callback and hasattr(self.gui_callback, 'root'):
                self.gui_callback.root.after(100, self._process_gui_queue)
                
    def queue_gui_update(self, action: str, *args):
        """Queue a GUI update to be processed in the main thread"""
        if self.gui_callback:
            self.gui_queue.put((action, *args))
            self._schedule_gui_worker()
            
    def log_info(self, message: str):
        """Log an info message"""
        if self.logger:
            self.logger.info(message)
        self.queue_gui_update('log', message)
            
    def log_warning(self, message: str):
        """Log a warning message"""
        if self.logger:
            self.logger.warning(message)
        self.queue_gui_update('log', f"WARNING: {message}")
            
    def log_error(self, message: str):
        """Log an error message"""
        if self.logger:
            self.logger.error(message)
        self.queue_gui_update('log', f"ERROR: {message}")
        
    async def process_data(self, data: bytes) -> Optional[bytes]:
        """Process incoming data - must be implemented by subclasses"""
        raise NotImplementedError("Subclasses must implement process_data")
        
    def update_gui(self, callback_name: str, data: Dict[str, Any]):
        """Update GUI with data in a thread-safe way"""
        if self.gui_callback and hasattr(self.gui_callback, callback_name):
            self.queue_gui_update(callback_name, data)
            
    def clear_buffer(self):
        """Clear the internal buffer"""
        self.buffer.clear()