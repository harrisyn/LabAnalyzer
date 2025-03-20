"""
TCP Server implementation for medical analyzer connections with protocol support
"""
import asyncio
import socket
import logging
import sys
import threading
import time
import errno
import queue
from datetime import datetime
from tkinter import NORMAL, DISABLED
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
    
    # Control Characters
    ENQ = b'\x05'  # Enquiry
    ACK = b'\x06'  # Acknowledge
    NAK = b'\x15'  # Negative Acknowledge
    EOT = b'\x04'  # End of Transmission
    
    def __init__(self, config, db_manager, logger=None, gui_callback=None, sync_manager=None):
        """Initialize the TCP server"""
        self.config = config
        self.db_manager = db_manager
        self.logger = logger or logging.getLogger(__name__)
        self.gui_callback = gui_callback
        self.gui_queue = queue.Queue()
        self._gui_worker_scheduled = False
        
        # Get analyzer type and protocol from config
        analyzer_type = self.config.get("analyzer_type", "SYSMEX XN-L")
        protocol = self.config.get("protocol", "ASTM").upper()
        
        self.log_message(f"Initializing server for analyzer: {analyzer_type} with protocol: {protocol}")
        
        # Select appropriate parser
        self.parser = self._create_parser(analyzer_type, protocol, db_manager, logger, gui_callback)
        
        self.sync_manager = sync_manager
        if sync_manager and self.parser:
            self.parser.set_sync_manager(sync_manager)
        
        self.server = None
        self.serve_task = None
        self.clients = {}
        self.is_running = False
        self.server_thread = None
        self.sock = None

    # Parser mappings
    PARSER_MAP = {
        ("Mindray BS-430", "HL7"): HL7Parser,
        ("HumaCount 5D", "LIS"): LISParser,
        ("RESPONSE 920", "RESPONSE"): ResponseParser,
        ("Roche Cobas", "ASTM"): CobasParser,
        ("Siemens Dimension", "ASTM"): DimensionParser,
        ("Abbott ARCHITECT", "POCT1A"): AbbottParser,
        ("VITROS", "ASTM"): VitrosParser,
        ("Beckman AU", "ASTM"): BeckmanParser
    }

    def _create_parser(self, analyzer_type, protocol, db_manager, logger, gui_callback):
        """Create appropriate parser based on analyzer type and protocol"""
        parser_class = self.PARSER_MAP.get((analyzer_type, protocol), ASTMParser)
        parser = parser_class(db_manager, logger)
        
        # Set GUI callback using the thread-safe mechanism
        if gui_callback:
            parser.set_gui_callback(gui_callback)
            
        return parser
        
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
                
    def queue_gui_update(self, action: str, *args):
        """Queue a GUI update to be processed in the main thread"""
        if self.gui_callback:
            self.gui_queue.put((action, *args))
            self._schedule_gui_worker()

    def log_message(self, message, level="info"):
        """Log messages to logger and UI in a thread-safe way"""
        if level == "info":
            self.logger.info(message)
        elif level == "error":
            self.logger.error(message)
        
        # Queue GUI update instead of direct call
        self.queue_gui_update('log', message)

    def _cleanup_socket(self, socket_obj):
        """Clean up a socket safely"""
        if socket_obj:
            try:
                socket_obj.shutdown(socket.SHUT_RDWR)
            except (OSError, socket.error):
                pass  # Socket may not be connected
            try:
                socket_obj.close()
            except (OSError, socket.error) as e:
                self.log_message(f"Error closing socket: {e}", level="error")

    def _cleanup_all_clients(self):
        """Close all client connections"""
        for client_id, client in list(self.clients.items()):
            if client["status"] == "connected":
                client_sock = client.get("sock")
                if client_sock:
                    self._cleanup_socket(client_sock)
        self.clients.clear()

    def _initialize_server_socket(self, port):
        """Initialize and bind the server socket"""
        # Create a fresh socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Windows-specific: disable nagle algorithm
        if hasattr(socket, 'TCP_NODELAY'):
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        
        # Add a short delay to ensure previous socket is fully released
        time.sleep(0.1)
        
        # Bind socket
        self.sock.bind(('0.0.0.0', port))
        self.sock.listen(100)
        self.log_message(f"Socket bound successfully to port {port}")

    def start(self):
        """Start the TCP server with improved cleanup for restart scenarios"""
        if self.is_running:
            self.log_message("Server is already running")
            return True

        # Set running flag and start the GUI queue processor
        self.is_running = True
        if self.gui_callback and hasattr(self.gui_callback, 'root'):
            self.gui_callback.root.after(100, self._process_gui_queue)
        
        # Start server thread
        self.server_thread = threading.Thread(target=self._initialize_and_serve)
        self.server_thread.daemon = True
        self.server_thread.start()
        
        # Give the thread a moment to try initialization
        time.sleep(0.1)
        
        # Check if we're still running (no errors occurred)
        if self.is_running:
            self.notify_server_started()
            return True
        return False

    def _initialize_and_serve(self):
        """Initialize socket and start serving in worker thread"""
        try:
            port = self.config.get("port", 5000)
            
            # Check if port is available
            if not self._is_port_available(port):
                self.log_message(f"Port {port} is already in use. Please try a different port.", level="error")
                self.is_running = False
                return
                
            self.log_message(f"Starting server on port {port}...")
            
            # Clean up any existing resources
            self._cleanup_socket(self.sock)
            self.sock = None
            self.clients.clear()
            
            # Initialize new server socket
            try:
                self._initialize_server_socket(port)
                # Queue success message
                self.queue_gui_update('log', f"Socket bound successfully to port {port}")
            except OSError as e:
                self.log_message(f"Failed to bind to port {port}: {e}", level="error")
                self.is_running = False
                return
                
            addr = self.sock.getsockname()
            self.log_message(f"Server now listening on {addr[0]}:{addr[1]}")
            
            # Now begin accepting connections
            self._serve()
            
        except Exception as e:
            self.log_message(f"Unexpected error starting server: {e}", level="error")
            self.is_running = False

    async def stop(self):
        """Stop the TCP server asynchronously"""
        if not self.is_running:
            return True

        try:
            self.log_message("Stopping server asynchronously...")
            self.is_running = False
            
            # Clean up connections
            self._cleanup_all_clients()
            self._cleanup_socket(self.sock)
            self.sock = None
            
            # Wait for server thread
            if self.server_thread and self.server_thread.is_alive():
                await asyncio.sleep(0.5)
            
            self.log_message("Server stopped successfully")
            self.notify_server_stopped()
            return True

        except Exception as e:
            self.log_message(f"Error stopping server: {e}", level="error")
            self.is_running = False
            return False

    def stop_sync(self):
        """Synchronous version of stop for cases where async isn't available"""
        if not self.is_running:
            return True

        try:
            self.log_message("Stopping server (sync)...")
            self.is_running = False
            
            # Clean up connections
            self._cleanup_all_clients()
            self._cleanup_socket(self.sock)
            self.sock = None
            
            # Wait for server thread
            if self.server_thread and self.server_thread.is_alive():
                time.sleep(0.5)
            
            self.log_message("Server stopped successfully (sync)")
            self.notify_server_stopped()
            return True
            
        except Exception as e:
            self.log_message(f"Error stopping server (sync): {e}", level="error")
            self.is_running = False
            return False

    def _is_port_available(self, port):
        """Check if the specified port is available"""
        try:
            # Create a temporary socket to test port availability
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.settimeout(1)
            result = test_socket.connect_ex(('127.0.0.1', port))
            test_socket.close()
            
            # If result is 0, the port is in use
            return result != 0
        except Exception:
            # If there's any error checking, assume port is not available to be safe
            return False
            
    def _serve(self):
        """Background task to keep server running"""
        try:
            # Set a timeout so the loop can regularly check if is_running is still True
            self.sock.settimeout(0.5)  # 500ms timeout
            
            while self.is_running:
                try:
                    client_sock, addr = self.sock.accept()
                    client_thread = threading.Thread(target=self.handle_client, args=(client_sock, addr))
                    client_thread.daemon = True
                    client_thread.start()
                except socket.timeout:
                    # This is expected due to our timeout - just loop again
                    continue
                except OSError as e:
                    # Socket was probably closed - check if we're still supposed to be running
                    if self.is_running:
                        self.log_message(f"Error accepting connection: {e}", level="error")
                    break
        except Exception as e:
            if self.is_running:  # Only log if we weren't intentionally stopped
                self.log_message(f"Error in server task: {e}", level="error")

    def _register_client(self, client_id, addr, client_sock):
        """Register a new client connection"""
        self.clients[client_id] = {
            "address": addr[0],
            "port": addr[1],
            "connected_at": datetime.now().isoformat(),
            "status": "connected",
            "sock": client_sock
        }
        
        self.log_message(f"New client connected from {addr[0]}:{addr[1]}")
        self.gui_queue.put(('update_connection_count',))
        self.gui_queue.put(('log_connection', addr[0], addr[1]))

    def _handle_client_data(self, client_sock, addr, loop):
        """Handle data from a client connection"""
        try:
            data = client_sock.recv(4096)
            if not data:
                return False
            
            self.log_message(f"Received {len(data)} bytes from {addr[0]}:{addr[1]}")
            
            # Check for ENQ immediately before passing to parser
            if data == self.ENQ:
                self.log_message("Received ENQ - sending immediate ACK")
                client_sock.sendall(self.ACK)
                return True
            
            # Process through the selected parser
            if self.parser:
                try:
                    response = loop.run_until_complete(self.parser.process_data(data))
                    if response:
                        client_sock.sendall(response)
                except Exception as e:
                    self.log_message(f"Error processing data: {e}", level="error")
                    client_sock.sendall(self.NAK)
            return True
        except socket.timeout:
            # This is expected due to our timeout
            return True
        except Exception as e:
            if self.is_running:
                self.log_message(f"Error receiving data from {addr[0]}:{addr[1]}: {e}", level="error")
            return False

    def _cleanup_client(self, client_id, addr, client_sock, loop):
        """Clean up client connection resources"""
        client_sock.close()
        self.clients[client_id]["status"] = "disconnected"
        self.log_message(f"Client {addr[0]}:{addr[1]} disconnected")
        
        # Queue GUI updates
        self.gui_queue.put(('update_connection_count',))
        self.gui_queue.put(('log_disconnection', addr[0], addr[1]))
        
        # Close the event loop
        loop.close()

    def handle_client(self, client_sock, addr):
        """Handle client connection in a separate thread"""
        client_id = f"{addr[0]}:{addr[1]}"
        
        # Register new client
        self._register_client(client_id, addr, client_sock)
        
        # Create an event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            client_sock.settimeout(0.5)  # Set timeout for periodic server status check
            while self.is_running:
                if not self._handle_client_data(client_sock, addr, loop):
                    break
        finally:
            self._cleanup_client(client_id, addr, client_sock, loop)

    def notify_server_started(self):
        if self.gui_callback and hasattr(self.gui_callback, 'server_started'):
            self.gui_callback.server_started()

    def notify_server_stopped(self):
        if self.gui_callback and hasattr(self.gui_callback, 'server_stopped'):
            self.gui_callback.server_stopped()

    def get_status(self):
        """Get current server status"""
        if not self.is_running:
            return "Stopped"
        
        active_clients = sum(1 for c in self.clients.values() if c["status"] == "connected")
        return f"Running (Clients: {active_clients})"

    def get_clients(self):
        """Get list of connected clients"""
        return {k: v for k, v in self.clients.items() if v["status"] == "connected"}

    def start_threaded(self):
        """Start the TCP server in a separate thread"""
        server_thread = threading.Thread(target=self.run_server)
        server_thread.daemon = True  # This allows the thread to exit when the main program exits
        server_thread.start()

    def run_server(self):
        """Run the TCP server in the event loop"""
        self.start()  # Now we use the synchronous version which creates its own thread