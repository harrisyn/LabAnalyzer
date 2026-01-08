"""
Beckman AU Protocol Parser (ASTM E1394)
"""
from .astm_parser import ASTMParser

class BeckmanParser(ASTMParser):
    """
    Parser for Beckman AU analyzers using ASTM E1394 protocol.
    """
    
    def __init__(self, db_manager, logger, gui_callback=None, config=None):
        super().__init__(db_manager, logger, gui_callback, config)
        self.log_info("Initialized Beckman AU parser (ASTM)")
        
    def configure_for_analyzer(self, analyzer_type):
        super().configure_for_analyzer(analyzer_type)