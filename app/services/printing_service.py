import socket
import threading
import time
import logging
from datetime import datetime
from app.services.printer_manager import load_printer_settings, load_printers

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global lock for printing synchronization
print_lock = threading.RLock()

try:
    import win32print
except ImportError:
    win32print = None

def format_room_number_str(room_number):
    """
    Formats a room number to ensure 2 digits (e.g., '1' -> '01', '01' -> '01', '10' -> '10').
    Handles strings and integers. Returns a string.
    Duplicate of app.py logic to avoid circular imports.
    """
    if room_number is None:
        return ""
    try:
        # Check if it's a number (or string representation of a number)
        if isinstance(room_number, int) or (isinstance(room_number, str) and room_number.isdigit()):
            num = int(room_number)
            if 1 <= num <= 9:
                return f"{num:02d}"
        return str(room_number)
    except (ValueError, TypeError):
        return str(room_number)

def get_available_windows_printers():
    """Returns a list of installed Windows printers."""
    if not win32print:
        return []
    try:
        printers = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS)
        return [p[2] for p in printers]
    except Exception as e:
        print(f"Error listing printers: {e}")
        return []

def send_to_windows_printer(printer_name, data):
    """Sends raw bytes to a Windows printer."""
    if not win32print:
        return False, "win32print module not installed"
    
    try:
        with print_lock:
            hPrinter = win32print.OpenPrinter(printer_name)
            try:
                hJob = win32print.StartDocPrinter(hPrinter, 1, ("Print Job", None, "RAW"))
                try:
                    win32print.StartPagePrinter(hPrinter)
                    win32print.WritePrinter(hPrinter, data)
                    win32print.EndPagePrinter(hPrinter)
                finally:
                    win32print.EndDocPrinter(hPrinter)
            finally:
                win32print.ClosePrinter(hPrinter)
        return True, None
    except Exception as e:
        return False, str(e)

def send_to_printer(ip, port, data, retries=3):
    """
    Sends data to a network printer with exponential backoff retry logic.
    """
    last_error = None
    
    for attempt in range(1, retries + 1):
        try:
            with print_lock:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(5) # 5 seconds timeout for connection
                    s.connect((ip, int(port)))
                    s.sendall(data)
            return True, None
        except Exception as e:
            last_error = str(e)
            wait_time = 0.5 * (2 ** (attempt - 1)) # 0.5s, 1s, 2s
            logger.warning(f"Print attempt {attempt}/{retries} failed for {ip}:{port}: {e}. Retrying in {wait_time}s...")
            if attempt < retries:
                time.sleep(wait_time)
            
    logger.error(f"Failed to print to {ip}:{port} after {retries} attempts. Last error: {last_error}")
    return False, last_error

def get_printer_by_id(printer_id):
    """Retrieves printer configuration by ID."""
    if not printer_id:
        return None
    printers = load_printers()
    return next((p for p in printers if str(p.get('id')) == str(printer_id)), None)

def get_default_printer(role):
    """
    Retrieves the default printer for a specific role (bill, fiscal, kitchen, bar, reception).
    """
    settings = load_printer_settings()
    printer_id = settings.get(f'{role}_printer_id')
    return get_printer_by_id(printer_id)

def test_printer_connection(printer_config):
    """
    Tests the connection to a printer (Windows or Network).
    """
    ptype = printer_config.get('type', 'network')
    
    # Create test content
    ESC = b'\x1b'
    GS = b'\x1d'
    cmd = ESC + b'@' # Initialize
    cmd += ESC + b'a' + b'\x01' # Center
    cmd += GS + b'!' + b'\x11' # Double height/width
    cmd += b'TESTE DE IMPRESSAO\n'
    cmd += GS + b'!' + b'\x00' # Normal
    cmd += b'--------------------------------\n'
    cmd += f"Impressora: {printer_config['name']}\n".encode('cp850', errors='replace')
    cmd += f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n".encode('cp850', errors='replace')
    cmd += b'--------------------------------\n'
    cmd += b'\n\n\n'
    cmd += GS + b'V' + b'\x41' + b'\x03' # Cut

    if ptype == 'windows':
        printer_name = printer_config.get('windows_name')
        if not printer_name:
            return False, "Nome da impressora Windows nao configurado."
        return send_to_windows_printer(printer_name, cmd)
    else:
        ip = printer_config.get('ip')
        port = printer_config.get('port', 9100)
        if not ip:
            return False, "IP nao configurado."
        return send_to_printer(ip, port, cmd)

def print_system_notification(ip, title, message, printer_port=9100, is_windows=False, windows_name=None):
    """
    Prints a system notification (short slip) to a kitchen/bar printer.
    Used for pauses, errors, or system alerts.
    """
    try:
        # ESC/POS commands
        ESC = b'\x1b'
        GS = b'\x1d'
        INIT = ESC + b'@'
        CENTER = ESC + b'a' + b'\x01'
        LEFT = ESC + b'a' + b'\x00'
        BOLD = ESC + b'E' + b'\x01'
        NO_BOLD = ESC + b'E' + b'\x00'
        DOUBLE_HW = GS + b'!' + b'\x11'
        NORMAL = GS + b'!' + b'\x00'
        CUT = GS + b'V' + b'\x41' + b'\x03'
        
        cmd = INIT
        cmd += CENTER + BOLD + DOUBLE_HW
        cmd += f"{title}\n".encode('cp850', errors='replace')
        cmd += NO_BOLD + NORMAL
        cmd += b"--------------------------------\n"
        cmd += LEFT
        cmd += f"{datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n".encode('cp850', errors='replace')
        
        # Message body
        cmd += f"{message}\n".encode('cp850', errors='replace')
        
        cmd += b"\n\n\n"
        cmd += CUT
        
        if is_windows and windows_name:
            send_to_windows_printer(windows_name, cmd)
        else:
            # Network print
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect((ip, int(printer_port)))
                s.sendall(cmd)
                
        return True
    except Exception as e:
        print(f"Error printing system notification to {ip if not is_windows else windows_name}: {e}")
        return False

