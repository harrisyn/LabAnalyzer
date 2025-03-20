# Medical Analyzer Interface

A comprehensive Python application for receiving and processing data from various medical laboratory analyzers using multiple protocols.

## Features

- TCP/IP server for receiving analyzer data
- Multiple protocol support:
  - ASTM protocol (E1381/E1394)
  - HL7 protocol
  - LIS protocol
  - POCT1-A protocol (XML-based)
  - Various vendor-specific protocols
- Multiple analyzer support:
  - SYSMEX XN-L and other SYSMEX analyzers
  - Mindray BS-430 and other Mindray analyzers
  - HumaCount 5D hematology analyzer
  - Roche Cobas chemistry and immunoassay analyzers
  - Abbott ARCHITECT clinical chemistry analyzers
  - Siemens Dimension clinical chemistry analyzers
  - RESPONSE 920 chemistry analyzer
- Scattergram decompression and visualization
- Real-time data display in a user-friendly interface
- External server synchronization with multiple authentication methods
- SQLite database storage for results
- GUI interface with live updates
- Configurable settings with easy-to-use dialog

## Requirements

- Python 3.8 or higher
- Tkinter (usually comes with Python)
- Additional dependencies listed in requirements.txt

## Installation

1. Clone this repository
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Install the package in development mode:
   ```bash
   pip install -e .
   ```

## Usage

1. Start the application:
   ```bash
   python src/main.py
   ```

2. Click "Start Server" to begin listening for analyzer connections

3. The application will:
   - Listen for analyzer connections on the configured port (default: 5000)
   - Display received results in real-time
   - Show scattergrams when available
   - Sync data to external server if configured

## Supported Analyzers

### SYSMEX XN-L Hematology Analyzer
- Uses ASTM protocol
- Full support for CBC results and scattergrams
- Capable of processing patient demographic information

### Mindray BS-430 Chemistry Analyzer
- Uses HL7 protocol
- Supports chemistry panel results and QC data

### HumaCount 5D Hematology Analyzer
- Uses LIS protocol (proprietary)
- Supports CBC results

### Roche Cobas Chemistry/Immunoassay Analyzers
- Uses ASTM protocol with Roche extensions
- Supports various models including c311, c501, c502, e411, e601, e602
- Full support for chemistry and immunoassay results

### Abbott ARCHITECT Clinical Chemistry Analyzers
- Uses POCT1-A protocol (XML-based)
- Supports various models including c4000, c8000, i1000, i2000
- Full support for chemistry and immunoassay results

### Siemens Dimension Clinical Chemistry Analyzers
- Uses ASTM protocol with Siemens extensions
- Supports Dimension EXL, RxL, Xpand, and Vista systems
- Full support for chemistry and immunoassay results

### RESPONSE 920 Chemistry Analyzer
- Uses custom proprietary protocol
- Basic result support

## Testing

To test the application without a real analyzer, use the provided simulators:

```bash
# For ASTM protocol test (SYSMEX, etc.)
python tests/test_analyzer.py

# For general protocol testing
python tests/test_core.py
```

These simulators will generate sample data and send it to the application.

## External Server Synchronization

The application can synchronize data with external servers using:
- Real-time synchronization (as results arrive)
- Scheduled synchronization (at specific times)
- Cron-based synchronization (using cron expressions)

Authentication methods supported:
- API Key
- Bearer Token
- Basic Authentication
- Custom Headers
- OAuth 2.0

## Configuration

Edit `config.json` or use the GUI configuration dialog to customize:
- Port number
- Analyzer type and protocol
- Application name and instance ID
- External server settings
- Sync frequency and authentication

## Directory Structure

```
labSync/
├── src/
│   ├── database/      # Database management
│   ├── gui/           # GUI components
│   ├── network/       # Network and sync functionality
│   ├── protocols/     # Protocol parsers for different analyzers
│   └── utils/         # Utilities for configuration and logging
├── tests/             # Test scripts and simulators
├── logs/              # Application logs
├── config.json        # Configuration file
└── requirements.txt   # Dependencies
```

## License

MIT License