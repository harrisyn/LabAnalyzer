"""
Abbott ARCHITECT Protocol Parser (ASTM E1394)
"""
from .astm_parser import ASTMParser

class AbbottParser(ASTMParser):
    """
    Parser for Abbott ARCHITECT analyzers using ASTM E1394 protocol.
    """
    
    def __init__(self, db_manager, logger, gui_callback=None, config=None):
        """
        Initialize the parser
        """
        super().__init__(db_manager, logger, gui_callback, config)
        self.log_info("Initialized Abbott Architect parser (ASTM)")
        
    def configure_for_analyzer(self, analyzer_type):
        """Configure parser settings specifically for Abbott"""
        super().configure_for_analyzer(analyzer_type)
        
        # Abbott Architect specific field mappings if different from standard
        # Standard ASTM usually works, but can specific here if needed
        # self.field_positions.update({...})