def print_cashier_ticket(printer_config, type_str, amount, user, reason):
    """
    Prints a cashier transaction ticket (Sangria/Suprimento).
    Includes signature line for Sangria.
    """
    try:
        # ESC/POS commands
        ESC = b'\x1b'
        GS = b'\x1d'
        INIT = ESC + b'@'
        CENTER = ESC + b'a' + b'\x01'
        LEFT = ESC + b'a' + b'\x00'
        BOLD = ESC + b'E' + b'\x01'
        NO_BOLD = ESC + b'E' + b'\x00'
        DOUBLE_HW = GS + b'!' + b'\x11'
        NORMAL = GS + b'!' + b'\x00'
        CUT = GS + b'V' + b'\x41' + b'\x03'
        
        cmd = INIT
        cmd += CENTER + BOLD + DOUBLE_HW
        cmd += f"{type_str.upper()}\n".encode('cp850', errors='replace')
        cmd += NO_BOLD + NORMAL
        cmd += b"--------------------------------\n"
        cmd += LEFT
        cmd += f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n".encode('cp850', errors='replace')
        cmd += f"Resp: {user}\n".encode('cp850', errors='replace')
        cmd += b"--------------------------------\n"
        
        cmd += CENTER + BOLD
        cmd += f"R$ {amount:.2f}\n".encode('cp850', errors='replace')
        cmd += NO_BOLD + LEFT
        cmd += b"\n"
        cmd += f"Motivo: {reason}\n".encode('cp850', errors='replace')
        cmd += b"\n\n"
        
        if 'sangria' in type_str.lower() or 'retirada' in type_str.lower() or 'transferencia' in type_str.lower():
            cmd += b"\n\n"
            cmd += b"________________________________\n"
            cmd += b"      Assinatura Responsavel\n"
        
        cmd += b"\n\n\n"
        cmd += CUT
        
        if printer_config.get('type') == 'windows':
            return send_to_windows_printer(printer_config.get('windows_name'), cmd)
        else:
            ip = printer_config.get('ip')
            port = printer_config.get('port', 9100)
            if ip:
                return send_to_printer(ip, port, cmd)
            return False, "IP nao configurado"
            
    except Exception as e:
        print(f"Error printing cashier ticket: {e}")
        return False, str(e)

def print_cashier_ticket_async(printer_config, type_str, amount, user, reason):
    """
    Wraps print_cashier_ticket in a thread to prevent blocking the UI.
    """
    from threading import Thread
    try:
        Thread(target=print_cashier_ticket, args=(printer_config, type_str, amount, user, reason), daemon=True).start()
        return True
    except Exception as e:
        print(f"Failed to start async print: {e}")
        return False

