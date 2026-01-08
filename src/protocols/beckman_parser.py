"""
Beckman Coulter Protocol Parser for Clinical Chemistry Analyzers
Supports AU series (AU480, AU680, AU5800) and DxC series analyzers
"""
import asyncio
from datetime import datetime
import re
from .base_parser import BaseParser

class BeckmanParser(BaseParser):
    """Parser for Beckman Coulter analyzers using modified ASTM protocol"""
    
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

    # Beckman-specific Record Type Identifiers
    RECORD_TYPES = {
        'H': 'Header',
        'P': 'Patient',
        'O': 'Order',
        'R': 'Result',
        'C': 'Comment',
        'M': 'Manufacturer Information',
        'L': 'Terminator'
    }

    # Beckman-specific result flag mappings
    FLAG_MAP = {
        'H': 'High',
        'L': 'Low',
        'LL': 'Critical Low',
        'HH': 'Critical High',
        'A': 'Abnormal',
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
        self.current_frame_number = 0
        self.current_raw_record = None
        self.full_message_payload = []
        self.gui_callback = gui_callback
        self.sync_manager = None
        self.checksum_enabled = True
        self.pending_results = []

    def set_sync_manager(self, sync_manager):
        """Set the sync manager for real-time synchronization"""
        self.sync_manager = sync_manager
        self.log_info("Sync manager connected to Beckman parser")

    async def process_data(self, data: bytes):
        """Process incoming data from Beckman analyzer"""
        self.buffer.extend(data)
        
        if self.ENQ in self.buffer:
            return self._handle_enq()
        elif self.EOT in self.buffer:
            return self._handle_eot()
            
        # Process message frames
        while True:
            frame_result = await self._process_next_frame()
            if frame_result is None:
                break
            if frame_result is not None:
                return frame_result
                
        return None
        
    def _handle_enq(self):
        """Handle ENQ control character"""
        self.log_info("Received ENQ from Beckman analyzer")
        self.buffer.clear()
        return self.ACK
        
    def _handle_eot(self):
        """Handle EOT control character"""
        self.log_info("Received EOT from Beckman analyzer")
        self.buffer.clear()
        return None
        
    async def _process_next_frame(self):
        """Process the next frame in the buffer if available"""
        if not (self.STX in self.buffer and (self.ETX in self.buffer or self.ETB in self.buffer)):
            return None
            
        start_idx = self.buffer.find(self.STX)
        etx_idx = self.buffer.find(self.ETX, start_idx)
        etb_idx = self.buffer.find(self.ETB, start_idx)
        
        # Determine which end character comes first
        end_idx, end_char = self._get_frame_bounds(etx_idx, etb_idx)
        if end_idx is None:
            return None
            
        if start_idx >= end_idx:
            return None
            
        # Check if we have enough bytes for checksum
        if len(self.buffer) < end_idx + 3:
            return None
            
        return await self._process_frame_content(start_idx, end_idx, end_char)
        
    def _get_frame_bounds(self, etx_idx, etb_idx):
        """Determine the frame boundaries based on ETX/ETB positions"""
        if etx_idx != -1 and (etb_idx == -1 or etx_idx < etb_idx):
            return etx_idx, self.ETX
        elif etb_idx != -1:
            return etb_idx, self.ETB
        return None, None
        
    async def _process_frame_content(self, start_idx, end_idx, end_char):
        """Process the content of a frame and return appropriate response"""
        frame = self.buffer[start_idx + 1:end_idx].decode('ascii', errors='replace')
        
        if self.checksum_enabled and not self._validate_checksum(start_idx, end_idx):
            self.buffer = self.buffer[end_idx + 3:]
            return self.NAK
            
        self.log_info(f"Processing frame: {frame}")
        await self.process_record(frame)
        
        # Remove processed frame from buffer
        self.buffer = self.buffer[end_idx + 3:]
        
        # Increment frame number
        self.current_frame_number += 1
        
        if end_char == self.ETB:
            self.log_info("Frame ends with ETB, expecting more frames")
        else:  # ETX
            self.log_info("Frame ends with ETX, end of message")
            self.current_frame_number = 0
        
        return self.ACK
        
    def _validate_checksum(self, start_idx, end_idx):
        """Validate the checksum of a frame"""
        try:
            checksum_bytes = self.buffer[end_idx + 1:end_idx + 3]
            received_checksum = int(checksum_bytes.decode('ascii'), 16)
            calculated_checksum = 0
            for i in range(start_idx, end_idx + 1):
                calculated_checksum ^= self.buffer[i]
                
            if received_checksum != calculated_checksum:
                self.log_warning(f"Checksum mismatch: received {received_checksum:02X}, calculated {calculated_checksum:02X}")
                return False
                
            return True
        except ValueError:
            self.log_warning("Invalid checksum format")
            return False

    async def process_record(self, record: str):
        """Process a complete record"""
        try:
            fields = record.split('|')
            if not fields:
                return

            record_type = fields[0][0] if fields[0] else ''
            
            self.log_info(f"Record Type: {record_type} ({self.RECORD_TYPES.get(record_type, 'Unknown')})")
            
            # Add to full message payload
            self.full_message_payload.append(record)
            
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
        self.log_info("Processing Beckman Header record")
        self.current_patient_id = None
        self.current_frame_number = 1
        self.full_message_payload = []
        self.full_message_payload.append('|'.join(fields))

    async def handle_patient(self, fields):
        """Handle patient record"""
        self.log_info("Processing Patient record")
        patient_info = self.extract_patient_info(fields)
        
        if patient_info.get('patient_id'):
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
                
                if self.gui_callback and hasattr(self.gui_callback, 'update_patient_info'):
                    try:
                        patient_info['db_id'] = db_patient_id
                        asyncio.get_event_loop().call_soon_threadsafe(
                            self.gui_callback.update_patient_info,
                            patient_info
                        )
                    except Exception as e:
                        self.log_error(f"Error updating GUI with patient info: {e}")

    def extract_patient_info(self, fields):
        """Extract patient information from fields"""
        patient_info = {
            'patient_id': '',
            'patient_name': '',
            'date_of_birth': '',
            'sex': '',
            'physician': '',
            'sample_id': ''
        }
        
        try:
            # Beckman field mapping (adjust based on actual protocol)
            if len(fields) > 3:
                patient_info['patient_id'] = fields[3].strip()
            if len(fields) > 5:
                patient_info['patient_name'] = fields[5].strip()
            if len(fields) > 7:
                # Parse date in format YYYYMMDD
                date_str = fields[7].strip()
                if date_str and len(date_str) == 8:
                    try:
                        date_obj = datetime.strptime(date_str, '%Y%m%d')
                        patient_info['date_of_birth'] = date_obj.strftime('%Y-%m-%d')
                    except ValueError:
                        self.log_warning(f"Invalid date format: {date_str}")
            if len(fields) > 8:
                patient_info['sex'] = fields[8].strip()
            if len(fields) > 10:
                patient_info['physician'] = fields[10].strip()
            if len(fields) > 12:
                patient_info['sample_id'] = fields[12].strip()
                
        except Exception as e:
            self.log_error(f"Error extracting patient info: {e}")
            
        return patient_info

    async def handle_order(self, fields):
        """Handle order record"""
        self.log_info("Processing Order record")
        # Order processing would go here
        # Typically contains test orders and sample information

    async def handle_result(self, fields):
        """Handle result record"""
        try:
            if not self.current_patient_id:
                self.log_warning("No patient ID for result")
                return

            if len(fields) < 4:
                self.log_warning("Insufficient fields in result record")
                return

            # Extract result data (adjust field positions based on actual protocol)
            test_code = fields[2].strip() if len(fields) > 2 else ''
            value = fields[3].strip() if len(fields) > 3 else ''
            unit = fields[4].strip() if len(fields) > 4 else ''
            flags = fields[5].strip() if len(fields) > 5 else ''
            
            # Map result flags to standard format
            mapped_flags = self.FLAG_MAP.get(flags, flags)

            # Store result in database
            self.db_manager.add_result(
                self.current_patient_id,
                test_code,
                value,
                unit,
                mapped_flags
            )

            self.log_info(f"Stored result for test {test_code}: {value} {unit} {mapped_flags}")

            # Update GUI if callback exists
            if self.gui_callback and hasattr(self.gui_callback, 'update_result'):
                result_info = {
                    'test_code': test_code,
                    'value': value,
                    'unit': unit,
                    'flags': mapped_flags,
                    'patient_id': self.current_patient_id
                }
                
                try:
                    asyncio.get_event_loop().call_soon_threadsafe(
                        self.gui_callback.update_result,
                        result_info
                    )
                except Exception as e:
                    self.log_error(f"Error updating GUI with result: {e}")

        except Exception as e:
            self.log_error(f"Error processing result: {e}")

    async def handle_comment(self, fields):
        """Handle comment record"""
        self.log_info(f"Comment Record: {fields}")
        self.full_message_payload.append('|'.join(fields))

    async def handle_manufacturer_info(self, fields):
        """Handle manufacturer-specific information"""
        self.log_info("Processing manufacturer information record")
        # Process any Beckman-specific information here

    async def handle_terminator(self, fields):
        """Handle terminator record"""
        self.log_info("Processing terminator record")
        
        # Process any pending results
        for result in self.pending_results:
            try:
                self.db_manager.add_result(
                    self.current_patient_id,
                    result['test_code'],
                    result['value'],
                    result['unit'],
                    result['flags']
                )
            except Exception as e:
                self.log_error(f"Error processing pending result: {e}")
        
        self.pending_results = []
        
        # Trigger real-time sync if available
        if hasattr(self, 'sync_manager') and self.sync_manager and self.current_patient_id:
            try:
                asyncio.create_task(self.sync_manager.sync_patient_realtime(self.current_patient_id))
            except Exception as e:
                self.log_error(f"Error triggering real-time sync: {e}")
        
        # Reset current patient ID
        self.current_patient_id = None