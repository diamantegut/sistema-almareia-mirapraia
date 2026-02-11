import socket
import threading
from datetime import datetime
from printer_manager import load_printer_settings

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

def send_to_printer(ip, port, data):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5)
            s.connect((ip, int(port)))
            s.sendall(data)
        return True, None
    except Exception as e:
        print(f"Error printing to {ip}:{port} - {e}")
        return False, str(e)

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
        notes = item.get('notes', '')
        
        try:
            total_qty += float(qty)
        except:
            pass

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
                 cmd += f"   + {comp}\n".encode('cp850', errors='replace')
        
        # Questions Answers
        questions_answers = item.get('questions_answers', [])
        if questions_answers:
            for qa in questions_answers:
                q_text = qa.get('question', '')
                a_text = qa.get('answer', '')
                cmd += f"   > {q_text}: {a_text}\n".encode('cp850', errors='replace')

        # Notes (Indented, Inverted or just distinct)
        if notes:
            # cmd += GS + b'B' + b'\x01' # Inverse Printing
            cmd += f"   *** {notes} ***\n".encode('cp850', errors='replace')
            # cmd += GS + b'B' + b'\x00' # End Inverse
            
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
    
    # Create a map of product name -> printer_id
    product_printer_map = {}
    for p in products_db:
        # Check if product is marked for printing (default to True for backward compatibility if not set, 
        # but if printer_id is set, usually it implies printing. 
        # However, the new flag 'should_print' controls this explicitly.)
        should_print = p.get('should_print', True)
        if should_print and 'printer_id' in p and p['printer_id']:
            product_printer_map[p['name']] = p['printer_id']
            
    # Group items by (printer_id, category)
    jobs = {} # (printer_id, category) -> list of items
    
    for item in new_items:
        p_name = item['name']
        printer_id = product_printer_map.get(p_name)
        # Get category from product db if available, else 'Geral'
        category = 'Geral'
        product_data = next((p for p in products_db if p['name'] == p_name), None)
        if product_data and product_data.get('category'):
            category = product_data['category']
        
        if printer_id:
            key = printer_id # Group only by printer_id
            if key not in jobs:
                jobs[key] = []
            jobs[key].append(item)
        else:
            # Item has no assigned printer
            pass
            
    results = {}
    printed_item_ids = []
    
    # Process each job (printer)
    for printer_id, items in jobs.items():
        printer = next((p for p in printers_config if str(p['id']) == str(printer_id)), None)
        
        if printer:
            # Construct ticket data
            # No category in header as requested
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
            
    return {"results": results, "printed_ids": printed_item_ids}

