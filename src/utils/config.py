"""
Configuration utility for the application
"""
import os
import json
from pathlib import Path

CONFIG_FILE = 'config.json'

class Config:
    def get_config_path(self):
        """Return the path to the config file as a string"""
        return str(self.config_path)
    """
    Handles reading and writing to the application configuration file
    """
    def __init__(self, config_path=None):
        # Use LOCALAPPDATA for persistent config storage
        default_dir = Path(os.getenv('LOCALAPPDATA')) / 'LabSync'
        default_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = config_path or (default_dir / CONFIG_FILE)
        self.config = self._load_config()
    
    def _load_config(self):
        """Load the configuration file or create a default one if it doesn't exist"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                print(f"Error reading config file {self.config_path}, creating default")
                return self._create_default_config()
            except Exception as e:
                print(f"Error loading config: {e}, creating default")
                return self._create_default_config()
        else:
            return self._create_default_config()
    
    def _create_default_config(self):
        """Create a default configuration"""
        return {
            "version": "1.0.0",
            "port": 5000,
            "app_name": "LabSync",
            "instance_id": "LABSYNC-001",
            "analyzer_type": "SYSMEX XN-L",  # Keep this as it's the analyzer model name
            "protocol": "ASTM",
            "auto_start": False,
            "external_server": {
                "enabled": False,
                "url": "https://api.example.com/data",
                "api_key": "",
                "sync_frequency": "scheduled",
                "sync_interval": 15,
                "cron_schedule": "0 * * * *"
            }
        }
    
    def _save_config(self, config=None):
        """Save configuration to file"""
        if config is None:
            config = self.config
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        
        try:
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")
    
    def update(self, **kwargs):
        """Update configuration values"""
        # Handle nested updates for external_server
        if 'external_server' in kwargs:
            current_ext_server = self.config.get('external_server', {})
            current_ext_server.update(kwargs['external_server'])
            self.config['external_server'] = current_ext_server
            del kwargs['external_server']
        
        # Update remaining top-level keys
        self.config.update(kwargs)
        self._save_config()
    
    def get(self, key, default=None):
        """Get a configuration value"""
        # Support nested keys with dot notation (e.g., "external_server.url")
        if '.' in key:
            parts = key.split('.')
            value = self.config
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    return default
            return value if value is not None else default
        return self.config.get(key, default)