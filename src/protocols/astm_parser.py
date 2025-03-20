"""
ASTM Protocol Parser for Medical Analyzers
"""
from datetime import datetime
import re
import asyncio
import queue
import threading
from typing import Optional, Dict, Any
from .base_parser import BaseParser
from .scattergram_decoder import ScattergramDecoder

class ASTMParser(BaseParser):
    """
    Parser for ASTM protocol data from medical analyzers
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
        self.current_raw_record = None  # Initialize raw record storage
        self.full_message_payload = []  # Store full message
        self.scattergram_decoder = ScattergramDecoder(logger)
        self.gui_callback = gui_callback
        self.sync_manager = None  # Will be set separately
        self.sequence_number = 0
        self.pending_results = []
        
        # Message queue for async processing
        self.message_queue = queue.Queue()
        self.message_processor = None
        self.is_processing = False
        
    def set_sync_manager(self, sync_manager):
        """
        Set the sync manager for real-time synchronization
        
        Args:
            sync_manager: SyncManager instance
        """
        self.sync_manager = sync_manager
        self.log_info("Sync manager connected to ASTM parser")
    
    def start_message_processor(self):
        """Start the message processor thread"""
        if not self.message_processor or not self.message_processor.is_alive():
            self.is_processing = True
            self.message_processor = threading.Thread(target=self._process_message_queue)
            self.message_processor.daemon = True
            self.message_processor.start()
            
    def stop_message_processor(self):
        """Stop the message processor thread"""
        self.is_processing = False
        if self.message_processor:
            self.message_processor.join(timeout=1.0)
            
    def _process_message_queue(self):
        """Process messages from the queue"""
        while self.is_processing:
            try:
                # Get message with timeout to allow checking is_processing flag
                message = self.message_queue.get(timeout=0.5)
                
                # Create event loop for async operations
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    # Process the message
                    loop.run_until_complete(self.process_record(message))
                except Exception as e:
                    self.log_error(f"Error processing message: {e}")
                finally:
                    loop.close()
                    self.message_queue.task_done()
                    
            except queue.Empty:
                continue
            except Exception as e:
                self.log_error(f"Error in message processor: {e}")
                
    async def process_data(self, data: bytes):
        """
        Process incoming ASTM data
        
        Args:
            data: Raw bytes received from the analyzer
        """
        self.buffer.extend(data)
        
        # Log the raw data received
        self.log_info(f"Received {len(data)} bytes: {data!r}")
        
        # Process ASTM control characters
        if self.ENQ in self.buffer:
            # Analyzer is initiating communication
            self.log_info("Received ENQ (Enquiry)")
            # Clear buffer and acknowledge
            self.buffer.clear()
            self.full_message_payload = []  # Reset full message payload
            self.start_message_processor()  # Ensure processor is running
            return self.ACK  # Respond with ACK
            
        elif self.EOT in self.buffer:
            # End of transmission
            self.log_info("Received EOT (End of Transmission)")
            self.buffer.clear()
            self.full_message_payload = []  # Reset full message payload
            return None
            
        # Process message frames
        while self.CR in self.buffer:
            # Find the end of a record
            record_end = self.buffer.index(self.CR)
            
            # Extract the record (exclude CR)
            record = self.buffer[:record_end].decode('ascii', errors='replace')
            
            # Queue message for processing
            self.message_queue.put(record)
            
            # Remove the processed record from buffer
            self.buffer = self.buffer[record_end + 1:]
            
            # After processing a record, we acknowledge
            return self.ACK
            
        return None  # No response needed
    
    async def process_record(self, record: str):
        """
        Process a single ASTM record
        
        Args:
            record: A complete ASTM record string
        """
        if not record:
            return
            
        # Log the record
        self.log_info(f"Processing record: {record}")
        
        # Split the record into fields
        fields = record.split('|')
        
        if not fields[0]:
            self.log_warning(f"Empty record received: {record}")
            return

        # Extract record type and handle sequence numbering
        first_field = fields[0].strip()
        
        # Handle both numbered and unnumbered formats
        if len(first_field) > 1 and first_field[:-1].isdigit():
            # Numbered format (e.g., "1H")
            record_type = first_field[-1]
            sequence = first_field[:-1]
            self.sequence_number = int(sequence)
        else:
            # Unnumbered format (e.g., "H")
            record_type = first_field
            self.sequence_number += 1
            sequence = str(self.sequence_number)
            # Update the first field with the sequence number
            fields[0] = f"{sequence}{record_type}"

        self.log_info(f"Sequence: {sequence}, Record Type: {record_type} ({self.RECORD_TYPES.get(record_type, 'Unknown')})")
        
        # Handle different record types
        handlers = {
            'H': self.handle_header,
            'P': self.handle_patient,
            'O': self.handle_order,
            'R': self.handle_result,
            'C': self.handle_comment,
            'Q': self.handle_query,
            'L': self.handle_terminator
        }
        
        if handler := handlers.get(record_type):
            await handler(fields)
        else:
            self.log_warning(f"Unknown record type: {record_type}")
    
    async def handle_header(self, fields):
        """Handle header record"""
        self.log_info(f"Header Record: {fields}")
        # Header fields typically include sender info, date/time, etc.
        # Format: 1H|\\^&|||Host^1|||||Text||||ASTM|...
        
        # Reset current patient and start new message payload
        self.current_patient_id = None
        self.current_frame_number += 1
        self.full_message_payload = []  # Reset for new message
        self.full_message_payload.append('|'.join(fields))  # Add header to payload
    
    def extract_patient_info(self, fields):
        """
        Extract comprehensive patient information from ASTM Patient record fields
        
        Args:
            fields: The split fields of a patient record
            
        Returns:
            Dictionary containing parsed patient information
        """
        try:
            # Extract patient ID (field 4, index 3)
            patient_id = fields[3].strip() if len(fields) > 3 else ""
            
            # Extract sample number (field 5, index 4)
            sample_id = fields[4].strip() if len(fields) > 4 else ""
            
            # Extract and parse name (field 6, index 5)
            name_field = fields[5].strip() if len(fields) > 5 else ""
            name_parts = name_field.split("^")
            full_name = " ".join(filter(None, name_parts))  # Remove empty strings
            
            # Extract date of birth (field 8, index 7)
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
            
            # Extract sex (field 9, index 8)
            sex = fields[8].strip() if len(fields) > 8 else ""
            
            # Extract physician information (field 15, index 14)
            physician = fields[14].strip() if len(fields) > 14 else ""
            
            # Extract address fields if available
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
    
    async def handle_patient(self, fields):
        """Handle patient record"""
        # Format: 2P|1||PatientID|PID^2|||Sex||Address|...
        self.log_info(f"Patient Record: {fields}")
        
        # Add patient record to full message payload
        self.full_message_payload.append('|'.join(fields))
        
        try:
            # Extract comprehensive patient information
            patient_info = self.extract_patient_info(fields)
            
            # Log detailed patient info
            self.log_info(f"Extracted patient info: Name={patient_info['patient_name']}, "
                         f"ID={patient_info['patient_id']}, Sample ID={patient_info['sample_id']}, "
                         f"Sex={patient_info['sex']}, DOB={patient_info['date_of_birth']}, Age={patient_info['age']}")
            
            # Get the full message payload so far
            full_payload = '\n'.join(self.full_message_payload)
            
            # Store patient in database with raw data
            db_patient_id = self.db_manager.add_patient(
                patient_info['patient_id'],
                patient_info['patient_name'],
                patient_info['date_of_birth'],
                patient_info['sex'],
                patient_info['physician'],
                full_payload,  # Store the full message payload
                patient_info['sample_id']  # Include sample ID
            )
            
            if db_patient_id:
                self.current_patient_id = db_patient_id
                self.log_info(f"Patient stored with DB ID: {db_patient_id} and full payload data")
                
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
            self.log_error(f"Error processing patient record: {e}")
    
    async def handle_order(self, fields):
        """Handle order record"""
        self.log_info(f"Order Record: {fields}")
        
        # Add order record to full message payload
        self.full_message_payload.append('|'.join(fields))
    
    async def handle_result(self, fields):
        """Handle result record"""
        # Format: 3R|1|^^^TEST^^Result|Value|Unit|Reference Range|Flags|...
        self.log_info(f"Result Record: {fields}")
        
        # Add result record to full message payload
        self.full_message_payload.append('|'.join(fields))
        
        # Update patient's raw data with the full message payload so far
        if self.current_patient_id:
            full_payload = '\n'.join(self.full_message_payload)
            # Update the patient record with the latest full payload
            # Pass the database ID directly to ensure we update the existing patient
            self.db_manager.add_patient(
                self.current_patient_id,  # Pass the database ID directly
                None,  # No need to update name
                None,  # No need to update DOB
                None,  # No need to update sex
                None,  # No need to update physician
                full_payload,  # Update the full message payload
                None,  # No need to update sample_id
            )
        
        try:
            if not self.current_patient_id:
                self.log_warning("No current patient ID for result - ensure patient record is processed before results")
                return
                
            sequence = fields[1] if len(fields) > 1 else ""
            test_code_complex = fields[2] if len(fields) > 2 else ""
            value = fields[3] if len(fields) > 3 else ""
            unit = fields[4] if len(fields) > 4 else ""
            flags = fields[6] if len(fields) > 6 else ""
            
            # Extract test code from complex field (format: ^^^^XXXX^1)
            test_code_match = re.search(r'\^\^\^\^([A-Za-z0-9]+)', test_code_complex)
            test_code = test_code_match.group(1) if test_code_match else test_code_complex
            
            # Log the extracted test code for debugging
            self.log_info(f"Extracted test code '{test_code}' from '{test_code_complex}'")
            
            # Try to convert value to float for storage, but keep as string if not possible
            try:
                value_float = float(value)
            except (ValueError, TypeError):
                value_float = None
                
            # Store result in database
            result_id = self.db_manager.add_result(
                self.current_patient_id, 
                test_code, 
                value_float if value_float is not None else value, 
                unit, 
                flags,
                None,  # Keep default timestamp
                sequence  # Pass the sequence for sorting
            )
            
            if result_id:
                self.log_info(f"Result stored with ID: {result_id} for patient ID: {self.current_patient_id}")
            else:
                self.log_error(f"Failed to store result for patient ID: {self.current_patient_id}")
        except Exception as e:
            self.log_error(f"Error processing result record: {e}")
    
    async def handle_comment(self, fields):
        """Handle comment record"""
        self.log_info(f"Comment Record: {fields}")
        
        # Add comment record to full message payload
        self.full_message_payload.append('|'.join(fields))
    
    async def handle_query(self, fields):
        """Handle query record"""
        self.log_info(f"Query Record: {fields}")
        
        # Add query record to full message payload
        self.full_message_payload.append('|'.join(fields))
    
    async def handle_terminator(self, fields):
        """Handle termination record"""
        self.log_info(f"Terminator Record: {fields}")
        
        # Add terminator record to full message payload
        self.full_message_payload.append('|'.join(fields))
        
        # Final update of the patient record with complete message
        if self.current_patient_id:
            full_payload = '\n'.join(self.full_message_payload)
            # Update the patient record with the complete payload
            # Pass the database ID directly to ensure we update the existing patient
            self.db_manager.add_patient(
                self.current_patient_id,  # Pass the database ID directly
                None,  # No need to update name
                None,  # No need to update DOB
                None,  # No need to update sex
                None,  # No need to update physician
                full_payload,  # Update with the complete message payload
                None,  # No need to update sample_id
            )
            
            # Try to sync this patient in real-time if sync manager is available
            if hasattr(self, 'sync_manager') and self.sync_manager:
                try:
                    # Create task to sync in background so we don't block message processing
                    asyncio.create_task(self.sync_manager.sync_patient_realtime(self.current_patient_id))
                except Exception as e:
                    self.log_error(f"Error triggering real-time sync: {e}")
            
            # Process any pending results
            for result in self.pending_results:
                try:
                    self.db_manager.add_result(
                        self.current_patient_id,
                        result['test_code'],
                        result['value'],
                        result['unit'],
                        result['flags'],
                        None,
                        result.get('sequence', '0')
                    )
                except Exception as e:
                    self.log_error(f"Error processing pending result: {e}")
            
            self.pending_results = []
            
            # Reset current patient ID after processing everything
            self.current_patient_id = None
            
        # Reset sequence number for next message
        self.sequence_number = 0
    
    async def process_scattergram(self, data: bytes):
        """
        Process scattergram data from analyzers like SYSMEX XN-L
        
        Args:
            data: Compressed scattergram data
        """
        self.log_info(f"Received scattergram data: {len(data)} bytes")
        
        try:
            # Decompress the scattergram data
            scattergram = self.scattergram_decoder.decompress(data)
            
            # If GUI callback is available, update the display
            if self.gui_callback and hasattr(self.gui_callback, 'update_scattergram'):
                # Schedule the GUI update in the main thread
                asyncio.get_event_loop().call_soon_threadsafe(
                    self.gui_callback.update_scattergram,
                    scattergram
                )
                # Show the scattergram frame if it's hidden
                asyncio.get_event_loop().call_soon_threadsafe(
                    self.gui_callback._show_scattergram
                )
                
            self.log_info("Scattergram processed successfully")
            
        except Exception as e:
            self.log_error(f"Error processing scattergram: {e}")