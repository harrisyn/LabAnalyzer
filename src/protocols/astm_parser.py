"""
ASTM Protocol Parser for Medical Analyzers
"""
from datetime import datetime
import re
import asyncio
import queue
import threading
import json
from typing import Optional, Dict, Any, List, Tuple
from .base_parser import BaseParser
from .scattergram_decoder import ScattergramDecoder

class ASTMParser(BaseParser):
    """
    Parser for ASTM protocol data from medical analyzers
    
    This class handles all ASTM-specific communication and parsing logic,
    including complete message collection, framing, and acknowledgment.
    """
    # ASTM Control Characters
    STX = b'\x02'  # Start of Text
    ETX = b'\x03'  # End of Text
    EOT = b'\x04'  # End of Transmission
    ENQ = b'\x05'  # Enquiry
    ACK = b'\x06'  # Acknowledge
    NAK = b'\x15'  # Negative Acknowledge
    ETB = b'\x17'  # End of Transmission Block
    LF = b'\x0A'   # Line Feed
    CR = b'\x0D'   # Carriage Return
    CRLF = CR + LF
    
    # Record Type Identifiers
    RECORD_TYPES = {
        'H': 'Header',
        'P': 'Patient',
        'O': 'Order',
        'R': 'Result',
        'C': 'Comment',
        'Q': 'Query',
        'L': 'Terminator'
    }
    
    def __init__(self, db_manager, logger, gui_callback=None, config=None):
        """
        Initialize the parser
        
        Args:
            db_manager: DatabaseManager instance for storing parsed data
            logger: Logger instance for logging events
            gui_callback: Optional callback function for GUI updates
            config: Configuration dictionary for parser-specific settings
        """
        super().__init__(db_manager, logger)
        self.config = config or {}
        self.sync_manager = None
        self.gui_callback = gui_callback
        
        # Message collection and processing
        self.current_message_frames = []
        self.collecting_message = False
        self.full_raw_payload = ""
        self.message_counter = 0
        
        # Initialize the scattergram decoder if needed
        self.scattergram_decoder = ScattergramDecoder(logger)
        
        # Configure parser based on analyzer type
        self.analyzer_type = self.config.get("analyzer_type", "GENERIC")
        self.configure_for_analyzer(self.analyzer_type)
        
    def configure_for_analyzer(self, analyzer_type):
        """Configure parser settings based on analyzer type"""
        self.log_info(f"Configuring ASTM parser for analyzer type: {analyzer_type}")
        
        # Default field positions (can be overridden by analyzer-specific settings)
        self.field_positions = {
            "patient_id": 4,       # Field 5 (0-indexed)
            "sample_id": 3,        # Field 4 (0-indexed)
            "patient_name": 5,     # Field 6 (0-indexed)
            "date_of_birth": 7,    # Field 8 (0-indexed)
            "sex": 8,              # Field 9 (0-indexed)
            "physician": 12,       # Field 13 (0-indexed)
            
            # Result record field positions
            "result_sequence": 1,  # Field 2 (0-indexed)
            "result_test_code": 2, # Field 3 (0-indexed)
            "result_value": 3,     # Field 4 (0-indexed)
            "result_unit": 4,      # Field 5 (0-indexed)
            "result_flag": 6,      # Field 7 (0-indexed)
        }
        
        # Analyzer-specific configurations
        if analyzer_type == "SYSMEX XN-L" or analyzer_type == "SYSMEX XN-550":
            # SYSMEX specific test code pattern
            self.test_code_pattern = r'\^\^\^\^([A-Za-z0-9\#\_\-\/\?]+)'
            # Special configuration for SYSMEX
            self.field_positions.update({
                "patient_id": 4,        # Field 5 (0-indexed) - 1418626
                "sample_id": 3,         # Field 4 (0-indexed) - if empty, use patient_id
                "patient_name": 5,      # Field 6 (0-indexed) - ^FAABAR^AHITOPHEL
                "date_of_birth": 7,     # Field 8 (0-indexed) - 19830101
                "sex": 8,               # Field 9 (0-indexed) - M
                "physician": 14,        # Field 15 (0-indexed) - ^
            })
        elif analyzer_type == "ROCHE COBAS":
            # Different test code pattern for COBAS
            self.test_code_pattern = r'([A-Za-z0-9]+)\^'
        else:
            # Generic pattern for most ASTM implementations
            self.test_code_pattern = r'\^\^\^\^([A-Za-z0-9\#\_\-\/\?]+)'
    
    def set_sync_manager(self, sync_manager):
        """Set the sync manager for real-time synchronization"""
        self.sync_manager = sync_manager
        self.log_info("Sync manager connected to ASTM parser")
    
    def set_gui_callback(self, callback):
        """Set the GUI callback safely"""
        self.gui_callback = callback
    
    def handle_data(self, data: bytes) -> bytes:
        """
        Main entry point for handling data from TCP server
        
        Args:
            data: Raw bytes received from the analyzer
            
        Returns:
            Response bytes to send back to the analyzer (ACK, NAK, or None)
        """
        try:
            # Log the raw data received
            self.log_info(f"Received {len(data)} bytes: {data!r}")
            
            # Handle ASTM control characters
            if data == self.ENQ:
                # Analyzer is initiating communication
                self.log_info("Received ENQ (Enquiry)")
                self.collecting_message = True
                self.current_message_frames = []
                return self.ACK  # Respond with ACK
                
            elif data == self.EOT:
                # End of transmission - process the complete message
                self.log_info("Received EOT (End of Transmission)")
                
                if self.collecting_message and self.current_message_frames:
                    # Process the complete message
                    self._process_complete_message()
                    
                # Reset collection state
                self.collecting_message = False
                self.current_message_frames = []
                return None  # No response needed
            
            # Handle ASTM framed data (STX...ETX)
            if data.startswith(self.STX) and (self.ETX in data or self.ETB in data):
                try:
                    # Find the position of the end marker
                    end_marker = self.ETX if self.ETX in data else self.ETB
                    end_pos = data.index(end_marker)
                    
                    # Extract frame content between STX and ETX/ETB
                    frame_content = data[1:end_pos].decode('ascii', errors='replace')
                    
                    # Log frame information
                    record_type = "Unknown"
                    if len(frame_content) >= 2:
                        record_type_char = frame_content[1] if frame_content[0].isdigit() else frame_content[0]
                        if record_type_char in self.RECORD_TYPES:
                            record_type = self.RECORD_TYPES.get(record_type_char, "Unknown")
                    
                    self.log_info(f"Received ASTM {record_type} frame - sending immediate ACK")
                    self.log_info(f"Frame content: {frame_content}")
                    
                    # If collecting a message, add this frame
                    if self.collecting_message:
                        self.current_message_frames.append(frame_content)
                        
                    # Always ACK the frame
                    return self.ACK
                    
                except Exception as e:
                    self.log_error(f"Error processing ASTM frame: {e}")
                    # Send NAK on error
                    return self.NAK
            
            # Return None if no specific response is needed
            return None
            
        except Exception as e:
            import traceback
            self.log_error(f"Error in ASTM data handling: {e}\n{traceback.format_exc()}")
            # Return NAK to indicate error
            return self.NAK
    
    def _process_complete_message(self):
        """Process a complete ASTM message after all frames are received"""
        try:
            self.message_counter += 1
            message_id = f"MSG{self.message_counter}"
            
            self.log_info(f"Processing complete message {message_id} with {len(self.current_message_frames)} frames")
            
            # Create the raw payload
            self.full_raw_payload = "\n".join(self.current_message_frames)
            
            # Log the complete raw message payload
            self.log_info(f"Complete raw message payload ({len(self.full_raw_payload)} bytes):")
            self.log_info(self.full_raw_payload)
            
            # Extract message information
            message_info = self._extract_message_info()
            
            # Add the raw payload to the message info
            message_info['raw_payload'] = self.full_raw_payload
            
            # Process extracted information in a background thread
            processing_thread = threading.Thread(
                target=self._background_process_message,
                args=(message_info,)
            )
            processing_thread.daemon = True
            processing_thread.start()
            
            return True
        except Exception as e:
            import traceback
            self.log_error(f"Error processing complete message: {e}\n{traceback.format_exc()}")
            return False
    
    def _extract_message_info(self) -> Dict[str, Any]:
        """
        Extract patient and result information from the message frames
        
        Returns:
            Dictionary containing patient information and test results
        """
        # Initialize message info
        message_info = {
            'patient_id': None,
            'patient_name': None,
            'dob': None,
            'sex': None,
            'physician': None,
            'sample_id': None,
            'results': [],
            'timestamp': datetime.now().isoformat()
        }
        
        # First pass: Process each frame to extract patient info and result info
        for frame in self.current_message_frames:
            try:
                # Parse the record type and fields
                fields = frame.split('|')
                if not fields or len(fields[0]) < 1:
                    continue
                
                record_type = fields[0][-1] if fields[0][-1].isalpha() else None
                
                # Extract patient info from Patient (P) record
                if record_type == 'P':
                    self._extract_patient_info(fields, message_info)
                
                # Extract test info from Result (R) records
                elif record_type == 'R':
                    self._extract_result_info(fields, message_info)
            
            except Exception as e:
                self.log_error(f"Error extracting info from frame: {e}")
                continue
        
        # Second pass: If patient_id is still None, try to get it from O record
        if not message_info['patient_id']:
            self.log_info("No patient ID found in P record, checking O record")
            for frame in self.current_message_frames:
                fields = frame.split('|')
                if not fields or len(fields[0]) < 1:
                    continue
                
                record_type = fields[0][-1] if fields[0][-1].isalpha() else None
                
                if record_type == 'O':
                    self._extract_patient_id_from_order(fields, message_info)

        return message_info
    
    def _extract_patient_info(self, fields: List[str], message_info: Dict[str, Any]):
        """Extract patient information from P record fields"""
        try:
            # Get field positions from configuration
            patient_id_pos = self.field_positions["patient_id"]
            sample_id_pos = self.field_positions["sample_id"]
            name_pos = self.field_positions["patient_name"]
            dob_pos = self.field_positions["date_of_birth"]
            sex_pos = self.field_positions["sex"]
            physician_pos = self.field_positions["physician"]
            
            # Extract patient ID
            if len(fields) > patient_id_pos and fields[patient_id_pos]:
                message_info['patient_id'] = fields[patient_id_pos].strip()
            
            # Extract sample ID
            if len(fields) > sample_id_pos and fields[sample_id_pos]:
                message_info['sample_id'] = fields[sample_id_pos].strip()
            # If sample ID is not available, use patient ID as fallback
            if not message_info['sample_id'] and message_info['patient_id']:
                message_info['sample_id'] = message_info['patient_id']
            
            # Extract name - handle different ASTM name formats
            if len(fields) > name_pos and fields[name_pos]:
                name_parts = fields[name_pos].split('^')
                
                # Log name parts for debugging
                self.log_info(f"Name parts: {name_parts}")
                
                if self.analyzer_type in ["SYSMEX XN-L", "SYSMEX XN-550"]:
                    # SYSMEX format: ^LASTNAME^FIRSTNAME
                    if len(name_parts) >= 3:
                        patient_name = f"{name_parts[2]} {name_parts[1]}".strip()
                        if patient_name:
                            message_info['patient_name'] = patient_name
                    elif len(name_parts) == 2:
                        # Fallback if format is unexpected
                        patient_name = f"{name_parts[1]}".strip()
                        if patient_name:
                            message_info['patient_name'] = patient_name
                    else:
                        # Just use what we have
                        message_info['patient_name'] = fields[name_pos].strip()
                else:
                    # Generic handling for other analyzers
                    if len(name_parts) >= 3:
                        # Format: ^LASTNAME^FIRSTNAME or FIRSTNAME^LASTNAME^SUFFIX
                        patient_name = f"{name_parts[2]} {name_parts[1]}".strip()
                        if patient_name:
                            message_info['patient_name'] = patient_name
                    elif len(name_parts) == 2:
                        # Format: LASTNAME^FIRSTNAME
                        patient_name = f"{name_parts[1]} {name_parts[0]}".strip()
                        if patient_name:
                            message_info['patient_name'] = patient_name
                    else:
                        # Just use what we have
                        message_info['patient_name'] = fields[name_pos].strip()
            
            # Extract DOB in YYYYMMDD format
            if len(fields) > dob_pos and fields[dob_pos]:
                dob = fields[dob_pos].strip()
                if len(dob) == 8 and dob.isdigit():
                    # Format as YYYY-MM-DD
                    try:
                        message_info['dob'] = f"{dob[0:4]}-{dob[4:6]}-{dob[6:8]}"
                    except Exception:
                        message_info['dob'] = dob
                else:
                    message_info['dob'] = dob
            
            # Extract sex
            if len(fields) > sex_pos and fields[sex_pos]:
                sex = fields[sex_pos].strip().upper()
                if sex in ['M', 'F', 'U', 'O']:
                    message_info['sex'] = sex
                else:
                    message_info['sex'] = 'U'  # Unknown
            
            # Extract physician
            if len(fields) > physician_pos and fields[physician_pos]:
                message_info['physician'] = fields[physician_pos].strip()
            
            self.log_info(f"Extracted patient info: {json.dumps({k: v for k, v in message_info.items() if k != 'results'})}")
            
        except Exception as e:
            import traceback
            self.log_error(f"Error extracting patient info: {e}\n{traceback.format_exc()}")
    
    def _extract_result_info(self, fields: List[str], message_info: Dict[str, Any]):
        """Extract test results from R record fields"""
        try:
            # Get field positions from configuration
            seq_pos = self.field_positions["result_sequence"]
            test_code_pos = self.field_positions["result_test_code"]
            value_pos = self.field_positions["result_value"]
            unit_pos = self.field_positions["result_unit"]
            flag_pos = self.field_positions["result_flag"]
            
            # Create a result object
            result = {
                'test_code': None,
                'value': None,
                'unit': None,
                'flags': None,
                'sequence': fields[seq_pos] if len(fields) > seq_pos else "0"
            }
            
            # Extract test code using the configured pattern
            if len(fields) > test_code_pos:
                test_code_complex = fields[test_code_pos]
                test_code_match = re.search(self.test_code_pattern, test_code_complex)
                if test_code_match:
                    result['test_code'] = test_code_match.group(1)
                else:
                    result['test_code'] = test_code_complex.strip()
            
            # Extract value, unit and flags
            if len(fields) > value_pos:
                result['value'] = fields[value_pos].strip()
            
            if len(fields) > unit_pos:
                result['unit'] = fields[unit_pos].strip()
            
            if len(fields) > flag_pos:
                result['flags'] = fields[flag_pos].strip()
            
            # Add to results array
            message_info['results'].append(result)
            
            self.log_info(f"Extracted result: {json.dumps(result)}")
            
        except Exception as e:
            self.log_error(f"Error extracting result info: {e}")
    
    def _extract_patient_id_from_order(self, fields: List[str], message_info: Dict[str, Any]):
        """
        Extract patient ID from O record fields when it's not found in the P record
        
        Format examples:
        - "^^                475371^M" (patient ID is 475371)
        - Other ASTM O record formats with patient ID embedded
        """
        try:
            # First, try standard field that often contains patient ID in O records
            # This is typically field 4 in O records (index 3)
            if len(fields) > 3 and fields[3]:
                # Parse the complex field value to extract the patient ID
                # Common format: ^^                PATIENT_ID^X
                order_field = fields[3].strip()
                
                # Log the raw field for debugging
                self.log_info(f"Attempting to extract patient ID from O record field: '{order_field}'")
                
                # Try to extract using regex - looking for numeric ID typically after spaces or ^ characters
                patient_id_match = re.search(r'\^+\s*(\d+)', order_field)
                if patient_id_match:
                    patient_id = patient_id_match.group(1).strip()
                    if patient_id:
                        message_info['patient_id'] = patient_id
                        self.log_info(f"Extracted patient ID from O record: {patient_id}")
                        return
                
                # Try alternative approach - split by ^ and find a numeric component
                parts = order_field.split('^')
                for part in parts:
                    part = part.strip()
                    if part and part.isdigit():
                        message_info['patient_id'] = part
                        self.log_info(f"Extracted patient ID from O record (alternative method): {part}")
                        return
            
            # If the above methods don't work, try the same field position as in P records
            patient_id_pos = self.field_positions["patient_id"]
            if len(fields) > patient_id_pos and fields[patient_id_pos]:
                patient_id = fields[patient_id_pos].strip()
                if patient_id:
                    message_info['patient_id'] = patient_id
                    self.log_info(f"Extracted patient ID from O record standard position: {patient_id}")
                    return
                    
        except Exception as e:
            self.log_error(f"Error extracting patient ID from O record: {e}")
            import traceback
            self.log_error(traceback.format_exc())
    
    def _background_process_message(self, message_info: Dict[str, Any]):
        """Process the complete message in a background thread"""
        try:
            self.log_info(f"Background thread: Processing message for patient {message_info['patient_id']}")
            
            # Skip processing if no patient ID found
            if not message_info['patient_id']:
                self.log_warning("No patient ID found in message - skipping processing")
                return
            
            # 1. First, store the patient in the database
            try:
                patient_db_id = self.db_manager.add_patient(
                    message_info['patient_id'],
                    message_info['patient_name'],
                    message_info['dob'],
                    message_info['sex'],
                    message_info['physician'],
                    message_info['raw_payload'],
                    message_info['sample_id'],
                    listener_port=self.listener_port,
                    listener_name=self.listener_name
                )
                
                self.log_info(f"Patient stored with DB ID: {patient_db_id}")
                
                # Update UI if callback exists
                if self.gui_callback and hasattr(self.gui_callback, 'update_patient_info'):
                    # Add database ID to the info
                    patient_info = {
                        'db_id': patient_db_id,
                        'patient_id': message_info['patient_id'],
                        'patient_name': message_info['patient_name'],
                        'date_of_birth': message_info['dob'],
                        'sex': message_info['sex'],
                        'physician': message_info['physician'],
                        'sample_id': message_info['sample_id']
                    }
                    
                    # Use call_soon_threadsafe for thread safety
                    try:
                        loop = asyncio.get_event_loop()
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        
                    loop.call_soon_threadsafe(
                        lambda: self.gui_callback.update_patient_info(patient_info)
                    )
            
            except Exception as e:
                self.log_error(f"Error adding patient to database: {e}")
                return
            
            # 2. Process and store each result
            results_processed = 0
            for result in message_info['results']:
                try:
                    # Convert value to float if possible
                    try:
                        value_float = float(result['value'])
                    except (ValueError, TypeError):
                        value_float = None
                    
                    # Add result to database
                    result_id = self.db_manager.add_result(
                        patient_db_id,
                        result['test_code'],
                        value_float if value_float is not None else result['value'],
                        result['unit'],
                        result['flags'],
                        None,  # Use default timestamp
                        result['sequence']
                    )
                    
                    if result_id:
                        results_processed += 1
                        self.log_info(f"Result stored: {result['test_code']} = {result['value']} {result['unit']}")
                    
                except Exception as e:
                    self.log_error(f"Error storing result: {e}")
            
            self.log_info(f"Processed {results_processed} of {len(message_info['results'])} results")
            
            # 3. Try to sync the patient if sync manager is available
            if hasattr(self, 'sync_manager') and self.sync_manager and patient_db_id:
                try:
                    # Create a new event loop for this thread
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    # Run the sync operation
                    loop.run_until_complete(self.sync_manager.sync_patient_realtime(patient_db_id))
                    loop.close()
                    
                    self.log_info(f"Patient {message_info['patient_id']} synced successfully")
                    
                except Exception as e:
                    self.log_error(f"Error syncing patient: {e}")
            
            # 4. Update the UI to show new results
            if self.gui_callback and hasattr(self.gui_callback, 'update_results'):
                try:
                    # Use call_soon_threadsafe for thread safety
                    try:
                        loop = asyncio.get_event_loop()
                    except RuntimeError:
                        loop = asyncio.new_event_loop()
                        
                    loop.call_soon_threadsafe(
                        lambda: self.gui_callback.update_results()
                    )
                except Exception as e:
                    self.log_error(f"Error updating UI with results: {e}")
            
        except Exception as e:
            import traceback
            self.log_error(f"Error in background processing: {e}\n{traceback.format_exc()}")
    
    def get_message_info(self, raw_payload: str) -> Dict[str, Any]:
        """
        Parse a raw ASTM payload into patient and result information
        
        This method can be called externally by the TCP server to parse
        a complete ASTM message payload.
        
        Args:
            raw_payload: The raw ASTM message payload as a string
            
        Returns:
            Dictionary containing patient information and test results
        """
        # Split the payload into frames
        frames = raw_payload.strip().split('\n')
        
        # Store frames temporarily 
        self.current_message_frames = frames
        
        # Extract and return information
        message_info = self._extract_message_info()
        
        # Add the raw payload to the message info
        message_info['raw_payload'] = raw_payload
        
        return message_info
    
    def process_scattergram(self, data: bytes):
        """
        Process scattergram data from analyzers (e.g., SYSMEX XN-L)
        
        Args:
            data: Compressed scattergram data
        """
        try:
            self.log_info(f"Processing scattergram data: {len(data)} bytes")
            
            # Decompress and process the scattergram data
            scattergram = self.scattergram_decoder.decompress(data)
            
            # Update UI if callback exists
            if self.gui_callback and hasattr(self.gui_callback, 'update_scattergram'):
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    
                loop.call_soon_threadsafe(
                    lambda: self.gui_callback.update_scattergram(scattergram)
                )
                
                # Show the scattergram frame if it exists
                if hasattr(self.gui_callback, '_show_scattergram'):
                    loop.call_soon_threadsafe(
                        lambda: self.gui_callback._show_scattergram()
                    )
                
            return True
            
        except Exception as e:
            self.log_error(f"Error processing scattergram: {e}")
            return False