def format_ticket(table_id, waiter_name, items, printer_name):
    """
    Formats the ticket content for thermal printing (80mm).
    Standardized layout for Kitchen/Bar.
    """
    # ESC/POS commands
    ESC = b'\x1b'
    GS = b'\x1d'
    
    # Commands
    INIT = ESC + b'@'
    CENTER = ESC + b'a' + b'\x01'
    LEFT = ESC + b'a' + b'\x00'
    RIGHT = ESC + b'a' + b'\x02'
    
    # Fonts
    NORMAL = GS + b'!' + b'\x00'
    BOLD = ESC + b'E' + b'\x01'
    NO_BOLD = ESC + b'E' + b'\x00'
    NORMAL = GS + b'!' + b'\x00'
    DOUBLE_HW = GS + b'!' + b'\x11' # Double Height & Width
    DOUBLE_H = GS + b'!' + b'\x10'  # Double Height
    DOUBLE_W = GS + b'!' + b'\x20'  # Double Width
    
    # Separator
    SEPARATOR = b'--------------------------------\n'
    DOUBLE_SEPARATOR = b'================================\n'

    # Initialize
    cmd = INIT
    
    # --- HEADER ---
    cmd += LEFT
    cmd += DOUBLE_SEPARATOR
    
    # Table (Highlight) - Now the main title
    cmd += BOLD + DOUBLE_H
    
    # Format table_id if it's a room number
    display_table_id = format_room_number_str(table_id)
    
    cmd += f"MESA: {display_table_id}\n".encode('cp850', errors='replace')
    cmd += NO_BOLD + NORMAL
    
    # Meta Info
    cmd += DOUBLE_SEPARATOR
    cmd += f"Garcom: {waiter_name}\n".encode('cp850', errors='replace')
    cmd += f"Data:   {datetime.now().strftime('%d/%m/%Y %H:%M')}\n".encode('cp850', errors='replace')
    cmd += SEPARATOR
    cmd += b'\n'
    
    # --- ITEMS ---
    total_qty = 0
    
    for item in items:
        qty = item['qty']
        name = item['name']
        try:
            total_qty += float(qty)
        except:
            pass

        # Notes / Observations Logic
        notes = item.get('notes', '')
        observations = item.get('observations', [])
        
        final_notes = []
        
        # 1. Add observations (List or String)
        if observations:
            if isinstance(observations, list):
                final_notes.extend([str(o) for o in observations if o])
            elif isinstance(observations, str):
                final_notes.append(observations)
                
        # 2. Add legacy notes (String)
        if notes:
            final_notes.append(str(notes))

        # Format: QTY x NAME
        # We use Double Width for QTY to make it pop
        cmd += LEFT
        
        # Qty Line
        cmd += BOLD + DOUBLE_H
        # Format quantity as integer
        try:
            qty_val = float(qty)
            qty_display = str(int(qty_val)) if qty_val.is_integer() else str(qty_val)
            # Force integer as per user request if it looks like a float but user wants 1, 2, 11
            qty_display = str(int(qty_val))
        except:
            qty_display = str(qty)

        cmd += f"{qty_display} ".encode('cp850', errors='replace') 
        cmd += NO_BOLD + NORMAL 
        
        # 'x ' separator
        cmd += b'x '
        
        # Name (Bold)
        cmd += BOLD + NORMAL
        cmd += f"{name}\n".encode('cp850', errors='replace')
        cmd += NO_BOLD + NORMAL
        
        # Sub-items (Flavors & Accompaniments) - Unified Logic
        sub_items = []
        
        # 1. Flavors
        if item.get('flavor'):
            # Handle potential multiple flavors (comma separated string)
            flavors_list = [f.strip() for f in item['flavor'].split(',')] if ',' in item['flavor'] else [item['flavor']]
            sub_items.extend(flavors_list)
            
        # 2. Accompaniments
        if item.get('accompaniments'):
            sub_items.extend(item['accompaniments'])
            
        # Print sub-items with consistent format
        for sub in sub_items:
             cmd += f"   - {sub}\n".encode('cp850', errors='replace')

        # Complements (keep distinct with +)
        if item.get('complements'):
            for comp in item['complements']:
                 # Handle if comp is dict or string
                 comp_name = comp['name'] if isinstance(comp, dict) and 'name' in comp else str(comp)
                 cmd += f"   + {comp_name}\n".encode('cp850', errors='replace')
        
        # Questions Answers
        questions_answers = item.get('questions_answers', [])
        if questions_answers:
            for qa in questions_answers:
                q_text = qa.get('question', '')
                a_text = qa.get('answer', '')
                cmd += f"   > {q_text}: {a_text}\n".encode('cp850', errors='replace')

        # Notes (Indented, Inverted or just distinct)
        if final_notes:
            for note in final_notes:
                cmd += f"   *** {note} ***\n".encode('cp850', errors='replace')
            
        cmd += b'\n' # Spacing between items

    # --- FOOTER ---
    cmd += SEPARATOR
    cmd += LEFT
    cmd += f"Total de Itens: {int(total_qty) if total_qty.is_integer() else total_qty}\n".encode('cp850', errors='replace')
    cmd += LEFT
    cmd += DOUBLE_SEPARATOR
    
    # Cut
    cmd += b'\n\n\n\n'
    cmd += GS + b'V' + b'\x41' + b'\x03'
    
    return cmd

def print_order_items(table_id, waiter_name, new_items, printers_config, products_db):
    """
    Groups items by printer and sends print jobs.
    new_items: list of dicts {name, qty, ...}
    printers_config: list of dicts {id, name, ip, port}
    products_db: list of dicts (to look up printer_id for product name)
    """
    # Acquire lock to ensure sequential printing (prevents race conditions from concurrent requests)
    if not print_lock.acquire(timeout=10):
        logger.error(f"Could not acquire print lock for table {table_id}")
        return {"results": {"error": "System busy, try again"}, "printed_ids": []}
        
    try:
        if not new_items:
            logger.warning(f"Print request for Table {table_id} ignored: No items provided.")
            return {"results": {"error": "No items"}, "printed_ids": []}

        logger.info(f"Processing print order for Table {table_id} (Items: {len(new_items)})")
        
        # Create a map of product name -> printer_id
        product_printer_map = {}
        for p in products_db:
            should_print = p.get('should_print', True)
            if should_print and 'printer_id' in p and p['printer_id']:
                product_printer_map[p['name']] = p['printer_id']
                
        # Group items by (printer_id, category)
        jobs = {} # (printer_id, category) -> list of items
        
        for item in new_items:
            p_name = item['name']
            printer_id = product_printer_map.get(p_name)
            
            if not printer_id:
                # Fallback to default kitchen printer
                default_kitchen = get_default_printer('kitchen')
                if default_kitchen:
                    printer_id = default_kitchen['id']
            
            if printer_id:
                key = printer_id # Group only by printer_id
                if key not in jobs:
                    jobs[key] = []
                jobs[key].append(item)
            else:
                logger.warning(f"Item {p_name} has no assigned printer and no default kitchen printer found.")
                
        results = {}
        printed_item_ids = []
        
        # Process each job (printer)
        for printer_id, items in jobs.items():
            printer = next((p for p in printers_config if str(p['id']) == str(printer_id)), None)
            
            if printer:
                # Construct ticket data
                ticket_data = format_ticket(table_id, waiter_name, items, f"{printer['name']}")
                
                # Send to printer
                success = False
                error = None
                
                if printer.get('type') == 'windows':
                    success, error = send_to_windows_printer(printer.get('windows_name'), ticket_data)
                else:
                    # Default to network
                    success, error = send_to_printer(printer.get('ip'), printer.get('port', 9100), ticket_data)
                
                results[f"{printer['name']}"] = "OK" if success else f"Error: {error}"
                
                if success:
                    for item in items:
                        if 'id' in item:
                            printed_item_ids.append(item['id'])
                else:
                    logger.error(f"Failed to print to {printer['name']}: {error}")
        
        return {"results": results, "printed_ids": printed_item_ids}
        
    except Exception as e:
        logger.error(f"Unexpected error in print_order_items: {e}")
        return {"results": {"error": str(e)}, "printed_ids": []}
    finally:
        print_lock.release()

