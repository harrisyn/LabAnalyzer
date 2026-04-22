"""
Test code mappings and unit normalization for LIS2-A and other ASTM protocols.
Comprehensive mapping for hematology, chemistry, coagulation, and specialty tests.
"""

# =============================================================================
# HEMATOLOGY CODES (301-499, 950-999)
# =============================================================================
HEMATOLOGY_CODES = {
    # Complete Blood Count (CBC) - Primary Codes
    "301": {"name": "WBC", "full_name": "White Blood Cell Count", "unit": "10^9/L", "category": "CBC"},
    "302": {"name": "RBC", "full_name": "Red Blood Cell Count", "unit": "10^12/L", "category": "CBC"},
    "303": {"name": "HGB", "full_name": "Hemoglobin", "unit": "g/L", "category": "CBC"},
    "304": {"name": "HCT", "full_name": "Hematocrit", "unit": "%", "category": "CBC"},
    "305": {"name": "MCV", "full_name": "Mean Corpuscular Volume", "unit": "fL", "category": "CBC"},
    "306": {"name": "MCH", "full_name": "Mean Corpuscular Hemoglobin", "unit": "pg", "category": "CBC"},
    "307": {"name": "MCHC", "full_name": "Mean Corpuscular Hemoglobin Concentration", "unit": "g/dL", "category": "CBC"},
    "308": {"name": "PLT", "full_name": "Platelet Count", "unit": "10^9/L", "category": "CBC"},
    "309": {"name": "RDW-CV", "full_name": "Red Cell Distribution Width CV", "unit": "%", "category": "CBC"},
    "310": {"name": "RDW-SD", "full_name": "Red Cell Distribution Width SD", "unit": "fL", "category": "CBC"},
    "311": {"name": "MPV", "full_name": "Mean Platelet Volume", "unit": "fL", "category": "CBC"},
    "312": {"name": "PDW", "full_name": "Platelet Distribution Width", "unit": "fL", "category": "CBC"},
    "313": {"name": "PCT", "full_name": "Plateletcrit", "unit": "%", "category": "CBC"},
    "314": {"name": "P-LCR", "full_name": "Platelet Large Cell Ratio", "unit": "%", "category": "CBC"},
    "315": {"name": "P-LCC", "full_name": "Platelet Large Cell Count", "unit": "10^9/L", "category": "CBC"},
    
    # Differential - Percentages
    "320": {"name": "NEUT%", "full_name": "Neutrophils Percentage", "unit": "%", "category": "Differential"},
    "321": {"name": "LYMPH%", "full_name": "Lymphocytes Percentage", "unit": "%", "category": "Differential"},
    "322": {"name": "MONO%", "full_name": "Monocytes Percentage", "unit": "%", "category": "Differential"},
    "323": {"name": "EO%", "full_name": "Eosinophils Percentage", "unit": "%", "category": "Differential"},
    "324": {"name": "BASO%", "full_name": "Basophils Percentage", "unit": "%", "category": "Differential"},
    "325": {"name": "LUC%", "full_name": "Large Unstained Cells Percentage", "unit": "%", "category": "Differential"},
    "326": {"name": "IG%", "full_name": "Immature Granulocytes Percentage", "unit": "%", "category": "Differential"},
    "327": {"name": "LYMPH#", "full_name": "Lymphocytes Absolute", "unit": "10^9/L", "category": "Differential"},
    "328": {"name": "MONO#", "full_name": "Monocytes Absolute", "unit": "10^9/L", "category": "Differential"},
    "329": {"name": "EO#", "full_name": "Eosinophils Absolute", "unit": "10^9/L", "category": "Differential"},
    
    # Differential - Absolute Counts
    "330": {"name": "NEUT#", "full_name": "Neutrophils Absolute", "unit": "10^9/L", "category": "Differential"},
    "331": {"name": "LYMPH#", "full_name": "Lymphocytes Absolute", "unit": "10^9/L", "category": "Differential"},
    "332": {"name": "MONO#", "full_name": "Monocytes Absolute", "unit": "10^9/L", "category": "Differential"},
    "333": {"name": "EO#", "full_name": "Eosinophils Absolute", "unit": "10^9/L", "category": "Differential"},
    "334": {"name": "BASO#", "full_name": "Basophils Absolute", "unit": "10^9/L", "category": "Differential"},
    "335": {"name": "LUC#", "full_name": "Large Unstained Cells Absolute", "unit": "10^9/L", "category": "Differential"},
    "336": {"name": "IG#", "full_name": "Immature Granulocytes Absolute", "unit": "10^9/L", "category": "Differential"},
    
    # Reticulocytes
    "340": {"name": "RET%", "full_name": "Reticulocyte Percentage", "unit": "%", "category": "Reticulocyte"},
    "341": {"name": "RET#", "full_name": "Reticulocyte Absolute", "unit": "10^12/L", "category": "Reticulocyte"},
    "342": {"name": "IRF", "full_name": "Immature Reticulocyte Fraction", "unit": "%", "category": "Reticulocyte"},
    "343": {"name": "LFR", "full_name": "Low Fluorescence Ratio", "unit": "%", "category": "Reticulocyte"},
    "344": {"name": "MFR", "full_name": "Medium Fluorescence Ratio", "unit": "%", "category": "Reticulocyte"},
    "345": {"name": "HFR", "full_name": "High Fluorescence Ratio", "unit": "%", "category": "Reticulocyte"},
    "346": {"name": "RET-He", "full_name": "Reticulocyte Hemoglobin Equivalent", "unit": "pg", "category": "Reticulocyte"},
    "347": {"name": "Delta-He", "full_name": "Delta Hemoglobin Equivalent", "unit": "pg", "category": "Reticulocyte"},
    
    # NRBC (Nucleated Red Blood Cells)
    "350": {"name": "NRBC%", "full_name": "Nucleated RBC Percentage", "unit": "%", "category": "NRBC"},
    "351": {"name": "NRBC#", "full_name": "Nucleated RBC Absolute", "unit": "10^9/L", "category": "NRBC"},
    
    # Extended Differential / Atypical Cells
    "360": {"name": "ATYP%", "full_name": "Atypical Lymphocytes Percentage", "unit": "%", "category": "Extended"},
    "361": {"name": "ATYP#", "full_name": "Atypical Lymphocytes Absolute", "unit": "10^9/L", "category": "Extended"},
    "362": {"name": "BLAST%", "full_name": "Blasts Percentage", "unit": "%", "category": "Extended"},
    "363": {"name": "BLAST#", "full_name": "Blasts Absolute", "unit": "10^9/L", "category": "Extended"},
    "364": {"name": "BAND%", "full_name": "Band Neutrophils Percentage", "unit": "%", "category": "Extended"},
    "365": {"name": "BAND#", "full_name": "Band Neutrophils Absolute", "unit": "10^9/L", "category": "Extended"},
    "366": {"name": "META%", "full_name": "Metamyelocytes Percentage", "unit": "%", "category": "Extended"},
    "367": {"name": "META#", "full_name": "Metamyelocytes Absolute", "unit": "10^9/L", "category": "Extended"},
    "368": {"name": "MYELO%", "full_name": "Myelocytes Percentage", "unit": "%", "category": "Extended"},
    "369": {"name": "MYELO#", "full_name": "Myelocytes Absolute", "unit": "10^9/L", "category": "Extended"},
    "370": {"name": "PROMYELO%", "full_name": "Promyelocytes Percentage", "unit": "%", "category": "Extended"},
    "371": {"name": "PROMYELO#", "full_name": "Promyelocytes Absolute", "unit": "10^9/L", "category": "Extended"},
    
    # Advanced Sysmex Parameters (PLT-F, IPF)
    "380": {"name": "IPF%", "full_name": "Immature Platelet Fraction", "unit": "%", "category": "Advanced"},
    "381": {"name": "IPF#", "full_name": "Immature Platelet Fraction Absolute", "unit": "10^9/L", "category": "Advanced"},
    "382": {"name": "PLT-F", "full_name": "Fluorescent Platelet Count", "unit": "10^9/L", "category": "Advanced"},
    "383": {"name": "HYPO-He", "full_name": "Hypochromic RBC Percentage", "unit": "%", "category": "Advanced"},
    "384": {"name": "HYPER-He", "full_name": "Hyperchromic RBC Percentage", "unit": "%", "category": "Advanced"},
    "385": {"name": "MicroR", "full_name": "Microcytic RBC Percentage", "unit": "%", "category": "Advanced"},
    "386": {"name": "MacroR", "full_name": "Macrocytic RBC Percentage", "unit": "%", "category": "Advanced"},
    "387": {"name": "FRC%", "full_name": "Fragmented RBC Percentage", "unit": "%", "category": "Advanced"},
    "388": {"name": "FRC#", "full_name": "Fragmented RBC Absolute", "unit": "10^9/L", "category": "Advanced"},
    
    # Body Fluid Analysis
    "390": {"name": "BF-WBC", "full_name": "Body Fluid WBC", "unit": "/μL", "category": "BodyFluid"},
    "391": {"name": "BF-RBC", "full_name": "Body Fluid RBC", "unit": "/μL", "category": "BodyFluid"},
    "392": {"name": "BF-MN%", "full_name": "Body Fluid Mononuclear %", "unit": "%", "category": "BodyFluid"},
    "393": {"name": "BF-MN#", "full_name": "Body Fluid Mononuclear Absolute", "unit": "/μL", "category": "BodyFluid"},
    "394": {"name": "BF-PMN%", "full_name": "Body Fluid Polymorphonuclear %", "unit": "%", "category": "BodyFluid"},
    "395": {"name": "BF-PMN#", "full_name": "Body Fluid Polymorphonuclear Absolute", "unit": "/μL", "category": "BodyFluid"},
    "396": {"name": "BF-TC", "full_name": "Body Fluid Total Cells", "unit": "/μL", "category": "BodyFluid"},
    
    # ESR
    "400": {"name": "ESR", "full_name": "Erythrocyte Sedimentation Rate", "unit": "mm/hr", "category": "ESR"},
    "401": {"name": "ESR-1H", "full_name": "ESR 1 Hour", "unit": "mm/hr", "category": "ESR"},
    "402": {"name": "ESR-2H", "full_name": "ESR 2 Hour", "unit": "mm/hr", "category": "ESR"},
    
    # Alternative CBC Code Range (950-999) - Sysmex/Legacy
    "950": {"name": "WBC", "full_name": "White Blood Cell Count", "unit": "10^9/L", "category": "CBC"},
    "951": {"name": "RBC", "full_name": "Red Blood Cell Count", "unit": "10^12/L", "category": "CBC"},
    "952": {"name": "HGB", "full_name": "Hemoglobin", "unit": "g/L", "category": "CBC"},
    "953": {"name": "HCT", "full_name": "Hematocrit", "unit": "%", "category": "CBC"},
    "954": {"name": "MCV", "full_name": "Mean Corpuscular Volume", "unit": "fL", "category": "CBC"},
    "955": {"name": "MCH", "full_name": "Mean Corpuscular Hemoglobin", "unit": "pg", "category": "CBC"},
    "956": {"name": "MCHC", "full_name": "Mean Corpuscular Hemoglobin Concentration", "unit": "g/dL", "category": "CBC"},
    "957": {"name": "PLT", "full_name": "Platelet Count", "unit": "10^9/L", "category": "CBC"},
    "958": {"name": "RDW", "full_name": "Red Cell Distribution Width", "unit": "%", "category": "CBC"},
    "959": {"name": "MPV", "full_name": "Mean Platelet Volume", "unit": "fL", "category": "CBC"},
    "960": {"name": "NEUT%", "full_name": "Neutrophils Percentage", "unit": "%", "category": "Differential"},
    "961": {"name": "LYMPH%", "full_name": "Lymphocytes Percentage", "unit": "%", "category": "Differential"},
    "962": {"name": "MONO%", "full_name": "Monocytes Percentage", "unit": "%", "category": "Differential"},
    "963": {"name": "EO%", "full_name": "Eosinophils Percentage", "unit": "%", "category": "Differential"},
    "964": {"name": "BASO%", "full_name": "Basophils Percentage", "unit": "%", "category": "Differential"},
    "965": {"name": "NEUT#", "full_name": "Neutrophils Absolute", "unit": "10^9/L", "category": "Differential"},
    "966": {"name": "LYMPH#", "full_name": "Lymphocytes Absolute", "unit": "10^9/L", "category": "Differential"},
    "967": {"name": "MONO#", "full_name": "Monocytes Absolute", "unit": "10^9/L", "category": "Differential"},
    "968": {"name": "EO#", "full_name": "Eosinophils Absolute", "unit": "10^9/L", "category": "Differential"},
    "969": {"name": "BASO#", "full_name": "Basophils Absolute", "unit": "10^9/L", "category": "Differential"},
    "970": {"name": "IG%", "full_name": "Immature Granulocytes %", "unit": "%", "category": "Differential"},
    "971": {"name": "IG#", "full_name": "Immature Granulocytes Absolute", "unit": "10^9/L", "category": "Differential"},
    "972": {"name": "RET%", "full_name": "Reticulocyte Percentage", "unit": "%", "category": "Reticulocyte"},
    "973": {"name": "RET#", "full_name": "Reticulocyte Absolute", "unit": "10^12/L", "category": "Reticulocyte"},
    "974": {"name": "IRF", "full_name": "Immature Reticulocyte Fraction", "unit": "%", "category": "Reticulocyte"},
    "975": {"name": "NRBC%", "full_name": "Nucleated RBC Percentage", "unit": "%", "category": "NRBC"},
    "976": {"name": "NRBC#", "full_name": "Nucleated RBC Absolute", "unit": "10^9/L", "category": "NRBC"},
}

