# Patches for HL7 Parser and Protocol Mapping

## Patch 1: Fix HL7 Parser Field Extraction

### File: `src/protocols/hl7_parser.py`

#### Change 1: Update `_extract_patient_info` method (around line 210)

**Find:**
```python
            patient_id = fields[3].strip() if len(fields) > 3 else ""
            
            # In HL7, sample_id is often in OBR segment, using a placeholder here
            sample_id = ""
```

**Replace with:**
```python
            # Try field 2 first (External ID), then field 3 (Internal ID)
            patient_id = fields[2].strip() if len(fields) > 2 and fields[2].strip() else ""
            if not patient_id:
                patient_id = fields[3].strip() if len(fields) > 3 else ""
            
            # Sample ID will be extracted from OBR segment
            sample_id = ""
```

#### Change 2: Update OBR segment handling (around line 136-138)

**Find:**
```python
            elif segment_type == 'OBR':
                self.log_info("Processing Observation Request segment")
                # Observation request processing would go here
```

**Replace with:**
```python
            elif segment_type == 'OBR':
                self.log_info("Processing Observation Request segment")
                # Extract sample/specimen ID from OBR
                order_info = self._extract_order_info(fields)
                if order_info.get('sample_id'):
                    patient_info['sample_id'] = order_info['sample_id']
```

#### Change 3: Add `_extract_order_info` method (after `_extract_patient_info`, around line 270)

**Add this new method:**
```python
    def _extract_order_info(self, fields):
        """
        Extract order/sample information from an OBR segment
        
        Args:
            fields: The split fields of an OBR segment
            
        Returns:
            Dictionary with order information
        """
        try:
            # OBR segment format:
            # OBR|set_id|placer_order|filler_order|universal_service_id|...
            # Field 3 contains Filler Order Number (sample/specimen ID)
            sample_id = fields[3].strip() if len(fields) > 3 else ""
            
            return {"sample_id": sample_id}
        except Exception as e:
            self.log_error(f"Error extracting order info: {e}")
            return {}
```

---

## Patch 2: Enhance Protocol Mapping in TCPServer

### File: `src/network/tcp_server.py`

#### Change: Update `_create_parser` method (around line 76-91)

**Find:**
```python
    def _create_parser(self, analyzer_type, protocol):
        """Create appropriate parser based on analyzer type and protocol"""
        parser_class = self.PARSER_MAP.get((analyzer_type, protocol), ASTMParser)
        
        # Create parser with configuration
        parser = parser_class(
            self.db_manager, 
            self.logger, 
            gui_callback=self.gui_callback,
            config=self.config
        )
        
        if self.sync_manager:
            parser.set_sync_manager(self.sync_manager)
            
        return parser
```

**Replace with:**
```python
    def _create_parser(self, analyzer_type, protocol):
        """Create appropriate parser based on analyzer type and protocol"""
        # Protocol-to-parser mapping for fallback
        PROTOCOL_PARSER_MAP = {
            AnalyzerDefinitions.PROTOCOL_ASTM: ASTMParser,
            AnalyzerDefinitions.PROTOCOL_HL7: HL7Parser,
            AnalyzerDefinitions.PROTOCOL_LIS: LISParser,
            AnalyzerDefinitions.PROTOCOL_RESPONSE: ResponseParser,
            AnalyzerDefinitions.PROTOCOL_POCT1A: AbbottParser,
        }
        
        # Try exact match first (analyzer_type, protocol)
        parser_class = self.PARSER_MAP.get((analyzer_type, protocol))
        
        # If no exact match, fall back to protocol-only mapping
        if not parser_class:
            parser_class = PROTOCOL_PARSER_MAP.get(protocol, ASTMParser)
            self.log_message(
                f"No specific parser for ({analyzer_type}, {protocol}), using protocol default",
                level="info"
            )
        
        # Create parser with configuration
        parser = parser_class(
            self.db_manager, 
            self.logger, 
            gui_callback=self.gui_callback,
            config=self.config
        )
        
        if self.sync_manager:
            parser.set_sync_manager(self.sync_manager)
            
        return parser
```

---

## Summary of Changes

### HL7 Parser Fixes
1. **Patient ID extraction**: Now checks field 2 first (External ID), then falls back to field 3 (Internal ID)
2. **Sample ID extraction**: Added `_extract_order_info()` method to extract sample ID from OBR segment field 3
3. **OBR segment handling**: Updated to call `_extract_order_info()` and merge sample_id into patient_info

### Protocol Mapping Enhancement
1. **Protocol-only fallback**: Added `PROTOCOL_PARSER_MAP` for cases where analyzer type isn't in `PARSER_MAP`
2. **Flexible configuration**: Now respects the configured protocol even if analyzer type is unknown
3. **Logging**: Added info log when using protocol fallback

## Testing

After applying these patches:

1. **Test HL7 message parsing**:
   - Patient ID should be extracted as "322288" (from field 2)
   - Sample ID should be extracted as "322288" (from OBR field 3)
   - All 17 test results should be stored

2. **Test custom analyzer/protocol combinations**:
   - Configure a listener with any analyzer type + HL7 protocol
   - Should use HL7Parser regardless of analyzer type

## Expected Results

```
[Port:5000|MINDRAY_BS_430] Processing Patient ID segment
[Port:5000|MINDRAY_BS_430] Processing Observation Request segment
[Port:5000|MINDRAY_BS_430] Processing Observation Result segment (x17)
[Port:5000|MINDRAY_BS_430] Patient stored with DB ID: 1
[Port:5000|MINDRAY_BS_430] Stored patient: TIMOTHY WORLANYO (ID: 322288)
```
