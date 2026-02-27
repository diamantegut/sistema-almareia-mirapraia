import pandas as pd
import os
import sys
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
    
    RESERVATION_PAYMENTS_FILE = os.path.join(RESERVATIONS_DIR, "reservation_payments.json")

    def get_reservation_payments(self):
        import json
        if not os.path.exists(self.RESERVATION_PAYMENTS_FILE):
            return {}
        try:
            with open(self.RESERVATION_PAYMENTS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}

    def save_reservation_payment(self, reservation_id, payment_data):
        import json
        payments = self.get_reservation_payments()
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
        print(f"DEBUG: add_payment id={reservation_id} amount={amount}")
        res = self.get_reservation_by_id(reservation_id)
        if not res:
            raise ValueError("Reserva não encontrada")
            
        # Record payment in sidecar
        self.save_reservation_payment(reservation_id, {
            'amount': amount,
            'date': datetime.now().strftime('%d/%m/%Y %H:%M'),
            'details': payment_details
        })
        
        print(f"DEBUG: add_payment source_type={res.get('source_type')}")
        
        # If manual, update the file directly too for consistency
        if res.get('source_type') == 'manual':
            self.update_manual_reservation_payment(reservation_id, amount)

    def update_manual_reservation_payment(self, reservation_id, amount):
        import json
        print(f"DEBUG: update_manual_reservation_payment id={reservation_id} amount={amount}")
        if not os.path.exists(self.MANUAL_RESERVATIONS_FILE):
            print("DEBUG: MANUAL_RESERVATIONS_FILE not found")
            return
            
        with open(self.MANUAL_RESERVATIONS_FILE, 'r') as f:
            data = json.load(f)
            
        changed = False
        found = False
        for item in data:
            if str(item.get('id')) == str(reservation_id):
                found = True
                try:
                    current_paid = float(str(item.get('paid_amount', '0')).replace('R$', '').replace('.', '').replace(',', '.'))
                except:
                    current_paid = 0.0
                    
                new_paid = current_paid + float(amount)
                item['paid_amount'] = f"{new_paid:.2f}"
                print(f"DEBUG: Updating paid_amount from {current_paid} to {new_paid}")
                
                # Update remaining if needed
                try:
                    total = float(str(item.get('amount', '0')).replace('R$', '').replace('.', '').replace(',', '.'))
                except:
                    total = 0.0
                    
                item['to_receive'] = f"{max(0, total - new_paid):.2f}"
                changed = True
                break
        
        if not found:
            print(f"DEBUG: Reservation ID {reservation_id} not found in file")
        
        if changed:
            with open(self.MANUAL_RESERVATIONS_FILE, 'w') as f:
                json.dump(data, f, indent=2)
            print("DEBUG: File updated")

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
        reservations = self.get_manual_reservations_data()
        
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
            return filtered
        except:
            return []