# =============================================================================
# CHEMISTRY CODES (1001-1299)
# =============================================================================
CHEMISTRY_CODES = {
    # Liver Function Tests
    "1001": {"name": "ALT", "full_name": "Alanine Aminotransferase", "unit": "U/L", "category": "Liver"},
    "1002": {"name": "AST", "full_name": "Aspartate Aminotransferase", "unit": "U/L", "category": "Liver"},
    "1003": {"name": "ALP", "full_name": "Alkaline Phosphatase", "unit": "U/L", "category": "Liver"},
    "1004": {"name": "GGT", "full_name": "Gamma-Glutamyl Transferase", "unit": "U/L", "category": "Liver"},
    "1005": {"name": "TBIL", "full_name": "Total Bilirubin", "unit": "μmol/L", "category": "Liver"},
    "1006": {"name": "DBIL", "full_name": "Direct Bilirubin", "unit": "μmol/L", "category": "Liver"},
    "1007": {"name": "IBIL", "full_name": "Indirect Bilirubin", "unit": "μmol/L", "category": "Liver"},
    "1008": {"name": "TP", "full_name": "Total Protein", "unit": "g/L", "category": "Liver"},
    "1009": {"name": "ALB", "full_name": "Albumin", "unit": "g/L", "category": "Liver"},
    "1010": {"name": "GLOB", "full_name": "Globulin", "unit": "g/L", "category": "Liver"},
    "1011": {"name": "A/G", "full_name": "Albumin/Globulin Ratio", "unit": "", "category": "Liver"},
    "1012": {"name": "LDH", "full_name": "Lactate Dehydrogenase", "unit": "U/L", "category": "Liver"},
    "1013": {"name": "5NT", "full_name": "5-Nucleotidase", "unit": "U/L", "category": "Liver"},
    "1014": {"name": "CHE", "full_name": "Cholinesterase", "unit": "U/L", "category": "Liver"},
    "1015": {"name": "PALB", "full_name": "Prealbumin", "unit": "mg/L", "category": "Liver"},
    
    # Renal Function Tests
    "1020": {"name": "CREA", "full_name": "Creatinine", "unit": "μmol/L", "category": "Renal"},
    "1021": {"name": "BUN", "full_name": "Blood Urea Nitrogen", "unit": "mmol/L", "category": "Renal"},
    "1022": {"name": "UREA", "full_name": "Urea", "unit": "mmol/L", "category": "Renal"},
    "1023": {"name": "eGFR", "full_name": "Estimated GFR", "unit": "mL/min/1.73m²", "category": "Renal"},
    "1024": {"name": "UA", "full_name": "Uric Acid", "unit": "μmol/L", "category": "Renal"},
    "1025": {"name": "CysC", "full_name": "Cystatin C", "unit": "mg/L", "category": "Renal"},
    "1026": {"name": "B2M", "full_name": "Beta-2-Microglobulin", "unit": "mg/L", "category": "Renal"},
    "1027": {"name": "ACR", "full_name": "Albumin/Creatinine Ratio", "unit": "mg/g", "category": "Renal"},
    "1028": {"name": "MALB", "full_name": "Microalbumin", "unit": "mg/L", "category": "Renal"},
    
    # Electrolytes
    "1030": {"name": "Na", "full_name": "Sodium", "unit": "mmol/L", "category": "Electrolyte"},
    "1031": {"name": "K", "full_name": "Potassium", "unit": "mmol/L", "category": "Electrolyte"},
    "1032": {"name": "Cl", "full_name": "Chloride", "unit": "mmol/L", "category": "Electrolyte"},
    "1033": {"name": "Ca", "full_name": "Calcium Total", "unit": "mmol/L", "category": "Electrolyte"},
    "1034": {"name": "iCa", "full_name": "Ionized Calcium", "unit": "mmol/L", "category": "Electrolyte"},
    "1035": {"name": "Mg", "full_name": "Magnesium", "unit": "mmol/L", "category": "Electrolyte"},
    "1036": {"name": "PHOS", "full_name": "Phosphorus", "unit": "mmol/L", "category": "Electrolyte"},
    "1037": {"name": "CO2", "full_name": "Carbon Dioxide/Bicarbonate", "unit": "mmol/L", "category": "Electrolyte"},
    "1038": {"name": "ANION", "full_name": "Anion Gap", "unit": "mmol/L", "category": "Electrolyte"},
    "1039": {"name": "OSM", "full_name": "Osmolality", "unit": "mOsm/kg", "category": "Electrolyte"},
    
    # Lipid Panel
    "1040": {"name": "CHOL", "full_name": "Total Cholesterol", "unit": "mmol/L", "category": "Lipid"},
    "1041": {"name": "TG", "full_name": "Triglycerides", "unit": "mmol/L", "category": "Lipid"},
    "1042": {"name": "HDL", "full_name": "HDL Cholesterol", "unit": "mmol/L", "category": "Lipid"},
    "1043": {"name": "LDL", "full_name": "LDL Cholesterol", "unit": "mmol/L", "category": "Lipid"},
    "1044": {"name": "VLDL", "full_name": "VLDL Cholesterol", "unit": "mmol/L", "category": "Lipid"},
    "1045": {"name": "NonHDL", "full_name": "Non-HDL Cholesterol", "unit": "mmol/L", "category": "Lipid"},
    "1046": {"name": "TC/HDL", "full_name": "Cholesterol/HDL Ratio", "unit": "", "category": "Lipid"},
    "1047": {"name": "LDL/HDL", "full_name": "LDL/HDL Ratio", "unit": "", "category": "Lipid"},
    "1048": {"name": "ApoA1", "full_name": "Apolipoprotein A1", "unit": "g/L", "category": "Lipid"},
    "1049": {"name": "ApoB", "full_name": "Apolipoprotein B", "unit": "g/L", "category": "Lipid"},
    "1050": {"name": "Lp(a)", "full_name": "Lipoprotein (a)", "unit": "nmol/L", "category": "Lipid"},
    
    # Glucose/Diabetes
    "1060": {"name": "GLU", "full_name": "Glucose", "unit": "mmol/L", "category": "Glucose"},
    "1061": {"name": "FPG", "full_name": "Fasting Plasma Glucose", "unit": "mmol/L", "category": "Glucose"},
    "1062": {"name": "HbA1c", "full_name": "Hemoglobin A1c", "unit": "%", "category": "Glucose"},
    "1063": {"name": "NGSP", "full_name": "HbA1c NGSP", "unit": "%", "category": "Glucose"},
    "1064": {"name": "eAG", "full_name": "Estimated Average Glucose", "unit": "mmol/L", "category": "Glucose"},
    "1065": {"name": "IFCC", "full_name": "HbA1c IFCC", "unit": "mmol/mol", "category": "Glucose"},
    "1066": {"name": "FRU", "full_name": "Fructosamine", "unit": "μmol/L", "category": "Glucose"},
    "1067": {"name": "INS", "full_name": "Insulin", "unit": "pmol/L", "category": "Glucose"},
    "1068": {"name": "CPEP", "full_name": "C-Peptide", "unit": "nmol/L", "category": "Glucose"},
    "1069": {"name": "HOMA-IR", "full_name": "HOMA Insulin Resistance", "unit": "", "category": "Glucose"},
    
    # Cardiac Markers
    "1070": {"name": "cTnI", "full_name": "Cardiac Troponin I", "unit": "ng/L", "category": "Cardiac"},
    "1071": {"name": "cTnT", "full_name": "Cardiac Troponin T", "unit": "ng/L", "category": "Cardiac"},
    "1072": {"name": "hsTnI", "full_name": "High-Sensitivity Troponin I", "unit": "ng/L", "category": "Cardiac"},
    "1073": {"name": "hsTnT", "full_name": "High-Sensitivity Troponin T", "unit": "ng/L", "category": "Cardiac"},
    "1074": {"name": "CK", "full_name": "Creatine Kinase", "unit": "U/L", "category": "Cardiac"},
    "1075": {"name": "CK-MB", "full_name": "Creatine Kinase MB", "unit": "U/L", "category": "Cardiac"},
    "1076": {"name": "CK-MM", "full_name": "Creatine Kinase MM", "unit": "U/L", "category": "Cardiac"},
    "1077": {"name": "MYO", "full_name": "Myoglobin", "unit": "ng/mL", "category": "Cardiac"},
    "1078": {"name": "BNP", "full_name": "Brain Natriuretic Peptide", "unit": "pg/mL", "category": "Cardiac"},
    "1079": {"name": "NT-proBNP", "full_name": "NT-proBNP", "unit": "pg/mL", "category": "Cardiac"},
    "1080": {"name": "HCY", "full_name": "Homocysteine", "unit": "μmol/L", "category": "Cardiac"},
    "1081": {"name": "Ddimer", "full_name": "D-Dimer", "unit": "mg/L FEU", "category": "Cardiac"},
    
    # Inflammatory Markers
    "1085": {"name": "CRP", "full_name": "C-Reactive Protein", "unit": "mg/L", "category": "Inflammation"},
    "1086": {"name": "hsCRP", "full_name": "High-Sensitivity CRP", "unit": "mg/L", "category": "Inflammation"},
    "1087": {"name": "PCT", "full_name": "Procalcitonin", "unit": "ng/mL", "category": "Inflammation"},
    "1088": {"name": "IL6", "full_name": "Interleukin-6", "unit": "pg/mL", "category": "Inflammation"},
    "1089": {"name": "ESR", "full_name": "Erythrocyte Sedimentation Rate", "unit": "mm/hr", "category": "Inflammation"},
    "1090": {"name": "SAA", "full_name": "Serum Amyloid A", "unit": "mg/L", "category": "Inflammation"},
    
    # Thyroid Function
    "1100": {"name": "TSH", "full_name": "Thyroid Stimulating Hormone", "unit": "mIU/L", "category": "Thyroid"},
    "1101": {"name": "FT3", "full_name": "Free Triiodothyronine", "unit": "pmol/L", "category": "Thyroid"},
    "1102": {"name": "FT4", "full_name": "Free Thyroxine", "unit": "pmol/L", "category": "Thyroid"},
    "1103": {"name": "TT3", "full_name": "Total Triiodothyronine", "unit": "nmol/L", "category": "Thyroid"},
    "1104": {"name": "TT4", "full_name": "Total Thyroxine", "unit": "nmol/L", "category": "Thyroid"},
    "1105": {"name": "rT3", "full_name": "Reverse T3", "unit": "pmol/L", "category": "Thyroid"},
    "1106": {"name": "TG", "full_name": "Thyroglobulin", "unit": "ng/mL", "category": "Thyroid"},
    "1107": {"name": "TPOAb", "full_name": "Anti-TPO Antibodies", "unit": "IU/mL", "category": "Thyroid"},
    "1108": {"name": "TgAb", "full_name": "Anti-Thyroglobulin Antibodies", "unit": "IU/mL", "category": "Thyroid"},
    "1109": {"name": "TRAb", "full_name": "TSH Receptor Antibodies", "unit": "IU/L", "category": "Thyroid"},
    
    # Iron Studies
    "1110": {"name": "FE", "full_name": "Iron", "unit": "μmol/L", "category": "Iron"},
    "1111": {"name": "TIBC", "full_name": "Total Iron Binding Capacity", "unit": "μmol/L", "category": "Iron"},
    "1112": {"name": "UIBC", "full_name": "Unsaturated Iron Binding Capacity", "unit": "μmol/L", "category": "Iron"},
    "1113": {"name": "TSAT", "full_name": "Transferrin Saturation", "unit": "%", "category": "Iron"},
    "1114": {"name": "FERR", "full_name": "Ferritin", "unit": "μg/L", "category": "Iron"},
    "1115": {"name": "TRF", "full_name": "Transferrin", "unit": "g/L", "category": "Iron"},
    "1116": {"name": "sTfR", "full_name": "Soluble Transferrin Receptor", "unit": "mg/L", "category": "Iron"},
    
    # Pancreatic Enzymes
    "1120": {"name": "AMY", "full_name": "Amylase", "unit": "U/L", "category": "Pancreas"},
    "1121": {"name": "PAMY", "full_name": "Pancreatic Amylase", "unit": "U/L", "category": "Pancreas"},
    "1122": {"name": "LIP", "full_name": "Lipase", "unit": "U/L", "category": "Pancreas"},
    
    # Blood Gases
    "1130": {"name": "pH", "full_name": "Blood pH", "unit": "", "category": "BloodGas"},
    "1131": {"name": "pCO2", "full_name": "Partial Pressure CO2", "unit": "mmHg", "category": "BloodGas"},
    "1132": {"name": "pO2", "full_name": "Partial Pressure O2", "unit": "mmHg", "category": "BloodGas"},
    "1133": {"name": "HCO3", "full_name": "Bicarbonate", "unit": "mmol/L", "category": "BloodGas"},
    "1134": {"name": "BE", "full_name": "Base Excess", "unit": "mmol/L", "category": "BloodGas"},
    "1135": {"name": "sO2", "full_name": "Oxygen Saturation", "unit": "%", "category": "BloodGas"},
    "1136": {"name": "LAC", "full_name": "Lactate", "unit": "mmol/L", "category": "BloodGas"},
    "1137": {"name": "tHb", "full_name": "Total Hemoglobin", "unit": "g/dL", "category": "BloodGas"},
    "1138": {"name": "COHb", "full_name": "Carboxyhemoglobin", "unit": "%", "category": "BloodGas"},
    "1139": {"name": "MetHb", "full_name": "Methemoglobin", "unit": "%", "category": "BloodGas"},
    
    # Hormones
    "1150": {"name": "CORT", "full_name": "Cortisol", "unit": "nmol/L", "category": "Hormone"},
    "1151": {"name": "ACTH", "full_name": "Adrenocorticotropic Hormone", "unit": "pmol/L", "category": "Hormone"},
    "1152": {"name": "GH", "full_name": "Growth Hormone", "unit": "mIU/L", "category": "Hormone"},
    "1153": {"name": "IGF1", "full_name": "Insulin-like Growth Factor 1", "unit": "nmol/L", "category": "Hormone"},
    "1154": {"name": "PRL", "full_name": "Prolactin", "unit": "mIU/L", "category": "Hormone"},
    "1155": {"name": "FSH", "full_name": "Follicle Stimulating Hormone", "unit": "IU/L", "category": "Hormone"},
    "1156": {"name": "LH", "full_name": "Luteinizing Hormone", "unit": "IU/L", "category": "Hormone"},
    "1157": {"name": "E2", "full_name": "Estradiol", "unit": "pmol/L", "category": "Hormone"},
    "1158": {"name": "PROG", "full_name": "Progesterone", "unit": "nmol/L", "category": "Hormone"},
    "1159": {"name": "TESTO", "full_name": "Testosterone", "unit": "nmol/L", "category": "Hormone"},
    "1160": {"name": "FTESTO", "full_name": "Free Testosterone", "unit": "pmol/L", "category": "Hormone"},
    "1161": {"name": "SHBG", "full_name": "Sex Hormone Binding Globulin", "unit": "nmol/L", "category": "Hormone"},
    "1162": {"name": "DHEAS", "full_name": "DHEA Sulfate", "unit": "μmol/L", "category": "Hormone"},
    "1163": {"name": "PTH", "full_name": "Parathyroid Hormone", "unit": "pmol/L", "category": "Hormone"},
    "1164": {"name": "25OHD", "full_name": "Vitamin D (25-OH)", "unit": "nmol/L", "category": "Hormone"},
    "1165": {"name": "125OHD", "full_name": "Vitamin D (1,25-OH)", "unit": "pmol/L", "category": "Hormone"},
    "1166": {"name": "ALDO", "full_name": "Aldosterone", "unit": "pmol/L", "category": "Hormone"},
    "1167": {"name": "RENIN", "full_name": "Renin", "unit": "mIU/L", "category": "Hormone"},
    
    # Tumor Markers
    "1180": {"name": "AFP", "full_name": "Alpha-Fetoprotein", "unit": "IU/mL", "category": "TumorMarker"},
    "1181": {"name": "CEA", "full_name": "Carcinoembryonic Antigen", "unit": "μg/L", "category": "TumorMarker"},
    "1182": {"name": "CA125", "full_name": "Cancer Antigen 125", "unit": "U/mL", "category": "TumorMarker"},
    "1183": {"name": "CA199", "full_name": "Cancer Antigen 19-9", "unit": "U/mL", "category": "TumorMarker"},
    "1184": {"name": "CA153", "full_name": "Cancer Antigen 15-3", "unit": "U/mL", "category": "TumorMarker"},
    "1185": {"name": "CA724", "full_name": "Cancer Antigen 72-4", "unit": "U/mL", "category": "TumorMarker"},
    "1186": {"name": "PSA", "full_name": "Prostate Specific Antigen", "unit": "μg/L", "category": "TumorMarker"},
    "1187": {"name": "fPSA", "full_name": "Free PSA", "unit": "μg/L", "category": "TumorMarker"},
    "1188": {"name": "PSA%", "full_name": "Free/Total PSA Ratio", "unit": "%", "category": "TumorMarker"},
    "1189": {"name": "HCG", "full_name": "Human Chorionic Gonadotropin", "unit": "IU/L", "category": "TumorMarker"},
    "1190": {"name": "bHCG", "full_name": "Beta-HCG", "unit": "IU/L", "category": "TumorMarker"},
    "1191": {"name": "NSE", "full_name": "Neuron-Specific Enolase", "unit": "μg/L", "category": "TumorMarker"},
    "1192": {"name": "CYFRA", "full_name": "CYFRA 21-1", "unit": "μg/L", "category": "TumorMarker"},
    "1193": {"name": "SCC", "full_name": "Squamous Cell Carcinoma Antigen", "unit": "μg/L", "category": "TumorMarker"},
    "1194": {"name": "S100", "full_name": "S100 Protein", "unit": "μg/L", "category": "TumorMarker"},
    "1195": {"name": "HE4", "full_name": "Human Epididymis Protein 4", "unit": "pmol/L", "category": "TumorMarker"},
    
    # Vitamins & Nutrition
    "1200": {"name": "VitB12", "full_name": "Vitamin B12", "unit": "pmol/L", "category": "Vitamin"},
    "1201": {"name": "Folate", "full_name": "Folate", "unit": "nmol/L", "category": "Vitamin"},
    "1202": {"name": "RBCFol", "full_name": "Red Cell Folate", "unit": "nmol/L", "category": "Vitamin"},
    "1203": {"name": "VitA", "full_name": "Vitamin A (Retinol)", "unit": "μmol/L", "category": "Vitamin"},
    "1204": {"name": "VitE", "full_name": "Vitamin E (Tocopherol)", "unit": "μmol/L", "category": "Vitamin"},
    "1205": {"name": "VitC", "full_name": "Vitamin C (Ascorbic Acid)", "unit": "μmol/L", "category": "Vitamin"},
    "1206": {"name": "Zn", "full_name": "Zinc", "unit": "μmol/L", "category": "Vitamin"},
    "1207": {"name": "Cu", "full_name": "Copper", "unit": "μmol/L", "category": "Vitamin"},
    "1208": {"name": "Se", "full_name": "Selenium", "unit": "μmol/L", "category": "Vitamin"},
}

