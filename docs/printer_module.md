# Printer Module Technical Documentation

## Overview
The Printer Module manages printer configurations, routing, and communication for the Sistema Almareia Mirapraia. It supports both Network (ESC/POS) and Windows (RAW) printers, handling various ticket types such as bills, kitchen orders, fiscal receipts, and system notifications.

## Key Files
- `app/services/printer_manager.py`: Handles CRUD operations for printer configurations and settings.
- `app/services/printing_service.py`: Contains the core printing logic, ticket formatting, and communication with printer hardware.
- `data/printers.json`: Stores the list of configured printers.
- `data/printer_settings.json`: Stores default printer assignments (Bill, Fiscal, Kitchen, etc.).

## Core Functions

### Printer Configuration (`app/services/printer_manager.py`)

#### `load_printers()`
- **Purpose**: Loads the list of configured printers from `data/printers.json`.
- **Returns**: `list[dict]` - A list of printer objects.
- **Error Handling**: Returns an empty list if the file is missing or contains invalid JSON. Logs errors.

#### `save_printers(printers_data)`
- **Purpose**: Saves the list of printers to `data/printers.json`.
- **Parameters**: 
  - `printers_data` (`list[dict]`): List of printer objects to save.
- **Returns**: `None`

#### `load_printer_settings()`
- **Purpose**: Loads default printer assignments (e.g., which printer is for Bills).
- **Returns**: `dict` - Settings object (e.g., `{'bill_printer_id': '...', 'fiscal_printer_id': '...'}`).

#### `save_printer_settings(settings_data)`
- **Purpose**: Saves printer assignments to `data/printer_settings.json`.
- **Parameters**:
  - `settings_data` (`dict`): Settings object.
- **Returns**: `None`

### Printing Service (`app/services/printing_service.py`)

#### `send_to_printer(ip, port, data, retries=3)`
- **Purpose**: Sends raw bytes to a network printer using a TCP socket.
- **Parameters**:
  - `ip` (`str`): Printer IP address.
  - `port` (`int`): Printer port (default 9100).
  - `data` (`bytes`): Raw data to send (usually ESC/POS commands).
  - `retries` (`int`): Number of retry attempts (default 3). Implements exponential backoff.
- **Returns**: `(bool, str)` - Tuple containing success status and error message (if any).

#### `send_to_windows_printer(printer_name, data)`
- **Purpose**: Sends raw bytes to a locally installed Windows printer using `win32print`.
- **Parameters**:
  - `printer_name` (`str`): Name of the Windows printer.
  - `data` (`bytes`): Raw data to send.
- **Returns**: `(bool, str)` - Tuple containing success status and error message.

#### `print_system_notification(ip, title, message, printer_port=9100, is_windows=False, windows_name=None)`
- **Purpose**: Prints a short system notification slip (e.g., for errors or alerts).
- **Parameters**:
  - `ip` (`str`): Target IP (if network).
  - `title` (`str`): Notification title.
  - `message` (`str`): Notification body.
  - `printer_port` (`int`): Target port.
  - `is_windows` (`bool`): True if targeting a Windows printer.
  - `windows_name` (`str`): Windows printer name.
- **Returns**: `bool` - True if successful.

#### `print_order_items(table_id, waiter_name, new_items, printers_config, products_db)`
- **Purpose**: Routes and prints kitchen/bar order tickets based on product configuration.
- **Logic**:
  - Groups items by their assigned printer.
  - Formats tickets using `format_ticket`.
  - Sends jobs sequentially using a global lock (`print_lock`) to prevent race conditions.
- **Returns**: `dict` - Result summary and list of printed item IDs.

#### `print_bill(printer_config, table_id, items, subtotal, service_fee, total, waiter_name, guest_name=None, room_number=None)`
- **Purpose**: Prints the customer bill (conferência de conta).
- **Parameters**:
  - `printer_config` (`dict`): specific printer config to use (optional override).
  - `table_id`, `items`, etc.: Bill details.
- **Returns**: `(bool, str)` - Success status and error message.

#### `print_fiscal_receipt(printer_config, invoice_data)`
- **Purpose**: Prints an NFC-e fiscal receipt.
- **Parameters**:
  - `invoice_data` (`dict`): Structured data from the fiscal API.
- **Returns**: `(bool, str)` - Success status and error message.

## Usage Examples

### Sending a raw command to a network printer
```python
from app.services.printing_service import send_to_printer

ESC = b'\x1b'
cmd = ESC + b'@' + b'Hello World\n'
success, error = send_to_printer('192.168.1.100', 9100, cmd)
if not success:
    print(f"Failed: {error}")
```

### Loading printers
```python
from app.services.printer_manager import load_printers
printers = load_printers()
for p in printers:
    print(f"ID: {p['id']}, Name: {p['name']}")
```

## Security & Best Practices
- **Thread Safety**: Major printing functions use a global `threading.RLock` (`print_lock`) to ensure that concurrent requests do not interleave data on the printer stream.
- **Error Handling**: All network operations are wrapped in try/except blocks with logging. Network printing implements retry logic.
- **Input Validation**: Functions check for valid IP addresses and printer names before attempting connection.
- **Logging**: The module uses Python's `logging` library for structured error reporting instead of `print` statements.

