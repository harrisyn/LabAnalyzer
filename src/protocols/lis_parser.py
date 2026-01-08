"""
LIS Protocol Parser for HumaCount 5D Analyzers
"""
import asyncio
from datetime import datetime
import re
from .base_parser import BaseParser

class LISParser(BaseParser):
    """
    Parser for LIS protocol data from HumaCount 5D hematology analyzers
    """
    # LIS Protocol Control Characters
    STX = b'\x02'  # Start of Text
    ETX = b'\x03'  # End of Text
    EOT = b'\x04'  # End of Transmission
    ENQ = b'\x05'  # Enquiry
    ACK = b'\x06'  # Acknowledge
    NAK = b'\x15'  # Negative Acknowledge
    ETB = b'\x17'  # End of Transmission Block
    LF = b'\x0A'   # Line Feed
    CR = b'\x0D'   # Carriage Return
    
    # Record Type Identifiers for HumaCount 5D LIS format
    RECORD_TYPES = {
        'H': 'Header',
        'P': 'Patient',
        'O': 'Order',
        'R': 'Result',
        'L': 'Terminator'
    }
    
    def __init__(self, db_manager, logger, gui_callback=None, config=None):
        """
        Initialize the parser
        
        Args:
            db_manager: DatabaseManager instance for storing parsed data
            logger: Logger instance for logging events
            gui_callback: Optional callback function for GUI updates
            config: Configuration object
        """
        super().__init__(db_manager, logger, config=config)
        self.current_patient_id = None
        self.current_raw_record = None
        self.full_message_payload = []
        self.gui_callback = gui_callback
        self.sync_manager = None
        
    def set_sync_manager(self, sync_manager):
        """
        Set the sync manager for real-time synchronization
        
        Args:
            sync_manager: SyncManager instance
        """
        self.sync_manager = sync_manager
        self.log_info("Sync manager connected to LIS parser")
    
    async def process_data(self, data: bytes):
        """
        Process incoming LIS data
        
        Args:
            data: Raw bytes received from the analyzer
            
        Returns:
            Response bytes if needed, None otherwise
        """
        self.buffer.extend(data)
        
        # Log the raw data received
        self.log_info(f"Received {len(data)} bytes: {data!r}")
        
        # Process LIS control characters for HumaCount 5D
        if self.ENQ in self.buffer:
            # Analyzer is initiating communication
            self.log_info("Received ENQ (Enquiry) from HumaCount 5D")
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
            
        # Process message frames - HumaCount typically uses STX/ETX framing
        while self.STX in self.buffer and self.ETX in self.buffer:
            start_idx = self.buffer.find(self.STX)
            end_idx = self.buffer.find(self.ETX, start_idx)
            
            if start_idx < end_idx:
                # Extract the message without STX and ETX markers
                frame = self.buffer[start_idx + 1:end_idx].decode('ascii', errors='replace')
                
                self.log_info(f"Processing frame: {frame}")
                
                # Process the frame
                await self.process_record(frame)
                
                # Remove the processed frame from the buffer
                self.buffer = self.buffer[end_idx + 1:]
                
                # Send ACK after processing each frame
                return self.ACK

        return None  # No response needed yet
        
    async def process_record(self, record: str):
        """
        Process a single record from the data stream
        
        Args:
            record: A complete record string from the analyzer
        """
        if not record:
            return
            
        self.log_info(f"Processing LIS record: {record}")
        
        # Store raw record for debugging
        self.current_raw_record = record
        self.full_message_payload.append(record)
        
        # Split the record into fields based on LIS format (typically pipe-delimited)
        fields = record.split('|')
        
        if not fields:
            self.log_warning("Empty record received")
            return
            
        try:
            # Extract sequence number if available (usually in field 2)
            sequence = fields[1].strip() if len(fields) > 1 else "0"
            
            # Determine record type from the first field
            record_type = fields[0][-1] if fields[0] else ''  # Last character is the record type
            
            self.log_info(f"Sequence: {sequence}, Record Type: {record_type} ({self.RECORD_TYPES.get(record_type, 'Unknown')})")
            
            # Handle different record types
            handlers = {
                'H': self.handle_header,
                'P': self.handle_patient,
                'O': self.handle_order,
                'R': self.handle_result,
                'L': self.handle_terminator
            }
            
            if handler := handlers.get(record_type):
                await handler(fields)
            else:
                self.log_warning(f"Unknown record type in LIS message: {record_type}")
                
        except Exception as e:
            self.log_error(f"Error processing LIS record: {e}")
    
    async def handle_header(self, fields):
        """Handle header record"""
        self.log_info("Processing LIS Header record")
        # HumaCount 5D header processing would go here
        # Typically contains sender info, date/time, etc.
    
    async def handle_patient(self, fields):
        """Handle patient record"""
        self.log_info("Processing LIS Patient record")
        
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
                        # Add database ID to the info for GUI
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
            # For HumaCount 5D, the typical field order might be different from ASTM
            # Adapting based on typical LIS implementations
            
            # Patient ID is typically in field 3
            patient_id = fields[2].strip() if len(fields) > 2 else ""
            
            # Sample ID might be in field 4
            sample_id = fields[3].strip() if len(fields) > 3 else ""
            
            # Name field is typically field 5, may use ^ as separator for last^first format
            name_field = fields[4].strip() if len(fields) > 4 else ""
            name_parts = name_field.split("^")
            
            # Build full name based on available parts
            if len(name_parts) > 1:
                full_name = f"{name_parts[1]} {name_parts[0]}".strip()  # First Last
            else:
                full_name = name_field
                
            # Extract DOB if available (typically field 7)
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
            
            # Extract sex (field 8, index 7)
            sex = fields[7].strip() if len(fields) > 7 else ""
            
            # Extract physician information (may be in field 10)
            physician = fields[9].strip() if len(fields) > 9 else ""
            
            # Extract address fields if available (may be field 11)
            address = fields[10].strip() if len(fields) > 10 else ""
            
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
        self.log_info("Processing LIS Order record")
        # HumaCount 5D specific order processing would go here
        # Often contains test order details
    
    async def handle_result(self, fields):
        """Handle result record"""
        self.log_info("Processing LIS Result record")
        
        if not self.current_patient_id:
            self.log_warning("Received result record without a patient ID")
            return
            
        try:
            # The typical field structure in HumaCount 5D result records
            # Field 2: Test code
            # Field 3: Value
            # Field 4: Units
            # Field 5: Reference range or flags
            
            if len(fields) < 3:
                self.log_warning("Result record has insufficient fields")
                return
                
            test_code = fields[1].strip() if len(fields) > 1 else ""
            value = fields[2].strip() if len(fields) > 2 else ""
            unit = fields[3].strip() if len(fields) > 3 else ""
            flags = fields[4].strip() if len(fields) > 4 else ""
            
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
            if self.sync_manager and hasattr(self.sync_manager, 'sync_patient_realtime'):
                try:
                    asyncio.create_task(self.sync_manager.sync_patient_realtime(self.current_patient_id))
                except Exception as e:
                    self.log_error(f"Error triggering real-time sync: {e}")
                    
        except Exception as e:
            self.log_error(f"Error in handle_result: {e}")
    
    async def handle_terminator(self, fields):
        """Handle termination record"""
        self.log_info("Processing LIS Terminator record")
        # HumaCount 5D specific terminator processing would go here
        
        # Typically indicates the end of a message block
        # Often the time to finalize any processing and prepare for the next message