# =============================================================================
# COAGULATION CODES (2001-2199)
# =============================================================================
COAGULATION_CODES = {
    # Basic Coagulation Tests
    "2001": {"name": "PT", "full_name": "Prothrombin Time", "unit": "sec", "category": "BasicCoag"},
    "2002": {"name": "INR", "full_name": "International Normalized Ratio", "unit": "", "category": "BasicCoag"},
    "2003": {"name": "PTT", "full_name": "Partial Thromboplastin Time", "unit": "sec", "category": "BasicCoag"},
    "2004": {"name": "APTT", "full_name": "Activated Partial Thromboplastin Time", "unit": "sec", "category": "BasicCoag"},
    "2005": {"name": "TT", "full_name": "Thrombin Time", "unit": "sec", "category": "BasicCoag"},
    "2006": {"name": "TCT", "full_name": "Thrombin Clotting Time", "unit": "sec", "category": "BasicCoag"},
    "2007": {"name": "ACT", "full_name": "Activated Clotting Time", "unit": "sec", "category": "BasicCoag"},
    "2008": {"name": "BT", "full_name": "Bleeding Time", "unit": "min", "category": "BasicCoag"},
    "2009": {"name": "CT", "full_name": "Clotting Time", "unit": "min", "category": "BasicCoag"},
    
    # Fibrinogen & Fibrin Degradation
    "2010": {"name": "FIB", "full_name": "Fibrinogen", "unit": "g/L", "category": "Fibrinogen"},
    "2011": {"name": "FIBc", "full_name": "Fibrinogen (Clauss)", "unit": "g/L", "category": "Fibrinogen"},
    "2012": {"name": "FIBd", "full_name": "Fibrinogen (Derived)", "unit": "g/L", "category": "Fibrinogen"},
    "2013": {"name": "FDP", "full_name": "Fibrin Degradation Products", "unit": "μg/mL", "category": "Fibrinogen"},
    "2014": {"name": "Ddimer", "full_name": "D-Dimer", "unit": "mg/L FEU", "category": "Fibrinogen"},
    "2015": {"name": "DdimerDDU", "full_name": "D-Dimer (DDU)", "unit": "μg/mL DDU", "category": "Fibrinogen"},
    "2016": {"name": "FSP", "full_name": "Fibrin Split Products", "unit": "μg/mL", "category": "Fibrinogen"},
    
    # Natural Anticoagulants
    "2020": {"name": "AT", "full_name": "Antithrombin Activity", "unit": "%", "category": "Anticoagulant"},
    "2021": {"name": "AT-Ag", "full_name": "Antithrombin Antigen", "unit": "%", "category": "Anticoagulant"},
    "2022": {"name": "PC", "full_name": "Protein C Activity", "unit": "%", "category": "Anticoagulant"},
    "2023": {"name": "PC-Ag", "full_name": "Protein C Antigen", "unit": "%", "category": "Anticoagulant"},
    "2024": {"name": "PS", "full_name": "Protein S Activity", "unit": "%", "category": "Anticoagulant"},
    "2025": {"name": "PS-Free", "full_name": "Free Protein S", "unit": "%", "category": "Anticoagulant"},
    "2026": {"name": "PS-Total", "full_name": "Total Protein S", "unit": "%", "category": "Anticoagulant"},
    "2027": {"name": "APCR", "full_name": "Activated Protein C Resistance", "unit": "", "category": "Anticoagulant"},
    "2028": {"name": "TFPI", "full_name": "Tissue Factor Pathway Inhibitor", "unit": "ng/mL", "category": "Anticoagulant"},
    
    # Coagulation Factors
    "2030": {"name": "FI", "full_name": "Factor I (Fibrinogen)", "unit": "%", "category": "Factor"},
    "2031": {"name": "FII", "full_name": "Factor II (Prothrombin)", "unit": "%", "category": "Factor"},
    "2032": {"name": "FV", "full_name": "Factor V", "unit": "%", "category": "Factor"},
    "2033": {"name": "FVII", "full_name": "Factor VII", "unit": "%", "category": "Factor"},
    "2034": {"name": "FVIII", "full_name": "Factor VIII", "unit": "%", "category": "Factor"},
    "2035": {"name": "FIX", "full_name": "Factor IX", "unit": "%", "category": "Factor"},
    "2036": {"name": "FX", "full_name": "Factor X", "unit": "%", "category": "Factor"},
    "2037": {"name": "FXI", "full_name": "Factor XI", "unit": "%", "category": "Factor"},
    "2038": {"name": "FXII", "full_name": "Factor XII", "unit": "%", "category": "Factor"},
    "2039": {"name": "FXIII", "full_name": "Factor XIII", "unit": "%", "category": "Factor"},
    "2040": {"name": "FXIII-A", "full_name": "Factor XIII A-Subunit", "unit": "%", "category": "Factor"},
    "2041": {"name": "FXIII-B", "full_name": "Factor XIII B-Subunit", "unit": "%", "category": "Factor"},
    
    # von Willebrand Factor
    "2050": {"name": "vWF-Ag", "full_name": "von Willebrand Factor Antigen", "unit": "%", "category": "vWF"},
    "2051": {"name": "vWF-Act", "full_name": "von Willebrand Factor Activity", "unit": "%", "category": "vWF"},
    "2052": {"name": "vWF-RCo", "full_name": "von Willebrand Factor Ristocetin Cofactor", "unit": "%", "category": "vWF"},
    "2053": {"name": "vWF-GPIb", "full_name": "vWF Glycoprotein Ib Binding", "unit": "%", "category": "vWF"},
    "2054": {"name": "vWF-CB", "full_name": "vWF Collagen Binding", "unit": "%", "category": "vWF"},
    "2055": {"name": "vWF-FVIII", "full_name": "vWF Factor VIII Binding", "unit": "%", "category": "vWF"},
    "2056": {"name": "RIPA", "full_name": "Ristocetin-Induced Platelet Aggregation", "unit": "%", "category": "vWF"},
    
    # Platelet Function
    "2060": {"name": "PFA-EPI", "full_name": "PFA-100 Collagen/Epinephrine", "unit": "sec", "category": "PlateletFunction"},
    "2061": {"name": "PFA-ADP", "full_name": "PFA-100 Collagen/ADP", "unit": "sec", "category": "PlateletFunction"},
    "2062": {"name": "PFA-P2Y", "full_name": "PFA P2Y Closure Time", "unit": "sec", "category": "PlateletFunction"},
    "2063": {"name": "PAgg-ADP", "full_name": "Platelet Aggregation ADP", "unit": "%", "category": "PlateletFunction"},
    "2064": {"name": "PAgg-EPI", "full_name": "Platelet Aggregation Epinephrine", "unit": "%", "category": "PlateletFunction"},
    "2065": {"name": "PAgg-COL", "full_name": "Platelet Aggregation Collagen", "unit": "%", "category": "PlateletFunction"},
    "2066": {"name": "PAgg-AA", "full_name": "Platelet Aggregation Arachidonic Acid", "unit": "%", "category": "PlateletFunction"},
    "2067": {"name": "PAgg-RISTO", "full_name": "Platelet Aggregation Ristocetin", "unit": "%", "category": "PlateletFunction"},
    "2068": {"name": "VerifyNow-ASA", "full_name": "VerifyNow Aspirin", "unit": "ARU", "category": "PlateletFunction"},
    "2069": {"name": "VerifyNow-P2Y12", "full_name": "VerifyNow P2Y12", "unit": "PRU", "category": "PlateletFunction"},
    
    # Lupus Anticoagulant Panel
    "2070": {"name": "LA", "full_name": "Lupus Anticoagulant Screen", "unit": "", "category": "LupusAnticoag"},
    "2071": {"name": "dRVVT-Screen", "full_name": "Dilute Russell Viper Venom Time Screen", "unit": "sec", "category": "LupusAnticoag"},
    "2072": {"name": "dRVVT-Confirm", "full_name": "Dilute Russell Viper Venom Time Confirm", "unit": "sec", "category": "LupusAnticoag"},
    "2073": {"name": "dRVVT-Ratio", "full_name": "dRVVT Screen/Confirm Ratio", "unit": "", "category": "LupusAnticoag"},
    "2074": {"name": "LAC-Screen", "full_name": "LAC Screen", "unit": "sec", "category": "LupusAnticoag"},
    "2075": {"name": "LAC-Confirm", "full_name": "LAC Confirm", "unit": "sec", "category": "LupusAnticoag"},
    "2076": {"name": "LAC-Ratio", "full_name": "LAC Screen/Confirm Ratio", "unit": "", "category": "LupusAnticoag"},
    "2077": {"name": "aCL-IgG", "full_name": "Anti-Cardiolipin IgG", "unit": "GPL U/mL", "category": "LupusAnticoag"},
    "2078": {"name": "aCL-IgM", "full_name": "Anti-Cardiolipin IgM", "unit": "MPL U/mL", "category": "LupusAnticoag"},
    "2079": {"name": "aB2GPI-IgG", "full_name": "Anti-Beta2 Glycoprotein I IgG", "unit": "U/mL", "category": "LupusAnticoag"},
    "2080": {"name": "aB2GPI-IgM", "full_name": "Anti-Beta2 Glycoprotein I IgM", "unit": "U/mL", "category": "LupusAnticoag"},
    
    # Anti-Xa Monitoring
    "2090": {"name": "Anti-Xa-UFH", "full_name": "Anti-Xa (Unfractionated Heparin)", "unit": "IU/mL", "category": "AntiXa"},
    "2091": {"name": "Anti-Xa-LMWH", "full_name": "Anti-Xa (LMWH)", "unit": "IU/mL", "category": "AntiXa"},
    "2092": {"name": "Anti-Xa-Rivaroxaban", "full_name": "Anti-Xa (Rivaroxaban)", "unit": "ng/mL", "category": "AntiXa"},
    "2093": {"name": "Anti-Xa-Apixaban", "full_name": "Anti-Xa (Apixaban)", "unit": "ng/mL", "category": "AntiXa"},
    "2094": {"name": "Anti-Xa-Edoxaban", "full_name": "Anti-Xa (Edoxaban)", "unit": "ng/mL", "category": "AntiXa"},
    "2095": {"name": "Anti-Xa-Fondaparinux", "full_name": "Anti-Xa (Fondaparinux)", "unit": "mg/L", "category": "AntiXa"},
    
    # Thromboelastography (TEG/ROTEM)
    "2100": {"name": "TEG-R", "full_name": "TEG Reaction Time", "unit": "min", "category": "TEG"},
    "2101": {"name": "TEG-K", "full_name": "TEG K Time", "unit": "min", "category": "TEG"},
    "2102": {"name": "TEG-Angle", "full_name": "TEG Angle", "unit": "deg", "category": "TEG"},
    "2103": {"name": "TEG-MA", "full_name": "TEG Maximum Amplitude", "unit": "mm", "category": "TEG"},
    "2104": {"name": "TEG-LY30", "full_name": "TEG Lysis at 30 min", "unit": "%", "category": "TEG"},
    "2105": {"name": "TEG-CI", "full_name": "TEG Coagulation Index", "unit": "", "category": "TEG"},
    "2110": {"name": "ROTEM-CT", "full_name": "ROTEM Clotting Time", "unit": "sec", "category": "ROTEM"},
    "2111": {"name": "ROTEM-CFT", "full_name": "ROTEM Clot Formation Time", "unit": "sec", "category": "ROTEM"},
    "2112": {"name": "ROTEM-Alpha", "full_name": "ROTEM Alpha Angle", "unit": "deg", "category": "ROTEM"},
    "2113": {"name": "ROTEM-MCF", "full_name": "ROTEM Maximum Clot Firmness", "unit": "mm", "category": "ROTEM"},
    "2114": {"name": "ROTEM-ML", "full_name": "ROTEM Maximum Lysis", "unit": "%", "category": "ROTEM"},
    "2115": {"name": "ROTEM-A10", "full_name": "ROTEM Amplitude at 10 min", "unit": "mm", "category": "ROTEM"},
    
    # Fibrinolysis Markers
    "2120": {"name": "PAI-1", "full_name": "Plasminogen Activator Inhibitor 1", "unit": "ng/mL", "category": "Fibrinolysis"},
    "2121": {"name": "tPA", "full_name": "Tissue Plasminogen Activator", "unit": "ng/mL", "category": "Fibrinolysis"},
    "2122": {"name": "PLG", "full_name": "Plasminogen Activity", "unit": "%", "category": "Fibrinolysis"},
    "2123": {"name": "A2AP", "full_name": "Alpha-2-Antiplasmin", "unit": "%", "category": "Fibrinolysis"},
    "2124": {"name": "TAT", "full_name": "Thrombin-Antithrombin Complex", "unit": "μg/L", "category": "Fibrinolysis"},
    "2125": {"name": "F1+2", "full_name": "Prothrombin Fragment 1+2", "unit": "pmol/L", "category": "Fibrinolysis"},
    "2126": {"name": "PIC", "full_name": "Plasmin-Antiplasmin Complex", "unit": "μg/L", "category": "Fibrinolysis"},
    "2127": {"name": "PAP", "full_name": "Plasmin-Alpha2-Plasmin Inhibitor Complex", "unit": "μg/L", "category": "Fibrinolysis"},
    
    # Heparin Monitoring
    "2130": {"name": "HepAssay", "full_name": "Heparin Assay", "unit": "U/mL", "category": "Heparin"},
    "2131": {"name": "Anti-PF4", "full_name": "Anti-Platelet Factor 4 Antibodies", "unit": "OD", "category": "Heparin"},
    "2132": {"name": "HIT-Ab", "full_name": "HIT Antibodies", "unit": "", "category": "Heparin"},
    "2133": {"name": "SRA", "full_name": "Serotonin Release Assay", "unit": "%", "category": "Heparin"},
}