def print_transfer_ticket(from_table, to_table, waiter_name, printers_config):
    """
    Prints a notification about table transfer to Bar and Kitchen printers.
    Ensures unique printing per IP/Device to avoid duplication.
    """
    # Build ticket
    ESC = b'\x1b'
    GS = b'\x1d'
    INIT = ESC + b'@'
    CENTER = ESC + b'a' + b'\x01'
    BOLD = ESC + b'E' + b'\x01'
    NO_BOLD = ESC + b'E' + b'\x00'
    DOUBLE_HW = GS + b'!' + b'\x11'
    
    cmd = INIT + CENTER + DOUBLE_HW + BOLD
    cmd += b'*** TRANSFERENCIA ***\n\n'
    cmd += NO_BOLD + BOLD
    cmd += f"DE: MESA {from_table}\n".encode('cp850', errors='replace')
    cmd += f"PARA: MESA {to_table}\n".encode('cp850', errors='replace')
    cmd += b'\n'
    cmd += NO_BOLD
    cmd += f"Garcom: {waiter_name}\n".encode('cp850', errors='replace')
    cmd += f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n".encode('cp850', errors='replace')
    cmd += b'\n\n'
    cmd += b"________________________________\n"
    cmd += b"      Assinatura Responsavel\n"
    cmd += b'\n\n\n'
    cmd += GS + b'V' + b'\x41' + b'\x03'
    
    # Identify unique target printers (Bar and Kitchen)
    unique_targets = {} # Key -> PrinterConfig
    
    # Helper to generate unique key for printer
    def get_printer_key(p):
        if p.get('type') == 'windows':
            return f"win:{p.get('windows_name')}"
        else:
            return f"net:{p.get('ip')}:{p.get('port', 9100)}"

    # 1. Add Default Bar Printer
    bar_p = get_default_printer('bar')
    if bar_p:
        unique_targets[get_printer_key(bar_p)] = bar_p
        
    # 2. Add Default Kitchen Printer
    kitchen_p = get_default_printer('kitchen')
    if kitchen_p:
        unique_targets[get_printer_key(kitchen_p)] = kitchen_p
        
    # 3. Fallback/Supplement: Scan all printers if defaults not sufficient or to ensure coverage?
    # Requirement: "exclusivamente para duas categorias... Bar e Cozinha"
    # If defaults are set, we rely on them. 
    # If defaults are NOT set, we should look for printers with 'Bar' or 'Cozinha' in name.
    
    if not unique_targets:
        for p in printers_config:
            name_lower = p.get('name', '').lower()
            if 'bar' in name_lower or 'cozinha' in name_lower or 'kitchen' in name_lower:
                unique_targets[get_printer_key(p)] = p
    
    logger.info(f"Printing transfer ticket to {len(unique_targets)} unique destinations.")
    
    for key, printer in unique_targets.items():
        try:
            if printer.get('type') == 'windows':
                send_to_windows_printer(printer.get('windows_name'), cmd)
            else:
                send_to_printer(printer.get('ip'), printer.get('port', 9100), cmd)
        except Exception as e:
            logger.error(f"Error printing transfer ticket to {key}: {e}")

def print_consolidated_stock_warning(items, printers_config):
    """
    Prints a consolidated warning ticket to the Kitchen printer about low stock for multiple items.
    items: list of dicts {'name': product_name, 'qty': current_qty}
    """
    if not items:
        return

    # Build ticket
    ESC = b'\x1b'
    GS = b'\x1d'
    INIT = ESC + b'@'
    CENTER = ESC + b'a' + b'\x01'
    LEFT = ESC + b'a' + b'\x00'
    BOLD = ESC + b'E' + b'\x01'
    NO_BOLD = ESC + b'E' + b'\x00'
    DOUBLE_HW = GS + b'!' + b'\x11'
    
    cmd = INIT + CENTER + DOUBLE_HW + BOLD
    cmd += b'!!! ESTOQUE BAIXO !!!\n\n'
    cmd += NO_BOLD + LEFT
    cmd += f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n".encode('cp850', errors='replace')
    cmd += b"--------------------------------\n"
    cmd += BOLD
    
    for item in items:
        cmd += f"{item['name'][:25]:<25} {item['qty']:>5.2f}\n".encode('cp850', errors='replace')
        
    cmd += NO_BOLD
    cmd += b'\n\n\n'
    cmd += GS + b'V' + b'\x41' + b'\x03'
    
    # Send to Kitchen printers only (Deduplicated)
    target_printers = []
    seen_ips = set()
    
    for p in printers_config:
        if 'Cozinha' in p.get('name', '') or 'Kitchen' in p.get('name', ''):
            # Key for deduplication: IP:Port or Name (for windows)
            key = p.get('windows_name') if p.get('type') == 'windows' else f"{p.get('ip')}:{p.get('port')}"
            if key and key not in seen_ips:
                target_printers.append(p)
                seen_ips.add(key)
    
    # Fallback if no specific kitchen printer
    if not target_printers:
        default_kitchen = get_default_printer('kitchen')
        if default_kitchen:
            target_printers.append(default_kitchen)

    for printer in target_printers:
        try:
            if printer.get('type') == 'windows':
                send_to_windows_printer(printer.get('windows_name'), cmd)
            else:
                send_to_printer(printer.get('ip'), printer.get('port', 9100), cmd)
        except:
            pass

