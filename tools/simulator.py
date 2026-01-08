#!/usr/bin/env python3
"""
LabAnalyzer Simulator
---------------------
Simulates medical analyzers sending realistic data to the LabAnalyzer server.
Reads from the same config location as the LabSync app (LOCALAPPDATA/LabSync/config.json).
"""

import socket
import time
import json
import random
import threading
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path

# Protocol Constants
STX = b'\x02'
ETX = b'\x03'
EOT = b'\x04'
ENQ = b'\x05'
ACK = b'\x06'
NAK = b'\x15'
ETB = b'\x17'
VT  = b'\x0b'
FS  = b'\x1c'
CR  = b'\r'
LF  = b'\n'

# Sample data for realistic patient generation
FIRST_NAMES_MALE = ["James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph", "Thomas", "Charles",
                    "Kwame", "Kofi", "Yaw", "Kweku", "Kwabena", "Kojo", "Emmanuel", "Isaac", "Daniel", "Samuel"]
FIRST_NAMES_FEMALE = ["Mary", "Patricia", "Jennifer", "Linda", "Elizabeth", "Barbara", "Susan", "Jessica", "Sarah", "Karen",
                      "Ama", "Akua", "Yaa", "Afia", "Abena", "Efua", "Grace", "Esther", "Mercy", "Patience"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
              "Mensah", "Asante", "Owusu", "Amankwah", "Osei", "Boateng", "Adjei", "Agyemang", "Kwarteng", "Appiah"]
PHYSICIANS = ["Dr. Mensah", "Dr. Asante", "Dr. Owusu", "Dr. Boateng", "Dr. Adjei", "Dr. Smith", "Dr. Johnson", "Dr. Williams"]

# Test result ranges for different parameters (realistic clinical ranges)
HEMATOLOGY_TESTS = {
    "WBC": {"min": 4.0, "max": 11.0, "unit": "10^3/uL", "decimals": 2},
    "RBC": {"min": 3.8, "max": 5.8, "unit": "10^6/uL", "decimals": 2},
    "HGB": {"min": 11.5, "max": 17.5, "unit": "g/dL", "decimals": 1},
    "HCT": {"min": 35.0, "max": 50.0, "unit": "%", "decimals": 1},
    "MCV": {"min": 80.0, "max": 100.0, "unit": "fL", "decimals": 1},
    "MCH": {"min": 27.0, "max": 33.0, "unit": "pg", "decimals": 1},
    "MCHC": {"min": 32.0, "max": 36.0, "unit": "g/dL", "decimals": 1},
    "PLT": {"min": 150.0, "max": 400.0, "unit": "10^3/uL", "decimals": 0},
    "RDW": {"min": 11.5, "max": 14.5, "unit": "%", "decimals": 1},
    "MPV": {"min": 7.5, "max": 11.5, "unit": "fL", "decimals": 1},
}

CHEMISTRY_TESTS = {
    "GLU": {"min": 70, "max": 110, "unit": "mg/dL", "decimals": 0},
    "BUN": {"min": 7, "max": 20, "unit": "mg/dL", "decimals": 0},
    "CREA": {"min": 0.6, "max": 1.2, "unit": "mg/dL", "decimals": 2},
    "ALT": {"min": 7, "max": 56, "unit": "U/L", "decimals": 0},
    "AST": {"min": 10, "max": 40, "unit": "U/L", "decimals": 0},
    "CHOL": {"min": 125, "max": 200, "unit": "mg/dL", "decimals": 0},
    "TRIG": {"min": 50, "max": 150, "unit": "mg/dL", "decimals": 0},
    "HDL": {"min": 40, "max": 60, "unit": "mg/dL", "decimals": 0},
    "LDL": {"min": 60, "max": 130, "unit": "mg/dL", "decimals": 0},
    "TP": {"min": 6.0, "max": 8.3, "unit": "g/dL", "decimals": 1},
}


def calculate_astm_checksum(frame_str):
    """Calculate ASTM checksum for a frame (modulo 256)"""
    total = sum(frame_str.encode('ascii'))
    return f"{total % 256:02X}"


