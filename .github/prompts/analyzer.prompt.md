# Project: XN-L Analyzer Data Receiver

## Overview
Develop a cross-platform GUI application (Windows/macOS) that listens on a configurable TCP/IP port to receive ASTM data from various analyzers (e.g., SYSMEX XN-L). The application should decode the ASTM protocol, store the data in a SQLite database, and display the parsed data in a user-friendly interface. The application should also include a collapsible log section for detailed event tracking and support external server synchronization with configurable frequency (real-time, scheduled, or cron-based).

## Functional Requirements

### 1. **Configuration File**
   - Allow users to specify:
     - Port to listen on.
     - Name of the application.
     - Unique instance identifier.
     - Analyzer type (e.g., SYSMEX XN-L, ABBOTT CELL-DYN, etc.).
     - External server details (if enabled):
       - Server URL.
       - Authentication credentials (e.g., API key, username/password).
       - Sync frequency: real-time, scheduled, or cron-based.
     - Example `config.json`:
       ```json
       {
         "port": 5000,
         "app_name": "XN-L Data Receiver",
         "instance_id": "XN-L-001",
         "analyzer_type": "SYSMEX XN-L",
         "protocol": "ASTM",
         "external_server": {
           "enabled": true,
           "url": "https://api.example.com/data",
           "api_key": "your_api_key_here",
           "sync_frequency": "cron",
           "cron_schedule": "0 * * * *"  // Every hour
         }
       }
       ```

### 2. **TCP/IP Server**
   - Listen on the port specified in the configuration file.
   - Handle multiple clients asynchronously.
   - Respond to ASTM events according to the analyzer type and protocol.
   - Log connection status, client details, and errors.

### 3. **Analyzer-Specific Protocol Handling**
   - Support multiple analyzer types (e.g., SYSMEX XN-L, ABBOTT CELL-DYN).
   - Parse received events according to the configured analyzer and protocol.
   - Example:
     - SYSMEX XN-L -> ASTM protocol.
     - ABBOTT CELL-DYN -> Custom protocol (if applicable).

### 4. **Database Storage**
   - Use SQLite for local data storage.
   - Create tables for patients and results.
   - Store patient information (ID, name, DOB, sex, physician).
   - Store test results (test code, value, unit, flags, timestamp).
   - Add a `sync_status` field to indicate whether records are synced or local.
     - `sync_status`: "synced" or "local".

### 5. **External Server Synchronization**
   - If an external server is configured:
     - **Real-time Sync**: Send data to the external server immediately after receiving it.
     - **Scheduled Sync**: Send data at fixed intervals (e.g., every 5 minutes).
     - **Cron-based Sync**: Use a cron schedule to send data (e.g., every hour).
   - Mark records as "synced" after successful transmission.
   - Retry failed sync attempts with exponential backoff.

### 6. **GUI**
   - **Connection Status**: Display connection status (connected/disconnected).
   - **Data Table**: Show parsed data in a table (test, value, unit, sync_status).
   - **Collapsible Log Section**:
     - Display raw and decoded events.
     - Show connected clients and their details.
     - Highlight errors and warnings.
     - Allow filtering by event type (e.g., connection, data, error).
   - **Configuration Panel**:
     - Allow users to edit the configuration file (port, app name, analyzer type, external server settings).
     - Validate input before saving changes.
   - **Sync Status Panel**:
     - Display sync status for each record (synced/local).
     - Show sync history and errors.

### 7. **Scattergram Decompression**
   - Implement Huffman + Run-Length decoding for scattergram data.
   - Display decompressed scattergram images (optional).

### 8. **Error Handling**
   - Handle network errors (e.g., connection drops).
   - Validate ASTM data integrity.
   - Log errors and malformed messages.

### 9. **Additional ASTM Record Types**
   - Support additional ASTM record types:
     - C (comment).
     - Q (query).
     - L (terminator).
   - Extend the parser to handle these record types.

### 10. **HL7 Integration**
   - Add support for HL7 integration for hospital systems.
   - Convert ASTM data to HL7 format for external systems.
   - Provide a configuration option to enable/disable HL7 integration.

## Non-Functional Requirements

### 1. **Performance**
   - Handle high-throughput data efficiently.
   - Use asynchronous programming for network operations.

### 2. **Security**
   - Optional: Add SSL encryption for secure communication.
   - Encrypt sensitive data (e.g., API keys) in the configuration file.

### 3. **Usability**
   - Provide a clean and intuitive interface.
   - Include tooltips and help documentation.

### 4. **Compatibility**
   - Support Windows and macOS.
   - Use Python 3.11+ for development.

## Deliverables
1. Source code for the application.
2. A `requirements.txt` file listing dependencies.
3. A SQLite database schema.
4. A configuration file (`config.json`).
5. Documentation for setup and usage.

## Example Workflow
1. Start the application.
2. Configure the port, app name, instance ID, analyzer type, and external server settings.
3. Click "Start Server" to listen on the specified port.
4. Connect the analyzer to the application.
5. View parsed data in the GUI table.
6. Monitor detailed logs in the collapsible log section.
7. Observe sync status for each record (synced/local).

## Dependencies
- Python 3.11+
- Libraries: `numpy`, `asyncio`, `sqlite3`, `tkinter`, `json`, `requests`, `croniter`

## Testing
- Test with sample ASTM data.
- Verify database storage and GUI updates.
- Simulate network errors and validate error handling.
- Test with multiple analyzer types and protocols.
- Validate external server synchronization (real-time, scheduled, cron-based).

## Future Enhancements
1. Add scattergram image display.
2. Export data to CSV or PDF.
3. Implement user authentication and access control.
4. Add support for additional analyzer types and protocols.

---

### **Configuration File (`config.json`)**
```json
{
  "port": 5000,
  "app_name": "XN-L Data Receiver",
  "instance_id": "XN-L-001",
  "analyzer_type": "SYSMEX XN-L",
  "protocol": "ASTM",
  "external_server": {
    "enabled": true,
    "url": "https://api.example.com/data",
    "api_key": "your_api_key_here",
    "sync_frequency": "cron",
    "cron_schedule": "0 * * * *"  // Every hour
  }
}