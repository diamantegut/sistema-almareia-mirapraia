import json
import os
import hashlib
import uuid
from datetime import datetime, timedelta
from app.services.guest_manager import guest_manager

class PreCheckinService:
    def __init__(self, data_dir='data'):
        self.data_dir = data_dir
        self.links_file = os.path.join(data_dir, 'pre_checkin_links.json')
        self.manual_allocations_file = os.path.join(data_dir, 'manual_allocations.json')
        self._ensure_file()

    def _ensure_file(self):
        if not os.path.exists(self.links_file):
            with open(self.links_file, 'w') as f:
                json.dump({}, f)
        
        # Ensure allocations file exists too (if not already)
        if not os.path.exists(self.manual_allocations_file):
            with open(self.manual_allocations_file, 'w') as f:
                json.dump({}, f)

    def _load_links(self):
        try:
            with open(self.links_file, 'r') as f:
                return json.load(f)
        except:
            return {}

    def _save_links(self, links):
        with open(self.links_file, 'w') as f:
            json.dump(links, f, indent=4)

    def generate_link(self, reservation_id, room_number=None, guest_name=None):
        """
        Generates a unique pre-checkin link for a reservation.
        """
        links = self._load_links()
        
        # Check if active link exists
        for token, data in links.items():
            if data.get('reservation_id') == str(reservation_id) and data.get('status') == 'pending':
                # Check expiration
                expires = datetime.strptime(data['expires_at'], '%Y-%m-%d %H:%M:%S')
                if expires > datetime.now():
                    return token

        # Generate new token
        raw_str = f"{reservation_id}{datetime.now().timestamp()}{uuid.uuid4()}"
        token = hashlib.sha256(raw_str.encode()).hexdigest()[:32] # 32 chars is enough
        
        expires_at = datetime.now() + timedelta(days=7)
        
        links[token] = {
            "reservation_id": str(reservation_id),
            "room_number": str(room_number) if room_number else None,
            "guest_name": guest_name,
            "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "expires_at": expires_at.strftime('%Y-%m-%d %H:%M:%S'),
            "status": "pending"
        }
        
        self._save_links(links)
        return token

    def validate_token(self, token):
        """
        Validates token and returns reservation data if valid.
        """
        links = self._load_links()
        data = links.get(token)
        
        if not data:
            return None, "Link inválido."
            
        if data['status'] != 'pending':
            return None, "Link já utilizado ou expirado."
            
        expires = datetime.strptime(data['expires_at'], '%Y-%m-%d %H:%M:%S')
        if datetime.now() > expires:
            data['status'] = 'expired'
            self._save_links(links)
            return None, "Link expirado."
            
        # Fetch existing guest data if available
        # We try to find if there is already a guest file linked to this reservation
        guest = guest_manager.get_guest_by_reservation(data['reservation_id'])
        
        return {
            "link_data": data,
            "guest_data": guest
        }, None

    def complete_pre_checkin(self, token, form_data, files=None):
        """
        Processes the pre-checkin form submission.
        """
        links = self._load_links()
        link_data = links.get(token)
        
        if not link_data or link_data['status'] != 'pending':
            return False, "Link inválido ou expirado."

        reservation_id = link_data['reservation_id']
        
        # 1. Update/Create Guest File
        # Check if guest exists
        guest = guest_manager.get_guest_by_reservation(reservation_id)
        
        # Parse Minors from form data (minors[index][field])
        minors_dict = {}
        for key, value in form_data.items():
            if key.startswith('minors['):
                try:
                    # expected format: minors[0][name]
                    parts = key.replace(']', '').split('[')
                    if len(parts) == 3:
                        idx = int(parts[1])
                        field = parts[2]
                        if idx not in minors_dict:
                            minors_dict[idx] = {}
                        minors_dict[idx][field] = value
                except:
                    continue
        
        minors_list = [minors_dict[i] for i in sorted(minors_dict.keys())]

        personal_info = {
            "name": form_data.get('name'),
            "surname": form_data.get('surname'),
            "phone": form_data.get('phone'),
            "email": form_data.get('email'),
            "cpf": form_data.get('cpf'),
            "rg": form_data.get('rg'),
            "nationality": form_data.get('nationality'),
            "marital_status": form_data.get('marital_status'),
            "birth_date": form_data.get('birth_date'),
            "vehicle": form_data.get('vehicle') == 'on',
            "minors": minors_list
        }

        if personal_info['vehicle']:
            personal_info['vehicle_details'] = {
                'brand': form_data.get('vehicle_brand'),
                'model': form_data.get('vehicle_model'),
                'plate': form_data.get('vehicle_plate')
            }
        
        address_info = {
            "street": form_data.get('street'),
            "number": form_data.get('number'),
            "neighborhood": form_data.get('neighborhood'),
            "city": form_data.get('city'),
            "state": form_data.get('state'),
            "zip_code": form_data.get('zip_code'),
            "country": form_data.get('country', 'Brasil'),
            "complement": form_data.get('complement')
        }
        
        # Merge address into personal_info or keep separate? 
        # GuestManager structure has personal_info. Let's put address there for now or update GuestManager structure.
        # Looking at GuestManager v2.0 in memory/code:
        # fiscal_info has "address". personal_info usually has basics.
        # I'll populate both where appropriate.
        
        personal_info['address'] = address_info # Add nested address
        
        stay_info = {
            "room_number": link_data.get('room_number'),
            "reservation_id": reservation_id,
            # We assume checkin/out dates come from reservation or form
            "checkin_date": form_data.get('checkin_date'),
            "checkout_date": form_data.get('checkout_date')
        }
        
        if guest:
            guest_id = guest['id']
            guest_manager.update_guest_info(guest_id, 'personal_info', personal_info)
            # Update fiscal info too
            fiscal_update = {
                "cpf": form_data.get('cpf'),
                "address": f"{address_info['street']}, {address_info['number']} - {address_info['city']}/{address_info['state']}"
            }
            guest_manager.update_guest_info(guest_id, 'fiscal_info', fiscal_update)
        else:
            # Create new guest
            guest_id = guest_manager.create_guest(personal_info, stay_info, reservation_id=reservation_id)
            # Update fiscal info immediately
            fiscal_update = {
                "cpf": form_data.get('cpf'),
                "address": f"{address_info['street']}, {address_info['number']} - {address_info['city']}/{address_info['state']}"
            }
            guest_manager.update_guest_info(guest_id, 'fiscal_info', fiscal_update)

        # 2. Handle Files (Documents)
        if files:
            doc_dir = os.path.join(self.data_dir, 'secure_docs', guest_id)
            os.makedirs(doc_dir, exist_ok=True)
            
            saved_docs = []
            # Handle both list (if multiple files passed) or dict-like (if named fields passed, e.g. request.files)
            file_list = []
            if isinstance(files, list):
                file_list = files
            elif hasattr(files, 'values'):
                file_list = list(files.values())
            
            for file in file_list:
                if file and hasattr(file, 'filename') and file.filename:
                    ext = os.path.splitext(file.filename)[1].lower()
                    if ext in ['.jpg', '.jpeg', '.png', '.pdf']:
                        safe_name = f"doc_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}{ext}"
                        path = os.path.join(doc_dir, safe_name)
                        file.save(path)
                        saved_docs.append(safe_name)
            
            if saved_docs:
                guest_manager.update_guest_info(guest_id, 'documents', {'files': saved_docs})

        # 3. Mark Link as Completed
        link_data['status'] = 'completed'
        link_data['completed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        link_data['guest_id'] = guest_id
        self._save_links(links)
        
        return True, "Pré-check-in realizado com sucesso!"

pre_checkin_service = PreCheckinService()