def generate_random_patient():
    """Generate realistic random patient data"""
    sex = random.choice(["M", "F"])
    if sex == "M":
        first_name = random.choice(FIRST_NAMES_MALE)
    else:
        first_name = random.choice(FIRST_NAMES_FEMALE)
    
    last_name = random.choice(LAST_NAMES)
    
    # Generate DOB (ages 18-80)
    age = random.randint(18, 80)
    dob = datetime.now() - timedelta(days=age*365 + random.randint(0, 364))
    
    return {
        "patient_id": str(random.randint(100000, 999999)),
        "sample_id": str(random.randint(1000, 9999)),
        "first_name": first_name,
        "last_name": last_name,
        "full_name": f"{last_name}^{first_name}",
        "dob": dob.strftime("%Y%m%d"),
        "dob_hl7": dob.strftime("%Y%m%d"),
        "sex": sex,
        "age": age,
        "physician": random.choice(PHYSICIANS)
    }


def generate_test_results(test_type="hematology"):
    """Generate realistic test results"""
    results = []
    tests = HEMATOLOGY_TESTS if test_type == "hematology" else CHEMISTRY_TESTS
    
    # Randomly select 5-10 tests
    selected_tests = random.sample(list(tests.keys()), min(random.randint(5, 10), len(tests)))
    
    for idx, test_code in enumerate(selected_tests, 1):
        test_info = tests[test_code]
        value = round(random.uniform(test_info["min"], test_info["max"]), test_info["decimals"])
        
        # Determine if value is abnormal
        mid = (test_info["min"] + test_info["max"]) / 2
        range_size = test_info["max"] - test_info["min"]
        if value < test_info["min"] + range_size * 0.1:
            flag = "L"  # Low
        elif value > test_info["max"] - range_size * 0.1:
            flag = "H"  # High
        else:
            flag = "N"  # Normal
        
        results.append({
            "sequence": idx,
            "code": test_code,
            "value": value,
            "unit": test_info["unit"],
            "flag": flag
        })
    
    return results