def print_stock_warning(product_name, current_qty, printers_config):
    """
    Prints a warning ticket to the Kitchen printer about low stock.
    """
    # Build ticket
    ESC = b'\x1b'
    GS = b'\x1d'
    INIT = ESC + b'@'
    CENTER = ESC + b'a' + b'\x01'
    BOLD = ESC + b'E' + b'\x01'
    NO_BOLD = ESC + b'E' + b'\x00'
    DOUBLE_HW = GS + b'!' + b'\x11'
    
    cmd = INIT + CENTER + DOUBLE_HW + BOLD
    cmd += b'!!! ESTOQUE BAIXO !!!\n\n'
    cmd += NO_BOLD + BOLD
    cmd += f"PRODUTO: {product_name}\n".encode('cp850', errors='replace')
    cmd += f"RESTAM: {current_qty:.2f}\n".encode('cp850', errors='replace')
    cmd += b'\n'
    cmd += NO_BOLD
    cmd += f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n".encode('cp850', errors='replace')
    cmd += b'\n\n\n'
    cmd += GS + b'V' + b'\x41' + b'\x03'
    
    # Send to Kitchen printer
    kitchen_p = get_default_printer('kitchen')
    if kitchen_p:
        try:
            if kitchen_p.get('type') == 'windows':
                send_to_windows_printer(kitchen_p.get('windows_name'), cmd)
            else:
                send_to_printer(kitchen_p.get('ip'), kitchen_p.get('port', 9100), cmd)
        except:
            pass

def process_and_print_pending_bills(pending_bills, printer_name=None):
    # This function is used by reception reports (A4 or thermal list)
    # The user asked for specific individual bill printing, handled separately.
    # This existing function can remain as is, but we should ensure it uses the reception printer if printer_name is not passed.
    
    if not printer_name:
        rec_p = get_default_printer('reception')
        if rec_p:
            printer_name = rec_p.get('windows_name') if rec_p.get('type') == 'windows' else None
            # If network, this function currently doesn't support it well because it builds a big report
            # The existing implementation seems to support windows mostly for reports or network with raw commands
            # We will keep it but acknowledge it might need the reception printer config.
            pass

    # ... (Keep existing implementation logic) ...
    # Re-implementing just to be safe and avoid code loss during overwrite
    # ESC/POS commands
    ESC = b'\x1b'
    GS = b'\x1d'
    INIT = ESC + b'@'
    CENTER = ESC + b'a' + b'\x01'
    LEFT = ESC + b'a' + b'\x00'
    RIGHT = ESC + b'a' + b'\x02'
    BOLD = ESC + b'E' + b'\x01'
    NO_BOLD = ESC + b'E' + b'\x00'
    NORMAL = GS + b'!' + b'\x00'
    DOUBLE_H = GS + b'!' + b'\x10'
    SEPARATOR = b'--------------------------------\n'
    DOUBLE_SEPARATOR = b'================================\n'
    
    result = {
        "bills_processed": [],
        "summary": {
            "total_bills_count": 0,
            "grand_total": 0.0,
            "origin_totals": [],
            "product_totals": {}
        },
        "errors": []
    }
    
    cmd = INIT
    cmd += CENTER + BOLD + DOUBLE_H
    cmd += b'RELATORIO DE CONTAS\nPENDENTES\n'
    cmd += NO_BOLD + NORMAL
    cmd += f"{datetime.now().strftime('%d/%m/%Y %H:%M')}\n".encode('cp850', errors='replace')
    cmd += DOUBLE_SEPARATOR + LEFT
    
    total_bills_count = 0
    grand_total = 0.0
    
    for index, bill in enumerate(pending_bills):
        try:
            origin = bill.get('origin', {})
            client = origin.get('client', 'N/A')
            table = origin.get('table', 'N/A')
            order_id = origin.get('order_id', 'N/A')
            products = bill.get('products', [])
            if not products: continue
            
            bill_total = 0.0
            cmd += BOLD + f"CONTA #{index + 1}\n".encode('cp850', errors='replace') + NO_BOLD
            cmd += f"Origem: {client} | Mesa: {table}\n".encode('cp850', errors='replace')
            cmd += f"Pedido: {order_id}\n".encode('cp850', errors='replace')
            cmd += SEPARATOR
            
            bill_products_processed = []
            for prod in products:
                name = prod.get('name', 'Item')
                qty = float(prod.get('qty', 0))
                subtotal = float(prod.get('subtotal', 0))
                bill_total += subtotal
                
                if name not in result["summary"]["product_totals"]:
                    result["summary"]["product_totals"][name] = 0.0
                result["summary"]["product_totals"][name] += qty
                
                qty_display = f"{int(qty)}" if qty.is_integer() else f"{qty:.2f}"
                cmd += f"{qty_display} x {name}\n".encode('cp850', errors='replace')
                cmd += RIGHT + f"R$ {subtotal:.2f}\n".encode('cp850', errors='replace') + LEFT
                
                bill_products_processed.append({"name": name, "qty": qty, "subtotal": subtotal})
            
            cmd += SEPARATOR
            cmd += RIGHT + BOLD + f"TOTAL: R$ {bill_total:.2f}\n".encode('cp850', errors='replace') + NO_BOLD + LEFT
            cmd += b'\n'
            
            grand_total += bill_total
            total_bills_count += 1
            
            result["bills_processed"].append({"origin": origin, "products": bill_products_processed, "total": bill_total})
            result["summary"]["origin_totals"].append({"origin_desc": f"{client} (Mesa {table})", "total": bill_total})
            
        except Exception as e:
            result["errors"].append(f"Error: {e}")
            continue

    cmd += DOUBLE_SEPARATOR
    cmd += CENTER + BOLD + b'RESUMO GERAL\n' + NO_BOLD + LEFT
    cmd += f"Contas: {total_bills_count}\n".encode('cp850', errors='replace')
    cmd += BOLD + f"TOTAL: R$ {grand_total:.2f}\n".encode('cp850', errors='replace') + NO_BOLD
    cmd += b'\n\n\n\n' + GS + b'V' + b'\x41' + b'\x03'
    
    result["summary"]["total_bills_count"] = total_bills_count
    result["summary"]["grand_total"] = grand_total
    
    if printer_name:
        send_to_windows_printer(printer_name, cmd)
    else:
        # Try sending to reception printer if configured
        rec_p = get_default_printer('reception')
        if rec_p:
            if rec_p.get('type') == 'windows':
                send_to_windows_printer(rec_p.get('windows_name'), cmd)
            else:
                send_to_printer(rec_p.get('ip'), rec_p.get('port', 9100), cmd)

    return result

