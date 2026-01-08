"""
Configuration utility for the application
"""
import os
import json
from pathlib import Path

CONFIG_FILE = 'config.json'

class Config:
    """
    Handles reading and writing to the application configuration file
    """
    def __init__(self, config_path=None):
        # Use LOCALAPPDATA for persistent config storage
        default_dir = Path(os.getenv('LOCALAPPDATA')) / 'LabSync'
        default_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = config_path or (default_dir / CONFIG_FILE)
        self.config = self._load_config()

    def get_config_path(self):
        """Return the path to the config file as a string"""
        return str(self.config_path)
    
    def _load_config(self):
        """Load the configuration file or create a default one if it doesn't exist"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
                    # Ensure backward compatibility or migration if needed
                    return self._migrate_config(config)
            except json.JSONDecodeError:
                print(f"Error reading config file {self.config_path}, creating default")
                return self._create_default_config()
            except Exception as e:
                print(f"Error loading config: {e}, creating default")
                return self._create_default_config()
        
        return self._create_default_config()

    def _create_default_config(self):
        """Create and save a default configuration"""
        config = {
            "version": "1.0.0",
            "app_name": "LabSync",
            "instance_id": "LABSYNC-001",
            "listeners": [
                {
                    "port": 5000,
                    "analyzer_type": "SYSMEX XN-L",
                    "protocol": "ASTM"
                }
            ],
            # Legacy support (optional, but good for transition)
            "port": 5000,
            "analyzer_type": "SYSMEX XN-L",
            "protocol": "ASTM",
            
            "auto_start": False,
            "external_server": {
                "enabled": True,
                "url": "https://api.staging.serenity.health/v2/emr/lab-analyzer-results",
                "api_key": "",
                "sync_frequency": "realtime",
                "cron_schedule": "0 * * * *",
                "retry_interval": 60,
                "http_method": "POST",
                "auth_method": "api_key",
                "api_key_header": "X-API-Key"
            }
        }
        self._save_config_to_file(config)
        return config

    def _migrate_config(self, config):
        """Migrate legacy config to new format if needed"""
        if "listeners" not in config:
            # Create listeners from legacy fields if they exist
            if "port" in config:
                config["listeners"] = [
                    {
                        "port": config.get("port", 5000),
                        "analyzer_type": config.get("analyzer_type", "SYSMEX XN-L"),
                        "protocol": config.get("protocol", "ASTM")
                    }
                ]
            else:
                config["listeners"] = []
        return config

    def _save_config(self):
        """Save the current configuration to file"""
        self._save_config_to_file(self.config)

    def _save_config_to_file(self, config):
        """Helper to write config to disk"""
        try:
            # Create directory if it doesn't exist
            dirname = os.path.dirname(self.config_path)
            if dirname:
                os.makedirs(dirname, exist_ok=True)
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

    def get_listeners(self):
        """Get the list of configured listeners"""
        return self.config.get("listeners", [])

    def add_listener(self, port, analyzer_type, protocol):
        """Add a new listener configuration"""
        listeners = self.get_listeners()
        # Check if port already exists
        for listener in listeners:
            if listener["port"] == port:
                # Update existing
                listener["analyzer_type"] = analyzer_type
                listener["protocol"] = protocol
                self._save_config()
                return
        
        # Add new
        listeners.append({
            "port": port,
            "analyzer_type": analyzer_type,
            "protocol": protocol
        })
        self.config["listeners"] = listeners
        self._save_config()

    def remove_listener(self, port):
        """Remove a listener by port"""
        listeners = self.get_listeners()
        self.config["listeners"] = [l for l in listeners if l["port"] != port]
        self._save_config()