"""
Roche Cobas Protocol Parser (ASTM E1394)
"""
from .astm_parser import ASTMParser

class CobasParser(ASTMParser):
    """
    Parser for Roche Cobas analyzers using ASTM E1394 protocol.
    """
    
    def __init__(self, db_manager, logger, gui_callback=None, config=None):
        super().__init__(db_manager, logger, gui_callback, config)
        self.log_info("Initialized Roche Cobas parser (ASTM)")
        
    def configure_for_analyzer(self, analyzer_type):
        super().configure_for_analyzer(analyzer_type)
        # Custom field mappings for Cobas can go here if needed
        # self.field_positions.update({...})