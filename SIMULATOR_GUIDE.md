# LabAnalyzer Simulator - Comprehensive Test Guide

## Overview
The simulator has been updated to generate realistic LIS2-A format ASTM messages with comprehensive test code coverage matching the expanded test_code_mapping.py.

## Test Coverage

### 🔬 Hematology Tests (Codes 301-499, 950-999)
**Total: 30+ test codes**

#### Complete Blood Count (301-315)
- 301: Hemoglobin (11.0-17.0 g/dL)
- 302: Hematocrit (33.0-45.0 %)
- 303: WBC (4.0-11.0 10^9/L)
- 304: Platelet Count (150-400 10^9/L)
- 305: RBC (4.0-6.0 10^12/L)
- 306-313: RDW, MCV, MCH, MCHC, MPV, PCT, PDW
- 314: Creatinine (50-150 umol/L)
- 315: Glucose (3.0-7.0 mmol/L)

#### Differential Counts (320-336)
- 320-324: Absolute counts (Neutrophils#, Lymphocytes#, Monocytes#, Eosinophils#, Basophils#)
- 326-330: Percentage counts (Neutrophils%, Lymphocytes%, Monocytes%, Eosinophils%, Basophils%)

#### Reticulocytes (340-347)
- 340: Reticulocyte% (0.5-2.5%)
- 341: Reticulocyte# (20-100 10^9/L)

#### Advanced Indices (356-371)
- 356: RET-He (8.0-12.0 g/dL)
- 357: AST (20-50 U/L)

#### QC Codes (950-952) - **Always Included**
- 950: QC Code 1 (0-100)
- 951: QC Code 2 (0-20)
- 952: QC Code 3 (0-25)

---

### 🧪 Chemistry Tests (Codes 1001-1299)
**Total: 40+ test codes**

#### Liver Function (1001-1015)
- 1001: Albumin (35-52 g/L)
- 1002: ALT (7-56 U/L)
- 1003: AST (10-40 U/L)
- 1004: ALP (40-150 U/L)
- 1005: Total Bilirubin (3.4-20.5 umol/L)
- 1006: Direct Bilirubin (0-5.1 umol/L)
- 1007: GGT (5-35 U/L)
- 1008: Total Protein (60-80 g/L)

#### Renal Function (1020-1028)
- 1020: Urea (2.5-7.1 mmol/L)
- 1021: Creatinine (53-115 umol/L)
- 1022: Uric Acid (155-416 umol/L)
- 1023: eGFR (60-120 mL/min)

#### Electrolytes (1030-1039)
- 1030: Sodium (135-145 mmol/L)
- 1031: Potassium (3.5-5.1 mmol/L)
- 1032: Chloride (98-107 mmol/L)
- 1033: Calcium (2.15-2.55 mmol/L)
- 1034: Magnesium (0.7-1.0 mmol/L)
- 1035: Phosphate (0.8-1.5 mmol/L)
- 1036: CO2/Bicarbonate (22-29 mmol/L)

#### Lipid Panel (1040-1050)
- 1040: Total Cholesterol (3.0-5.2 mmol/L)
- 1041: Triglycerides (0.5-1.7 mmol/L)
- 1042: HDL Cholesterol (0.9-1.6 mmol/L)
- 1043: LDL Cholesterol (1.8-3.5 mmol/L)
- 1044: TC/HDL Ratio (2.0-5.0)

#### Glucose/Diabetes (1060-1069)
- 1060: Glucose (3.9-6.1 mmol/L)
- 1061: HbA1c (20-42 mmol/mol)

#### Cardiac Markers (1070-1081)
- 1070: Troponin I (0-14 ng/mL)
- 1071: Troponin T (0-0.04 ng/mL)
- 1072: CK-MB (0-5 ng/mL)
- 1073: CK (30-200 U/L)
- 1074: BNP (100-400 ng/mL)
- 1075: NT-proBNP (0-125 pg/mL)

#### Thyroid Function (1100-1109)
- 1100: TSH (0.4-4.0 mIU/L)
- 1101: Free T4 (12-22 pmol/L)
- 1102: Free T3 (3.1-6.8 pmol/L)
- 1103: Total T4 (60-160 nmol/L)
- 1104: Total T3 (1.2-2.8 nmol/L)

---

### 🩸 Coagulation Tests (Codes 2001-2199)
**Total: 15+ test codes**

#### Basic Coagulation (2001-2009)
- 2001: PT (11.0-13.5 sec)
- 2002: INR (0.9-1.1)
- 2003: APTT (25-35 sec)
- 2004: Thrombin Time (14-21 sec)

#### Fibrinogen (2010-2016)
- 2010: Fibrinogen (2.0-4.0 g/L)
- 2011: D-Dimer (0-10 mg/L)
- 2012: FDP (0-5 ug/mL)

#### Factor Assays (2030-2041)
- 2030: Factor II (70-120%)
- 2031: Factor V (70-130%)
- 2032: Factor VII (70-120%)
- 2033: Factor VIII (70-150%)
- 2034: Factor IX (70-120%)
- 2035: Factor X (70-120%)

---

## LIS2-A Message Format

### Sample Structure
```
H|\^&|||5602030||||||||LIS2-A|20260112183155
P|1
O|1|546 Y^3^5||^^^1.0000+301+1.0\950+1.0\951+1.0\952+1.0|R||19700101005436||||N||||5||||||||||F
R|1|^^^1.0000+301+1.0|89|g/L||^0^\^0^\^0^\^0^||V|||20240509204227|20240509204810|56002030
R|2|^^^1.0000+950+1.0|15|||^5^||V|||20240509204227|20240509204247|56002030
R|3|^^^1.0000+951+1.0|4|||^0^||V|||20240509204227|20240509204247|56002030
R|4|^^^1.0000+952+1.0|20|||^5^||V|||20240509204227|20240509204247|56002030
L|1|N
```

### Key Features
1. **Test Code Format**: `^^^1.0000+<code>+1.0` (e.g., `^^^1.0000+301+1.0`)
2. **Flag System**: 
   - `^0^` = Normal
   - `^1^` = Low
   - `^2^` = High
   - `^5^` = QC flag
   - `^6^IIEM` = No Result
3. **QC Codes**: Always included (950, 951, 952)
4. **"No Result" Support**: 10% chance per test (realistic failure rate)

---

## Usage Examples

### Basic Usage
```bash
python tools/simulator.py
```
This will:
- Read listener configuration from `%LOCALAPPDATA%\LabSync\config.json`
- Generate one test run for each enabled listener
- Use realistic analyzer-specific test panels

### Continuous Mode
```bash
python tools/simulator.py --loop
```
- Runs continuously with 10-second intervals
- Press Ctrl+C to stop

### Test Type Selection (Automatic)
The simulator automatically selects test types based on analyzer name:
- **Hematology**: SYSMEX, HUMA, MINDRAY analyzers
- **Coagulation**: COAG, ACL, STA analyzers
- **Comprehensive**: COMPREHENSIVE, COMPLETE panels
- **Chemistry**: All other analyzers

---

## Realistic Features

### 1. Random Patient Generation
- Realistic Ghanaian/International names
- Ages 18-80
- Random patient IDs and sample IDs

### 2. Abnormal Results
- 15% of results flagged as Low (flag=1)
- 15% of results flagged as High (flag=2)
- 10% "No Result" values (realistic failure rate)

### 3. QC Codes
- Always included in every sample
- Use special flag values (0 or 5)

### 4. Timing
- Realistic result timestamps
- Staggered timestamps for each test (30-300 seconds before transmission)

### 5. Rack Positions
- Realistic format: `546 Y^3^5` (rack, position X, position Y)

---

## Testing Scenarios

### Scenario 1: Basic Hematology Panel
**Analyzer**: SYSMEX XN-L  
**Tests Generated**: CBC (301-315), Differential (320-330), QC (950-952)  
**Expected Results**: ~8-15 tests with QC codes

### Scenario 2: Chemistry Panel
**Analyzer**: COBAS c311  
**Tests Generated**: Liver (1001-1008), Renal (1020-1023), Electrolytes (1030-1036), QC  
**Expected Results**: ~9-18 tests with QC codes

### Scenario 3: Coagulation Panel
**Analyzer**: ACL TOP 500  
**Tests Generated**: Basic Coag (2001-2004), Fibrinogen (2010-2012), Factors (2030-2035), QC  
**Expected Results**: ~7-11 tests with QC codes

### Scenario 4: Comprehensive Panel
**Analyzer**: COMPREHENSIVE PANEL  
**Tests Generated**: Mix of Hematology + Chemistry + QC  
**Expected Results**: ~10-16 tests with QC codes

---

## Validation Checklist

After running the simulator, verify:

1. ✅ All messages parse correctly in the application
2. ✅ Test codes map to human-readable names
3. ✅ Units display correctly
4. ✅ Flags (Normal/High/Low) show properly
5. ✅ "No Result" values handle gracefully
6. ✅ QC codes (950, 951, 952) always present
7. ✅ Database stores all results
8. ✅ Multi-port listeners work independently
9. ✅ ASTM frame buffering handles multi-byte messages
10. ✅ Thread-safe database operations (no race conditions)

---

## Troubleshooting

### Connection Refused
- Ensure LabAnalyzer app is running
- Check that port numbers match in config.json
- Verify firewall isn't blocking connections

### No Tests Displayed
- Check logs for parsing errors
- Verify test codes exist in test_code_mapping.py
- Check database for stored results

### Checksum Errors
- LIS2-A uses modulo 256 checksum
- Verify frame structure matches samples
- Check for encoding issues (ASCII only)

---

## Performance Notes

- Each simulation run takes ~2-5 seconds per listener
- Frame transmission with ACK handshaking
- TCP socket timeout: 5 seconds
- Realistic inter-frame delays

---

## Future Enhancements

Potential additions:
1. Text code format (Sysmex text codes: WBC, RBC, HGB, etc.)
2. More coagulation tests (currently 15 codes, mapping has 85+)
3. Scattergram data generation
4. Patient demographics in P records
5. Multi-sample batches
6. Error condition simulations

---

## Code Structure

```
tools/simulator.py
├── HEMATOLOGY_TESTS (30+ codes: 301-499, 950-999)
├── CHEMISTRY_TESTS (40+ codes: 1001-1299)
├── COAGULATION_TESTS (15+ codes: 2001-2199)
├── generate_test_results() - Smart test selection
├── send_astm_message() - LIS2-A format
└── Simulator class - Multi-port coordination
```

---

## Version History

**v2.0** (Current)
- ✅ LIS2-A format support
- ✅ 85+ test codes across all categories
- ✅ "No Result" handling
- ✅ QC codes always included
- ✅ Realistic flag system
- ✅ Coagulation panel support
- ✅ Comprehensive panel mixing

**v1.0** (Previous)
- Basic ASTM E1394-97
- 20 test codes
- Simple text codes (WBC, RBC, etc.)

---

**Generated by**: LabAnalyzer Development Team  
**Last Updated**: January 2026  
**Compatible with**: LabAnalyzer v2.0+, multi-listeners branch
