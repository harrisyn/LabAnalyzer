"""
Unit tests for core functionality
"""
import unittest
import asyncio
import os
import sys
from pathlib import Path
import json

# Add src directory to Python path
sys.path.append(str(Path(os.path.dirname(os.path.abspath(__file__))).parent))

from src.utils.config import Config
from src.database.db_manager import DatabaseManager
from src.protocols.astm_parser import ASTMParser
from src.protocols.scattergram_decoder import ScattergramDecoder
from src.utils.logger import Logger

class TestConfig(unittest.TestCase):
    def setUp(self):
        self.test_config_path = "test_config.json"
        self.config = Config(self.test_config_path)
        
    def tearDown(self):
        if os.path.exists(self.test_config_path):
            os.remove(self.test_config_path)
            
    def test_default_config(self):
        """Test that default configuration is created correctly"""
        self.assertEqual(self.config.get("port"), 5000)
        self.assertEqual(self.config.get("protocol"), "ASTM")
        self.assertFalse(self.config.get("external_server", {}).get("enabled"))
        
    def test_update_config(self):
        """Test configuration update"""
        self.config.update(port=6000)
        self.assertEqual(self.config.get("port"), 6000)

class TestDatabaseManager(unittest.TestCase):
    def setUp(self):
        self.test_db = "test.db"
        self.db = DatabaseManager(self.test_db)
        
    def tearDown(self):
        self.db.close()
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
            
    def test_add_patient(self):
        """Test patient addition"""
        patient_id = self.db.add_patient("TEST001", "Test Patient", "2000-01-01", "M", "Dr. Test")
        self.assertIsNotNone(patient_id)
        
    def test_add_result(self):
        """Test result addition"""
        patient_id = self.db.add_patient("TEST001", "Test Patient", "2000-01-01", "M", "Dr. Test")
        result_id = self.db.add_result(patient_id, "WBC", 10.5, "g/L")
        self.assertIsNotNone(result_id)

class TestASTMParser(unittest.TestCase):
    def setUp(self):
        self.logger = Logger(name="test")
        self.db = DatabaseManager(":memory:")
        self.parser = ASTMParser(self.db, self.logger)
        
    def test_process_patient_record(self):
        """Test patient record processing"""
        record = "P|1||TEST123|123|Doe^John||19800101|M|||||||Dr. Smith"
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.parser.process_record(record))
        
        # Verify patient was added
        patient_id = self.db.get_patient_id_by_patient_id("TEST123")
        self.assertIsNotNone(patient_id)

class TestScattergramDecoder(unittest.TestCase):
    def setUp(self):
        self.logger = Logger(name="test")
        self.decoder = ScattergramDecoder(self.logger)
        
    def test_huffman_tree(self):
        """Test Huffman tree construction"""
        frequencies = {65: 10, 66: 5, 67: 2}
        tree = self.decoder.build_huffman_tree(frequencies)
        self.assertIsNotNone(tree)
        
    def test_rle_decompression(self):
        """Test run-length decoding"""
        # Simple test case: value 65 repeated 3 times
        compressed = bytes([65, 3])
        decompressed = self.decoder.decompress_rle(compressed)
        self.assertEqual(decompressed, bytes([65, 65, 65]))

def run_tests():
    unittest.main()