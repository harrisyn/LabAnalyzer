"""
Proprietary Protocol Parser for RESPONSE 920 Analyzers
"""
import asyncio
from datetime import datetime
import re
from .base_parser import BaseParser

class ResponseParser(BaseParser):
    """
    Parser for the proprietary protocol used by RESPONSE 920 analyzers
    """
    # Special Characters for RESPONSE 920 protocol
    SOH = b'\x01'  # Start of Header
    STX = b'\x02'  # Start of Text
    ETX = b'\x03'  # End of Text
    EOT = b'\x04'  # End of Transmission
    ENQ = b'\x05'  # Enquiry
    ACK = b'\x06'  # Acknowledge
    FF = b'\x0C'   # Form Feed (often used as record separator)
    CR = b'\x0D'   # Carriage Return
    LF = b'\x0A'   # Line Feed
    CRLF = CR + LF
    
    # Message format identifiers
    MESSAGE_TYPES = {
        'HEADER': 'Message Header',
        'PATIENT': 'Patient Information',
        'RESULT': 'Test Result',
        'COMMENT': 'Comment Information',
        'END': 'End of Message'
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
        self.message_id = 0
        self.current_raw_message = None
        self.full_message_payload = []
        self.gui_callback = gui_callback
        self.sync_manager = None
        # The RESPONSE 920 might use a different message format
        self.message_state = "WAITING"  # States: WAITING, IN_MESSAGE
        
    def set_sync_manager(self, sync_manager):
        """
        Set the sync manager for real-time synchronization
        
        Args:
            sync_manager: SyncManager instance
        """
        self.sync_manager = sync_manager
        self.log_info("Sync manager connected to RESPONSE 920 parser")
    
    async def process_data(self, data: bytes):
        """
        Process incoming data from RESPONSE 920
        
        Args:
            data: Raw bytes received from the analyzer
            
        Returns:
            Response bytes if needed, None otherwise
        """
        self.buffer.extend(data)
        
        # Log the raw data received
        self.log_info(f"Received {len(data)} bytes: {data!r}")
        
        # Process protocol control characters
        if self.ENQ in self.buffer:
            # Analyzer is initiating communication
            self.log_info("Received ENQ (Enquiry)")
            # Clear buffer and acknowledge
            self.buffer.clear()
            self.full_message_payload = []
            self.message_state = "WAITING"
            return self.ACK  # Respond with ACK
            
        elif self.EOT in self.buffer:
            # End of transmission
            self.log_info("Received EOT (End of Transmission)")
            self.buffer.clear()
            self.full_message_payload = []
            self.message_state = "WAITING"
            return None
            
        # RESPONSE 920 often uses SOH to start a message and ETX to end
        if self.SOH in self.buffer and self.message_state == "WAITING":
            self.message_state = "IN_MESSAGE"
            self.log_info("Message start detected")
            
        # Process complete messages (SOH to ETX)
        if self.message_state == "IN_MESSAGE" and self.ETX in self.buffer:
            end_idx = self.buffer.find(self.ETX)
            
            # Extract the complete message (including ETX)
            message = self.buffer[:end_idx + 1].decode('ascii', errors='replace')
            
            # Process the message
            self.log_info(f"Processing complete message: {message}")
            await self.process_message(message)
            
            # Remove the processed message from the buffer
            self.buffer = self.buffer[end_idx + 1:]
            
            # Reset state
            self.message_state = "WAITING"
            
            # Acknowledge receipt
            return self.ACK
            
        # If FF is used for record separation, process FF-separated records
        if self.FF in self.buffer and self.message_state == "IN_MESSAGE":
            while self.FF in self.buffer:
                ff_idx = self.buffer.find(self.FF)
                if ff_idx > 0:  # If there's data before the FF
                    record = self.buffer[:ff_idx].decode('ascii', errors='replace')
                    self.log_info(f"Processing FF-separated record: {record}")
                    await self.process_record(record)
                    
                    # Remove processed record and FF from buffer
                    self.buffer = self.buffer[ff_idx + 1:]
                else:
                    # FF with no preceding data, just remove it
                    self.buffer = self.buffer[1:]
                    
            # Always acknowledge after processing records
            return self.ACK
            
        # If no complete message can be processed yet, return None
        return None
        
    async def process_message(self, message: str):
        """
        Process a complete message from the RESPONSE 920
        
        Args:
            message: A complete message from the analyzer
        """
        if not message:
            return
            
        # Add to full message payload for logging
        self.full_message_payload.append(message)
        
        # RESPONSE 920 may use line-by-line format with specific section identifiers
        lines = message.replace('\r', '\n').split('\n')
        lines = [line for line in lines if line.strip()]  # Remove empty lines
        
        patient_info = {}
        results = []
        
        for line in lines:
            self.log_info(f"Processing line: {line}")
            
            # Parse based on line prefix
            if line.startswith("P|"):  # Patient info
                patient_info = self._extract_patient_info(line)
            elif line.startswith("R|"):  # Result info
                result = self._extract_result(line)
                if result:
                    results.append(result)
            elif line.startswith("C|"):  # Comment
                self.log_info(f"Comment line: {line}")
            elif line.startswith("H|"):  # Header
                self.log_info(f"Header line: {line}")
            elif line.startswith("E|"):  # End
                self.log_info(f"End of message")
                
        # Process the patient and results if we have patient info
        if patient_info and patient_info.get('patient_id'):
            full_payload = '\n'.join(self.full_message_payload)
            
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
                self.current_patient_id = db_patient_id
                self.log_info(f"Patient stored with DB ID: {db_patient_id}")
                
                # Store results
                for result in results:
                    self.db_manager.add_result(
                        db_patient_id,
                        result['test_code'],
                        result['value'],
                        result['unit'],
                        result['flags']
                    )
                
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
                        
                # Try to sync this patient in real-time if sync manager is available
                if hasattr(self, 'sync_manager') and self.sync_manager:
                    try:
                        asyncio.create_task(self.sync_manager.sync_patient_realtime(db_patient_id))
                    except Exception as e:
                        self.log_error(f"Error triggering real-time sync: {e}")
                        
            else:
                self.log_error(f"Failed to store patient with ID: {patient_info['patient_id']}")
    
    async def process_record(self, record: str):
        """
        Process a single record from the analyzer
        
        Args:
            record: A complete record string from the analyzer
        """
        if not record:
            return
            
        self.log_info(f"Processing record: {record}")
        
        # Store raw record for debugging
        self.current_raw_message = record
        self.full_message_payload.append(record)
        
        # Different record formats based on first character/field
        if record.startswith("P|"):
            # Patient information record
            patient_info = self._extract_patient_info(record)
            await self._handle_patient_info(patient_info)
        elif record.startswith("R|") and self.current_patient_id:
            # Result record
            result = self._extract_result(record)
            if result:
                self.db_manager.add_result(
                    self.current_patient_id,
                    result['test_code'],
                    result['value'],
                    result['unit'],
                    result['flags']
                )
        else:
            # Other record types (comments, headers, etc.)
            self.log_info(f"Other record type: {record[:10]}...")
    
    def _extract_patient_info(self, line):
        """
        Extract patient information from a patient line
        
        Args:
            line: A patient information line
            
        Returns:
            Dictionary with patient information
        """
        try:
            # Split the patient line by separator (typically |)
            fields = line.split('|')
            
            # RESPONSE 920 might use a different field order
            # This is a generic implementation that needs to be adjusted
            # based on actual protocol documentation
            
            patient_id = fields[1].strip() if len(fields) > 1 else ""
            sample_id = fields[2].strip() if len(fields) > 2 else ""
            
            # Name might be in format Last^First^Middle
            name_field = fields[3].strip() if len(fields) > 3 else ""
            name_parts = name_field.split("^")
            
            if len(name_parts) > 1:
                full_name = f"{name_parts[1]} {name_parts[0]}".strip()  # First Last
            else:
                full_name = name_field
                
            # DOB may be in format YYYYMMDD
            dob_str = fields[4].strip() if len(fields) > 4 else ""
            dob = None
            age = None
            
            if dob_str:
                try:
                    dob = datetime.strptime(dob_str, "%Y%m%d")
                    
                    # Calculate age
                    today = datetime.today()
                    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                    
                    dob = dob.strftime("%Y-%m-%d")  # Format for readability
                except ValueError:
                    self.log_warning(f"Could not parse birth date: {dob_str}")
                    dob = dob_str
                    
            # Sex may be coded as M/F/O
            sex = fields[5].strip() if len(fields) > 5 else ""
            
            # Physician might be in a later field
            physician = fields[6].strip() if len(fields) > 6 else ""
            
            return {
                "patient_id": patient_id,
                "sample_id": sample_id,
                "patient_name": full_name,
                "sex": sex,
                "date_of_birth": dob,
                "age": age,
                "physician": physician,
                "address": ""  # Address may not be included in RESPONSE 920 format
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
    
    def _extract_result(self, line):
        """
        Extract result information from a result line
        
        Args:
            line: A result line
            
        Returns:
            Dictionary with result information or None if invalid
        """
        try:
            # Split by separator (typically |)
            fields = line.split('|')
            
            if len(fields) < 4:
                return None
                
            # RESPONSE 920 might have its own field order for results
            test_code = fields[1].strip() if len(fields) > 1 else ""
            value = fields[2].strip() if len(fields) > 2 else ""
            unit = fields[3].strip() if len(fields) > 3 else ""
            flags = fields[4].strip() if len(fields) > 4 else ""
            
            # Try to convert value to float
            try:
                value_float = float(value)
            except (ValueError, TypeError):
                value_float = None
                
            return {
                "test_code": test_code,
                "value": value_float if value_float is not None else value,
                "unit": unit,
                "flags": flags,
            }
        except Exception as e:
            self.log_error(f"Error extracting result: {e}")
            return None
    
    async def _handle_patient_info(self, patient_info):
        """
        Handle storing patient information and updating GUI
        
        Args:
            patient_info: Dictionary of patient information
        """
        if not patient_info.get('patient_id'):
            self.log_warning("Patient record missing patient ID")
            return
            
        try:
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
            self.log_error(f"Error handling patient info: {e}")