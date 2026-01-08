"""
HL7 Protocol Parser for Medical Analyzers (Mindray BS-430)
"""
import re
import asyncio
from datetime import datetime
from .base_parser import BaseParser

class HL7Parser(BaseParser):
    """
    Parser for HL7 protocol data from medical analyzers like Mindray BS-430
    """
    # HL7 Control Characters
    VT = b'\x0B'  # Vertical Tab (start of block)
    FS = b'\x1C'  # File Separator
    CR = b'\x0D'  # Carriage Return
    LF = b'\x0A'  # Line Feed
    
    # HL7 Segment Types
    SEGMENT_TYPES = {
        'MSH': 'Message Header',
        'PID': 'Patient Identification',
        'OBR': 'Observation Request',
        'OBX': 'Observation Result',
        'NTE': 'Notes and Comments',
        'EVN': 'Event Type',
    }
    
    def __init__(self, db_manager, logger, gui_callback=None, config=None):
        """
        Initialize the parser
        
        Args:
            db_manager: DatabaseManager instance for storing parsed data
            logger: Logger instance for logging events
            gui_callback: Optional callback function for GUI updates
            config: Configuration dictionary
        """
        super().__init__(db_manager, logger)
        self.config = config or {}
        self.current_patient_id = None
        self.current_message_id = 0
        self.current_raw_message = None
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
        self.log_info("Sync manager connected to HL7 parser")
    
    async def process_data(self, data: bytes):
        """
        Process incoming HL7 data
        
        Args:
            data: Raw bytes received from the analyzer
            
        Returns:
            Response bytes if needed, None otherwise
        """
        self.buffer.extend(data)
        
        # Log the raw data received
        self.log_info(f"Received {len(data)} bytes: {data!r}")
        
        # Check for message start and end markers
        if self.VT in self.buffer and self.FS in self.buffer:
            start_idx = self.buffer.find(self.VT)
            end_idx = self.buffer.find(self.FS)
            
            if start_idx < end_idx:
                # Extract the message without VT and FS markers
                message = self.buffer[start_idx + 1:end_idx].decode('ascii', errors='replace')
                
                # Process the HL7 message
                await self.process_message(message)
                
                # Remove the processed message from the buffer
                self.buffer = self.buffer[end_idx + 1:]
                
                # Acknowledge the message with ACK
                return self._generate_ack()
        
        return None  # No response needed yet
        
    async def process_message(self, message: str):
        """
        Process a complete HL7 message
        
        Args:
            message: A complete HL7 message string
        """
        if not message:
            return
            
        self.log_info(f"Processing HL7 message: {message}")
        
        # Add to full message payload
        self.full_message_payload = []
        self.full_message_payload.append(message)
        
        # Split message into segments (each line is a segment)
        segments = message.split('\r')
        
        # Process each segment
        patient_info = {}
        results = []
        
        for segment in segments:
            if not segment:
                continue
                
            # Split segment into fields by |
            fields = segment.split('|')
            
            if not fields or len(fields) < 2:
                continue
                
            segment_type = fields[0]
            
            # Handle different segment types
            if segment_type == 'MSH':
                self.log_info("Processing Message Header segment")
                # Message header processing would go here
                
            elif segment_type == 'PID':
                self.log_info("Processing Patient ID segment")
                patient_info = self._extract_patient_info(fields)
                
            elif segment_type == 'OBR':
                self.log_info("Processing Observation Request segment")
                # Extract sample/specimen ID from OBR
                order_info = self._extract_order_info(fields)
                if order_info.get('sample_id'):
                    patient_info['sample_id'] = order_info['sample_id']
                
            elif segment_type == 'OBX':
                self.log_info("Processing Observation Result segment")
                result = self._extract_result(fields)
                if result:
                    results.append(result)
                
        # Store patient in database if we have patient info
        if patient_info.get('patient_id'):
            full_payload = '\n'.join(self.full_message_payload)
            
            db_patient_id = self.db_manager.add_patient(
                patient_info['patient_id'],
                patient_info['patient_name'],
                patient_info['date_of_birth'],
                patient_info['sex'],
                patient_info['physician'],
                full_payload,
                patient_info['sample_id'],
                listener_port=self.listener_port,
                listener_name=self.listener_name
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
    
    def _extract_patient_info(self, fields):
        """
        Extract patient information from a PID segment
        
        Args:
            fields: The split fields of a PID segment
            
        Returns:
            Dictionary with patient information
        """
        try:
            # For Mindray BS-430, typical PID segment format:
            # PID|1||patient_id||patient_name||DOB|Sex||||address||||physician
            
           # Try field 2 first (External ID), then field 3 (Internal ID)
            patient_id = fields[2].strip() if len(fields) > 2 and fields[2].strip() else ""
            if not patient_id:
                patient_id = fields[3].strip() if len(fields) > 3 else ""
            
            # Sample ID will be extracted from OBR segment
            sample_id = ""
            
            # Extract name (in HL7 typically in field 5)
            name_field = fields[5].strip() if len(fields) > 5 else ""
            name_parts = name_field.split("^")
            full_name = " ".join(filter(None, name_parts))
            
            # Extract DOB (field 7)
            dob_str = fields[7].strip() if len(fields) > 7 else ""
            dob = None
            age = None
            
            if dob_str:
                try:
                    # HL7 typically uses YYYYMMDD format
                    dob = datetime.strptime(dob_str, "%Y%m%d")
                    
                    # Calculate age
                    today = datetime.today()
                    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                    
                    dob = dob.strftime("%Y-%m-%d")
                except ValueError:
                    self.log_warning(f"Could not parse birth date: {dob_str}")
                    dob = dob_str
            
            # Extract sex (field 8)
            sex = fields[8].strip() if len(fields) > 8 else ""
            
            # Extract physician information (field 15)
            physician = fields[15].strip() if len(fields) > 15 else ""
            
            # Extract address
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
    def _extract_order_info(self, fields):
        """
        Extract order/sample information from an OBR segment
        
        Args:
            fields: The split fields of an OBR segment
            
        Returns:
            Dictionary with order information
        """
        try:
            # OBR segment format:
            # OBR|set_id|placer_order|filler_order|universal_service_id|...
            # Field 3 contains Filler Order Number (sample/specimen ID)
            sample_id = fields[3].strip() if len(fields) > 3 else ""
            
            return {"sample_id": sample_id}
        except Exception as e:
            self.log_error(f"Error extracting order info: {e}")
            return {}
            
    def _extract_result(self, fields):
        """
        Extract result information from an OBX segment
        
        Args:
            fields: The split fields of an OBX segment
            
        Returns:
            Dictionary with result information or None if invalid
        """
        try:
            # For Mindray BS-430, typical OBX format:
            # OBX|sequence|result_type|test_code^test_name|sub_id|value|unit|reference_range|abnormal_flags
            
            sequence = fields[1] if len(fields) > 1 else ""
            
            # Test code is typically in field 3, often in format CODE^NAME
            test_field = fields[3] if len(fields) > 3 else ""
            test_parts = test_field.split("^")
            test_code = test_parts[0] if test_parts else ""
            
            value = fields[5] if len(fields) > 5 else ""
            unit = fields[6] if len(fields) > 6 else ""
            flags = fields[8] if len(fields) > 8 else ""
            
            # Try to convert value to float for storage
            try:
                value_float = float(value)
            except (ValueError, TypeError):
                value_float = None
                
            return {
                "test_code": test_code,
                "value": value_float if value_float is not None else value,
                "unit": unit,
                "flags": flags,
                "sequence": sequence
            }
        except Exception as e:
            self.log_error(f"Error extracting result: {e}")
            return None
    
    def _generate_ack(self):
        """
        Generate HL7 ACK (acknowledgment) message
        
        Returns:
            Bytes to send as acknowledgment
        """
        # Simple ACK response for HL7
        # In real implementation, this would generate a proper MSA segment
        ack = self.VT + b"MSH|^~\\&|RECEIVER|FACILITY||SENDER|" + \
              datetime.now().strftime("%Y%m%d%H%M%S").encode() + \
              b"||ACK|" + str(self.current_message_id).encode() + \
              b"|P|2.3\rMSA|AA|" + str(self.current_message_id).encode() + b"\r" + self.FS + self.CR
        
        self.current_message_id += 1
        return ack