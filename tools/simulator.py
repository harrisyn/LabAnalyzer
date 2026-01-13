#!/usr/bin/env python3
"""
LabAnalyzer Simulator
---------------------
Simulates medical analyzers sending realistic data to the LabAnalyzer server.
Reads from the same config location as the LabSync app (LOCALAPPDATA/LabSync/config.json).

Usage:
    python tools/simulator.py                    # Auto-generate all ASTM variants
    python tools/simulator.py --variant2         # Only VARIANT_2 format
    python tools/simulator.py --full-patient     # Only full patient records
    python tools/simulator.py --loop             # Continuous mode
    
ASTM Behavior:
    - By default, generates 4 messages per ASTM analyzer:
      1. VARIANT_1 + Minimal patient
      2. VARIANT_1 + Full patient  
      3. VARIANT_2 + Minimal patient
      4. VARIANT_2 + Full patient
    - Use --variant2 or --full-patient to send only specific format
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

# Test result ranges matching the test_code_mapping.py codes (LIS2-A numeric format)
# Format: code -> {"min": value, "max": value, "unit": "unit", "decimals": int, "name": "description"}

# HEMATOLOGY - Codes 301-499, 950-999
HEMATOLOGY_TESTS = {
    # Complete Blood Count (301-315)
    301: {"min": 11.0, "max": 17.0, "unit": "g/dL", "decimals": 1, "name": "Hemoglobin"},
    302: {"min": 33.0, "max": 45.0, "unit": "%", "decimals": 1, "name": "Hematocrit"},
    303: {"min": 4.0, "max": 11.0, "unit": "10^9/L", "decimals": 2, "name": "WBC"},
    304: {"min": 150, "max": 400, "unit": "10^9/L", "decimals": 0, "name": "Platelet Count"},
    305: {"min": 4.0, "max": 6.0, "unit": "10^12/L", "decimals": 2, "name": "RBC"},
    306: {"min": 11.5, "max": 14.5, "unit": "%", "decimals": 1, "name": "RDW-SD"},
    307: {"min": 11.5, "max": 15.0, "unit": "%", "decimals": 1, "name": "RDW-CV"},
    308: {"min": 80, "max": 100, "unit": "fL", "decimals": 1, "name": "MCV"},
    309: {"min": 27, "max": 32, "unit": "pg", "decimals": 1, "name": "MCH"},
    310: {"min": 32.0, "max": 36.0, "unit": "g/dL", "decimals": 1, "name": "MCHC"},
    311: {"min": 7.0, "max": 12.0, "unit": "fL", "decimals": 1, "name": "MPV"},
    312: {"min": 0.10, "max": 0.50, "unit": "%", "decimals": 2, "name": "PCT"},
    313: {"min": 8.0, "max": 14.0, "unit": "fL", "decimals": 1, "name": "PDW"},
    314: {"min": 50, "max": 150, "unit": "umol/L", "decimals": 1, "name": "Creatinine"},
    315: {"min": 3.0, "max": 7.0, "unit": "mmol/L", "decimals": 1, "name": "Glucose"},
    
    # Differential - Absolute counts (320-336)
    320: {"min": 2.0, "max": 7.5, "unit": "10^9/L", "decimals": 2, "name": "Neutrophils#"},
    321: {"min": 1.0, "max": 4.0, "unit": "10^9/L", "decimals": 2, "name": "Lymphocytes#"},
    322: {"min": 0.2, "max": 1.0, "unit": "10^9/L", "decimals": 2, "name": "Monocytes#"},
    323: {"min": 0.0, "max": 0.5, "unit": "10^9/L", "decimals": 2, "name": "Eosinophils#"},
    324: {"min": 0.0, "max": 0.2, "unit": "10^9/L", "decimals": 2, "name": "Basophils#"},
    326: {"min": 40, "max": 70, "unit": "%", "decimals": 1, "name": "Neutrophils%"},
    327: {"min": 20, "max": 45, "unit": "%", "decimals": 1, "name": "Lymphocytes%"},
    328: {"min": 2, "max": 10, "unit": "%", "decimals": 1, "name": "Monocytes%"},
    329: {"min": 0, "max": 6, "unit": "%", "decimals": 1, "name": "Eosinophils%"},
    330: {"min": 0, "max": 2, "unit": "%", "decimals": 1, "name": "Basophils%"},
    
    # Reticulocyte (340-347)
    340: {"min": 0.5, "max": 2.5, "unit": "%", "decimals": 2, "name": "Reticulocyte%"},
    341: {"min": 20, "max": 100, "unit": "10^9/L", "decimals": 1, "name": "Reticulocyte#"},
    
    # Advanced indices (356-371)
    356: {"min": 8.0, "max": 12.0, "unit": "g/dL", "decimals": 1, "name": "RET-He"},
    357: {"min": 20, "max": 50, "unit": "U/L", "decimals": 0, "name": "AST"},
    
    # QC Codes (950-976) - These appear in every sample
    950: {"min": 0, "max": 100, "unit": "", "decimals": 0, "name": "QC Code 1"},
    951: {"min": 0, "max": 20, "unit": "", "decimals": 0, "name": "QC Code 2"},
    952: {"min": 0, "max": 25, "unit": "", "decimals": 0, "name": "QC Code 3"},
}

# CHEMISTRY - Codes 1001-1299
CHEMISTRY_TESTS = {
    # Liver Function (1001-1015)
    1001: {"min": 35, "max": 52, "unit": "g/L", "decimals": 0, "name": "Albumin"},
    1002: {"min": 7, "max": 56, "unit": "U/L", "decimals": 0, "name": "ALT"},
    1003: {"min": 10, "max": 40, "unit": "U/L", "decimals": 0, "name": "AST"},
    1004: {"min": 40, "max": 150, "unit": "U/L", "decimals": 0, "name": "ALP"},
    1005: {"min": 3.4, "max": 20.5, "unit": "umol/L", "decimals": 1, "name": "Total Bilirubin"},
    1006: {"min": 0, "max": 5.1, "unit": "umol/L", "decimals": 1, "name": "Direct Bilirubin"},
    1007: {"min": 5, "max": 35, "unit": "U/L", "decimals": 0, "name": "GGT"},
    1008: {"min": 60, "max": 80, "unit": "g/L", "decimals": 0, "name": "Total Protein"},
    
    # Renal Function (1020-1028)
    1020: {"min": 2.5, "max": 7.1, "unit": "mmol/L", "decimals": 1, "name": "Urea"},
    1021: {"min": 53, "max": 115, "unit": "umol/L", "decimals": 0, "name": "Creatinine"},
    1022: {"min": 155, "max": 416, "unit": "umol/L", "decimals": 0, "name": "Uric Acid"},
    1023: {"min": 60, "max": 120, "unit": "mL/min", "decimals": 0, "name": "eGFR"},
    
    # Electrolytes (1030-1039)
    1030: {"min": 135, "max": 145, "unit": "mmol/L", "decimals": 1, "name": "Sodium"},
    1031: {"min": 3.5, "max": 5.1, "unit": "mmol/L", "decimals": 1, "name": "Potassium"},
    1032: {"min": 98, "max": 107, "unit": "mmol/L", "decimals": 1, "name": "Chloride"},
    1033: {"min": 2.15, "max": 2.55, "unit": "mmol/L", "decimals": 2, "name": "Calcium"},
    1034: {"min": 0.7, "max": 1.0, "unit": "mmol/L", "decimals": 2, "name": "Magnesium"},
    1035: {"min": 0.8, "max": 1.5, "unit": "mmol/L", "decimals": 2, "name": "Phosphate"},
    1036: {"min": 22, "max": 29, "unit": "mmol/L", "decimals": 0, "name": "CO2/Bicarbonate"},
    
    # Lipid Panel (1040-1050)
    1040: {"min": 3.0, "max": 5.2, "unit": "mmol/L", "decimals": 2, "name": "Total Cholesterol"},
    1041: {"min": 0.5, "max": 1.7, "unit": "mmol/L", "decimals": 2, "name": "Triglycerides"},
    1042: {"min": 0.9, "max": 1.6, "unit": "mmol/L", "decimals": 2, "name": "HDL Cholesterol"},
    1043: {"min": 1.8, "max": 3.5, "unit": "mmol/L", "decimals": 2, "name": "LDL Cholesterol"},
    1044: {"min": 2.0, "max": 5.0, "unit": "", "decimals": 1, "name": "TC/HDL Ratio"},
    
    # Glucose/Diabetes (1060-1069)
    1060: {"min": 3.9, "max": 6.1, "unit": "mmol/L", "decimals": 1, "name": "Glucose"},
    1061: {"min": 20, "max": 42, "unit": "mmol/mol", "decimals": 0, "name": "HbA1c"},
    
    # Cardiac Markers (1070-1081)
    1070: {"min": 0, "max": 14, "unit": "ng/mL", "decimals": 1, "name": "Troponin I"},
    1071: {"min": 0, "max": 0.04, "unit": "ng/mL", "decimals": 3, "name": "Troponin T"},
    1072: {"min": 0, "max": 5, "unit": "ng/mL", "decimals": 1, "name": "CK-MB"},
    1073: {"min": 30, "max": 200, "unit": "U/L", "decimals": 0, "name": "CK"},
    1074: {"min": 100, "max": 400, "unit": "ng/mL", "decimals": 0, "name": "BNP"},
    1075: {"min": 0, "max": 125, "unit": "pg/mL", "decimals": 0, "name": "NT-proBNP"},
    
    # Thyroid Function (1100-1109)
    1100: {"min": 0.4, "max": 4.0, "unit": "mIU/L", "decimals": 2, "name": "TSH"},
    1101: {"min": 12, "max": 22, "unit": "pmol/L", "decimals": 1, "name": "Free T4"},
    1102: {"min": 3.1, "max": 6.8, "unit": "pmol/L", "decimals": 1, "name": "Free T3"},
    1103: {"min": 60, "max": 160, "unit": "nmol/L", "decimals": 0, "name": "Total T4"},
    1104: {"min": 1.2, "max": 2.8, "unit": "nmol/L", "decimals": 1, "name": "Total T3"},
}

# COAGULATION - Codes 2001-2199
COAGULATION_TESTS = {
    # Basic Coagulation (2001-2009)
    2001: {"min": 11.0, "max": 13.5, "unit": "sec", "decimals": 1, "name": "PT"},
    2002: {"min": 0.9, "max": 1.1, "unit": "", "decimals": 2, "name": "INR"},
    2003: {"min": 25, "max": 35, "unit": "sec", "decimals": 1, "name": "APTT"},
    2004: {"min": 14, "max": 21, "unit": "sec", "decimals": 1, "name": "Thrombin Time"},
    
    # Fibrinogen (2010-2016)
    2010: {"min": 2.0, "max": 4.0, "unit": "g/L", "decimals": 2, "name": "Fibrinogen"},
    2011: {"min": 0, "max": 10, "unit": "mg/L", "decimals": 1, "name": "D-Dimer"},
    2012: {"min": 0, "max": 5, "unit": "ug/mL", "decimals": 2, "name": "FDP"},
    
    # Factor Assays (2030-2041)
    2030: {"min": 70, "max": 120, "unit": "%", "decimals": 0, "name": "Factor II"},
    2031: {"min": 70, "max": 130, "unit": "%", "decimals": 0, "name": "Factor V"},
    2032: {"min": 70, "max": 120, "unit": "%", "decimals": 0, "name": "Factor VII"},
    2033: {"min": 70, "max": 150, "unit": "%", "decimals": 0, "name": "Factor VIII"},
    2034: {"min": 70, "max": 120, "unit": "%", "decimals": 0, "name": "Factor IX"},
    2035: {"min": 70, "max": 120, "unit": "%", "decimals": 0, "name": "Factor X"},
}


def calculate_astm_checksum(frame_str):
    """Calculate ASTM checksum for a frame (modulo 256)"""
    total = sum(frame_str.encode('ascii'))
    return f"{total % 256:02X}"


def generate_random_patient(include_demographics=False):
    """
    Generate realistic random patient data
    
    Args:
        include_demographics: If True, generate full patient demographics.
                            If False, only generate minimal IDs (LIS2-A style)
    
    Returns:
        Dictionary with patient information
    """
    if include_demographics:
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
            "full_name": f"^{last_name}^{first_name}",  # ASTM format: ^LASTNAME^FIRSTNAME
            "dob": dob.strftime("%Y%m%d"),
            "dob_hl7": dob.strftime("%Y%m%d"),
            "sex": sex,
            "age": age,
            "physician": random.choice(PHYSICIANS),
            "has_demographics": True
        }
    else:
        # Minimal patient data (LIS2-A VARIANT_1 style)
        return {
            "patient_id": None,  # No patient ID in minimal P record
            "sample_id": str(random.randint(1000, 9999)),
            "first_name": None,
            "last_name": None,
            "full_name": None,
            "dob": None,
            "dob_hl7": None,
            "sex": None,
            "age": None,
            "physician": None,
            "has_demographics": False
        }


def generate_test_results(test_type="hematology"):
    """Generate realistic test results using numeric LIS2-A codes"""
    results = []
    
    # Determine which test dictionary to use
    if test_type == "hematology":
        # Select common hematology tests (include QC codes)
        common_codes = [301, 302, 303, 304, 305, 308, 309, 310, 314, 315, 
                       320, 321, 322, 326, 327, 328, 
                       950, 951, 952]  # Always include QC codes
        selected_codes = random.sample([c for c in common_codes if c not in [950, 951, 952]], 
                                      min(random.randint(5, 12), len(common_codes) - 3))
        selected_codes.extend([950, 951, 952])  # Always add QC codes
        tests = {k: HEMATOLOGY_TESTS[k] for k in selected_codes if k in HEMATOLOGY_TESTS}
        
    elif test_type == "chemistry":
        # Select common chemistry tests
        common_codes = [1001, 1002, 1003, 1004, 1005, 1007, 1020, 1021, 1022,
                       1030, 1031, 1032, 1033, 1040, 1041, 1042, 1043, 1060,
                       950, 951, 952]  # Include QC codes
        selected_codes = random.sample([c for c in common_codes if c not in [950, 951, 952]], 
                                      min(random.randint(6, 15), len(common_codes) - 3))
        selected_codes.extend([950, 951, 952])
        tests = {k: CHEMISTRY_TESTS.get(k, HEMATOLOGY_TESTS.get(k)) for k in selected_codes}
        
    elif test_type == "coagulation":
        # Select coagulation tests
        common_codes = [2001, 2002, 2003, 2004, 2010, 2011, 2030, 2031, 2032, 2033,
                       950, 951, 952]
        selected_codes = random.sample([c for c in common_codes if c not in [950, 951, 952]], 
                                      min(random.randint(4, 8), len(common_codes) - 3))
        selected_codes.extend([950, 951, 952])
        tests = {k: COAGULATION_TESTS.get(k, HEMATOLOGY_TESTS.get(k)) for k in selected_codes}
        
    else:  # comprehensive panel
        # Mix of all types
        hema_codes = random.sample([301, 302, 303, 304, 305, 308, 309, 310, 320, 321, 326, 327], 
                                   random.randint(3, 6))
        chem_codes = random.sample([1001, 1002, 1003, 1020, 1021, 1030, 1031, 1032, 1040, 1041, 1060], 
                                   random.randint(4, 7))
        selected_codes = hema_codes + chem_codes + [950, 951, 952]
        tests = {}
        for k in selected_codes:
            if k in HEMATOLOGY_TESTS:
                tests[k] = HEMATOLOGY_TESTS[k]
            elif k in CHEMISTRY_TESTS:
                tests[k] = CHEMISTRY_TESTS[k]
            elif k in COAGULATION_TESTS:
                tests[k] = COAGULATION_TESTS[k]
    
    # Generate results with occasional "No Result" values
    for idx, test_code in enumerate(sorted(tests.keys()), 1):
        test_info = tests[test_code]
        
        # 10% chance of "No Result" (except for QC codes which always have values)
        if test_code not in [950, 951, 952] and random.random() < 0.10:
            results.append({
                "sequence": idx,
                "code": test_code,
                "value": "No Result",
                "unit": test_info["unit"],
                "flag": "6",  # 6 = No Result flag
                "flag_detail": "^6^IIEM\\^0^NR\\^0^NR\\^0^NR"
            })
        else:
            value = round(random.uniform(test_info["min"], test_info["max"]), test_info["decimals"])
            
            # Determine abnormal flag (more realistic distribution)
            mid = (test_info["min"] + test_info["max"]) / 2
            range_size = test_info["max"] - test_info["min"]
            
            # QC codes use special flags
            if test_code in [950, 951, 952]:
                flag = str(random.choice([0, 5]))  # 0 or 5 for QC
                flag_detail = f"^{flag}^" if flag == "0" else f"^{flag}^||V"
            else:
                if value < test_info["min"] + range_size * 0.15:
                    flag = "1"  # Low
                    flag_detail = "^1^\\^0^\\^0^\\^0^"
                elif value > test_info["max"] - range_size * 0.15:
                    flag = "2"  # High  
                    flag_detail = "^2^\\^0^\\^0^\\^0^"
                else:
                    flag = "0"  # Normal
                    flag_detail = "^0^\\^0^\\^0^\\^0^"
            
            results.append({
                "sequence": idx,
                "code": test_code,
                "value": value,
                "unit": test_info["unit"],
                "flag": flag,
                "flag_detail": flag_detail
            })
    
    return results


class Simulator:
    def __init__(self):
        self.listeners = []
        self.config_path = None
        self.use_variant2 = False
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
                status = "[OK]" if enabled else "[X]"
                print(f"  {i:<4} {port:<8} {analyzer:<20} {protocol:<10} {name:<15} {status}")
        
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
        
        # Determine test type based on analyzer
        if "SYSMEX" in analyzer.upper() or "HUMA" in analyzer.upper() or "MINDRAY" in analyzer.upper():
            test_type = "hematology"
        elif "COAG" in analyzer.upper() or "ACL" in analyzer.upper() or "STA" in analyzer.upper():
            test_type = "coagulation"
        elif "COMPREHENSIVE" in analyzer.upper() or "COMPLETE" in analyzer.upper():
            test_type = "comprehensive"
        else:
            test_type = "chemistry"
        
        # Determine what combinations to send
        explicit_variant = hasattr(self, 'use_variant2') and '--variant2' in sys.argv
        explicit_patient = hasattr(self, 'use_full_patient') and '--full-patient' in sys.argv
        
        # For ASTM: generate all combinations unless explicitly specified
        if "ASTM" in protocol:
            if explicit_variant or explicit_patient:
                # User specified format, only send one message
                variant2 = getattr(self, 'use_variant2', False)
                full_patient = getattr(self, 'use_full_patient', False)
                combinations = [(variant2, full_patient)]
                self.log("MODE", f"Single message: VARIANT_{'2' if variant2 else '1'}, {'Full' if full_patient else 'Minimal'} patient", port)
            else:
                # Send all 4 combinations
                combinations = [
                    (False, False),  # VARIANT_1, minimal patient
                    (False, True),   # VARIANT_1, full patient
                    (True, False),   # VARIANT_2, minimal patient
                    (True, True)     # VARIANT_2, full patient
                ]
                self.log("MODE", "Auto-generating all 4 ASTM combinations (VARIANT_1/2 × Minimal/Full)", port)
            
            for idx, (use_v2, use_full) in enumerate(combinations, 1):
                if len(combinations) > 1:
                    variant_name = "VARIANT_2" if use_v2 else "VARIANT_1"
                    patient_name = "Full" if use_full else "Minimal"
                    self.log("COMBO", f"[{idx}/{len(combinations)}] {variant_name} + {patient_name} Patient", port)
                
                # Generate fresh patient and results for each combination
                patient = generate_random_patient(include_demographics=use_full)
                results = generate_test_results(test_type)
                
                if use_full:
                    self.log("PATIENT", f"Patient: {patient['first_name']} {patient['last_name']} (ID: {patient['patient_id']})", port)
                else:
                    self.log("PATIENT", f"Minimal patient (Sample: {patient['sample_id']})", port)
                
                try:
                    self.log("CONNECT", f"Connecting to 127.0.0.1:{port}...", port)
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(5.0)
                    sock.connect(('127.0.0.1', port))
                    self.log("CONNECT", f"✓ Connected", port)
                    
                    # Temporarily set flags for this specific message
                    old_v2 = getattr(self, 'use_variant2', False)
                    self.use_variant2 = use_v2
                    
                    self.send_astm_message(sock, port, analyzer, patient, results)
                    
                    # Restore original flag
                    self.use_variant2 = old_v2
                    
                    sock.close()
                    self.log("COMPLETE", f"✓ Message sent successfully", port)
                    
                    # Small delay between messages
                    if len(combinations) > 1 and idx < len(combinations):
                        time.sleep(0.5)
                        
                except ConnectionRefusedError:
                    self.log("ERROR", f"✗ Connection REFUSED - Server not listening on port {port}", port)
                except socket.timeout:
                    self.log("ERROR", f"✗ Connection TIMEOUT", port)
                except Exception as e:
                    self.log("ERROR", f"✗ Error: {type(e).__name__}: {e}", port)
                    
        else:
            # Non-ASTM protocols: single message with specified options
            include_demographics = getattr(self, 'use_full_patient', False)
            patient = generate_random_patient(include_demographics=include_demographics)
            results = generate_test_results(test_type)
            
            if include_demographics:
                self.log("PATIENT", f"Generated Patient ID: {patient['patient_id']}", port)
                self.log("PATIENT", f"Name: {patient['first_name']} {patient['last_name']} ({patient['sex']}, Age {patient['age']})", port)
                self.log("PATIENT", f"Sample ID: {patient['sample_id']}", port)
            else:
                self.log("PATIENT", f"Minimal patient record (sample ID only)", port)
                self.log("PATIENT", f"Sample ID: {patient['sample_id']}", port)
            
            try:
                self.log("CONNECT", f"Attempting connection to 127.0.0.1:{port}...", port)
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5.0)
                sock.connect(('127.0.0.1', port))
                self.log("CONNECT", f"✓ Connection established successfully", port)
                
                # Choose protocol based on configuration
                if "HL7" in protocol:
                    self.send_hl7_message(sock, port, analyzer, patient, results)
                elif "LIS" in protocol:
                    # LIS in this app uses HL7 (as per LISParser inheriting HL7Parser)
                    self.send_hl7_message(sock, port, analyzer, patient, results)
                elif "POCT" in protocol or "RESPONSE" in protocol:
                    self.send_astm_message(sock, port, analyzer, patient, results)
                else:
                    self.log("WARN", f"Unknown protocol '{protocol}', defaulting to HL7", port)
                    self.send_hl7_message(sock, port, analyzer, patient, results)
                    
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
        """Send a complete ASTM LIS2-A message with realistic data"""
        self.log("ASTM", "Beginning ASTM LIS2-A transmission sequence", port)
        
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
        instrument_id = "5602030"  # Simulated instrument ID
        
        # Build frames in LIS2-A format
        frames = []
        
        # H Record (Header) - LIS2-A format
        frames.append(f"H|\\^&|||{instrument_id}||||||||LIS2-A|{timestamp}")
        
        # P Record (Patient)
        # Two formats:
        # 1. Minimal (VARIANT_1/LIS2-A): P|1
        # 2. Full (VARIANT_2/Sysmex): P|1||<sample_id>|<patient_id>|<name>|<mother>|<dob>|<sex>|...
        if patient.get("has_demographics", False):
            # Full format with all patient demographics
            # Format: P|seq||sample_id|patient_id|name||dob|sex|||||physician||||||||||||
            frames.append(
                f"P|1||{patient['sample_id']}|{patient['patient_id']}|{patient['full_name']}||{patient['dob']}|{patient['sex']}|||||{patient['physician']}||||||||||||"
            )
        else:
            # Minimal format - patient info will come from O record sample ID
            frames.append(f"P|1")
        
        # O Record (Order) - Build test list based on variant format
        if self.use_variant2:
            # VARIANT_2: ^^^^CODE format (Sysmex XN-L style)
            test_list = "\\".join([f"^^^^{TEST_RESULT_RANGES[r['code']]['name']}" for r in results])
        else:
            # VARIANT_1: ^^^1.0000+CODE+1.0 format (LIS2-A style)
            test_list = "\\".join([f"^^^1.0000+{r['code']:03d}+1.0" for r in results])
        
        rack_position = f"{random.randint(1, 99)} {random.choice('ABCDEFGH')}^{random.randint(1, 9)}^{random.randint(1, 9)}"
        frames.append(f"O|1|{rack_position}||{test_list}|R||19700101005436||||N||||{instrument_id}||||||||||F")
        
        # R Records (Results) - Format based on variant
        for result in results:
            result_timestamp = (datetime.now() - timedelta(seconds=random.randint(30, 300))).strftime("%Y%m%d%H%M%S")
            
            if self.use_variant2:
                # VARIANT_2 format: ^^^^CODE^sequence
                test_code_field = f"^^^^{TEST_RESULT_RANGES[result['code']]['name']}^1"
            else:
                # VARIANT_1 format: ^^^1.0000+CODE+1.0
                test_code_field = f"^^^1.0000+{result['code']:03d}+1.0"
            
            if result["value"] == "No Result":
                # No Result format
                frames.append(
                    f"R|{result['sequence']}|{test_code_field}|No Result|{result['unit']}||"
                    f"{result['flag_detail']}||V|||{result_timestamp}|{result_timestamp}|{instrument_id}"
                )
            else:
                # Normal result format
                frames.append(
                    f"R|{result['sequence']}|{test_code_field}|{result['value']}|{result['unit']}||"
                    f"{result['flag_detail']}||V|||{result_timestamp}|{timestamp}|{instrument_id}"
                )
        
        # L Record (Terminator)
        frames.append("L|1|N")
        
        self.log("ASTM", f"Step 3: Sending {len(frames)} data frames (LIS2-A format)", port)
        
        frame_idx = 0  # LIS2-A uses 0-based frame numbering
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
        self.log("ASTM", "✓ ASTM LIS2-A transmission complete", port)

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
    
    # Parse command-line arguments
    use_full_patient = "--full-patient" in sys.argv or "--full" in sys.argv
    use_loop = "--loop" in sys.argv
    use_variant2 = "--variant2" in sys.argv or "--v2" in sys.argv
    
    sim = Simulator()
    sim.use_full_patient = use_full_patient
    sim.use_variant2 = use_variant2
    
    # Show mode information
    if use_variant2 or use_full_patient:
        if use_variant2:
            print("[FORMAT] ASTM VARIANT_2 only (Sysmex XN-L style: ^^^^CODE^1)\n")
        else:
            print("[FORMAT] ASTM VARIANT_1 only (LIS2-A style: ^^^1.0000+CODE+1.0)\n")
        
        if use_full_patient:
            print("[MODE] Full patient demographics only\n")
        else:
            print("[MODE] Minimal patient records only\n")
    else:
        print("[AUTO MODE] ASTM: Generating all 4 combinations per analyzer")
        print("            (VARIANT_1/2 × Minimal/Full patient)\n")
        print("            Use --variant2 or --full-patient for specific format\n")
    
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
    
    if use_loop:
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
        print("\nTip: Run with --loop for continuous simulation, --full-patient for full demographics.")


if __name__ == "__main__":
    main()