# =============================================================================
# COMBINED MASTER DICTIONARY
# =============================================================================
LIS2_A_TEST_CODES = {}
LIS2_A_TEST_CODES.update(HEMATOLOGY_CODES)
LIS2_A_TEST_CODES.update(CHEMISTRY_CODES)
LIS2_A_TEST_CODES.update(COAGULATION_CODES)

# Text-based code aliases (for ASTM E1394-97 / Sysmex format)
TEXT_CODE_ALIASES = {
    # Hematology
    "WBC": "301", "RBC": "302", "HGB": "303", "HCT": "304",
    "MCV": "305", "MCH": "306", "MCHC": "307", "PLT": "308",
    "RDW": "309", "RDW-CV": "309", "RDW-SD": "310",
    "MPV": "311", "PDW": "312", "PCT": "313", "P-LCR": "314",
    "NEUT%": "320", "LYMPH%": "321", "MONO%": "322", "EO%": "323", "BASO%": "324",
    "NEUT#": "330", "LYMPH#": "331", "MONO#": "332", "EO#": "333", "BASO#": "334",
    "NE%": "320", "LY%": "321", "MO%": "322",
    "NE#": "330", "LY#": "331", "MO#": "332",
    "RET%": "340", "RET#": "341", "IRF": "342", "RET-He": "346",
    "NRBC%": "350", "NRBC#": "351",
    "IG%": "326", "IG#": "336",
    "IPF": "380", "IPF%": "380",
    "ESR": "400",
    
    # Chemistry
    "ALT": "1001", "AST": "1002", "ALP": "1003", "GGT": "1004",
    "TBIL": "1005", "DBIL": "1006", "TP": "1008", "ALB": "1009",
    "CREA": "1020", "BUN": "1021", "UREA": "1022", "eGFR": "1023", "UA": "1024",
    "Na": "1030", "K": "1031", "Cl": "1032", "Ca": "1033", "Mg": "1035", "PHOS": "1036",
    "CHOL": "1040", "TG": "1041", "HDL": "1042", "LDL": "1043",
    "GLU": "1060", "HbA1c": "1062", "NGSP": "1063",
    "cTnI": "1070", "cTnT": "1071", "CK": "1074", "CK-MB": "1075",
    "BNP": "1078", "NT-proBNP": "1079",
    "CRP": "1085", "hsCRP": "1086", "PCT": "1087",
    "TSH": "1100", "FT3": "1101", "FT4": "1102", "T3": "1103", "T4": "1104",
    "FE": "1110", "TIBC": "1111", "FERR": "1114",
    "AMY": "1120", "LIP": "1122",
    "AFP": "1180", "CEA": "1181", "CA125": "1182", "CA199": "1183", "PSA": "1186",
    "VitB12": "1200", "FOLATE": "1201",
    
    # Coagulation
    "PT": "2001", "INR": "2002", "PTT": "2003", "APTT": "2004", "TT": "2005",
    "FIB": "2010", "FIBRINOGEN": "2010", "FDP": "2013", "DDIMER": "2014", "D-DIMER": "2014",
    "AT": "2020", "AT3": "2020", "ATIII": "2020",
    "PC": "2022", "PS": "2024",
    "FVIII": "2034", "FIX": "2035",
    "vWF": "2050", "VWF-AG": "2050", "VWF-ACT": "2051",
}

