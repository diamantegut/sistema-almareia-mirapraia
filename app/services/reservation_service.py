
import pandas as pd
import os
from datetime import datetime
import re
from app.services.system_config_manager import (
    MANUAL_ALLOCATIONS_FILE, GUEST_DETAILS_FILE, 
    MANUAL_RESERVATIONS_FILE, RESERVATIONS_DIR
)

class ReservationService:
    RESERVATIONS_DIR = RESERVATIONS_DIR
    RESERVATIONS_FILE = os.path.join(RESERVATIONS_DIR, "minhas_reservas.xlsx")
    MANUAL_RESERVATIONS_FILE = MANUAL_RESERVATIONS_FILE
    RESERVATION_STATUS_OVERRIDES_FILE = os.path.join(RESERVATIONS_DIR, "reservation_status_overrides.json")
    
    # Room Capacities (Estimated)
    ROOM_CAPACITIES = {
        "01": 2, "02": 2, "03": 2, # Areia
        "11": 4, # Mar Familia
        "12": 3, "14": 3, "15": 3, "16": 3, "17": 3, "21": 3, "22": 3, "23": 3, "24": 3, "25": 3, "26": 3, # Mar
        "31": 2, "35": 2, # Alma Banheira
        "32": 2, "34": 2, # Alma
        "33": 2 # Master Diamante
    }

    def get_reservation_status_overrides(self):
        import json
        if not os.path.exists(self.RESERVATION_STATUS_OVERRIDES_FILE):
            return {}
        try:
            with open(self.RESERVATION_STATUS_OVERRIDES_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}

    def update_reservation_status(self, reservation_id, new_status):
        import json
        overrides = self.get_reservation_status_overrides()
        overrides[str(reservation_id)] = new_status
        
        with open(self.RESERVATION_STATUS_OVERRIDES_FILE, 'w') as f:
            json.dump(overrides, f, indent=4)
            
    def get_manual_reservations_data(self):
        import json
        if not os.path.exists(self.MANUAL_RESERVATIONS_FILE):
            return []
        try:
            with open(self.MANUAL_RESERVATIONS_FILE, 'r') as f:
                data = json.load(f)
                if not isinstance(data, list): return []
                
                # Apply Status Overrides
                overrides = self.get_reservation_status_overrides()
                for item in data:
                    rid = str(item.get('id'))
                    if rid in overrides:
                        item['status'] = overrides[rid]
                        
                return data
        except:
            return []

    def create_manual_reservation(self, data):
        import json
        import uuid
        
        reservations = self.get_manual_reservations_data()
        
        new_res = {
            'id': str(uuid.uuid4()),
            'guest_name': data.get('guest_name'),
            'checkin': data.get('checkin'), # DD/MM/YYYY
            'checkout': data.get('checkout'), # DD/MM/YYYY
            'category': data.get('category', 'Manual'),
            'status': data.get('status', 'Pendente'),
            'channel': data.get('channel', 'Direto'),
            'amount': data.get('amount', '0.00'),
            'paid_amount': data.get('paid_amount', '0.00'),
            'to_receive': data.get('to_receive', '0.00'),
            'created_at': datetime.now().strftime('%d/%m/%Y %H:%M')
        }
        
        reservations.append(new_res)
        
        dir_name = os.path.dirname(self.MANUAL_RESERVATIONS_FILE)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        
        with open(self.MANUAL_RESERVATIONS_FILE, 'w') as f:
            json.dump(reservations, f, indent=2)
            
        return new_res

    def _parse_excel_file(self, file_path):
        parsed_items = []
        try:
            df = pd.read_excel(file_path)
            
            # Determine format based on columns
            is_standard = 'Checkin/out' in df.columns and 'Responsável' in df.columns
            
            if is_standard:
                for index, row in df.iterrows():
                    # Parse Checkin/out "04/02/2026 - 06/02/2026"
                    checkin_out = str(row.get('Checkin/out', ''))
                    checkin = None
                    checkout = None
                    
                    if ' - ' in checkin_out:
                        parts = checkin_out.split(' - ')
                        if len(parts) == 2:
                            checkin = parts[0].strip()
                            checkout = parts[1].strip()
                    
                    # Basic cleaning
                    guest_name = str(row.get('Responsável', 'Unknown'))
                    category = str(row.get('Categoria', 'Unknown'))
                    status = str(row.get('Status do pagamento', 'Unknown'))
                    channel = str(row.get('Canais', 'Unknown'))
                    res_id = str(row.get('Id', ''))
                    
                    amount_str = str(row.get('Valor', ''))
                    paid_amount_str = str(row.get('Valor pago', ''))
                    to_receive_str = str(row.get('Valor a receber', ''))

                    def parse_br_money(val_str):
                        try:
                            clean = str(val_str).replace('R$', '').replace('.', '').replace(',', '.').strip()
                            if not clean: return 0.0
                            return float(clean)
                        except:
                            return 0.0

                    parsed_items.append({
                        'id': res_id,
                        'guest_name': guest_name,
                        'checkin': checkin,
                        'checkout': checkout,
                        'category': category,
                        'status': status,
                        'channel': channel,
                        'amount': amount_str,
                        'paid_amount': paid_amount_str,
                        'to_receive': to_receive_str,
                        'amount_val': parse_br_money(amount_str),
                        'paid_amount_val': parse_br_money(paid_amount_str),
                        'to_receive_val': parse_br_money(to_receive_str),
                        'source_file': os.path.basename(file_path)
                    })
            else:
                # Import format (no headers or specific column indices)
                df_no_header = pd.read_excel(file_path, header=None)
                if df_no_header.shape[1] >= 10:
                    start_row = 0
                    if str(df_no_header.iloc[0, 2]).lower() in ['hóspede', 'nome', 'guest']:
                        start_row = 1
                        
                    for index, row in df_no_header.iloc[start_row:].iterrows():
                        try:
                            # Col C (2): Name
                            guest_name = str(row[2]).strip()
                            if not guest_name or guest_name.lower() == 'nan': continue
                            
                            # Col D (3): Dates
                            dates_raw = str(row[3]).strip()
                            checkin, checkout = None, None
                            if ' - ' in dates_raw:
                                parts = dates_raw.split(' - ')
                                if len(parts) == 2:
                                    checkin = parts[0].strip()
                                    checkout = parts[1].strip()
                            
                            # Col E (4): Category
                            category = str(row[4]).strip()
                            
                            # Col G (6): Channel
                            channel = str(row[6]).strip()
                            
                            # Col H (7): Total
                            amount_val = row[7]
                            
                            # Col I (8): Paid
                            paid_val = row[8]
                            
                            # Col J (9): To Receive
                            to_receive_val = row[9]
                            
                            # Generate ID
                            import hashlib
                            res_id_raw = f"{guest_name}_{dates_raw}_{category}"
                            res_id = hashlib.md5(res_id_raw.encode()).hexdigest()[:8]
                            
                            def format_money(val):
                                try:
                                    if isinstance(val, (int, float)): return f"{val:.2f}"
                                    return str(val)
                                except: return "0.00"
                                
                            def parse_money(val):
                                try:
                                    if isinstance(val, (int, float)): return float(val)
                                    s = str(val).replace('R$', '').replace('.', '').replace(',', '.').strip()
                                    return float(s) if s else 0.0
                                except: return 0.0

                            parsed_items.append({
                                'id': res_id,
                                'guest_name': guest_name,
                                'checkin': checkin,
                                'checkout': checkout,
                                'category': category,
                                'status': 'Importada',
                                'channel': channel,
                                'amount': format_money(amount_val),
                                'paid_amount': format_money(paid_val),
                                'to_receive': format_money(to_receive_val),
                                'amount_val': parse_money(amount_val),
                                'paid_amount_val': parse_money(paid_val),
                                'to_receive_val': parse_money(to_receive_val),
                                'source_file': os.path.basename(file_path)
                            })
                        except Exception:
                            continue
        except Exception as e:
            print(f"Error reading reservations Excel {file_path}: {e}")
        return parsed_items

    UNALLOCATED_RESERVATIONS_FILE = os.path.join(RESERVATIONS_DIR, "unallocated_reservations.json")

    def _get_diff(self, old, new):
        """
        Compares two reservation dictionaries and returns a list of changed fields.
        """
        changes = []
        fields = [
            ('guest_name', 'Nome do Hóspede'),
            ('checkin', 'Check-in'),
            ('checkout', 'Check-out'),
            ('category', 'Categoria'),
            ('status', 'Status'),
            ('amount', 'Valor Total'),
            ('paid_amount', 'Valor Pago'),
            ('to_receive', 'A Receber')
        ]
        
        for field, label in fields:
            old_val = str(old.get(field, '')).strip()
            new_val = str(new.get(field, '')).strip()
            
            # Special handling for floats/money to avoid "100.0" vs "100.00" false positives
            if field in ['amount', 'paid_amount', 'to_receive']:
                try:
                    v1 = float(old_val.replace('R$', '').replace('.', '').replace(',', '.')) if old_val else 0.0
                    v2 = float(new_val.replace('R$', '').replace('.', '').replace(',', '.')) if new_val else 0.0
                    if abs(v1 - v2) > 0.01:
                        changes.append(f"{label}: '{old_val}' -> '{new_val}'")
                except:
                    if old_val != new_val:
                        changes.append(f"{label}: '{old_val}' -> '{new_val}'")
            else:
                if old_val != new_val:
                    changes.append(f"{label}: '{old_val}' -> '{new_val}'")
                    
        return changes

    def save_unallocated_reservations(self, unallocated_items):
        """
        Saves unallocated reservations to a JSON file.
        """
        import json
        if not unallocated_items:
            return
            
        current_data = self.get_unallocated_reservations()
        
        # Append new items
        current_data.extend(unallocated_items)
        
        with open(self.UNALLOCATED_RESERVATIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(current_data, f, indent=4, ensure_ascii=False)

    def get_unallocated_reservations(self, filters=None):
        """
        Retrieves unallocated reservations, optionally filtered.
        filters: dict with keys 'date', 'start_date', 'end_date', 'category', 'guest_name'
        """
        import json
        if not os.path.exists(self.UNALLOCATED_RESERVATIONS_FILE):
            return []
            
        try:
            with open(self.UNALLOCATED_RESERVATIONS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Add index to item for deletion reference
            for idx, item in enumerate(data):
                item['original_index'] = idx

            if not filters:
                return data
                
            filtered = []
            for item in data:
                match = True
                
                # Date Range Overlap Filter
                if filters.get('start_date') or filters.get('end_date'):
                    try:
                        r_cin = datetime.strptime(item.get('checkin'), '%d/%m/%Y')
                        r_cout = datetime.strptime(item.get('checkout'), '%d/%m/%Y')
                        
                        f_start = datetime.min
                        f_end = datetime.max
                        
                        if filters.get('start_date'):
                            f_start = datetime.strptime(filters['start_date'], '%Y-%m-%d')
                        if filters.get('end_date'):
                            f_end = datetime.strptime(filters['end_date'], '%Y-%m-%d')
                            
                        # Overlap: (StartA <= EndB) and (EndA >= StartB)
                        if not (r_cin <= f_end and r_cout >= f_start):
                            match = False
                    except: pass
                
                # Single Date Point Filter (Legacy)
                elif filters.get('date'):
                    # Check if date falls within reservation range
                    try:
                        f_date = datetime.strptime(filters['date'], '%Y-%m-%d')
                        r_cin = datetime.strptime(item.get('checkin'), '%d/%m/%Y')
                        r_cout = datetime.strptime(item.get('checkout'), '%d/%m/%Y')
                        if not (r_cin <= f_date <= r_cout):
                            match = False
                    except: pass
                    
                if filters.get('category') and filters['category'].lower() not in str(item.get('category')).lower():
                    match = False
                    
                if filters.get('guest_name') and filters['guest_name'].lower() not in str(item.get('guest_name')).lower():
                    match = False
                    
                if match:
                    filtered.append(item)
            return filtered
        except:
            return []

    def delete_unallocated_reservation(self, item_index):
        """
        Deletes an unallocated reservation by its index in the list.
        Returns True if successful.
        """
        import json
        if not os.path.exists(self.UNALLOCATED_RESERVATIONS_FILE):
            return False
            
        try:
            with open(self.UNALLOCATED_RESERVATIONS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if 0 <= item_index < len(data):
                data.pop(item_index)
                with open(self.UNALLOCATED_RESERVATIONS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                return True
            return False
        except Exception as e:
            print(f"Error deleting unallocated reservation: {e}")
            return False

    def get_conflict_details(self, category, checkin_str, checkout_str):
        """
        Checks availability and returns detailed conflict information if unavailable.
        Returns: (is_available, conflict_details_dict)
        """
        try:
            cin = datetime.strptime(checkin_str, '%d/%m/%Y')
            cout = datetime.strptime(checkout_str, '%d/%m/%Y')
        except ValueError:
            return False, {'type': 'invalid_dates', 'message': 'Datas inválidas'}

        from app.services.data_service import load_room_occupancy
        occupancy = load_room_occupancy()
        
        # Expand range slightly to cover edges
        start_date = datetime(cin.year, cin.month, cin.day)
        num_days = max(1, (cout - cin).days + 1)
        range_end = start_date + pd.Timedelta(days=num_days - 1)
        
        # Build grid with existing occupancy
        grid = self.get_occupancy_grid(occupancy, start_date, num_days)
        
        # Allocate existing reservations
        reservations = self.get_february_reservations()
        self.allocate_reservations(grid, reservations, start_date, num_days)
        
        # Determine candidate rooms
        mapping = self.get_room_mapping()
        norm_mapping = {k.lower().strip(): v for k, v in mapping.items()}
        cat_norm = str(category).lower().strip()
        
        candidates = []
        if cat_norm in norm_mapping:
            candidates = norm_mapping[cat_norm]
        else:
            for k, v in norm_mapping.items():
                if k in cat_norm or cat_norm in k:
                    candidates = v
                    break 
        
        if not candidates:
            return False, {'type': 'invalid_category', 'message': f'Categoria desconhecida: {category}'}

        # Calculate required slots for the NEW reservation
        required_slots = []
        
        curr = cin
        while curr <= cout:
            if start_date <= curr <= range_end:
                day_offset = (curr - start_date).days
                day_idx = day_offset * 2
                
                # Logic must match allocate_reservations
                if curr == cin:
                    required_slots.append(day_idx + 1) # PM
                elif curr == cout:
                    required_slots.append(day_idx) # AM
                else:
                    required_slots.append(day_idx)
                    required_slots.append(day_idx + 1)
            
            curr = datetime(curr.year, curr.month, curr.day) + pd.Timedelta(days=1)
            
        required_slots = [s for s in required_slots if 0 <= s < (num_days * 2)]
        
        if not required_slots:
             return True, None

        # Check availability and collect conflicts
        rooms_blocked_reasons = {} 
        
        for room in candidates:
            is_free = True
            blockers = []
            
            # If room not in grid, it's free
            if room not in grid: 
                return True, None
            
            room_slots = grid[room]
            
            for slot in required_slots:
                if slot in room_slots:
                    is_free = False
                    blocker_info = room_slots[slot]
                    
                    # Deduplicate blockers for this room
                    is_known = False
                    for b in blockers:
                        if b.get('id') == blocker_info.get('id') and b.get('guest') == blocker_info.get('guest'):
                            is_known = True
                            break
                    if not is_known:
                        blockers.append(blocker_info)
            
            if is_free:
                return True, None
            else:
                rooms_blocked_reasons[room] = blockers
        
        # Construct detailed report
        conflict_summary = []
        detailed_blockers = []
        
        for room, blockers in rooms_blocked_reasons.items():
            blocker_descs = []
            for b in blockers:
                desc = f"{b.get('guest', 'Unknown')} ({b.get('checkin')} - {b.get('checkout')})"
                blocker_descs.append(desc)
                
                detailed_blockers.append({
                    'room': room,
                    'guest': b.get('guest'),
                    'checkin': b.get('checkin'),
                    'checkout': b.get('checkout'),
                    'id': b.get('id')
                })
                
            conflict_summary.append(f"Quarto {room}: {', '.join(blocker_descs)}")
            
        return False, {
            'type': 'no_availability',
            'message': 'Sem disponibilidade na categoria',
            'details': conflict_summary,
            'blockers': detailed_blockers
        }

    def preview_import(self, temp_file_path):
        """
        Parses the temp file and compares with existing reservations to generate a preview report.
        Includes duplicate detection, change tracking, and conflict detection.
        """
        # 1. Parse new items
        new_items = self._parse_excel_file(temp_file_path)
        if not new_items:
            return {'success': False, 'error': 'Nenhuma reserva válida encontrada ou formato incorreto.'}
            
        # 2. Get existing state
        current_reservations = self.get_february_reservations()
        
        # 3. Compare & Detect
        report = {
            'total_found': len(new_items),
            'new_entries': [],
            'updates': [],
            'conflicts': [],
            'unchanged': []
        }
        
        # Index existing
        existing_map_id = {r['id']: r for r in current_reservations if r.get('id')}
        existing_map_key = {}
        for r in current_reservations:
            name = str(r.get('guest_name', '')).lower().strip()
            cin = str(r.get('checkin', '')).strip()
            cout = str(r.get('checkout', '')).strip()
            if name and cin and cout:
                existing_map_key[f"{name}|{cin}|{cout}"] = r

        # Prepare for conflict check (Load logic once if possible, but for now we rely on has_availability_for_category)
        # Note: calling has_availability_for_category in a loop is slow. 
        # But for valid conflict detection involving ALL reservations, we need the grid.
        
        for item in new_items:
            try:
                match = None
                is_update = False
                changes = []
                
                # Match Logic
                if item.get('id') in existing_map_id:
                    match = existing_map_id[item['id']]
                else:
                    key = f"{str(item.get('guest_name','')).lower().strip()}|{str(item.get('checkin','')).strip()}|{str(item.get('checkout','')).strip()}"
                    if key in existing_map_key:
                        match = existing_map_key[key]
                
                # Update vs New Logic
                if match:
                    item['original_id'] = match.get('id')
                    changes = self._get_diff(match, item)
                    if changes:
                        item['changes'] = changes
                        report['updates'].append(item)
                        is_update = True
                    else:
                        report['unchanged'].append(item)
                        continue # No need to check conflict for unchanged
                else:
                    report['new_entries'].append(item)
                
                # Conflict Detection Logic (for New and Changed Updates)
                # Only check if relevant fields (dates/category) changed or if it's new
                should_check_conflict = True
                if is_update:
                    # Only check if dates or category changed
                    date_cat_changed = any(c.startswith(('Check-in', 'Check-out', 'Categoria')) for c in changes)
                    if not date_cat_changed:
                        should_check_conflict = False
                
                if should_check_conflict:
                    cat = item.get('category', '')
                    cin = item.get('checkin', '')
                    cout = item.get('checkout', '')
                    
                    is_available, conflict_details = self.get_conflict_details(cat, cin, cout)
                    
                    if not is_available:
                        conflict_info = {
                            'item': item,
                            'reason': 'Sem disponibilidade na categoria/período',
                            'details': conflict_details,
                            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                            'status': 'conflict'
                        }
                        report['conflicts'].append(conflict_info)
                        # Mark item as having conflict
                        item['has_conflict'] = True
                        item['conflict_reason'] = 'Sem disponibilidade'
                        item['conflict_details'] = conflict_details
            except Exception as e:
                item['has_conflict'] = True
                item['conflict_reason'] = f"Erro processando item: {str(e)}"
                report['conflicts'].append({
                    'item': item,
                    'reason': str(e),
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'status': 'error'
                })
                # Ensure it is tracked in lists for processing
                if item not in report['new_entries'] and item not in report['updates'] and item not in report['unchanged']:
                     report['new_entries'].append(item)

        return {'success': True, 'report': report}

    def process_import_confirm(self, temp_file_path, token):
        """
        Processes the confirmed import:
        1. Filters out conflicts
        2. Saves valid reservations (New + Updates + Unchanged) to a new Excel file
        3. Saves conflicts to unallocated_reservations.json
        """
        # Reuse preview logic
        preview_result = self.preview_import(temp_file_path)
        if not preview_result['success']:
            return preview_result
            
        report = preview_result['report']
        
        valid_items = []
        conflict_items = []
        
        # Helper to process items
        def process_list(items, is_update=False):
            for item in items:
                if item.get('has_conflict'):
                    # Ensure conflict info is robust
                    if 'conflict_reason' not in item:
                        item['conflict_reason'] = 'Conflito detectado na confirmação'
                    conflict_items.append(item)
                else:
                    # If it's an update, ensure we use the ORIGINAL ID to guarantee overwrite
                    if is_update and item.get('original_id'):
                        item['id'] = item['original_id']
                    valid_items.append(item)

        process_list(report['new_entries'])
        process_list(report['updates'], is_update=True)
        # Unchanged items are valid and should be kept in the new file source
        process_list(report['unchanged'])
        
        # Save Valid to Excel
        if valid_items:
            try:
                # Prepare DataFrame with standard columns
                df_data = []
                for item in valid_items:
                    df_data.append({
                        'Id': item.get('id'),
                        'Responsável': item.get('guest_name'),
                        'Checkin/out': f"{item.get('checkin')} - {item.get('checkout')}",
                        'Categoria': item.get('category'),
                        'Status do pagamento': item.get('status'),
                        'Canais': item.get('channel'),
                        'Valor': item.get('amount'),
                        'Valor pago': item.get('paid_amount'),
                        'Valor a receber': item.get('to_receive')
                    })
                
                df = pd.DataFrame(df_data)
                final_name = f"imported_{token}"
                # Ensure extension
                if not final_name.endswith('.xlsx'):
                    final_name += '.xlsx'
                    
                final_path = os.path.join(self.RESERVATIONS_DIR, final_name)
                df.to_excel(final_path, index=False)
            except Exception as e:
                return {'success': False, 'error': f"Erro ao salvar arquivo Excel: {str(e)}"}
            
        # Save Conflicts
        if conflict_items:
            try:
                self.save_unallocated_reservations(conflict_items)
            except Exception as e:
                # If we fail to save conflicts, we should warn? 
                # Ideally rollback, but file is already written.
                return {'success': True, 'warning': f"Importado com sucesso, mas erro ao salvar conflitos: {str(e)}"}
            
        return {
            'success': True, 
            'message': 'Importação processada com sucesso.',
            'summary': {
                'imported': len(valid_items),
                'conflicts': len(conflict_items)
            }
        }

    def get_february_reservations(self):
        """
        Reads all Excel files in the directory and returns a combined list of reservation dictionaries.
        Also includes manual reservations from JSON.
        """
        all_reservations = []
        
        # 1. Load Manual Reservations (JSON)
        manual_res = self.get_manual_reservations_data()
        for res in manual_res:
            try:
                def parse_val(v):
                    try: return float(str(v).replace('R$', '').replace('.', '').replace(',', '.'))
                    except: return 0.0
                
                res['amount_val'] = parse_val(res.get('amount'))
                res['paid_amount_val'] = parse_val(res.get('paid_amount'))
                res['to_receive_val'] = parse_val(res.get('to_receive'))
                all_reservations.append(res)
            except: continue

        # 2. Load Excel Reservations
        if os.path.exists(self.RESERVATIONS_DIR):
            import glob
            
            # Get all xlsx files
            files = glob.glob(os.path.join(self.RESERVATIONS_DIR, "*.xlsx"))
            # Exclude temporary files (~$)
            files = [f for f in files if not os.path.basename(f).startswith("~$")]
            
            # Sort files by modification time (oldest first) to ensure updates overwrite older data
            files.sort(key=os.path.getmtime)
            
            for file_path in files:
                parsed = self._parse_excel_file(file_path)
                all_reservations.extend(parsed)
        
        # Deduplicate by ID (Keep latest version)
        unique_map = {}
        for res in all_reservations:
            if res.get('id'):
                unique_map[res['id']] = res
        all_reservations = list(unique_map.values())
        
        # 3. Apply Overrides to ALL Reservations
        overrides = self.get_reservation_status_overrides()
        manual_allocs = self.get_manual_overrides()

        # Deduplicate Logic
        # Priority: Most recent file (already sorted by mtime)
        # Key: ID (if present) OR (Guest Name + Checkin + Checkout)
        
        unique_reservations = {}
        
        for res in all_reservations:
            # Apply Status Override (Early)
            rid = str(res.get('id'))
            if rid in overrides:
                res['status'] = overrides[rid]

            # 1. Try by ID first
            if rid and rid != 'nan' and rid != 'None':
                unique_reservations[rid] = res
            else:
                # 2. Try by Composite Key (Name + Dates)
                # Normalize keys
                name = str(res.get('guest_name', '')).lower().strip()
                cin = str(res.get('checkin', '')).strip()
                cout = str(res.get('checkout', '')).strip()
                
                if name and cin and cout:
                    # Check if we already have a reservation with this key (even if it has a different ID or generated ID)
                    found_id = None
                    for existing_id, existing_res in unique_reservations.items():
                        e_name = str(existing_res.get('guest_name', '')).lower().strip()
                        e_cin = str(existing_res.get('checkin', '')).strip()
                        e_cout = str(existing_res.get('checkout', '')).strip()
                        if e_name == name and e_cin == cin and e_cout == cout:
                            found_id = existing_id
                            break
                    
                    if found_id:
                        # Update existing
                        unique_reservations[found_id] = res
                        # Ensure ID consistency
                        res['id'] = found_id
                    else:
                        # New entry
                        if not rid:
                            import uuid
                            rid = str(uuid.uuid4())[:8]
                            res['id'] = rid
                        unique_reservations[rid] = res
        
        final_list = list(unique_reservations.values())
        
        # Apply Manual Allocations (Financial, Dates, Avg Daily) to FINAL list
        for res in final_list:
            rid = str(res.get('id'))
            self.merge_overrides_into_reservation(rid, res, overrides_cache=manual_allocs)
            
        return final_list

    def search_reservations(self, query):
        """
        Searches reservations by guest name or CPF/Document.
        Returns a list of matching reservation objects.
        """
        if not query:
            return []
            
        import unicodedata
        def normalize(s):
            return ''.join(c for c in unicodedata.normalize('NFD', str(s)) if unicodedata.category(c) != 'Mn').lower()

        query_norm = normalize(query).strip()
        # Remove common separators for CPF check
        query_clean = re.sub(r'[.\-]', '', query_norm)
        is_numeric_search = query_clean.isdigit() and len(query_clean) >= 3
        
        all_reservations = self.get_february_reservations()
        all_details = self.get_guest_details_data()
        
        matching_ids = set()
        
        # 1. Search in Guest Details (Deep Search: CPF, Doc, Name in details)
        for res_id, details in all_details.items():
            match = False
            
            # Personal Info
            p_info = details.get('personal_info', {})
            # Fiscal Info
            f_info = details.get('fiscal_info', {})
            
            # Name Check (in details)
            d_name = normalize(p_info.get('name', '') or '')
            if query_norm in d_name:
                match = True
                
            # Doc/CPF Check
            if is_numeric_search:
                doc_id = re.sub(r'\D', '', str(p_info.get('doc_id', '')))
                cpf = re.sub(r'\D', '', str(f_info.get('cpf', '')))
                cnpj = re.sub(r'\D', '', str(f_info.get('cnpj', '')))
                
                if query_clean in doc_id or query_clean in cpf or query_clean in cnpj:
                    match = True
            
            if match:
                matching_ids.add(str(res_id))
                
        # 2. Filter Reservations
        results = []
        seen_ids = set()
        
        for res in all_reservations:
            r_id = str(res.get('id', ''))
            if r_id in seen_ids:
                continue
            
            # Check if ID matches from details search
            if r_id in matching_ids:
                results.append(res)
                seen_ids.add(r_id)
                continue
                
            # Check basic info (Name in reservation list)
            r_name = normalize(res.get('guest_name', '') or '')
            
            if query_norm in r_name:
                results.append(res)
                seen_ids.add(r_id)
                
        # 3. Sort by Check-in Date (Most recent first)
        def parse_date(d_str):
            try:
                return datetime.strptime(str(d_str), '%d/%m/%Y')
            except:
                return datetime.min
                
        results.sort(key=lambda x: parse_date(x.get('checkin')), reverse=True)
        
        return results

    def get_room_mapping(self):
        return {
            "Suíte Areia": ["01", "02", "03"],
            "Suíte Mar Família": ["11"],
            "Suíte Mar": ["12", "14", "15", "16", "17", "21", "22", "23", "24", "25", "26"],
            "Suíte Alma c/ Banheira": ["31", "35"],
            "Suíte Alma": ["32", "34"],
            "Suíte Master Diamante": ["33"]
        }

    MANUAL_ALLOCATIONS_FILE = MANUAL_ALLOCATIONS_FILE
    GUEST_DETAILS_FILE = GUEST_DETAILS_FILE

    def has_availability_for_category(self, category, checkin_str, checkout_str):
        try:
            cin = datetime.strptime(checkin_str, '%d/%m/%Y')
            cout = datetime.strptime(checkout_str, '%d/%m/%Y')
        except ValueError:
            return False
        from app.services.data_service import load_room_occupancy
        occupancy = load_room_occupancy()
        start_date = datetime(cin.year, cin.month, cin.day)
        num_days = max(1, (cout - cin).days + 1)
        grid = self.get_occupancy_grid(occupancy, start_date, num_days)
        reservations = self.get_february_reservations()
        dummy = {
            'id': '__new__',
            'guest_name': 'Novo',
            'checkin': checkin_str,
            'checkout': checkout_str,
            'category': category,
            'status': 'Pendente',
            'channel': 'Direto',
            'amount': '0',
            'paid_amount': '0',
            'to_receive': '0'
        }
        reservations2 = reservations + [dummy]
        self.allocate_reservations(grid, reservations2, start_date, num_days)
        for r in reservations2:
            if r.get('id') == '__new__':
                return bool(r.get('allocated'))
        return False

    def available_categories_for_period(self, checkin_str, checkout_str, exclude_category=None):
        mapping = self.get_room_mapping()
        result = []
        for cat in mapping.keys():
            if exclude_category and str(cat) == str(exclude_category):
                continue
            if self.has_availability_for_category(cat, checkin_str, checkout_str):
                result.append(cat)
        return result

    def get_guest_details_data(self):
        import json
        if not os.path.exists(self.GUEST_DETAILS_FILE):
            return {}
        try:
            with open(self.GUEST_DETAILS_FILE, 'r') as f:
                data = json.load(f)
                if isinstance(data, dict): return data
                return {}
        except:
            return {}

    def save_guest_details_data(self, data):
        import json
        os.makedirs(os.path.dirname(self.GUEST_DETAILS_FILE), exist_ok=True)
        with open(self.GUEST_DETAILS_FILE, 'w') as f:
            json.dump(data, f, indent=2)

    def get_guest_details(self, reservation_id):
        all_details = self.get_guest_details_data()
        details = all_details.get(str(reservation_id), {})
        
        # Merge with basic reservation info if needed?
        # For now just return the stored extended details
        return details

    def update_guest_details(self, reservation_id, info):
        all_details = self.get_guest_details_data()
        
        current = all_details.get(str(reservation_id), {})
        
        # Deep merge or replace? Replace sections seems safer as per frontend sending full objects
        if 'personal_info' in info:
            current['personal_info'] = info['personal_info']
        if 'fiscal_info' in info:
            current['fiscal_info'] = info['fiscal_info']
        if 'operational_info' in info:
            current['operational_info'] = info['operational_info']
            
        current['updated_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
        
        all_details[str(reservation_id)] = current
        self.save_guest_details_data(all_details)
        return current

    def get_reservation_by_id(self, reservation_id):
        reservations = self.get_february_reservations()
        for res in reservations:
            if str(res.get('id')) == str(reservation_id):
                return res
        return None

    def get_manual_overrides(self):
        import json
        if not os.path.exists(self.MANUAL_ALLOCATIONS_FILE):
            return {}
        try:
            with open(self.MANUAL_ALLOCATIONS_FILE, 'r') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                # Se não for dicionário (ex: lista vazia []), retorna dict vazio
                return {}
        except:
            return {}

    def save_manual_allocation(self, reservation_id, room_number=None, price_adjustment=None, checkin=None, checkout=None, occupancy_data=None):
        import json
        
        # Perform Collision Check if we have room and dates
        # If room_number is not provided, we need to know the current room to check collision for date change.
        # But if room_number is None, we might be just updating dates and relying on auto-allocation or existing manual room.
        
        # To be safe, let's load current state
        allocations = self.get_manual_overrides()
        current_alloc = allocations.get(str(reservation_id), {})
        if isinstance(current_alloc, str): current_alloc = {'room': current_alloc}
        
        target_room = room_number if room_number else current_alloc.get('room')
        target_checkin = checkin if checkin else current_alloc.get('checkin')
        target_checkout = checkout if checkout else current_alloc.get('checkout')
        
        # We can only check collision if we have room AND dates. 
        # If we don't have a room (e.g. auto-allocated), we can't easily check collision without full allocation logic.
        # However, if we are setting a MANUAL room or we already have one, we MUST check.
        
        if target_room and target_checkin and target_checkout:
             self.check_collision(reservation_id, target_room, target_checkin, target_checkout, occupancy_data)

        # Reload allocations in case check_collision took time (unlikely to change, but good practice)
        allocations = self.get_manual_overrides()
        entry = allocations.get(str(reservation_id), {})
        if isinstance(entry, str): 
            entry = {'room': entry}
            
        # Capture previous state for financial calc BEFORE updating with new values
        prev_entry_checkin = entry.get('checkin')
        prev_entry_checkout = entry.get('checkout')
            
        if room_number:
            entry['room'] = str(room_number)
        if price_adjustment:
            entry['price_adjustment'] = price_adjustment
        if checkin:
            entry['checkin'] = checkin
        if checkout:
            entry['checkout'] = checkout
        
        # If a price_adjustment is provided or dates changed, compute and persist financial overrides
        try:
            res = self.get_reservation_by_id(reservation_id) or {}
            
            # Helper to parse money safely handling BRL and US formats
            def _parse_money(v):
                try:
                    if v is None: return 0.0
                    if isinstance(v, (int, float)): return float(v)
                    s = str(v).strip().replace('R$', '').replace(' ', '')
                    if ',' in s:
                        # 1.200,50 -> 1200.50
                        s = s.replace('.', '').replace(',', '.')
                    return float(s)
                except:
                    return 0.0

            current_amount = _parse_money(res.get('amount_val', res.get('amount')))
            paid_amount = _parse_money(res.get('paid_amount_val', res.get('paid_amount')))
            
            # Dates
            from datetime import datetime as _dt
            cin_str = res.get('checkin')
            cout_str = res.get('checkout')
            
            # Apply previous manual overrides if present for baseline
            try:
                prev_cin = prev_entry_checkin or cin_str
                prev_cout = prev_entry_checkout or cout_str
                d_in = _dt.strptime(prev_cin, '%d/%m/%Y')
                d_out = _dt.strptime(prev_cout, '%d/%m/%Y')
                old_days = max(1, (d_out - d_in).days)
            except:
                old_days = 1
                
            # New dates (if provided)
            try:
                n_in_str = checkin or entry.get('checkin') or cin_str
                n_out_str = checkout or entry.get('checkout') or cout_str
                nd_in = _dt.strptime(n_in_str, '%d/%m/%Y')
                nd_out = _dt.strptime(n_out_str, '%d/%m/%Y')
                new_days = max(1, (nd_out - nd_in).days)
            except:
                new_days = old_days
                
            # Default avg
            avg_daily = current_amount / old_days if old_days > 0 else 0.0
            
            # Compute new total by rule
            new_total = None
            if price_adjustment:
                try:
                    ptype = str(price_adjustment.get('type', '')).lower()
                except:
                    ptype = ''
                
                if ptype in ('manual', 'manual_total'):
                    new_total = _parse_money(price_adjustment.get('amount'))
                elif ptype in ('extra_daily_manual', 'per_day_manual', 'extra_manual'):
                    extra_daily = _parse_money(price_adjustment.get('amount'))
                    # If reducing days, diff_days is 0, so no refund? 
                    # User likely wants to ADD this amount per EXTRA day.
                    # If simply changing price per day, that's different.
                    # Assuming this is "Add R$ X for each extra day"
                    diff_days = max(0, new_days - old_days)
                    new_total = current_amount + (extra_daily * diff_days)
                elif ptype in ('auto', 'automatic'):
                    new_total = avg_daily * new_days
            
            # Fallback: auto recalculation if dates changed and NO explicit manual total set
            if new_total is None and (checkin or checkout):
                # If we just moved dates but kept duration, keep price? 
                # If duration changed, recalc?
                # "Bug1 ... nao esta ajustando o valor" suggests they expect recalc.
                if new_days != old_days:
                    new_total = avg_daily * new_days
                else:
                    # If days count is same, keep current amount unless explicit auto requested
                    # But if we are here, it means NO price_adjustment was passed (or type unknown)
                    # Let's be conservative: only change if days changed.
                    new_total = current_amount
            
            if new_total is not None:
                fin = entry.get('financial', {})
                fin['amount'] = f"{new_total:.2f}"
                
                # Preserve paid amount if any (prefer override > original)
                # If paid_amount is already in fin, keep it. Else use original.
                if 'paid_amount' not in fin or fin.get('paid_amount') is None:
                     fin['paid_amount'] = f"{paid_amount:.2f}"
                else:
                    # If it IS in fin, ensure it's formatted
                    p_val = _parse_money(fin['paid_amount'])
                    fin['paid_amount'] = f"{p_val:.2f}"
                    paid_amount = p_val # Update for calculation below

                # Calculate To Receive
                try:
                    total_val = float(fin['amount']) # It's already .2f string
                    to_recv = max(0.0, total_val - paid_amount)
                except:
                    to_recv = max(0.0, new_total - paid_amount)
                    
                fin['to_receive'] = f"{to_recv:.2f}"
                entry['financial'] = fin
        except Exception as e:
            # Log error but don't crash
            print(f"Error calculating financial overrides for {reservation_id}: {str(e)}")
            pass
        
        allocations[str(reservation_id)] = entry
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.MANUAL_ALLOCATIONS_FILE), exist_ok=True)
        
        with open(self.MANUAL_ALLOCATIONS_FILE, 'w') as f:
            json.dump(allocations, f, indent=2)

    def update_financial_overrides(self, reservation_id, info):
        import json
        allocations = self.get_manual_overrides()
        entry = allocations.get(str(reservation_id), {})
        if isinstance(entry, str):
            entry = {'room': entry}
        fin = entry.get('financial', {})
        for key in ['amount', 'paid_amount', 'to_receive', 'status', 'channel']:
            if key in info and info.get(key) is not None:
                fin[key] = str(info.get(key))
        entry['financial'] = fin
        allocations[str(reservation_id)] = entry
        os.makedirs(os.path.dirname(self.MANUAL_ALLOCATIONS_FILE), exist_ok=True)
        with open(self.MANUAL_ALLOCATIONS_FILE, 'w') as f:
            json.dump(allocations, f, indent=2)
        return fin

    def merge_overrides_into_reservation(self, res_id, res, overrides_cache=None):
        if overrides_cache is not None:
            allocs = overrides_cache
        else:
            allocs = self.get_manual_overrides()
            
        entry = allocs.get(str(res_id))
        
        # Merge overrides if they exist
        if entry and isinstance(entry, dict):
            # Dates overrides
            cin = entry.get('checkin') or res.get('checkin')
            cout = entry.get('checkout') or res.get('checkout')
            if cin: res['checkin'] = cin
            if cout: res['checkout'] = cout
            
            # Financial overrides
            fin = entry.get('financial') or {}
            for k in ['amount', 'paid_amount', 'to_receive', 'status', 'channel']:
                if fin.get(k) is not None:
                    res[k] = fin.get(k)
                    # Update numeric helpers if they exist
                    if k == 'amount':
                        try:
                            res['amount_val'] = float(str(fin.get(k)).replace(',', '.'))
                        except:
                            pass
                    if k == 'paid_amount':
                        try:
                            res['paid_amount_val'] = float(str(fin.get(k)).replace(',', '.'))
                        except:
                            pass

        # Calculate Avg Daily Paid (ALWAYS, regardless of overrides)
        try:
            d_in = datetime.strptime(res.get('checkin'), '%d/%m/%Y')
            d_out = datetime.strptime(res.get('checkout'), '%d/%m/%Y')
            days = max(1, (d_out - d_in).days)
            
            paid_val = res.get('paid_amount')
            if isinstance(paid_val, (int, float)):
                paid = float(paid_val)
            else:
                # Clean currency formatting if string
                paid_str = str(paid_val or '0').replace('R$', '').replace(' ', '')
                if ',' in paid_str and '.' in paid_str:
                     # e.g. 1.200,50 -> 1200.50
                     paid_str = paid_str.replace('.', '').replace(',', '.')
                elif ',' in paid_str:
                     paid_str = paid_str.replace(',', '.')
                paid = float(paid_str)
                
            res['avg_daily_paid'] = round(paid / days, 2)
        except Exception:
            res['avg_daily_paid'] = 0.0
        
        # Calculate Avg Daily Total (Total Amount / Days)
        try:
            d_in = datetime.strptime(res.get('checkin'), '%d/%m/%Y')
            d_out = datetime.strptime(res.get('checkout'), '%d/%m/%Y')
            days = max(1, (d_out - d_in).days)
            
            total_val = res.get('amount')
            if isinstance(total_val, (int, float)):
                total = float(total_val)
            else:
                # Clean currency formatting if string
                total_str = str(total_val or '0').replace('R$', '').replace(' ', '')
                if ',' in total_str and '.' in total_str:
                        # e.g. 1.200,50 -> 1200.50
                        total_str = total_str.replace('.', '').replace(',', '.')
                elif ',' in total_str:
                        total_str = total_str.replace(',', '.')
                total = float(total_str)
            
            res['avg_daily_total'] = round(total / days, 2)
        except Exception:
            res['avg_daily_total'] = 0.0
        
        return res
    def check_collision(self, reservation_id, room_number, checkin_str, checkout_str, occupancy_data=None):
        try:
            new_checkin = datetime.strptime(checkin_str, '%d/%m/%Y')
            new_checkout = datetime.strptime(checkout_str, '%d/%m/%Y')
        except ValueError:
            raise ValueError("Formato de data inválido. Use DD/MM/YYYY.")

        # 1. Check Occupancy (Checked-in guests)
        if occupancy_data:
            # We need to know who is the guest of the current reservation to avoid self-collision
            current_res = self.get_reservation_by_id(reservation_id)
            current_guest = current_res.get('guest_name') if current_res else None
            
            for r_num, data in occupancy_data.items():
                try:
                    r_num_fmt = f"{int(r_num):02d}"
                except:
                    r_num_fmt = str(r_num)
                
                if r_num_fmt == str(room_number):
                    # If the occupant is the same guest, allow it (Assuming it's the same reservation)
                    # This is heuristic, but safe for now.
                    if current_guest and data.get('guest_name') == current_guest:
                        continue
                        
                    occ_in = datetime.strptime(data['checkin'], '%d/%m/%Y')
                    occ_out = datetime.strptime(data['checkout'], '%d/%m/%Y')
                    
                    # Overlap logic:
                    # If new_checkin < occ_out AND new_checkout > occ_in
                    if new_checkin < occ_out and new_checkout > occ_in:
                         raise ValueError(f"Quarto {room_number} ocupado por {data.get('guest_name')} ({data.get('checkin')} - {data.get('checkout')})")

        # 2. Check other reservations (Manual or Auto if we could, but let's stick to Manual Priority logic)
        # Actually, we should check against ALL reservations to be safe.
        all_reservations = self.get_february_reservations()
        
        for res in all_reservations:
            if str(res['id']) == str(reservation_id):
                continue
            
            # Determine effective dates
            m_checkin, m_checkout = self.get_manual_dates(res['id'])
            eff_checkin_str = m_checkin if m_checkin else res['checkin']
            eff_checkout_str = m_checkout if m_checkout else res['checkout']
            
            try:
                eff_checkin = datetime.strptime(eff_checkin_str, '%d/%m/%Y')
                eff_checkout = datetime.strptime(eff_checkout_str, '%d/%m/%Y')
            except:
                continue
                
            # Determine effective room
            # Priority: Manual > None (we don't check auto-allocated because manual bumps auto)
            # Wait! If another reservation is ALSO Manually allocated to this room, that's a collision.
            manual_room = self.get_manual_room(res['id'])
            
            if manual_room and str(manual_room) == str(room_number):
                # Check overlap
                if new_checkin < eff_checkout and new_checkout > eff_checkin:
                    raise ValueError(f"Conflito com reserva de {res['guest_name']} no quarto {room_number} ({eff_checkin_str} - {eff_checkout_str})")

    def calculate_reservation_update(self, reservation_id, new_room=None, new_checkin=None, new_checkout=None):
        """
        Calculates price difference and validates moves/resizes.
        Returns a dict with validation status and price info.
        """
        result = {
            'valid': True,
            'conflict_message': None,
            'old_total': 0.0,
            'new_total': 0.0,
            'diff': 0.0,
            'days': 0,
            'old_days': 0,
            'avg_daily': 0.0
        }

        try:
            res = self.get_reservation_by_id(reservation_id)
            if not res:
                return {'valid': False, 'conflict_message': "Reserva não encontrada."}
                
            current_checkin_str = res.get('checkin')
            current_checkout_str = res.get('checkout')
            current_amount = float(res.get('amount_val', 0.0))
            
            # Determine effective new dates
            target_checkin_str = new_checkin if new_checkin else current_checkin_str
            target_checkout_str = new_checkout if new_checkout else current_checkout_str
            
            # Determine effective new room
            # If new_room is provided, use it. If not, use current allocated room (or manual override).
            current_manual_room = self.get_manual_room(reservation_id)
            current_allocated_room = res.get('allocated_room')
            
            # Priority: New Room > Current Manual > Current Allocated > None
            target_room = new_room if new_room else (current_manual_room if current_manual_room else current_allocated_room)
            
            # 1. Date Validation
            try:
                d_in = datetime.strptime(target_checkin_str, '%d/%m/%Y')
                d_out = datetime.strptime(target_checkout_str, '%d/%m/%Y')
                days = (d_out - d_in).days
            except ValueError:
                return {'valid': False, 'conflict_message': "Datas inválidas."}
                
            if days < 1:
                return {'valid': False, 'conflict_message': "Período inválido (mínimo 1 diária)."}
            
            # 2. Collision Check
            # We need occupancy data to check collisions properly.
            # Assuming occupancy_data is passed or loaded. 
            # Ideally, we should load it here if not provided, but checking collision is expensive if we reload every time.
            # Let's load it here for safety as this is a critical validation step.
            from app.services.data_service import load_room_occupancy
            occupancy_data = load_room_occupancy()
            
            try:
                if target_room:
                    self.check_collision(reservation_id, target_room, target_checkin_str, target_checkout_str, occupancy_data)
            except ValueError as e:
                 return {'valid': False, 'conflict_message': str(e)}

            # 3. Capacity Check
            if target_room:
                 try:
                     r_key = f"{int(target_room):02d}"
                 except:
                     r_key = str(target_room)
                     
                 cap = self.ROOM_CAPACITIES.get(r_key, 2)
                 
                 # Check guest details for count (if available)
                 # details = self.get_guest_details(reservation_id)
                 # guest_count = details.get('guest_count', 2) # Default 2?
                 # if guest_count > cap:
                 #    return {'valid': False, 'conflict_message': f"Capacidade do quarto {target_room} excedida ({cap} pessoas)."}
                 pass

            # 4. Price Calculation
            # Determine effective current dates (for avg calculation)
            try:
                c_in = datetime.strptime(current_checkin_str, '%d/%m/%Y')
                c_out = datetime.strptime(current_checkout_str, '%d/%m/%Y')
                current_days = (c_out - c_in).days
                if current_days < 1: current_days = 1
            except:
                current_days = 1
                
            avg_daily = current_amount / current_days
            new_total = avg_daily * days
            
            result.update({
                'old_total': current_amount,
                'new_total': new_total,
                'diff': new_total - current_amount,
                'days': days,
                'old_days': current_days,
                'avg_daily': avg_daily
            })
            
            return result

        except Exception as e:
            return {'valid': False, 'conflict_message': f"Erro interno: {str(e)}"}


            
    def get_manual_room(self, reservation_id):
        allocs = self.get_manual_overrides()
        val = allocs.get(str(reservation_id))
        if isinstance(val, dict):
            return val.get('room')
        return val # Handle legacy string format if any
        
    def get_manual_dates(self, reservation_id):
        allocs = self.get_manual_overrides()
        val = allocs.get(str(reservation_id))
        if isinstance(val, dict):
            return val.get('checkin'), val.get('checkout')
        return None, None

    def allocate_reservations(self, grid, reservations, start_date, num_days):
        mapping = self.get_room_mapping()
        
        # Normalize mapping keys for easier matching
        norm_mapping = {k.lower().strip(): v for k, v in mapping.items()}
        
        range_end = start_date + pd.Timedelta(days=num_days - 1)

        for res in reservations:
            # Skip if already cancelled
            if str(res.get('status')).lower() == 'cancelado':
                res['allocated'] = False
                continue

            # Parse dates
            try:
                # Check for Manual Date Overrides
                m_checkin, m_checkout = self.get_manual_dates(res.get('id', ''))
                
                if m_checkin and m_checkout:
                    checkin = datetime.strptime(m_checkin, '%d/%m/%Y')
                    checkout = datetime.strptime(m_checkout, '%d/%m/%Y')
                    # Update reservation object with overrides so frontend sees them
                    res['checkin'] = m_checkin
                    res['checkout'] = m_checkout
                    res['is_date_overridden'] = True
                else:
                    checkin = datetime.strptime(res['checkin'], '%d/%m/%Y')
                    checkout = datetime.strptime(res['checkout'], '%d/%m/%Y')
            except (ValueError, TypeError):
                res['allocated'] = False
                continue

            # Check if reservation overlaps with range
            if checkout < start_date or checkin > range_end:
                # Not in range, but mark as not allocated? 
                # If it's outside range, we don't care about allocating it for THIS view.
                # But we should probably mark it false to be safe.
                res['allocated'] = False
                continue

            # Calculate required slots (indices)
            required_slots = []
            
            curr = checkin
            while curr <= checkout:
                if start_date <= curr <= range_end:
                    day_offset = (curr - start_date).days
                    day_idx = day_offset * 2
                    
                    # If checkin day, only PM occupied
                    if curr == checkin:
                        required_slots.append(day_idx + 1)
                    # If checkout day, only AM occupied
                    elif curr == checkout:
                        required_slots.append(day_idx)
                    # Middle days, both occupied
                    else:
                        required_slots.append(day_idx)
                        required_slots.append(day_idx + 1)
                
                curr = datetime(curr.year, curr.month, curr.day) + pd.Timedelta(days=1)

            # Filter out valid slots only (should be handled by if condition, but safety check)
            required_slots = [s for s in required_slots if 0 <= s < (num_days * 2)]

            if not required_slots:
                 res['allocated'] = False
                 continue

            # Check Manual Allocation First
            res_id = str(res.get('id', ''))
            allocated_room = None
            
            manual_room = self.get_manual_room(res_id)
            
            if manual_room:
                is_free = True
                if manual_room not in grid: grid[manual_room] = {}
                
                for slot in required_slots:
                    # If status is occupied (checked-in), we CANNOT override
                    if grid[manual_room].get(slot, {}).get('status') == 'occupied':
                        is_free = False
                        break
                
                if is_free:
                    allocated_room = manual_room

            # If not manually allocated or manual allocation failed, try auto
            if not allocated_room:
                cat = str(res.get('category', '')).lower().strip()
                candidates = []
                
                if cat in norm_mapping:
                    candidates = norm_mapping[cat]
                else:
                    for k, v in norm_mapping.items():
                        if k in cat or cat in k:
                            candidates = v
                            break
                
                if not candidates:
                    res['allocated'] = False
                    continue
                
                # Try to find a room
                for room in candidates:
                    is_free = True
                    if room not in grid: grid[room] = {}
                
                    for slot in required_slots:
                        if slot in grid[room]:
                            is_free = False
                            break
                
                    if is_free:
                        allocated_room = room
                        break
            
            if allocated_room:
                res['allocated'] = True
                res['allocated_room'] = allocated_room
                
                # Mark in grid
                if allocated_room not in grid: grid[allocated_room] = {}
                for slot in required_slots:
                    grid[allocated_room][slot] = {
                        'status': 'reserved',
                        'guest': res['guest_name'],
                        'checkin': res['checkin'],
                        'checkout': res['checkout'],
                        'category': res['category'],
                        'payment_status': res['status'],
                        'channel': res['channel'],
                        'amount': res.get('amount', ''),
                        'paid_amount': res.get('paid_amount', ''),
                        'to_receive': res.get('to_receive', ''),
                        'id': res.get('id', '')
                    }
            else:
                res['allocated'] = False
            
        return grid

    def get_occupancy_grid(self, occupancy, start_date, num_days):
        """
        Generates a grid of occupancy for the given range using half-day slots.
        Slot 0 = start_date AM, Slot 1 = start_date PM, ...
        Returns: {room_num: {slot_index: {'status': 'occupied', ...}}}
        """
        grid = {}
        
        for raw_room_num, data in occupancy.items():
            try:
                room_num = f"{int(raw_room_num):02d}"
            except (ValueError, TypeError):
                room_num = str(raw_room_num)

            grid[room_num] = {}
            
            try:
                checkin_str = data.get('checkin')
                checkout_str = data.get('checkout')
                
                if not checkin_str or not checkout_str:
                    continue
                    
                checkin = datetime.strptime(checkin_str, '%d/%m/%Y')
                checkout = datetime.strptime(checkout_str, '%d/%m/%Y')
                
                # Calculate intersection with requested range
                range_end = start_date + pd.Timedelta(days=num_days - 1)
                
                if checkout < start_date or checkin > range_end:
                    continue
                
                curr = checkin
                while curr <= checkout:
                    if start_date <= curr <= range_end:
                        # Calculate slot relative to start_date
                        day_offset = (curr - start_date).days
                        day_idx = day_offset * 2
                        
                        slots_to_fill = []
                        if curr == checkin:
                            slots_to_fill.append(day_idx + 1) # Checkin PM
                        elif curr == checkout:
                            slots_to_fill.append(day_idx) # Checkout AM
                        else:
                            slots_to_fill.append(day_idx)
                            slots_to_fill.append(day_idx + 1)
                            
                        for slot in slots_to_fill:
                            if 0 <= slot < (num_days * 2):
                                grid[room_num][slot] = {
                                    'status': 'occupied',
                                    'guest': data.get('guest_name'),
                                    'checkin': checkin_str,
                                    'checkout': checkout_str
                                }
                            
                    curr = datetime(curr.year, curr.month, curr.day) + pd.Timedelta(days=1)
                        
            except ValueError:
                continue
        return grid

    def auto_pre_allocate(self, window_hours=24):
        """
        Auto pre-allocate rooms for upcoming reservations (within window).
        Returns list of actions performed.
        """
        actions = []
        reservations = self.get_february_reservations()
        grid = {} # Temporary grid for collision check
        occupancy = {} # Load actual occupancy? We should pass it or load it.
        # Ideally we load current occupancy to avoid allocating to currently occupied rooms
        from app.services.data_service import load_room_occupancy
        occupancy_data = load_room_occupancy()
        
        # Build current grid state
        # We need a range? Let's say today + 7 days
        start_date = datetime.now()
        start_date = datetime(start_date.year, start_date.month, start_date.day)
        
        grid = self.get_occupancy_grid(occupancy_data, start_date, 7)
        # We also need to mark already allocated reservations in this grid
        # But allocate_reservations does that.
        
        # Filter reservations starting soon
        target_reservations = []
        now = datetime.now()
        
        for res in reservations:
            try:
                checkin = datetime.strptime(res['checkin'], '%d/%m/%Y')
                # If checkin is within window (e.g. today or tomorrow)
                # and NOT already manually allocated
                diff_hours = (checkin - now).total_seconds() / 3600
                # Relaxed window: -24h to +window_hours (allow today's past checkins too)
                if -24 <= diff_hours <= window_hours:
                    if not self.get_manual_room(res['id']):
                        target_reservations.append(res)
            except: continue
            
        if not target_reservations:
            return []
            
        # Re-run allocation logic for these specific targets
        # But we need to respect EXISTING allocations.
        # So we should run full allocation first? 
        # Actually, allocate_reservations does auto-allocation.
        # We just want to "PIN" (save) the result of auto-allocation for these specific ones.
        
        # Let's run full allocation simulation
        # Note: allocate_reservations modifies the reservations list IN PLACE by adding 'allocated' and 'allocated_room'
        self.allocate_reservations(grid.copy(), reservations, start_date, 7)
        
        # Now check where our target reservations ended up
        for res in reservations: # Iterate original list because 'res' in target_reservations is a copy/ref
             # Check if this res ID is in our target list
             is_target = any(t['id'] == res['id'] for t in target_reservations)
             if is_target:
                 if res.get('allocated') and res.get('allocated_room'):
                     # It was auto-allocated! Let's save it as manual to "PIN" it.
                     room = res['allocated_room']
                     self.save_manual_allocation(res['id'], room_number=room)
                     actions.append(f"Pré-alocação: {res['guest_name']} -> Quarto {room}")
        
        return actions

    def get_upcoming_checkins(self):
        """Returns list of reservations checking in today/tomorrow with allocated rooms."""
        reservations = self.get_february_reservations()
        upcoming = []
        now = datetime.now()
        today = datetime(now.year, now.month, now.day)
        
        # Ensure we have allocation info
        from app.services.data_service import load_room_occupancy
        occupancy = load_room_occupancy()
        grid = self.get_occupancy_grid(occupancy, today, 3)
        self.allocate_reservations(grid, reservations, today, 3)
        
        for res in reservations:
            try:
                checkin = datetime.strptime(res['checkin'], '%d/%m/%Y')
                if (checkin - today).days in [0, 1]: # Today or Tomorrow
                     if res.get('allocated') and res.get('allocated_room'):
                         upcoming.append({
                             'id': res.get('id'),
                             'room': res['allocated_room'],
                             'guest': res['guest_name'],
                             'checkin': res['checkin'],
                             'status': 'allocated'
                         })
            except: continue
            
        return upcoming

    def get_gantt_segments(self, grid, start_date, num_days):
        """
        Converts the daily grid (half-day slots) into a list of segments for each room.
        Returns: {room_num: [{'type': 'empty'|'reserved'|'occupied', 'length': int, 'data': ...}, ...]}
        """
        total_slots = num_days * 2
        segments = {}
        
        for room, slots_data in grid.items():
            room_segments = []
            current_segment = None
            
            for i in range(total_slots):
                cell = slots_data.get(i)
                
                if cell:
                    # Unique signature
                    cell_signature = (cell.get('status'), cell.get('guest'), cell.get('checkin'))
                    
                    if current_segment and current_segment['signature'] == cell_signature:
                        current_segment['length'] += 1
                    else:
                        if current_segment:
                            room_segments.append(current_segment)
                        
                        current_segment = {
                            'type': cell.get('status'),
                            'length': 1,
                            'signature': cell_signature,
                            'data': cell.copy()
                        }
                        # Inject start_slot (index)
                        current_segment['data']['start_day'] = i

                else:
                    # Empty slot
                    # Check if we should break empty segment at day boundary (Midnight)
                    # i is current slot. If i is even (0, 2, 4...), it's AM (Start of Day).
                    # If we have a current empty segment, it means it ends at i-1 (PM/Midnight).
                    # We want to close it to render the vertical grid line.
                    
                    should_break = (i % 2 == 0) and current_segment and current_segment['type'] == 'empty'
                    
                    if current_segment and current_segment['type'] == 'empty' and not should_break:
                        current_segment['length'] += 1
                    else:
                        if current_segment:
                            room_segments.append(current_segment)
                        current_segment = {
                            'type': 'empty',
                            'length': 1,
                            'signature': 'empty',
                            'data': {'start_day': i}
                        }
            
            if current_segment:
                room_segments.append(current_segment)
            
            segments[room] = room_segments
            
        return segments
