"""
Analyzer simulator for testing the application with multiple analyzer types
"""
import asyncio
import random
import datetime
import socket
import sys
import xml.etree.ElementTree as ET
import json

class AnalyzerSimulator:
    """Simulates various medical analyzers sending data in their native protocols"""
    
    # Common Control Characters
    ENQ = b'\x05'  # Enquiry
    ACK = b'\x06'  # Acknowledge
    NAK = b'\x15'  # Negative Acknowledge
    EOT = b'\x04'  # End of Transmission
    STX = b'\x02'  # Start of Text
    ETX = b'\x03'  # End of Text
    ETB = b'\x17'  # End of Transmission Block
    CR = b'\x0D'   # Carriage Return
    LF = b'\x0A'   # Line Feed
    VT = b'\x0B'   # Vertical Tab (HL7)
    FS = b'\x1C'   # File Separator (HL7)
    
    ANALYZER_TYPES = {
        "SYSMEX XN-L": "ASTM",
        "SYSMEX XN-550": "ASTM",
        "Mindray BS-430": "HL7",
        "HumaCount 5D": "LIS",
        "Roche Cobas": "ASTM",
        "Abbott ARCHITECT": "POCT1A",
        "Siemens Dimension": "ASTM",
        "RESPONSE 920": "RESPONSE",
        "VITROS": "ASTM"
    }
    
    # Complete list of test codes for SYSMEX analyzers
    SYSMEX_TEST_CODES = [
        "WBC", "RBC", "HGB", "HCT", "MCV", "MCH", "MCHC", "PLT",
        "RDW-SD", "RDW-CV", "PDW", "MPV", "P-LCR", "PCT",
        "NEUT#", "LYMPH#", "MONO#", "EO#", "BASO#",
        "NEUT%", "LYMPH%", "MONO%", "EO%", "BASO%",
        "IG#", "IG%", "MICROR", "MACROR",
        "Microcytosis", "Anemia", "Blasts/Abn_Lympho?", "Left_Shift?",
        "Atypical_Lympho?", "NRBC?", "RBC_Agglutination?", "Turbidity/HGB_Interference?",
        "Iron_Deficiency?", "HGB_Defect?", "Fragments?", "IRBC?",
        "PLT_Clumps?", "Positive_Morph", "Positive_Count"
    ]
    
    # Normal ranges and units for common hematology tests
    TEST_RANGES = {
        "WBC": {"unit": "10*3/uL", "low": 4.0, "high": 11.0, "normal_low": 4.5, "normal_high": 11.0},
        "RBC": {"unit": "10*6/uL", "low": 2.5, "high": 7.5, "normal_low": 4.0, "normal_high": 5.5},
        "HGB": {"unit": "g/dL", "low": 8.0, "high": 20.0, "normal_low": 12.0, "normal_high": 16.0},
        "HCT": {"unit": "%", "low": 25.0, "high": 60.0, "normal_low": 36.0, "normal_high": 46.0},
        "MCV": {"unit": "fL", "low": 60.0, "high": 120.0, "normal_low": 80.0, "normal_high": 100.0},
        "MCH": {"unit": "pg", "low": 20.0, "high": 40.0, "normal_low": 27.0, "normal_high": 33.0},
        "MCHC": {"unit": "g/dL", "low": 30.0, "high": 40.0, "normal_low": 32.0, "normal_high": 36.0},
        "PLT": {"unit": "10*3/uL", "low": 50.0, "high": 700.0, "normal_low": 150.0, "normal_high": 400.0},
        "RDW-SD": {"unit": "fL", "low": 30.0, "high": 50.0, "normal_low": 35.0, "normal_high": 45.0},
        "RDW-CV": {"unit": "%", "low": 10.0, "high": 20.0, "normal_low": 11.5, "normal_high": 14.5},
        "PDW": {"unit": "fL", "low": 8.0, "high": 18.0, "normal_low": 9.0, "normal_high": 17.0},
        "MPV": {"unit": "fL", "low": 6.0, "high": 12.0, "normal_low": 7.5, "normal_high": 11.5},
        "P-LCR": {"unit": "%", "low": 10.0, "high": 50.0, "normal_low": 13.0, "normal_high": 43.0},
        "PCT": {"unit": "%", "low": 0.1, "high": 0.5, "normal_low": 0.19, "normal_high": 0.39},
        "NEUT#": {"unit": "10*3/uL", "low": 1.5, "high": 8.0, "normal_low": 2.0, "normal_high": 7.0},
        "LYMPH#": {"unit": "10*3/uL", "low": 0.5, "high": 4.0, "normal_low": 1.0, "normal_high": 3.0},
        "MONO#": {"unit": "10*3/uL", "low": 0.1, "high": 1.5, "normal_low": 0.2, "normal_high": 0.8},
        "EO#": {"unit": "10*3/uL", "low": 0.0, "high": 0.5, "normal_low": 0.02, "normal_high": 0.3},
        "BASO#": {"unit": "10*3/uL", "low": 0.0, "high": 0.2, "normal_low": 0.0, "normal_high": 0.1},
        "NEUT%": {"unit": "%", "low": 30.0, "high": 85.0, "normal_low": 40.0, "normal_high": 70.0},
        "LYMPH%": {"unit": "%", "low": 10.0, "high": 60.0, "normal_low": 20.0, "normal_high": 40.0},
        "MONO%": {"unit": "%", "low": 2.0, "high": 15.0, "normal_low": 2.0, "normal_high": 8.0},
        "EO%": {"unit": "%", "low": 0.0, "high": 10.0, "normal_low": 1.0, "normal_high": 4.0},
        "BASO%": {"unit": "%", "low": 0.0, "high": 2.0, "normal_low": 0.0, "normal_high": 1.0},
        "IG#": {"unit": "10*3/uL", "low": 0.0, "high": 0.1, "normal_low": 0.0, "normal_high": 0.06},
        "IG%": {"unit": "%", "low": 0.0, "high": 2.0, "normal_low": 0.0, "normal_high": 0.6},
        "MICROR": {"unit": "%", "low": 0.0, "high": 50.0, "normal_low": 0.0, "normal_high": 25.0},
        "MACROR": {"unit": "%", "low": 0.0, "high": 15.0, "normal_low": 0.0, "normal_high": 5.0}
    }
    
    # Flag tests that don't have numeric values but return A/N flags
    FLAG_TESTS = [
        "Microcytosis", "Anemia", "Positive_Morph", "Positive_Count"
    ]
    
    # Suspicion tests that return percentage values (0-100)
    SUSPICION_TESTS = [
        "Blasts/Abn_Lympho?", "Left_Shift?", "Atypical_Lympho?", "NRBC?",
        "RBC_Agglutination?", "Turbidity/HGB_Interference?", "Iron_Deficiency?",
        "HGB_Defect?", "Fragments?", "IRBC?", "PLT_Clumps?"
    ]
    
    # Scattergram tests (PNG files)
    SCATTERGRAM_TESTS = [
        "SCAT_WDF", "SCAT_WDF-CBC", "DIST_RBC", "DIST_PLT"
    ]
    
    def __init__(self, analyzer_type="SYSMEX XN-L", host='127.0.0.1', port=5000):
        """Initialize the simulator with connection settings and analyzer type"""
        if analyzer_type not in self.ANALYZER_TYPES:
            raise ValueError(f"Unsupported analyzer type. Must be one of: {', '.join(self.ANALYZER_TYPES.keys())}")
        
        self.analyzer_type = analyzer_type
        self.protocol = self.ANALYZER_TYPES[analyzer_type]
        self.host = host
        self.port = port
        self.reader = None
        self.writer = None
        self._event_loop = None
        self.frame_number = 1
        
    async def connect(self):
        """Connect to the server"""
        print(f"Connecting to {self.host}:{self.port} as {self.analyzer_type}")
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            print("Connected successfully")
        except Exception as e:
            print(f"Connection failed: {e}")
            raise
        
    async def send_data(self, data: bytes, is_astm_frame=False):
        """Send data and wait for acknowledgment"""
        try:
            # If this is an ASTM frame, add STX, ETX and checksum
            if is_astm_frame and self.protocol == "ASTM":
                framed_data = self._frame_astm_data(data)
                self.writer.write(framed_data)
            else:
                self.writer.write(data)
                
            await self.writer.drain()
            
            # Set a timeout for acknowledgment
            try:
                response = await asyncio.wait_for(self.reader.read(1), timeout=5.0)
                if response == self.ACK:
                    print(f"Received ACK for frame: {data[:20]}...")
                    return True
                elif response == self.NAK:
                    print(f"Received NAK for frame: {data[:20]}...")
                    return False
                else:
                    print(f"Received unknown response: {response}")
                    return False
            except asyncio.TimeoutError:
                print(f"Timeout waiting for acknowledgment for: {data[:20]}...")
                return False
                
        except Exception as e:
            print(f"Error sending data: {e}")
            return False

    def _frame_astm_data(self, data):
        """
        Frame ASTM data with STX, frame number, data, ETX/ETB, and checksum
        
        Format: STX + Frame# + Data + ETX/ETB + Checksum + CR + LF
        """
        # Convert frame number to string (limit to 0-7)
        frame_num = str(self.frame_number % 8)
        
        # Combine frame number and data
        frame_data = frame_num.encode('ascii') + data
        
        # Calculate checksum (sum of ASCII values modulo 256, represented as 2 hex chars)
        checksum = self._calculate_checksum(frame_data + self.ETX)
        checksum_hex = format(checksum, '02X').encode('ascii')
        
        # Build the complete frame
        complete_frame = self.STX + frame_data + self.ETX + checksum_hex + self.CR + self.LF
        
        # Increment frame number for next frame
        self.frame_number += 1
        
        return complete_frame
    
    def _calculate_checksum(self, data):
        """Calculate ASTM checksum - sum of ASCII values modulo 256"""
        return sum(data) % 256

    def generate_header(self):
        """Generate a header record based on analyzer type"""
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        
        if self.protocol == "ASTM":
            if "SYSMEX" in self.analyzer_type:
                serial_number = f"00-{random.randint(10, 99)}"
                instrument_id = f"{random.randint(10000, 99999)}"
                # Example: H|\^&|||XN-550^00-27^20557^^^^BD634545||||||||E1394-97
                return f"H|\\^&|||{self.analyzer_type}^{serial_number}^{instrument_id}^^^^BD{random.randint(100000, 999999)}||||||||E1394-97".encode('ascii')
            else:
                return f"H|\\^&|||{self.analyzer_type}|||||HOST||P|1|{timestamp}".encode('ascii')
        elif self.protocol == "HL7":
            return f"MSH|^~\\&||{self.analyzer_type}||HOST|{timestamp}||ORU^R01|1|P|2.5.1||||||ASCII\r".encode('ascii')
        elif self.protocol == "LIS":
            return f"H|{self.analyzer_type}|{timestamp}|1||||||||||1\r".encode('ascii')
        elif self.protocol == "POCT1A":
            xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Message DeviceID="{self.analyzer_type}" DateTime="{timestamp}" MessageType="OBS">
  <Patient>
    <ID>""".encode('ascii')
            return xml
        elif self.protocol == "RESPONSE":
            return f"##SR#{timestamp}#{self.analyzer_type}#1\r".encode('ascii')
        
    def generate_patient(self, patient_id):
        """Generate a patient record based on analyzer type"""
        names = ["John Smith", "Jane Doe", "Bob Johnson", "Alice Brown", "Samuel Aduko", "Harriet Aduko", "Michael Ntow", "Grace Mensah"]
        sexes = ["M", "F"]
        name = random.choice(names)
        sex = random.choice(sexes)
        dob = f"{random.randint(1950, 2020):04d}{random.randint(1, 12):02d}{random.randint(1, 28):02d}"
        
        # Create name in correct format for ASTM
        if "SYSMEX" in self.analyzer_type:
            # SYSMEX format: ^LASTNAME^FIRSTNAME
            name_parts = name.split()
            if len(name_parts) == 2:
                formatted_name = f"^{name_parts[1]}^{name_parts[0]}"
            else:
                formatted_name = f"^{name}^"
        else:
            # Generic format
            name_parts = name.split()
            if len(name_parts) == 2:
                formatted_name = f"^{name_parts[1]}^{name_parts[0]}"
            else:
                formatted_name = f"^{name}^"
        
        if self.protocol == "ASTM":
            # Example: P|1|||475371|^ADUKO^HARRIET||20050101|F|||||^||||||||||||^^^
            return f"P|1|||{patient_id}|{formatted_name}||{dob}|{sex}|||||^||||||||||||^^^".encode('ascii')
        elif self.protocol == "HL7":
            return f"PID|||{patient_id}||{name}|||||{sex}|||||||||||||||{dob}\r".encode('ascii')
        elif self.protocol == "LIS":
            return f"P|{patient_id}|{name}|{dob}|{sex}||Dr. House\r".encode('ascii')
        elif self.protocol == "POCT1A":
            xml = f"""    <ID>{patient_id}</ID>
    <Name>{name}</Name>
    <DOB>{dob}</DOB>
    <Sex>{sex}</Sex>
  </Patient>""".encode('ascii')
            return xml
        elif self.protocol == "RESPONSE":
            return f"##PD#{patient_id}#{name}#{sex}#{dob}#Dr. House\r".encode('ascii')

    def generate_comment(self):
        """Generate a comment record"""
        if self.protocol == "ASTM":
            return f"C|1||".encode('ascii')
        else:
            return None

    def generate_order(self, patient_id, sequence=1):
        """Generate an order record based on analyzer type"""
        if self.protocol == "ASTM":
            if "SYSMEX" in self.analyzer_type:
                # Create list of test codes
                test_codes = []
                for code in self.SYSMEX_TEST_CODES:
                    test_codes.append(f"^^^^{code}")
                
                # Join with backslash
                test_code_str = "\\".join(test_codes)
                
                # Example: O|1||^^                475371^M|^^^^WBC\^^^^RBC\...
                return f"O|{sequence}||^^                {patient_id}^M|{test_code_str}|||||||N||||||||||||||F".encode('ascii')
            else:
                return f"O|{sequence}|{patient_id}||^^^ALL||||||A||||1".encode('ascii')
        else:
            return None  # Not needed for other protocols in this simulation

    def generate_result(self, sequence, test_code, value=None, unit=None, flags=None):
        """Generate a result record based on analyzer type"""
        current_time = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        
        # If not provided, get default units and generate appropriate values based on test code
        if value is None and test_code in self.TEST_RANGES:
            test_info = self.TEST_RANGES[test_code]
            # Generate a value within normal range 80% of the time, abnormal 20%
            if random.random() < 0.8:  # Normal value
                value = round(random.uniform(test_info["normal_low"], test_info["normal_high"]), 
                             1 if "%" in test_info["unit"] or test_info["normal_high"] > 100 else 2)
                flags = "N"  # Normal
            else:  # Abnormal value
                if random.random() < 0.5:  # Low value
                    value = round(random.uniform(test_info["low"], test_info["normal_low"]), 
                                 1 if "%" in test_info["unit"] or test_info["normal_high"] > 100 else 2)
                    flags = "L"  # Low
                else:  # High value
                    value = round(random.uniform(test_info["normal_high"], test_info["high"]), 
                                 1 if "%" in test_info["unit"] or test_info["normal_high"] > 100 else 2)
                    flags = "H"  # High
            
            if unit is None:
                unit = test_info["unit"]
        
        # Handle flag tests (no numeric value, just A/N flag)
        elif test_code in self.FLAG_TESTS:
            value = ""
            if flags is None:
                flags = "A" if random.random() < 0.2 else "N"  # 20% chance of being Abnormal
            unit = ""
        
        # Handle suspicion tests (0-100 percentage value, no flags)
        elif test_code in self.SUSPICION_TESTS:
            if value is None:
                value = random.randint(0, 100) 
                # Higher values for some common conditions
                if test_code == "Iron_Deficiency?" and random.random() < 0.3:
                    value = random.randint(70, 100)  # More likely to be high
                elif test_code == "PLT_Clumps?" and random.random() < 0.1:
                    value = random.randint(50, 100)  # Sometimes high
            flags = ""
            unit = ""
        
        # Handle scattergram tests (PNG files)
        elif test_code in self.SCATTERGRAM_TESTS:
            # Generate a PNG filename pattern like: PNG&R&20250404&R&2025_04_04_15_30_475371_WDF.PNG
            now = datetime.datetime.now()
            date_part = now.strftime("%Y%m%d")
            time_part = now.strftime("%Y_%m_%d_%H_%M")
            test_part = test_code.split("_")[-1] if "_" in test_code else ""
            
            value = f"PNG&R&{date_part}&R&{time_part}_{sequence}_{test_part}.PNG"
            flags = "N"
            unit = ""
        
        # Default values for anything else
        else:
            if value is None:
                value = round(random.uniform(1, 15), 2)
            if unit is None:
                unit = "g/L"
            if flags is None:
                flags = "N"
                
        # Convert value to string if it's a number
        if isinstance(value, (int, float)):
            value = str(value)
                
        if self.protocol == "ASTM":
            if "SYSMEX" in self.analyzer_type:
                # Example: R|1|^^^^WBC^1|8.76|10*3/uL||N||F||||20250404153018
                return f"R|{sequence}|^^^^{test_code}^1|{value}|{unit}||{flags}||F||||{current_time}".encode('ascii')
            else:
                return f"R|{sequence}|^^^^{test_code}|{value}|{unit}||{flags}|||||||".encode('ascii')
        elif self.protocol == "HL7":
            return f"OBX|{sequence}|NM|{test_code}||{value}|{unit}|||||F|||{current_time}\r".encode('ascii')
        elif self.protocol == "LIS":
            return f"R|{sequence}|{test_code}|{value}|{unit}|{flags}|F\r".encode('ascii')
        elif self.protocol == "POCT1A":
            xml = f"""  <Result>
    <Test>{test_code}</Test>
    <Value>{value}</Value>
    <Unit>{unit}</Unit>
    <Flags>{flags}</Flags>
  </Result>""".encode('ascii')
            return xml
        elif self.protocol == "RESPONSE":
            return f"##RS#{sequence}#{test_code}#{value}#{unit}#{flags}\r".encode('ascii')

    def generate_terminator(self):
        """Generate a terminator record based on analyzer type"""
        if self.protocol == "ASTM":
            return "L|1|N".encode('ascii')
        elif self.protocol == "HL7":
            return "".encode('ascii')  # HL7 doesn't use terminators
        elif self.protocol == "LIS":
            return "L|1\r".encode('ascii')
        elif self.protocol == "POCT1A":
            return "</Message>".encode('ascii')
        elif self.protocol == "RESPONSE":
            return "##END\r".encode('ascii')

    async def run_simulation(self, num_patients=5, results_per_patient=None):
        """Run a complete simulation based on analyzer type"""
        try:
            await self.connect()
            
            for i in range(num_patients):
                patient_id = f"{random.randint(100000, 999999)}"
                print(f"\nProcessing patient {i+1}/{num_patients} (ID: {patient_id})")
                
                # Reset frame number for each patient
                self.frame_number = 1
                
                # For ASTM protocol
                if self.protocol == "ASTM":
                    # Start communication with ENQ
                    if not await self.send_data(self.ENQ):
                        print("Failed to get ENQ acknowledgment")
                        continue
                    
                    # Send header frame
                    if not await self.send_data(self.generate_header(), True):
                        print("Failed to get header acknowledgment")
                        continue
                    
                    # Send patient data frame
                    if not await self.send_data(self.generate_patient(patient_id), True):
                        print("Failed to get patient data acknowledgment")
                        continue
                    
                    # Send comment frame before order
                    comment = self.generate_comment()
                    if comment and not await self.send_data(comment, True):
                        print("Failed to get comment acknowledgment")
                        continue
                    
                    # Send order frame
                    order_frame = self.generate_order(patient_id)
                    if order_frame and not await self.send_data(order_frame, True):
                        print("Failed to get order data acknowledgment")
                        continue
                    
                    # Send another comment frame
                    if comment and not await self.send_data(comment, True):
                        print("Failed to get second comment acknowledgment")
                        continue
                    
                    # Determine which tests to send based on analyzer type
                    if "SYSMEX" in self.analyzer_type:
                        # For SYSMEX, include all the basic CBC parameters and differentials
                        sequence = 1
                        used_test_codes = []
                        
                        # First, send all numeric test results
                        for test_code in self.TEST_RANGES.keys():
                            print(f"Sending result for {test_code}")
                            if not await self.send_data(self.generate_result(sequence, test_code), True):
                                print(f"Failed to get result {sequence} ({test_code}) acknowledgment")
                                continue
                            used_test_codes.append(test_code)
                            sequence += 1
                            await asyncio.sleep(0.05)  # Small delay between results
                        
                        # Next, send flag tests
                        for test_code in self.FLAG_TESTS:
                            print(f"Sending result for {test_code}")
                            if not await self.send_data(self.generate_result(sequence, test_code), True):
                                print(f"Failed to get result {sequence} ({test_code}) acknowledgment")
                                continue
                            used_test_codes.append(test_code)
                            sequence += 1
                            await asyncio.sleep(0.05)
                        
                        # Then send suspicion tests
                        for test_code in self.SUSPICION_TESTS:
                            print(f"Sending result for {test_code}")
                            if not await self.send_data(self.generate_result(sequence, test_code), True):
                                print(f"Failed to get result {sequence} ({test_code}) acknowledgment")
                                continue
                            used_test_codes.append(test_code)
                            sequence += 1
                            await asyncio.sleep(0.05)
                        
                        # Finally send scattergram results
                        for test_code in self.SCATTERGRAM_TESTS:
                            print(f"Sending result for {test_code}")
                            if not await self.send_data(self.generate_result(sequence, test_code), True):
                                print(f"Failed to get result {sequence} ({test_code}) acknowledgment")
                                continue
                            used_test_codes.append(test_code)
                            sequence += 1
                            await asyncio.sleep(0.05)
                            
                    else:
                        # For non-SYSMEX analyzers, just send a random selection of common tests
                        test_codes = ["WBC", "RBC", "HGB", "HCT", "PLT", "NEUT%", "LYMPH%", "MONO%", "EO%", "BASO%"]
                        
                        # Determine how many results to send
                        if results_per_patient is None:
                            num_results = len(test_codes)
                        else:
                            num_results = min(results_per_patient, len(test_codes))
                            
                        for j in range(num_results):
                            test = test_codes[j]
                            if not await self.send_data(self.generate_result(j+1, test), True):
                                print(f"Failed to get result {j+1} acknowledgment")
                                continue
                            await asyncio.sleep(0.05)  # Small delay between results
                    
                    # Send comment frame before terminator
                    if comment and not await self.send_data(comment, True):
                        print("Failed to get final comment acknowledgment")
                        continue
                    
                    # Send terminator
                    if not await self.send_data(self.generate_terminator(), True):
                        print("Failed to get terminator acknowledgment")
                        continue
                    
                    # End transmission
                    await self.send_data(self.EOT)
                    
                # Other protocols remain the same
                else:
                    # Start communication
                    if not await self.send_data(self.ENQ):
                        print("Failed to get ENQ acknowledgment")
                        continue
                    
                    # Send header
                    if not await self.send_data(self.generate_header()):
                        print("Failed to get header acknowledgment")
                        continue
                    
                    # Send patient data
                    if not await self.send_data(self.generate_patient(patient_id)):
                        print("Failed to get patient data acknowledgment")
                        continue
                    
                    # Generate random results
                    test_codes = ["WBC", "RBC", "HGB", "HCT", "PLT"]
                    
                    # Determine how many results to send
                    if results_per_patient is None:
                        num_results = len(test_codes)
                    else:
                        num_results = min(results_per_patient, len(test_codes))
                        
                    for j in range(num_results):
                        test = test_codes[j]
                        if not await self.send_data(self.generate_result(j+1, test)):
                            print(f"Failed to get result {j+1} acknowledgment")
                            continue
                        await asyncio.sleep(0.05)  # Small delay between results
                    
                    # Send terminator
                    if not await self.send_data(self.generate_terminator()):
                        print("Failed to get terminator acknowledgment")
                        continue
                    
                    # End transmission
                    await self.send_data(self.EOT)
                
                # Wait between patients
                await asyncio.sleep(1)
                
        except Exception as e:
            print(f"Simulation error: {e}")
            import traceback
            print(traceback.format_exc())
            
        finally:
            if self.writer:
                try:
                    self.writer.close()
                    await self.writer.wait_closed()
                    print("\nConnection closed properly")
                except Exception as e:
                    print(f"\nError closing connection: {e}")

async def async_main():
    """Async entry point for the simulator"""
    # Print available analyzer types
    print("Available analyzer types:")
    for analyzer in AnalyzerSimulator.ANALYZER_TYPES.keys():
        print(f"- {analyzer}")
    
    # Get analyzer type from user
    analyzer_type = input("\nEnter analyzer type (or press Enter for default SYSMEX XN-L): ").strip()
    if not analyzer_type:
        analyzer_type = "SYSMEX XN-L"
    
    try:
        # First try a basic socket test
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(('127.0.0.1', 5000))
        sock.close()
        
        if result != 0:
            print(f"Failed to connect to server: {result}")
            return
            
        print(f"\nSocket test successful, running {analyzer_type} simulation...")
        simulator = AnalyzerSimulator(analyzer_type=analyzer_type)
        await simulator.run_simulation()
        
    except Exception as e:
        print(f"Error in simulator: {e}")
        import traceback
        print(traceback.format_exc())

def main():
    """Main entry point that sets up the event loop properly"""
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        # Create and set the event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Run the async main function
        loop.run_until_complete(async_main())
    except KeyboardInterrupt:
        print("\nSimulation interrupted by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        print(traceback.format_exc())
    finally:
        # Clean up the event loop
        try:
            loop.close()
        except:
            pass

if __name__ == "__main__":
    main()