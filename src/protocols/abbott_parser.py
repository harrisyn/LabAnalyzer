"""
Abbott ARCHITECT Protocol Parser for Clinical Chemistry Analyzers
"""
import asyncio
from datetime import datetime
import re
import xml.etree.ElementTree as ET
import base64
from .base_parser import BaseParser

class AbbottParser(BaseParser):
    """
    Parser for Abbott ARCHITECT analyzers using POCT1-A protocol (XML-based)
    Supports c4000, c8000, i1000, i2000 series analyzers
    """
    # POCT1-A Message Types
    MSG_TYPES = {
        "REQ": "Request",
        "OBS": "Observation",
        "EVT": "Event",
        "DIR": "Directory",
        "ACK": "Acknowledgment",
        "NAK": "Negative Acknowledgment"
    }
    
    # Abbott-specific control characters
    STX = b'\x02'  # Start of Text
    ETX = b'\x03'  # End of Text
    EOT = b'\x04'  # End of Transmission
    ENQ = b'\x05'  # Enquiry
    ACK = b'\x06'  # Acknowledge
    NAK = b'\x15'  # Negative Acknowledge
    
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
        self.in_message = False
        self.xml_buffer = []
        self.gui_callback = gui_callback
        self.sync_manager = None
        self.message_id = 0
        
    def set_sync_manager(self, sync_manager):
        """
        Set the sync manager for real-time synchronization
        
        Args:
            sync_manager: SyncManager instance
        """
        self.sync_manager = sync_manager
        self.log_info("Sync manager connected to Abbott parser")
    
    async def process_data(self, data: bytes):
        """
        Process incoming data from Abbott analyzer
        
        Args:
            data: Raw bytes received from the analyzer
            
        Returns:
            Response bytes if needed, None otherwise
        """
        self.buffer.extend(data)
        
        # Log the raw data received
        self.log_info(f"Received {len(data)} bytes from Abbott ARCHITECT")
        
        # Process POCT1-A protocol messages which may be wrapped in custom Abbott framing
        # First, check for Abbott-specific control characters
        if self.ENQ in self.buffer:
            # Analyzer is requesting to start communication
            self.log_info("Received ENQ from Abbott ARCHITECT analyzer")
            self.buffer.clear()
            return self.ACK  # Acknowledge and allow data to flow
            
        elif self.EOT in self.buffer:
            # End of transmission
            self.log_info("Received EOT from Abbott ARCHITECT analyzer")
            self.buffer.clear()
            self.in_message = False
            self.xml_buffer = []
            return None
            
        # Look for message start/end markers
        while True:
            # If we're not in a message yet, look for STX (start marker)
            if not self.in_message:
                if self.STX not in self.buffer:
                    break  # No start marker yet
                
                # Start of a new message
                stx_pos = self.buffer.find(self.STX)
                self.buffer = self.buffer[stx_pos + 1:]
                self.in_message = True
                self.xml_buffer = []
                
            # If we're in a message, look for ETX (end marker)
            else:
                if self.ETX not in self.buffer:
                    # Message incomplete, store what we have and wait for more
                    try:
                        self.xml_buffer.append(self.buffer.decode('utf-8', errors='replace'))
                        self.buffer = bytearray()
                    except Exception as e:
                        self.log_error(f"Error decoding buffer: {e}")
                    break
                    
                # Found end of message
                etx_pos = self.buffer.find(self.ETX)
                try:
                    # Get the content up to ETX
                    message_part = self.buffer[:etx_pos].decode('utf-8', errors='replace')
                    self.xml_buffer.append(message_part)
                    
                    # Process the complete XML message
                    xml_message = ''.join(self.xml_buffer)
                    asyncio.create_task(self.process_xml_message(xml_message))
                    
                    # Clear buffer up to and including ETX
                    self.buffer = self.buffer[etx_pos + 1:]
                    self.in_message = False
                    self.xml_buffer = []
                    
                    # Acknowledge receipt of message
                    return self.ACK
                    
                except Exception as e:
                    self.log_error(f"Error processing XML message: {e}")
                    self.buffer = self.buffer[etx_pos + 1:]
                    self.in_message = False
                    self.xml_buffer = []
                    return self.NAK
        
        return None  # No immediate response needed
        
    async def process_xml_message(self, xml_content):
        """
        Process a complete XML message from POCT1-A protocol
        
        Args:
            xml_content: Complete XML message as string
        """
        self.log_info("Processing XML message from Abbott ARCHITECT")
        
        try:
            # Remove any invalid XML characters that may have been inserted
            # (Abbott devices sometimes insert non-standard control chars)
            xml_content = self._sanitize_xml(xml_content)
            
            # Parse the XML
            root = ET.fromstring(xml_content)
            
            # Get the POCT1-A namespace
            ns = self._extract_namespace(root)
            ns_dict = {'poct': ns} if ns else {}
            
            # Determine message type
            if ns:
                msg_type_elem = root.find(".//poct:Message", ns_dict)
                msg_type = msg_type_elem.get("MessageType") if msg_type_elem is not None else "Unknown"
            else:
                msg_type_elem = root.find(".//Message")
                msg_type = msg_type_elem.get("MessageType") if msg_type_elem is not None else "Unknown"
                
            self.log_info(f"POCT1-A message type: {msg_type} ({self.MSG_TYPES.get(msg_type, 'Unknown')})")
            
            # Process based on message type
            if msg_type == "OBS":  # Observation results
                await self._process_observation(root, ns_dict)
            elif msg_type == "EVT":  # Event message
                self._process_event(root, ns_dict)
            elif msg_type == "DIR":  # Directory message
                self._process_directory(root, ns_dict)
            else:
                self.log_info(f"Skipping processing of message type: {msg_type}")
                
        except ET.ParseError as e:
            self.log_error(f"XML parse error: {e}")
        except Exception as e:
            self.log_error(f"Error processing XML message: {e}")
            
    def _extract_namespace(self, element):
        """Extract XML namespace from the root element"""
        match = re.search(r'\{(.*?)\}', element.tag)
        return match.group(1) if match else None
            
    def _sanitize_xml(self, xml_content):
        """Remove invalid XML characters"""
        # Replace any ASCII control characters except allowed ones
        sanitized = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F]', '', xml_content)
        return sanitized
            
    async def _process_observation(self, root, ns_dict):
        """Process an observation message containing patient results"""
        self.log_info("Processing observation results")
        
        try:
            # Get patient information first
            patient_info = self._extract_patient_info(root, ns_dict)
            
            # Store full XML message for reference
            full_payload = ET.tostring(root, encoding='unicode')
            
            # Add patient to database
            if patient_info['patient_id']:
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
            else:
                self.log_warning("No patient ID found in observation message")
                
            # Now process test results
            await self._extract_test_results(root, ns_dict)
                
        except Exception as e:
            self.log_error(f"Error processing observation message: {e}")
            
    def _extract_patient_info(self, root, ns_dict):
        """
        Extract patient information from the observation message
        
        Args:
            root: XML root element
            ns_dict: Namespace dictionary
            
        Returns:
            Dictionary with patient information
        """
        try:
            prefix = "poct:" if ns_dict else ""
            
            # Initialize with default values
            patient_info = {
                "patient_id": "",
                "sample_id": "",
                "patient_name": "Unknown",
                "sex": "",
                "date_of_birth": "",
                "age": None,
                "physician": "",
                "address": ""
            }
            
            # Find patient section
            patient_elem = root.find(f".//{prefix}Patient", ns_dict)
            if patient_elem is not None:
                # Extract patient ID
                patient_id_elem = patient_elem.find(f".//{prefix}PatientID", ns_dict)
                if patient_id_elem is not None:
                    patient_info["patient_id"] = patient_id_elem.text or ""
                
                # Extract patient name
                name_elem = patient_elem.find(f".//{prefix}PatientName", ns_dict)
                if name_elem is not None:
                    # Get the parts of the name
                    family_name = name_elem.find(f".//{prefix}FamilyName", ns_dict)
                    given_name = name_elem.find(f".//{prefix}GivenName", ns_dict)
                    middle_name = name_elem.find(f".//{prefix}MiddleName", ns_dict)
                    
                    # Build full name
                    parts = []
                    if given_name is not None and given_name.text:
                        parts.append(given_name.text)
                    if middle_name is not None and middle_name.text:
                        parts.append(f"{middle_name.text[0]}.")
                    if family_name is not None and family_name.text:
                        parts.append(family_name.text)
                        
                    if parts:
                        patient_info["patient_name"] = " ".join(parts)
                
                # Extract date of birth
                dob_elem = patient_elem.find(f".//{prefix}DateOfBirth", ns_dict)
                if dob_elem is not None and dob_elem.text:
                    try:
                        # Parse date in format YYYY-MM-DD
                        dob = datetime.strptime(dob_elem.text, "%Y-%m-%d")
                        patient_info["date_of_birth"] = dob.strftime("%Y-%m-%d")
                        
                        # Calculate age
                        today = datetime.today()
                        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                        patient_info["age"] = age
                    except ValueError:
                        # Handle alternative date formats or invalid dates
                        self.log_warning(f"Could not parse birth date: {dob_elem.text}")
                        patient_info["date_of_birth"] = dob_elem.text
                
                # Extract sex
                sex_elem = patient_elem.find(f".//{prefix}Gender", ns_dict)
                if sex_elem is not None:
                    patient_info["sex"] = sex_elem.text or ""
                    
            # Extract sample ID from observation request info
            request_elem = root.find(f".//{prefix}ObservationRequest", ns_dict)
            if request_elem is not None:
                sample_id_elem = request_elem.find(f".//{prefix}SpecimenID", ns_dict)
                if sample_id_elem is not None:
                    patient_info["sample_id"] = sample_id_elem.text or ""
                    
                # Extract ordering physician
                order_elem = request_elem.find(f".//{prefix}UniversalServiceID", ns_dict)
                if order_elem is not None:
                    physician_elem = order_elem.find(f".//{prefix}OrderingPhysician", ns_dict)
                    if physician_elem is not None:
                        patient_info["physician"] = physician_elem.text or ""
                    
            return patient_info
            
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
            
    async def _extract_test_results(self, root, ns_dict):
        """
        Extract test results from the observation message
        
        Args:
            root: XML root element
            ns_dict: Namespace dictionary
        """
        try:
            if not self.current_patient_id:
                self.log_warning("No current patient ID, cannot store results")
                return
                
            prefix = "poct:" if ns_dict else ""
            
            # Find all test results
            result_elements = root.findall(f".//{prefix}TestResult", ns_dict)
            
            if not result_elements:
                self.log_warning("No test results found in message")
                return
                
            self.log_info(f"Found {len(result_elements)} test results")
            
            for result_elem in result_elements:
                try:
                    # Extract test code and name
                    test_id_elem = result_elem.find(f".//{prefix}TestID", ns_dict)
                    test_code = test_id_elem.text if test_id_elem is not None else "Unknown"
                    
                    test_name_elem = result_elem.find(f".//{prefix}TestName", ns_dict)
                    test_name = test_name_elem.text if test_name_elem is not None else ""
                    
                    # Extract result value
                    value_elem = result_elem.find(f".//{prefix}Value", ns_dict)
                    value = value_elem.text.strip() if value_elem is not None and value_elem.text else ""
                    
                    # Extract unit
                    unit_elem = result_elem.find(f".//{prefix}Unit", ns_dict)
                    unit = unit_elem.text if unit_elem is not None else ""
                    
                    # Extract flags/abnormal flags
                    flags = ""
                    flag_elem = result_elem.find(f".//{prefix}AbnormalFlags", ns_dict)
                    if flag_elem is not None:
                        flags = flag_elem.text if flag_elem.text else ""
                    
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
                    
                    self.log_info(f"Stored result for test {test_code} ({test_name}): {value} {unit} {flags}")
                    
                    # Update GUI if callback exists
                    if self.gui_callback and hasattr(self.gui_callback, 'update_result'):
                        result_info = {
                            'test_code': test_code,
                            'test_name': test_name,
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
                
                except Exception as e:
                    self.log_error(f"Error processing test result: {e}")
            
            # Try to sync this patient's results in real-time if sync manager is available
            if hasattr(self, 'sync_manager') and self.sync_manager:
                try:
                    asyncio.create_task(self.sync_manager.sync_patient_realtime(self.current_patient_id))
                except Exception as e:
                    self.log_error(f"Error triggering real-time sync: {e}")
                    
        except Exception as e:
            self.log_error(f"Error extracting test results: {e}")
    
    def _process_event(self, root, ns_dict):
        """Process an event message"""
        self.log_info("Processing event message")
        prefix = "poct:" if ns_dict else ""
        
        try:
            # Extract event type
            event_elem = root.find(f".//{prefix}Event", ns_dict)
            if event_elem is not None:
                event_type = event_elem.get("Type", "Unknown")
                self.log_info(f"Event type: {event_type}")
                
                # Log device information if present
                device_elem = root.find(f".//{prefix}Device", ns_dict)
                if device_elem is not None:
                    model_elem = device_elem.find(f".//{prefix}Model", ns_dict)
                    serial_elem = device_elem.find(f".//{prefix}SerialNumber", ns_dict)
                    
                    model = model_elem.text if model_elem is not None else "Unknown"
                    serial = serial_elem.text if serial_elem is not None else "Unknown"
                    
                    self.log_info(f"Device: {model}, Serial: {serial}")
        except Exception as e:
            self.log_error(f"Error processing event message: {e}")
    
    def _process_directory(self, root, ns_dict):
        """Process a directory message"""
        self.log_info("Processing directory message")
        # Directory messages may contain lists of available tests or capabilities
        # Could be used for analyzer configuration
    
    def create_ack_response(self, message_id):
        """
        Create an XML acknowledgment message
        
        Args:
            message_id: ID of the message being acknowledged
            
        Returns:
            XML string for the ACK message
        """
        now = datetime.now().isoformat(timespec='seconds')
        
        # Create an acknowledgment message
        ack_message = f"""<?xml version="1.0" encoding="UTF-8"?>
<POCT1A xmlns="http://schemas.pointofcare.org/POCT1-A">
  <Message MessageID="ACK_{message_id}" DeviceID="SERVER" Version="1.0" MessageType="ACK" DeviceTime="{now}">
    <Acknowledgment MessageID="{message_id}" Result="AA" />
  </Message>
</POCT1A>"""
        
        return ack_message
        
    def create_nak_response(self, message_id, error_code="AR", error_message="Message rejected"):
        """
        Create an XML negative acknowledgment message
        
        Args:
            message_id: ID of the message being rejected
            error_code: Error code (default: AR - Application Reject)
            error_message: Error message
            
        Returns:
            XML string for the NAK message
        """
        now = datetime.now().isoformat(timespec='seconds')
        
        # Create a negative acknowledgment message
        nak_message = f"""<?xml version="1.0" encoding="UTF-8"?>
<POCT1A xmlns="http://schemas.pointofcare.org/POCT1-A">
  <Message MessageID="NAK_{message_id}" DeviceID="SERVER" Version="1.0" MessageType="NAK" DeviceTime="{now}">
    <NegativeAcknowledgment MessageID="{message_id}" Result="{error_code}">
      <ErrorMessage>{error_message}</ErrorMessage>
    </NegativeAcknowledgment>
  </Message>
</POCT1A>"""
        
        return nak_message