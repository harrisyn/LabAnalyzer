"""
Ortho Clinical Diagnostics VITROS Protocol Parser for Clinical Chemistry Analyzers
"""
import asyncio
from datetime import datetime
import re
from .base_parser import BaseParser

class VitrosParser(BaseParser):
    """
    Parser for Ortho Clinical Diagnostics VITROS analyzers
    Supports VITROS 250, 350, 5600, ECi, and 3600 systems
    Uses a modified ASTM E1381/E1394 protocol
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
        'Q': 'Request',  # VITROS specific
        'S': 'Scientific',  # VITROS specific
        'M': 'Manufacturer',
        'L': 'Terminator'
    }
    
    def __init__(self, db_manager, logger, gui_callback=None):
        """
        Initialize the parser
        
        Args:
            db_manager: DatabaseManager instance for storing parsed data
            logger: Logger instance for logging events
            gui_callback: Optional callback function for GUI updates
        """
        super().__init__(db_manager, logger)
        self.current_patient_id = None
        self.current_frame_number = 0
        self.current_raw_record = None
        self.full_message_payload = []
        self.gui_callback = gui_callback
        self.sync_manager = None
        self.checksum_enabled = True
        # VITROS-specific state tracking
        self.current_sample_id = None
        self.pending_results = []
        
    def set_sync_manager(self, sync_manager):
        """
        Set the sync manager for real-time synchronization
        
        Args:
            sync_manager: SyncManager instance
        """
        self.sync_manager = sync_manager
        self.log_info("Sync manager connected to VITROS parser")
    
    async def process_data(self, data: bytes):
        """
        Process incoming data from VITROS analyzer
        
        Args:
            data: Raw bytes received from the analyzer
            
        Returns:
            Response bytes if needed, None otherwise
        """
        self.buffer.extend(data)
        
        # Log the raw data received
        self.log_info(f"Received {len(data)} bytes from VITROS analyzer")
        
        # Process ASTM control characters
        if self.ENQ in self.buffer:
            # Analyzer is initiating communication
            self.log_info("Received ENQ (Enquiry) from VITROS analyzer")
            # Clear buffer and acknowledge
            self.buffer.clear()
            self.full_message_payload = []  # Reset full message payload
            return self.ACK  # Respond with ACK
            
        elif self.EOT in self.buffer:
            # End of transmission
            self.log_info("Received EOT (End of Transmission)")
            self.buffer.clear()
            self.full_message_payload = []  # Reset full message payload
            return None
            
        # Process message frames
        while self.STX in self.buffer and (self.ETX in self.buffer or self.ETB in self.buffer):
            # Find the beginning of a frame
            start_idx = self.buffer.find(self.STX)
            
            # Find the end of the frame (either ETX or ETB)
            etx_idx = self.buffer.find(self.ETX, start_idx)
            etb_idx = self.buffer.find(self.ETB, start_idx)
            
            # Determine which end character comes first
            if etx_idx != -1 and (etb_idx == -1 or etx_idx < etb_idx):
                end_idx = etx_idx
                end_char = self.ETX
            elif etb_idx != -1:
                end_idx = etb_idx
                end_char = self.ETB
            else:
                # Neither found after start, need more data
                break
                
            if start_idx < end_idx:
                # Calculate positions for extracting the frame
                frame_start = start_idx + 1  # Skip STX
                frame_end = end_idx  # Up to but not including ETX/ETB
                
                # Check if we have enough bytes for a checksum (2 bytes after ETX/ETB)
                if len(self.buffer) >= end_idx + 3:
                    # Extract the frame without control characters
                    frame = self.buffer[frame_start:frame_end].decode('ascii', errors='replace')
                    
                    # Extract checksum (2 hex characters after ETX/ETB)
                    checksum_bytes = self.buffer[end_idx + 1:end_idx + 3]
                    try:
                        received_checksum = int(checksum_bytes.decode('ascii'), 16)
                        
                        # Calculate checksum - XOR of all bytes in the frame including STX
                        calculated_checksum = 0
                        for i in range(start_idx, end_idx + 1):
                            calculated_checksum ^= self.buffer[i]
                            
                        if self.checksum_enabled and received_checksum != calculated_checksum:
                            self.log_warning(f"Checksum mismatch: received {received_checksum:02X}, calculated {calculated_checksum:02X}")
                            # Remove up to the end character + checksum
                            self.buffer = self.buffer[end_idx + 3:]
                            return self.NAK  # Request retransmission
                    except ValueError:
                        self.log_warning("Invalid checksum format")
                        # Try to continue anyway
                    
                    self.log_info(f"Processing VITROS frame: {frame}")
                    
                    # Process the frame
                    await self.process_record(frame)
                    
                    # Remove the processed frame from buffer including checksum
                    self.buffer = self.buffer[end_idx + 3:]
                    
                    # Increment frame number for multi-frame messages
                    self.current_frame_number += 1
                    
                    # Send acknowledgment after processing the frame
                    if end_char == self.ETB:
                        # More frames to come
                        self.log_info("Frame ends with ETB, expecting more frames")
                    else:  # ETX
                        # End of message
                        self.log_info("Frame ends with ETX, end of message")
                        self.current_frame_number = 0
                        
                    return self.ACK  # Acknowledge receipt
                else:
                    # Need more data for the checksum
                    break
        
        return None  # No response needed yet
        
    async def process_record(self, record: str):
        """
        Process a single record from the analyzer
        
        Args:
            record: A complete record string from the analyzer
        """
        if not record:
            return
            
        self.log_info(f"Processing VITROS record: {record}")
        
        # Store raw record for debugging
        self.current_raw_record = record
        self.full_message_payload.append(record)
        
        # Split the record into fields based on ASTM format (typically | delimited)
        fields = record.split('|')
        
        if not fields:
            self.log_warning("Empty record received")
            return
            
        try:
            # Determine record type from the first field
            if not fields[0]:
                self.log_warning("Record type not found")
                return
                
            record_type = fields[0][-1] if fields[0] else ''  # Last character is the record type
            
            # Extract sequence number if available (usually in field 2)
            sequence = fields[1].strip() if len(fields) > 1 else "0"
            
            self.log_info(f"Sequence: {sequence}, Record Type: {record_type} ({self.RECORD_TYPES.get(record_type, 'Unknown')})")
            
            # Handle different record types
            handlers = {
                'H': self.handle_header,
                'P': self.handle_patient,
                'O': self.handle_order,
                'R': self.handle_result,
                'C': self.handle_comment,
                'Q': self.handle_request,
                'S': self.handle_scientific,
                'M': self.handle_manufacturer,
                'L': self.handle_terminator
            }
            
            if handler := handlers.get(record_type):
                await handler(fields)
            else:
                self.log_warning(f"Unknown record type: {record_type}")
                
        except Exception as e:
            self.log_error(f"Error processing VITROS record: {e}")
    
    async def handle_header(self, fields):
        """Handle header record"""
        self.log_info("Processing VITROS Header record")
        
        try:
            if len(fields) >= 5:
                # Extract sender information
                sender_info = fields[4].split('^') if fields[4] else []
                if len(sender_info) >= 3:
                    instrument = sender_info[0]
                    model = sender_info[1]
                    serial = sender_info[2]
                    self.log_info(f"Message from {instrument} {model}, S/N: {serial}")
        except Exception as e:
            self.log_error(f"Error processing header: {e}")
    
    async def handle_patient(self, fields):
        """Handle patient record"""
        self.log_info("Processing VITROS Patient record")
        
        try:
            # Extract patient information from the fields
            patient_info = self.extract_patient_info(fields)
            
            # Store full message for reference
            full_payload = '\n'.join(self.full_message_payload)
            
            # Add patient to database
            db_patient_id = self.db_manager.add_patient(
                patient_info['patient_id'],
                patient_info['patient_name'],
                patient_info['date_of_birth'],
                patient_info['sex'],
                patient_info['physician'],
                full_payload,
                patient_info['sample_id']
            )
            
            if db_patient_id:
                self.log_info(f"Patient stored with DB ID: {db_patient_id}")
                self.current_patient_id = db_patient_id
                
                # Update GUI if callback exists
                if self.gui_callback and hasattr(self.gui_callback, 'update_patient_info'):
                    try:
                        # Add database ID to the info
                        patient_info['db_id'] = db_patient_id
                        asyncio.get_event_loop().call_soon_threadsafe(
                            self.gui_callback.update_patient_info,
                            patient_info
                        )
                    except Exception as e:
                        self.log_error(f"Error updating GUI with patient info: {e}")
                
                # Process any pending results that came before the patient record
                if self.pending_results and self.current_sample_id == patient_info['sample_id']:
                    self.log_info(f"Processing {len(self.pending_results)} pending results")
                    for result in self.pending_results:
                        await self.store_result(result)
                    self.pending_results = []
            else:
                self.log_error(f"Failed to store patient with ID: {patient_info['patient_id']}")
                
        except Exception as e:
            self.log_error(f"Error in handle_patient: {e}")
    
    def extract_patient_info(self, fields):
        """
        Extract patient information from a patient record
        
        Args:
            fields: The split fields of a patient record
            
        Returns:
            Dictionary with patient information
        """
        try:
            # VITROS fields layout:
            # P|1|12345|111111|SMITH^JOHN||19800101|M||||||||||||||20230305
            
            patient_id = fields[3].strip() if len(fields) > 3 else ""
            self.current_sample_id = fields[2].strip() if len(fields) > 2 else ""
            
            # Name field is typically field 4, may use ^ as separator for last^first format
            name_field = fields[4].strip() if len(fields) > 4 else ""
            name_parts = name_field.split("^")
            
            # Build full name based on available parts
            if len(name_parts) > 1:
                full_name = f"{name_parts[1]} {name_parts[0]}".strip()  # First Last
            else:
                full_name = name_field
                
            # Extract DOB if available 
            dob_str = fields[6].strip() if len(fields) > 6 else ""
            dob = None
            age = None
            
            if dob_str:
                try:
                    # Try to parse DOB in YYYYMMDD format
                    dob = datetime.strptime(dob_str, "%Y%m%d")
                    
                    # Calculate age
                    today = datetime.today()
                    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                    
                    dob = dob.strftime("%Y-%m-%d")  # Format DOB for readability
                except ValueError:
                    # Handle alternative date formats or invalid dates
                    self.log_warning(f"Could not parse birth date: {dob_str}")
                    dob = dob_str
            
            # Extract sex
            sex = fields[7].strip() if len(fields) > 7 else ""
            
            # Extract physician (no direct field for this in standard ASTM, use a common location)
            physician = fields[15].strip() if len(fields) > 15 and fields[15] else ""
            
            return {
                "patient_id": patient_id,
                "sample_id": self.current_sample_id,
                "patient_name": full_name,
                "sex": sex,
                "date_of_birth": dob,
                "age": age,
                "physician": physician,
                "address": ""  # Not typically included in VITROS messages
            }
        except Exception as e:
            self.log_error(f"Error extracting patient info: {e}")
            return {
                "patient_id": "",
                "sample_id": "",
                "patient_name": "Unknown",
                "sex": "",
                "date_of_birth": "",
                "age": None,
                "physician": "",
                "address": ""
            }
    
    async def handle_order(self, fields):
        """Handle order record"""
        self.log_info("Processing VITROS Order record")
        
        try:
            # Extract sample ID if present
            if len(fields) > 3:
                sample_id = fields[2].strip()
                if sample_id:
                    self.current_sample_id = sample_id
                    self.log_info(f"Sample ID updated: {sample_id}")
                    
            # Extract test information
            if len(fields) > 4:
                test_info = fields[4].split('^')
                if len(test_info) >= 4:
                    test_code = test_info[3]
                    test_name = test_info[4] if len(test_info) >= 5 else test_code
                    self.log_info(f"Order for test: {test_code} ({test_name})")
        except Exception as e:
            self.log_error(f"Error processing order: {e}")
    
    async def handle_result(self, fields):
        """Handle result record"""
        self.log_info("Processing VITROS Result record")
        
        try:
            # Create result dictionary
            result = {
                'sample_id': fields[2].strip() if len(fields) > 2 else self.current_sample_id,
                'test_code': "",
                'value': "",
                'unit': "",
                'flags': "",
                'ref_range': ""
            }
            
            # Update current sample ID if provided
            if result['sample_id']:
                self.current_sample_id = result['sample_id']
            
            # Extract test information
            if len(fields) > 2:
                test_info = fields[2].split('^')
                if len(test_info) >= 3:
                    result['test_code'] = test_info[2]
                    
            # Extract result value
            if len(fields) > 3:
                result['value'] = fields[3].strip()
                
            # Extract unit
            if len(fields) > 4:
                result['unit'] = fields[4].strip()
                
            # Extract reference range
            if len(fields) > 5:
                ref_parts = fields[5].split('^')
                if len(ref_parts) >= 2:
                    result['ref_range'] = f"{ref_parts[0]}-{ref_parts[1]}"
                    
            # Extract flags/abnormal flags
            if len(fields) > 6:
                result['flags'] = fields[6].strip()
            
            if self.current_patient_id:
                await self.store_result(result)
            else:
                # Store result for later processing when patient ID is available
                self.log_info(f"Queuing result for sample {result['sample_id']} (no patient ID yet)")
                self.pending_results.append(result)
                
        except Exception as e:
            self.log_error(f"Error processing result: {e}")
    
    async def store_result(self, result):
        """Store a test result in the database"""
        try:
            # Convert value to float for storage if possible
            try:
                value_float = float(result['value'])
            except (ValueError, TypeError):
                value_float = None
                
            # Store result in database
            self.db_manager.add_result(
                self.current_patient_id,
                result['test_code'],
                value_float if value_float is not None else result['value'],
                result['unit'],
                result['flags'],
                result['ref_range']
            )
            
            self.log_info(f"Stored result for test {result['test_code']}: {result['value']} {result['unit']} {result['flags']}")
            
            # Update GUI if callback exists
            if self.gui_callback and hasattr(self.gui_callback, 'update_result'):
                result_info = {
                    'test_code': result['test_code'],
                    'value': value_float if value_float is not None else result['value'],
                    'unit': result['unit'],
                    'flags': result['flags'],
                    'ref_range': result['ref_range'],
                    'patient_id': self.current_patient_id
                }
                
                try:
                    asyncio.get_event_loop().call_soon_threadsafe(
                        self.gui_callback.update_result,
                        result_info
                    )
                except Exception as e:
                    self.log_error(f"Error updating GUI with result: {e}")
                    
            # Try to sync this result in real-time if sync manager is available
            if hasattr(self, 'sync_manager') and self.sync_manager:
                try:
                    asyncio.create_task(self.sync_manager.sync_patient_realtime(self.current_patient_id))
                except Exception as e:
                    self.log_error(f"Error triggering real-time sync: {e}")
        except Exception as e:
            self.log_error(f"Error storing result: {e}")
    
    async def handle_comment(self, fields):
        """Handle comment record"""
        self.log_info("Processing VITROS Comment record")
        
        try:
            if not self.current_patient_id:
                self.log_info("No patient ID, skipping comment")
                return
                
            comment_type = fields[2].strip() if len(fields) > 2 else ""
            comment_source = fields[3].strip() if len(fields) > 3 else ""
            comment_text = fields[4].strip() if len(fields) > 4 else ""
            
            if comment_text:
                self.log_info(f"Comment ({comment_type}/{comment_source}): {comment_text}")
                
                # Store comment as a special result
                self.db_manager.add_result(
                    self.current_patient_id,
                    f"COMMENT_{comment_type}",
                    comment_text,
                    "",
                    ""
                )
        except Exception as e:
            self.log_error(f"Error processing comment: {e}")
    
    async def handle_request(self, fields):
        """Handle request record (VITROS specific)"""
        self.log_info("Processing VITROS Request record")
        # This record type is specific to VITROS systems and typically 
        # contains information about test requests from the LIS
    
    async def handle_scientific(self, fields):
        """Handle scientific record (VITROS specific)"""
        self.log_info("Processing VITROS Scientific record")
        # Contains additional scientific/QC data from the VITROS analyzer
        
    async def handle_manufacturer(self, fields):
        """Handle manufacturer record"""
        self.log_info("Processing VITROS Manufacturer record")
        # Contains VITROS-specific information
        
    async def handle_terminator(self, fields):
        """Handle termination record"""
        self.log_info("Processing VITROS Terminator record")
        # Indicates the end of a message block
        
        # In VITROS systems, it's common to reset patient context after a complete message
        self.current_patient_id = None