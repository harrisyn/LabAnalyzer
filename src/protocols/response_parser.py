"""
Response 920 Protocol Parser (ASTM E1394)
"""
from .astm_parser import ASTMParser

class ResponseParser(ASTMParser):
    """
    Parser for DiaSys Response 920 analyzers using ASTM E1394 protocol.
    """
    
    def __init__(self, db_manager, logger, gui_callback=None, config=None):
        """
        Initialize the parser
        """
        super().__init__(db_manager, logger, gui_callback, config)
        self.log_info("Initialized Response 920 parser (ASTM)")