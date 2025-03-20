"""
Logging utility for the application
"""
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

class Logger:
    """
    Configurable logger that outputs to both console and file
    """
    def __init__(self, name="labSync", log_level=logging.INFO, log_to_file=True):
        """
        Initialize the logger
        
        Args:
            name: Logger name
            log_level: Minimum log level to record
            log_to_file: Whether to save logs to file
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(log_level)
        self.logger.propagate = False
        
        # Clear any existing handlers
        if self.logger.handlers:
            self.logger.handlers.clear()
            
        # Console handler with colored output
        console_handler = logging.StreamHandler(sys.stdout)
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        # File handler (optional)
        if log_to_file:
            log_dir = Path(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'logs')
            os.makedirs(log_dir, exist_ok=True)
            
            log_file = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)
        
        # Store callbacks for real-time UI updates
        self.ui_callbacks = []
    
    def add_ui_callback(self, callback):
        """Add a callback function for real-time UI updates"""
        if callback not in self.ui_callbacks:
            self.ui_callbacks.append(callback)
            
    def remove_ui_callback(self, callback):
        """Remove a UI callback function"""
        if callback in self.ui_callbacks:
            self.ui_callbacks.remove(callback)
    
    def _notify_ui(self, level, message):
        """Notify UI callbacks of new log message"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for callback in self.ui_callbacks:
            try:
                callback(timestamp, level, message)
            except Exception as e:
                print(f"Error in UI callback: {e}")
    
    def debug(self, message):
        """Log debug message"""
        self.logger.debug(message)
        self._notify_ui("DEBUG", message)
        
    def info(self, message):
        """Log info message"""
        self.logger.info(message)
        self._notify_ui("INFO", message)
        
    def warning(self, message):
        """Log warning message"""
        self.logger.warning(message)
        self._notify_ui("WARNING", message)
        
    def error(self, message):
        """Log error message"""
        self.logger.error(message)
        self._notify_ui("ERROR", message)
        
    def critical(self, message):
        """Log critical message"""
        self.logger.critical(message)
        self._notify_ui("CRITICAL", message)
        
    def get_logger(self):
        """Return the underlying logger object"""
        return self.logger