# Unit normalization mapping
UNIT_NORMALIZATION = {
    # Standard units
    "g/L": "g/L",
    "g/dL": "g/dL",
    "mg/L": "mg/L",
    "mg/dL": "mg/dL",
    "μg/L": "μg/L",
    "ug/L": "μg/L",
    "ng/L": "ng/L",
    "ng/mL": "ng/mL",
    "pg/mL": "pg/mL",
    
    # Molar concentrations
    "mmol/L": "mmol/L",
    "μmol/L": "μmol/L",
    "umol/L": "μmol/L",
    "nmol/L": "nmol/L",
    "pmol/L": "pmol/L",
    "mmol/mol": "mmol/mol",
    
    # Cell counts
    "10*3/uL": "10³/μL",
    "10*6/uL": "10⁶/μL",
    "10*9/L": "10⁹/L",
    "10^9/L": "10⁹/L",
    "10*12/L": "10¹²/L",
    "10^12/L": "10¹²/L",
    "/uL": "/μL",
    "/μL": "/μL",
    
    # Cell indices
    "fL": "fL",
    "pg": "pg",
    
    # Percentages and ratios
    "%": "%",
    "ratio": "ratio",
    
    # Enzyme activity
    "U/L": "U/L",
    "IU/L": "IU/L",
    "mIU/L": "mIU/L",
    "IU/mL": "IU/mL",
    
    # Time
    "sec": "sec",
    "min": "min",
    "mm/hr": "mm/hr",
    
    # Coagulation specific
    "mg/L FEU": "mg/L FEU",
    "μg/mL DDU": "μg/mL DDU",
    "GPL U/mL": "GPL U/mL",
    "MPL U/mL": "MPL U/mL",
    "ARU": "ARU",
    "PRU": "PRU",
    
    # Blood gas
    "mmHg": "mmHg",
    "kPa": "kPa",
    "mOsm/kg": "mOsm/kg",
    
    # Other
    "deg": "°",
    "mm": "mm",
    "OD": "OD",
}

