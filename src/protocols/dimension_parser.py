"""
Siemens Dimension Protocol Parser (ASTM E1394)
"""
from .astm_parser import ASTMParser

class DimensionParser(ASTMParser):
    """
    Parser for Siemens Dimension analyzers using ASTM E1394 protocol.
    """
    
    def __init__(self, db_manager, logger, gui_callback=None, config=None):
        super().__init__(db_manager, logger, gui_callback, config)
        self.log_info("Initialized Siemens Dimension parser (ASTM)")
        
    def configure_for_analyzer(self, analyzer_type):
        super().configure_for_analyzer(analyzer_type)