"""
Centralized definitions for analyzer types and their protocols
"""

class AnalyzerDefinitions:
    # Analyzer Types
    SYSMEX_XN_L = "SYSMEX XN-L"
    MINDRAY_BS_430 = "Mindray BS-430"
    HUMACOUNT_5D = "HumaCount 5D"
    RESPONSE_920 = "RESPONSE 920"
    ROCHE_COBAS = "Roche Cobas"
    SIEMENS_DIMENSION = "Siemens Dimension"
    ABBOTT_ARCHITECT = "Abbott ARCHITECT"
    VITROS = "VITROS"
    BECKMAN_AU = "Beckman AU"

    # Protocols
    PROTOCOL_ASTM = "ASTM"
    PROTOCOL_HL7 = "HL7"
    PROTOCOL_LIS = "LIS"
    PROTOCOL_RESPONSE = "RESPONSE"
    PROTOCOL_POCT1A = "POCT1A"

    # Map of analyzer types to their default protocols
    ANALYZER_PROTOCOL_MAP = {
        SYSMEX_XN_L: PROTOCOL_ASTM,
        MINDRAY_BS_430: PROTOCOL_HL7,
        HUMACOUNT_5D: PROTOCOL_LIS,
        RESPONSE_920: PROTOCOL_RESPONSE,
        ROCHE_COBAS: PROTOCOL_ASTM,
        SIEMENS_DIMENSION: PROTOCOL_ASTM,
        ABBOTT_ARCHITECT: PROTOCOL_POCT1A,
        VITROS: PROTOCOL_ASTM,
        BECKMAN_AU: PROTOCOL_ASTM
    }

    # List of all supported analyzers
    SUPPORTED_ANALYZERS = list(ANALYZER_PROTOCOL_MAP.keys())

    @classmethod
    def get_protocol_for_analyzer(cls, analyzer_type: str) -> str:
        """Get the default protocol for a given analyzer type"""
        return cls.ANALYZER_PROTOCOL_MAP.get(analyzer_type, cls.PROTOCOL_ASTM)

    @classmethod
    def get_supported_analyzers(cls) -> list:
        """Get list of all supported analyzers"""
        return cls.SUPPORTED_ANALYZERS

    @classmethod
    def get_supported_protocols(cls) -> list:
        """Get list of all supported protocols"""
        return [cls.PROTOCOL_ASTM, cls.PROTOCOL_HL7, cls.PROTOCOL_LIS, 
                cls.PROTOCOL_RESPONSE, cls.PROTOCOL_POCT1A]