# Reference ranges for flag calculation (adult ranges)
# Format: (low, high) or (low, high, critical_low, critical_high)
REFERENCE_RANGES = {
    # CBC
    "301": (4.0, 11.0),       # WBC 10^9/L
    "302": (4.0, 5.5),        # RBC 10^12/L (male avg)
    "303": (120, 170),        # HGB g/L
    "304": (36, 50),          # HCT %
    "305": (80, 100),         # MCV fL
    "306": (27, 33),          # MCH pg
    "307": (32, 36),          # MCHC g/dL
    "308": (150, 400),        # PLT 10^9/L
    "309": (11.5, 14.5),      # RDW-CV %
    "310": (35, 56),          # RDW-SD fL
    "311": (7.5, 11.5),       # MPV fL
    "312": (9, 17),           # PDW fL
    "313": (0.1, 0.5),        # PCT %
    "314": (13, 43),          # P-LCR %
    "315": (30, 90),          # P-LCC 10^9/L

    # Differential %
    "320": (40, 75),          # NEUT%
    "321": (20, 45),          # LYMPH%
    "322": (2, 10),           # MONO%
    "323": (1, 6),            # EO%
    "324": (0, 2),            # BASO%
    "325": (0, 4),            # LUC%
    "326": (0, 0.5),          # IG%

    # Differential absolute 10^9/L
    "327": (1.0, 3.2),        # LYMPH# (alt code)
    "328": (0.1, 1.0),        # MONO# (alt code)
    "329": (0.02, 0.5),       # EO# (alt code)
    "330": (1.8, 7.5),        # NEUT#
    "331": (1.0, 3.2),        # LYMPH#
    "332": (0.1, 1.0),        # MONO#
    "333": (0.02, 0.5),       # EO#
    "334": (0, 0.1),          # BASO#
    "335": (0, 0.4),          # LUC#
    "336": (0, 0.05),         # IG#

    # Reticulocyte
    "340": (0.5, 2.5),        # RET%
    "341": (0.02, 0.1),       # RET# 10^12/L
    "342": (0, 24),           # IRF %
    "343": (68, 95),          # LFR %
    "344": (3, 21),           # MFR %
    "345": (0, 4),            # HFR %
    "346": (28, 35),          # RET-He pg
    "347": (-2.0, 2.0),       # Delta-He pg

    # NRBC
    "350": (0, 0),            # NRBC% (normally 0)
    "351": (0, 0),            # NRBC# (normally 0)

    # Extended differential (no universal range — flag only when clearly abnormal)
    "360": (0, 5),            # ATYP%
    "362": (0, 0),            # BLAST% (normally 0)
    "364": (0, 5),            # BAND%
    "380": (0, 7),            # IPF%
    "383": (0, 2.5),          # HYPO-He%
    "384": (0, 4),            # HYPER-He%
    "385": (0, 2.5),          # MicroR%
    "386": (0, 3),            # MacroR%
    "387": (0, 0.5),          # FRC%

    # ESR mm/hr (age-independent conservative range)
    "400": (0, 20),           # ESR
    "401": (0, 20),           # ESR-1H
    "402": (0, 30),           # ESR-2H

    # Legacy CBC codes (950-series)
    "950": (4.0, 11.0),       # WBC
    "951": (4.0, 5.5),        # RBC
    "952": (120, 170),        # HGB
    "953": (36, 50),          # HCT
    "954": (80, 100),         # MCV
    "955": (27, 33),          # MCH
    "956": (32, 36),          # MCHC
    "957": (150, 400),        # PLT
    "958": (11.5, 14.5),      # RDW
    "959": (7.5, 11.5),       # MPV
    "960": (40, 75),          # NEUT%
    "961": (20, 45),          # LYMPH%
    "962": (2, 10),           # MONO%
    "963": (1, 6),            # EO%
    "964": (0, 2),            # BASO%
    "965": (1.8, 7.5),        # NEUT#
    "966": (1.0, 3.2),        # LYMPH#
    "967": (0.1, 1.0),        # MONO#
    "968": (0.02, 0.5),       # EO#
    "969": (0, 0.1),          # BASO#
    "970": (0, 0.5),          # IG%
    "971": (0, 0.05),         # IG#
    "972": (0.5, 2.5),        # RET%
    "973": (0.02, 0.1),       # RET#
    "974": (0, 24),           # IRF

    # Liver function
    "1001": (7, 56),          # ALT U/L
    "1002": (10, 40),         # AST U/L
    "1003": (44, 147),        # ALP U/L
    "1004": (9, 48),          # GGT U/L
    "1005": (3.4, 20.5),      # TBIL μmol/L
    "1006": (1.7, 8.6),       # DBIL μmol/L
    "1007": (1.7, 12.0),      # IBIL μmol/L
    "1008": (60, 83),         # TP g/L
    "1009": (35, 50),         # ALB g/L
    "1010": (20, 35),         # GLOB g/L
    "1011": (1.2, 2.0),       # A/G ratio
    "1012": (120, 246),       # LDH U/L
    "1014": (4000, 12000),    # CHE U/L
    "1015": (200, 400),       # PALB mg/L

    # Renal
    "1020": (45, 110),        # CREA μmol/L
    "1021": (2.5, 7.1),       # BUN mmol/L
    "1022": (2.5, 7.8),       # UREA mmol/L
    "1024": (150, 420),       # UA μmol/L
    "1025": (0.51, 0.98),     # CysC mg/L
    "1028": (0, 30),          # MALB mg/L

    # Electrolytes
    "1030": (136, 145),       # Na mmol/L
    "1031": (3.5, 5.1),       # K mmol/L
    "1032": (98, 106),        # Cl mmol/L
    "1033": (2.15, 2.55),     # Ca mmol/L
    "1034": (1.15, 1.35),     # iCa mmol/L
    "1035": (0.66, 1.07),     # Mg mmol/L
    "1036": (0.81, 1.45),     # PHOS mmol/L
    "1037": (22, 29),         # CO2/HCO3 mmol/L
    "1039": (275, 295),       # OSM mOsm/kg

    # Lipids
    "1040": (0, 5.2),         # CHOL mmol/L
    "1041": (0, 1.7),         # TG mmol/L
    "1042": (1.0, 999),       # HDL mmol/L
    "1043": (0, 3.4),         # LDL mmol/L
    "1044": (0, 4.1),         # VLDL mmol/L
    "1048": (1.0, 1.76),      # ApoA1 g/L
    "1049": (0.52, 1.09),     # ApoB g/L

    # Glucose / Diabetes
    "1060": (3.9, 5.6),       # GLU fasting mmol/L
    "1061": (3.9, 5.6),       # FPG mmol/L
    "1062": (4.0, 5.6),       # HbA1c %
    "1063": (4.0, 5.6),       # NGSP %
    "1065": (20, 38),         # IFCC mmol/mol
    "1066": (200, 285),       # FRU μmol/L

    # Cardiac markers
    "1070": (0, 0.04),        # cTnI μg/L
    "1071": (0, 0.01),        # cTnT μg/L
    "1072": (0, 5),           # BNP pmol/L
    "1073": (0, 125),         # NT-proBNP pg/mL
    "1074": (30, 200),        # CK U/L
    "1075": (0, 24),          # CKMB U/L
    "1076": (0, 7),           # MYO μg/L

    # Inflammatory
    "1080": (0, 10),          # ESR mm/hr (chemistry panel)
    "1085": (0, 10),          # CRP mg/L
    "1086": (0, 3),           # hsCRP mg/L
    "1087": (0, 10),          # IL-6 pg/mL
    "1088": (0, 500),         # PCT ng/mL (sepsis threshold 0.5)
    "1089": (0, 0.5),         # SAA mg/L

    # Thyroid
    "1100": (0.4, 4.0),       # TSH mIU/L
    "1101": (3.1, 6.8),       # FT3 pmol/L
    "1102": (12, 22),         # FT4 pmol/L
    "1103": (1.2, 2.7),       # T3 nmol/L
    "1104": (66, 181),        # T4 nmol/L

    # Iron studies
    "1110": (10, 30),         # FE μmol/L
    "1111": (45, 80),         # TIBC μmol/L
    "1112": (20, 55),         # UIBC μmol/L
    "1113": (20, 50),         # TSAT %
    "1114": (20, 250),        # FERR μg/L

    # Bone / Calcium metabolism
    "1120": (9, 55),          # PTH pmol/L (×0.094 for ng/L)
    "1121": (20, 50),         # Vit D nmol/L (sufficiency >50)

    # Pancreatic
    "1130": (0, 100),         # AMY U/L
    "1131": (0, 60),          # LIP U/L

    # Coagulation
    "2001": (11, 14),         # PT sec
    "2002": (0.8, 1.2),       # INR
    "2003": (70, 120),        # PT% activity
    "2004": (25, 35),         # APTT sec
    "2005": (0.75, 1.25),     # APTT ratio
    "2006": (15, 21),         # TT sec
    "2007": (85, 120),        # FV activity %
    "2008": (70, 150),        # FVIII activity %
    "2009": (70, 130),        # FIX activity %
    "2010": (2.0, 4.0),       # FIB g/L
    "2011": (70, 120),        # FX activity %
    "2012": (80, 120),        # FXII activity %
    "2014": (0, 0.5),         # D-Dimer mg/L FEU
    "2015": (0, 0.5),         # D-Dimer μg/mL DDU
    "2016": (0, 10),          # FDP μg/mL
    "2017": (0, 8),           # XL-FDP μg/mL
    "2018": (0, 8),           # PAP μg/mL
    "2020": (80, 120),        # AT %
    "2021": (70, 130),        # PC activity %
    "2022": (70, 130),        # PS free %
}

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_test_info(code: str) -> dict:
    """
    Get test information by numeric code or text alias.
    
    Args:
        code: Numeric code (e.g., "301") or text code (e.g., "WBC")
    
    Returns:
        Dictionary with name, full_name, unit, category or empty dict if not found
    """
    # Try direct lookup first
    if code in LIS2_A_TEST_CODES:
        return LIS2_A_TEST_CODES[code]
    
    # Try text alias
    upper_code = code.upper()
    if upper_code in TEXT_CODE_ALIASES:
        numeric_code = TEXT_CODE_ALIASES[upper_code]
        return LIS2_A_TEST_CODES.get(numeric_code, {})
    
    return {}


