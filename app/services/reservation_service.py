
import pandas as pd
import os
from datetime import datetime
import re

class ReservationService:
    RESERVATIONS_DIR = r"F:\Reservas FEV"
    RESERVATIONS_FILE = r"F:\Reservas FEV\minhas_reservas.xlsx" 

    MANUAL_RESERVATIONS_FILE = r"f:\Sistema Almareia Mirapraia\data\manual_reservations.json"

    def get_manual_reservations_data(self):
        import json
        if not os.path.exists(self.MANUAL_RESERVATIONS_FILE):
            return []
        try:
            with open(self.MANUAL_RESERVATIONS_FILE, 'r') as f:
                data = json.load(f)
                if isinstance(data, list): return data
                return []
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
            
            for file_path in files:
                try:
                    df = pd.read_excel(file_path)
                    
                    # Columns: 'Estabelecimento', 'Id', 'Responsável', 'Checkin/out', 'Categoria', 
                    # 'Status do pagamento', 'Canais', 'Valor', 'Valor pago', 'Valor a receber'
                    
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
                        
                        # Deduplicate by ID if necessary? 
                        # If same ID exists in multiple files, we might have duplicates.
                        # Let's assume files are distinct chunks or we should handle dedup.
                        # For now, just append.
                        
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
    
                        all_reservations.append({
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
                            'to_receive_val': parse_br_money(to_receive_str)
                        })
                        
                except Exception as e:
                    print(f"Error reading reservations Excel {file_path}: {e}")
                    continue
        
        # Deduplicate based on ID (keep last found?)
        
        # Deduplicate based on ID (keep last found?)
        unique_reservations = {}
        for res in all_reservations:
            if res['id']:
                unique_reservations[res['id']] = res
            else:
                # No ID? append with random key or ignore? 
                # If no ID, we can't track it well.
                import uuid
                unique_reservations[str(uuid.uuid4())] = res
                
        return list(unique_reservations.values())

    def get_room_mapping(self):
        return {
            "Suíte Areia": ["01", "02", "03"],
            "Suíte Mar Família": ["11"],
            "Suíte Mar": ["12", "14", "15", "16", "17", "21", "22", "23", "24", "25", "26"],
            "Suíte Alma c/ Banheira": ["31", "35"],
            "Suíte Alma": ["32", "34"],
            "Suíte Master Diamante": ["33"]
        }

    MANUAL_ALLOCATIONS_FILE = r"f:\Sistema Almareia Mirapraia\data\manual_allocations.json"
    GUEST_DETAILS_FILE = r"f:\Sistema Almareia Mirapraia\data\guest_details.json"

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
            
        if room_number:
            entry['room'] = str(room_number)
        if price_adjustment:
            entry['price_adjustment'] = price_adjustment
        if checkin:
            entry['checkin'] = checkin
        if checkout:
            entry['checkout'] = checkout
            
        allocations[str(reservation_id)] = entry
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.MANUAL_ALLOCATIONS_FILE), exist_ok=True)
        
        with open(self.MANUAL_ALLOCATIONS_FILE, 'w') as f:
            json.dump(allocations, f, indent=2)

    def check_collision(self, reservation_id, room_number, checkin_str, checkout_str, occupancy_data=None):
        try:
            new_checkin = datetime.strptime(checkin_str, '%d/%m/%Y')
            new_checkout = datetime.strptime(checkout_str, '%d/%m/%Y')
        except ValueError:
            raise ValueError("Formato de data inválido. Use DD/MM/YYYY.")

        # 1. Check Occupancy (Checked-in guests)
        if occupancy_data:
            for r_num, data in occupancy_data.items():
                try:
                    r_num_fmt = f"{int(r_num):02d}"
                except:
                    r_num_fmt = str(r_num)
                
                if r_num_fmt == str(room_number):
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