def format_bill(table_id, items, subtotal, service_fee, total, waiter_name, guest_name=None, room_number=None):
    """
    Formats the conference bill (Pre-closing).
    """
    ESC = b'\x1b'
    GS = b'\x1d'
    INIT = ESC + b'@'
    CENTER = ESC + b'a' + b'\x01'
    LEFT = ESC + b'a' + b'\x00'
    RIGHT = ESC + b'a' + b'\x02'
    BOLD = ESC + b'E' + b'\x01'
    NO_BOLD = ESC + b'E' + b'\x00'
    DOUBLE_HW = GS + b'!' + b'\x11'
    DOUBLE_H = GS + b'!' + b'\x10'
    NORMAL = GS + b'!' + b'\x00'
    SEPARATOR = b'--------------------------------\n'
    
    cmd = INIT + CENTER + BOLD
    cmd += b'RESTAURANTE MIRAPRAIA\n'
    cmd += NO_BOLD
    cmd += b'CONFERENCIA DE CONTA\n'
    cmd += SEPARATOR
    
    # --- HEADER MODIFICATION ---
    cmd += LEFT
    
    # 1. Guest/Room Info (High Priority)
    if room_number or guest_name:
        cmd += BOLD + DOUBLE_H
        if room_number:
            cmd += f"QUARTO: {room_number}\n".encode('cp850', errors='replace')
        if guest_name:
            cmd += f"HOSPEDE: {guest_name[:20]}\n".encode('cp850', errors='replace') # Truncate to fit
        cmd += NO_BOLD + NORMAL
        cmd += SEPARATOR

    # 2. Table and Meta
    cmd += f"Mesa: {table_id}\n".encode('cp850', errors='replace')
    cmd += f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n".encode('cp850', errors='replace')
    cmd += f"Garcom: {waiter_name}\n".encode('cp850', errors='replace')
    
    cmd += SEPARATOR
    cmd += b'ITEM                 QTD   VALOR\n'
    cmd += SEPARATOR
    
    for item in items:
        name = item['name'][:20]
        qty = item['qty']
        price = item['price'] * qty
        line = f"{name:<20} {qty:>3.0f} {price:>7.2f}\n"
        cmd += line.encode('cp850', errors='replace')
        
    cmd += SEPARATOR
    cmd += RIGHT + BOLD
    cmd += f"SUBTOTAL: R$ {subtotal:.2f}\n".encode('cp850', errors='replace')
    if service_fee > 0:
        cmd += f"SERVICO (10%): R$ {service_fee:.2f}\n".encode('cp850', errors='replace')
    
    cmd += DOUBLE_HW
    cmd += f"TOTAL: R$ {total:.2f}\n".encode('cp850', errors='replace')
    cmd += NO_BOLD + NORMAL + CENTER
    cmd += b'\nNAO E DOCUMENTO FISCAL\n'
    cmd += b'\n\n\n' + GS + b'V' + b'\x41' + b'\x03'
    
    return cmd

def print_bill(printer_config, table_id, items, subtotal, service_fee, total, waiter_name, guest_name=None, room_number=None):
    """
    Sends the bill to the configured BILL printer.
    """
    # Use configuration instead of hardcoded IP
    target_printer = get_default_printer('bill')
    
    if not target_printer:
        # Fallback to the passed config if valid
        if printer_config and (printer_config.get('ip') or printer_config.get('type') == 'windows'):
            target_printer = printer_config
        else:
            logger.error("No bill printer configured.")
            return False, "Impressora de conta não configurada."

    logger.info(f"Printing bill to {target_printer['name']}")

    try:
        data = format_bill(table_id, items, subtotal, service_fee, total, waiter_name, guest_name, room_number)
        
        if target_printer.get('type') == 'windows':
            return send_to_windows_printer(target_printer.get('windows_name'), data)
        else:
            return send_to_printer(target_printer.get('ip'), target_printer.get('port', 9100), data)

    except Exception as e:
        logger.error(f"Error printing bill: {e}")
        return False, str(e)