class Simulator:
    def __init__(self):
        self.listeners = []
        self.config_path = None
        self.load_config()

    def get_config_path(self):
        """Get the config path used by LabSync app (LOCALAPPDATA/LabSync/config.json)"""
        # Primary location: Same as LabSync app
        localappdata = os.getenv('LOCALAPPDATA')
        if localappdata:
            app_config = Path(localappdata) / 'LabSync' / 'config.json'
            if app_config.exists():
                return str(app_config)
        
        # Fallback: Project root config.json
        project_root = Path(__file__).parent.parent / 'config.json'
        if project_root.exists():
            return str(project_root)
        
        # Another fallback: CWD
        cwd_config = Path.cwd() / 'config.json'
        if cwd_config.exists():
            return str(cwd_config)
        
        return None

    def load_config(self):
        self.config_path = self.get_config_path()
        
        if not self.config_path:
            self.log("ERROR", "Could not find config.json in any expected location!")
            self.log("ERROR", "Checked locations:")
            localappdata = os.getenv('LOCALAPPDATA')
            if localappdata:
                self.log("ERROR", f"  1. {Path(localappdata) / 'LabSync' / 'config.json'}")
            self.log("ERROR", f"  2. {Path(__file__).parent.parent / 'config.json'}")
            self.log("ERROR", f"  3. {Path.cwd() / 'config.json'}")
            return

        try:
            self.log("CONFIG", f"Reading configuration from:")
            self.log("CONFIG", f"  {self.config_path}")
            
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            
            # Handle legacy config migration (same logic as Config class)
            if "listeners" not in config:
                if "port" in config:
                    config["listeners"] = [{
                        "port": config.get("port", 5000),
                        "analyzer_type": config.get("analyzer_type", "SYSMEX XN-L"),
                        "protocol": config.get("protocol", "ASTM"),
                        "name": "Default"
                    }]
                else:
                    config["listeners"] = []
            
            self.listeners = config.get('listeners', [])
            
        except FileNotFoundError:
            self.log("ERROR", f"Configuration file not found: {self.config_path}")
        except json.JSONDecodeError as e:
            self.log("ERROR", f"Invalid JSON in configuration file: {e}")
        except Exception as e:
            self.log("ERROR", f"Error loading config: {e}")

    def log(self, prefix, message, port=None):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        port_str = f":{port}" if port else ""
        print(f"[{timestamp}] [{prefix}{port_str}] {message}")

    def print_config_summary(self):
        """Print a detailed summary of loaded configuration"""
        print("\n" + "=" * 70)
        print("  CONFIGURATION SUMMARY")
        print("=" * 70)
        print(f"\n  Config File: {self.config_path}")
        print(f"\n  Loaded Listeners: {len(self.listeners)}")
        print("-" * 70)
        
        if not self.listeners:
            print("  ⚠️  NO LISTENERS CONFIGURED!")
            print("  Please add listeners in the LabSync application settings.")
        else:
            print(f"  {'#':<4} {'Port':<8} {'Analyzer':<20} {'Protocol':<10} {'Name':<15}")
            print("  " + "-" * 60)
            for i, lst in enumerate(self.listeners, 1):
                port = lst.get('port', 'N/A')
                analyzer = lst.get('analyzer_type', 'Unknown')
                protocol = lst.get('protocol', 'Unknown')
                name = lst.get('name', '-')
                enabled = lst.get('enabled', True)
                status = "✓" if enabled else "✗"
                print(f"  {i:<4} {port:<8} {analyzer:<20} {protocol:<10} {name:<15} [{status}]")
        
        print("=" * 70 + "\n")
        
        # Return whether we have valid listeners
        return len(self.listeners) > 0

    def simulate_all(self):
        self.log("SIMULATION", "=" * 60)
        self.log("SIMULATION", "Starting simulation run for all listeners")
        self.log("SIMULATION", "=" * 60)
        
        if not self.listeners:
            self.log("ERROR", "No listeners to simulate. Check your configuration.")
            return
        
        threads = []
        for listener in self.listeners:
            # Skip disabled listeners
            if not listener.get('enabled', True):
                self.log("SKIP", f"Listener on port {listener.get('port')} is disabled")
                continue
                
            t = threading.Thread(target=self.simulate_listener, args=(listener,))
            t.start()
            threads.append(t)
        
        for t in threads:
            t.join()
        
        self.log("SIMULATION", "=" * 60)
        self.log("SIMULATION", "Simulation run complete")
        self.log("SIMULATION", "=" * 60)
            
    def simulate_listener(self, listener):
        port = listener.get('port')
        protocol = listener.get('protocol', 'ASTM').upper()
        analyzer = listener.get('analyzer_type', 'Unknown')
        name = listener.get('name', f"{analyzer}")
        
        self.log("START", f"Initializing simulation", port)
        self.log("INFO", f"Analyzer: {analyzer}", port)
        self.log("INFO", f"Protocol: {protocol}", port)
        self.log("INFO", f"Name: {name}", port)
        self.log("INFO", f"Target: 127.0.0.1:{port}", port)
        
        # Generate patient for this simulation
        patient = generate_random_patient()
        self.log("PATIENT", f"Generated Patient ID: {patient['patient_id']}", port)
        self.log("PATIENT", f"Name: {patient['first_name']} {patient['last_name']} ({patient['sex']}, Age {patient['age']})", port)
        self.log("PATIENT", f"Sample ID: {patient['sample_id']}", port)
        
        try:
            self.log("CONNECT", f"Attempting connection to 127.0.0.1:{port}...", port)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect(('127.0.0.1', port))
            self.log("CONNECT", f"✓ Connection established successfully", port)
            
            # Determine test type based on analyzer
            test_type = "hematology" if "SYSMEX" in analyzer.upper() or "HUMA" in analyzer.upper() else "chemistry"
            results = generate_test_results(test_type)
            self.log("RESULTS", f"Generated {len(results)} test results ({test_type})", port)
            
            # Choose protocol based on configuration
            if "ASTM" in protocol:
                self.send_astm_message(sock, port, analyzer, patient, results)
            elif "HL7" in protocol:
                self.send_hl7_message(sock, port, analyzer, patient, results)
            elif "LIS" in protocol:
                # LIS in this app uses HL7 (as per LISParser inheriting HL7Parser)
                self.send_hl7_message(sock, port, analyzer, patient, results)
            elif "POCT" in protocol or "RESPONSE" in protocol:
                self.send_astm_message(sock, port, analyzer, patient, results)
            else:
                self.log("WARN", f"Unknown protocol '{protocol}', defaulting to ASTM", port)
                self.send_astm_message(sock, port, analyzer, patient, results)
                
            sock.close()
            self.log("COMPLETE", f"✓ Simulation finished successfully", port)
            
        except ConnectionRefusedError:
            self.log("ERROR", f"✗ Connection REFUSED - Server not listening on port {port}", port)
            self.log("ERROR", f"  Make sure the LabAnalyzer app is running and port {port} is configured", port)
        except socket.timeout:
            self.log("ERROR", f"✗ Connection TIMEOUT - No response from 127.0.0.1:{port}", port)
            self.log("ERROR", f"  Server may be overloaded or firewall is blocking", port)
        except OSError as e:
            self.log("ERROR", f"✗ Network ERROR: {e}", port)
        except Exception as e:
            self.log("ERROR", f"✗ Unexpected error: {type(e).__name__}: {e}", port)

    def send_astm_message(self, sock, port, analyzer, patient, results):
        """Send a complete ASTM message with realistic data"""
        self.log("ASTM", "Beginning ASTM transmission sequence", port)
        
        # 1. Send ENQ
        self.log("ASTM", "Step 1: Sending ENQ (Enquiry)", port)
        sock.send(ENQ)
        
        # 2. Wait for ACK
        try:
            resp = sock.recv(1)
            if resp == ACK:
                self.log("ASTM", "Step 2: Received ACK - Proceeding with data", port)
            elif resp == NAK:
                self.log("ASTM", "Step 2: Received NAK - Server rejected, aborting", port)
                return
            else:
                self.log("ASTM", f"Step 2: Unexpected response: {resp!r} - Aborting", port)
                return
        except socket.timeout:
            self.log("ASTM", "Step 2: TIMEOUT waiting for ACK - Aborting", port)
            return

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        
        # Build frames
        frames = []
        
        # H Record (Header)
        frames.append(f"H|\\^&|||{analyzer}^^^HOST|||||{analyzer}||P|1|{timestamp}")
        
        # P Record (Patient)
        frames.append(f"P|1|{patient['patient_id']}|{patient['patient_id']}|{patient['patient_id']}|"
                     f"{patient['full_name']}||{patient['dob']}|{patient['sex']}|"
                     f"||||{patient['physician']}")
        
        # O Record (Order)
        frames.append(f"O|1|{patient['sample_id']}||^^^ALL|||{timestamp}|||||||||||||||||||F")
        
        # R Records (Results)
        for result in results:
            frames.append(f"R|{result['sequence']}|^^^{result['code']}|{result['value']}|"
                         f"{result['unit']}||{result['flag']}||F|||{timestamp}")
        
        # L Record (Terminator)
        frames.append("L|1|N")
        
        self.log("ASTM", f"Step 3: Sending {len(frames)} data frames", port)
        
        frame_idx = 1
        for content in frames:
            seq = str(frame_idx % 8)
            data_to_sum = seq + content + '\x03'
            cs = calculate_astm_checksum(data_to_sum)
            
            frame_bytes = STX + seq.encode('ascii') + content.encode('ascii') + ETX + cs.encode('ascii') + CR + LF
            
            # Determine record type for logging
            record_type = content[0] if content else "?"
            record_desc = {"H": "Header", "P": "Patient", "O": "Order", "R": "Result", "L": "Terminator"}.get(record_type, "Unknown")
            
            sock.send(frame_bytes)
            self.log("ASTM", f"  Frame {frame_idx}: {record_desc} record sent ({len(frame_bytes)} bytes)", port)
            
            # Wait for ACK
            try:
                resp = sock.recv(1)
                if resp != ACK:
                    self.log("ASTM", f"  Frame {frame_idx}: Expected ACK, got {resp!r}", port)
            except socket.timeout:
                self.log("ASTM", f"  Frame {frame_idx}: Timeout waiting for ACK", port)
            
            frame_idx += 1

        # 4. Send EOT
        self.log("ASTM", "Step 4: Sending EOT (End of Transmission)", port)
        sock.send(EOT)
        self.log("ASTM", "✓ ASTM transmission complete", port)

    def send_hl7_message(self, sock, port, analyzer, patient, results):
        """Send a complete HL7 ORU^R01 message with realistic data"""
        self.log("HL7", "Beginning HL7 v2.3.1 transmission", port)
        
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        msg_control_id = random.randint(100000, 999999)
        
        segments = []
        
        # MSH - Message Header
        segments.append(f"MSH|^~\\&|{analyzer}|LAB|LABSYNC|LIS|{timestamp}||ORU^R01|{msg_control_id}|P|2.3.1")
        self.log("HL7", "  Segment: MSH (Header) - Message Control ID: " + str(msg_control_id), port)
        
        # PID - Patient Identification
        segments.append(f"PID|1||{patient['patient_id']}||{patient['full_name']}||{patient['dob_hl7']}|{patient['sex']}")
        self.log("HL7", f"  Segment: PID (Patient) - ID: {patient['patient_id']}", port)
        
        # OBR - Observation Request
        segments.append(f"OBR|1||{patient['sample_id']}|00001^Automated Analysis^L|||{timestamp}||||||||{patient['physician']}")
        self.log("HL7", f"  Segment: OBR (Order) - Sample: {patient['sample_id']}", port)
        
        # OBX - Observation Results
        for result in results:
            flag_map = {"N": "N", "H": "H", "L": "L"}
            segments.append(f"OBX|{result['sequence']}|NM|{result['code']}^{result['code']}||"
                          f"{result['value']}|{result['unit']}||{flag_map.get(result['flag'], 'N')}||F")
        
        self.log("HL7", f"  Segments: {len(results)} OBX (Results)", port)
        
        message = "\r".join(segments)
        
        # Wrap in MLLP framing: VT + message + FS + CR
        framed_msg = VT + message.encode('ascii') + FS + CR
        
        self.log("HL7", f"Sending HL7 message ({len(framed_msg)} bytes)", port)
        sock.send(framed_msg)
        
        # Wait for ACK (optional in some implementations)
        try:
            sock.settimeout(2.0)
            resp = sock.recv(1024)
            if resp:
                self.log("HL7", f"Received response: {len(resp)} bytes", port)
        except socket.timeout:
            self.log("HL7", "No ACK received (timeout) - This may be normal", port)
        
        self.log("HL7", "✓ HL7 transmission complete", port)


