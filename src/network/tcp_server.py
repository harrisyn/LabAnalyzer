"""
TCP Server implementation for medical analyzer connections with protocol support
"""
import socket
import logging
import threading
import time
import errno
import queue
import json
from datetime import datetime
from ..utils.analyzers import AnalyzerDefinitions
from ..protocols.astm_parser import ASTMParser
from ..protocols.hl7_parser import HL7Parser
from ..protocols.lis_parser import LISParser
from ..protocols.response_parser import ResponseParser
from ..protocols.cobas_parser import CobasParser
from ..protocols.abbott_parser import AbbottParser
from ..protocols.dimension_parser import DimensionParser
from ..protocols.vitros_parser import VitrosParser
from ..protocols.beckman_parser import BeckmanParser

class TCPServer:
    """TCP Server implementation for medical analyzer connections"""
    
    # Parser mappings using AnalyzerDefinitions constants
    PARSER_MAP = {
        (AnalyzerDefinitions.MINDRAY_BS_430, AnalyzerDefinitions.PROTOCOL_HL7): HL7Parser,
        (AnalyzerDefinitions.HUMACOUNT_5D, AnalyzerDefinitions.PROTOCOL_LIS): LISParser,
        (AnalyzerDefinitions.RESPONSE_920, AnalyzerDefinitions.PROTOCOL_RESPONSE): ResponseParser,
        (AnalyzerDefinitions.ROCHE_COBAS, AnalyzerDefinitions.PROTOCOL_ASTM): CobasParser,
        (AnalyzerDefinitions.SIEMENS_DIMENSION, AnalyzerDefinitions.PROTOCOL_ASTM): DimensionParser,
        (AnalyzerDefinitions.ABBOTT_ARCHITECT, AnalyzerDefinitions.PROTOCOL_POCT1A): AbbottParser,
        (AnalyzerDefinitions.VITROS, AnalyzerDefinitions.PROTOCOL_ASTM): VitrosParser,
        (AnalyzerDefinitions.BECKMAN_AU, AnalyzerDefinitions.PROTOCOL_ASTM): BeckmanParser,
        (AnalyzerDefinitions.SYSMEX_XN_L, AnalyzerDefinitions.PROTOCOL_ASTM): ASTMParser
    }

    def __init__(self, config, db_manager, logger=None, gui_callback=None, sync_manager=None):
        """Initialize the TCP server"""
        self.config = config
        self.db_manager = db_manager
        self.logger = logger or logging.getLogger(__name__)
        self.gui_callback = gui_callback
        self.gui_queue = queue.Queue()
        self._gui_worker_scheduled = False
        
        # Get analyzer type and protocol from config
        self.analyzer_type = self.config.get("analyzer_type", AnalyzerDefinitions.SYSMEX_XN_L)
        self.protocol = self.config.get("protocol", AnalyzerDefinitions.get_protocol_for_analyzer(self.analyzer_type))
        
        self.log_message(f"Initializing server for analyzer: {self.analyzer_type} with protocol: {self.protocol}")
        
        # Select appropriate parser
        self.parser = self._create_parser()
        
        # Set sync manager
        self.sync_manager = sync_manager
        if sync_manager and self.parser:
            self.parser.set_sync_manager(sync_manager)
        
        self.server = None
        self.serve_task = None
        self.clients = {}
        self.is_running = False
        self.server_thread = None
        self.sock = None

    def _create_parser(self):
        """Create appropriate parser based on analyzer type and protocol"""
        parser_class = self.PARSER_MAP.get((self.analyzer_type, self.protocol), ASTMParser)
        
        self.log_message(f"Using parser: {parser_class.__name__}")
        
        # Create parser with configuration
        parser = parser_class(
            self.db_manager, 
            self.logger, 
            gui_callback=self.gui_callback,
            config=self.config
        )
        
        return parser

    def log_message(self, message, level="info"):
        """Log messages to logger and UI in a thread-safe way"""
        if level == "info":
            self.logger.info(message)
        elif level == "error":
            self.logger.error(message)
        elif level == "warning":
            self.logger.warning(message)
        
        # Queue GUI update instead of direct call
        self.queue_gui_update('log', message)

    def queue_gui_update(self, action: str, *args):
        """Queue a GUI update to be processed in the main thread"""
        if self.gui_callback:
            self.gui_queue.put((action, *args))
            self._schedule_gui_worker()

    def _schedule_gui_worker(self):
        """Schedule the GUI worker if not already scheduled"""
        if not self._gui_worker_scheduled and self.gui_callback and hasattr(self.gui_callback, 'root'):
            self.gui_callback.root.after(100, self._process_gui_queue)
            self._gui_worker_scheduled = True

    def _process_gui_queue(self):
        """Process pending GUI updates"""
        if not self.gui_callback or not hasattr(self.gui_callback, 'root'):
            return
            
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
            self.logger.error(f"Error processing GUI queue: {e}")
        finally:
            if self.is_running and self.gui_callback and hasattr(self.gui_callback, 'root'):
                self.gui_callback.root.after(100, self._process_gui_queue)

    def handle_client(self, client_sock, addr):
        """Handle client connection in a separate thread"""
        client_id = f"{addr[0]}:{addr[1]}"
        
        try:
            # Set socket options for better performance
            client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            # Set a reasonable timeout
            client_sock.settimeout(1.0)
            
            # Register new client
            self._register_client(client_id, addr, client_sock)
            
            # Main client loop
            while self.is_running:
                try:
                    # Receive data with timeout
                    data = client_sock.recv(4096)
                    
                    # Check if connection closed
                    if not data:
                        self.log_message(f"Connection closed by {addr[0]}:{addr[1]}")
                        break
                    
                    self.log_message(f"Received {len(data)} bytes from {addr[0]}:{addr[1]}")
                    
                    # Log raw data for debugging (if enabled)
                    if self.config.get("debug_raw_data", False):
                        try:
                            self.log_message(f"Raw data: {data!r}")
                        except Exception:
                            self.log_message(f"Raw data: [Binary data of {len(data)} bytes]")
                    
                    # Let the parser handle the data and get the response
                    # All protocol-specific logic is now in the parser
                    response = self.parser.handle_data(data)
                    
                    # Send the response if one was returned
                    if response:
                        self.log_message(f"Sending response: {response!r}")
                        client_sock.sendall(response)
                    
                except socket.timeout:
                    # Socket timeout - check if still running
                    continue
                except socket.error as e:
                    if e.errno == errno.EWOULDBLOCK:
                        continue
                    elif e.errno == errno.ECONNRESET:
                        self.log_message(f"Connection reset by {addr[0]}:{addr[1]}", level="info")
                        break
                    else:
                        self.log_message(f"Socket error: {e}", level="error")
                        break
                except Exception as e:
                    self.log_message(f"Error handling client data: {e}", level="error")
                    import traceback
                    self.log_message(traceback.format_exc(), level="error")
                    break
        
        except Exception as e:
            self.log_message(f"Error in client handler: {e}", level="error")
        
        finally:
            # Clean up client resources
            try:
                client_sock.close()
                
                # Update client status
                if client_id in self.clients:
                    self.clients[client_id]["status"] = "disconnected"
                    
                self.log_message(f"Client {addr[0]}:{addr[1]} disconnected")
                
                # Queue GUI updates
                self.queue_gui_update('update_connection_count')
                self.queue_gui_update('log_disconnection', addr[0], addr[1])
            except Exception as e:
                self.log_message(f"Error during client cleanup: {e}", level="error")

    def start(self):
        """Start the TCP server"""
        if self.is_running:
            self.log_message("Server is already running")
            return True

        # Set running flag
        self.is_running = True
        
        # Start the server in a separate thread to avoid blocking UI
        self.server_thread = threading.Thread(target=self._run_server)
        self.server_thread.daemon = True
        self.server_thread.start()
        
        # Return immediately to keep UI responsive
        return True

    def _run_server(self):
        """Run server in background thread"""
        try:
            # Log server startup
            port = self.config.get("port", 5000)
            self.log_message(f"Starting server on port {port}...")
            
            # Initialize server socket
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.sock.bind(('0.0.0.0', port))
                self.sock.listen(5)
                self.log_message(f"Server now listening on 0.0.0.0:{port}")
            except OSError as e:
                self.log_message(f"Failed to bind to port {port}: {e}", level="error")
                self.is_running = False
                self.queue_gui_update('server_stopped')
                return False
                
            # Notify GUI of successful startup
            self.queue_gui_update('server_started')
            
            # Set a reasonable timeout to allow checking is_running flag
            self.sock.settimeout(1.0)
            
            # Accept client connections
            while self.is_running:
                try:
                    client_sock, addr = self.sock.accept()
                    self.log_message(f"New client connected from {addr[0]}:{addr[1]}")
                    
                    # Start client handler in a separate thread
                    client_thread = threading.Thread(target=self.handle_client, args=(client_sock, addr))
                    client_thread.daemon = True
                    # Store thread reference in the clients dictionary for proper cleanup
                    client_id = f"{addr[0]}:{addr[1]}"
                    if client_id not in self.clients:
                        self.clients[client_id] = {}
                    self.clients[client_id]["thread"] = client_thread
                    client_thread.start()
                    
                    # Queue GUI update
                    self.queue_gui_update('update_connection_count')
                    self.queue_gui_update('log_connection', addr[0], addr[1])
                    
                except socket.timeout:
                    # This is expected due to the timeout we set
                    continue
                except Exception as e:
                    if self.is_running:  # Only log errors if we're still supposed to be running
                        self.log_message(f"Error accepting connection: {e}", level="error")
            
            self.log_message("Server stopping...")
            return True
            
        except Exception as e:
            self.log_message(f"Server error: {e}", level="error")
            self.is_running = False
            self.queue_gui_update('server_stopped')
            return False

    def stop(self):
        """Stop the TCP server"""
        if not self.is_running:
            return True
            
        self.log_message("Stopping server...")
        self.is_running = False
        
        # Close listening socket
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                self.log_message(f"Error closing server socket: {e}", level="error")
        
        # Close all client connections
        for client_id, client_info in list(self.clients.items()):
            if "socket" in client_info and client_info["socket"]:
                try:
                    client_info["socket"].close()
                except Exception:
                    pass
            # Join client threads for proper cleanup
            if "thread" in client_info and client_info["thread"].is_alive():
                client_info["thread"].join(timeout=2.0)
        
        # Wait for server thread to finish
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2.0)
        
        # Clear client list
        self.clients = {}
        
        # Notify GUI
        self.queue_gui_update('server_stopped')
        
        return True

    def stop_sync(self):
        """Synchronously stop the server - for shutdown"""
        self.stop()

    def _register_client(self, client_id, addr, sock):
        """Register a new client connection"""
        self.clients[client_id] = {
            "address": addr[0],
            "port": addr[1],
            "socket": sock,
            "status": "connected",
            "connected_at": datetime.now().isoformat()
        }
        
        # Update GUI
        self.queue_gui_update('update_connection_count')
        self.queue_gui_update('log_connection', addr[0], addr[1])

    def get_clients(self):
        """Get a list of connected clients"""
        return self.clients

    def _is_port_available(self, port):
        """Check if a port is available for binding"""
        try:
            # Try to create a socket and bind to the port
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            s.bind(('0.0.0.0', port))
            s.close()
            return True
        except Exception:
            return False

    def set_gui_callback(self, callback):
        """Set the GUI callback safely"""
        self.gui_callback = callback
        if hasattr(self, 'parser') and self.parser:
            self.parser.set_gui_callback(callback)

    def is_port_in_use(self, port):
        """Check if the specified port is in use"""
        return not self._is_port_available(port)

    def get_client_count(self):
        """Get the count of active clients"""
        return len([c for c in self.clients.values() if c.get("status") == "connected"])