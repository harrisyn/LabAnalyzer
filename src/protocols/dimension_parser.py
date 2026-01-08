"""
Siemens Dimension Protocol Parser for Clinical Chemistry Analyzers
"""
import asyncio
from datetime import datetime
import re
from .base_parser import BaseParser

class DimensionParser(BaseParser):
    """
    Parser for Siemens Dimension analyzers using ASTM protocol with Siemens extensions
    Supports Dimension EXL, RxL, Xpand, and Vista systems
    """
    # ASTM message type constants
    TYPE_HEADER = 'H'
    TYPE_PATIENT = 'P'
    TYPE_ORDER = 'O'
    TYPE_RESULT = 'R'
    TYPE_COMMENT = 'C'
    TYPE_TERMINATOR = 'L'
    TYPE_MANUFACTURER = 'M'  # Siemens-specific

    # ASTM delimiters and special characters
    STX = b'\x02'  # Start of Text
    ETX = b'\x03'  # End of Text
    EOT = b'\x04'  # End of Transmission
    ENQ = b'\x05'  # Enquiry
    ACK = b'\x06'  # Acknowledge
    NAK = b'\x15'  # Negative Acknowledge
    FS = b'\x1C'   # Field Separator
    CR = b'\x0D'   # Carriage Return
    LF = b'\x0A'   # Line Feed
    CRLF = CR + LF
    
    # Dimension-specific result flag mappings
    FLAG_MAP = {
        'H': 'High',
        'L': 'Low',
        'LL': 'Critical Low',
        'HH': 'Critical High',
        'A': 'Abnormal',
        'N': 'Normal',
        'I': 'Inconclusive',
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
        self.current_sample_id = None
        self.frame_expected = 1
        self.message_expected = False
        self.gui_callback = gui_callback
        self.sync_manager = None
        
    def set_sync_manager(self, sync_manager):
        """
        Set the sync manager for real-time synchronization
        
        Args:
            sync_manager: SyncManager instance
        """
        self.sync_manager = sync_manager
        self.log_info("Sync manager connected to Dimension parser")
    
    async def process_data(self, data: bytes):
        """
        Process incoming data from Dimension analyzer
        
        Args:
            data: Raw bytes received from the analyzer
            
        Returns:
            Response bytes if needed, None otherwise
        """
        self.buffer.extend(data)
        
        # Log the raw data received (limited to first 100 bytes for clarity)
        preview = data[:min(100, len(data))]
        self.log_info(f"Received {len(data)} bytes from Siemens Dimension: {preview}")
        
        # Check for special control characters
        if self.ENQ in self.buffer:
            # Connection initialization query
            self.log_info("ENQ received - Connection request from analyzer")
            self.buffer.clear()
            return self.ACK  # Respond with ACK to allow data to flow
            
        elif self.EOT in self.buffer:
            # End of transmission
            self.log_info("EOT received - End of transmission")
            self.buffer.clear()
            self.frame_expected = 0
            self.message_expected = False
            return None
            
        # Look for complete ASTM frames
        response = await self.process_frames()
        return response
    
    async def process_frames(self):
        """
        Process ASTM frames in the buffer
        
        Returns:
            Response bytes if needed, None otherwise
        """
        # Look for frame start (STX) and end (ETX) characters
        while self.STX in self.buffer and self.ETX in self.buffer:
            stx_pos = self.buffer.find(self.STX)
            etx_pos = self.buffer.find(self.ETX, stx_pos)
            
            if etx_pos > stx_pos:
                # Extract and process the frame
                frame = self.buffer[stx_pos+1:etx_pos]
                
                try:
                    # Get the frame number (first character after STX)
                    frame_num = int(chr(frame[0]))
                    
                    # Extract the rest of the frame data
                    frame_data = frame[1:]
                    
                    if frame_num != self.frame_expected:
                        self.log_warning(f"Unexpected frame number. Got {frame_num}, expected {self.frame_expected}")
                        # Clear up to ETX and return NAK
                        self.buffer = self.buffer[etx_pos+1:]
                        return self.NAK
                    
                    # Process the frame data
                    self.log_info(f"Processing frame {frame_num}")
                    
                    # Decode the frame data
                    try:
                        frame_text = frame_data.decode('ascii', errors='replace')
                        await self.process_message(frame_text)
                        
                        # Increment expected frame number (wrap around from 7 to 0)
                        self.frame_expected = (self.frame_expected + 1) % 8
                        
                        # Clear processed data from buffer
                        self.buffer = self.buffer[etx_pos+1:]
                        
                        # Respond with ACK
                        return self.ACK
                        
                    except Exception as e:
                        self.log_error(f"Error processing frame: {e}")
                        self.buffer = self.buffer[etx_pos+1:]
                        return self.NAK
                        
                except Exception as e:
                    self.log_error(f"Invalid frame format: {e}")
                    # Skip to after ETX and continue
                    self.buffer = self.buffer[etx_pos+1:]
                    return self.NAK
            else:
                break  # Incomplete frame, wait for more data
        
        return None  # No response needed at this time
    
    async def process_message(self, message_text):
        """
        Process an ASTM message segment
        
        Args:
            message_text: The message text from a frame
        """
        # Split the message into fields
        fields = message_text.split('|')
        
        if not fields or len(fields) < 2:
            self.log_warning("Invalid message format - insufficient fields")
            return
            
        # Get message type (first field)
        message_type = fields[0].strip()
        
        try:
            if message_type == self.TYPE_HEADER:
                self.log_info("Processing header record")
                self._process_header(fields)
                
            elif message_type == self.TYPE_PATIENT:
                self.log_info("Processing patient record")
                await self._process_patient(fields)
                
            elif message_type == self.TYPE_ORDER:
                self.log_info("Processing order record")
                self._process_order(fields)
                
            elif message_type == self.TYPE_RESULT:
                self.log_info("Processing result record")
                await self._process_result(fields)
                
            elif message_type == self.TYPE_COMMENT:
                self.log_info("Processing comment record")
                self._process_comment(fields)
                
            elif message_type == self.TYPE_MANUFACTURER:
                self.log_info("Processing manufacturer-specific record")
                self._process_manufacturer(fields)
                
            elif message_type == self.TYPE_TERMINATOR:
                self.log_info("Processing terminator record")
                self._process_terminator(fields)
                
            else:
                self.log_warning(f"Unknown record type: {message_type}")
                
        except Exception as e:
            self.log_error(f"Error processing message: {e}")
    
    def _process_header(self, fields):
        """
        Process a header record
        
        Args:
            fields: Split fields from the message
        """
        # Fields typically include:
        # H|\\^&|||Dimension^EXL 200^12345^^^LIS||||||P|LIS|20230314123000
        try:
            if len(fields) >= 10:
                # Extract sender info (field 4)
                sender_info = fields[4].split('^') if fields[4] else []
                if len(sender_info) >= 3:
                    instrument = sender_info[0]
                    model = sender_info[1]
                    serial = sender_info[2]
                    self.log_info(f"Message from {instrument} {model}, S/N: {serial}")
                
                # Extract date/time (field 13)
                if len(fields) >= 13:
                    datetime_str = fields[12]
                    if len(datetime_str) >= 14:
                        try:
                            # Parse date in format YYYYMMDDhhmmss
                            dt = datetime.strptime(datetime_str[:14], "%Y%m%d%H%M%S")
                            self.log_info(f"Message timestamp: {dt}")
                        except ValueError:
                            self.log_warning(f"Invalid datetime format: {datetime_str}")
        except Exception as e:
            self.log_error(f"Error processing header: {e}")
    
    async def _process_patient(self, fields):
        """
        Process a patient record
        
        Args:
            fields: Split fields from the message
        """
        # Fields typically include:
        # P|1||123456|SMITH^JOHN||19800101|M|||||||||||||||||||
        try:
            patient_id = ""
            patient_name = "Unknown"
            date_of_birth = ""
            sex = ""
            
            if len(fields) >= 4:
                patient_id = fields[3].strip()
                
            if len(fields) >= 5 and fields[4]:
                name_parts = fields[4].split('^')
                if len(name_parts) >= 2:
                    patient_name = f"{name_parts[1]} {name_parts[0]}"  # Format as "John Smith"
                elif len(name_parts) >= 1:
                    patient_name = name_parts[0]
                    
            if len(fields) >= 7 and fields[6]:
                date_str = fields[6].strip()
                if len(date_str) == 8:  # Format: YYYYMMDD
                    try:
                        date_obj = datetime.strptime(date_str, "%Y%m%d")
                        date_of_birth = date_obj.strftime("%Y-%m-%d")
                    except ValueError:
                        self.log_warning(f"Invalid birth date format: {date_str}")
                        date_of_birth = date_str
                        
            if len(fields) >= 8 and fields[7]:
                sex = fields[7].strip()
                
            # Store patient information
            if patient_id:
                # Store full message for reference
                full_message = '|'.join(fields)
                
                # Add patient to database
                db_patient_id = self.db_manager.add_patient(
                    patient_id,
                    patient_name,
                    date_of_birth,
                    sex,
                    "",  # No physician info in this record
                    full_message,
                    self.current_sample_id or ""
                )
                
                if db_patient_id:
                    self.log_info(f"Patient stored with DB ID: {db_patient_id}")
                    self.current_patient_id = db_patient_id
                    
                    # Update GUI if callback exists
                    if self.gui_callback and hasattr(self.gui_callback, 'update_patient_info'):
                        try:
                            # Create patient info dict for GUI
                            patient_info = {
                                'patient_id': patient_id,
                                'patient_name': patient_name,
                                'date_of_birth': date_of_birth,
                                'sex': sex,
                                'db_id': db_patient_id,
                                'sample_id': self.current_sample_id or ""
                            }
                            
                            asyncio.get_event_loop().call_soon_threadsafe(
                                self.gui_callback.update_patient_info,
                                patient_info
                            )
                        except Exception as e:
                            self.log_error(f"Error updating GUI with patient info: {e}")
                else:
                    self.log_error(f"Failed to store patient with ID: {patient_id}")
            else:
                self.log_warning("No patient ID found in patient record")
                
        except Exception as e:
            self.log_error(f"Error processing patient record: {e}")
    
    def _process_order(self, fields):
        """
        Process an order record
        
        Args:
            fields: Split fields from the message
        """
        # Fields typically include:
        # O|1|123456789|^^^GLU^Glucose|R||20230314123000|||||A||||SERUM||||||||||
        try:
            if len(fields) >= 3:
                # Extract specimen ID from field 3
                self.current_sample_id = fields[2].strip() if fields[2] else None
                self.log_info(f"Sample ID set to: {self.current_sample_id}")
                
            if len(fields) >= 4 and fields[3]:
                # Extract test information
                test_info = fields[3].split('^')
                if len(test_info) >= 4:
                    test_code = test_info[3]
                    test_name = test_info[4] if len(test_info) >= 5 else test_code
                    self.log_info(f"Order for test: {test_code} ({test_name})")
                    
            if len(fields) >= 7 and fields[6]:
                # Extract collection date/time
                collection_time = fields[6].strip()
                if len(collection_time) >= 14:
                    try:
                        # Parse date in format YYYYMMDDhhmmss
                        dt = datetime.strptime(collection_time[:14], "%Y%m%d%H%M%S")
                        self.log_info(f"Sample collection time: {dt}")
                    except ValueError:
                        self.log_warning(f"Invalid datetime format: {collection_time}")
        except Exception as e:
            self.log_error(f"Error processing order record: {e}")
    
    async def _process_result(self, fields):
        """
        Process a result record
        
        Args:
            fields: Split fields from the message
        """
        # Fields typically include:
        # R|1|^^^GLU|120|mg/dL|70^110|H|||F||20230314123000|12345|DIMENSION|COMPLETED
        try:
            if not self.current_patient_id:
                self.log_warning("No current patient ID, cannot store results")
                return
                
            if len(fields) < 5:
                self.log_warning("Incomplete result record")
                return
                
            # Extract test code and name
            test_code = "Unknown"
            test_name = "Unknown"
            
            if fields[2]:
                test_parts = fields[2].split('^')
                if len(test_parts) >= 4:
                    test_code = test_parts[3]
                    test_name = test_code
                    
            # Extract result value
            value = fields[3].strip() if len(fields) >= 4 and fields[3] else ""
            
            # Extract unit
            unit = fields[4].strip() if len(fields) >= 5 and fields[4] else ""
            
            # Extract reference range
            ref_range = ""
            if len(fields) >= 6 and fields[5]:
                ref_range = fields[5].replace('^', '-')
                
            # Extract flags/abnormal flags
            flags = ""
            if len(fields) >= 7 and fields[6]:
                flags = fields[6].strip()
                # Map flags to human-readable form
                if flags in self.FLAG_MAP:
                    flags = self.FLAG_MAP[flags]
            
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
                flags,
                ref_range  # Add reference range as additional info
            )
            
            self.log_info(f"Stored result for test {test_code}: {value} {unit} {flags}")
            
            # Update GUI if callback exists
            if self.gui_callback and hasattr(self.gui_callback, 'update_result'):
                result_info = {
                    'test_code': test_code,
                    'test_name': test_name,
                    'value': value_float if value_float is not None else value,
                    'unit': unit,
                    'flags': flags,
                    'ref_range': ref_range,
                    'patient_id': self.current_patient_id
                }
                
                try:
                    asyncio.get_event_loop().call_soon_threadsafe(
                        self.gui_callback.update_result,
                        result_info
                    )
                except Exception as e:
                    self.log_error(f"Error updating GUI with result: {e}")
            
            # Try to sync this patient's results in real-time if sync manager is available
            if hasattr(self, 'sync_manager') and self.sync_manager:
                try:
                    asyncio.create_task(self.sync_manager.sync_patient_realtime(self.current_patient_id))
                except Exception as e:
                    self.log_error(f"Error triggering real-time sync: {e}")
                    
        except Exception as e:
            self.log_error(f"Error processing result record: {e}")
    
    def _process_comment(self, fields):
        """
        Process a comment record
        
        Args:
            fields: Split fields from the message
        """
        # Fields typically include:
        # C|1|I|Sample comment^^^|G
        try:
            if len(fields) >= 4 and fields[3]:
                comment = fields[3].replace('^', ' ').strip()
                self.log_info(f"Comment: {comment}")
                
                if self.current_patient_id:
                    # Store comment as a special result
                    self.db_manager.add_result(
                        self.current_patient_id,
                        "COMMENT",
                        comment,
                        "",
                        ""
                    )
        except Exception as e:
            self.log_error(f"Error processing comment record: {e}")
    
    def _process_manufacturer(self, fields):
        """
        Process a manufacturer-specific record (Siemens specific)
        
        Args:
            fields: Split fields from the message
        """
        # These records contain Dimension-specific data
        try:
            if len(fields) >= 3:
                manufacturer_code = fields[1].strip() if fields[1] else "Unknown"
                data = fields[2].strip() if fields[2] else ""
                self.log_info(f"Manufacturer-specific data: {manufacturer_code} = {data}")
                
                # Process based on manufacturer code
                if manufacturer_code == "QC":
                    # Quality Control data
                    self.log_info("QC data received")
                    # Store if needed or process for QC tracking
                elif manufacturer_code == "CAL":
                    # Calibration data
                    self.log_info("Calibration data received")
                elif manufacturer_code == "ERR":
                    # Error code
                    self.log_warning(f"Analyzer error: {data}")
        except Exception as e:
            self.log_error(f"Error processing manufacturer record: {e}")
    
    def _process_terminator(self, fields):
        """
        Process a terminator record
        
        Args:
            fields: Split fields from the message
        """
        # Fields typically include:
        # L|1|N
        try:
            if len(fields) >= 3:
                terminator_code = fields[2].strip() if fields[2] else ""
                
                if terminator_code == "N":
                    self.log_info("Normal termination of message")
                elif terminator_code == "E":
                    self.log_warning("Termination with error")
                elif terminator_code == "I":
                    self.log_info("Termination with warning")
                else:
                    self.log_info(f"Message terminated with code: {terminator_code}")
                    
                # Reset current patient after message is complete
                self.current_patient_id = None
                
        except Exception as e:
            self.log_error(f"Error processing terminator record: {e}")