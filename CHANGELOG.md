# Changelog - UI/UX and Multi-Port Improvements

## Fixed
- **TCPServer Crash**: Resolved a critical bug where `_create_parser` was called without arguments during server initialization.
- **HL7Parser**: Fixed constructor to accept `config` argument, resolving instantiation errors.

## Added
- **Multi-Port Support**: 
  - `TCPServer` now supports listening on multiple ports simultaneously, each with its own Analyzer Type and Protocol.
  - Implemented backward compatibility for existing single-port configurations.
- **Listener Dashboard (UI)**:
  - Replaced the simple status bar with a comprehensive **System Dashboard**.
  - Displays individual "Cards" for each configured listener.
  - Shows real-time status (Online/Offline) and Client Connection counts for *each* port.
- **Client Tracking**:
  - `TCPServer` now tracks which listener (`local_port`) received a connection, enabling accurate per-port statistics.
- **Hot Reload**:
  - Updating configuration now automatically reloads the server state.
  - If server is running, it restarts seamlessly to apply new listeners immediately.
- **Protocol Compliance**:
  - **Abbott Architect**: Corrected protocol from POCT1-A to ASTM E1394.
  - **HumaCount 5D**: Corrected protocol from Custom-ASTM to HL7 v2.x.
  - **Response 920**: Corrected protocol from Proprietary to ASTM E1394.
  - Standardized Roche Cobas, Siemens Dimension, Beckman AU, and Vitros to use robust ASTM implementation.

## Changed
- **UI Styling**: Added `Card.TFrame` style for better visual separation of listener cards.
- **Application Window**: Refactored status handling to support the dynamic dashboard and ensure the main application loop can trigger UI updates correctly via `update_ui_status`.
- **Config Dialog**: Adjusted layout packing order to ensure "Add", "Edit", and "Remove" buttons are always visible and accessible in the listeners configuration tab.
