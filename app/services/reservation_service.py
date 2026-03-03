import pandas as pd
import os
import sys
from datetime import datetime
import re
from app.services.system_config_manager import (
    MANUAL_ALLOCATIONS_FILE, GUEST_DETAILS_FILE, 
    MANUAL_RESERVATIONS_FILE, RESERVATIONS_DIR
)
from app.services.cashier_service import file_lock

class ReservationService:
    RESERVATIONS_DIR = RESERVATIONS_DIR
    RESERVATIONS_FILE = os.path.join(RESERVATIONS_DIR, "minhas_reservas.xlsx")
    MANUAL_RESERVATIONS_FILE = MANUAL_RESERVATIONS_FILE
    RESERVATION_STATUS_OVERRIDES_FILE = os.path.join(RESERVATIONS_DIR, "reservation_status_overrides.json")
    
    RESERVATION_PAYMENTS_FILE = os.path.join(RESERVATIONS_DIR, "reservation_payments.json")

    def get_reservation_payments(self):
        import json
        if not os.path.exists(self.RESERVATION_PAYMENTS_FILE):
            return {}
        try:
            with file_lock(self.RESERVATION_PAYMENTS_FILE):
                with open(self.RESERVATION_PAYMENTS_FILE, 'r') as f:
                    return json.load(f)
        except:
            return {}

    def save_reservation_payment(self, reservation_id, payment_data):
        import json
        with file_lock(self.RESERVATION_PAYMENTS_FILE):
            if os.path.exists(self.RESERVATION_PAYMENTS_FILE):
                try:
                    with open(self.RESERVATION_PAYMENTS_FILE, 'r') as f:
                        payments = json.load(f)
                except:
                    payments = {}
            else:
                payments = {}
                
            if reservation_id not in payments:
                payments[reservation_id] = []
            
            payments[reservation_id].append(payment_data)
            
            with open(self.RESERVATION_PAYMENTS_FILE, 'w') as f:
                json.dump(payments, f, indent=4)

    def get_reservation_by_id(self, reservation_id):
        # Check Manual
        manual = self.get_manual_reservations_data()
        for i, res in enumerate(manual):
            rid = str(res.get('id'))
            target = str(reservation_id)
            if rid == target:
                res['source_type'] = 'manual'
                return res
        
        # Check Main Excel
        if os.path.exists(self.RESERVATIONS_FILE):
            items = self._parse_excel_file(self.RESERVATIONS_FILE)
            for item in items:
                if str(item.get('id')) == str(reservation_id):
                    item['source_type'] = 'excel'
                    return item
                    
        # Check other Excel files in directory
        if os.path.exists(self.RESERVATIONS_DIR):
            for f in os.listdir(self.RESERVATIONS_DIR):
                if (f.endswith('.xlsx') or f.endswith('.xls')) and f != os.path.basename(self.RESERVATIONS_FILE):
                    items = self._parse_excel_file(os.path.join(self.RESERVATIONS_DIR, f))
                    for item in items:
                        if str(item.get('id')) == str(reservation_id):
                            item['source_type'] = 'excel'
                            return item
        return None

    def add_payment(self, reservation_id, amount, payment_details):
        # print(f"DEBUG: add_payment id={reservation_id} amount={amount}")
        res = self.get_reservation_by_id(reservation_id)
        if not res:
            raise ValueError("Reserva não encontrada")
            
        # Record payment in sidecar
        self.save_reservation_payment(reservation_id, {
            'amount': amount,
            'date': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'details': payment_details
        })
        
        # print(f"DEBUG: add_payment source_type={res.get('source_type')}")
        
        # If manual, update the file directly too for consistency
        if res.get('source_type') == 'manual':
            self.update_manual_reservation_payment(reservation_id, amount)

    def update_manual_reservation_payment(self, reservation_id, amount):
        import json
        # print(f"DEBUG: update_manual_reservation_payment id={reservation_id} amount={amount}")
        if not os.path.exists(self.MANUAL_RESERVATIONS_FILE):
            # print("DEBUG: MANUAL_RESERVATIONS_FILE not found")
            return
            
        with file_lock(self.MANUAL_RESERVATIONS_FILE):
            with open(self.MANUAL_RESERVATIONS_FILE, 'r') as f:
                data = json.load(f)
                
            changed = False
            found = False
            for item in data:
                if str(item.get('id')) == str(reservation_id):
                    found = True
                    try:
                        val_str = str(item.get('paid_amount', '0')).strip()
                        if ',' in val_str:
                            # Assume BR format: 1.000,00
                            current_paid = float(val_str.replace('R$', '').replace('.', '').replace(',', '.'))
                        else:
                            # Assume standard format: 1000.00
                            current_paid = float(val_str.replace('R$', ''))
                    except:
                        current_paid = 0.0
                        
                    new_paid = current_paid + float(amount)
                    item['paid_amount'] = f"{new_paid:.2f}"
                    # print(f"DEBUG: Updating paid_amount from {current_paid} to {new_paid}")
                    
                    # Update remaining if needed
                    try:
                        total_str = str(item.get('amount', '0')).strip()
                        if ',' in total_str:
                            total = float(total_str.replace('R$', '').replace('.', '').replace(',', '.'))
                        else:
                            total = float(total_str.replace('R$', ''))
                    except:
                        total = 0.0
                        
                    item['to_receive'] = f"{max(0, total - new_paid):.2f}"
                    changed = True
                    break
            
            if not found:
                pass
                # print(f"DEBUG: Reservation ID {reservation_id} not found in file")
            
            if changed:
                with open(self.MANUAL_RESERVATIONS_FILE, 'w') as f:
                    json.dump(data, f, indent=2)
                # print("DEBUG: File updated")

    def get_guest_details(self, reservation_id):
        import json
        
        # 1. Try to load from Guest Details File
        details = {}
        if os.path.exists(GUEST_DETAILS_FILE):
            try:
                with file_lock(GUEST_DETAILS_FILE):
                    with open(GUEST_DETAILS_FILE, 'r', encoding='utf-8') as f:
                        all_details = json.load(f)
                        details = all_details.get(str(reservation_id), {})
            except Exception as e:
                print(f"Error loading guest details: {e}")
        
        # 2. If empty, try to populate from Reservation
        if not details:
            res = self.get_reservation_by_id(reservation_id)
            if res:
                details = {
                    'personal_info': {
                        'name': res.get('guest_name', ''),
                        'email': '',
                        'phone': '',
                        'cpf': '',
                        'address': '',
                        'city': '',
                        'state': '',
                        'zip': '',
                        'country': ''
                    },
                    'history': [],
                    'companions': []
                }
        
        # Ensure structure
        if 'personal_info' not in details:
            details['personal_info'] = {}
        
        # If we have reservation but name is missing in details, sync it
        if 'name' not in details['personal_info'] or not details['personal_info']['name']:
             res = self.get_reservation_by_id(reservation_id)
             if res:
                 details['personal_info']['name'] = res.get('guest_name', '')
                 
        return details

    def update_guest_details(self, reservation_id, updates):
        """
        Updates guest details for a reservation.
        Updates 'guest_name' in MANUAL_RESERVATIONS_FILE.
        Updates other fields in GUEST_DETAILS_FILE.
        """
        import json
        
        success = False
        
        # 1. Update Manual Reservation (if name changed)
        if 'guest_name' in updates:
            if os.path.exists(self.MANUAL_RESERVATIONS_FILE):
                with file_lock(self.MANUAL_RESERVATIONS_FILE):
                    try:
                        with open(self.MANUAL_RESERVATIONS_FILE, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        
                        changed = False
                        for item in data:
                            if str(item.get('id')) == str(reservation_id):
                                item['guest_name'] = updates['guest_name']
                                changed = True
                        
                        if changed:
                            with open(self.MANUAL_RESERVATIONS_FILE, 'w', encoding='utf-8') as f:
                                json.dump(data, f, indent=4, ensure_ascii=False)
                            success = True
                    except Exception as e:
                        print(f"Error updating manual reservation: {e}")
        
        # 2. Update Extended Details in GUEST_DETAILS_FILE
        try:
            with file_lock(GUEST_DETAILS_FILE):
                all_details = {}
                if os.path.exists(GUEST_DETAILS_FILE):
                    try:
                        with open(GUEST_DETAILS_FILE, 'r', encoding='utf-8') as f:
                            all_details = json.load(f)
                    except:
                        all_details = {}
                
                # Get existing or create new
                current_details = all_details.get(str(reservation_id), {})
                
                # Ensure structure
                if 'personal_info' not in current_details:
                    current_details['personal_info'] = {}
                if 'companions' not in current_details:
                    current_details['companions'] = []
                
                # Map specific fields if present at top level
                if 'guest_name' in updates:
                    current_details['personal_info']['name'] = updates['guest_name']
                if 'email' in updates:
                    current_details['personal_info']['email'] = updates['email']
                if 'phone' in updates:
                    current_details['personal_info']['phone'] = updates['phone']
                if 'cpf' in updates:
                    current_details['personal_info']['cpf'] = updates['cpf']
                if 'notes' in updates:
                    current_details['notes'] = updates['notes']
                    
                # Also support direct structured updates
                if 'personal_info' in updates:
                    current_details['personal_info'].update(updates['personal_info'])
                
                if 'companions' in updates:
                    current_details['companions'] = updates['companions']
                    
                all_details[str(reservation_id)] = current_details
                
                with open(GUEST_DETAILS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(all_details, f, indent=4, ensure_ascii=False)
                
                success = True
        except Exception as e:
            print(f"Error updating guest details file: {e}")
            
        return success

    def auto_pre_allocate(self, window_hours=48):
        """
        Placeholder for auto pre-allocation logic.
        Returns a list of actions taken.
        """
        # print(f"DEBUG: auto_pre_allocate window_hours={window_hours}")
        return []

    def save_manual_allocation(self, reservation_id, room_number, checkin, checkout, occupancy_data=None):
        import json
        # print(f"DEBUG: save_manual_allocation id={reservation_id} room={room_number}")
        
        manual_alloc_file = os.path.join(self.RESERVATIONS_DIR, "manual_allocations.json")
        
        with file_lock(manual_alloc_file):
            allocations = {}
            if os.path.exists(manual_alloc_file):
                try:
                    with open(manual_alloc_file, 'r') as f:
                        allocations = json.load(f)
                except:
                    allocations = {}
            
            allocations[str(reservation_id)] = {"room": str(room_number)}
            
            with open(manual_alloc_file, 'w') as f:
                json.dump(allocations, f, indent=2)
            
        # print(f"DEBUG: Manual allocation saved for {reservation_id} -> {room_number}")

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
        with file_lock(self.RESERVATION_STATUS_OVERRIDES_FILE):
            overrides = {}
            if os.path.exists(self.RESERVATION_STATUS_OVERRIDES_FILE):
                try:
                    with open(self.RESERVATION_STATUS_OVERRIDES_FILE, 'r') as f:
                        overrides = json.load(f)
                except:
                    overrides = {}

            overrides[str(reservation_id)] = new_status
            
            with open(self.RESERVATION_STATUS_OVERRIDES_FILE, 'w') as f:
                json.dump(overrides, f, indent=4)
            
    def get_manual_reservations_data(self):
        import json
        # print(f"DEBUG: Reading manual reservations from {self.MANUAL_RESERVATIONS_FILE}")
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
        
        print(f"DEBUG: create_manual_reservation data={data}")
        
        amount_val = data.get('amount')
        if not amount_val:
            amount_val = data.get('total_value')
        if not amount_val:
            amount_val = '0.00'

        new_res = {
            'id': str(uuid.uuid4()),
            'guest_name': data.get('guest_name'),
            'checkin': data.get('checkin'), # DD/MM/YYYY
            'checkout': data.get('checkout'), # DD/MM/YYYY
            'category': data.get('category', 'Manual'),
            'status': data.get('status', 'Pendente'),
            'channel': data.get('channel', 'Direto'),
            'amount': str(amount_val),
            'paid_amount': str(data.get('paid_amount', '0.00')),
            'to_receive': str(data.get('to_receive', '0.00')),
            'created_at': datetime.now().strftime('%d/%m/%Y %H:%M')
        }
        
        print(f"DEBUG: create_manual_reservation new_res={new_res}")
        
        dir_name = os.path.dirname(self.MANUAL_RESERVATIONS_FILE)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
            
        with file_lock(self.MANUAL_RESERVATIONS_FILE):
            reservations = []
            if os.path.exists(self.MANUAL_RESERVATIONS_FILE):
                try:
                    with open(self.MANUAL_RESERVATIONS_FILE, 'r') as f:
                        reservations = json.load(f)
                        if not isinstance(reservations, list): reservations = []
                except:
                    reservations = []
            
            reservations.append(new_res)
            
            with open(self.MANUAL_RESERVATIONS_FILE, 'w') as f:
                json.dump(reservations, f, indent=2)
            
        return new_res

    def get_february_reservations(self):
        """
        Retrieves all active reservations from Manual and Excel sources.
        Originally named for a specific month, now returns all relevant reservations.
        """
        # Load Manual
        manual = self.get_manual_reservations_data()
        
        # Load Excel
        excel_items = []
        if os.path.exists(self.RESERVATIONS_FILE):
             excel_items.extend(self._parse_excel_file(self.RESERVATIONS_FILE))
        
        if os.path.exists(self.RESERVATIONS_DIR):
             for f in os.listdir(self.RESERVATIONS_DIR):
                 if (f.endswith('.xlsx') or f.endswith('.xls')) and f != os.path.basename(self.RESERVATIONS_FILE):
                     try:
                        excel_items.extend(self._parse_excel_file(os.path.join(self.RESERVATIONS_DIR, f)))
                     except: pass
        
        # Apply overrides to all items (manual + excel)
        overrides = self.get_reservation_status_overrides()
        for item in manual:
            rid = str(item.get('id'))
            if rid in overrides:
                item['status'] = overrides[rid]
        for item in excel_items:
            rid = str(item.get('id'))
            if rid in overrides:
                item['status'] = overrides[rid]
        
        # Merge - prefer manual if duplicate IDs? 
        # Usually manual and excel are distinct sets or manual overrides excel?
        # For now, just concatenate.
        return manual + excel_items

    def get_room_mapping(self):
        """
        Returns a dictionary mapping categories to lists of room numbers.
        """
        # Hardcoded based on ROOM_CAPACITIES knowledge or derived
        return {
            "Suíte Areia": ["01", "02", "03"],
            "Suíte Mar Família": ["11"],
            "Suíte Mar": ["12", "14", "15", "16", "17", "21", "22", "23", "24", "25", "26"],
            "Suíte Alma c/ Banheira": ["31", "35"],
            "Suíte Alma": ["32", "34"],
            "Suíte Master Diamante": ["33"]
        }

    def get_occupancy_grid(self, occupancy_data, start_date, num_days):
        """
        Initializes an empty grid for the given date range.
        grid[room] = [slot0, slot1, ...]
        Each day has 2 slots (AM/PM).
        """
        grid = {}
        total_slots = num_days * 2
        
        # All known rooms
        all_rooms = []
        mapping = self.get_room_mapping()
        for rooms in mapping.values():
            all_rooms.extend(rooms)
            
        for room in all_rooms:
            grid[room] = [None] * total_slots
            
        return grid

    def allocate_reservations(self, grid, reservations, start_date, num_days):
        """
        Places reservations into the grid.
        Resolves room allocation based on manual allocations or category matching.
        """
        import json
        from datetime import timedelta
        
        # Load Manual Allocations
        manual_allocs = {}
        manual_alloc_file = os.path.join(self.RESERVATIONS_DIR, "manual_allocations.json")
        if os.path.exists(manual_alloc_file):
            try:
                with open(manual_alloc_file, 'r') as f:
                    manual_allocs = json.load(f)
            except: pass

        # Sort reservations to prioritize fixed allocations?
        # Or just process all.
        
        mapping = self.get_room_mapping()
        # Invert mapping for easy lookup
        room_to_cat = {}
        for cat, rooms in mapping.items():
            for r in rooms:
                room_to_cat[r] = cat

        for res in reservations:
            try:
                # Parse dates
                # Checkin format: DD/MM/YYYY or YYYY-MM-DD
                cin_str = res.get('checkin')
                cout_str = res.get('checkout')
                
                if not cin_str or not cout_str: continue
                
                try:
                    if '-' in cin_str:
                        cin = datetime.strptime(cin_str, '%Y-%m-%d')
                    else:
                        cin = datetime.strptime(cin_str, '%d/%m/%Y')
                        
                    if '-' in cout_str:
                        cout = datetime.strptime(cout_str, '%Y-%m-%d')
                    else:
                        cout = datetime.strptime(cout_str, '%d/%m/%Y')
                except: continue
                
                # Calculate slots relative to start_date
                # Start Date 00:00 is Slot 0 (Day 1 AM)
                # Checkin usually 14:00 -> Slot 1 (Day 1 PM)
                # Checkout usually 12:00 -> Slot 0 (Day 2 AM) - wait, next day AM.
                
                # Logic:
                # Day Delta = (Date - StartDate).days
                # Checkin Slot = DayDelta * 2 + 1 (PM)
                # Checkout Slot = DayDelta * 2 (AM) (Exclusive? No, inclusive of that morning?)
                # A stay from Day 1 to Day 2:
                # Day 1 PM (Slot 1)
                # Day 2 AM (Slot 2)
                # Checkout is at Day 2 AM. So it occupies Slot 2.
                # Next guest checks in Day 2 PM (Slot 3).
                
                start_delta = (cin - start_date).days
                end_delta = (cout - start_date).days
                
                # Range of slots
                # Start: start_delta * 2 + 1
                # End: end_delta * 2
                # Example: 1st to 2nd.
                # Start 1st (delta 0) -> Slot 1.
                # End 2nd (delta 1) -> Slot 2.
                # Range: [1, 2] (inclusive)
                
                start_slot = start_delta * 2 + 1
                end_slot = end_delta * 2
                
                # Clip to grid range
                total_slots = num_days * 2
                if end_slot < 0 or start_slot >= total_slots:
                    continue
                    
                # Effective range
                eff_start = max(0, start_slot)
                eff_end = min(total_slots - 1, end_slot)
                
                if eff_start > eff_end: continue
                
                # Determine Room
                res_id = str(res.get('id'))
                allocated_room = None
                
                # 1. Check Manual Allocation
                if res_id in manual_allocs:
                    allocated_room = manual_allocs[res_id].get('room')
                
                # 2. Check if reservation has room field (some manual ones might)
                if not allocated_room and res.get('room'):
                    allocated_room = res.get('room')
                    
                # 3. If not allocated, try to find empty room in category
                if not allocated_room:
                    cat = res.get('category', 'Unknown')
                    # Normalize category string?
                    # Try exact match first
                    candidates = mapping.get(cat, [])
                    if not candidates:
                         # Try partial match
                         for k, v in mapping.items():
                             if cat.lower() in k.lower() or k.lower() in cat.lower():
                                 candidates = v
                                 break
                    
                    # Find first free room
                    for room in candidates:
                        is_free = True
                        if room not in grid: continue
                        for s in range(eff_start, eff_end + 1):
                            if grid[room][s] is not None:
                                is_free = False
                                break
                        if is_free:
                            allocated_room = room
                            break
                            
                # Place in grid if room found/assigned
                if allocated_room and allocated_room in grid:
                    # Check conflicts if forced
                    # We just overwrite for now or mark conflict?
                    # The grid stores the reservation object
                    
                    # Store simple dict or full res?
                    # Store dict with needed info
                    cell_data = {
                        'id': res_id,
                        'guest': res.get('guest_name'),
                        'checkin': cin.strftime('%d/%m/%Y'),
                        'checkout': cout.strftime('%d/%m/%Y'),
                        'category': res.get('category'),
                        'payment_status': res.get('status'),
                        'channel': res.get('channel'),
                        'amount': res.get('amount'),
                        'paid_amount': res.get('paid_amount'),
                        'to_receive': res.get('to_receive')
                    }
                    
                    for s in range(eff_start, eff_end + 1):
                        if grid[allocated_room][s] is None:
                            grid[allocated_room][s] = cell_data
                        else:
                            # Conflict!
                            # Could store list of collisions?
                            # For visualization, maybe just overwrite or mark conflict
                            # Let's keep the existing one or overwrite?
                            # If we overwrite, we lose the previous one.
                            # Maybe we shouldn't have placed it if occupied.
                            # But if it was manually allocated, we force it.
                            pass
                            
            except Exception as e:
                print(f"Error allocating reservation {res.get('id')}: {e}")
                continue
                
        return grid

    def get_gantt_segments(self, grid, start_date, num_days):
        """
        Converts the grid into segments for the UI.
        Returns: { 'room': [ {type, length, data}, ... ] }
        """
        segments = {}
        total_slots = num_days * 2
        
        for room, slots in grid.items():
            room_segments = []
            current_res_id = None
            current_start = 0
            current_data = None
            
            for i in range(total_slots):
                cell = slots[i]
                cell_id = cell['id'] if cell else None
                
                if cell_id != current_res_id:
                    # End previous segment
                    if current_start < i:
                        length = i - current_start
                        
                        seg_type = 'empty'
                        if current_res_id:
                            status = str(current_data.get('payment_status', '')).lower()
                            if 'checked-in' in status or 'hospedado' in status or 'ocupado' in status:
                                seg_type = 'occupied'
                            else:
                                seg_type = 'reserved'
                        
                        seg_data = current_data if current_res_id else {'start_day': current_start}
                        if current_res_id:
                            # Add start_day to data for UI
                            seg_data['start_day'] = current_start
                        
                        room_segments.append({
                            'type': seg_type,
                            'length': length,
                            'data': seg_data
                        })
                    
                    # Start new segment
                    current_res_id = cell_id
                    current_start = i
                    current_data = cell
            
            # End last segment
            if current_start < total_slots:
                length = total_slots - current_start
                
                seg_type = 'empty'
                if current_res_id:
                    status = str(current_data.get('payment_status', '')).lower()
                    if 'checked-in' in status or 'hospedado' in status or 'ocupado' in status:
                        seg_type = 'occupied'
                    else:
                        seg_type = 'reserved'
                        
                seg_data = current_data if current_res_id else {'start_day': current_start}
                if current_res_id:
                    seg_data['start_day'] = current_start
                    
                room_segments.append({
                    'type': seg_type,
                    'length': length,
                    'data': seg_data
                })
                
            segments[room] = room_segments
            
        return segments

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
            return filtered
        except:
            return []
