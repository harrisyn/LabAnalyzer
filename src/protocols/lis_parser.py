"""
LIS Protocol Parser for HumaCount 5D (HL7 v2.3.1)
"""
from .hl7_parser import HL7Parser

class LISParser(HL7Parser):
    """
    Parser for HumaCount 5D hematology analyzers using HL7 protocol.
    """
    
    def __init__(self, db_manager, logger, gui_callback=None, config=None):
        """
        Initialize the parser
        """
        super().__init__(db_manager, logger, gui_callback, config)
        self.log_info("Initialized HumaCount 5D parser (HL7)")
        
    # The HL7Parser base class handles standard HL7 v2 messages (MSH, PID, OBR, OBX).
    # If HumaCount deviates (e.g. non-standard segment names or field usage), 
    # we can override process_message or extraction methods here.
    # For now, we assume standard HL7 compliance as found in research.