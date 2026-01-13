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
        (AnalyzerDefinitions.SYSMEX_XN_L, AnalyzerDefinitions.PROTOCOL_ASTM): ASTMParser,
        (AnalyzerDefinitions.SYSMEX_XN_L, AnalyzerDefinitions.PROTOCOL_HL7): HL7Parser
    }

    def __init__(self, config, db_manager, logger=None, gui_callback=None, sync_manager=None):
        """Initialize the TCP server"""
        self.config = config
        self.db_manager = db_manager
        self.logger = logger or logging.getLogger(__name__)
        self.gui_callback = gui_callback
        self.gui_queue = queue.Queue()
        self._gui_worker_scheduled = False
        self._gui_worker_lock = threading.Lock()  # Thread-safe GUI scheduling
        
        # ASTM frame buffers per client for handling partial frames
        self._client_buffers = {}  # client_id -> bytearray
        self._buffer_lock = threading.Lock()
        
        # Determine listeners configuration
        self.listeners_config = self.config.get("listeners", [])
        
        # Backward compatibility: if no listeners defined, use main config
        if not self.listeners_config:
            analyzer_type = self.config.get("analyzer_type", AnalyzerDefinitions.SYSMEX_XN_L)
            protocol = self.config.get("protocol", AnalyzerDefinitions.get_protocol_for_analyzer(analyzer_type))
            port = self.config.get("port", 5000)
            
            self.listeners_config.append({
                "port": port,
                "analyzer_type": analyzer_type,
                "protocol": protocol,
                "name": "Default"
            })
            
        self.log_message(f"Initializing server with {len(self.listeners_config)} listeners")
        
        # Store parsers for each listener/socket
        # Key: local_port, Value: parser instance
        self.parsers = {}
        
        # Initialize parsers for each listener
        for listener in self.listeners_config:
            port = listener.get("port")
            a_type = listener.get("analyzer_type")
            prot = listener.get("protocol")
            
            if port and a_type and prot:
                listener_name = listener.get("name", f"{a_type} on {port}")
                self.parsers[port] = self._create_parser(a_type, prot, port, listener_name)
                self.log_message(f"Configured listener on port {port}: {a_type} ({prot})")

        # For backward compatibility/ease of access, keep a reference to the "default" or first parser
        # This is primarily used by the sync manager or other components that might expect a single parser
        if self.parsers:
            self.parser = list(self.parsers.values())[0] 
        else:
            self.parser = None

        # Set sync manager
        self.sync_manager = sync_manager
        if sync_manager:
            for parser in self.parsers.values():
                parser.set_sync_manager(sync_manager)
        
        self.server_sockets = []
        self.is_running = False
        self.server_thread = None
        self.clients = {}

    def _create_parser(self, analyzer_type, protocol, port=None, listener_name=None):
        """Create appropriate parser based on analyzer type and protocol"""
        # Use arguments passed to the function, NOT self.* properties which might vary per listener
        parser_class = self.PARSER_MAP.get((analyzer_type, protocol), ASTMParser)
        
        self.log_message(f"Creating parser {parser_class.__name__} for {analyzer_type}")
        
        # Create parser with configuration
        # We might want to pass specific config subsets in the future, 
        # but for now passing the global config is fine as parsers check keys like "analyzer_type"
        # However, we should override analyzer_type in the config passed to the parser if possible,
        # or rely on the parser config logic.
        # Since base_parser and others might read config directly, we'll need to ensure they behave correctly.
        # Ideally we'd pass a tailored config object, but for now let's pass the global one 
        # AND manual configuration if the parser supports it.
        
        parser = parser_class(
            self.db_manager, 
            self.logger, 
            gui_callback=self.gui_callback,
            config=self.config
        )
        
        # Set listener info for tracking which listener received data
        if hasattr(parser, 'set_listener_info'):
            parser.set_listener_info(port, listener_name)
        
        # Explicitly configure for the specific analyzer type
        if hasattr(parser, 'configure_for_analyzer'):
            parser.configure_for_analyzer(analyzer_type)
            
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
        """Schedule the GUI worker if not already scheduled - thread-safe"""
        with self._gui_worker_lock:
            if not self._gui_worker_scheduled and self.gui_callback and hasattr(self.gui_callback, 'root'):
                try:
                    self.gui_callback.root.after(100, self._process_gui_queue)
                    self._gui_worker_scheduled = True
                except Exception:
                    # GUI might not be ready yet
                    pass

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
            with self._gui_worker_lock:
                if self.is_running and self.gui_callback and hasattr(self.gui_callback, 'root'):
                    try:
                        self.gui_callback.root.after(100, self._process_gui_queue)
                    except Exception:
                        self._gui_worker_scheduled = False
                else:
                    self._gui_worker_scheduled = False

    def handle_client(self, client_sock, addr, local_port):
        """Handle client connection in a separate thread"""
        client_id = f"{addr[0]}:{addr[1]}"
        
        # Determine which parser to use based on the port the client connected to
        parser = self.parsers.get(local_port, self.parser)
        
        try:
            # Set socket options for better performance
            client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            # Set a reasonable timeout
            client_sock.settimeout(1.0)
            
            # Register new client
            self._register_client(client_id, addr, client_sock, local_port)
            
            # Initialize buffer for this client
            with self._buffer_lock:
                self._client_buffers[client_id] = bytearray()
            
            if parser:
                self.log_message(f"Handling client {client_id} on port {local_port} with {type(parser).__name__}")
            else:
                self.log_message(f"Warning: No specific parser found for port {local_port}, using default")

            # Main client loop
            while self.is_running:
                try:
                    # Receive data with timeout - use larger buffer for ASTM frames
                    data = client_sock.recv(8192)
                    
                    # Check if connection closed
                    if not data:
                        self.log_message(f"Connection closed by {addr[0]}:{addr[1]}")
                        break
                    
                    self.log_message(f"Received {len(data)} bytes from {addr[0]}:{addr[1]}")
                    
                    # Log raw data for debugging (if enabled)
                    if self.config.get("debug_raw_data", False):
                        self._log_raw_data_to_file(data, local_port)
                        try:
                            self.log_message(f"Raw data: {data!r}")
                        except Exception:
                            self.log_message(f"Raw data: [Binary data of {len(data)} bytes]")
                    
                    # Buffer the data and extract complete frames
                    complete_data = self._buffer_data(client_id, data)
                    
                    # Let the parser handle the buffered data and get the response
                    if parser and complete_data:
                        response = parser.handle_data(complete_data)
                        
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
                
                # Clean up buffer for this client
                with self._buffer_lock:
                    if client_id in self._client_buffers:
                        del self._client_buffers[client_id]
                
                # Update client status
                if client_id in self.clients:
                    self.clients[client_id]["status"] = "disconnected"
                    
                self.log_message(f"Client {addr[0]}:{addr[1]} disconnected")
                
                # Queue GUI updates
                self.queue_gui_update('update_connection_count')
                self.queue_gui_update('log_disconnection', addr[0], addr[1])
            except Exception as e:
                self.log_message(f"Error during client cleanup: {e}", level="error")

    def _buffer_data(self, client_id, data):
        """
        Buffer incoming data and return complete ASTM frames.
        
        ASTM frames are delimited by:
        - STX (0x02) at start
        - ETX (0x03) or ETB (0x17) at end
        - Followed by checksum and CR LF
        
        This handles partial frames that may be split across recv() calls.
        
        Args:
            client_id: Client identifier
            data: Raw bytes received
            
        Returns:
            Complete buffered data or None if still waiting for more data
        """
        # ASTM control characters
        STX = 0x02  # Start of Text
        ETX = 0x03  # End of Text
        ETB = 0x17  # End of Block
        EOT = 0x04  # End of Transmission
        ENQ = 0x05  # Enquiry
        ACK = 0x06  # Acknowledge
        NAK = 0x15  # Negative Acknowledge
        CR = 0x0D   # Carriage Return
        LF = 0x0A   # Line Feed
        
        with self._buffer_lock:
            # Get or create buffer for this client
            if client_id not in self._client_buffers:
                self._client_buffers[client_id] = bytearray()
            
            buffer = self._client_buffers[client_id]
            buffer.extend(data)
            
            # Single control characters (ENQ, ACK, NAK, EOT) should be processed immediately
            if len(buffer) == 1:
                if buffer[0] in (ENQ, ACK, NAK, EOT):
                    result = bytes(buffer)
                    buffer.clear()
                    return result
            
            # Check for complete frames
            # Look for frame endings: ETX + checksum + CR + LF or ETB + checksum + CR + LF
            complete_data = bytearray()
            
            while buffer:
                # Handle single control characters at start of buffer
                if buffer[0] in (ENQ, ACK, NAK, EOT):
                    complete_data.append(buffer[0])
                    del buffer[0]
                    continue
                
                # Look for STX
                try:
                    stx_pos = buffer.index(STX)
                except ValueError:
                    # No STX found - might be non-ASTM data or corrupt
                    # Return what we have and clear buffer
                    if buffer:
                        result = bytes(buffer)
                        buffer.clear()
                        return result if complete_data else result
                    break
                
                # Remove any data before STX (shouldn't happen in normal operation)
                if stx_pos > 0:
                    complete_data.extend(buffer[:stx_pos])
                    del buffer[:stx_pos]
                
                # Look for ETX or ETB followed by checksum and CR LF
                frame_end = -1
                for i, byte in enumerate(buffer):
                    if byte in (ETX, ETB):
                        # Need at least 3 more bytes: checksum (2 chars) + CR + LF or just CR+LF
                        # Minimum: ETX + 2 checksum chars + CR + LF = 5 bytes from ETX position
                        # But some devices might not use checksum, look for CR LF
                        min_end = i + 3  # ETX + CR + LF minimum
                        if len(buffer) >= min_end:
                            # Check if we have CR LF after ETX/ETB (possibly with checksum)
                            for j in range(i + 1, min(len(buffer), i + 5)):
                                if j + 1 < len(buffer):
                                    if buffer[j] == CR and buffer[j + 1] == LF:
                                        frame_end = j + 2
                                        break
                                    elif buffer[j] == CR or buffer[j] == LF:
                                        # Some devices use just CR or LF
                                        frame_end = j + 1
                                        break
                            if frame_end > 0:
                                break
                
                if frame_end > 0:
                    # Complete frame found
                    complete_data.extend(buffer[:frame_end])
                    del buffer[:frame_end]
                else:
                    # Incomplete frame - wait for more data
                    break
            
            if complete_data:
                return bytes(complete_data)
            
            # Still waiting for more data
            return None

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
        """Run server in background thread - refactored for multi-port support"""
        import selectors
        sel = selectors.DefaultSelector()
        
        try:
            # Create sockets for each listener
            for listener in self.listeners_config:
                port = int(listener.get("port", 5000))
                name = listener.get('name', 'Unknown')
                
                # specific check for enabled flag
                if "enabled" in listener and not listener["enabled"]:
                    self.log_message(f"Listener on port {port} ({name}) is disabled/paused.")
                    continue

                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    sock.bind(('0.0.0.0', port))
                    sock.listen(5)
                    sock.setblocking(False)
                    
                    # Register with selector
                    sel.register(sock, selectors.EVENT_READ, data=port)
                    
                    self.server_sockets.append(sock)
                    self.log_message(f"Listening on 0.0.0.0:{port} ({name})")
                    
                except OSError as e:
                    self.log_message(f"Failed to bind to port {port}: {e}", level="error")
            
            if not self.server_sockets:
                # If we have listeners configured but all are disabled, this might be intentional.
                # But if NO listeners are configured at all, or binding failed, we stop.
                
                # Check if we have any enabled listeners that failed
                enabled_listeners = [l for l in self.listeners_config if l.get("enabled", True)]
                
                if not enabled_listeners:
                     self.log_message("No enabled listeners configured. Server pausing.", level="warning")
                     # We can keep running effectively doing nothing, or stop.
                     # Original logic stopped. Let's keep it stopping but clarify message.
                else:
                    self.log_message("No sockets opened (all bindings failed). Stopping server.", level="error")
                
                self.is_running = False
                self.queue_gui_update('server_stopped')
                return False

            # Notify GUI of successful startup
            self.queue_gui_update('server_started')
            
            # Main server loop
            while self.is_running:
                try:
                    # Select with timeout to allow checking is_running
                    events = sel.select(timeout=1.0)
                    
                    for key, mask in events:
                        sock = key.fileobj
                        local_port = key.data
                        
                        try:
                            client_sock, addr = sock.accept()
                            self.log_message(f"New client connected from {addr[0]}:{addr[1]} on port {local_port}")
                            
                            # Start client handler in a separate thread
                            client_thread = threading.Thread(target=self.handle_client, args=(client_sock, addr, local_port))
                            client_thread.daemon = True
                            
                            # Store thread reference
                            client_id = f"{addr[0]}:{addr[1]}"
                            if client_id not in self.clients:
                                self.clients[client_id] = {}
                            self.clients[client_id]["thread"] = client_thread
                            client_thread.start()
                            
                            # Queue GUI update
                            self.queue_gui_update('update_connection_count')
                            self.queue_gui_update('log_connection', addr[0], addr[1])
                            
                        except Exception as e:
                            self.log_message(f"Error accepting connection on port {local_port}: {e}", level="error")
                            
                except Exception as e:
                    if self.is_running:
                        self.log_message(f"Selector loop error: {e}", level="error")

            self.log_message("Server stopping...")
            return True
            
        except Exception as e:
            self.log_message(f"Server error: {e}", level="error")
            self.is_running = False
            self.queue_gui_update('server_stopped')
            return False
        finally:
            try:
                sel.close()
            except:
                pass

    def _log_raw_data_to_file(self, data, port):
        """Log raw data to a file for debugging"""
        try:
            import os
            # Use LOCALAPPDATA for log storage
            from pathlib import Path
            default_dir = Path(os.getenv('LOCALAPPDATA')) / 'LabSync' / 'debug_logs'
            default_dir.mkdir(parents=True, exist_ok=True)
            
            filename = default_dir / f"raw_data_port_{port}.log"
            
            with open(filename, 'ab') as f:
                # Write timestamp header
                timestamp = datetime.now().isoformat().encode('utf-8')
                f.write(b'--- ' + timestamp + b' ---\n')
                f.write(data)
                f.write(b'\n')
        except Exception as e:
            self.log_message(f"Error writing raw debug data: {e}", level="error")

    def stop(self):
        """Stop the TCP server"""
        if not self.is_running:
            return True
            
        self.log_message("Stopping server...")
        self.is_running = False
        
        # Close all server sockets
        for sock in self.server_sockets:
            try:
                sock.close()
            except Exception as e:
                self.log_message(f"Error closing server socket: {e}", level="error")
        self.server_sockets = []
        
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

    def _register_client(self, client_id, addr, sock, local_port):
        """Register a new client connection"""
        self.clients[client_id] = {
            "address": addr[0],
            "port": addr[1],
            "local_port": local_port,
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
        # Update callback for all active parsers
        if hasattr(self, 'parsers'):
            for parser in self.parsers.values():
                if parser:
                    parser.set_gui_callback(callback)

    def is_port_in_use(self, port):
        """Check if the specified port is in use"""
        return not self._is_port_available(port)

    def get_client_count(self):
        """Get the count of active clients"""
        return len([c for c in self.clients.values() if c.get("status") == "connected"])

    def reload_config(self):
        """Reload configuration from the config object"""
        self.log_message("Reloading server configuration...")
        
        # Stop everything first if running (though caller should probably stop first)
        was_running = self.is_running
        if was_running:
            self.stop()
            
        # Re-read listeners config
        self.listeners_config = self.config.get("listeners", [])
        
        # Backward compatibility logic
        if not self.listeners_config:
            analyzer_type = self.config.get("analyzer_type", AnalyzerDefinitions.SYSMEX_XN_L)
            protocol = self.config.get("protocol", AnalyzerDefinitions.get_protocol_for_analyzer(analyzer_type))
            port = self.config.get("port", 5000)
            
            self.listeners_config.append({
                "port": port,
                "analyzer_type": analyzer_type,
                "protocol": protocol,
                "name": "Default"
            })
            
        self.log_message(f"Reloaded configuration: {len(self.listeners_config)} listeners")
        
        # Re-initialize parsers
        self.parsers = {}
        for listener in self.listeners_config:
            # Skip disabled listeners
            if "enabled" in listener and not listener["enabled"]:
                continue
                
            port = listener.get("port")
            a_type = listener.get("analyzer_type")
            prot = listener.get("protocol")
            
            if port and a_type and prot:
                listener_name = listener.get("name", f"{a_type} on {port}")
                self.parsers[port] = self._create_parser(a_type, prot, port, listener_name)
        
        # Update default parser reference
        if self.parsers:
            self.parser = list(self.parsers.values())[0] 
        else:
            self.parser = None
            
        # Re-set sync manager on new parsers
        if self.sync_manager:
            for parser in self.parsers.values():
                parser.set_sync_manager(self.sync_manager)

        # Re-set GUI callback on new parsers
        if self.gui_callback:
            self.set_gui_callback(self.gui_callback)
            
        self.log_message("Configuration reload complete")
        
        return True