def print_transfer_ticket(from_table, to_table, waiter_name, printers_config):
    """
    Prints a notification about table transfer to all kitchen/bar printers.
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
    cmd += b'\n\n\n'
    cmd += GS + b'V' + b'\x41' + b'\x03'
    
    # Send to all non-reception printers (Kitchen/Bar)
    # Filter printers that are usually for orders
    target_printers = [p for p in printers_config if p.get('type') != 'windows' or 'Cozinha' in p.get('name', '') or 'Bar' in p.get('name', '')]
    if not target_printers:
        # Fallback: try all
        target_printers = printers_config
        
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
    
    # Send to Kitchen printers only
    target_printers = [p for p in printers_config if 'Cozinha' in p.get('name', '')]
    
    for printer in target_printers:
        try:
            if printer.get('type') == 'windows':
                send_to_windows_printer(printer.get('windows_name'), cmd)
            else:
                send_to_printer(printer.get('ip'), printer.get('port', 9100), cmd)
        except:
            pass

def process_and_print_pending_bills(pending_bills, printer_name=None):
    """
    Processes and prints a report of pending bills.
    
    Args:
        pending_bills (list): List of dictionaries containing bill info.
        printer_name (str): Name of the printer to send the report to.
        
    Returns:
        dict: Processed data including summary.
    """
    # ESC/POS commands
    ESC = b'\x1b'
    GS = b'\x1d'
    
    # Fonts & Styles
    INIT = ESC + b'@'
    CENTER = ESC + b'a' + b'\x01'
    LEFT = ESC + b'a' + b'\x00'
    RIGHT = ESC + b'a' + b'\x02'
    BOLD = ESC + b'E' + b'\x01'
    NO_BOLD = ESC + b'E' + b'\x00'
    NORMAL = GS + b'!' + b'\x00'
    DOUBLE_H = GS + b'!' + b'\x10'
    DOUBLE_W = GS + b'!' + b'\x20'
    
    SEPARATOR = b'--------------------------------\n'
    DOUBLE_SEPARATOR = b'================================\n'
    
    # Initialize result structure
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
            # Extract Origin Info
            origin = bill.get('origin', {})
            client = origin.get('client', 'N/A')
            table = origin.get('table', 'N/A')
            order_id = origin.get('order_id', 'N/A')
            
            products = bill.get('products', [])
            if not products:
                continue
                
            bill_total = 0.0
            
            # Header for this bill
            cmd += BOLD + f"CONTA #{index + 1}\n".encode('cp850', errors='replace') + NO_BOLD
            cmd += f"Origem: {client} | Mesa: {table}\n".encode('cp850', errors='replace')
            cmd += f"Pedido: {order_id}\n".encode('cp850', errors='replace')
            cmd += SEPARATOR
            
            bill_products_processed = []
            
            for prod in products:
                name = prod.get('name', 'Item Desconhecido')
                try:
                    qty = float(prod.get('qty', 0))
                except (ValueError, TypeError):
                    qty = 0.0
                    
                try:
                    unit_price = float(prod.get('unit_price', 0))
                except (ValueError, TypeError):
                    unit_price = 0.0
                    
                try:
                    subtotal = float(prod.get('subtotal', 0))
                    # Recalculate if 0 but we have qty/price? 
                    # Trust input for now, but fallback
                    if subtotal == 0 and qty > 0 and unit_price > 0:
                        subtotal = qty * unit_price
                except (ValueError, TypeError):
                    subtotal = 0.0
                
                bill_total += subtotal
                
                # Aggregate for summary
                if name not in result["summary"]["product_totals"]:
                    result["summary"]["product_totals"][name] = 0.0
                result["summary"]["product_totals"][name] += qty
                
                # Print Item
                # Format: Qty x Name ..... Subtotal
                qty_display = f"{int(qty)}" if qty.is_integer() else f"{qty:.2f}"
                cmd += f"{qty_display} x {name}\n".encode('cp850', errors='replace')
                cmd += RIGHT + f"R$ {subtotal:.2f}\n".encode('cp850', errors='replace') + LEFT
                
                bill_products_processed.append({
                    "name": name,
                    "qty": qty,
                    "unit_price": unit_price,
                    "subtotal": subtotal
                })
            
            cmd += SEPARATOR
            cmd += RIGHT + BOLD + f"TOTAL: R$ {bill_total:.2f}\n".encode('cp850', errors='replace') + NO_BOLD + LEFT
            cmd += b'\n'
            
            # Update Globals
            grand_total += bill_total
            total_bills_count += 1
            
            # Store processed data
            result["bills_processed"].append({
                "origin": origin,
                "products": bill_products_processed,
                "total": bill_total
            })
            
            result["summary"]["origin_totals"].append({
                "origin_desc": f"{client} (Mesa {table})",
                "total": bill_total
            })
            
        except Exception as e:
            error_msg = f"Erro processando conta index {index}: {str(e)}"
            print(error_msg)
            result["errors"].append(error_msg)
            continue

    # --- SUMMARY SECTION ---
    cmd += DOUBLE_SEPARATOR
    cmd += CENTER + BOLD + b'RESUMO GERAL\n' + NO_BOLD + LEFT
    cmd += DOUBLE_SEPARATOR
    
    cmd += f"Contas Processadas: {total_bills_count}\n".encode('cp850', errors='replace')
    cmd += BOLD + f"TOTAL GERAL: R$ {grand_total:.2f}\n".encode('cp850', errors='replace') + NO_BOLD
    cmd += SEPARATOR
    
    # By Origin
    cmd += CENTER + b'POR ORIGEM\n' + LEFT
    for item in result["summary"]["origin_totals"]:
        cmd += f"{item['origin_desc']}: R$ {item['total']:.2f}\n".encode('cp850', errors='replace')
    cmd += SEPARATOR
    
    # By Product
    cmd += CENTER + b'CONSUMO TOTAL\n' + LEFT
    sorted_products = sorted(result["summary"]["product_totals"].items(), key=lambda x: x[1], reverse=True)
    for name, qty in sorted_products:
        qty_display = f"{int(qty)}" if qty.is_integer() else f"{qty:.2f}"
        cmd += f"{qty_display} x {name}\n".encode('cp850', errors='replace')
    
    cmd += b'\n\n\n\n'
    cmd += GS + b'V' + b'\x41' + b'\x03'
    
    # Finalize result dict
    result["summary"]["total_bills_count"] = total_bills_count
    result["summary"]["grand_total"] = grand_total
    
    # Print if requested
    if printer_name:
        success, error = send_to_windows_printer(printer_name, cmd)
        if not success:
            result["errors"].append(f"Erro de impressao: {error}")
    
    return result

def format_bill(table_id, items, subtotal, service_fee, total, waiter_name, guest_name=None, room_number=None):
    """
    Formats the conference bill (Pre-closing).
    """
    # ESC/POS commands
    ESC = b'\x1b'
    GS = b'\x1d'
    INIT = ESC + b'@'
    CENTER = ESC + b'a' + b'\x01'
    LEFT = ESC + b'a' + b'\x00'
    RIGHT = ESC + b'a' + b'\x02'
    
    BOLD = ESC + b'E' + b'\x01'
    NO_BOLD = ESC + b'E' + b'\x00'
    DOUBLE_HW = GS + b'!' + b'\x11'
    NORMAL = GS + b'!' + b'\x00'
    
    SEPARATOR = b'--------------------------------\n'
    
    cmd = INIT + CENTER + BOLD
    cmd += b'RESTAURANTE MIRAPRAIA\n'
    cmd += NO_BOLD
    cmd += b'CONFERENCIA DE CONTA\n'
    cmd += SEPARATOR
    
    cmd += LEFT
    cmd += f"Mesa: {table_id}\n".encode('cp850', errors='replace')
    cmd += f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n".encode('cp850', errors='replace')
    cmd += f"Garcom: {waiter_name}\n".encode('cp850', errors='replace')
    
    if guest_name and room_number:
        cmd += f"Hospede: {guest_name} | Quarto: {room_number}\n".encode('cp850', errors='replace')
    else:
        if guest_name:
            cmd += f"Hospede: {guest_name}\n".encode('cp850', errors='replace')
        if room_number:
            cmd += f"Quarto: {room_number}\n".encode('cp850', errors='replace')
        
    cmd += SEPARATOR
    
    cmd += b'ITEM                 QTD   VALOR\n'
    cmd += SEPARATOR
    
    for item in items:
        name = item['name'][:20] # Truncate name
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
    
    cmd += NO_BOLD + NORMAL
    cmd += CENTER
    cmd += b'\nNAO E DOCUMENTO FISCAL\n'
    cmd += b'\n\n\n'
    cmd += GS + b'V' + b'\x41' + b'\x03'
    
    return cmd

def print_bill(printer_config, table_id, items, subtotal, service_fee, total, waiter_name, guest_name=None, room_number=None):
    """
    Sends the bill to the specified printer.
    If printer_config is invalid/missing, defaults to Bar (192.168.69.60).
    """
    # Force Bar Printer IP for Bill Printing as requested
    if not printer_config:
        printer_config = {}
        
    # OVERRIDE IP/PORT to ensure it goes to the right place
    printer_config['ip'] = '192.168.69.60'
    printer_config['port'] = 9100
    printer_config['type'] = 'network'
         
    print(f"DEBUG: FORCE printing bill to {printer_config.get('ip')}:{printer_config.get('port')}")

    try:
        data = format_bill(table_id, items, subtotal, service_fee, total, waiter_name, guest_name, room_number)
        
        # Always use network send since we forced IP
        return send_to_printer(printer_config.get('ip'), printer_config.get('port', 9100), data)

    except Exception as e:
        print(f"Error printing bill: {e}")
        return False, str(e)

def format_cancellation_ticket(table_id, waiter_name, items, printer_name, justification=None):
    """
    Formats the cancellation ticket.
    """
    # ESC/POS commands
    ESC = b'\x1b'
    GS = b'\x1d'
    
    # Commands
    INIT = ESC + b'@'
    CENTER = ESC + b'a' + b'\x01'
    LEFT = ESC + b'a' + b'\x00'
    
    # Fonts
    NORMAL = GS + b'!' + b'\x00'
    BOLD = ESC + b'E' + b'\x01'
    NO_BOLD = ESC + b'E' + b'\x00'
    DOUBLE_HW = GS + b'!' + b'\x11' # Double Height & Width
    DOUBLE_H = GS + b'!' + b'\x10'  # Double Height
    
    # Separator
    SEPARATOR = b'--------------------------------\n'
    DOUBLE_SEPARATOR = b'================================\n'

    # Initialize
    cmd = INIT
    
    # --- HEADER ---
    cmd += CENTER
    cmd += DOUBLE_SEPARATOR
    
    # CANCELAMENTO (Highlight)
    cmd += BOLD + DOUBLE_HW
    cmd += b"*** CANCELAMENTO ***\n"
    cmd += NO_BOLD + NORMAL
    
    cmd += LEFT
    cmd += DOUBLE_SEPARATOR
    
    # Table
    cmd += BOLD + DOUBLE_H
    
    # Format table_id
    display_table_id = format_room_number_str(table_id)
    
    cmd += f"MESA: {display_table_id}\n".encode('cp850', errors='replace')
    cmd += NO_BOLD + NORMAL
    
    # Meta Info
    cmd += DOUBLE_SEPARATOR
    cmd += f"Solicitante: {waiter_name}\n".encode('cp850', errors='replace')
    cmd += f"Data:   {datetime.now().strftime('%d/%m/%Y %H:%M')}\n".encode('cp850', errors='replace')
    if justification:
        cmd += b'\n'
        cmd += b"MOTIVO:\n"
        cmd += f"{justification}\n".encode('cp850', errors='replace')
    cmd += SEPARATOR
    cmd += b'\n'
    
    # --- ITEMS ---
    for item in items:
        qty = item['qty']
        name = item['name']
        
        # Format: -QTY x NAME
        cmd += LEFT
        
        # Qty Line (Negative to emphasize removal)
        cmd += BOLD + DOUBLE_H
        try:
            qty_val = float(qty)
            qty_display = str(int(qty_val)) if qty_val.is_integer() else str(qty_val)
        except:
            qty_display = str(qty)

        cmd += f"-{qty_display} ".encode('cp850', errors='replace') 
        cmd += NO_BOLD + NORMAL 
        
        # 'x ' separator
        cmd += b'x '
        
        # Name (Bold)
        cmd += BOLD + NORMAL
        cmd += f"{name}\n".encode('cp850', errors='replace')
        cmd += NO_BOLD + NORMAL
        
        cmd += b'\n'

    # --- FOOTER ---
    cmd += SEPARATOR
    
    # Cut
    cmd += b'\n\n\n\n'
    cmd += GS + b'V' + b'\x41' + b'\x03'
    
    return cmd

def print_cancellation_items(table_id, waiter_name, cancelled_items, printers_config, products_db, justification=None):
    """
    Groups cancelled items by printer and sends cancellation tickets.
    """
    # Apply Frigobar Filter
    settings = load_printer_settings()
    if settings.get('frigobar_filter_enabled', True):
        filtered_items = []
        for item in cancelled_items:
            # Try to find product in products_db
            product = next((p for p in products_db if p['name'] == item['name']), None)
            category = product.get('category') if product else None
            
            if not category:
                category = item.get('category')
                
            if category != 'Frigobar':
                filtered_items.append(item)
        
        cancelled_items = filtered_items
        if not cancelled_items:
            print("Cancellation skipped: All items filtered (Frigobar).")
            return

    # Group by printer
    printer_groups = {}
    
    for item in cancelled_items:
        # Resolve printer
        product = next((p for p in products_db if p['name'] == item['name']), None)
        printer_id = product.get('printer_id') if product else None
        
        if not printer_id:
            # Fallback to default
            printer_id = printers_config[0]['id'] if printers_config else None
            
        if printer_id:
            if printer_id not in printer_groups:
                printer_groups[printer_id] = []
            printer_groups[printer_id].append(item)
            
    # Send to each printer
    for printer_id, items in printer_groups.items():
        printer = next((p for p in printers_config if p['id'] == printer_id), None)
        if printer:
            try:
                ticket_data = format_cancellation_ticket(table_id, waiter_name, items, printer['name'], justification)
                
                if printer['type'] == 'windows':
                    send_to_windows_printer(printer['windows_name'], ticket_data)
                else:
                    # Network
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        s.settimeout(5)
                        s.connect((printer['ip'], int(printer.get('port', 9100))))
                        s.sendall(ticket_data)
                        
                print(f"Cancellation ticket sent to {printer['name']}")
            except Exception as e:
                print(f"Error printing cancellation to {printer['name']}: {e}")

def format_fiscal_receipt(invoice_data, printer_width=32):
    """
    Formats the NFC-e content for thermal printing.
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
    SMALL = ESC + b'M' + b'\x01' # Small font if supported, or just normal
    
    # Separator
    SEPARATOR = b'--------------------------------\n'
    
    # Data extraction
    env = invoice_data.get('ambiente', 'homologacao')
    status = invoice_data.get('status')
    
    auth = invoice_data.get('autorizacao', {})
    chave = invoice_data.get('chave', auth.get('chave_acesso', ''))
    proto = auth.get('numero_protocolo', '')
    data_emi = invoice_data.get('data_emissao', '')
    
    # Initialize
    cmd = INIT
    
    # --- HEADER ---
    cmd += CENTER
    if env == 'homologacao':
        cmd += BOLD
        cmd += b'AMBIENTE DE HOMOLOGACAO\n'
        cmd += b'SEM VALOR FISCAL\n'
        cmd += NO_BOLD
        cmd += SEPARATOR
    
    cmd += BOLD
    cmd += b'RESTAURANTE MIRAPRAIA LTDA\n'
    cmd += NO_BOLD
    cmd += b'CNPJ: 28.952.732/0001-09\n'
    cmd += b'BEIRA MAR, S/N - TAMANDARE, PE\n'
    cmd += SEPARATOR
    
    cmd += BOLD
    cmd += b'NFC-e - Nota Fiscal de Consumidor Eletronica\n'
    cmd += NO_BOLD
    cmd += SEPARATOR
    
    # --- ITEMS ---
    cmd += LEFT
    cmd += b'ITEM CODIGO DESCRICAO\n'
    cmd += b'QTD UN VL UNIT(R$) ST VL ITEM(R$)\n'
    cmd += SEPARATOR
    
    # --- TOTALS ---
    cmd += RIGHT
    total_val = invoice_data.get('valor_total', 0.0)
    cmd += BOLD
    cmd += f"VALOR TOTAL R$ {total_val:.2f}\n".encode('cp850', errors='replace')
    cmd += NO_BOLD
    cmd += SEPARATOR
    
    # --- FOOTER ---
    cmd += CENTER
    cmd += b'Consulta via Leitor de QR Code\n'
    cmd += b'\n'
    
    cmd += LEFT
    cmd += f"Chave de Acesso:\n{chave}\n".encode('cp850', errors='replace')
    cmd += f"Protocolo: {proto}\n".encode('cp850', errors='replace')
    cmd += f"Data: {data_emi}\n".encode('cp850', errors='replace')
    
    cmd += b'\n'
    cmd += CENTER
    cmd += b'Consulte pela Chave de Acesso em:\n'
    cmd += b'http://nfce.sefaz.pe.gov.br/\n'
    
    # Cut
    cmd += b'\n\n\n\n'
    cmd += GS + b'V' + b'\x41' + b'\x03'
    
    return cmd

def print_fiscal_receipt(printer_config, invoice_data):
    """
    Sends the fiscal receipt to the specified printer.
    """
    try:
        if not printer_config:
            printer_config = {}

        if not printer_config.get('ip') and printer_config.get('type') != 'windows':
            settings = load_printer_settings()
            fiscal_printer_id = settings.get('fiscal_printer_id')
            if fiscal_printer_id:
                from printer_manager import load_printers
                printers = load_printers()
                resolved = next((p for p in printers if str(p.get('id')) == str(fiscal_printer_id)), None)
                if resolved:
                    printer_config = resolved

        data = format_fiscal_receipt(invoice_data)
        
        if printer_config.get('type') == 'windows':
            windows_name = printer_config.get('windows_name') or printer_config.get('name')
            return send_to_windows_printer(windows_name, data)
        return send_to_printer(printer_config.get('ip'), printer_config.get('port', 9100), data)
        
    except Exception as e:
        print(f"Error printing fiscal receipt: {e}")
        return False, str(e)
