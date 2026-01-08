# Quick Fix for tcp_server.py

## Problem
The `_create_parser()` method was updated to accept `analyzer_type` and `protocol` parameters, but line 55 still calls it without arguments.

## Solution
Change line 55 from:
```python
self.parser = self._create_parser()
```

To:
```python
self.parser = self._create_parser(self.analyzer_type, self.protocol)
```

## Full Context (lines 48-60)
```python
        # Get analyzer type and protocol from config
        self.analyzer_type = self.config.get("analyzer_type", AnalyzerDefinitions.SYSMEX_XN_L)
        self.protocol = self.config.get("protocol", AnalyzerDefinitions.get_protocol_for_analyzer(self.analyzer_type))
        
        self.log_message(f"Initializing server for analyzer: {self.analyzer_type} with protocol: {self.protocol}")
        
        # Select appropriate parser
        self.parser = self._create_parser(self.analyzer_type, self.protocol)  # ← CHANGE THIS LINE
        
        # Set sync manager
        self.sync_manager = sync_manager
        if sync_manager and self.parser:
            self.parser.set_sync_manager(sync_manager)
```

This will fix the error: `TCPServer._create_parser() missing 2 required positional arguments: 'analyzer_type' and 'protocol'`