def main():
    print("\n" + "=" * 70)
    print("  LabAnalyzer Protocol Simulator")
    print("  Generates realistic analyzer data for testing")
    print("=" * 70 + "\n")
    
    sim = Simulator()
    
    # Print configuration summary and verify
    if not sim.print_config_summary():
        print("ERROR: No listeners configured. Please configure listeners in LabSync.")
        sys.exit(1)
    
    # Ask for confirmation before starting
    if len(sys.argv) == 1:
        response = input("Press ENTER to start simulation, or 'q' to quit: ").strip().lower()
        if response == 'q':
            print("Simulation cancelled.")
            sys.exit(0)
    
    if len(sys.argv) > 1 and sys.argv[1] == "--loop":
        print("Running in CONTINUOUS mode (Ctrl+C to stop)\n")
        try:
            iteration = 1
            while True:
                print(f"\n{'='*70}")
                print(f"  ITERATION {iteration}")
                print(f"{'='*70}\n")
                sim.simulate_all()
                print("\nWaiting 10 seconds before next iteration...")
                time.sleep(10)
                iteration += 1
        except KeyboardInterrupt:
            print("\n\nSimulation stopped by user.")
    else:
        sim.simulate_all()
        print("\nTip: Run with --loop argument for continuous simulation.")


if __name__ == "__main__":
    main()
