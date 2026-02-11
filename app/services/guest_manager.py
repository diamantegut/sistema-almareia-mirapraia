import json
import os
import uuid
from datetime import datetime
from cryptography.fernet import Fernet

class GuestManager:
    def __init__(self, data_dir='data'):
        self.data_dir = data_dir
        # New structure root
        self.hospedes_root = os.path.join(data_dir, 'Hospedes')
        # Legacy for backward compatibility
        self.guests_dir = os.path.join(data_dir, 'guests_encrypted')
        
        self.key_file = os.path.join(data_dir, 'secret.key')
        self.index_file = os.path.join(data_dir, 'guest_index.json')
        
        self._ensure_dir()
        self._load_key()
        self._load_index()
        self._load_sequence()

    def _ensure_dir(self):
        if not os.path.exists(self.guests_dir):
            os.makedirs(self.guests_dir)
        if not os.path.exists(self.hospedes_root):
            os.makedirs(self.hospedes_root)

    def _load_key(self):
        if not os.path.exists(self.key_file):
            self.key = Fernet.generate_key()
            with open(self.key_file, 'wb') as key_file:
                key_file.write(self.key)
        else:
            with open(self.key_file, 'rb') as key_file:
                self.key = key_file.read()
        self.cipher_suite = Fernet(self.key)

    def _load_index(self):
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, 'r') as f:
                    self.index = json.load(f)
            except:
                self.index = {}
        else:
            self.index = {}

    def _save_index(self):
        with open(self.index_file, 'w') as f:
            json.dump(self.index, f, indent=4)

    def _get_file_path(self, guest_id):
        # Check index first
        if guest_id in self.index:
            rel_path = self.index[guest_id]
            return os.path.join(self.data_dir, rel_path)
        
        # Fallback to legacy path logic check
        legacy_path = os.path.join(self.guests_dir, f"{guest_id}.enc")
        if os.path.exists(legacy_path):
            return legacy_path
            
        return legacy_path # Default for new if not indexed (shouldn't happen with create_guest)

    def _determine_path(self, checkin_date_str):
        # checkin_date_str expected format: YYYY-MM-DD or DD/MM/YYYY
        try:
            if '-' in checkin_date_str:
                date_obj = datetime.strptime(checkin_date_str, "%Y-%m-%d")
            else:
                date_obj = datetime.strptime(checkin_date_str, "%d/%m/%Y")
        except:
            date_obj = datetime.now()
            
        path = os.path.join('Hospedes', date_obj.strftime("%Y"), date_obj.strftime("%m"), date_obj.strftime("%d"))
        full_path = os.path.join(self.data_dir, path)
        if not os.path.exists(full_path):
            os.makedirs(full_path)
        return path

    def _save_guest(self, guest_id, data):
        """Encrypts and saves guest data."""
        file_path = self._get_file_path(guest_id)
        # Ensure dir exists for the file path (in case it's new and path generated but dir not made?)
        # _determine_path makes the dir, so we are good.
        
        json_data = json.dumps(data, ensure_ascii=False)
        encrypted_data = self.cipher_suite.encrypt(json_data.encode('utf-8'))
        with open(file_path, 'wb') as f:
            f.write(encrypted_data)

    def _load_sequence(self):
        seq_file = os.path.join(self.data_dir, 'guest_sequence.json')
        if os.path.exists(seq_file):
            try:
                with open(seq_file, 'r') as f:
                    data = json.load(f)
                    self.sequence = data.get('last_sequence', 0)
            except:
                self.sequence = 0
        else:
            self.sequence = 0

    def _get_next_sequence(self):
        self.sequence += 1
        seq_file = os.path.join(self.data_dir, 'guest_sequence.json')
        with open(seq_file, 'w') as f:
            json.dump({'last_sequence': self.sequence}, f)
        return self.sequence

    def create_guest(self, personal_info, stay_info, reservation_id=None):
        """
        Creates a new guest file with comprehensive structure.
        """
        guest_id = str(uuid.uuid4())
        
        # Determine path based on check-in
        checkin = stay_info.get('checkin_date', datetime.now().strftime("%Y-%m-%d"))
        rel_dir = self._determine_path(checkin)
        rel_path = os.path.join(rel_dir, f"{guest_id}.enc")
        
        self.index[guest_id] = rel_path
        self._save_index()
        
        # Get next sequence
        ficha_number = self._get_next_sequence()
        
        guest_data = {
            "id": guest_id,
            "ficha_number": ficha_number,
            "personal_info": personal_info,
            "stay_info": {
                "room_number": stay_info.get('room_number'),
                "checkin_date": stay_info.get('checkin_date'),
                "checkout_date": stay_info.get('checkout_date'),
                "status": "active",
                "checked_in_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "reservation_id": str(reservation_id) if reservation_id else None
            },
            "fiscal_info": {
                "competence_date": datetime.now().strftime("%d/%m/%Y"),
                "borrower_type": "cpf", # cpf, cnpj, foreigner
                "cpf": "",
                "cnpj": "",
                "foreigner_passport": "",
                "foreigner_country": "",
                "address": "",
                "municipal_activity": "090101",
                "nbs": "103031100",
                "indicator": "030101",
                "tax_classification": "200048",
                "situation_code": "200",
                "municipality": "Tamandaré",
                "activity_type": "09.01"
            },
            "financials": {
                "daily_rate": 0.0,
                "paid_amount": 0.0,
                "amount_due": 0.0,
                "payments": [],
                "pending_charges": [],
                "balance": 0.0,
                "taxes": {
                    "federal_rate": 15.46,
                    "municipal_rate": 5.00
                }
            },
            "operational_info": {
                "breakfast_time_start": "",
                "breakfast_time_end": "",
                "dietary_restrictions": [],
                "allergies": "",
                "commemorative_dates": []
            },
            "orders": [],
            "metadata": {
                "created_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "version": "2.0"
            }
        }
        
        self._save_guest(guest_id, guest_data)
        return guest_id

    def get_guest(self, guest_id):
        """Retrieves guest data."""
        file_path = self._get_file_path(guest_id)
        if not os.path.exists(file_path):
            return None
        
        try:
            with open(file_path, 'rb') as f:
                encrypted_data = f.read()
            decrypted_data = self.cipher_suite.decrypt(encrypted_data)
            return json.loads(decrypted_data.decode('utf-8'))
        except Exception as e:
            print(f"Error loading guest {guest_id}: {e}")
            return None

    def get_guest_by_reservation(self, reservation_id):
        """Finds a guest by reservation ID."""
        # Check index first (fastest if mapped)
        # Since we don't map reservation_id in index yet, iterate.
        
        # 1. Iterate through index (Active guests)
        for guest_id in self.index:
            guest = self.get_guest(guest_id)
            if guest and str(guest.get('stay_info', {}).get('reservation_id')) == str(reservation_id):
                return guest
                
        # 2. Fallback: Iterate legacy directory if not found (Migration support)
        if os.path.exists(self.guests_dir):
            for filename in os.listdir(self.guests_dir):
                if filename.endswith('.enc'):
                    guest_id = filename.replace('.enc', '')
                    if guest_id not in self.index: # Avoid double checking
                        guest = self.get_guest(guest_id)
                        if guest and str(guest.get('stay_info', {}).get('reservation_id')) == str(reservation_id):
                            # Auto-index for future
                            self.index[guest_id] = os.path.join('guests_encrypted', filename)
                            self._save_index()
                            return guest
        return None

    def get_history_by_doc(self, doc_id):
        """Finds all stays for a given document ID."""
        history = []
        if not doc_id:
            return history
            
        # Iterate all indexed guests
        for guest_id in self.index:
            guest = self.get_guest(guest_id)
            if guest:
                # Check personal info doc
                g_doc = guest.get('personal_info', {}).get('doc_id')
                # Check fiscal info doc
                f_doc = guest.get('fiscal_info', {}).get('cpf') or guest.get('fiscal_info', {}).get('cnpj') or guest.get('fiscal_info', {}).get('foreigner_passport')
                
                if (g_doc and str(g_doc) == str(doc_id)) or (f_doc and str(f_doc) == str(doc_id)):
                    # Add summary
                    stay = guest.get('stay_info', {})
                    history.append({
                        'guest_id': guest_id,
                        'checkin': stay.get('checkin_date'),
                        'checkout': stay.get('checkout_date'),
                        'room': stay.get('room_number'),
                        'status': stay.get('status')
                    })
        
        # Sort by checkin date descending
        try:
            history.sort(key=lambda x: datetime.strptime(x['checkin'], '%d/%m/%Y') if x['checkin'] else datetime.min, reverse=True)
        except:
            pass
            
        return history

    def save_document_photo(self, guest_id, file_storage):
        """Saves an uploaded document photo securely."""
        docs_dir = os.path.join(self.data_dir, 'secure_docs')
        if not os.path.exists(docs_dir):
            os.makedirs(docs_dir)
            
        ext = os.path.splitext(file_storage.filename)[1]
        filename = f"{guest_id}_doc_{uuid.uuid4().hex[:8]}{ext}"
        path = os.path.join(docs_dir, filename)
        file_storage.save(path)
        
        self.update_guest_info(guest_id, 'personal_info', {'document_photo_path': filename})
        return filename

    def update_guest_info(self, guest_id, section, data):
        """
        Updates a specific section of guest data.
        :param section: 'personal_info', 'stay_info', 'fiscal_info', 'financials', 'operational_info', etc.
        """
        guest = self.get_guest(guest_id)
        if not guest:
            return False

        # Allow creating standard sections if they don't exist (Migration support)
        valid_sections = ['fiscal_info', 'operational_info', 'financials', 'extra_data', 'personal_info', 'stay_info', 'documents']
        if section not in guest and section in valid_sections:
            guest[section] = {}

        if section in guest:
            guest[section].update(data)
            self._save_guest(guest_id, guest)
            return True
             
        return False

    def add_order(self, guest_id, order_data):
        """
        Adds a restaurant order to the guest's history.
        """
        guest = self.get_guest(guest_id)
        if not guest:
            return False

        if 'orders' not in guest:
            guest['orders'] = []

        guest['orders'].append(order_data)
        self._save_guest(guest_id, guest)
        return True

    def add_payment(self, guest_id, payment_data):
        """
        Records a payment.
        """
        guest = self.get_guest(guest_id)
        if not guest:
            return False

        payment_entry = {
            "id": str(uuid.uuid4()),
            "date": datetime.now().strftime("%d/%m/%Y"),
            "amount": payment_data.get('amount', 0.0),
            "method": payment_data.get('method', 'cash'),
            "description": payment_data.get('description', 'Payment')
        }

        guest['financials']['payments'].append(payment_entry)
        self._recalculate_balance(guest)
        self._save_guest(guest_id, guest)
        return True

    def checkout_guest(self, guest_id):
        """
        Finalizes the guest file upon checkout.
        """
        guest = self.get_guest(guest_id)
        if not guest:
            return False

        guest['stay_info']['status'] = 'checked_out'
        guest['stay_info']['checked_out_at'] = datetime.now().strftime("%d/%m/%Y %H:%M")
        
        self._save_guest(guest_id, guest)
        return True

    def _recalculate_balance(self, guest):
        total_charges = sum(c['amount'] for c in guest['financials']['pending_charges'] if c['status'] == 'pending')
        total_payments = sum(p['amount'] for p in guest['financials']['payments'])
        # Add Daily Rate if not in pending charges (depends on how daily rates are charged)
        # For now, we assume daily rates are added to pending_charges or tracked separately.
        # But for the "Amount Due" field logic:
        guest['financials']['paid_amount'] = total_payments
        guest['financials']['balance'] = total_charges - total_payments
        guest['financials']['amount_due'] = max(0, guest['financials']['balance'])

# Singleton instance for easy import
guest_manager = GuestManager()
