"""
Roche Cobas Protocol Parser for Clinical Chemistry Analyzers
"""
import asyncio
from datetime import datetime
import re
from .base_parser import BaseParser

class CobasParser(BaseParser):
    """
    Parser for Roche Cobas analyzers that use a modified ASTM protocol
    Supports models like Cobas c111, c311, c501, and Integra series
    """
    # ASTM Control Characters (same as standard ASTM but with some variations)
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
    
    # Record Type Identifiers (Cobas may use additional types)
    RECORD_TYPES = {
        'H': 'Header',
        'P': 'Patient',
        'O': 'Order',
        'R': 'Result',
        'C': 'Comment',
        'M': 'Manufacturer Information',
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
        self.checksum_enabled = True  # Cobas often uses checksums
        
    def set_sync_manager(self, sync_manager):
        """
        Set the sync manager for real-time synchronization
        
        Args:
            sync_manager: SyncManager instance
        """
        self.sync_manager = sync_manager
        self.log_info("Sync manager connected to Cobas parser")
    
    async def process_data(self, data: bytes):
        """
        Process incoming data from Cobas analyzer
        
        Args:
            data: Raw bytes received from the analyzer
            
        Returns:
            Response bytes if needed, None otherwise
        """
        self.buffer.extend(data)
        
        # Log the raw data received
        self.log_info(f"Received {len(data)} bytes: {data!r}")
        
        # Process ASTM control characters
        if self.ENQ in self.buffer:
            # Analyzer is initiating communication
            self.log_info("Received ENQ (Enquiry) from Cobas analyzer")
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
                    
                    self.log_info(f"Processing frame: {frame}")
                    
                    # Process the frame
                    await self.process_record(frame)
                    
                    # Remove the processed frame from the buffer including checksum
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
            
        self.log_info(f"Processing Cobas record: {record}")
        
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
                
            # Extract frame number and record type
            frame_info = fields[0]
            record_type = frame_info[-1] if frame_info else ''  # Last character is the record type
            
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
                'M': self.handle_manufacturer_info,
                'L': self.handle_terminator
            }
            
            if handler := handlers.get(record_type):
                await handler(fields)
            else:
                self.log_warning(f"Unknown record type: {record_type}")
                
        except Exception as e:
            self.log_error(f"Error processing record: {e}")
    
    async def handle_header(self, fields):
        """Handle header record"""
        self.log_info("Processing Cobas Header record")
        # Typically contains sender info, date/time, etc.
    
    async def handle_patient(self, fields):
        """Handle patient record"""
        self.log_info("Processing Cobas Patient record")
        
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
            # Cobas may use a slightly different field order
            # This is based on common ASTM implementations for clinical chemistry
            
            # Patient ID is typically in field 3
            patient_id = fields[3].strip() if len(fields) > 3 else ""
            
            # Sample ID might be in field 4
            sample_id = fields[4].strip() if len(fields) > 4 else ""
            
            # Name field is typically field 5, may use ^ as separator for last^first format
            name_field = fields[5].strip() if len(fields) > 5 else ""
            name_parts = name_field.split("^")
            
            # Build full name based on available parts
            if len(name_parts) > 1:
                full_name = f"{name_parts[1]} {name_parts[0]}".strip()  # First Last
            else:
                full_name = name_field
                
            # Extract DOB if available (typically field 7)
            dob_str = fields[7].strip() if len(fields) > 7 else ""
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
            
            # Extract sex (field 8, index 7)
            sex = fields[8].strip() if len(fields) > 8 else ""
            
            # Extract physician information (usually in field 15)
            physician = fields[15].strip() if len(fields) > 15 else ""
            
            # Extract address fields if available
            address = fields[11].strip() if len(fields) > 11 else ""
            
            return {
                "patient_id": patient_id,
                "sample_id": sample_id,
                "patient_name": full_name,
                "sex": sex,
                "date_of_birth": dob,
                "age": age,
                "physician": physician,
                "address": address
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
        self.log_info("Processing Cobas Order record")
        # Order processing for Cobas analyzers
    
    async def handle_result(self, fields):
        """Handle result record"""
        self.log_info("Processing Cobas Result record")
        
        if not self.current_patient_id:
            self.log_warning("Received result record without a patient ID")
            return
            
        try:
            # Cobas result field positions:
            # Field 2: Sequence number
            # Field 3: Universal Test ID
            # Field 4: Data or Measurement value
            # Field 6: Units
            # Field 8: Abnormal flags
            
            if len(fields) < 3:
                self.log_warning("Result record has insufficient fields")
                return
                
            test_code = fields[3].strip() if len(fields) > 3 else ""
            value = fields[4].strip() if len(fields) > 4 else ""
            unit = fields[6].strip() if len(fields) > 6 else ""
            flags = fields[8].strip() if len(fields) > 8 else ""
            
            if not test_code:
                self.log_warning("Result record missing test code")
                return
                
            # Convert value to float for storage if possible
            try:
                value_float = float(value)
            except (ValueError, TypeError):
                value_float = None
            
            # Store result in database
            self.db_manager.add_result(
                self.current_patient_id,
                test_code,
                value_float if value_float is not None else value,
                unit,
                flags
            )
            
            self.log_info(f"Stored result for test {test_code}: {value} {unit} {flags}")
            
            # Update GUI if callback exists
            if self.gui_callback and hasattr(self.gui_callback, 'update_result'):
                result_info = {
                    'test_code': test_code,
                    'value': value_float if value_float is not None else value,
                    'unit': unit,
                    'flags': flags,
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
            self.log_error(f"Error in handle_result: {e}")
    
    async def handle_comment(self, fields):
        """Handle comment record"""
        self.log_info("Processing Cobas Comment record")
        # Cobas often includes comments to explain results or QC information
    
    async def handle_manufacturer_info(self, fields):
        """Handle manufacturer-specific information record"""
        self.log_info("Processing Cobas Manufacturer Info record")
        # Roche Cobas specific information, often including extended result details
    
    async def handle_terminator(self, fields):
        """Handle termination record"""
        self.log_info("Processing Cobas Terminator record")
        # Typically indicates the end of a message block