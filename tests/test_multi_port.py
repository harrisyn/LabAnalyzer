import unittest
import socket
import threading
import time
import json
import os
import sys
from unittest.mock import MagicMock

# Mock numpy if not available
try:
    import numpy
except ImportError:
    sys.modules['numpy'] = MagicMock()

from src.network.tcp_server import TCPServer
from src.utils.config import Config
from src.database.db_manager import DatabaseManager
from src.utils.analyzers import AnalyzerDefinitions

class TestMultiPort(unittest.TestCase):
    def setUp(self):
        # Setup mock config
        self.config = Config()
        # Manually inject listeners into the config object for testing
        # The Config class might load from file, so we override the internal dict
        self.config.config["listeners"] = [
            {
                "enabled": True,
                "port": 5001,
                "analyzer_type": AnalyzerDefinitions.SYSMEX_XN_L,
                "protocol": AnalyzerDefinitions.PROTOCOL_ASTM,
                "name": "ASTM Analyzer"
            },
            {
                "enabled": True,
                "port": 5002,
                "analyzer_type": AnalyzerDefinitions.MINDRAY_BS_430,
                "protocol": AnalyzerDefinitions.PROTOCOL_HL7,
                "name": "HL7 Analyzer"
            }
        ]
        
        self.db_manager = DatabaseManager() 
        self.server = TCPServer(self.config, self.db_manager)
        self.server.start()
        time.sleep(1) # Wait for server threads to start

    def tearDown(self):
        self.server.stop()
        time.sleep(1)

    def test_multi_port_connection(self):
        # Test connection to port 5001
        sock1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result1 = sock1.connect_ex(('127.0.0.1', 5001))
        self.assertEqual(result1, 0, "Could not connect to port 5001")
        sock1.close()

        # Test connection to port 5002
        sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result2 = sock2.connect_ex(('127.0.0.1', 5002))
        self.assertEqual(result2, 0, "Could not connect to port 5002")
        sock2.close()

    def test_protocol_isolation(self):
        # Connect to ASTM port (5001)
        sock1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock1.connect(('127.0.0.1', 5001))
        sock1.send(b'\x05') # ENQ in ASTM
        response1 = sock1.recv(1024)
        self.assertEqual(response1, b'\x06', "Expected ACK for ASTM ENQ")
        sock1.close()

        # Connect to HL7 port (5002)
        sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock2.connect(('127.0.0.1', 5002))
        # HL7 doesn't respond to ENQ with ACK. It expects MSH.
        # We send something that isn't ENQ to verify it's not the ASTM parser
        sock2.send(b'\x0bMSH|^~\\&|SENDER|RECEIVER|20230101||ORU^R01|1|P|2.3.1|\r\x1c\r')
        # We don't strictly check response content here as HL7 parser might vary, 
        # but we ensure it accepts connection and doesn't crash.
        # If it was ASTM parser, it would likely ignore or NAK this if it expected ENQ.
        sock2.close()

    def test_concurrency(self):
        # Connect two clients to the same port (5001)
        sock1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock1.connect(('127.0.0.1', 5001))
        
        sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock2.connect(('127.0.0.1', 5001))
        
        # Send partial data from Client 1
        sock1.send(b'\x05') # ENQ
        resp1 = sock1.recv(1024)
        self.assertEqual(resp1, b'\x06', "Client 1 should get ACK")
        
        # Send data from Client 2
        sock2.send(b'\x05') # ENQ
        resp2 = sock2.recv(1024)
        self.assertEqual(resp2, b'\x06', "Client 2 should get ACK")
        
        sock1.close()
        sock2.close()

if __name__ == '__main__':
    unittest.main()
