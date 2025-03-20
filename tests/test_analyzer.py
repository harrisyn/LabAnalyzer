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
    CR = b'\x0D'   # Carriage Return
    LF = b'\x0A'   # Line Feed
    VT = b'\x0B'   # Vertical Tab (HL7)
    FS = b'\x1C'   # File Separator (HL7)
    
    ANALYZER_TYPES = {
        "SYSMEX XN-L": "ASTM",
        "Mindray BS-430": "HL7",
        "HumaCount 5D": "LIS",
        "Roche Cobas": "ASTM",
        "Abbott ARCHITECT": "POCT1A",
        "Siemens Dimension": "ASTM",
        "RESPONSE 920": "RESPONSE",
        "VITROS": "ASTM"
    }
    
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
        
    async def connect(self):
        """Connect to the server"""
        print(f"Connecting to {self.host}:{self.port} as {self.analyzer_type}")
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            print("Connected successfully")
        except Exception as e:
            print(f"Connection failed: {e}")
            raise
        
    async def send_data(self, data: bytes):
        """Send data and wait for acknowledgment"""
        try:
            self.writer.write(data)
            await self.writer.drain()
            
            # Set a timeout for acknowledgment
            try:
                response = await asyncio.wait_for(self.reader.read(1), timeout=5.0)
                return response == self.ACK
            except asyncio.TimeoutError:
                print("Timeout waiting for acknowledgment")
                return False
                
        except Exception as e:
            print(f"Error sending data: {e}")
            return False

    def generate_header(self):
        """Generate a header record based on analyzer type"""
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        
        if self.protocol == "ASTM":
            return f"1H|\\^&|||{self.analyzer_type}|||||HOST||P|1|{timestamp}\r".encode('ascii')
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
        names = ["John Smith", "Jane Doe", "Bob Johnson", "Alice Brown"]
        sexes = ["M", "F"]
        name = random.choice(names)
        sex = random.choice(sexes)
        dob = "19800101"
        
        if self.protocol == "ASTM":
            return f"2P|1||{patient_id}|{patient_id}|{name}||{dob}|{sex}|||||||Dr. House\r".encode('ascii')
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

    def generate_result(self, sequence, test_code, value, unit="g/L", flags="N"):
        """Generate a result record based on analyzer type"""
        if self.protocol == "ASTM":
            return f"{sequence+2}R|{sequence}|^^^{test_code}^^|{value}|{unit}||{flags}||F|||\r".encode('ascii')
        elif self.protocol == "HL7":
            return f"OBX|{sequence}|NM|{test_code}||{value}|{unit}|||||F|||{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}\r".encode('ascii')
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
            return "5L|1|N\r".encode('ascii')
        elif self.protocol == "HL7":
            return "".encode('ascii')  # HL7 doesn't use terminators
        elif self.protocol == "LIS":
            return "L|1\r".encode('ascii')
        elif self.protocol == "POCT1A":
            return "</Message>".encode('ascii')
        elif self.protocol == "RESPONSE":
            return "##END\r".encode('ascii')

    async def run_simulation(self, num_patients=5, results_per_patient=3):
        """Run a complete simulation based on analyzer type"""
        try:
            await self.connect()
            
            for i in range(num_patients):
                patient_id = f"P{random.randint(10000, 99999)}"
                print(f"\nProcessing patient {i+1}/{num_patients} (ID: {patient_id})")
                
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
                for j in range(results_per_patient):
                    test_codes = ["WBC", "RBC", "HGB", "HCT", "PLT"]
                    test = random.choice(test_codes)
                    value = round(random.uniform(1, 15), 2)
                    if not await self.send_data(self.generate_result(j+1, test, value)):
                        print(f"Failed to get result {j+1} acknowledgment")
                        continue
                    await asyncio.sleep(0.1)  # Small delay between results
                
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
    finally:
        # Clean up the event loop
        try:
            loop.close()
        except:
            pass

if __name__ == "__main__":
    main()