def format_cancellation_ticket(table_id, waiter_name, items, printer_name, justification=None):
    # ... (Same as before) ...
    ESC = b'\x1b'
    GS = b'\x1d'
    INIT = ESC + b'@'
    CENTER = ESC + b'a' + b'\x01'
    LEFT = ESC + b'a' + b'\x00'
    NORMAL = GS + b'!' + b'\x00'
    BOLD = ESC + b'E' + b'\x01'
    NO_BOLD = ESC + b'E' + b'\x00'
    DOUBLE_HW = GS + b'!' + b'\x11'
    DOUBLE_H = GS + b'!' + b'\x10'
    SEPARATOR = b'--------------------------------\n'
    DOUBLE_SEPARATOR = b'================================\n'
    
    cmd = INIT + CENTER + DOUBLE_SEPARATOR
    cmd += BOLD + DOUBLE_HW + b"*** CANCELAMENTO ***\n" + NO_BOLD + NORMAL
    cmd += LEFT + DOUBLE_SEPARATOR
    
    display_table_id = format_room_number_str(table_id)
    cmd += BOLD + DOUBLE_H + f"MESA: {display_table_id}\n".encode('cp850', errors='replace') + NO_BOLD + NORMAL
    
    cmd += DOUBLE_SEPARATOR
    cmd += f"Solicitante: {waiter_name}\n".encode('cp850', errors='replace')
    cmd += f"Data:   {datetime.now().strftime('%d/%m/%Y %H:%M')}\n".encode('cp850', errors='replace')
    if justification:
        cmd += b'\nMOTIVO:\n' + f"{justification}\n".encode('cp850', errors='replace')
    cmd += SEPARATOR + b'\n'
    
    for item in items:
        qty = item['qty']
        name = item['name']
        cmd += LEFT + BOLD + DOUBLE_H
        try:
            qty_val = float(qty)
            qty_display = str(int(qty_val)) if qty_val.is_integer() else str(qty_val)
        except:
            qty_display = str(qty)
        cmd += f"-{qty_display} ".encode('cp850', errors='replace') + NO_BOLD + NORMAL + b'x '
        cmd += BOLD + NORMAL + f"{name}\n".encode('cp850', errors='replace') + NO_BOLD + NORMAL + b'\n'

    cmd += SEPARATOR + b'\n\n\n\n' + GS + b'V' + b'\x41' + b'\x03'
    return cmd

def print_cancellation_items(table_id, waiter_name, cancelled_items, printers_config, products_db, justification=None):
    settings = load_printer_settings()
    if settings.get('frigobar_filter_enabled', True):
        filtered_items = []
        for item in cancelled_items:
            product = next((p for p in products_db if p['name'] == item['name']), None)
            category = product.get('category') if product else item.get('category')
            if category != 'Frigobar':
                filtered_items.append(item)
        cancelled_items = filtered_items
        if not cancelled_items: return

    # Use same logic as print_order_items for routing
    printer_groups = {}
    for item in cancelled_items:
        product = next((p for p in products_db if p['name'] == item['name']), None)
        printer_id = product.get('printer_id') if product else None
        
        if not printer_id:
            kitchen_p = get_default_printer('kitchen')
            printer_id = kitchen_p['id'] if kitchen_p else None
            
        if printer_id:
            if printer_id not in printer_groups: printer_groups[printer_id] = []
            printer_groups[printer_id].append(item)
            
    for printer_id, items in printer_groups.items():
        printer = next((p for p in printers_config if str(p['id']) == str(printer_id)), None)
        if printer:
            try:
                ticket_data = format_cancellation_ticket(table_id, waiter_name, items, printer['name'], justification)
                if printer['type'] == 'windows':
                    send_to_windows_printer(printer['windows_name'], ticket_data)
                else:
                    send_to_printer(printer['ip'], int(printer.get('port', 9100)), ticket_data)
            except Exception as e:
                print(f"Error printing cancellation: {e}")

def format_fiscal_receipt(invoice_data, printer_width=32):
    # ... (Keep existing) ...
    ESC = b'\x1b'
    GS = b'\x1d'
    INIT = ESC + b'@'
    CENTER = ESC + b'a' + b'\x01'
    LEFT = ESC + b'a' + b'\x00'
    RIGHT = ESC + b'a' + b'\x02'
    NORMAL = GS + b'!' + b'\x00'
    BOLD = ESC + b'E' + b'\x01'
    NO_BOLD = ESC + b'E' + b'\x00'
    SEPARATOR = b'--------------------------------\n'
    
    env = invoice_data.get('ambiente', 'homologacao')
    auth = invoice_data.get('autorizacao', {})
    chave = invoice_data.get('chave', auth.get('chave_acesso', ''))
    proto = auth.get('numero_protocolo', '')
    data_emi = invoice_data.get('data_emissao', '')
    
    cmd = INIT + CENTER
    if env == 'homologacao':
        cmd += BOLD + b'AMBIENTE DE HOMOLOGACAO\nSEM VALOR FISCAL\n' + NO_BOLD + SEPARATOR
    
    cmd += BOLD + b'RESTAURANTE MIRAPRAIA LTDA\n' + NO_BOLD
    cmd += b'CNPJ: 28.952.732/0001-09\nBEIRA MAR, S/N - TAMANDARE, PE\n' + SEPARATOR
    cmd += BOLD + b'NFC-e - Nota Fiscal de Consumidor Eletronica\n' + NO_BOLD + SEPARATOR
    
    cmd += LEFT + b'ITEM CODIGO DESCRICAO\nQTD UN VL UNIT(R$) ST VL ITEM(R$)\n' + SEPARATOR
    
    # Items would go here if passed in detail, assuming invoice_data structure matches standard
    
    cmd += RIGHT
    total_val = invoice_data.get('valor_total', 0.0)
    cmd += BOLD + f"VALOR TOTAL R$ {total_val:.2f}\n".encode('cp850', errors='replace') + NO_BOLD + SEPARATOR
    
    cmd += CENTER + b'Consulta via Leitor de QR Code\n\n'
    cmd += LEFT + f"Chave de Acesso:\n{chave}\nProtocolo: {proto}\nData: {data_emi}\n".encode('cp850', errors='replace')
    cmd += b'\n' + CENTER + b'Consulte pela Chave de Acesso em:\nhttp://nfce.sefaz.pe.gov.br/\n'
    cmd += b'\n\n\n\n' + GS + b'V' + b'\x41' + b'\x03'
    return cmd