def get_human_readable_name(code: str) -> str:
    """
    Convert a code to its human-readable name.
    
    Args:
        code: Numeric or text code
    
    Returns:
        Human-readable name or the original code if not found
    """
    info = get_test_info(code)
    return info.get("name", code)


def get_full_name(code: str) -> str:
    """
    Get the full descriptive name for a test code.
    
    Args:
        code: Numeric or text code
    
    Returns:
        Full descriptive name or the original code if not found
    """
    info = get_test_info(code)
    return info.get("full_name", code)


def normalize_unit(unit: str) -> str:
    """
    Normalize a unit string to a standard format.
    
    Args:
        unit: Unit string from analyzer
    
    Returns:
        Normalized unit string
    """
    return UNIT_NORMALIZATION.get(unit, unit)


def get_reference_range(code: str) -> tuple | None:
    """
    Get reference range for a test code.
    
    Args:
        code: Numeric code
    
    Returns:
        Tuple (low, high) or None if not found
    """
    # Try direct lookup
    if code in REFERENCE_RANGES:
        return REFERENCE_RANGES[code]
    
    # Try text alias lookup
    upper_code = code.upper()
    if upper_code in TEXT_CODE_ALIASES:
        numeric_code = TEXT_CODE_ALIASES[upper_code]
        return REFERENCE_RANGES.get(numeric_code)
    
    return None


