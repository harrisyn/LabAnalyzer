import os
import json
import sys
from pathlib import Path

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.utils.config import Config

def test_config_migration():
    print("Testing Config Migration...")
    # Create a dummy legacy config file
    config_path = Path("test_config.json")
    legacy_config = {
        "version": "1.0.0",
        "port": 9999,
        "analyzer_type": "TEST_ANALYZER",
        "protocol": "TEST_PROTOCOL"
    }
    with open(config_path, 'w') as f:
        json.dump(legacy_config, f)
    
    try:
        # Initialize Config with this file
        config = Config(config_path=config_path)
        
        # Check if listeners are populated
        listeners = config.get_listeners()
        print(f"Listeners: {listeners}")
        
        assert len(listeners) == 1
        assert listeners[0]["port"] == 9999
        assert listeners[0]["analyzer_type"] == "TEST_ANALYZER"
        assert listeners[0]["protocol"] == "TEST_PROTOCOL"
        print("Migration Test Passed!")
        
    finally:
        if os.path.exists(config_path):
            os.remove(config_path)

def test_listener_management():
    print("\nTesting Listener Management...")
    config_path = Path("test_config_listeners.json")
    
    try:
        config = Config(config_path=config_path)
        
        # Add a listener
        config.add_listener(8000, "ANALYZER_A", "PROTO_A")
        listeners = config.get_listeners()
        assert len(listeners) >= 1
        found = False
        for l in listeners:
            if l["port"] == 8000:
                assert l["analyzer_type"] == "ANALYZER_A"
                assert l["protocol"] == "PROTO_A"
                found = True
        assert found
        print("Add Listener Passed!")
        
        # Update existing listener
        config.add_listener(8000, "ANALYZER_A_UPDATED", "PROTO_A_UPDATED")
        listeners = config.get_listeners()
        for l in listeners:
            if l["port"] == 8000:
                assert l["analyzer_type"] == "ANALYZER_A_UPDATED"
                assert l["protocol"] == "PROTO_A_UPDATED"
        print("Update Listener Passed!")
        
        # Remove listener
        config.remove_listener(8000)
        listeners = config.get_listeners()
        found = False
        for l in listeners:
            if l["port"] == 8000:
                found = True
        assert not found
        print("Remove Listener Passed!")
        
    finally:
        if os.path.exists(config_path):
            os.remove(config_path)

if __name__ == "__main__":
    test_config_migration()
    test_listener_management()