def print_fiscal_receipt(printer_config, invoice_data):
    try:
        # Use configuration
        target_printer = get_default_printer('fiscal')
        
        if not target_printer:
            if printer_config and (printer_config.get('ip') or printer_config.get('type') == 'windows'):
                target_printer = printer_config
            else:
                return False, "Impressora Fiscal não configurada"

        data = format_fiscal_receipt(invoice_data)
        
        if target_printer.get('type') == 'windows':
            return send_to_windows_printer(target_printer.get('windows_name'), data)
        return send_to_printer(target_printer.get('ip'), target_printer.get('port', 9100), data)
        
    except Exception as e:
        logger.error(f"Error printing fiscal receipt: {e}")
        return False, str(e)

def format_individual_bill_thermal(room_num, guest_name, charges, total_amount):
    """
    Formats the individual bill for reception thermal printer (80mm).
    """
    ESC = b'\x1b'
    GS = b'\x1d'
    INIT = ESC + b'@'
    CENTER = ESC + b'a' + b'\x01'
    LEFT = ESC + b'a' + b'\x00'
    RIGHT = ESC + b'a' + b'\x02'
    BOLD = ESC + b'E' + b'\x01'
    NO_BOLD = ESC + b'E' + b'\x00'
    NORMAL = GS + b'!' + b'\x00'
    DOUBLE_HW = GS + b'!' + b'\x11'
    DOUBLE_H = GS + b'!' + b'\x10'
    SEPARATOR = b'--------------------------------\n'
    DOUBLE_SEPARATOR = b'================================\n'
    
    cmd = INIT + CENTER + BOLD + DOUBLE_H
    cmd += b'HOTEL ALMAREIA\n'
    cmd += NO_BOLD + NORMAL
    cmd += b'EXTRATO DE CONSUMO\n'
    cmd += SEPARATOR
    
    cmd += LEFT
    cmd += f"Quarto: {room_num}\n".encode('cp850', errors='replace')
    cmd += f"Hospede: {guest_name}\n".encode('cp850', errors='replace')
    cmd += f"Emissao: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n".encode('cp850', errors='replace')
    cmd += DOUBLE_SEPARATOR
    
    # Header Items
    cmd += b"DATA   DESCRICAO           VALOR\n"
    cmd += SEPARATOR
    
    for charge in charges:
        date = charge.get('date', '')
        # Truncate date to DD/MM
        date_short = date[:5]
        
        # Iterate sub items
        line_items = charge.get('items', [])
        if not line_items:
            # Try legacy key
            line_items = charge.get('line_items', [])
            
        if not line_items:
            # Fallback if no details
            desc = "Consumo Diverso"
            val = float(charge.get('total', 0))
            line = f"{date_short} {desc:<18} {val:>8.2f}\n"
            cmd += line.encode('cp850', errors='replace')
        else:
            charge_subtotal = 0.0
            for item in line_items:
                name = item['name'][:18]
                qty = float(item.get('qty', 1))
                
                # Fix for 0 values: use price * qty if total is missing
                val = float(item.get('total', 0))
                if val == 0:
                    val = float(item.get('price', 0)) * qty
                
                charge_subtotal += val
                
                # Format: DD/MM Qty x Name      Total
                if qty > 1:
                    desc = f"{int(qty)}x {name}"
                else:
                    desc = name
                    
                line = f"{date_short} {desc:<18} {val:>8.2f}\n"
                cmd += line.encode('cp850', errors='replace')
                
            # Service Fee line if applicable
            sf = float(charge.get('service_fee', 0))
            if sf > 0:
                 line = f"      Taxa Servico       {sf:>8.2f}\n"
                 cmd += line.encode('cp850', errors='replace')
                 charge_subtotal += sf
            
            # Print Charge Subtotal
            final_charge_total = float(charge.get('total', 0))
            if final_charge_total == 0:
                final_charge_total = charge_subtotal
                
            cmd += RIGHT + f"Subtotal: {final_charge_total:.2f}\n".encode('cp850', errors='replace') + LEFT
             
        cmd += b'- - - - - - - - - - - - - - - - \n'

    cmd += SEPARATOR
    cmd += RIGHT + BOLD + DOUBLE_H
    cmd += f"TOTAL: R$ {total_amount:.2f}\n".encode('cp850', errors='replace')
    cmd += NO_BOLD + NORMAL + CENTER
    cmd += b'\n'
    cmd += b'Obrigado pela preferencia!\n'
    cmd += b'www.hotelalmareia.com.br\n'
    cmd += b'\n\n\n\n' + GS + b'V' + b'\x41' + b'\x03'
    
    return cmd

def print_individual_bills_thermal(printer_id, room_num, guest_name, charges, total_amount):
    """
    Prints individual bills to the specified printer using thermal format.
    """
    printer = get_printer_by_id(printer_id)
    if not printer:
        return False, "Impressora não encontrada"
        
    data = format_individual_bill_thermal(room_num, guest_name, charges, total_amount)
    
    try:
        if printer.get('type') == 'windows':
            return send_to_windows_printer(printer.get('windows_name'), data)
        else:
            return send_to_printer(printer.get('ip'), printer.get('port', 9100), data)
    except Exception as e:
        logger.error(f"Error printing individual bills: {e}")
        return False, str(e)