def calculate_flag(code: str, value: float) -> str:
    """
    Calculate result flag based on reference range.
    
    Args:
        code: Test code
        value: Numeric result value
    
    Returns:
        Flag string: 'L' (low), 'H' (high), 'LL' (critical low), 
        'HH' (critical high), or '' (normal)
    """
    ref_range = get_reference_range(code)
    if not ref_range:
        return ""
    
    low, high = ref_range[0], ref_range[1]
    
    # Check for critical ranges if provided
    if len(ref_range) >= 4:
        crit_low, crit_high = ref_range[2], ref_range[3]
        if value < crit_low:
            return "LL"
        if value > crit_high:
            return "HH"
    
    # Normal range check
    if value < low:
        return "L"
    if value > high:
        return "H"
    
    return ""


def get_category_tests(category: str) -> dict:
    """
    Get all tests in a specific category.
    
    Args:
        category: Category name (e.g., "CBC", "Liver", "Coagulation")
    
    Returns:
        Dictionary of code -> test info for matching tests
    """
    return {
        code: info for code, info in LIS2_A_TEST_CODES.items()
        if info.get("category", "").lower() == category.lower()
    }


def resolve_code(raw_code: str) -> str:
    """
    Resolve a raw code to its canonical numeric form.
    
    Args:
        raw_code: Code from analyzer (could be numeric or text)
    
    Returns:
        Canonical numeric code or original if not found
    """
    # Already numeric
    if raw_code in LIS2_A_TEST_CODES:
        return raw_code
    
    # Try text alias
    upper_code = raw_code.upper()
    return TEXT_CODE_ALIASES.get(upper_code, raw_code)
